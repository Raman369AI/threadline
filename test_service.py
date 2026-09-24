import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from threadline.service import SnapshotStore, ThreadlineError


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'api.py').write_text("""from service import service
@router.post('/items', response_model=Reply)
def create(payload: Request):
    if payload.ok:
        return service(payload.value)
    return None
""")
        (self.root/'service.py').write_text("""def helper(value):
    return value.strip()
def service(value):
    cleaned = helper(value)
    notify(cleaned)
    return cleaned
""")
        (self.root/'pyproject.toml').write_text('[project.scripts]\nexample = "api:create"\n')
        self.store=SnapshotStore(self.root,retention=2)

    def test_start_catalog_keeps_routes_commands_tasks_and_methods_independent(self):
        source = 'from fastapi import APIRouter\nrouter = APIRouter(prefix="/api")\n'
        source += ''.join(f'@router.get("/items/{i}")\ndef route_{i}():\n    return {i}\n' for i in range(35))
        source += "@router.websocket('/live')\nasync def live():\n    pass\n@shared_task\ndef sync_records():\n    pass\nclass Worker:\n    def __init__(self):\n        pass\n    def execute(self):\n        pass\n"
        (self.root/'routes.py').write_text(source)
        catalog = self.store.starts(limit=6)
        self.assertEqual(catalog['groups']['http']['total'], 37)
        self.assertEqual(catalog['groups']['http']['nextCursor'], 6)
        self.assertTrue(any(row['label'] == 'example' for row in catalog['groups']['commands']['items']))
        self.assertTrue(any(row['name'] == 'sync_records' for row in catalog['groups']['tasks']['items']))
        route = self.store.starts(query='/api/items/34')['results']['items'][0]
        self.assertEqual(route['name'], 'route_34')
        self.assertEqual(route['label'], 'GET /api/items/34')
        for query in ('Worker.__init__', 'Worker.execute', 'sync_records', 'example'):
            result = self.store.starts(query=query)['results']
            self.assertEqual(result['total'], 1)
            self.assertTrue(self.store.get_workflow(result['items'][0]['id'])['stages']['items'])
        page = self.store.starts(category='http', cursor=6, limit=6)
        self.assertEqual(len(page['results']['items']), 6)
        self.assertTrue(all(row['category'] == 'http' for row in page['results']['items']))

    def test_endpoint_verbs_filter_before_pagination(self):
        source = 'from fastapi import APIRouter\nrouter = APIRouter()\n'
        source += ''.join(f'@router.get("/items/{i}")\ndef route_{i}():\n    return {i}\n' for i in range(35))
        source += '@router.api_route("/shared", methods=["GET", "POST"])\ndef shared():\n    pass\n@router.delete("/items")\ndef remove():\n    pass\n'
        (self.root/'verbs.py').write_text(source)
        catalog = self.store.starts(limit=6)
        self.assertTrue({'GET', 'POST', 'DELETE'}.issubset(catalog['httpMethods']))
        post = self.store.starts(category='http', method='POST', limit=6)['results']
        self.assertTrue(any(row['name'] == 'shared' for row in post['items']))
        self.assertTrue(all('POST' in row['httpMethods'] for row in post['items']))
        get = self.store.starts(category='http', method='GET', cursor=30, limit=6)['results']
        self.assertEqual(get['total'], 36)
        self.assertEqual(len(get['items']), 6)
        self.assertTrue(all('GET' in row['httpMethods'] for row in get['items']))
        delete = self.store.starts(category='http', method='DELETE')['results']
        self.assertEqual([row['name'] for row in delete['items']], ['remove'])
        methods = self.store.starts(category='methods')['results']['items']
        self.assertEqual(methods, sorted(methods, key=lambda row: (row['file'], row['line'], row['name'])))

    def test_modules_pick_only_methods_from_selected_file(self):
        for i in range(25):
            (self.root/f'module_{i:02}.py').write_text('class Worker:\n    def run(self):\n        return 1\n    def __init__(self):\n        pass\n')
        modules = self.store.modules(limit=20)['modules']
        self.assertEqual(modules['total'], 27)
        self.assertEqual(modules['nextCursor'], 20)
        self.assertEqual(len(self.store.modules(cursor=20)['modules']['items']), 7)
        match = self.store.modules(query='module_24')['modules']['items']
        self.assertEqual(match, [{'name': 'module_24', 'file': 'module_24.py', 'total': 2}])
        picked = self.store.modules(file='module_24.py')['methods']['items']
        self.assertEqual([row['name'] for row in picked], ['Worker.run', 'Worker.__init__'])
        self.assertTrue(all(row['file'] == 'module_24.py' for row in picked))
        self.assertEqual(self.store.modules(file='module_24.py', query='run')['methods']['total'], 1)
        # Route handlers and script entrypoints remain available through their module.
        self.assertEqual(self.store.modules(file='api.py')['methods']['items'][0]['name'], 'create')
        with self.assertRaises(ThreadlineError): self.store.modules(file='../missing.py')
        with self.assertRaises(ThreadlineError): self.store.modules(limit=101)

    def test_snapshot_queries_are_bounded_and_consistent(self):
        summary=self.store.summary(limit=1)
        self.assertEqual(summary['schemaVersion'],'1.1')
        self.assertEqual(summary['entrypoints']['items'][0]['name'],'create')
        self.assertEqual(summary['entrypoints']['items'][0]['confidence'],'supported')
        found=self.store.find_symbols('service',snapshot_id=summary['snapshotId'],limit=1)
        self.assertEqual(found['symbols']['total'],2)
        symbol=next(item for item in self.store.find_symbols('service',snapshot_id=summary['snapshotId'],limit=10)['symbols']['items'] if item['name']=='service')
        method=self.store.get_method(symbol['id'],snapshot_id=summary['snapshotId'],limit=1)
        self.assertGreater(method['operations']['total'],method['operations']['omitted'])
        with self.assertRaises(ThreadlineError): self.store.find_symbols(limit=101)

    def test_generic_workflow_nests_cross_file_calls_and_retains_unknowns(self):
        summary=self.store.summary()
        entry=summary['entrypoints']['items'][0]['id']
        workflow=self.store.get_workflow(entry,snapshot_id=summary['snapshotId'],limit=100)
        stages=workflow['stages']['items']
        service=next(s for s in stages if s['label']=='service')
        helper=next(s for s in stages if s['label']=='helper')
        notify=next(s for s in stages if s['label']=='notify')
        self.assertEqual(service['parent'],'entry')
        self.assertEqual(helper['parent'],service['id'])
        self.assertEqual(notify['status'],'unknown')
        self.assertTrue(workflow['alternatives']['items'])
        self.assertLessEqual(len(workflow['links']),100)
        self.assertTrue(all(isinstance(item['branches'],list) for item in self.store.get_method(entry,limit=10)['operations']['items']))
        proof=service['evidence'][0]['evidenceId']
        source=self.store.get_source(snapshot_id=summary['snapshotId'],evidence=proof)
        self.assertIn('service(payload.value)',source['source'])

    def test_large_evidence_returns_bounded_original_source_with_continuation(self):
        lines=['def large_handler(payload):']+[f'    value_{index} = payload' for index in range(205)]+['    return payload']
        (self.root/'large.py').write_text('\n'.join(lines)+'\n')
        summary=self.store.summary(refresh=True)
        symbol=next(item for item in self.store.find_symbols('large_handler',snapshot_id=summary['snapshotId'],limit=10)['symbols']['items'] if item['name']=='large_handler')
        source=self.store.get_source(snapshot_id=summary['snapshotId'],evidence=symbol['evidenceId'])
        self.assertEqual(source['evidenceId'],symbol['evidenceId'])
        self.assertEqual(len(source['source'].splitlines()),200)
        self.assertTrue(source['truncated'])
        self.assertEqual(source['nextStart'],source['span']['end']+1)
        self.assertGreater(source['requestedSpan']['end'],source['span']['end'])
        with self.assertRaises(ThreadlineError):
            self.store.get_source(snapshot_id=summary['snapshotId'],file='large.py',start=1,end=201)

    def test_refresh_retains_then_expires_snapshots(self):
        first=self.store.summary()['snapshotId']
        (self.root/'api.py').write_text((self.root/'api.py').read_text()+'\nchanged = 1\n')
        second=self.store.summary(refresh=True)['snapshotId']
        self.assertIs(self.store.model(first),self.store.model(first))
        (self.root/'api.py').write_text((self.root/'api.py').read_text()+'changed_again = 2\n')
        third=self.store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(second,third)
        with self.assertRaises(ThreadlineError): self.store.model(first)

    def test_configuration_only_edit_changes_snapshot_without_rewriting_history(self):
        first=self.store.summary()['snapshotId']
        (self.root/'pyproject.toml').write_text('[project.scripts]\nexample="service:helper"\n')
        second=self.store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(first,second)
        self.assertEqual(self.store.summary(snapshot_id=first)['entrypoints']['items'][0]['name'],'create')
        self.assertEqual(self.store.summary(snapshot_id=second)['entrypoints']['items'][0]['name'],'helper')

    def test_empty_configuration_presence_changes_snapshot_identity(self):
        configuration = self.root / 'pyproject.toml'
        configuration.unlink()
        absent = self.store.summary()['snapshotId']
        configuration.write_text('')
        present_empty = self.store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(absent, present_empty)
        configuration.unlink()
        self.assertEqual(self.store.summary(refresh=True)['snapshotId'], absent)

    def test_configuration_read_failure_is_visible_and_keeps_prior_snapshot(self):
        from threadline import analyzer

        healthy = self.store.summary()
        read_source = analyzer.read_source_bytes

        def fail_configuration(path, root):
            if path.name == 'pyproject.toml':
                raise PermissionError('fixture read failure')
            return read_source(path, root)

        with patch('threadline.analyzer.read_source_bytes', side_effect=fail_configuration):
            failed = self.store.summary(refresh=True)
            failed_model = self.store.model(failed['snapshotId'])
        self.assertNotEqual(healthy['snapshotId'], failed['snapshotId'])
        self.assertEqual(failed['coverage']['discovered'], healthy['coverage']['discovered'])
        self.assertEqual(failed_model['configurationManifest']['error'],
                         'PermissionError: fixture read failure')
        self.assertEqual(failed['diagnostics']['parseErrors']['total'], 0)
        self.assertEqual(failed['diagnostics']['configurationErrors']['total'], 1)
        self.assertEqual(failed['diagnostics']['analysisErrors']['total'], 1)
        error = failed['diagnostics']['configurationErrors']['items'][0]
        self.assertEqual(error['file'], 'pyproject.toml')
        self.assertEqual(error['kind'], 'configuration')
        self.assertIn('fixture read failure', error['message'])
        self.assertEqual(self.store.diagnostics(category='errors')['rows']['items'], [error])
        self.assertEqual(self.store.summary(snapshot_id=healthy['snapshotId'])['diagnostics']['parseErrors']['total'], 0)
        self.assertEqual(self.store.summary(refresh=True)['snapshotId'], healthy['snapshotId'])

    def test_configuration_decode_failure_is_visible(self):
        from threadline import analyzer

        (self.root / 'bad.py').write_text('def broken(:\n')
        read_source = analyzer.read_source_bytes

        def invalid_configuration(path, root):
            if path.name == 'pyproject.toml':
                return b'\xff'
            return read_source(path, root)

        with patch('threadline.analyzer.read_source_bytes', side_effect=invalid_configuration):
            summary = self.store.summary()
            manifest = self.store.model(summary['snapshotId'])['configurationManifest']
        self.assertTrue(manifest['present'])
        self.assertIsNotNone(manifest['hash'])
        self.assertIn('UnicodeDecodeError', manifest['error'])
        self.assertEqual(summary['diagnostics']['parseErrors']['total'], 1)
        self.assertEqual(summary['diagnostics']['configurationErrors']['total'], 1)
        self.assertEqual(summary['diagnostics']['analysisErrors']['total'], 2)
        self.assertEqual(summary['diagnostics']['parseErrors']['items'][0]['file'], 'bad.py')
        error = summary['diagnostics']['configurationErrors']['items'][0]
        self.assertEqual((error['file'], error['kind']), ('pyproject.toml', 'configuration'))
        self.assertEqual({row['file'] for row in self.store.diagnostics(category='errors')['rows']['items']},
                         {'bad.py', 'pyproject.toml'})

    def test_browser_pages_preserve_branch_bodies_and_allow_all_definitions(self):
        (self.root/'many.py').write_text('def many(value):\n'+''.join(f'    value += {i}\n' for i in range(45))+'    if value:\n        return value\n    return 0\n')
        self.store.refresh()
        symbol=self.store.find_symbols('many')['symbols']['items'][0]
        rows=[];cursor=0
        while cursor is not None:
            page=self.store.get_scope(symbol['id'],cursor=cursor,limit=10)
            self.assertLessEqual(len(page['flow']['items']),10)
            rows.extend(page['flow']['items']);cursor=page['flow']['nextCursor']
        self.assertEqual(len(rows),47)
        branch=next(row for row in rows if row['kind']=='If')
        self.assertEqual(branch['branches'][0]['nodes'][0]['kind'],'Return')
        modules=self.store.find_symbols(kind='module')['symbols']['items']
        self.assertTrue(modules)
        self.assertTrue(all(row['kind']=='module' for row in modules))
        self.assertNotIn('source',self.store.summary())

    def test_same_line_call_evidence_preserves_distinct_columns(self):
        from threadline.service import evidence_id
        (self.root/'same_line.py').write_text('def nested():\n    return outer(inner())\n')
        self.store.refresh()
        symbol=self.store.find_symbols('nested')['symbols']['items'][0]
        scope=self.store.model()['scopes'][symbol['id']]
        calls=scope['flow'][0]['calls']
        identifiers=[evidence_id(call['span']) for call in calls]
        self.assertEqual(len(set(identifiers)),2)
        for call,identifier in zip(calls,identifiers):
            source=self.store.get_source(evidence=identifier)
            self.assertEqual(source['requestedSpan'],call['span'])

    def test_workflow_alternatives_continue_after_final_call_stage(self):
        (self.root/'branches.py').write_text('def branches(value):\n'+''.join(f'    if value == {i}:\n        value += 1\n' for i in range(125))+'    return value\n')
        self.store.refresh()
        symbol=self.store.find_symbols('branches')['symbols']['items'][0]
        first=self.store.get_workflow(symbol['id'],limit=100)
        self.assertIsNone(first['stages']['nextCursor'])
        self.assertEqual(first['alternatives']['nextCursor'],100)
        second=self.store.get_workflow(symbol['id'],cursor=100,limit=100)
        self.assertEqual(len(second['alternatives']['items']),25)
        self.assertIsNone(second['alternatives']['nextCursor'])

    def test_deep_call_chain_has_explicit_truncation_instead_of_recursion_failure(self):
        (self.root/'chain.py').write_text('\n'.join(f'def step_{i}():\n    return step_{i+1}()' for i in range(160))+'\ndef step_160():\n    return 1\n')
        self.store.refresh()
        symbol=next(row for row in self.store.find_symbols('step_0')['symbols']['items'] if row['name']=='step_0')
        result=self.store.get_workflow(symbol['id'],limit=100)
        self.assertTrue(result['truncated'])
        next_page=self.store.get_workflow(symbol['id'],cursor=100,limit=100)
        self.assertTrue(any(stage.get('expansionTruncated') for stage in next_page['stages']['items']))

    def test_workflow_pages_reuse_cache_without_mutation_and_expire(self):
        from unittest.mock import patch
        from threadline.workflows import generic_workflow
        entry = self.store.summary()['entrypoints']['items'][0]['id']
        first_id = self.store.current_id
        with patch('threadline.service.generic_workflow', wraps=generic_workflow) as build:
            first = self.store.get_workflow(entry, limit=1)
            first['stages']['items'][0]['label'] = 'mutated by consumer'
            self.store.get_workflow(entry, cursor=1, limit=1)
            again = self.store.get_workflow(entry, limit=1)
            self.assertNotEqual(again['stages']['items'][0]['label'], 'mutated by consumer')
            self.assertEqual(build.call_count, 1)
            for index in range(2):
                path = self.root/'api.py'
                path.write_text(path.read_text()+f'\nrevision_{index} = {index}\n')
                self.store.refresh()
                self.store.get_workflow(entry, limit=1)
            self.assertEqual(build.call_count, 3)
        self.assertFalse(any(key[0] == first_id for key in self.store._workflow_cache))

    def test_workflow_cache_budget_and_concurrent_requests(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from threadline.workflows import generic_workflow
        entry = self.store.summary()['entrypoints']['items'][0]['id']
        with patch('threadline.service.generic_workflow', wraps=generic_workflow) as build:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.store.get_workflow(entry, limit=1), range(4)))
            self.assertEqual(build.call_count, 1)
            self.assertEqual(len(results), 4)
        with patch('threadline.service.MAX_WORKFLOW_CACHE_ENTRIES', 1):
            other = self.store.find_symbols('helper')['symbols']['items'][0]['id']
            self.store.get_workflow(other)
            self.assertEqual(len(self.store._workflow_cache), 1)
        self.assertLessEqual(self.store._workflow_cache_bytes, 16*1024*1024)

    def test_lazy_branch_pages_bound_nested_bodies_and_keep_exact_evidence(self):
        (self.root/'huge.py').write_text('def huge(value):\n    if value:\n'+''.join(
            f'        if value == {i}:\n            value += {i}\n' for i in range(150))+'    return value\n')
        self.store.refresh()
        symbol = self.store.find_symbols('huge')['symbols']['items'][0]['id']
        page = self.store.get_scope(symbol, shallow=True)
        branch = page['flow']['items'][0]['branches'][0]
        self.assertEqual(branch['total'], 150)
        self.assertEqual(branch['nodes'], [])
        rows = []
        cursor = 0
        while cursor is not None:
            result = self.store.get_branch(symbol, branch['operation'], branch['arm'], cursor=cursor, limit=20)
            self.assertLessEqual(len(result['flow']['items']), 20)
            rows.extend(result['flow']['items'])
            cursor = result['flow']['nextCursor']
        self.assertEqual(len(rows), 150)
        self.assertTrue(all(not row['branches'][0]['nodes'] for row in rows))
        nested = rows[-1]['branches'][0]
        leaf = self.store.get_branch(symbol, nested['operation'], nested['arm'])['flow']['items'][0]
        source = self.store.get_source(file=leaf['span']['file'], start=leaf['span']['start'], end=leaf['span']['end'])
        self.assertIn('value += 149', source['source'])
        with self.assertRaises(ThreadlineError): self.store.get_branch(symbol, branch['operation'], -1)
        with self.assertRaises(ThreadlineError): self.store.get_branch(symbol, 'missing', 0)

    def test_malformed_project_metadata_is_not_executed_or_trusted(self):
        (self.root/'pyproject.toml').write_text('project = 3\ntool = ["unexpected"]\n')
        self.assertTrue(self.store.summary()['entrypoints']['items'])

    def test_parse_failure_edits_change_snapshot_and_retained_diagnostics(self):
        store = SnapshotStore(self.root, retention=6)
        clean = store.summary()['snapshotId']
        path = self.root / 'bad.py'
        path.write_text('def broken(:\n')
        added = store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(clean, added)
        self.assertEqual([row['file'] for row in store.summary()['diagnostics']['parseErrors']['items']], ['bad.py'])
        path.write_text('def broken( :\n')
        edited = store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(added, edited)
        self.assertEqual(store.summary(snapshot_id=clean)['diagnostics']['parseErrors']['total'], 0)
        path.write_text('def broken():\n    return 1\n')
        fixed = store.summary(refresh=True)['snapshotId']
        self.assertNotEqual(edited, fixed)
        self.assertEqual(store.summary()['diagnostics']['parseErrors']['total'], 0)
        path.write_text('def broken(:\n')
        broken_again = store.summary(refresh=True)['snapshotId']
        self.assertEqual(broken_again, added)
        path.unlink()
        removed = store.summary(refresh=True)['snapshotId']
        self.assertEqual(removed, clean)
        self.assertEqual(store.summary()['diagnostics']['parseErrors']['total'], 0)

    def test_query_results_are_detached_from_retained_model(self):
        (self.root / 'bad.py').write_text('def bad(:\n')
        self.store.refresh()
        symbol = self.store.find_symbols('create')['symbols']['items'][0]
        scope = self.store.get_scope(symbol['id'])
        scope['scope']['name'] = 'modified by caller'
        scope['flow']['items'][0]['label'] = 'modified by caller'
        method = self.store.get_method(symbol['id'])
        method['operations']['items'][0]['label'] = 'modified by caller'
        diagnostics = self.store.diagnostics(category='errors')
        diagnostics['rows']['items'][0]['message'] = 'modified by caller'
        summary = self.store.summary()
        summary['limits'].clear()
        summary['diagnostics']['parseErrors']['items'][0]['message'] = 'modified by caller'
        self.assertNotEqual(self.store.get_scope(symbol['id'])['scope']['name'], 'modified by caller')
        self.assertNotEqual(self.store.get_scope(symbol['id'])['flow']['items'][0]['label'], 'modified by caller')
        self.assertNotEqual(self.store.get_method(symbol['id'])['operations']['items'][0]['label'], 'modified by caller')
        self.assertNotEqual(self.store.diagnostics(category='errors')['rows']['items'][0]['message'], 'modified by caller')
        self.assertTrue(self.store.summary()['limits'])

    def test_method_and_workflow_keep_the_same_call_semantics(self):
        (self.root / 'contract.py').write_text('''class Repo:
    def get(self, key):
        return key
def entry(flag):
    repo = Repo()
    if flag:
        return repo.get(1)
    return 0
    repo.get(2)
''')
        model = self.store.refresh()
        entry = next(scope for scope in model['scopes'].values()
                     if scope['file'] == 'contract.py' and scope['name'] == 'entry')
        method = self.store.get_method(entry['id'], limit=50)
        workflow = self.store.get_workflow(entry['id'], limit=50)
        calls = [call for operation in method['operations']['items']
                 for call in operation['calls']]
        stages = {stage['id']: stage for stage in workflow['stages']['items']}
        self.assertEqual(len(calls), 3)
        for call in calls:
            stage = stages['call:' + call['id']]
            for field in ('status', 'reasonCode', 'guards', 'receiverBindings', 'unreachable'):
                self.assertEqual(stage[field], call[field])
            self.assertEqual(stage['executionContext']['kind'], call['executionContext']['kind'])
            self.assertEqual(stage['evidenceId'], call['evidenceId'])
