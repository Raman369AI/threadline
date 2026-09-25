import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from threadline.agent_cli import main
from threadline.html_export import write_html
from threadline.service import SnapshotStore, ThreadlineError


class HTMLExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = "raise RuntimeError('must never execute')\nvalue = '</script><script>alert(1)</script>'\nidentity = lambda item: item\n"
        (self.root / 'app.py').write_text(self.source)

    def test_cli_exports_without_server_and_keeps_source_inert(self):
        output = self.root / 'review.html'
        with patch('threadline.agent_cli.make_server') as server, patch('threadline.agent_cli.webbrowser.open') as browser, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['review', str(self.root), '--output', str(output), '--no-open']), 0)
        server.assert_not_called()
        browser.assert_not_called()
        html = output.read_text()
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn('</script><script>alert(1)</script>', html)
        data = json.loads(html.split('<script id="threadline-snapshot" type="application/json">', 1)[1].split('</script>', 1)[0])
        snapshot = data['snapshots'][data['current']]
        self.assertEqual(snapshot['sources']['app.py']['source'], self.source)
        # Lambdas are callable definitions too; export must retain their returns.
        method = next(iter(snapshot['methods'].values()))
        self.assertIn('return', [event['kind'] for event in method['dataflow']['events']])

    def test_size_failure_preserves_existing_file_and_removes_temporary(self):
        store = SnapshotStore(self.root)
        store.refresh()
        output = self.root / 'review.html'
        output.write_text('previous review')
        with patch('threadline.html_export.MAX_HTML_BYTES', 1), self.assertRaisesRegex(ThreadlineError, 'narrow the review'):
            write_html(store, output)
        self.assertEqual(output.read_text(), 'previous review')
        self.assertEqual(list(self.root.glob('.threadline-*')), [])

    def test_rejects_source_filename_as_output(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['review', str(self.root), '--output', str(self.root / 'app.py'), '--no-open']), 2)
        self.assertEqual((self.root / 'app.py').read_text(), self.source)


if __name__ == '__main__':
    unittest.main()
