import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT=Path(__file__).parent


class OnlineRepositoryRunnerTests(unittest.TestCase):
    def test_runner_clones_pinned_source_and_writes_passing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);origin=base/'origin';cache=base/'cache';report=base/'report.json'
            origin.mkdir()
            (origin/'api.py').write_text("""from service import clean

def handle(payload):
    if payload:
        value = clean(payload)
    else:
        return None
    publish(value)
    return value
""")
            (origin/'service.py').write_text("""def clean(value):
    return value.strip()
""")
            self.git(origin,'init','-q');self.git(origin,'config','user.email','test@example.com');self.git(origin,'config','user.name','Test')
            self.git(origin,'add','.');self.git(origin,'commit','-qm','fixture')
            revision=self.git(origin,'rev-parse','HEAD').stdout.strip()
            manifest=base/'manifest.json'
            manifest.write_text(json.dumps({'schemaVersion':1,'repositories':[{
                'name':'fixture','url':str(origin),'revision':revision,'exclude':[],
                'forbiddenImports':['api'],'reviewSymbol':{'qualified':'handle','file':'api.py'},
                'minimums':{'files':2,'definitions':2,'branches':1,'workflowStages':3,'workflowFiles':2},
                'requiredStatuses':['supported','unknown'],
            }]}))
            result=subprocess.run([sys.executable,str(ROOT/'tests'/'online_repo_smoke.py'),
                                   '--manifest',str(manifest),'--cache-dir',str(cache),'--report',str(report)],
                                  cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            payload=json.loads(report.read_text())
            self.assertTrue(payload['passed'])
            row=payload['repositories'][0]
            self.assertTrue(row['workingTreeClean'])
            self.assertEqual(row['targetImports'],[])
            self.assertGreaterEqual(row['evidenceChecks'],2)

    def git(self,root,*args):
        return subprocess.run(['git','-C',str(root),*args],check=True,text=True,capture_output=True)


if __name__=='__main__':
    unittest.main()
