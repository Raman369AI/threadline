"""Independent, manually authored call-resolution and data-flow checks; fixtures are never run."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path

from threadline.dataflow import build_dataflow
from threadline.service import SnapshotStore

CORPUS = Path(__file__).parent / 'tests' / 'semantic_cases.json'


def evaluate():
    rows = []
    for case in json.loads(CORPUS.read_text())['cases']:
        with tempfile.TemporaryDirectory(prefix='threadline-semantics-') as directory:
            root = Path(directory)
            for name, source in case['files'].items():
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
            store = SnapshotStore(root)
            model = store.current
            for expected in case['checks']:
                scope = next(scope for scope in model['scopes'].values() if scope['qualified'] == expected['scope'])
                if expected.get('kind') == 'effects':
                    rows.append(effects_check(case['name'], expected, scope))
                    continue
                if expected.get('kind') in ('changes', 'name'):
                    rows.append(dataflow_check(case['name'], expected, build_dataflow(model, scope['id'])))
                    continue
                operations = store.get_method(scope['id'], limit=100)['operations']['items']
                calls = [call for node in operations for call in node['calls'] if call['name'] == expected['call']]
                if len(calls) != 1:
                    rows.append({'case':case['name'], 'passed':False, 'reason':'Expected exactly one annotated call', 'falseSupported':False})
                    continue
                call = calls[0]
                targets = {model['scopes'][target]['file']+':'+model['scopes'][target]['qualified'] for target in call['targets']}
                allowed = set(expected['allowedTargets'])
                required = set(expected.get('requiredTargets', []))
                false_supported = call['status'] == 'supported' and ('supported' not in expected['allowedStatuses'] or not targets or not targets <= allowed)
                evidence = store.get_source(evidence=call['evidenceId'])
                valid = (call['status'] in expected['allowedStatuses'] and required <= targets <= allowed
                         and evidence['requestedSpan'] == call['span'] and expected['call'] in evidence['source'])
                rows.append({'case':case['name'], 'status':call['status'], 'targets':sorted(targets),
                             'directTarget':expected['directTarget'], 'falseSupported':false_supported,
                             'missingRequiredTargets':sorted(required - targets),
                             'passed':valid, 'evidenceId':call['evidenceId']})
    direct = [row for row in rows if row.get('directTarget')]
    return {'cases':len(rows), 'passed':all(row['passed'] for row in rows),
            'falseSupported':sum(row['falseSupported'] for row in rows),
            'unresolved':sum(row.get('status') == 'unknown' for row in rows),
            'directTargetsResolved':sum(row.get('status') == 'supported' for row in direct),
            'directTargetsAnnotated':len(direct), 'results':rows,
            'scope':'Curated source expectations, not execution observations or a complete semantic oracle.'}


def effects_check(case, expected, scope):
    """`effects`: effect classes a method must have (with optional certainty, detail, and first hop) or must not."""
    effects = scope.get('sideEffects', [])
    def matches(want, effect):
        return (effect['effect'] == want['effect']
                and want.get('certainty', effect['certainty']) == effect['certainty']
                and want.get('detail', effect.get('detail')) == effect.get('detail')
                and ('via' not in want or effect['via'][:1] == [want['via']])
                and ('direct' not in want or (not effect['via']) == want['direct']))
    missing = [want for want in expected.get('mustHave', []) if not any(matches(want, effect) for effect in effects)]
    present = {effect['effect'] for effect in effects}
    unexpected = sorted(set(expected.get('mustNotHave', [])) & present)
    return {'case': case, 'check': 'effects', 'scope': expected['scope'],
            'effects': sorted({f"{e['effect']}{' ' + e['detail'] if e.get('detail') else ''} ({e['certainty']}{', via ' + e['via'][0] if e['via'] else ''})" for e in effects}),
            'missing': missing, 'unexpected': unexpected, 'passed': not missing and not unexpected, 'falseSupported': False}


def dataflow_check(case, expected, flow):
    """`changes`: names a method may change; `name`: what a name read inside a method refers to."""
    if expected['kind'] == 'changes':
        changed = {node['name'] for node in flow['nodes'] if node['kind'] in ('object_state', 'field')}
        missing = set(expected.get('mustChange', [])) - changed
        unexpected = set(expected.get('mustNotChange', [])) & changed
        return {'case': case, 'check': 'changes', 'scope': expected['scope'], 'changed': sorted(changed),
                'passed': not missing and not unexpected, 'falseSupported': False}
    kinds = {node['kind'] for node in flow['nodes'] if node['name'] == expected['name'] and node['kind'] != 'output'}
    gaps = [gap for gap in flow['gaps'] if gap['kind'] == 'unbound_read' and gap.get('expression') == expected['name']]
    if expected.get('mustBeUnbound'):
        # The name is out of scope at this read, e.g. after its comprehension or except clause.
        passed = bool(gaps)
    elif 'allowedKinds' in expected:
        # A name local to a comprehension may leave no outside node at all; it must never be unbound.
        passed = kinds <= set(expected['allowedKinds']) and not gaps
    else:
        passed = kinds == {expected['expectedKind']} and (expected['expectedKind'] == 'external' or not gaps)
    return {'case': case, 'check': 'name', 'scope': expected['scope'], 'name': expected['name'],
            'kinds': sorted(kinds), 'passed': passed, 'falseSupported': False}


class SemanticAccuracyTests(unittest.TestCase):
    def test_manual_call_resolution_corpus(self):
        result = evaluate()
        self.assertEqual(result['falseSupported'], 0, result)
        self.assertTrue(result['passed'], result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = evaluate()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
