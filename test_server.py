import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
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

    def test_loopback_startup_does_not_require_dns(self):
        with patch('socket.getfqdn',side_effect=AssertionError('Unexpected DNS lookup')):
            server=make_server(self.root,port=0)
        try:
            self.assertEqual(server.server_name,'localhost')
            self.assertGreater(server.server_port,0)
        finally: server.server_close()

    def refresh_request(self):
        with urlopen(self.url+'/api/session') as response: token=json.load(response)['token']
        return Request(self.url+'/api/reindex',method='POST',headers={'X-Threadline-Token':token})

    def test_untrusted_hosts_and_missing_refresh_token_are_rejected(self):
        for host in ('attacker.example', '127.0.0.1:1', 'localhost.attacker.example'):
            for path in ('/api/source?file=target.py', '/api/session', '/'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(self.url+path,headers={'Host':host}))
                self.assertEqual(error.exception.code,403)
                error.exception.close()
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/api/reindex',method='POST'))
        self.assertEqual(error.exception.code,403)
        error.exception.close()
        request=self.refresh_request();request.add_header('Origin','https://'+self.url.split('//')[1])
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code,403)
        error.exception.close()

    def test_readers_keep_previous_snapshot_until_refresh_finishes(self):
        from threadline.service import SnapshotStore
        previous=self.server.threadline_store.current['snapshotId']
        original=SnapshotStore.refresh
        ready,release=threading.Event(),threading.Event()
        results=[]
        def delayed(store):
            result=original(store);ready.set()
            if not release.wait(5): raise RuntimeError('test refresh timed out')
            return result
        request=self.refresh_request()
        self.path.write_text('def sample():\n    return 9\n')
        def refresh():
            with urlopen(request) as response: results.append(json.load(response))
        with patch.object(SnapshotStore,'refresh',delayed):
            worker=threading.Thread(target=refresh);worker.start()
            try:
                self.assertTrue(ready.wait(5))
                with urlopen(self.url+'/api/summary') as response: self.assertEqual(json.load(response)['snapshotId'],previous)
                with self.assertRaises(HTTPError) as error: urlopen(self.refresh_request())
                self.assertEqual(error.exception.code,409);error.exception.close()
            finally: release.set();worker.join(5)
        self.assertEqual(len(results),1)
        self.assertNotEqual(results[0]['snapshotId'],previous)

    def test_failed_refresh_keeps_last_good_snapshot(self):
        from threadline.service import ThreadlineError
        before=self.server.threadline_store.current['snapshotId']
        request=self.refresh_request()
        with patch('threadline.service.analyze',side_effect=ThreadlineError('budget exceeded')):
            with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code,400);error.exception.close()
        with urlopen(self.url+'/api/summary') as response: self.assertEqual(json.load(response)['snapshotId'],before)

    def test_oversized_response_and_excess_concurrency_fail_explicitly(self):
        from threadline.service import SnapshotStore
        with patch.object(SnapshotStore,'model',return_value={'large':'x'*(4*1024*1024+1)}):
            with self.assertRaises(HTTPError) as error: urlopen(self.url+'/api/index')
            self.assertEqual(error.exception.code,413)
            self.assertIn('Response exceeds',json.load(error.exception)['error']);error.exception.close()
        for _ in range(8): self.server.slots.acquire()
        try:
            with self.assertRaises(HTTPError) as error: urlopen(self.url+'/api/summary')
            self.assertEqual(error.exception.code,503);error.exception.close()
        finally:
            for _ in range(8): self.server.slots.release()
        with urlopen(self.url+'/api/summary') as response:self.assertEqual(response.status,200)

    def test_snapshot_refresh_is_explicit_and_never_executes_target(self):
        with urlopen(self.url+'/api/index') as response:
            before = json.load(response)
        self.path.write_text('raise RuntimeError("still do not execute")\ndef sample():\n    return 2\n')
        with urlopen(self.url+'/api/index') as response:
            unchanged = json.load(response)
        self.assertEqual(before['files']['target.py']['hash'],unchanged['files']['target.py']['hash'])
        with urlopen(self.refresh_request()) as response:
            summary=json.load(response)
        with urlopen(self.url+'/api/index?snapshot='+summary['snapshotId']) as response:
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
