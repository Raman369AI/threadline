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

    def test_source_hash_and_ast_use_one_read_even_if_file_changes(self):
        import hashlib
        from unittest.mock import patch
        from threadline.analyzer import read_source_bytes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'source.py';original=b'def value():\n    return 1\n';path.write_bytes(original)
            def read_then_edit(target, allowed_root, *args):
                raw=read_source_bytes(target,allowed_root,*args)
                if target==path: path.write_bytes(b'def value():\n    return 2\n')
                return raw
            with patch('threadline.analyzer.read_source_bytes',side_effect=read_then_edit): result=analyze(root)
            self.assertEqual(result['files']['source.py']['hash'],hashlib.sha256(original).hexdigest())
            self.assertEqual(result['files']['source.py']['source'],original.decode())
            self.assertEqual(self.scope(result,'value')['output']['returns'],['1'])

    def test_file_and_ast_budgets_fail_explicitly(self):
        from unittest.mock import patch
        from threadline.analyzer import AnalysisLimitError, read_source_bytes
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'large.py';path.write_text('value = 123456789\n')
            with self.assertRaises(AnalysisLimitError):read_source_bytes(path,root,4)
            with patch('threadline.analyzer.MAX_AST_NODES',1):
                with self.assertRaises(AnalysisLimitError):analyze(root)

    def test_namespace_packages_resolve_cross_root_calls_with_exact_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name, source in {'one/acme/orders/api.py':'from acme.shared.clean import clean\ndef handle(value):\n    return clean(value)\n','two/acme/shared/clean.py':'def clean(value):\n    return value.strip()\n'}.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
            result=analyze(root,source_roots=['one','two'])
            call=self.scope(result,'handle')['flow'][0]['calls'][0]
            self.assertEqual(call['status'],'supported')
            self.assertEqual(result['scopes'][call['targets'][0]]['file'],'two/acme/shared/clean.py')
            self.assertEqual(call['span']['hash'],result['files']['one/acme/orders/api.py']['hash'])

    def test_decorated_routes_and_instance_dispatch_remain_possible(self):
        _,result=self.inspect({'app.py':"""@router.get('/')
def endpoint(value):
    return value
class View:
    def get(self, request):
        return endpoint(request)
def handle(view: View, request):
    return view.get(request)
"""})
        for name in ('View.get','handle'):
            call=self.scope(result,name)['flow'][0]['calls'][0]
            self.assertEqual(call['status'],'possible')

    def test_import_receiver_shadowing_and_duplicate_definitions_are_not_confirmed(self):
        _,result=self.inspect({'helper.py':'def clean(value):\n    return value\n', 'api.py':"""import helper
def handle(helper, value):
    return helper.clean(value)
if flag:
    def choose():
        return 1
else:
    def choose():
        return 2
def run():
    return choose()
"""})
        call=self.scope(result,'handle')['flow'][0]['calls'][0]
        self.assertEqual(call['status'],'possible')
        self.assertNotIn(self.scope(result,'handle')['id'],self.scope(result,'clean')['callers'])
        call=self.scope(result,'run')['flow'][0]['calls'][0]
        self.assertEqual(call['status'],'possible')
        self.assertEqual(len(call['targets']),2)

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
        by_name = {call['name']: call for call in node['calls']}
        self.assertFalse(by_name['check']['conditional'])
        self.assertTrue(all(by_name[name]['conditional'] for name in ('inner', 'outer', 'fallback')))

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

    def test_common_object_oriented_receivers_and_distinct_chained_calls(self):
        _, result = self.inspect({
            'pkg/repo.py': '''class Repo:
    def get(self, key):
        return key
''',
            'app.py': '''import pkg.repo
import pkg.repo as r
from pkg.repo import Repo
class Base:
    def helper(self):
        return 1
class Service(Base):
    def __init__(self, repo: Repo):
        self.repo = repo
    def entry(self, key):
        return self.repo.get(key), self.helper(), pkg.repo.Repo().get(key), r.Repo().get(key)
def dotted():
    return pkg.repo.Repo().get(1)
''',
        })
        calls = [call for node in Analyzer.walk_flow(self.scope(result, 'Service.entry')['flow'])
                 for call in node['calls']]
        by_name = {call['name']: call for call in calls}
        for name, qualified in (('self.repo.get', 'Repo.get'), ('self.helper', 'Base.helper'),
                                ('pkg.repo.Repo().get', 'Repo.get'), ('r.Repo().get', 'Repo.get')):
            call = by_name[name]
            self.assertEqual(call['status'], 'possible', name)
            self.assertEqual([result['scopes'][target]['qualified'] for target in call['targets']], [qualified])
            self.assertEqual(call['bindings'][call['targets'][0]][-1]['parameter'], 'key' if qualified == 'Repo.get' else 'self')
            self.assertEqual(call['receiverBindings'][call['targets'][0]]['mode'], 'implicit')
            self.assertEqual(call['receiverBindings'][call['targets'][0]]['certainty'], 'possible')
        evidence = by_name['self.repo.get']['candidateEvidence']
        self.assertEqual([row['span']['start'] for row in evidence], [9, 8])
        self.assertTrue(all(row['span']['hash'] == result['files']['app.py']['hash'] for row in evidence))
        all_ids = [call['id'] for call in calls]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(result['coverage']['calls'], result['coverage']['representedCalls'])

    def test_local_binding_constructs_and_class_namespace_do_not_invent_calls(self):
        _, result = self.inspect({'x.py': '''import pkg as module
def helper():
    return 1
class Example:
    def method(self):
        return 2
    def entry(self):
        return method()
def loop(callbacks):
    for helper in callbacks:
        helper()
def context(ctx):
    with ctx as helper:
        helper()
def unpack(values):
    helper, other = values
    helper()
def walrus(callback):
    if helper := callback:
        helper()
def pattern(value):
    match value:
        case [helper]:
            helper()
def comprehension(callbacks):
    [helper() for helper in callbacks]
    return helper()
def imported_comprehension(modules):
    [module.clean() for module in modules]
''', 'pkg.py': 'def clean(): return 1\n'})
        for qualified in ('loop', 'context', 'unpack', 'walrus', 'pattern'):
            call = next(call for node in Analyzer.walk_flow(self.scope(result, qualified)['flow'])
                        for call in node['calls'] if call['name'] == 'helper')
            self.assertEqual((call['status'], call['targets']), ('unknown', []), qualified)
        class_call = self.scope(result, 'Example.entry')['flow'][0]['calls'][0]
        self.assertEqual((class_call['status'], class_call['targets']), ('unknown', []))
        comp_calls = [call for node in Analyzer.walk_flow(self.scope(result, 'comprehension')['flow'])
                      for call in node['calls']]
        self.assertEqual([call['status'] for call in comp_calls], ['unknown', 'supported'])
        imported_comp = self.scope(result, 'imported_comprehension')['flow'][0]['calls'][0]
        self.assertEqual((imported_comp['status'], imported_comp['targets']), ('unknown', []))
        self.assertEqual(self.scope(result, 'helper')['callers'], [self.scope(result, 'comprehension')['id']])

    def test_calls_before_local_binding_are_not_marked_supported(self):
        _, result = self.inspect({'app.py': '''def later_import():
    clean()
    from helpers import clean
def later_definition():
    clean()
    def clean(): return 1
clean()
def clean(): return 2
if flag:
    def conditional(): return 3
conditional()
''', 'helpers.py': 'def clean(): return 4\n'})
        for qualified in ('later_import', 'later_definition'):
            call = self.scope(result, qualified)['flow'][0]['calls'][0]
            self.assertEqual(call['status'], 'possible', qualified)
            self.assertEqual(call['reasonCode'], 'binding_not_established')
            self.assertIn('may not be bound before this call', call['reason'])
        module = next(scope for scope in result['scopes'].values()
                      if scope['kind'] == 'module' and scope['file'] == 'app.py')
        calls = [call for node in module['flow'] for call in node['calls']]
        self.assertEqual([call['status'] for call in calls if call['name'] in ('clean', 'conditional')],
                         ['possible', 'possible'])

    def test_explicit_unbound_and_module_function_arguments_are_not_shifted(self):
        _, result = self.inspect({'models.py': '''class Repo:
    def get(self, key):
        return key
def plain(self, key):
    return key
''', 'app.py': '''import models
def run():
    models.Repo.get(models.Repo(), 4)
    models.plain('receiver', 4)
'''})
        calls = [call for node in Analyzer.walk_flow(self.scope(result, 'run')['flow'])
                 for call in node['calls']]
        unbound = next(call for call in calls if call['name'] == 'models.Repo.get')
        plain = next(call for call in calls if call['name'] == 'models.plain')
        self.assertEqual(unbound['status'], 'supported')
        self.assertEqual([(row['argument'], row['parameter']) for row in unbound['bindings'][unbound['targets'][0]]],
                         [('models.Repo()', 'self'), ('4', 'key')])
        self.assertEqual(unbound['receiverBindings'][unbound['targets'][0]]['mode'], 'explicit')
        self.assertEqual([(row['argument'], row['parameter']) for row in plain['bindings'][plain['targets'][0]]],
                         [("'receiver'", 'self'), ('4', 'key')])
        self.assertEqual(plain['receiverBindings'][plain['targets'][0]]['mode'], 'not-applicable')

    def test_classmethod_binds_class_for_instance_and_class_access(self):
        _, result = self.inspect({'x.py': '''class Service:
    @classmethod
    def build(cls, value): return value
    def entry(self):
        return self.build(4), Service.build(5)
'''})
        calls = {call['name']: call for call in self.scope(result, 'Service.entry')['flow'][0]['calls']}
        instance = calls['self.build']
        class_call = calls['Service.build']
        self.assertEqual(instance['bindings'][instance['targets'][0]][0]['argument'], 'type(self) (implicit)')
        self.assertEqual(class_call['bindings'][class_call['targets'][0]][0]['argument'], 'Service (implicit class)')
        self.assertEqual(instance['receiverBindings'][instance['targets'][0]]['mode'], 'implicit')

    def test_expression_guards_unreachable_calls_and_caller_index(self):
        _, result = self.inspect({'x.py': '''def yes(): return 1
def no(): return 0
def danger(): return -1
def entry(flag):
    return yes() if flag else no()
    danger()
'''})
        entry = self.scope(result, 'entry')
        calls = [call for node in Analyzer.walk_flow(entry['flow']) for call in node['calls']]
        branches = {call['name']: call['guards'][0]['branch'] for call in calls[:2]}
        self.assertEqual(branches, {'yes': 'true', 'no': 'false'})
        self.assertTrue(calls[2]['unreachable'])
        self.assertNotIn(entry['id'], self.scope(result, 'danger')['callers'])
        self.assertEqual(calls[2]['executionContext']['kind'], 'function body')

    def test_first_comprehension_iterable_is_not_guarded_by_iteration(self):
        _, result = self.inspect({'x.py': '''def source(): return [1]
def visit(x): return x
def entry():
    return [visit(x) for x in source()]
'''})
        calls = {call['name']: call for call in self.scope(result, 'entry')['flow'][0]['calls']}
        self.assertEqual(calls['source']['guards'], [])
        self.assertFalse(calls['source']['conditional'])
        self.assertEqual(calls['visit']['guards'][0]['kind'], 'comprehension')
        self.assertTrue(calls['visit']['conditional'])

    def test_class_comprehension_body_cannot_see_class_names(self):
        _, result = self.inspect({'x.py': '''class Example:
    def helper(): return [1]
    values = [helper() for _ in helper()]
'''})
        operations = self.scope(result, 'Example')['flow']
        calls = [call for node in operations for call in node['calls'] if call['name'] == 'helper']
        self.assertEqual(len(calls), 2)
        self.assertEqual([call['status'] for call in calls], ['unknown', 'supported'])
        self.assertFalse(calls[1]['conditional'])

    def test_generator_first_iterable_is_eager_but_element_is_deferred(self):
        _, result = self.inspect({'x.py': '''def source(): return [1]
def visit(x): return x
def entry():
    return (visit(x) for x in source())
'''})
        calls = {call['name']: call for call in self.scope(result, 'entry')['flow'][0]['calls']}
        self.assertEqual(calls['source']['executionContext'], {'kind': 'function body', 'deferred': False})
        self.assertEqual(calls['visit']['executionContext'], {'kind': 'generator expression', 'deferred': True})

    def test_shadowed_super_does_not_infer_base_member(self):
        _, result = self.inspect({'x.py': '''class Base:
    def helper(self): return 1
class Child(Base):
    def entry(self, super): return super().helper()
'''})
        call = next(call for call in self.scope(result, 'Child.entry')['flow'][0]['calls']
                    if call['name'] == 'super().helper')
        self.assertEqual((call['status'], call['targets']), ('unknown', []))

    def test_known_multiple_inheritance_uses_c3_order(self):
        _, result = self.inspect({'x.py': '''class Left:
    def helper(self): return 1
class Right:
    def helper(self): return 2
class Child(Left, Right):
    def entry(self): return self.helper(), super().helper()
class Base:
    def work(self): return 1
class First(Base): pass
class Second(Base):
    def work(self): return 2
class Diamond(First, Second):
    def entry(self): return self.work()
class UnknownBase(ExternalBase, Left):
    def entry(self): return self.helper()
'''})
        child_calls = [call for call in self.scope(result, 'Child.entry')['flow'][0]['calls']
                       if call['name'].endswith('.helper')]
        self.assertEqual(len(child_calls), 2)
        for call in child_calls:
            self.assertEqual(call['status'], 'possible')
            self.assertEqual([result['scopes'][target]['qualified'] for target in call['targets']], ['Left.helper'])
        diamond = self.scope(result, 'Diamond.entry')['flow'][0]['calls'][0]
        self.assertEqual([result['scopes'][target]['qualified'] for target in diamond['targets']], ['Second.work'])
        uncertain = self.scope(result, 'UnknownBase.entry')['flow'][0]['calls'][0]
        self.assertEqual(uncertain['status'], 'possible')
        self.assertEqual([result['scopes'][target]['qualified'] for target in uncertain['targets']], ['Left.helper'])

    def test_property_result_is_not_the_getter_call_target(self):
        _, result = self.inspect({'x.py': '''class Service:
    @property
    def handler(self): return lambda: 1
    def entry(self): return self.handler()
def external(service: Service): return service.handler()
'''})
        for qualified in ('Service.entry', 'external'):
            call = self.scope(result, qualified)['flow'][0]['calls'][0]
            self.assertEqual((call['status'], call['targets']), ('unknown', []))
            self.assertEqual(call['reasonCode'], 'descriptor_result')
            self.assertIn('callable result', call['reason'])
        self.assertEqual(self.scope(result, 'Service.handler')['callers'], [])

    def test_conflicting_instance_assignments_remain_possible(self):
        _, result = self.inspect({'x.py': '''class RepoA:
    def get(self): return 1
class RepoB:
    def get(self): return 2
class Service:
    def __init__(self, flag):
        self.repo = RepoA() if flag else RepoB()
    def entry(self):
        return self.repo.get()
'''})
        call = self.scope(result, 'Service.entry')['flow'][0]['calls'][0]
        self.assertEqual(call['status'], 'possible')
        self.assertEqual({result['scopes'][target]['qualified'] for target in call['targets']},
                         {'RepoA.get', 'RepoB.get'})

    def test_annotated_instance_assignment_has_source_provenance(self):
        _, result = self.inspect({'x.py': '''class Repo:
    def get(self): return 1
class Service:
    def __init__(self):
        self.repo: Repo = Repo()
    def entry(self): return self.repo.get()
'''})
        call = self.scope(result, 'Service.entry')['flow'][0]['calls'][0]
        self.assertEqual(call['status'], 'possible')
        self.assertEqual([result['scopes'][target]['qualified'] for target in call['targets']], ['Repo.get'])
        self.assertEqual([proof['span']['start'] for proof in call['candidateEvidence']], [5])
        self.assertEqual(call['candidateEvidence'][0]['receiverType'], 'Repo')

    def test_manifest_router_prefix_and_effect_tokens(self):
        _, result = self.inspect({'api.py': '''router = APIRouter(prefix='/v1')
def entry(x, bag):
    x.address()
    bag.add(1)
''', 'bad.py': 'def broken('})
        self.assertEqual(result['routerPrefixes']['api.py:router'], '/v1')
        self.assertEqual(result['discoveryManifest']['bad.py']['status'], 'error')
        self.assertIsNotNone(result['discoveryManifest']['bad.py']['hash'])
        nodes = self.scope(result, 'entry')['flow']
        self.assertFalse(any('possible effect' in effect for effect in nodes[0]['effects']))
        self.assertTrue(any('possible effect: bag.add' == effect for effect in nodes[1]['effects']))

    def test_global_enclosing_and_lazy_type_alias_scopes_remain_distinct(self):
        _, result = self.inspect({'case.py': '''def helper():
    return 1
class Box:
    def local():
        return 2
    type Alias = local()
    def entry(self):
        return helper()
def outer():
    def inner():
        return helper()
    return inner()
'''})
        method_call = self.scope(result, 'Box.entry')['flow'][0]['calls'][0]
        enclosing_call = self.scope(result, 'outer.inner')['flow'][0]['calls'][0]
        self.assertEqual(method_call['status'], 'supported')
        self.assertEqual(enclosing_call['status'], 'supported')
        alias_call = next(call for node in Analyzer.walk_flow(self.scope(result, 'Box')['flow'])
                          for call in node['calls'] if call['name'] == 'local')
        self.assertEqual(alias_call['status'], 'supported')
        self.assertEqual(alias_call['executionContext'], {'kind': 'type alias value', 'deferred': True})
        self.assertTrue(alias_call['execution'].startswith('deferred type alias'))

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
