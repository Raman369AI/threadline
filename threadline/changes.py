"""Static Git change review with external diff and text conversion disabled."""
from __future__ import annotations

import hashlib
import io
import re
import subprocess
import tempfile
import time
import tokenize
from pathlib import Path, PurePosixPath
from typing import Any

from .service import SnapshotStore, ThreadlineError, add_evidence_ids
from .analyzer import EXCLUDED, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .templates import (MAX_TEMPLATE_ASSETS, MAX_TEMPLATE_FILE_BYTES,
                        MAX_TEMPLATE_TOTAL_BYTES, TEMPLATE_SUFFIXES,
                        literal_template_names)

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def review_changes(root: str | Path, base: str = 'HEAD', files: list[str] | None = None, store: SnapshotStore | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    base_revision = _git(root, ['rev-parse', '--verify', '--end-of-options', base + '^{commit}'])
    statuses = _statuses(root, base_revision)
    if files is not None:
        allowed = {Path(name).as_posix() for name in files}
        statuses = [row for row in statuses if row['path'] in allowed or row.get('oldPath') in allowed]
    current_store = store or SnapshotStore(root)
    current = current_store.current
    source_roots = current['analysisOptions']['sourceRoots']
    exclusions = current['analysisOptions']['exclude']
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='threadline-base-') as directory:
        base_root = Path(directory).resolve()
        total_bytes = count = 0
        entries = []
        for record in _git_z(root, ['ls-tree', '-r', '-z', base_revision]):
            metadata, separator, name = record.partition('\t')
            fields = metadata.split()
            if not separator or len(fields) != 3:
                raise ThreadlineError('Git baseline tree entry is malformed')
            entries.append((name, fields[0]))

        def materialize(name, size_limit):
            nonlocal total_bytes, count
            target = base_root / name
            if target.is_absolute() and base_root not in target.resolve().parents:
                raise ThreadlineError('Git tree path escapes the baseline root')
            count += 1
            if time.monotonic() - started > 60: raise ThreadlineError('Baseline materialization exceeded 60 second budget')
            if count > MAX_FILES: raise ThreadlineError('Baseline file budget exceeded')
            size = int(_git(root, ['cat-file', '-s', f'{base_revision}:{name}']))
            total_bytes += size
            if size > size_limit or total_bytes > MAX_TOTAL_BYTES: raise ThreadlineError('Baseline byte budget exceeded')
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = _git_bytes(root, ['cat-file', 'blob', f'{base_revision}:{name}'])
            target.write_bytes(raw)
            return raw

        sources = {}
        for name, mode in entries:
            if mode not in ('100644', '100755') or not (name.endswith('.py') or name == 'pyproject.toml'):
                continue
            if name != 'pyproject.toml' and any(name == prefix or name.startswith(prefix + '/') for prefix in exclusions):
                continue
            if any(part in EXCLUDED for part in Path(name).parts): continue
            if name != 'pyproject.toml' and not any(prefix == '.' or name.startswith(prefix + '/') for prefix in source_roots): continue
            raw = materialize(name, MAX_FILE_BYTES)
            if name.endswith('.py') and b'TemplateResponse' in raw:
                try:
                    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                    sources[name] = raw.decode(encoding)
                except (SyntaxError, UnicodeError, LookupError):
                    pass

        template_names = literal_template_names(sources)
        template_parts = [PurePosixPath(name.replace('\\', '/')).parts
                          for name in template_names]
        template_count = template_bytes = 0
        for name, mode in entries:
            if mode not in ('100644', '100755') or not name.lower().endswith(TEMPLATE_SUFFIXES):
                continue  # Git symlinks and submodules are never materialized as source.
            parts = PurePosixPath(name).parts
            if not any(parts[-len(wanted):] == wanted for wanted in template_parts):
                continue
            if any(name == prefix or name.startswith(prefix + '/') for prefix in exclusions):
                continue
            if any(part in EXCLUDED for part in Path(name).parts):
                continue
            template_count += 1
            if template_count > MAX_TEMPLATE_ASSETS:
                raise ThreadlineError('Baseline template asset budget exceeded')
            size = int(_git(root, ['cat-file', '-s', f'{base_revision}:{name}']))
            template_bytes += size
            if template_bytes > MAX_TEMPLATE_TOTAL_BYTES:
                raise ThreadlineError('Baseline template byte budget exceeded')
            materialize(name, MAX_TEMPLATE_FILE_BYTES)
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
    renamed_current, renamed_before = [], []
    unassessed = []
    for row in statuses:
        path = row['path']
        new_lines = hunks.get(path, {}).get('new', [])
        old_path = row.get('oldPath', path)
        old_lines = hunks.get(path, {}).get('old', [])
        if path == 'pyproject.toml':
            unassessed.extend(_unassessed_changes(current, path, new_lines, row['status'], 'working'))
            unassessed.extend(_unassessed_changes(before, old_path, old_lines, row['status'], 'base'))
            continue
        if path.lower().endswith(TEMPLATE_SUFFIXES):
            unassessed.extend(_unassessed_changes(current, path, new_lines, row['status'], 'working'))
            unassessed.extend(_unassessed_changes(before, old_path, old_lines, row['status'], 'base'))
            continue
        if row['status'] == 'R' and not new_lines and not old_lines:
            renamed_current.extend(_affected(current, path, [], 'R', reason='definition moved without a source edit'))
            renamed_before.extend(_affected(before, old_path, [], 'R', reason='definition moved without a source edit'))
            continue
        changed_current.extend(_affected(current, path, new_lines, row['status']))
        changed_before.extend(_affected(before, old_path, old_lines, row['status']))
        unassessed.extend(_unassessed_changes(current, path, new_lines, row['status'], 'working'))
        unassessed.extend(_unassessed_changes(before, old_path, old_lines, row['status'], 'base'))
    current_ids = {item['id'] for item in changed_current + renamed_current}
    callers = []
    for scope in current['scopes'].values():
        if any(call['status'] == 'supported' and current_ids.intersection(call['targets'])
               for call in _reachable_calls(scope)):
            callers.append(_scope_ref(scope, 'known source-linked caller; execution is not established'))
    # Baseline relationships stay separate: deleted targets cannot resolve in
    # the working snapshot, and line-based scope IDs can change after edits.
    previous_ids = {item['id'] for item in changed_before + renamed_before}
    baseline_callers = []
    for scope in before['scopes'].values():
        calls = []
        for call in _reachable_calls(scope):
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
    for scope in current['scopes'].values():
        if scope['id'] in current_ids: continue
        if any(call['status'] == 'possible' and current_ids.intersection(call['targets'])
               for call in _reachable_calls(scope)):
            possible.append(_scope_ref(scope, 'possible caller under static dispatch assumptions'))
    changed_current = _unique(changed_current)
    changed_before = _unique(changed_before)
    renamed_current = _unique(renamed_current)
    renamed_before = _unique(renamed_before)
    _attach_counterparts(changed_current + renamed_current, current, before, statuses)
    _attach_counterparts(changed_before + renamed_before, before, current, statuses, reverse=True)
    if store:
        for side, snapshot_id in (('working', current['snapshotId']), ('base', before['snapshotId'])):
            if snapshot_id in store._models:
                store.register_change_evidence(snapshot_id, [row['span'] for row in unassessed
                                                             if row['side'] == side and 'span' in row])
    return {'base': base, 'workingSnapshotId': current['snapshotId'], 'baseSnapshotId': before['snapshotId'],
            'files': statuses, 'changedMethods': changed_current, 'previousMethods': changed_before,
            'renamedMethods': renamed_current, 'previousRenamedMethods': renamed_before,
            'unassessedChanges': unassessed,
            'knownCallers': _unique(callers), 'baselineCallers': baseline_callers, 'possibleImpact': _unique(possible),
            'parseErrors': {'working': current['errors'], 'base': before['errors']},
            'notice': 'Changed methods have syntactic source overlap; renamed methods have unchanged source at a new path. Caller lists show direct source relationships, not complete transitive or data-dependency impact. Runtime reachability is not established.'}


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
        if result.returncode not in allowed_codes:
            raise ThreadlineError(errors.read(4096).decode(errors='replace').strip())
        if output.tell() > MAX_GIT_BYTES:
            raise ThreadlineError('Git output exceeds byte budget; narrow the comparison')
        output.seek(0)
        return output.read(MAX_GIT_BYTES + 1)


def _git(root, args):
    return _git_bytes(root, args).decode(errors='surrogateescape').strip()


def _git_z(root, args):
    raw = _git_bytes(root, args).decode(errors='surrogateescape')
    return [item for item in raw.split('\0') if item]

def _statuses(root, base):
    pathspecs = ['*.py', 'pyproject.toml', *(f'*{suffix}' for suffix in TEMPLATE_SUFFIXES)]
    values = _git_z(root, ['diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '--find-renames', base, '--', *pathspecs])
    rows = []
    index = 0
    while index < len(values):
        status = values[index]
        index += 1
        if status.startswith(('R', 'C')):
            old, new = values[index:index + 2]
            index += 2
            rows.append({'status': status[0], 'oldPath': old, 'path': new})
        else:
            path = values[index]
            index += 1
            rows.append({'status': status[0], 'path': path})
    tracked = {row['path'] for row in rows}
    for path in _git_z(root, ['ls-files', '--others', '--exclude-standard', '-z', '--', *pathspecs]):
        if path not in tracked:
            rows.append({'status': 'A', 'path': path, 'untracked': True})
    return rows

def _snapshot_statuses(before, current, hints):
    """Git supplies rename hints; snapshot source state decides actual changes."""
    old_files, new_files = before['files'], current['files']
    old_manifest = before.get('discoveryManifest') or {name: {'hash': info['hash'], 'status': 'parsed'} for name, info in old_files.items()}
    new_manifest = current.get('discoveryManifest') or {name: {'hash': info['hash'], 'status': 'parsed'} for name, info in new_files.items()}
    old_names = set(old_manifest) | {row['file'] for row in before['errors']}
    new_names = set(new_manifest) | {row['file'] for row in current['errors']}
    rows, claimed_old, claimed_new = [], set(), set()
    for hint in hints:
        old, new = hint.get('oldPath'), hint['path']
        if hint['status'] == 'R' and old in old_names - new_names and new in new_names - old_names:
            rows.append(hint)
            claimed_old.add(old)
            claimed_new.add(new)
    untracked = {row['path'] for row in hints if row.get('untracked')}
    for name in sorted(old_names | new_names):
        if name in claimed_old or name in claimed_new: continue
        if name not in old_names:
            rows.append({'status': 'A', 'path': name, **({'untracked': True} if name in untracked else {})})
        elif name not in new_names:
            rows.append({'status': 'D', 'path': name})
        elif old_manifest.get(name) != new_manifest.get(name):
            rows.append({'status': 'M', 'path': name})
    old_configuration = before.get('configurationManifest', {'present': bool(before.get('configuration')), 'hash': before.get('configuration')})
    new_configuration = current.get('configurationManifest', {'present': bool(current.get('configuration')), 'hash': current.get('configuration')})
    if old_configuration != new_configuration:
        status = ('A' if not old_configuration.get('present') else
                  'D' if not new_configuration.get('present') else 'M')
        row = {'status': status, 'path': 'pyproject.toml'}
        if 'pyproject.toml' in untracked:
            row['untracked'] = True
        rows.append(row)
    old_templates = {name: info for name, info in before.get('templateManifest', {}).items()
                     if not name.startswith('@')}
    new_templates = {name: info for name, info in current.get('templateManifest', {}).items()
                     if not name.startswith('@')}
    for hint in hints:
        path = hint['path']
        old_path = hint.get('oldPath', path)
        if not path.lower().endswith(TEMPLATE_SUFFIXES) and not old_path.lower().endswith(TEMPLATE_SUFFIXES):
            continue
        if old_path not in old_templates and path not in new_templates:
            continue  # An unreferenced asset is outside this source review.
        if (hint['status'] == 'R' and old_path != path
                or old_templates.get(old_path) != new_templates.get(path)):
            rows.append(hint)
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
            if row['path'] == 'pyproject.toml':
                old = _configuration_info(before)
                new = _configuration_info(current)
            elif row['path'].lower().endswith(TEMPLATE_SUFFIXES):
                old = before.get('templateAssets', {}).get(row.get('oldPath', row['path']))
                new = current.get('templateAssets', {}).get(row['path'])
            else:
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


def _affected(model, file, ranges, status, *, reason='changed source overlaps definition'):
    rows=[]
    for scope in model['scopes'].values():
        if scope['file'] != file or scope['kind'] in ('module','class'): continue
        if status in ('A', 'D') or (status == 'R' and not ranges) or any(
            scope['span']['start'] <= end and start <= scope['span']['end'] for start, end in ranges
        ):
            rows.append(_scope_ref(scope, reason))
    return rows


def _unassessed_changes(model, file, ranges, status, side):
    """Expose source edits that callable-overlap analysis cannot account for."""
    is_template = file.lower().endswith(TEMPLATE_SUFFIXES)
    info = (_configuration_info(model) if file == 'pyproject.toml' else
            model.get('templateAssets', {}).get(file) if is_template else
            model['files'].get(file))
    if info is None:
        if file == 'pyproject.toml':
            manifest = model.get('configurationManifest', {})
            if not manifest.get('present'):
                return []
            return [{'file': file, 'side': side, 'status': status,
                     'reason': 'Project configuration could not be read; impact is unassessed',
                     'analysisError': manifest.get('error', 'configuration source unavailable')}]
        if is_template:
            manifest = model.get('templateManifest', {}).get(file)
            if manifest is None:
                return []
            return [{'file': file, 'side': side, 'status': status,
                     'reason': 'Referenced template could not be read; impact is unassessed',
                     'analysisError': manifest.get('reason', 'template source unavailable')}]
        error = next((item for item in model['errors'] if item['file'] == file), None)
        if error is None:
            return []
        return [{'file': file, 'side': side, 'status': status, 'reason':
                 'Source could not be parsed or read; impact is unassessed',
                 'analysisError': error['message']}]
    line_count = info['lines']
    if line_count == 0:
        return ([{'file': file, 'side': side, 'status': status,
                  'reason': ('Referenced template changed; callable impact is unassessed'
                             if is_template else
                             'Project configuration file changed; callable impact is unassessed')}]
                if file == 'pyproject.toml' or is_template else [])
    selected = [(1, line_count)] if status in ('A', 'D') else ranges
    if not selected:
        return ([{'file': file, 'side': side, 'status': status,
                  'reason': ('Referenced template bytes changed; callable impact is unassessed'
                             if is_template else
                             'Project configuration bytes changed; callable impact is unassessed')}]
                if file == 'pyproject.toml' or is_template else [])
    callable_spans = sorted((scope['span']['start'], scope['span']['end'])
                            for scope in model['scopes'].values()
                            if scope['file'] == file and scope['kind'] not in ('module', 'class'))
    rows = []
    for start, end in selected:
        fragments = [(max(1, start), min(line_count, end))]
        for covered_start, covered_end in callable_spans:
            next_fragments = []
            for first, last in fragments:
                if last < covered_start or first > covered_end:
                    next_fragments.append((first, last))
                else:
                    if first < covered_start:
                        next_fragments.append((first, covered_start - 1))
                    if last > covered_end:
                        next_fragments.append((covered_end + 1, last))
            fragments = next_fragments
        for first, last in fragments:
            if first > last:
                continue
            span = {'file': file, 'start': first, 'end': last, 'hash': info['hash']}
            rows.append(add_evidence_ids({'file': file, 'side': side, 'status': status,
                                          'span': span, 'reason':
                                          ('Changed referenced template source; impact is unassessed'
                                           if is_template else
                                           'Changed source outside callable definitions; impact is unassessed')}))
    return rows


def _configuration_info(model):
    manifest = model.get('configurationManifest')
    if manifest is None:
        source = model.get('configuration', '')
        if not source:
            return None
        return {'source': source, 'hash': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                'lines': len(source.splitlines())}
    if not manifest.get('present') or manifest.get('hash') is None or manifest.get('error'):
        return None
    source = model.get('configuration', '')
    return {'source': source, 'hash': manifest['hash'], 'lines': len(source.splitlines())}


def _attach_counterparts(rows, own_model, other_model, statuses, *, reverse=False):
    """Match unique symbols independently of their position-based occurrence IDs."""
    def index(model):
        result = {}
        for scope in model['scopes'].values():
            key = (scope['file'], scope['qualified'], scope['kind'])
            result.setdefault(key, []).append(scope)
        return result

    own_index = index(own_model)
    other_index = index(other_model)
    old_to_new = {row['oldPath']: row['path'] for row in statuses if row.get('oldPath')}
    new_to_old = {new: old for old, new in old_to_new.items()}
    file_map = old_to_new if reverse else new_to_old
    for row in rows:
        symbol = own_model['scopes'][row['id']]
        other_file = file_map.get(symbol['file'], symbol['file'])
        own_matches = own_index.get((symbol['file'], symbol['qualified'], symbol['kind']), [])
        candidates = other_index.get((other_file, symbol['qualified'], symbol['kind']), [])
        if len(own_matches) > 1 or len(candidates) > 1:
            row['match'] = 'ambiguous'
        elif len(candidates) == 1:
            row['match'] = 'paired'
            row['counterpartId'] = candidates[0]['id']
            row['counterpartSnapshotId'] = other_model['snapshotId']
        elif any(error['file'] == other_file for error in other_model['errors']):
            row['match'] = 'ambiguous'
        else:
            row['match'] = 'added' if not reverse else 'deleted'

def _scope_ref(scope, reason):
    return add_evidence_ids({'id':scope['id'],'name':scope['qualified'],'file':scope['file'],'span':scope['span'],'reason':reason})
def _unique(rows):
    return list({row['id']: row for row in rows}.values())
def _nodes(flow):
    for node in flow:
        yield node
        for branch in node['branches']: yield from _nodes(branch['nodes'])


def _reachable_calls(scope):
    def visit(nodes, unreachable=False):
        for node in nodes:
            blocked = unreachable or node.get('unreachable', False)
            if not blocked:
                yield from node['calls']
            for branch in node['branches']:
                yield from visit(branch['nodes'], blocked)
    yield from visit(scope['flow'])
