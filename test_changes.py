import subprocess
import tempfile
import unittest
from pathlib import Path
from threadline.changes import review_changes
from threadline.service import SnapshotStore
from threadline.server import make_server


class ChangeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        subprocess.run(['git','init','-q'],cwd=self.root,check=True)
        subprocess.run(['git','config','user.email','test@example.invalid'],cwd=self.root,check=True)
        subprocess.run(['git','config','user.name','Test'],cwd=self.root,check=True)
        (self.root/'logic.py').write_text('def keep(value):\n    return value\ndef remove(value):\n    return value\n')
        (self.root/'caller.py').write_text('from logic import keep\ndef entry(value):\n    return keep(value)\n')
        subprocess.run(['git','add','.'],cwd=self.root,check=True);subprocess.run(['git','commit','-qm','base'],cwd=self.root,check=True)

    def test_changed_deleted_and_untracked_methods_are_separate_from_callers(self):
        (self.root/'logic.py').write_text('def keep(value):\n    if value:\n        return value.strip()\n    return None\n')
        (self.root/'new.py').write_text('raise RuntimeError("never execute")\ndef added():\n    return 1\n')
        store=SnapshotStore(self.root);result=review_changes(self.root,'HEAD',store=store)
        self.assertEqual({row['status'] for row in result['files']},{'M','A'})
        self.assertIn('keep',{row['name'] for row in result['changedMethods']})
        self.assertIn('added',{row['name'] for row in result['changedMethods']})
        self.assertIn('remove',{row['name'] for row in result['previousMethods']})
        self.assertIn('entry',{row['name'] for row in result['knownCallers']})
        self.assertFalse(result['parseErrors']['working'])
        previous=next(row for row in result['previousMethods'] if row['name']=='remove')
        source=store.get_source(snapshot_id=result['baseSnapshotId'],evidence=previous['evidenceId'])
        self.assertIn('def remove',source['source'])


    def test_browser_snapshot_contains_change_starts_and_retained_base(self):
        (self.root/'logic.py').write_text('def keep(value):\n    return value.strip()\ndef remove(value):\n    return value\n')
        server=make_server(self.root,port=0,base='HEAD')
        try:
            model=server.threadline_store.current
            changed=model['changes']['changedMethods'][0]
            self.assertIn(changed['id'],model['generatedWorkflows'])
            base=model['changes']['baseSnapshotId']
            self.assertEqual(server.threadline_store.model(base)['snapshotId'],base)
        finally: server.server_close()
