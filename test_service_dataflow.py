"""Snapshot-pinned data-flow and bounded method-source API regressions."""

import json
import io
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from threadline.server import make_server
from threadline.service import SnapshotStore, ThreadlineError
from threadline.agent_cli import main as cli_main


class MethodSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'example.py'
        self.source = ('def marker(function):\n    return function\n\n'
                       '@marker\ndef long_method(value):\n'
                       + ''.join(f'    value += {number}\n' for number in range(230))
                       + '    return value\n\ndef sibling():\n    return 1\n')
        self.path.write_text(self.source)
        self.store = SnapshotStore(self.root)
        self.model = self.store.refresh()
        self.symbol = next(scope['id'] for scope in self.model['scopes'].values()
                           if scope['qualified'] == 'long_method')

    def test_method_source_pages_exact_decorated_span_and_retains_old_source(self):
        snapshot = self.model['snapshotId']
        first = self.store.get_method_source(self.symbol, snapshot_id=snapshot, limit=100)
        self.assertEqual(first['span']['start'], 4)
        self.assertEqual(first['lines']['items'][0], {'number': 4, 'text': '@marker'})
        self.assertEqual(first['lines']['items'][1],
                         {'number': 5, 'text': 'def long_method(value):'})
        self.assertEqual(first['lines']['nextCursor'], 100)
        self.assertEqual(first['lines']['total'], 233)
        lines = []
        cursor = 0
        while cursor is not None:
            page = self.store.get_method_source(self.symbol, snapshot_id=snapshot,
                                                cursor=cursor, limit=100)['lines']
            lines.extend(page['items'])
            cursor = page['nextCursor']
        self.assertEqual(len(lines), 233)
        self.assertEqual(lines[-1]['text'], '    return value')
        self.assertNotIn('def sibling', '\n'.join(row['text'] for row in lines))
        evidence = self.store.get_source(snapshot_id=snapshot, evidence=first['evidenceId'])
        self.assertEqual(evidence['requestedSpan'], first['span'])
        self.path.write_text(self.source.replace('    return value\n\ndef sibling',
                                                 '    return value + 1\n\ndef sibling'))
        self.assertNotEqual(self.store.refresh()['snapshotId'], snapshot)
        old_tail = self.store.get_method_source(self.symbol, snapshot_id=snapshot,
                                                cursor=200, limit=100)['lines']['items'][-1]
        self.assertEqual(old_tail['text'], '    return value')

    def test_method_source_rejects_noncallables_and_invalid_pages(self):
        module = next(scope['id'] for scope in self.model['scopes'].values()
                      if scope['kind'] == 'module')
        with self.assertRaisesRegex(ThreadlineError, 'callable'):
            self.store.get_method_source(module)
        with self.assertRaisesRegex(ThreadlineError, 'limit'):
            self.store.get_method_source(self.symbol, limit=101)

    def test_http_method_source_uses_snapshot_and_bounded_pages(self):
        server = make_server(self.root, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address = 'http://127.0.0.1:' + str(server.server_port)
        query = urlencode({'symbol': self.symbol, 'snapshot': self.model['snapshotId'],
                           'cursor': 200, 'limit': 100})
        with urlopen(address + '/api/method-source?' + query) as response:
            result = json.load(response)
        self.assertEqual(result['snapshotId'], self.model['snapshotId'])
        self.assertEqual(result['lines']['items'][-1]['text'], '    return value')
        with self.assertRaises(HTTPError) as error:
            urlopen(address + '/api/method-source?' + urlencode(
                {'symbol': self.symbol, 'snapshot': 'stale'}))
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(address + '/api/method-source?' + urlencode(
                {'symbol': self.symbol, 'cursor': 100}))
        self.assertEqual(error.exception.code, 400)


class DataflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'route.py').write_text(
            'from fastapi.templating import Jinja2Templates\n'
            'templates = Jinja2Templates(directory="templates")\n'
            'def handler(value):\n'
            '    old = value\n'
            '    value = value + [1]\n'
            '    result = {"items": value}\n'
            '    result["other"] = old\n'
            '    return templates.TemplateResponse("page.html", {"items": result})\n')
        templates = self.root / 'templates'
        templates.mkdir()
        (templates / 'page.html').write_text(
            '{% for item in items %}{{ item.name }}{% endfor %}\n'
            '<script>apiFetch("/api/later")</script>\n')
        self.store = SnapshotStore(self.root)
        self.model = self.store.refresh()
        self.symbol = next(scope['id'] for scope in self.model['scopes'].values()
                           if scope['qualified'] == 'handler')

    def test_dataflow_pages_have_evidence_and_no_dangling_edge(self):
        snapshot = self.model['snapshotId']
        result = self.store.get_dataflow(self.symbol, snapshot_id=snapshot, limit=2)
        self.assertEqual(result['snapshotId'], snapshot)
        self.assertEqual(result['dataflowVersion'], '1.0')
        self.assertGreater(result['events']['total'], 2)
        self.assertEqual(result['events']['nextCursor'], 2)
        endpoints = ({row['id'] for row in result['nodes']}
                     | {row['id'] for row in result['events']['items']}
                     | {row['id'] for row in result['eventReferences']})
        self.assertTrue(result['edges'])
        self.assertTrue(all(edge['from'] in endpoints and edge['to'] in endpoints
                            for edge in result['edges']))
        for event in result['events']['items']:
            source = self.store.get_source(snapshot_id=snapshot, evidence=event['evidenceId'])
            self.assertEqual(source['requestedSpan'], event['span'])
        with self.assertRaisesRegex(ThreadlineError, 'limit'):
            self.store.get_dataflow(self.symbol, limit=101)

    def test_evidence_survives_graph_eviction_without_growing_evidence_index(self):
        snapshot = self.model['snapshotId']
        with patch('threadline.service.MAX_DATAFLOW_CACHE_ENTRIES', 2):
            first = self.store.get_dataflow(self.symbol, snapshot_id=snapshot, limit=1)
            event = first['events']['items'][0]
            self.assertTrue(event['evidenceId'].startswith('span1.'))
            node_ids = [row['id'] for row in first['nodes'][:2]]
            for node in node_ids:
                self.store.get_dataflow(self.symbol, snapshot_id=snapshot,
                                        node_id=node, direction='downstream')
            self.assertEqual(len(self.store._dataflow_cache), 2)
            self.assertNotIn((snapshot, self.symbol, None, 'both', 0), self.store._dataflow_cache)
            self.assertLessEqual(self.store._dataflow_cache_bytes, 16 * 1024 * 1024)
            self.assertEqual(self.store._dataflow_cache_bytes,
                             sum(size for _, size in self.store._dataflow_cache.values()))
            self.assertEqual(self.store._registered_evidence, {})
            source = self.store.get_source(snapshot_id=snapshot, evidence=event['evidenceId'])
            self.assertEqual(source['requestedSpan'], event['span'])
            self.assertEqual(self.store._registered_evidence, {})
            self.assertEqual(self.store._evidence, {})

    def test_node_trace_and_template_links_use_retained_source(self):
        snapshot = self.model['snapshotId']
        overview = self.store.get_dataflow(self.symbol, snapshot_id=snapshot, limit=100)
        node = next(row['id'] for row in overview['nodes'] if row['name'] == 'value')
        trace = self.store.get_dataflow(self.symbol, snapshot_id=snapshot,
                                        node_id=node, direction='downstream', limit=2)
        self.assertEqual(trace['trace']['nodeId'], node)
        self.assertEqual(trace['trace']['direction'], 'downstream')
        self.assertLessEqual(trace['events']['total'], overview['events']['total'])
        self.assertEqual(len(trace['events']['items']), min(2, trace['events']['total']))
        with self.assertRaisesRegex(ValueError, 'unknown data-flow node'):
            self.store.get_dataflow(self.symbol, node_id='missing')
        links = overview['templates']['links']
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertEqual(link['status'], 'matched')
        self.assertEqual(link['candidates'], ['templates/page.html'])
        self.assertTrue(any(row['contextKey'] == 'items' for row in link['contextUses']))
        self.assertEqual(link['clientFetches'][0]['kind'], 'later-client-request')
        use = link['contextUses'][0]
        source = self.store.get_source(snapshot_id=snapshot, evidence=use['evidenceId'])
        self.assertEqual(source['span']['file'], 'templates/page.html')
        self.assertIn('item', source['source'])
        old_source = source['source']
        (self.root / 'templates' / 'page.html').write_text('{{ items }}\n')
        changed = self.store.refresh()['snapshotId']
        self.assertNotEqual(changed, snapshot)
        self.assertEqual(self.store.get_source(snapshot_id=snapshot,
                                               evidence=use['evidenceId'])['source'], old_source)
        with self.assertRaisesRegex(ThreadlineError, 'does not belong'):
            self.store.get_source(snapshot_id=changed, evidence=use['evidenceId'])
        self.assertEqual(self.store.get_dataflow(self.symbol, snapshot_id=snapshot)['templates']['links'][0]['clientFetches'][0]['path'],
                         '/api/later')

    def test_http_dataflow_and_cli_snapshot_pinning(self):
        server = make_server(self.root, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address = 'http://127.0.0.1:' + str(server.server_port)
        query = urlencode({'symbol': self.symbol, 'snapshot': self.model['snapshotId'],
                           'limit': 2})
        with urlopen(address + '/api/dataflow?' + query) as response:
            http_result = json.load(response)
        self.assertEqual(http_result['events']['nextCursor'], 2)
        with self.assertRaises(HTTPError) as error:
            urlopen(address + '/api/dataflow?' + urlencode({'symbol': self.symbol,
                                                            'snapshot': 'stale'}))
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(address + '/api/dataflow?' + urlencode({'symbol': self.symbol,
                                                            'cursor': 2}))
        self.assertEqual(error.exception.code, 400)

        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', str(self.root), '--symbol', 'handler', '--limit', '2'])
        self.assertEqual(code, 0)
        cli_result = json.loads(output.getvalue())
        self.assertEqual(cli_result['operation'], 'dataflow')
        self.assertEqual(cli_result['result']['events']['total'], http_result['events']['total'])
        self.assertEqual(cli_result['snapshotId'], http_result['snapshotId'])
        self.assertEqual(cli_result['pagination']['events']['nextCursor'], 2)

        session = self.root / 'review.json'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(['snapshot', str(self.root), '--output', str(session)]), 0)
        (self.root / 'route.py').write_text('def handler(value):\n    return value\n')
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', '--session', str(session), '--symbol', 'handler',
                             '--snapshot', self.model['snapshotId'], '--cursor', '2',
                             '--limit', '2', '--detail', 'references'])
        self.assertEqual(code, 0)
        continued = json.loads(output.getvalue())
        self.assertEqual(continued['snapshotId'], self.model['snapshotId'])
        self.assertEqual(continued['result']['events']['items'][0]['id'], 'e3')
        self.assertNotIn('span', continued['result']['events']['items'][0])

        node = cli_result['result']['nodes'][0]['id']
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', '--session', str(session), '--symbol', 'handler',
                             '--node', node, '--direction', 'downstream'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['result']['trace']['nodeId'], node)

        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', str(self.root), '--symbol', 'handler',
                             '--node', node])
        self.assertEqual(code, 2)
        self.assertIn('--snapshot is required', json.loads(output.getvalue())['error']['message'])


class ModelPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        classes = ''.join(f'class Model{number}:\n    field: int\n\n'
                          for number in range(85))
        names = ', '.join(f'Model{number}' for number in range(85))
        (self.root / 'models.py').write_text(
            classes + f'def handler():\n    return ({names})\n')
        self.store = SnapshotStore(self.root)
        self.model = self.store.refresh()
        self.symbol = next(scope['id'] for scope in self.model['scopes'].values()
                           if scope['qualified'] == 'handler')

    def test_model_pages_preserve_event_and_node_identity(self):
        snapshot = self.model['snapshotId']
        first = self.store.get_dataflow(self.symbol, snapshot_id=snapshot, limit=2)
        second = self.store.get_dataflow(self.symbol, snapshot_id=snapshot,
                                         model_cursor=80, limit=2)
        self.assertEqual(first['modelTotal'], 85)
        self.assertEqual(len(first['models']), 80)
        self.assertEqual(first['nextModelOffset'], 80)
        self.assertEqual((second['modelCursor'], len(second['models']),
                          second['nextModelOffset']), (80, 5, None))
        self.assertEqual(len({row['id'] for row in first['models'] + second['models']}), 85)
        self.assertEqual([row['id'] for row in first['events']['items']],
                         [row['id'] for row in second['events']['items']])
        self.assertEqual([row['id'] for row in first['nodes']],
                         [row['id'] for row in second['nodes']])
        self.assertEqual({key[-1] for key in self.store._dataflow_cache}, {0, 80})
        self.assertFalse(first['truncated'])
        self.assertFalse(second['truncated'])
        with self.assertRaisesRegex(ThreadlineError, 'model_cursor'):
            self.store.get_dataflow(self.symbol, model_cursor=-1)

    def test_http_and_cli_model_cursor_require_matching_snapshot(self):
        snapshot = self.model['snapshotId']
        server = make_server(self.root, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        address = 'http://127.0.0.1:' + str(server.server_port)
        query = urlencode({'symbol': self.symbol, 'snapshot': snapshot,
                           'model_cursor': 80, 'limit': 2})
        with urlopen(address + '/api/dataflow?' + query) as response:
            page = json.load(response)
        self.assertEqual((page['modelTotal'], len(page['models']),
                          page['nextModelOffset']), (85, 5, None))
        for bad_query in (
            {'symbol': self.symbol, 'model_cursor': 80},
            {'symbol': self.symbol, 'model_cursor': 80, 'snapshot': 'stale'},
        ):
            with self.assertRaises(HTTPError) as error:
                urlopen(address + '/api/dataflow?' + urlencode(bad_query))
            self.assertEqual(error.exception.code, 400)

        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', str(self.root), '--symbol', 'handler',
                             '--snapshot', snapshot, '--model-cursor', '80',
                             '--limit', '2'])
        self.assertEqual(code, 0)
        cli_page = json.loads(output.getvalue())
        self.assertEqual(cli_page['result']['models'], page['models'])
        self.assertEqual(cli_page['pagination']['models'],
                         {'total': 85, 'nextCursor': None, 'omitted': 0})
        session = self.root / 'model-review.json'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main(['snapshot', str(self.root), '--output', str(session)]), 0)
        (self.root / 'models.py').write_text('def handler():\n    return None\n')
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', '--session', str(session), '--symbol', 'handler',
                             '--model-cursor', '80'])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output.getvalue())['result']['models']), 5)
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(['dataflow', str(self.root), '--symbol', 'handler',
                             '--model-cursor', '80'])
        self.assertEqual(code, 2)
        self.assertIn('--snapshot is required', json.loads(output.getvalue())['error']['message'])


if __name__ == '__main__':
    unittest.main()
