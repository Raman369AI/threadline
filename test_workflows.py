import tempfile
import unittest
from pathlib import Path

from threadline.analyzer import analyze
from threadline.workflows import generic_workflow


class WorkflowTests(unittest.TestCase):
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
