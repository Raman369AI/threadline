import tempfile
import unittest
from pathlib import Path

from threadline.analyzer import analyze
from threadline.service import SnapshotStore
from threadline.workflows import generic_workflow


class WorkflowTests(unittest.TestCase):
    def workflow_for(self, source, name='entry'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'app.py').write_text(source)
        model = analyze(root)
        scope = next(scope for scope in model['scopes'].values() if scope['qualified'] == name)
        return generic_workflow(model, scope['id'])

    def test_workflow_preserves_expression_choice_and_unreachable_call(self):
        workflow = self.workflow_for('''def yes():
    return 1
def no():
    return 0
def entry(flag):
    value = yes() if flag else no()
    return value
    yes()
''')
        choices = [row for row in workflow['alternatives'] if row['kind'] == 'expression']
        self.assertTrue(any('Conditional value' in row['label'] for row in choices))
        branches = [stage for stage in workflow['stages'] if stage['label'] in ('yes', 'no')]
        self.assertEqual(len(branches), 3)
        self.assertTrue(all(stage['conditional'] for stage in branches[:2]))
        self.assertEqual([stage['guards'][0]['branch'] for stage in branches[:2]], ['true', 'false'])
        self.assertTrue(branches[-1]['unreachable'])
        self.assertTrue(any(row['status'] == 'unreachable' for row in workflow['uncertainties']))

    def test_constructing_class_does_not_replay_class_body(self):
        workflow = self.workflow_for('''def register():
    return 1
class Repo:
    value = register()
    def __init__(self):
        self.ready = True
def entry():
    return Repo()
''')
        labels = [stage['label'] for stage in workflow['stages']]
        self.assertEqual(labels, ['entry', 'Repo'])
        constructor = workflow['stages'][1]
        self.assertTrue(constructor['construction'])
        self.assertEqual(len(constructor['constructorCandidates']), 1)
        self.assertIn('construction', constructor['condition'])
        self.assertTrue(any(row['stage'] == constructor['id'] and row['status'] == 'possible'
                            for row in workflow['uncertainties']))

    def test_deferred_call_context_reaches_nested_stages(self):
        workflow = self.workflow_for('''def dangerous():
    return 1
async def task():
    return dangerous()
def entry():
    return task()
''')
        task = next(stage for stage in workflow['stages'] if stage['label'] == 'task')
        nested = next(stage for stage in workflow['stages'] if stage['label'] == 'dangerous')
        self.assertIn('deferred coroutine', task['condition'])
        self.assertIn('deferred coroutine', nested['condition'])
        self.assertTrue(task['executionContext']['effectiveDeferred'])
        self.assertTrue(nested['executionContext']['effectiveDeferred'])
        self.assertTrue(nested['executionContext']['inheritedDeferred'])
        self.assertEqual(nested['executionContext']['deferredBy'], task['id'])

    def test_nested_constructor_and_method_calls_have_distinct_stages(self):
        workflow = self.workflow_for('''class Repo:
    def get(self):
        return 1
def entry():
    return Repo().get()
''')
        ids = [stage['id'] for stage in workflow['stages']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([stage['label'] for stage in workflow['stages']], ['entry', 'Repo', 'Repo().get'])

    def test_inferred_receiver_evidence_reaches_workflow_and_source_query(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('''class Repo:
    def get(self): return 1
class Service:
    def __init__(self, repo: Repo): self.repo = repo
    def entry(self): return self.repo.get()
''')
            store = SnapshotStore(root)
            entry = next(scope for scope in store.current['scopes'].values()
                         if scope['qualified'] == 'Service.entry')
            workflow = store.get_workflow(entry['id'])
            stage = next(stage for stage in workflow['stages']['items']
                         if stage['label'] == 'self.repo.get')
            self.assertEqual(len(stage['candidateEvidence']), 2)
            self.assertEqual(len(stage['evidence']), 3)
            self.assertEqual([proof['span']['start'] for proof in stage['candidateEvidence']], [4, 4])
            for proof in stage['candidateEvidence']:
                self.assertIn('evidenceId', proof)
                source = store.get_source(evidence=proof['evidenceId'])
                self.assertEqual(source['requestedSpan'], proof['span'])

    def test_generator_expression_context_reaches_nested_callee(self):
        workflow = self.workflow_for('''def leaf():
    return 1
def middle():
    return leaf()
def entry():
    return (middle() for _ in range(2))
''')
        middle = next(stage for stage in workflow['stages'] if stage['label'] == 'middle')
        leaf = next(stage for stage in workflow['stages'] if stage['label'] == 'leaf')
        self.assertEqual(middle['executionContext']['kind'], 'generator expression')
        self.assertTrue(leaf['executionContext']['inheritedDeferred'])
        self.assertEqual(leaf['executionContext']['deferredBy'], middle['id'])

    def test_lazy_type_alias_call_is_deferred_in_class_workflow(self):
        workflow = self.workflow_for('''class Box:
    def build():
        return int
    type Alias = build()
''', name='Box')
        alias_call = next(stage for stage in workflow['stages'] if stage['label'] == 'build')
        self.assertEqual(alias_call['executionContext']['kind'], 'type alias value')
        self.assertTrue(alias_call['executionContext']['effectiveDeferred'])
        self.assertIn('deferred type alias', alias_call['condition'])

    def test_callee_reexpands_when_deferred_context_differs(self):
        workflow = self.workflow_for('''def leaf():
    return 1
def middle():
    return leaf()
async def task():
    return middle()
def entry():
    middle()
    return task()
''')
        leaves = [stage for stage in workflow['stages'] if stage['label'] == 'leaf']
        self.assertEqual(len(leaves), 2)
        self.assertEqual([stage['executionContext']['effectiveDeferred'] for stage in leaves],
                         [False, True])
        ids = [stage['id'] for stage in workflow['stages']]
        self.assertEqual(len(ids), len(set(ids)))

    def analyze_fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        (root/'api.py').write_text('''from service import process

def create(payload):
    if not payload:
        return None
    result = process(payload)
    audit(result)
    return result
''')
        (root/'service.py').write_text('''from helpers import clean

def process(value):
    normalized = clean(value)
    return normalized
''')
        (root/'helpers.py').write_text('''def clean(value):
    return value.strip().lower()
''')
        return analyze(root)

    def test_every_repository_gets_generic_workflows_without_named_profiles(self):
        model=self.analyze_fixture()
        self.assertNotIn('profiles',model['workflows'])
        create=next(scope for scope in model['scopes'].values() if scope['qualified']=='create')
        workflow=generic_workflow(model,create['id'])
        self.assertEqual(workflow['stages'][0]['label'],'create')
        self.assertTrue(any(stage['label']=='process' for stage in workflow['stages']))
        self.assertTrue(any(stage['label']=='clean' for stage in workflow['stages']))
        self.assertTrue(any(stage['status']=='unknown' for stage in workflow['stages']))
        self.assertTrue(workflow['alternatives'])
        relations=[stage['moduleLink'] for stage in workflow['stages'] if 'moduleLink' in stage]
        self.assertEqual(relations, [{'from':'api','to':'service'}, {'from':'service','to':'helpers'}])
        self.assertTrue(all('moduleLink' not in stage for stage in workflow['stages'] if stage['status'] != 'supported'))

    def test_all_generated_connections_have_original_source_evidence(self):
        model=self.analyze_fixture()
        create=next(scope for scope in model['scopes'].values() if scope['qualified']=='create')
        workflow=generic_workflow(model,create['id'])
        for link in workflow['links']:
            self.assertTrue(link['evidence'])
            for proof in link['evidence']:
                span=proof['span'];source=model['files'][span['file']]
                self.assertEqual(span['hash'],source['hash'])
                fragment='\n'.join(source['source'].splitlines()[span['start']-1:span['end']])
                self.assertTrue(fragment.strip())

    def test_publish_subscribe_matches_remain_possible(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'events.py').write_text('''def callback(payload):
    return payload

def startup():
    bus.subscribe("ready", callback)

def send():
    bus.publish("ready", {"id": 1})
    bus.publish("unmatched", {})
''')
            model=analyze(directory)
            routes=model['workflows']['eventRoutes']
            self.assertEqual(len(routes),1)
            self.assertEqual(routes[0]['status'],'possible')
            self.assertEqual(model['scopes'][routes[0]['targets'][0]]['name'],'callback')
            self.assertEqual(len(routes[0]['evidence']),2)


if __name__=='__main__':
    unittest.main()
