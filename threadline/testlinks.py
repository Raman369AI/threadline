"""Link methods and tests from source evidence. Never runs the test suite."""
from __future__ import annotations

import ast
import re
from collections import defaultdict, deque
from pathlib import PurePosixPath

MAX_HOPS = 4
HTTP_VERBS = ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')
# Lower rank is stronger evidence; the display order follows it.
RELATIONS = {'direct': 0, 'route': 1, 'indirect': 2, 'name': 3}


def is_test_file(file):
    path = PurePosixPath(file)
    return (path.name.startswith('test_') or path.name.endswith('_test.py')
            or any(part in ('tests', 'test') for part in path.parts[:-1])) and path.name != 'conftest.py'


def is_test_scope(model, scope):
    if scope['kind'] not in ('function', 'method') or not is_test_file(scope['file']):
        return False
    if not scope['name'].startswith('test'):
        return False
    parent = model['scopes'].get(scope['parent'])
    return scope['kind'] == 'function' or bool(parent and parent['name'].startswith('Test'))


def _flatten(flow):
    for node in flow:
        yield node
        for branch in node['branches']:
            yield from _flatten(branch['nodes'])


def build_index(model):
    """Reverse call edges plus the enclosing test of every scope inside a test."""
    scopes = model['scopes']
    tests = {sid for sid, scope in scopes.items() if is_test_scope(model, scope)}
    owner = {}
    for sid in scopes:
        cursor = sid
        while cursor and cursor not in tests:
            cursor = scopes[cursor]['parent']
        if cursor:
            owner[sid] = cursor
    callers = defaultdict(list)
    requests = []
    for sid, scope in scopes.items():
        for node in _flatten(scope['flow']):
            for call in node['calls']:
                if call['status'] in ('supported', 'possible'):
                    for target in call['targets']:
                        callers[target].append((call['scope'], call))
                if call['scope'] in owner and call['arguments']:
                    route = _requested_route(call)
                    if route:
                        requests.append((owner[call['scope']], call, *route))
    routes = defaultdict(list)
    for row in model.get('catalog', []):
        if row['category'] == 'http':
            routes[row['id']].append(row['label'])
    return {'tests': tests, 'owner': owner, 'callers': callers, 'requests': requests, 'routes': routes}


def _requested_route(call):
    verb = call['name'].rsplit('.', 1)[-1]
    if verb not in HTTP_VERBS or '.' not in call['name']:
        return None
    try:
        path = ast.literal_eval(call['arguments'][0])
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    if not isinstance(path, str) or not path.startswith('/'):
        return None
    return verb.upper(), path.split('?', 1)[0]


def _route_pattern(template):
    parts = re.split(r'(\{[^}]+\}|<[^>]+>)', template)
    return re.compile('^' + ''.join('[^/]+' if part[:1] in '{<' else re.escape(part) for part in parts) + '/?$')


def _row(model, test_id, relation, status, reason, span, via=()):
    scope = model['scopes'][test_id]
    return {'id': test_id, 'name': scope['qualified'], 'file': scope['file'], 'line': scope['span']['start'],
            'span': scope['span'], 'relation': relation, 'status': status, 'reason': reason,
            'via': list(via), 'callsite': span}


def related_tests(model, index, symbol_id):
    """Tests that reach a method, strongest evidence first."""
    scopes, owner = model['scopes'], index['owner']
    found = {}
    def keep(row):
        current = found.get(row['id'])
        if current is None or (RELATIONS[row['relation']], len(row['via'])) < (RELATIONS[current['relation']], len(current['via'])):
            found[row['id']] = row
    # Walk callers backwards; each path keeps the weakest status it crossed.
    seen = {symbol_id: 0}
    queue = deque([(symbol_id, (), 'supported')])
    while queue:
        target, via, status = queue.popleft()
        for caller, call in index['callers'].get(target, []):
            step = 'possible' if 'possible' in (status, call['status']) else 'supported'
            test = owner.get(caller)
            if test:
                relation = 'direct' if not via else 'indirect'
                reason = ('Calls it directly' if not via else 'Calls it through ' + ' → '.join(scopes[s]['qualified'] for s in reversed(via)))
                keep(_row(model, test, relation, step, reason, call['span'], (scopes[s]['qualified'] for s in reversed(via))))
                continue
            if len(via) + 1 >= MAX_HOPS or seen.get(caller, MAX_HOPS) <= len(via) + 1:
                continue
            seen[caller] = len(via) + 1
            queue.append((caller, via + (caller,), step))
    for label in index['routes'].get(symbol_id, []):
        verbs, _, template = label.rpartition(' ')
        pattern = _route_pattern(template)
        for test, call, verb, path in index['requests']:
            if (verb in verbs.split(', ') or verbs in ('ROUTE', 'WS')) and pattern.match(path):
                keep(_row(model, test, 'route', 'possible', f'Requests {verb} {path}', call['span']))
    target = scopes[symbol_id]
    name = target['name'].strip('_').casefold()
    if len(name) >= 3 and target['kind'] not in ('module', 'class'):
        token = re.compile(r'(^|_)' + re.escape(name) + r'(_|$)')
        anchors = {target['module'].rsplit('.', 1)[-1]}
        parent = scopes.get(target['parent'])
        if parent and parent['kind'] == 'class':
            anchors.add(parent['name'])
        for test in index['tests']:
            if test in found:
                continue
            scope = scopes[test]
            if token.search(scope['name'].casefold()) and any(anchor and anchor in model['files'][scope['file']]['source'] for anchor in anchors):
                keep(_row(model, test, 'name', 'possible', 'Test name mentions it; no call was linked', scope['span']))
    return sorted(found.values(), key=lambda row: (RELATIONS[row['relation']], row['status'] != 'supported', len(row['via']), row['file'], row['line']))


def tested_subjects(model, index, test_id):
    """Non-test methods a test calls, following helpers defined in test files."""
    scopes, owner = model['scopes'], index['owner']
    rows, visited = {}, set()
    pending = deque([(sid, ()) for sid in scopes if owner.get(sid) == test_id])
    while pending:
        sid, via = pending.popleft()
        if sid in visited:
            continue
        visited.add(sid)
        for node in _flatten(scopes[sid]['flow']):
            for call in node['calls']:
                if call['status'] not in ('supported', 'possible'):
                    continue
                for target in call['targets']:
                    subject = scopes[target]
                    if subject['kind'] == 'lambda' or target in rows:
                        continue
                    if is_test_file(subject['file']):
                        if target not in index['tests'] and len(via) < MAX_HOPS:
                            pending.append((target, via + (subject['qualified'],)))
                        continue
                    rows[target] = {'id': target, 'name': subject['qualified'], 'file': subject['file'],
                                    'line': subject['span']['start'], 'span': subject['span'], 'status': call['status'],
                                    'callsite': call['span'], 'via': list(via),
                                    'reason': ('Constructed' if subject['kind'] == 'class' else 'Called')
                                              + (' directly' if not via else ' through ' + ' → '.join(via))}
    return sorted(rows.values(), key=lambda row: (len(row['via']), row['callsite']['file'], row['callsite']['start'], row['callsite']['col']))
