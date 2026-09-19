"""Static Git change review with external diff and text conversion disabled."""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .service import SnapshotStore, ThreadlineError, add_evidence_ids
from .analyzer import EXCLUDED, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def review_changes(root: str | Path, base: str = 'HEAD', files: list[str] | None = None, store: SnapshotStore | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    base_revision = _git(root, ['rev-parse', '--verify', '--end-of-options', base + '^{commit}'])
    statuses = _statuses(root, base_revision)
    if files is not None:
        allowed = {Path(name).as_posix() for name in files}
        statuses = [row for row in statuses if row['path'] in allowed or row.get('oldPath') in allowed]
    current_store = store or SnapshotStore(root); current = current_store.current
    source_roots = current['analysisOptions']['sourceRoots']
    exclusions = current['analysisOptions']['exclude']
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='threadline-base-') as directory:
        base_root = Path(directory).resolve()
        total_bytes = count = 0
        for name in (item for item in _git_z(root, ['ls-tree', '-r', '-z', '--name-only', base_revision]) if item.endswith('.py') or item == 'pyproject.toml'):
            target = base_root / name
            if target.is_absolute() and base_root not in target.resolve().parents:
                raise ThreadlineError('Git tree path escapes the baseline root')
            if name != 'pyproject.toml' and any(name == prefix or name.startswith(prefix + '/') for prefix in exclusions):
                continue
            if any(part in EXCLUDED for part in Path(name).parts): continue
            if name != 'pyproject.toml' and not any(prefix == '.' or name.startswith(prefix + '/') for prefix in source_roots): continue
            count += 1
            if time.monotonic() - started > 60: raise ThreadlineError('Baseline materialization exceeded 60 second budget')
            if count > MAX_FILES: raise ThreadlineError('Baseline file budget exceeded')
            size = int(_git(root, ['cat-file', '-s', f'{base_revision}:{name}']))
            total_bytes += size
            if size > MAX_FILE_BYTES or total_bytes > MAX_TOTAL_BYTES: raise ThreadlineError('Baseline byte budget exceeded')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_bytes(root, ['cat-file', 'blob', f'{base_revision}:{name}']))
        for value in source_roots:
            path = (base_root / value).resolve()
            if path != base_root and base_root not in path.parents: raise ThreadlineError('Invalid baseline source root')
            path.mkdir(parents=True, exist_ok=True)
        before_store = SnapshotStore(base_root, source_roots=source_roots, exclude=exclusions)
        before = before_store.refresh()
        if store: store.retain(before)
    statuses = _snapshot_statuses(before, current, statuses)
    if files is not None:
        statuses = [row for row in statuses if row['path'] in allowed or row.get('oldPath') in allowed]
    hunks = _hunks(before, current, statuses)
    changed_current, changed_before = [], []
    for row in statuses:
        path = row['path']
        new_lines = hunks.get(path, {}).get('new', [])
        old_path = row.get('oldPath', path)
        old_lines = hunks.get(path, {}).get('old', [])
        changed_current.extend(_affected(current, path, new_lines, row['status']))
        changed_before.extend(_affected(before, old_path, old_lines, row['status']))
    current_ids = {item['id'] for item in changed_current}
    callers = []
    for item in changed_current:
        for caller_id in current['scopes'][item['id']]['callers']:
            scope = current['scopes'][caller_id]
            callers.append(_scope_ref(scope, 'known source-linked caller'))
    # Baseline relationships stay separate: deleted targets cannot resolve in
    # the working snapshot, and line-based scope IDs can change after edits.
    previous_ids = {item['id'] for item in changed_before}
    baseline_callers = []
    caller_ids = {caller_id for target_id in previous_ids
                  for caller_id in before['scopes'][target_id]['callers']}
    for caller_id in sorted(caller_ids):
        scope = before['scopes'][caller_id]
        calls = []
        for node in _nodes(scope['flow']):
            for call in node['calls']:
                if call['status'] != 'supported':
                    continue
                for target_id in call['targets']:
                    if target_id in previous_ids:
                        calls.append(add_evidence_ids({
                            'span': call['span'],
                            'target': _scope_ref(before['scopes'][target_id], 'previous definition'),
                        }))
        if calls:
            row = _scope_ref(scope, 'historical source-linked caller; current resolution is not established')
            row.update(snapshotId=before['snapshotId'], calls=calls)
            baseline_callers.append(row)
    possible = []
    changed_names = {current['scopes'][item['id']]['name'] for item in changed_current}
    for scope in current['scopes'].values():
        if scope['id'] in current_ids: continue
        for node in _nodes(scope['flow']):
            if any(call['status'] == 'possible' and any(current['scopes'].get(t, {}).get('name') in changed_names for t in call['targets']) for call in node['calls']):
                possible.append(_scope_ref(scope, 'possible caller under static dispatch assumptions')); break
    return {'base': base, 'workingSnapshotId': current['snapshotId'], 'baseSnapshotId': before['snapshotId'],
            'files': statuses, 'changedMethods': _unique(changed_current), 'previousMethods': _unique(changed_before),
            'knownCallers': _unique(callers), 'baselineCallers': baseline_callers, 'possibleImpact': _unique(possible),
            'parseErrors': {'working': current['errors'], 'base': before['errors']},
            'notice': 'Changed methods are syntactic overlap. Callers are classified separately; reachability is not observed execution.'}


GIT_TIMEOUT_SECONDS = 30
MAX_GIT_BYTES = 64 * 1024 * 1024


def _git_bytes(root, args, *, allowed_codes=(0,)):
    # Spool output to disk so a large Git object cannot exhaust Python memory.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-c', 'diff.external=', *args],
                                    cwd=root, stdout=output, stderr=errors, timeout=GIT_TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ThreadlineError('Git query failed or exceeded its 30 second budget') from exc
        errors.seek(0)
        if result.returncode not in allowed_codes: raise ThreadlineError(errors.read(4096).decode(errors='replace').strip())
        if output.tell() > MAX_GIT_BYTES: raise ThreadlineError('Git output exceeds byte budget; narrow the comparison')
        output.seek(0)
        return output.read(MAX_GIT_BYTES + 1)


def _git(root, args):
    return _git_bytes(root, args).decode(errors='surrogateescape').strip()


def _git_z(root, args):
    raw = _git_bytes(root, args).decode(errors='surrogateescape')
    return [item for item in raw.split('\0') if item]

def _statuses(root, base):
    values = _git_z(root, ['diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '--find-renames', base, '--', '*.py'])
    rows=[]; index=0
    while index < len(values):
        status=values[index];index+=1
        if status.startswith(('R','C')):
            old,new=values[index:index+2];index+=2;rows.append({'status':status[0], 'oldPath':old, 'path':new})
        else:
            path=values[index];index+=1;rows.append({'status':status[0], 'path':path})
    tracked={row['path'] for row in rows}
    for path in _git_z(root, ['ls-files', '--others', '--exclude-standard', '-z', '--', '*.py']):
        if path not in tracked: rows.append({'status':'A', 'path':path, 'untracked':True})
    return rows

def _snapshot_statuses(before, current, hints):
    """Git supplies rename hints; analyzed bytes decide which paths actually changed."""
    old_files, new_files = before['files'], current['files']
    old_names = set(old_files) | {row['file'] for row in before['errors']}
    new_names = set(new_files) | {row['file'] for row in current['errors']}
    rows, claimed_old, claimed_new = [], set(), set()
    for hint in hints:
        old, new = hint.get('oldPath'), hint['path']
        if hint['status'] == 'R' and old in old_names - new_names and new in new_names - old_names:
            rows.append(hint); claimed_old.add(old); claimed_new.add(new)
    untracked = {row['path'] for row in hints if row.get('untracked')}
    for name in sorted(old_names | new_names):
        if name in claimed_old or name in claimed_new: continue
        if name not in old_names:
            rows.append({'status': 'A', 'path': name, **({'untracked': True} if name in untracked else {})})
        elif name not in new_names:
            rows.append({'status': 'D', 'path': name})
        elif old_files.get(name, {}).get('hash') != new_files.get(name, {}).get('hash'):
            rows.append({'status': 'M', 'path': name})
    return rows


def _hunks(before, current, statuses):
    # Diff the retained source bytes, never a working file that may have changed
    # after indexing. Fixed temporary filenames avoid quoted-path ambiguity.
    result = {}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='threadline-diff-') as directory:
        root = Path(directory)
        old_path, new_path = root / 'before.py', root / 'after.py'
        for row in statuses:
            if row['status'] in ('A', 'D'): continue
            if time.monotonic() - started > 60: raise ThreadlineError('Diff exceeded 60 second budget')
            old = before['files'].get(row.get('oldPath', row['path']))
            new = current['files'].get(row['path'])
            if old is None or new is None: continue  # Parse failures remain explicit in diagnostics.
            old_path.write_bytes(old['source'].encode('utf-8'))
            new_path.write_bytes(new['source'].encode('utf-8'))
            diff = _git_bytes(root, ['diff', '--no-index', '--no-ext-diff', '--no-textconv', '--unified=0', '--', str(old_path), str(new_path)], allowed_codes=(0, 1)).decode('utf-8', errors='replace')
            ranges = {'old': [], 'new': []}
            for line in diff.splitlines():
                match = HUNK.match(line)
                if not match: continue
                old_start, old_count, new_start, new_count = (int(match.group(1)), int(match.group(2) or 1), int(match.group(3)), int(match.group(4) or 1))
                ranges['old'].append((old_start, old_start + max(1, old_count) - 1))
                ranges['new'].append((new_start, new_start + max(1, new_count) - 1))
            result[row['path']] = ranges
    return result


def _affected(model, file, ranges, status):
    rows=[]
    for scope in model['scopes'].values():
        if scope['file'] != file or scope['kind'] in ('module','class'): continue
        if status == 'A' or not ranges or any(scope['span']['start'] <= end and start <= scope['span']['end'] for start,end in ranges):
            rows.append(_scope_ref(scope, 'changed source overlaps definition'))
    return rows

def _scope_ref(scope, reason):
    return add_evidence_ids({'id':scope['id'],'name':scope['qualified'],'file':scope['file'],'span':scope['span'],'reason':reason})
def _unique(rows):
    return list({(row['file'],row['name']):row for row in rows}.values())
def _nodes(flow):
    for node in flow:
        yield node
        for branch in node['branches']: yield from _nodes(branch['nodes'])
