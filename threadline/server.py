"""Serve the Threadline browser from a snapshot store."""
from __future__ import annotations

import json
import copy
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from socketserver import TCPServer
from urllib.parse import parse_qs, urlsplit

from .service import SnapshotStore, ThreadlineError
from .changes import review_changes

ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/workflow.js': ('workflow.js', 'text/javascript'), '/method.js': ('method.js', 'text/javascript'),
          '/review_data.js': ('review_data.js', 'text/javascript'), '/codefirst.js': ('codefirst.js', 'text/javascript'),
          '/styles.css': ('styles.css', 'text/css')}


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args)

    def server_bind(self):
        # This loopback-only service needs no reverse DNS lookup at startup.
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try: request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally: self.shutdown_request(request)
            return
        try: super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()


def make_server(root, host='127.0.0.1', port=4173, retention=2, base=None, source_roots=None, exclude=None, change_files=None):
    store = SnapshotStore(root, retention=retention, source_roots=source_roots, exclude=exclude)
    store.refresh()
    def enrich(candidate):
        if base:
            changes = review_changes(root, base, change_files, candidate)
            candidate.current['changes'] = changes
    enrich(store)
    lock = threading.Lock()
    token = secrets.token_urlsafe(32)
    allowed_hosts = set()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, content_type='application/json'):
            if not isinstance(body, bytes):
                encoded = bytearray()
                for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(body):
                    encoded.extend(chunk.encode())
                    if len(encoded) > 4 * 1024 * 1024: break
                body = bytes(encoded)
            if len(body) > 4 * 1024 * 1024:
                code, body = 413, b'{"error":"Response exceeds 4 MiB; narrow the source roots or request a smaller page"}'
                content_type = 'application/json'
            self.send_response(code)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)

        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def authorized_host(self):
            if self.headers.get('Host') not in allowed_hosts or len(self.headers.get_all('Host', [])) != 1:
                self.reply(403, {'error': 'Host must match this loopback server'})
                return False
            return True

        def do_GET(self):
            if not self.authorized_host(): return
            # Pin the store for the whole request, even while refresh publishes a replacement.
            pinned = store
            request = urlsplit(self.path); path = request.path; query = parse_qs(request.query)
            try:
                if path == '/api/session': return self.reply(200, {'token': token})
                if path == '/api/scope': return self.reply(200, pinned.get_scope(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20), shallow=_one(query, 'shallow') == '1'))
                if path == '/api/branch': return self.reply(200, pinned.get_branch(_one(query, 'symbol', required=True), _one(query, 'operation', required=True), _int(query, 'arm', 0), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20)))
                if path == '/api/compare': return self.reply(200, pinned.compare_change(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), side=_one(query, 'side', 'working'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 40)))
                if path == '/api/overview': return self.reply(200, pinned.method_overview(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20)))
                if path == '/api/tests': return self.reply(200, pinned.related_tests(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20)))
                if path == '/api/diagnostics': return self.reply(200, pinned.diagnostics(snapshot_id=_one(query, 'snapshot'), category=_one(query, 'category', 'errors'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25)))
                if path == '/api/index':
                    return self.reply(200, pinned.model(_one(query, 'snapshot')))
                if path == '/api/summary': return self.reply(200, pinned.summary(snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25)))
                if path == '/api/modules': return self.reply(200, pinned.modules(snapshot_id=_one(query, 'snapshot'), file=_one(query, 'file'), query=_one(query, 'q', ''), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20)))
                if path == '/api/starts': return self.reply(200, pinned.starts(snapshot_id=_one(query, 'snapshot'), query=_one(query, 'q', ''), category=_one(query, 'category'), method=_one(query, 'method'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 6)))
                if path == '/api/symbols': return self.reply(200, pinned.find_symbols(_one(query, 'q', ''), kind=_one(query, 'kind', 'callable'), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25)))
                if path == '/api/workflow': return self.reply(200, pinned.get_workflow(_one(query, 'entrypoint', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 40)))
                if path == '/api/method': return self.reply(200, pinned.get_method(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 50)))
                if path == '/api/method-source':
                    snapshot = _one(query, 'snapshot')
                    cursor = _int(query, 'cursor', 0)
                    if cursor and not snapshot:
                        raise ThreadlineError('snapshot is required for a later method-source page')
                    return self.reply(200, pinned.get_method_source(
                        _one(query, 'symbol', required=True), snapshot_id=snapshot,
                        cursor=cursor, limit=_int(query, 'limit', 100)))
                if path == '/api/dataflow':
                    snapshot = _one(query, 'snapshot')
                    cursor = _int(query, 'cursor', 0)
                    model_cursor = _int(query, 'model_cursor', 0)
                    node = _one(query, 'node')
                    if (cursor > 0 or model_cursor > 0 or node) and not snapshot:
                        raise ThreadlineError('snapshot is required for data-flow continuation')
                    return self.reply(200, pinned.get_dataflow(
                        _one(query, 'symbol', required=True), snapshot_id=snapshot,
                        node_id=node, direction=_one(query, 'direction', 'both'),
                        cursor=cursor, limit=_int(query, 'limit', 25),
                        model_cursor=model_cursor))
                if path == '/api/source': return self.reply(200, pinned.get_source(snapshot_id=_one(query, 'snapshot'), evidence=_one(query, 'evidence'), file=_one(query, 'file'), start=_optional_int(query, 'start'), end=_optional_int(query, 'end')))
                if path in ASSETS:
                    name, mime = ASSETS[path]
                    return self.reply(200, files('threadline.static').joinpath(name).read_bytes(), mime)
                if path == '/favicon.ico': return self.reply(204, b'', 'image/x-icon')
                return self.reply(404, {'error': 'Not found'})
            except (ThreadlineError, ValueError) as exc:
                return self.reply(400, {'error': str(exc)})

        def do_POST(self):
            nonlocal store
            if not self.authorized_host(): return
            if urlsplit(self.path).path != '/api/reindex': return self.reply(404, {'error': 'Not found'})
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host'):
                return self.reply(403, {'error': 'Cross-origin reindex is not allowed'})
            supplied_token = self.headers.get('X-Threadline-Token', '')
            if not supplied_token.isascii() or not secrets.compare_digest(supplied_token, token):
                return self.reply(403, {'error': 'A session token is required to refresh source'})
            if not lock.acquire(blocking=False): return self.reply(409, {'error': 'Refresh already in progress'})
            try:
                candidate = SnapshotStore(root, retention=retention, source_roots=source_roots, exclude=exclude)
                candidate._models = dict(store._models)
                candidate._order = copy.copy(store._order)
                candidate.refresh()
                candidate._models[candidate.current_id] = copy.deepcopy(candidate.current)
                enrich(candidate)
                store = candidate
                server.threadline_store = candidate
                self.reply(200, candidate.summary())
            except (ThreadlineError, ValueError, OSError) as exc:
                self.reply(400, {'error': str(exc), 'notice': 'Previous snapshot is still available'})
            finally:
                lock.release()

    if host != '127.0.0.1': raise ValueError('Threadline must bind to IPv4 loopback')
    server = BoundedHTTPServer((host, port), Handler)
    allowed_hosts.update({f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'})
    server.threadline_store = store
    return server


def _one(query, key, default=None, required=False):
    value = query.get(key, [default])[0]
    if required and not value: raise ThreadlineError(f'{key} is required')
    return value

def _int(query, key, default): return int(_one(query, key, default))
def _optional_int(query, key):
    value = _one(query, key)
    return int(value) if value is not None else None
