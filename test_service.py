import tempfile
import unittest
from pathlib import Path

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

    def test_snapshot_queries_are_bounded_and_consistent(self):
        summary=self.store.summary(limit=1)
        self.assertEqual(summary['schemaVersion'],'1.0')
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

    def test_malformed_project_metadata_is_not_executed_or_trusted(self):
        (self.root/'pyproject.toml').write_text('project = 3\ntool = ["unexpected"]\n')
        self.assertTrue(self.store.summary()['entrypoints']['items'])
