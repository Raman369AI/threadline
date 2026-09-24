"""A one-sentence method summary and its callers, built from the analyzed source."""
from __future__ import annotations

import re

from . import testlinks

MAX_NAMED = 3


def _names(values, limit=MAX_NAMED):
    values = list(dict.fromkeys(values))
    if not values:
        return ''
    shown = values[:limit]
    extra = len(values) - len(shown)
    if extra:
        return ', '.join(shown) + f' and {extra} more'
    return shown[0] if len(shown) == 1 else ', '.join(shown[:-1]) + ' and ' + shown[-1]


def _plural(count, word):
    return f'{count} {word}' + ('' if count == 1 else 's')


def summary(model, scope):
    """Plain sentences: what comes in, what it calls, what it can raise, what goes out."""
    if scope['kind'] in ('module', 'class'):
        return ''
    scopes = model['scopes']
    inputs = [p['name'] for p in scope['params']
              if p['name'] not in ('self', 'cls') and not str(p.get('default') or '').startswith('Depends(')]
    calls, creates, probable, raises, branching = [], [], [], [], 0
    library = unknown = 0
    for node in testlinks._flatten(scope['flow']):
        branching += bool(node['branches'])
        if node['kind'] == 'Raise' and node['label'] != 'Raise current exception':
            raises.append(re.split(r'[(\s]', node['label'][len('Raise '):], maxsplit=1)[0])
            continue  # Constructing the exception is covered by "can raise".
        for call in node['calls']:
            if call['scope'] != scope['id']:
                continue
            if call['status'] in ('supported', 'possible') and call['targets']:
                target = scopes.get(call['targets'][0])
                if target and target['id'] != scope['id']:
                    bucket = probable if call['status'] == 'possible' else creates if target['kind'] == 'class' else calls
                    bucket.append(target['qualified'])
            elif call['status'] == 'external':
                library += 1
            elif call['status'] == 'unknown':
                unknown += 1
    output = scope['output']
    returns = list(dict.fromkeys(output.get('returns', [])))
    declared = output.get('responseModel') if output.get('responseModel') not in (None, 'None') else output.get('annotation')
    if declared:
        result = declared
    elif returns and all(re.fullmatch(r'[\w.]+', value) for value in returns) and returns != ['None']:
        result = ' or '.join(returns[:MAX_NAMED])
    elif returns and returns != ['None']:
        result = 'a value'
    else:
        result = None
    sentences = ['Takes ' + (_names(inputs, 4) if inputs else 'no input') + '.']
    actions = []
    if creates:
        actions.append('creates ' + _names(creates))
    if calls:
        actions.append('calls ' + _names(calls))
    if probable:
        actions.append('probably calls ' + _names(probable))
    if library:
        actions.append('makes ' + _plural(library, 'library call'))
    if raises:
        actions.append('can raise ' + _names(raises))
    if actions:
        text = ', '.join(actions[:-1]) + (' and ' if len(actions) > 1 else '') + actions[-1]
        sentences.append(text[0].upper() + text[1:] + '.')
    if scope.get('generator'):
        sentences.append('Yields values' + (f' ({result})' if result else '') + '.')
    elif result:
        sentences.append(f'Returns {result}.')
    notes = []
    if branching:
        notes.append(_plural(branching, 'decision point'))
    if unknown:
        notes.append(_plural(unknown, 'call') + " Threadline can't trace")
    if notes:
        sentences.append(' · '.join(notes)[0].upper() + ' · '.join(notes)[1:] + '.')
    return ' '.join(sentences)


def callers(model, index, symbol_id):
    """Non-test definitions whose calls resolve to the method, surest first."""
    scopes, rows = model['scopes'], {}
    for caller, call in index['callers'].get(symbol_id, []):
        scope = scopes[caller]
        if caller in index['owner'] or caller == symbol_id or testlinks.is_test_file(scope['file']):
            continue
        current = rows.get(caller)
        if current and (current['status'] == 'supported' or call['status'] != 'supported'):
            continue
        rows[caller] = {'id': caller, 'name': scope['qualified'], 'file': scope['file'], 'line': scope['span']['start'],
                        'span': scope['span'], 'status': call['status'], 'callsite': call['span'], 'reason': call['reason']}
    return sorted(rows.values(), key=lambda row: (row['status'] != 'supported', row['file'], row['line']))
