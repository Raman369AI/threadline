"""Static Git change review with external diff and text conversion disabled."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .service import SnapshotStore, ThreadlineError, add_evidence_ids

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def review_changes(root: str | Path, base: str = 'HEAD', files: list[str] | None = None, store: SnapshotStore | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    _git(root, ['rev-parse', '--verify', base + '^{commit}'])
    statuses = _statuses(root, base)
    if files is not None:
        allowed = {Path(name).as_posix() for name in files}
        statuses = [row for row in statuses if row['path'] in allowed or row.get('oldPath') in allowed]
    current_store = store or SnapshotStore(root); current = current_store.current
    with tempfile.TemporaryDirectory(prefix='threadline-base-') as directory:
        base_root = Path(directory)
        for name in (item for item in _git_z(root, ['ls-tree', '-r', '-z', '--name-only', base]) if item.endswith('.py')):
            target = base_root / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git_bytes(root, ['cat-file', 'blob', f'{base}:{name}']))
        before_store = SnapshotStore(base_root); before = before_store.refresh()
        if store: store.retain(before)
    hunks = _hunks(root, base)
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
    possible = []
    changed_names = {current['scopes'][item['id']]['name'] for item in changed_current}
    for scope in current['scopes'].values():
        if scope['id'] in current_ids: continue
        for node in _nodes(scope['flow']):
            if any(call['status'] == 'possible' and any(current['scopes'].get(t, {}).get('name') in changed_names for t in call['targets']) for call in node['calls']):
                possible.append(_scope_ref(scope, 'possible caller under static dispatch assumptions')); break
    return {'base': base, 'workingSnapshotId': current['snapshotId'], 'baseSnapshotId': before['snapshotId'],
            'files': statuses, 'changedMethods': _unique(changed_current), 'previousMethods': _unique(changed_before),
            'knownCallers': _unique(callers), 'possibleImpact': _unique(possible),
            'parseErrors': {'working': current['errors'], 'base': before['errors']},
            'notice': 'Changed methods are syntactic overlap. Callers are classified separately; reachability is not observed execution.'}


def _git(root, args):
    result = subprocess.run(['git', '-c', 'diff.external=', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ThreadlineError(result.stderr.decode(errors='replace').strip() or 'Git query failed')
    return result.stdout.decode(errors='surrogateescape').strip()

def _git_bytes(root, args):
    result = subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode: raise ThreadlineError(result.stderr.decode(errors='replace').strip())
    return result.stdout

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

def _hunks(root, base):
    text=_git(root, ['diff', '--no-ext-diff', '--no-textconv', '--unified=0', '--find-renames', base, '--', '*.py'])
    result={}; old_path=None; new_path=None
    for line in text.splitlines():
        if line.startswith('--- a/'): old_path=line[6:]
        elif line.startswith('--- /dev/null'): old_path=None
        elif line.startswith('+++ b/'): new_path=line[6:]
        elif line.startswith('+++ /dev/null'): new_path=None
        elif (match:=HUNK.match(line)):
            key=new_path or old_path
            if not key: continue
            row=result.setdefault(key, {'old':[], 'new':[]})
            old_start,old_count,new_start,new_count=(int(match.group(1)),int(match.group(2) or 1),int(match.group(3)),int(match.group(4) or 1))
            row['old'].append((old_start,old_start+max(1,old_count)-1));row['new'].append((new_start,new_start+max(1,new_count)-1))
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
