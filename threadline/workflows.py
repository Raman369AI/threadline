"""Generic source workflows and conservative event-route discovery."""


def nodes(flow):
    for node in flow:
        yield node
        for branch in node['branches']:
            yield from nodes(branch['nodes'])


def event_routes(model):
    """Match literal/enum event expressions and registered callback candidates.

    Matching syntax is only a possible event route: mutable bus identities and
    startup conditions are intentionally not elevated to definite execution.
    """
    publishers, subscribers = [], []
    for scope in model['scopes'].values():
        if scope['kind'] in ('class', 'module'):
            continue
        for node in nodes(scope['flow']):
            for call in node['calls']:
                if call['name'].endswith('.publish') and call['arguments']:
                    publishers.append((scope, call))
                elif call['name'].endswith('.subscribe') and len(call['arguments']) >= 2:
                    subscribers.append((scope, call))
    routes = []
    for producer, pub in publishers:
        for registrar, sub in subscribers:
            if pub['arguments'][0] != sub['arguments'][0]:
                continue
            # Equal receiver spelling is not a proof of identity; retain uncertainty.
            if pub['name'].rsplit('.', 1)[0] != sub['name'].rsplit('.', 1)[0]:
                continue
            callback = sub['arguments'][1]
            member = callback.split('.')[-1]
            candidates = [s['id'] for s in model['scopes'].values() if s['name'] == member and s['kind'] not in ('module', 'class')]
            routes.append({'producer': producer['id'], 'event': pub['arguments'][0], 'callback': callback,
                           'targets': candidates, 'status': 'possible',
                           'reason': 'Matching publish/subscribe expressions; bus identity, registration execution and callback dispatch remain runtime-dependent.',
                           'evidence': [{'scope': producer['id'], 'span': pub['span'], 'label': 'Event publication'},
                                        {'scope': registrar['id'], 'span': sub['span'], 'label': 'Callback registration'}]})
    return routes


def build_workflows(model):
    return {'eventRoutes': event_routes(model)}

ENTRY_DECORATORS = ('.get(', '.post(', '.put(', '.patch(', '.delete(', '.route(', '.command(', '.callback(', '.task(')


def suggested_entrypoints(model):
    """Rank source-supported starts while retaining manual symbol selection."""
    declared = _declared_scripts(model)
    rows = []
    for scope in model['scopes'].values():
        if scope['kind'] == 'class' or scope['kind'] == 'lambda' or scope['kind'] == 'nested function':
            continue
        reasons, score = [], 0
        decorators = ' '.join(scope.get('decorators', []))
        if any(marker in decorator for marker in ENTRY_DECORATORS for decorator in scope.get('decorators', [])):
            reasons.append('recognized route, command, or task decorator'); score += 100
        key = f"{scope['module']}:{scope['qualified']}"
        if key in declared or f"{scope['module']}:{scope['name']}" in declared:
            reasons.append('declared project script'); score += 120
        if scope['name'] in ('main', 'cli', 'app') and scope['kind'] != 'module':
            reasons.append('conventional entrypoint name'); score += 50
        if scope['kind'] == 'module' and any("__name__ == '__main__'" in n.get('label', '') or '"__main__"' in n.get('label', '') for n in nodes(scope['flow'])):
            reasons.append('main guard'); score += 110
        if not reasons and scope['kind'] in ('function', 'method') and not scope['callers']:
            reasons.append('no source-linked callers in this snapshot'); score += 10
        if reasons:
            rows.append({'id': scope['id'], 'name': scope['qualified'], 'file': scope['file'],
                         'line': scope['span']['start'], 'reason': '; '.join(reasons), 'confidence': 'supported' if score >= 100 else 'suggested',
                         '_score': score, 'span': scope['span']})
    rows.sort(key=lambda item: (-item.pop('_score'), item['file'], item['line']))
    return rows


def _declared_scripts(model):
    """Read standard project metadata as data. Never imports build configuration."""
    try:
        import tomllib
        document = tomllib.loads(model.get('configuration', ''))
    except (OSError, UnicodeError, ValueError):
        return set()
    def table(value):
        return value if isinstance(value, dict) else {}
    values = list(table(table(document.get('project')).get('scripts')).values())
    poetry = table(table(table(document.get('tool')).get('poetry')).get('scripts'))
    values.extend(value for value in poetry.values() if isinstance(value, str))
    return {value.split('[', 1)[0].strip() for value in values if isinstance(value, str)}


def generic_workflow(model, scope_id, max_stages=500):
    """Build a nested cross-file call workflow without promoting ambiguity to fact."""
    root = model['scopes'][scope_id]
    stages = [{'id': 'entry', 'label': root['name'], 'scope': scope_id, 'methods': [scope_id],
               'span': root['span'], 'input': root['params'], 'output': root['output'],
               'condition': 'Selected source entrypoint', 'data': _boundary_text(root), 'status': 'supported'}]
    links, alternatives, uncertainties = [], [], []
    expanded, active = set(), []
    omitted = 0

    def expand(current_id, parent_stage, depth):
        nonlocal omitted
        if current_id in active:
            return
        current = model['scopes'][current_id]
        active.append(current_id)
        expanded.add(current_id)

        def visit(items, path=()):
            nonlocal omitted
            for operation in items:
                if operation['branches']:
                    alternatives.append({'scope': current_id, 'operation': operation['id'], 'label': operation['label'],
                                         'arms': [branch['label'] for branch in operation['branches']], 'span': operation['span']})
                for call in operation['calls']:
                    if len(stages) >= max_stages:
                        omitted += 1
                        continue
                    stage_id = 'call:' + call['id']
                    targets = call['targets']
                    definite = call['status'] == 'supported' and len(targets) == 1
                    candidate = model['scopes'].get(targets[0]) if len(targets) == 1 else None
                    target = candidate if definite else None
                    recursive = bool(target and target['id'] in active)
                    stage = {'id': stage_id, 'parent': parent_stage, 'depth': depth + 1, 'label': call['name'],
                             'scope': candidate['id'] if candidate else current_id, 'methods': targets,
                             'possibleTargets': targets, 'span': call['span'], 'callsite': not definite,
                             'data': f"{', '.join(call['arguments']) or 'no arguments'} → {call['destination']}",
                             'condition': (' / '.join(path) + ' · ' if path else '') + (call.get('execution') or 'ordinary call'),
                             'status': call['status'], 'reason': call['reason'], 'bindings': call['bindings'],
                             'recursive': recursive, 'evidence': [{'scope': current_id, 'span': call['span'], 'label': 'Original call site'}]}
                    stages.append(stage)
                    links.append({'id': stage_id, 'from': parent_stage, 'to': stage_id, 'kind': 'call',
                                  'label': 'Call inside ' + current['qualified'], 'data': ', '.join(call['arguments']),
                                  'status': call['status'], 'description': call['reason'] + '; returns to ' + call['destination'],
                                  'evidence': stage['evidence']})
                    if not definite:
                        uncertainties.append({'stage': stage_id, 'status': call['status'], 'reason': call['reason'],
                                              'possibleTargets': targets, 'span': call['span']})
                    elif recursive:
                        uncertainties.append({'stage': stage_id, 'status': 'recursive', 'reason': 'Recursive call; body is represented at its first expansion.',
                                              'possibleTargets': targets, 'span': call['span']})
                    elif target['id'] not in expanded:
                        if depth + 1 >= 100:
                            stage['expansionTruncated'] = True
                            omitted += 1
                        else:
                            expand(target['id'], stage_id, depth + 1)
                for branch in operation['branches']:
                    visit(branch['nodes'], path + (branch['label'],))
        visit(current['flow'])
        active.pop()

    expand(scope_id, 'entry', 0)
    for route_index, route in enumerate(r for r in model.get('workflows', {}).get('eventRoutes', []) if r['producer'] in expanded):
        if len(stages) >= max_stages:
            omitted += 1; continue
        stage_id = f'event:{route_index}:{route["producer"]}'
        stages.append({'id': stage_id, 'parent': 'entry', 'depth': 1, 'label': 'Subscriber: ' + route['callback'],
                       'scope': route['targets'][0] if len(route['targets']) == 1 else scope_id,
                       'methods': route['targets'] if len(route['targets']) == 1 else [], 'possibleTargets': route['targets'],
                       'span': route['evidence'][0]['span'], 'data': route['event'] + ' → callback payload',
                       'condition': route['reason'], 'status': 'possible', 'callsite': True, 'evidence': route['evidence']})
        links.append({'id': stage_id, 'from': 'entry', 'to': stage_id, 'kind': 'possible_event', 'label': route['event'],
                      'data': 'event payload', 'status': 'possible', 'description': route['reason'], 'evidence': route['evidence']})
        uncertainties.append({'stage': stage_id, 'status': 'possible', 'reason': route['reason'],
                              'possibleTargets': route['targets'], 'span': route['evidence'][0]['span']})
    return {'id': 'entrypoint-calls', 'title': root['qualified'] + ' workflow',
            'description': 'Calls remain nested under their caller. Branch context, return destinations, and unresolved targets are retained.',
            'provenance': 'Generated from syntax and conservative source binding; this is not an observed execution.',
            'root': scope_id, 'nested': True, 'stages': stages, 'links': links, 'alternatives': alternatives,
            'uncertainties': uncertainties, 'outcomes': [], 'truncated': omitted > 0, 'omitted': omitted,
            'limit': max_stages}

def _boundary_text(scope):
    visible = [p for p in scope['params'] if p['name'] not in ('self', 'cls') and not str(p.get('default') or '').startswith('Depends(')]
    inputs = ', '.join(p['name'] + (': ' + p['annotation'] if p.get('annotation') else '') for p in visible) or 'no explicit input'
    output = scope['output'].get('responseModel') or scope['output'].get('annotation')
    if not output:
        values = list(dict.fromkeys(scope['output'].get('returns', [])))
        output = ' / '.join(values) if values else 'implicit None'
    return inputs + ' → ' + output
