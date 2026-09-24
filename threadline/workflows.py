"""Generic source workflows and conservative event-route discovery."""

from __future__ import annotations

from typing import Any

from .schema import ExecutionContext, Workflow, WorkflowStage


def nodes(flow):
    for node in flow:
        yield node
        for branch in node['branches']:
            yield from nodes(branch['nodes'])


def _guard_text(guard):
    """Render a source-backed expression guard without treating it as a path proof."""
    if isinstance(guard, str):
        return guard
    if not isinstance(guard, dict):
        return ''
    condition = guard.get('condition', '')
    branch = guard.get('branch') or guard.get('requirement') or ''
    return f'{condition}: {branch}' if condition and branch else condition or branch


def event_routes(model):
    """Match literal/enum event expressions and registered callback candidates.

    Matching syntax is only a possible event route: mutable bus identities and
    startup conditions are intentionally not elevated to definite execution.
    """
    publishers, subscribers = [], []
    methods_by_name: dict[str, list[str]] = {}
    for scope in model['scopes'].values():
        if scope['kind'] in ('class', 'module'):
            continue
        methods_by_name.setdefault(scope['name'], []).append(scope['id'])
        for node in nodes(scope['flow']):
            for call in node['calls']:
                if call['name'].endswith('.publish') and call['arguments']:
                    publishers.append((scope, call))
                elif call['name'].endswith('.subscribe') and len(call['arguments']) >= 2:
                    subscribers.append((scope, call))
    registrations: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for registrar, sub in subscribers:
        key = (sub['arguments'][0], sub['name'].rsplit('.', 1)[0])
        registrations.setdefault(key, []).append((registrar, sub))
    routes = []
    for producer, pub in publishers:
        key = (pub['arguments'][0], pub['name'].rsplit('.', 1)[0])
        for registrar, sub in registrations.get(key, []):
            # Equal receiver spelling is not proof of bus identity.
            callback = sub['arguments'][1]
            member = callback.split('.')[-1]
            candidates = methods_by_name.get(member, [])
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
            reasons.append('recognized route, command, or task decorator')
            score += 100
        key = f"{scope['module']}:{scope['qualified']}"
        if key in declared or f"{scope['module']}:{scope['name']}" in declared:
            reasons.append('declared project script')
            score += 120
        if scope['name'] in ('main', 'cli', 'app') and scope['kind'] != 'module':
            reasons.append('conventional entrypoint name')
            score += 50
        if scope['kind'] == 'module' and any("__name__ == '__main__'" in n.get('label', '') or '"__main__"' in n.get('label', '') for n in nodes(scope['flow'])):
            reasons.append('main guard')
            score += 110
        if not reasons and scope['kind'] in ('function', 'method') and not scope['callers']:
            reasons.append('no source-linked callers in this snapshot')
            score += 10
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


def workflow_catalog(model):
    """Expose independent review starts; source declarations never imply execution."""
    import ast
    import tomllib
    try:
        config = tomllib.loads(model.get('configuration', ''))
        scripts = config.get('project', {}).get('scripts', {})
        if not isinstance(scripts, dict): scripts = {}
        poetry = config.get('tool', {}).get('poetry', {}).get('scripts', {})
        if isinstance(poetry, dict): scripts = {**poetry, **scripts}
    except (ValueError, AttributeError):
        scripts = {}
    commands: dict[str, list[str]] = {}
    for name, target in scripts.items():
        if isinstance(target, str): commands.setdefault(target.split('[', 1)[0].strip(), []).append(name)
    prefixes = model.get('routerPrefixes')
    if prefixes is None:
        # Compatibility for callers supplying an older analysis model.
        prefixes = {}
        for file, info in model['files'].items():
            try:
                tree = ast.parse(info['source'])
            except (SyntaxError, ValueError):
                continue
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
                    continue
                constructor = ast.unparse(node.value.func).split('.')[-1]
                if constructor not in ('APIRouter', 'Blueprint'):
                    continue
                prefix = next((kw.value.value for kw in node.value.keywords
                               if kw.arg in ('prefix', 'url_prefix')
                               and isinstance(kw.value, ast.Constant)
                               and isinstance(kw.value.value, str)), '')
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        prefixes[f'{file}:{target.id}'] = prefix
    rows = []
    for scope in model['scopes'].values():
        if scope['kind'] == 'class': continue
        entries = []
        http_methods = {}
        for text in scope['decorators']:
            try: decorator = ast.parse(text, mode='eval').body
            except (SyntaxError, ValueError): continue
            func = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
            args = decorator.args if isinstance(decorator, ast.Call) else []
            keywords = decorator.keywords if isinstance(decorator, ast.Call) else []
            path = next((kw.value for kw in keywords if kw.arg == 'path'), args[0] if args else None)
            if name in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'route', 'api_route', 'websocket', 'websocket_route'):
                if isinstance(path, ast.Constant) and isinstance(path.value, str):
                    receiver = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ''
                    route = prefixes.get(f"{scope['file']}:{receiver}", '') + path.value
                    verb = 'WS' if 'websocket' in name else name.upper()
                    if name in ('route', 'api_route'):
                        methods = next((kw.value for kw in keywords if kw.arg == 'methods'), None)
                        if isinstance(methods, (ast.List, ast.Tuple)) and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in methods.elts):
                            verb = ', '.join(item.value.upper() for item in methods.elts
                                             if isinstance(item, ast.Constant)
                                             and isinstance(item.value, str))
                        else: verb = 'ROUTE'
                    label = verb+' '+route
                    http_methods[label] = verb.split(', ')
                    entries.append(('http', label))
            elif name in ('command', 'callback', 'group'):
                label = next((kw.value.value for kw in keywords if kw.arg == 'name' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)), None)
                if not label and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str): label = args[0].value
                entries.append(('commands', label or scope['qualified']))
            elif name in ('task', 'shared_task', 'periodic_task', 'on_event', 'on_startup', 'on_shutdown'):
                entries.append(('tasks', scope['qualified']))
        key = f"{scope['module']}:{scope['qualified']}"
        entries.extend(('commands', name) for name in commands.get(key, []))
        if scope['kind'] == 'module':
            if any('__main__' in node.get('label', '') and '__name__' in node.get('label', '') for node in nodes(scope['flow'])):
                entries.append(('commands', 'python -m '+scope['module']))
            if not entries: continue
        if not entries: entries = [('methods', scope['qualified'])]
        for category, label in dict.fromkeys(entries):
            rows.append({'id': scope['id'], 'name': scope['qualified'], 'label': label,
                         'category': category, 'file': scope['file'], 'line': scope['span']['start'], 'span': scope['span'],
                         **({'httpMethods': http_methods[label]} if category == 'http' else {})})
    rows.sort(key=lambda row: (row['category'], row['name'].split('.')[-1].startswith('__'), row['label'].casefold(), row['file'], row['line']))
    return rows


def generic_workflow(model: dict[str, Any], scope_id: str, max_stages: int = 500) -> Workflow:
    """Build a nested cross-file call workflow without promoting ambiguity to fact."""
    root = model['scopes'][scope_id]
    stages: list[WorkflowStage] = [{'id': 'entry', 'label': root['name'], 'scope': scope_id, 'methods': [scope_id],
               'span': root['span'], 'input': root['params'], 'output': root['output'],
               'condition': 'Selected source entrypoint', 'data': _boundary_text(root), 'status': 'supported'}]
    links, alternatives, uncertainties = [], [], []
    expanded, expanded_contexts, active = set(), set(), []
    stage_ids = {'entry'}
    constructors_by_class: dict[str, list[str]] = {}
    for scope in model['scopes'].values():
        if scope['parent'] and scope['name'] in ('__new__', '__init__'):
            constructors_by_class.setdefault(scope['parent'], []).append(scope['id'])
    omitted = 0

    def expand(current_id, parent_stage, depth, inherited_context='', deferred_source=''):
        nonlocal omitted
        if current_id in active:
            return
        context_key = (current_id, bool(deferred_source))
        if context_key in expanded_contexts:
            return
        current = model['scopes'][current_id]
        active.append(current_id)
        expanded.add(current_id)
        expanded_contexts.add(context_key)

        def visit(items, path=(), unreachable=False):
            nonlocal omitted
            for operation in items:
                is_unreachable = unreachable or operation.get('unreachable', False)
                if operation['branches']:
                    alternatives.append({'scope': current_id, 'operation': operation['id'], 'label': operation['label'],
                                         'arms': [branch['label'] for branch in operation['branches']], 'span': operation['span'],
                                         'kind': 'statement', 'unreachable': is_unreachable})
                for decision in operation['decisions']:
                    if decision.get('alternatives'):
                        alternatives.append({'scope': current_id, 'operation': operation['id'], 'label': decision['label'],
                                             'arms': decision['alternatives'], 'span': decision['span'],
                                             'kind': 'expression', 'unreachable': is_unreachable})
                for call in operation['calls']:
                    if len(stages) >= max_stages:
                        omitted += 1
                        continue
                    stage_id = 'call:' + call['id']
                    if stage_id in stage_ids:
                        stage_id += f':instance:{len(stages)}'
                    stage_ids.add(stage_id)
                    targets = call['targets']
                    definite = call['status'] == 'supported' and len(targets) == 1
                    candidate = model['scopes'].get(targets[0]) if len(targets) == 1 else None
                    target = candidate if candidate and definite and candidate['kind'] != 'class' and not is_unreachable else None
                    recursive = bool(target and target['id'] in active)
                    constructor_candidates = []
                    if candidate and candidate['kind'] == 'class':
                        constructor_candidates = constructors_by_class.get(candidate['id'], [])
                    execution = call.get('execution') or 'ordinary call'
                    source_context = call.get('executionContext') or {}
                    execution_context: ExecutionContext = {
                        'kind': source_context.get('kind', 'unknown source body'),
                        'deferred': bool(source_context.get('deferred', False)),
                    }
                    execution_context['inheritedDeferred'] = bool(deferred_source)
                    execution_context['effectiveDeferred'] = bool(
                        execution_context.get('deferred') or deferred_source
                        or execution.startswith(('deferred coroutine', 'deferred generator'))
                    )
                    if deferred_source:
                        execution_context['deferredBy'] = deferred_source
                    local_context = ''
                    if execution_context.get('deferred') and not inherited_context:
                        local_context = 'inside ' + execution_context['kind'] + '; body is deferred until resumed'
                    context = ' / '.join(part for part in (inherited_context, local_context, *path,
                                        *(_guard_text(guard) for guard in call.get('guards', []))) if part)
                    if candidate and candidate['kind'] == 'class':
                        execution = 'object construction; initializer and metaclass dispatch are not established'
                    labels = {target_id: model['scopes'][target_id]['qualified']
                              for target_id in set(targets + constructor_candidates) if target_id in model['scopes']}
                    candidate_evidence = call.get('candidateEvidence', [])
                    stage_evidence = [{'scope': current_id, 'span': call['span'], 'label': 'Original call site'},
                                      *candidate_evidence]
                    stage: WorkflowStage = {'id': stage_id, 'parent': parent_stage, 'depth': depth + 1, 'label': call['name'],
                             'scope': candidate['id'] if candidate else current_id, 'methods': targets,
                             'possibleTargets': targets, 'span': call['span'], 'callsite': not definite,
                             'construction': bool(candidate and candidate['kind'] == 'class'),
                             'callerScope': current_id, 'destination': call['destination'], 'targetLabels': labels,
                             'data': f"{', '.join(call['arguments']) or 'no arguments'} → {call['destination']}",
                             'condition': (context + ' · ' if context else '') + execution,
                             'status': call['status'], 'reason': call['reason'],
                             'reasonCode': call.get('reasonCode', 'unresolved_target'),
                             'bindings': call['bindings'],
                             'receiverBindings': call.get('receiverBindings', {}),
                             'candidateEvidence': candidate_evidence,
                             'recursive': recursive, 'unreachable': is_unreachable,
                             'conditional': bool(path or call.get('conditional') or call.get('guards')),
                             'guards': call.get('guards', []),
                             'executionContext': execution_context,
                             'constructorCandidates': constructor_candidates,
                             'evidence': stage_evidence}
                    if target and target['file'] != current['file']:
                        stage['moduleLink'] = {'from': current['module'], 'to': target['module']}
                    stages.append(stage)
                    links.append({'id': stage_id, 'from': parent_stage, 'to': stage_id, 'kind': 'call',
                                  'label': 'Call inside ' + current['qualified'], 'data': ', '.join(call['arguments']),
                                  'status': call['status'], 'description': call['reason'] + '; returns to ' + call['destination'],
                                  'evidence': stage['evidence']})
                    if is_unreachable:
                        uncertainties.append({'stage': stage_id, 'status': 'unreachable',
                                              'reasonCode': 'unreachable_source',
                                              'reason': 'This call follows an unconditional exit in its source block.',
                                              'possibleTargets': targets, 'span': call['span']})
                    elif candidate and candidate['kind'] == 'class':
                        uncertainties.append({'stage': stage_id, 'status': 'possible',
                                              'reasonCode': 'constructor_dispatch',
                                              'reason': 'Constructing an object does not rerun its class body; initializer and metaclass dispatch remain uncertain.',
                                              'possibleTargets': constructor_candidates, 'span': call['span']})
                    elif not definite:
                        uncertainties.append({'stage': stage_id, 'status': call['status'],
                                              'reasonCode': call.get('reasonCode', 'unresolved_target'),
                                              'reason': call['reason'],
                                              'possibleTargets': targets, 'span': call['span']})
                    elif recursive:
                        uncertainties.append({'stage': stage_id, 'status': 'recursive',
                                              'kind': 'expansion', 'reasonCode': 'recursive_expansion',
                                              'reason': 'Recursive call; body is represented at its first expansion.',
                                              'possibleTargets': targets, 'span': call['span']})
                    elif target is not None:
                        deferred = execution if execution.startswith(('deferred coroutine', 'deferred generator')) else ''
                        child_context = deferred or inherited_context or local_context
                        child_source = stage_id if deferred else deferred_source or (
                            stage_id if execution_context.get('deferred') else '')
                        if (target['id'], bool(child_source)) not in expanded_contexts:
                            if depth + 1 >= 100:
                                stage['expansionTruncated'] = True
                                omitted += 1
                                continue
                            expand(target['id'], stage_id, depth + 1,
                                   child_context, child_source)
                for branch in operation['branches']:
                    visit(branch['nodes'], path + (branch['label'],), is_unreachable)
        visit(current['flow'])
        active.pop()

    expand(scope_id, 'entry', 0)
    for route_index, route in enumerate(r for r in model.get('workflows', {}).get('eventRoutes', []) if r['producer'] in expanded):
        if len(stages) >= max_stages:
            omitted += 1
            continue
        stage_id = f'event:{route_index}:{route["producer"]}'
        stages.append({'id': stage_id, 'parent': 'entry', 'depth': 1, 'label': 'Subscriber: ' + route['callback'],
                       'scope': route['targets'][0] if len(route['targets']) == 1 else scope_id,
                       'methods': route['targets'] if len(route['targets']) == 1 else [], 'possibleTargets': route['targets'],
                       'span': route['evidence'][0]['span'], 'data': route['event'] + ' → callback payload',
                       'condition': route['reason'], 'status': 'possible', 'callsite': True,
                       'reasonCode': 'event_route_candidate', 'evidence': route['evidence']})
        links.append({'id': stage_id, 'from': 'entry', 'to': stage_id, 'kind': 'possible_event', 'label': route['event'],
                      'data': 'event payload', 'status': 'possible', 'description': route['reason'], 'evidence': route['evidence']})
        uncertainties.append({'stage': stage_id, 'status': 'possible',
                              'reasonCode': 'event_route_candidate', 'reason': route['reason'],
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
