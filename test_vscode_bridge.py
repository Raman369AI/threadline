"""Exercise the shipped transport in an isolated interpreter, not a mocked analyzer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class VSCodeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = tempfile.TemporaryDirectory()
        cls.runner = Path(cls.bundle.name) / 'runner.py'
        shutil.copyfile(ROOT / 'vscode/python/runner.py', cls.runner)
        shutil.copytree(ROOT / 'threadline', Path(cls.bundle.name) / 'threadline', ignore=shutil.ignore_patterns('__pycache__'))

    @classmethod
    def tearDownClass(cls):
        cls.bundle.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = '@decorate\ndef outer(x):\n    def inner():\n        return "café"\n    return inner()\n'
        (self.root / 'demo.py').write_text(self.source, encoding='utf8')
        self.process = subprocess.Popen([sys.executable, '-I', '-S', '-u', str(self.runner)],
            cwd=self.root, env={**os.environ, 'PYTHONPATH':str(self.root)},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.serial = 0

    def tearDown(self):
        self.process.stdin.close()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()
        self.process.stdout.close(); self.process.stderr.close(); self.temp.cleanup()

    def call(self, op, **args):
        self.serial += 1
        self.process.stdin.write(json.dumps({'id':self.serial, 'op':op, **args}) + '\n'); self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        self.assertEqual(response['id'], self.serial)
        if 'error' in response: raise ValueError(response['error'])
        return response['result']

    def init(self, **options):
        return self.call('init', options={'root':str(self.root), **options})

    def test_cursor_decorator_nested_source_and_html(self):
        summary = self.init()
        outer = self.call('locate', file='demo.py', line=1)
        inner = self.call('locate', file='demo.py', line=4)
        self.assertEqual(outer['name'], 'outer')
        self.assertIn('inner', inner['name'])
        self.assertNotEqual(outer['id'], inner['id'])
        source = self.call('source', file='demo.py', line=4, snapshot=summary['snapshotId'])
        self.assertEqual(source['source'], self.source)
        page = self.call('query', path='/api/method-source', params={'symbol':inner['id'], 'snapshot':inner['snapshot']})
        self.assertEqual(page['snapshotId'], inner['snapshot'])
        output = self.root / 'review.html'
        self.call('export', path=str(output))
        self.assertIn('threadlineOffline', output.read_text())
        self.assertGreater(output.stat().st_size, 10000)

    def test_never_imports_target_or_startup_hooks(self):
        marker = self.root / 'EXECUTED'
        attack = f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\nraise RuntimeError("target imported")\n'
        for name in ('sitecustomize.py', 'usercustomize.py', 'threadline.py', 'demo.py'):
            (self.root / name).write_text(attack)
        self.init()
        self.assertFalse(marker.exists())

    def test_refresh_preserves_exact_old_source(self):
        before = self.init()['snapshotId']
        (self.root / 'demo.py').write_text('def replacement():\n    return 42\n')
        after = self.call('query', path='/api/reindex')['snapshotId']
        self.assertNotEqual(before, after)
        self.assertEqual(self.call('source', file='demo.py', line=1, snapshot=before)['source'], self.source)
        self.assertIn('replacement', self.call('source', file='demo.py', line=1, snapshot=after)['source'])

    def test_queries_reject_invalid_paths_lines_and_continuations(self):
        self.init()
        for file, line in [('../secret', 1), ('/etc/passwd', 1), ('demo.py', 0), ('demo.py', 100), ('missing.py', 1)]:
            with self.assertRaises(ValueError): self.call('source', file=file, line=line)
        with self.assertRaisesRegex(ValueError, 'Not found'): self.call('query', path='/api/nope')
        with self.assertRaisesRegex(ValueError, 'snapshot is required'):
            self.call('query', path='/api/method-source', params={'symbol':'x', 'cursor':1})
        with self.assertRaisesRegex(ValueError, 'Unknown bridge'):
            self.call('execute', code='raise RuntimeError()')
        self.assertIn('snapshotId', self.call('query', path='/api/summary'))

    def test_git_baseline_and_failed_refresh_keeps_previous_review(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True)
        git('init', '-q'); git('add', 'demo.py')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'baseline')
        (self.root / 'demo.py').unlink()
        (self.root / 'new.py').write_text('def new():\n    return 9\n')
        summary = self.init(base='HEAD')
        baseline = summary['changes']['baseSnapshotId']
        self.assertEqual(self.call('source', file='demo.py', line=1, snapshot=baseline)['source'], self.source)
        shutil.rmtree(self.root / '.git')
        with self.assertRaises(ValueError): self.call('query', path='/api/reindex')
        self.assertEqual(self.call('query', path='/api/summary')['snapshotId'], summary['snapshotId'])


if __name__ == '__main__': unittest.main()
