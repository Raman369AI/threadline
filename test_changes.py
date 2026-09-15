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
            self.assertEqual(server.threadline_store.get_workflow(changed['id'])['root'],changed['id'])
            base=model['changes']['baseSnapshotId']
            self.assertEqual(server.threadline_store.model(base)['snapshotId'],base)
        finally: server.server_close()

    def test_baseline_honors_source_roots_exclusions_and_script_metadata(self):
        (self.root/'src'/'package').mkdir(parents=True)
        (self.root/'src'/'package'/'app.py').write_text('def start():\n    return 1\n')
        (self.root/'ignored.py').write_text('def ignored():\n    return 0\n')
        (self.root/'pyproject.toml').write_text('[project.scripts]\nlaunch="package.app:start"\n')
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','commit','-qm','layout'],cwd=self.root,check=True)
        (self.root/'src'/'package'/'app.py').write_text('def start():\n    return 2\n')
        store=SnapshotStore(self.root,source_roots=['src'],exclude=['ignored.py'])
        result=review_changes(self.root,store=store)
        before=store.model(result['baseSnapshotId'])
        self.assertEqual(set(before['files']),{'src/package/app.py'})
        self.assertIn('declared project script',before['entrypoints'][0]['reason'])
        self.assertEqual(before['scopes'][before['entrypoints'][0]['id']]['module'],'package.app')

    def test_rename_with_spaces_preserves_old_and_new_evidence(self):
        subprocess.run(['git','mv','logic.py','renamed logic.py'],cwd=self.root,check=True)
        store=SnapshotStore(self.root);result=review_changes(self.root,store=store)
        self.assertEqual(result['files'][0]['status'],'R')
        self.assertEqual({row['file'] for row in result['previousMethods']},{'logic.py'})
        self.assertEqual({row['file'] for row in result['changedMethods']},{'renamed logic.py'})
        for row in result['previousMethods']:
            self.assertIn('def ',store.get_source(snapshot_id=result['baseSnapshotId'],evidence=row['evidenceId'])['source'])

    def test_git_timeout_is_an_actionable_error(self):
        from unittest.mock import patch
        from threadline.changes import _git_bytes
        from threadline.service import ThreadlineError
        with patch('threadline.changes.subprocess.run',side_effect=subprocess.TimeoutExpired('git',30)):
            with self.assertRaisesRegex(ThreadlineError,'budget'): _git_bytes(self.root,['status'])

    def test_quoted_unicode_filename_maps_only_modified_definition(self):
        name='café\tlogic.py'
        path=self.root/name
        path.write_text('def first():\n    return 1\ndef second():\n    return 2\n')
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','commit','-qm','unusual name'],cwd=self.root,check=True)
        path.write_text('def first():\n    return 1\ndef second():\n    return 3\n')
        result=review_changes(self.root)
        self.assertEqual([row['name'] for row in result['changedMethods']],['second'])
        self.assertEqual(result['changedMethods'][0]['file'],name)

    def test_working_file_edit_after_snapshot_does_not_change_diff_evidence(self):
        from unittest.mock import patch
        from threadline.changes import _hunks
        (self.root/'logic.py').write_text('def keep(value):\n    return value + 1\ndef remove(value):\n    return value\n')
        def change_after_index(before,current,statuses):
            (self.root/'logic.py').write_text('def keep(value):\n    return value\ndef remove(value):\n    return value + 2\n')
            return _hunks(before,current,statuses)
        store=SnapshotStore(self.root)
        with patch('threadline.changes._hunks',side_effect=change_after_index):
            result=review_changes(self.root,store=store)
        self.assertEqual([row['name'] for row in result['changedMethods']],['keep'])
        source=store.get_source(snapshot_id=result['workingSnapshotId'],evidence=result['changedMethods'][0]['evidenceId'])
        self.assertIn('return value + 1',source['source'])

    def test_system_temp_directory_alias_preserves_baseline_containment(self):
        from unittest.mock import patch
        actual=self.root/'temp-real';actual.mkdir()
        alias=self.root/'temp-alias';alias.symlink_to(actual,target_is_directory=True)
        (self.root/'logic.py').write_text('def keep(value):\n    return value + 1\n')
        with patch('tempfile.tempdir',str(alias)):
            result=review_changes(self.root)
        self.assertEqual([row['name'] for row in result['changedMethods']],['keep'])
