"""Independent, manually authored call-resolution checks; fixtures are never run."""
import argparse
import json
import tempfile
import unittest
from pathlib import Path

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
