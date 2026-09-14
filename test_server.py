import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from threadline.server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'target.py'
        self.path.write_text('raise RuntimeError("do not execute")\ndef sample():\n    return 1\n')
        self.server = make_server(self.root, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.temp.cleanup()

    def test_snapshot_refresh_is_explicit_and_never_executes_target(self):
        with urlopen(self.url+'/api/index') as response:
            before = json.load(response)
        self.path.write_text('raise RuntimeError("still do not execute")\ndef sample():\n    return 2\n')
        with urlopen(self.url+'/api/index') as response:
            unchanged = json.load(response)
        self.assertEqual(before['files']['target.py']['hash'],unchanged['files']['target.py']['hash'])
        with urlopen(Request(self.url+'/api/reindex',method='POST')) as response:
            after=json.load(response)
        self.assertNotEqual(before['files']['target.py']['hash'],after['files']['target.py']['hash'])
        self.assertIn('return 2',after['files']['target.py']['source'])

    def test_only_allowlisted_assets_and_index_are_served(self):
        for path in ['/target.py','/analyzer.py','/../README.md','/.env']:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url+path)
            self.assertEqual(error.exception.code,404)
        with urlopen(self.url+'/') as response:
            self.assertEqual(response.status,200)
            self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])

    def test_bounded_query_endpoints_share_the_snapshot(self):
        with urlopen(self.url+'/api/summary?limit=1') as response: summary=json.load(response)
        snapshot=summary['snapshotId']
        symbol=summary['entrypoints']['items'][0]['id']
        from urllib.parse import urlencode
        with urlopen(self.url+'/api/workflow?'+urlencode({'snapshot':snapshot,'entrypoint':symbol,'limit':1})) as response: workflow=json.load(response)
        self.assertEqual(workflow['snapshotId'],snapshot)
        self.assertEqual(len(workflow['stages']['items']),1)
        with self.assertRaises(HTTPError) as error: urlopen(self.url+'/api/source?file=../outside.py')
        self.assertEqual(error.exception.code,400)

    def test_cross_origin_reindex_is_rejected(self):
        request=Request(self.url+'/api/reindex',method='POST',headers={'Origin':'https://unrelated.example'})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code,403)


if __name__ == '__main__':
    unittest.main()
