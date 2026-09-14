import ast
import tempfile
import unittest
from pathlib import Path
from threadline.analyzer import Analyzer, analyze


class AnalyzerTests(unittest.TestCase):
    def inspect(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        return root, analyze(root)

    def scope(self, result, name):
        return next(s for s in result['scopes'].values() if s['qualified'] == name)

    def test_payload_output_is_local_and_preserves_declared_contract(self):
        _, result = self.inspect({'api.py': """@router.post('/', response_model=Reply)
def endpoint(payload: Request) -> Record:
    def nested():
        return 'not an endpoint output'
    if payload:
        return save(payload)
    return None
transform = lambda item: item.strip()
def empty():
    pass
"""})
        scope = self.scope(result, 'endpoint')
        self.assertEqual(scope['params'][0]['annotation'], 'Request')
        self.assertEqual(scope['output'], {
            'annotation': 'Record', 'responseModel': 'Reply',
            'returns': ['save(payload)', 'None'],
        })
        expression = next(s for s in result['scopes'].values() if s['kind'] == 'lambda')
        self.assertEqual(expression['output']['returns'], ['item.strip()'])
        self.assertEqual(self.scope(result, 'empty')['output']['returns'], [])

    def test_index_and_snapshot_without_execution(self):
        root, result = self.inspect({'main.py': '''raise RuntimeError("MUST NOT EXECUTE")
class Widget:
    def run(self, arg):
        def nested():
            return arg
        return lambda x: nested() + x
''', 'bad.py': 'def invalid('})
        self.assertEqual(result['coverage']['files'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['coverage']['kinds']['method'], 1)
        self.assertEqual(result['coverage']['kinds']['nested function'], 1)
        self.assertEqual(result['coverage']['kinds']['lambda'], 1)
        self.assertEqual(result['files']['main.py']['source'], (root / 'main.py').read_text())
        self.assertEqual(result['coverage']['statements'], result['coverage']['representedStatements'])

    def test_all_control_regions_and_exits(self):
        _, result = self.inspect({'logic.py': '''async def review(items, resource):
    try:
        async with resource:
            for item in items:
                if item is None:
                    continue
                elif item < 0:
                    break
                else:
                    await resource.write(item)
            else:
                return "exhausted"
    except ValueError:
        raise
    else:
        return "ok"
    finally:
        resource.close()
'''} )
        scope = self.scope(result, 'review')
        nodes = list(Analyzer.walk_flow(scope['flow']))
        kinds = {n['kind'] for n in nodes}
        self.assertTrue({'Try', 'AsyncWith', 'For', 'If', 'Continue', 'Break', 'Return', 'Raise'} <= kinds)
        protected = scope['flow'][0]
        self.assertEqual(len(protected['branches']), 4)
        self.assertIn('Finally', protected['branches'][-1]['label'])
        self.assertEqual(len(next(n for n in nodes if n['kind'] == 'For')['branches']), 2)
        self.assertEqual(result['coverage']['calls'], result['coverage']['representedCalls'])

    def test_call_binding_and_cross_file_resolution(self):
        _, result = self.inspect({'helper.py': 'def clean(value, *, mode="trim"):\n    return value.strip()\n',
                                  'api.py': 'from helper import clean\ndef handle(request):\n    result = clean(request.email, mode="lower")\n    return result\n'})
        call = self.scope(result, 'handle')['flow'][0]['calls'][0]
        self.assertEqual(call['status'], 'supported')
        self.assertEqual(call['destination'], 'result')
        mappings = call['bindings'][call['targets'][0]]
        self.assertEqual([(p['argument'],p['parameter']) for p in mappings], [('request.email','value'), ('\'lower\'','mode')])

    def test_nested_call_order_and_short_circuit(self):
        _, result = self.inspect({'logic.py': 'def f(a):\n    return a and outer(inner(a)) if check(a) else fallback()\n'})
        node = self.scope(result, 'f')['flow'][0]
        self.assertTrue(any('Conditional value' in d['label'] for d in node['decisions']))
        self.assertTrue(any('Short-circuit' in d['label'] for d in node['decisions']))
        names = [c['name'] for c in node['calls']]
        self.assertLess(names.index('inner'), names.index('outer'))
        self.assertTrue(all(c['conditional'] for c in node['calls']))

    def test_recursion_dynamic_calls_and_occurrences(self):
        _, result = self.inspect({'logic.py': 'def recurse(n, callback):\n    callback(n)\n    callback(n)\n    return recurse(n-1) if n else None\n'})
        scope = self.scope(result, 'recurse')
        calls = [c for n in Analyzer.walk_flow(scope['flow']) for c in n['calls']]
        self.assertNotEqual(calls[0]['id'], calls[1]['id'])
        self.assertEqual(calls[0]['status'], 'unknown')
        self.assertIn(scope['id'], calls[-1]['targets'])

    def test_match_comprehension_and_assert(self):
        _, result = self.inspect({'logic.py': '''def f(xs):
    assert xs
    values = [transform(x) for x in xs if keep(x)]
    match values:
        case [first, *_] if first:
            return first
        case _:
            return None
'''} )
        scope = self.scope(result,'f')
        self.assertEqual(len(scope['flow'][0]['branches']), 2)
        self.assertTrue(scope['flow'][1]['decisions'])
        self.assertEqual(len(scope['flow'][2]['branches']), 2)
        self.assertEqual(result['coverage']['calls'],result['coverage']['representedCalls'])

    def test_exact_unicode_multiline_spans_and_repeated_names(self):
        source = 'def alpha():\n    café = combine(\n        1,\n        2,\n    )\n    return café\n\nclass C:\n    def alpha(self):\n        return 0\n'
        _, result = self.inspect({'x.py': source})
        call = self.scope(result, 'alpha')['flow'][0]['calls'][0]
        self.assertEqual((call['span']['start'],call['span']['end']), (2,5))
        self.assertIn('combine(', '\n'.join(result['files']['x.py']['source'].splitlines()[1:5]))
        self.assertNotEqual(self.scope(result,'alpha')['id'],self.scope(result,'C.alpha')['id'])

    def test_coroutine_creation_is_deferred_and_scheduling_is_distinct(self):
        _, result=self.inspect({'x.py': 'import asyncio\nasync def work():\n    return 1\ndef start():\n    pending = work()\n    asyncio.create_task(pending)\n'})
        scope=self.scope(result,'start')
        self.assertTrue(scope['flow'][0]['calls'][0]['execution'].startswith('deferred coroutine'))
        self.assertTrue(scope['flow'][1]['calls'][0]['execution'].startswith('background scheduling'))

    def test_instance_targets_are_possible_and_library_targets_external(self):
        _, result = self.inspect({'events.py': 'class Bus:\n    def publish(self, data):\n        return data\nbus = Bus()\n',
                                  'api.py': 'from events import bus\nfrom sqlalchemy.ext.asyncio import AsyncSession\ndef send(db: AsyncSession, payload):\n    db.commit()\n    bus.publish(payload)\n'})
        scope=self.scope(result,'send')
        db_call=scope['flow'][0]['calls'][0]
        bus_call=scope['flow'][1]['calls'][0]
        self.assertEqual(db_call['status'],'external')
        self.assertEqual(bus_call['status'],'possible')
        self.assertEqual(result['scopes'][bus_call['targets'][0]]['qualified'],'Bus.publish')

    def test_constructor_and_unpacking_bindings(self):
        _, result=self.inspect({'x.py': 'class C:\n    def __init__(self, value, *, flag=True):\n        self.value=value\ndef f(args, kwargs):\n    return C(*args, **kwargs)\n'})
        call=self.scope(result,'f')['flow'][0]['calls'][0]
        bindings=call['bindings'][call['targets'][0]]
        self.assertEqual(bindings[0]['argument'],'new instance (implicit)')
        self.assertTrue(any('unresolved' in b['parameter'] for b in bindings))

    def test_decorators_defaults_generators_and_exception_groups(self):
        _, result=self.inspect({'x.py': 'def decorate(x):\n    return x\n@decorate\ndef f(value=default()):\n    try:\n        yield from (transform(x) for x in value if keep(x))\n    except* ValueError:\n        report()\n'})
        self.assertEqual(result['coverage']['statements'],result['coverage']['representedStatements'])
        self.assertEqual(result['coverage']['calls'],result['coverage']['representedCalls'])
        scope=self.scope(result,'f')
        self.assertEqual(scope['flow'][0]['kind'],'TryStar')
        self.assertTrue(scope['decorators'])

    def test_every_repository_statement_and_call_has_source_evidence(self):
        root=Path(__file__).parent/'example'
        result=analyze(root)
        self.assertFalse(result['errors'])
        self.assertEqual(result['coverage']['statements'],result['coverage']['representedStatements'])
        self.assertEqual(result['coverage']['calls'],result['coverage']['representedCalls'])
        self.assertFalse(result['coverage']['unmodeledCalls'])
        for scope in result['scopes'].values():
            for node in Analyzer.walk_flow(scope['flow']):
                source=result['files'][node['span']['file']]
                self.assertEqual(node['span']['hash'],source['hash'])
                self.assertGreaterEqual(node['span']['start'],1)
                self.assertLessEqual(node['span']['end'],source['lines'])

    def test_flat_application_directory_and_explicit_source_root_resolve_imports(self):
        root, result = self.inspect({'server/main.py': """from routers.jobs import run
def start():
    return run()
""", 'server/routers/jobs.py': """def run():
    return 1
"""})
        call=self.scope(result,'start')['flow'][0]['calls'][0]
        self.assertEqual(call['status'],'supported')
        explicit=analyze(root,source_roots=['server'])
        call=self.scope(explicit,'start')['flow'][0]['calls'][0]
        self.assertEqual(call['status'],'supported')
        with self.assertRaises(ValueError): analyze(root,source_roots=['../outside'])

    def test_symlink_and_environment_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.venv').mkdir()
            (root/'.venv'/'bad.py').write_text('broken(')
            (root/'main.py').write_text('x = 1\n')
            (root/'link.py').symlink_to(root/'main.py')
            result=analyze(root)
            self.assertEqual(result['coverage']['files'],1)
            self.assertEqual(len(result['excluded']),2)


if __name__ == '__main__':
    unittest.main()
