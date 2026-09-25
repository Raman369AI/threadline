import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from threadline.html_export import write_html
from threadline.service import SnapshotStore


class ReviewStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'pkg').mkdir()
        (self.root / 'pkg' / '__init__.py').write_text('if __name__ == "__main__":\n    pass\n')
        (self.root / 'pkg' / 'commands.py').write_text('def main():\n    return run()\ndef run():\n    return 0\n')
        (self.root / 'pkg' / 'cli.py').write_text('from .commands import main\n')
        (self.root / 'pkg' / '__main__.py').write_text('from .cli import main\nraise SystemExit(main())\n')
        # Sorts after test_commands alphabetically, so test-last ordering is observable.
        (self.root / 'zeta.py').write_text('def helper():\n    return 1\n')
        (self.root / 'pyproject.toml').write_text('[project]\nname="pkg"\n[project.scripts]\npkg = "pkg.cli:main"\n')
        (self.root / 'test_commands.py').write_text(
            'import unittest\nfrom pkg.commands import run\n'
            'class CommandTests(unittest.TestCase):\n    def test_run(self):\n        self.assertEqual(run(), 0)\n'
            'if __name__ == "__main__":\n    unittest.main()\n')
        self.store = SnapshotStore(self.root)
        self.store.refresh()

    def scope(self, name):
        return next(row['id'] for row in self.store.starts(query=name, limit=20)['results']['items'] if row['name'] == name)

    def test_unittest_case_named_tests_links_to_code(self):
        self.assertEqual(self.store.method_overview(self.scope('run'), limit=5)['counts']['tests'], 1)

    def test_reexported_script_and_package_main_are_commands_before_test_modules(self):
        rows = self.store.starts(category='commands', limit=20)['results']['items']
        labels = [row['label'] for row in rows]
        self.assertEqual(labels[:2], ['pkg', 'python -m pkg'])
        self.assertEqual(rows[0]['file'], 'pkg/commands.py')
        self.assertEqual(labels[-1], 'python -m test_commands')
        self.assertEqual(labels.count('python -m pkg'), 1)

    def test_project_modules_list_before_test_modules(self):
        files = [row['file'] for row in self.store.modules(limit=20)['modules']['items']]
        self.assertEqual(files[-1], 'test_commands.py')

    @unittest.skipUnless(shutil.which('node'), 'node is required to run the saved-review queries')
    def test_saved_html_answers_catalog_queries_like_the_server(self):
        output = write_html(self.store, self.root / 'review.html')
        html = output.read_text()
        snapshot = html.split('<script id="threadline-snapshot" type="application/json">', 1)[1].split('</script>', 1)[0]
        offline = (Path(__file__).parent / 'threadline' / 'static' / 'offline.js').read_text()
        queries = [('/api/starts', {'category': category}) for category in ('http', 'commands', 'tasks', 'methods')]
        queries += [('/api/starts', {'q': 'run'}), ('/api/modules', {}), ('/api/modules', {'file': 'pkg/commands.py'})]
        script = ('const snapshot=' + json.dumps(snapshot) + ';globalThis.window={};'
                  'globalThis.document={getElementById:()=>({textContent:snapshot})};\n' + offline +
                  '\n(async()=>{const out=[];for(const [path,params] of ' + json.dumps(queries) +
                  ')out.push(await window.threadlineOffline(path,{...params,limit:20}));console.log(JSON.stringify(out));})();')
        saved = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout)
        live = [self.store.starts(limit=20, **{'query' if key == 'q' else key: value for key, value in params.items()})
                if path == '/api/starts' else self.store.modules(limit=20, **params) for path, params in queries]
        order = lambda result: [(row.get('id'), row.get('label'), row['file'])
                                for row in (result.get('results') or result.get('modules') or result['methods'])['items']]
        for (path, params), expected, actual in zip(queries, live, saved):
            with self.subTest(path=path, params=params):
                self.assertEqual(order(actual), order(expected))


if __name__ == '__main__':
    unittest.main()
