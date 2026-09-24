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


    def test_deleted_target_retains_unchanged_caller_with_baseline_evidence(self):
        for delete_file in (False, True):
            with self.subTest(delete_file=delete_file):
                path = self.root / 'logic.py'
                if delete_file:
                    path.unlink()
                else:
                    path.write_text('def remove(value):\n    return value\n')
                store = SnapshotStore(self.root)
                result = review_changes(self.root, store=store)
                self.assertEqual(result['knownCallers'], [])
                self.assertEqual(len(result['baselineCallers']), 1)
                caller = result['baselineCallers'][0]
                self.assertEqual(caller['name'], 'entry')
                self.assertEqual(caller['snapshotId'], result['baseSnapshotId'])
                self.assertEqual([call['target']['name'] for call in caller['calls']], ['keep'])
                call = caller['calls'][0]
                source = store.get_source(snapshot_id=caller['snapshotId'], evidence=call['evidenceId'])
                self.assertIn('keep(value)', source['source'])
                target = store.get_source(snapshot_id=caller['snapshotId'], evidence=call['target']['evidenceId'])
                self.assertIn('def keep', target['source'])
                working = store.current
                entry = next(scope for scope in working['scopes'].values() if scope['qualified'] == 'entry')
                self.assertEqual(entry['span']['hash'], caller['span']['hash'])

    def test_baseline_possible_calls_are_not_promoted_to_known_relationships(self):
        (self.root/'caller.py').write_text('from logic import keep\ndef entry(value, keep):\n    return keep(value)\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'shadowed caller'], cwd=self.root, check=True)
        (self.root/'logic.py').write_text('def remove(value):\n    return value\n')
        result = review_changes(self.root)
        self.assertEqual(result['baselineCallers'], [])

    def test_change_summary_counts_and_baseline_callers_are_paged(self):
        (self.root/'caller.py').write_text('from logic import keep\n' + ''.join(
            f'def caller_{index}(value):\n    return keep(value)\n' for index in range(30)))
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'many callers'], cwd=self.root, check=True)
        (self.root/'logic.py').unlink()
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        summary = store.summary()
        self.assertEqual(summary['changes']['counts']['baselineCallers'], 30)
        self.assertNotIn('baselineCallers', summary['changes'])
        first = store.diagnostics(category='baselineCallers', limit=25)
        second = store.diagnostics(category='baselineCallers', cursor=first['rows']['nextCursor'], limit=25)
        self.assertEqual(len(first['rows']['items']), 25)
        self.assertEqual(len(second['rows']['items']), 5)
        self.assertIsNone(second['rows']['nextCursor'])
        self.assertEqual(len({row['id'] for row in first['rows']['items'] + second['rows']['items']}), 30)

    def test_comparison_retains_before_after_source_and_pages_independently(self):
        (self.root/'logic.py').write_text('def keep(value):\n'+''.join(f'    value += {i}\n' for i in range(60))+'    return value\n')
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        changed = next(row for row in store.current['changes']['changedMethods'] if row['name'] == 'keep')
        result = store.compare_change(changed['id'], limit=20)
        self.assertEqual(result['match'], 'paired')
        self.assertEqual(result['before']['lines']['total'], 2)
        self.assertEqual(result['after']['lines']['total'], 62)
        self.assertEqual(result['nextCursor'], 20)
        (self.root/'logic.py').write_text('raise RuntimeError("do not execute")\n')
        page = store.compare_change(changed['id'], cursor=20, limit=20)
        self.assertEqual(page['before']['lines']['items'], [])
        self.assertEqual(len(page['after']['lines']['items']), 20)
        self.assertIn('value += 19', page['after']['lines']['items'][0]['text'])
        previous = next(row for row in store.current['changes']['previousMethods'] if row['name'] == 'remove')
        self.assertEqual(store.compare_change(previous['id'], side='base')['match'], 'deleted')

    def test_comparison_tracks_renames_and_leaves_duplicate_names_ambiguous(self):
        subprocess.run(['git','mv','logic.py','renamed.py'],cwd=self.root,check=True)
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        self.assertEqual(store.current['changes']['changedMethods'], [])
        changed = next(row for row in store.current['changes']['renamedMethods'] if row['name'] == 'keep')
        self.assertEqual(changed['reason'], 'definition moved without a source edit')
        result = store.compare_change(changed['id'])
        self.assertEqual(result['match'], 'paired')
        self.assertEqual(result['before']['span']['file'], 'logic.py')
        self.assertEqual(result['after']['span']['file'], 'renamed.py')
        (self.root/'renamed.py').write_text('def keep(value):\n    return 1\ndef keep(value):\n    return 2\n')
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        changed = next(row for row in store.current['changes']['changedMethods'] if row['name'] == 'keep')
        self.assertEqual(store.compare_change(changed['id'])['match'], 'ambiguous')

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
        self.assertEqual(result['changedMethods'], [])
        self.assertEqual(result['previousMethods'], [])
        self.assertEqual({row['file'] for row in result['previousRenamedMethods']},{'logic.py'})
        self.assertEqual({row['file'] for row in result['renamedMethods']},{'renamed logic.py'})
        for row in result['previousRenamedMethods']:
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

    def test_module_constant_edit_remains_visible_and_source_linked(self):
        path = self.root / 'pricing.py'
        path.write_text('FEE = 1.05\ndef price(value):\n    return value * FEE\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'pricing base'], cwd=self.root, check=True)
        path.write_text('FEE = 1.08\ndef price(value):\n    return value * FEE\n')
        store = SnapshotStore(self.root)
        result = review_changes(self.root, store=store)
        self.assertEqual(result['changedMethods'], [])
        self.assertEqual(result['knownCallers'], [])
        self.assertEqual([row['path'] for row in result['files']], ['pricing.py'])
        current = next(row for row in result['unassessedChanges'] if row['side'] == 'working')
        previous = next(row for row in result['unassessedChanges'] if row['side'] == 'base')
        self.assertEqual(store.get_source(evidence=current['evidenceId'])['source'], 'FEE = 1.08')
        self.assertEqual(store.get_source(snapshot_id=result['baseSnapshotId'],
                                          evidence=previous['evidenceId'])['source'], 'FEE = 1.05')
        store.current['changes'] = result
        summary = store.summary()
        self.assertEqual(summary['changes']['counts']['files'], 1)
        self.assertEqual(summary['changes']['counts']['unassessedChanges'], 2)
        self.assertEqual(store.diagnostics(category='files')['rows']['items'][0]['path'], 'pricing.py')
        self.assertEqual(len(store.diagnostics(category='unassessedChanges')['rows']['items']), 2)

    def test_possible_impact_matches_candidate_identity(self):
        path = self.root / 'classes.py'
        path.write_text('class A:\n    def get(self):\n        return 1\n'
                        'class B:\n    def get(self):\n        return 2\n'
                        'def call_b(value: B):\n    return value.get()\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'class base'], cwd=self.root, check=True)
        path.write_text('class A:\n    def get(self):\n        return 3\n'
                        'class B:\n    def get(self):\n        return 2\n'
                        'def call_b(value: B):\n    return value.get()\n')
        store = SnapshotStore(self.root)
        result = review_changes(self.root, store=store)
        call_b = next(scope for scope in store.current['scopes'].values() if scope['qualified'] == 'call_b')
        candidate = call_b['flow'][0]['calls'][0]
        self.assertEqual(candidate['status'], 'possible')
        self.assertEqual([store.current['scopes'][target]['qualified'] for target in candidate['targets']], ['B.get'])
        self.assertEqual([row['name'] for row in result['changedMethods']], ['A.get'])
        self.assertEqual(result['possibleImpact'], [])

    def test_unreachable_call_is_not_reported_as_current_or_baseline_caller(self):
        (self.root / 'caller.py').write_text('from logic import keep\ndef entry(value):\n'
                                             '    return value\n    keep(value)\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'unreachable caller'], cwd=self.root, check=True)
        (self.root / 'logic.py').write_text('def keep(value):\n    return value + 1\n'
                                            'def remove(value):\n    return value\n')
        result = review_changes(self.root)
        self.assertEqual(result['knownCallers'], [])
        self.assertEqual(result['baselineCallers'], [])

    def test_rename_with_body_edit_and_line_shift_matches_unique_counterpart(self):
        subprocess.run(['git', 'mv', 'logic.py', 'renamed.py'], cwd=self.root, check=True)
        (self.root / 'renamed.py').write_text('# moved module\ndef keep(value):\n'
                                              '    return value + 1\ndef remove(value):\n'
                                              '    return value\n')
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        result = store.current['changes']
        changed = next(row for row in result['changedMethods'] if row['name'] == 'keep')
        self.assertNotEqual(changed['id'], changed['counterpartId'])
        self.assertEqual(changed['match'], 'paired')
        self.assertEqual(changed['counterpartSnapshotId'], result['baseSnapshotId'])
        comparison = store.compare_change(changed['id'])
        self.assertEqual(comparison['match'], 'paired')
        self.assertEqual(comparison['before']['span']['file'], 'logic.py')
        self.assertEqual(comparison['after']['span']['file'], 'renamed.py')
        self.assertTrue(any(row['file'] == 'renamed.py' for row in result['unassessedChanges']))

    def test_malformed_file_edit_has_file_and_unassessed_change_records(self):
        bad = self.root / 'bad.py'
        bad.write_text('def broken(:\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'bad base'], cwd=self.root, check=True)
        bad.write_text('def broken( :\n')
        result = review_changes(self.root)
        self.assertEqual([(row['status'], row['path']) for row in result['files']], [('M', 'bad.py')])
        self.assertEqual(result['changedMethods'], [])
        self.assertEqual({row['side'] for row in result['unassessedChanges']}, {'working', 'base'})
        self.assertTrue(all('analysisError' in row for row in result['unassessedChanges']))

    def test_configuration_only_edit_is_unassessed_with_both_source_sides(self):
        path = self.root / 'pyproject.toml'
        path.write_text('[project.scripts]\nlaunch = "logic:keep"\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'configuration base'], cwd=self.root, check=True)
        path.write_text('[project.scripts]\nlaunch = "logic:remove"\n')
        store = SnapshotStore(self.root)
        result = review_changes(self.root, store=store)
        self.assertEqual([(row['status'], row['path']) for row in result['files']], [('M', 'pyproject.toml')])
        self.assertEqual(result['changedMethods'], [])
        self.assertEqual(result['knownCallers'], [])
        self.assertEqual({row['side'] for row in result['unassessedChanges']}, {'working', 'base'})
        current = next(row for row in result['unassessedChanges'] if row['side'] == 'working')
        previous = next(row for row in result['unassessedChanges'] if row['side'] == 'base')
        self.assertEqual(store.get_source(evidence=current['evidenceId'])['source'], 'launch = "logic:remove"')
        self.assertEqual(store.get_source(snapshot_id=result['baseSnapshotId'],
                                          evidence=previous['evidenceId'])['source'], 'launch = "logic:keep"')

    def test_empty_configuration_addition_and_removal_stay_visible(self):
        path = self.root / 'pyproject.toml'
        path.write_text('')
        added = review_changes(self.root)
        self.assertEqual([(row['status'], row['path']) for row in added['files']], [('A', 'pyproject.toml')])
        self.assertEqual([row['side'] for row in added['unassessedChanges']], ['working'])
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'empty configuration'], cwd=self.root, check=True)
        path.unlink()
        deleted = review_changes(self.root)
        self.assertEqual([(row['status'], row['path']) for row in deleted['files']], [('D', 'pyproject.toml')])
        self.assertEqual([row['side'] for row in deleted['unassessedChanges']], ['base'])

    def test_unrelated_insertion_keeps_unchanged_method_comparable(self):
        (self.root / 'logic.py').write_text('# new context\n' + (self.root / 'logic.py').read_text())
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        changes = store.current['changes']
        self.assertEqual(changes['changedMethods'], [])
        self.assertEqual(changes['previousMethods'], [])
        working = next(scope for scope in store.current['scopes'].values()
                       if scope['file'] == 'logic.py' and scope['qualified'] == 'keep')
        baseline = store.model(changes['baseSnapshotId'])
        previous = next(scope for scope in baseline['scopes'].values()
                        if scope['file'] == 'logic.py' and scope['qualified'] == 'keep')
        self.assertNotEqual(working['id'], previous['id'])
        comparison = store.compare_change(working['id'])
        self.assertEqual(comparison['match'], 'paired')
        self.assertEqual(comparison['counterpartId'], previous['id'])
        self.assertFalse(comparison['sourceOverlap'])
        self.assertEqual(comparison['before']['span']['start'] + 1,
                         comparison['after']['span']['start'])
        self.assertEqual([row['text'] for row in comparison['before']['lines']['items']],
                         [row['text'] for row in comparison['after']['lines']['items']])
        reverse = store.compare_change(previous['id'], side='base')
        self.assertEqual(reverse['match'], 'paired')
        self.assertEqual(reverse['counterpartId'], working['id'])
        unchanged_file_symbol = next(scope for scope in store.current['scopes'].values()
                                     if scope['file'] == 'caller.py' and scope['qualified'] == 'entry')
        with self.assertRaisesRegex(ValueError, 'changed file'):
            store.compare_change(unchanged_file_symbol['id'])

    def test_context_comparison_keeps_duplicate_names_ambiguous(self):
        path = self.root / 'logic.py'
        path.write_text('def duplicate():\n    return 1\ndef duplicate():\n    return 2\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', 'commit', '-qm', 'duplicate definitions'], cwd=self.root, check=True)
        path.write_text('# new context\n' + path.read_text())
        store = SnapshotStore(self.root)
        store.current['changes'] = review_changes(self.root, store=store)
        duplicate = next(scope for scope in store.current['scopes'].values()
                         if scope['file'] == 'logic.py' and scope['qualified'] == 'duplicate')
        comparison = store.compare_change(duplicate['id'])
        self.assertEqual(comparison['match'], 'ambiguous')
        self.assertIsNone(comparison['counterpartId'])
        self.assertIsNone(comparison['before'])
