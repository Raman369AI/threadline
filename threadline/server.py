"""Serve the Threadline browser from a snapshot store."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from .service import SnapshotStore, ThreadlineError
from .changes import review_changes

ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/workflow.js': ('workflow.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css')}


def make_server(root, host='127.0.0.1', port=4173, retention=2, base=None, source_roots=None, exclude=None, change_files=None):
    store = SnapshotStore(root, retention=retention, source_roots=source_roots, exclude=exclude)
    store.refresh()
    def enrich():
        if base:
            changes = review_changes(root, base, change_files, store)
            store.current['changes'] = changes
            from .workflows import generic_workflow
            for item in changes['changedMethods']:
                if item['id'] in store.current['scopes']:
                    store.current['generatedWorkflows'][item['id']] = generic_workflow(store.current, item['id'])
    enrich()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, content_type='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            request = urlsplit(self.path); path = request.path; query = parse_qs(request.query)
            try:
                if path == '/api/index':
                    return self.reply(200, store.model(_one(query, 'snapshot')))
                if path == '/api/summary': return self.reply(200, store.summary(cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25)))
                if path == '/api/symbols': return self.reply(200, store.find_symbols(_one(query, 'q', ''), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25)))
                if path == '/api/workflow': return self.reply(200, store.get_workflow(_one(query, 'entrypoint', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 40)))
                if path == '/api/method': return self.reply(200, store.get_method(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 50)))
                if path == '/api/source': return self.reply(200, store.get_source(snapshot_id=_one(query, 'snapshot'), evidence=_one(query, 'evidence'), file=_one(query, 'file'), start=_optional_int(query, 'start'), end=_optional_int(query, 'end')))
                if path in ASSETS:
                    name, mime = ASSETS[path]
                    return self.reply(200, files('threadline.static').joinpath(name).read_bytes(), mime)
                if path == '/favicon.ico': return self.reply(204, b'', 'image/x-icon')
                return self.reply(404, {'error': 'Not found'})
            except (ThreadlineError, ValueError) as exc:
                return self.reply(400, {'error': str(exc)})

        def do_POST(self):
            if urlsplit(self.path).path != '/api/reindex': return self.reply(404, {'error': 'Not found'})
            origin, host_header = self.headers.get('Origin'), self.headers.get('Host')
            if origin and urlsplit(origin).netloc != host_header: return self.reply(403, {'error': 'Cross-origin reindex is not allowed'})
            with lock:
                store.refresh(); enrich()
            self.reply(200, store.current)

    server = ThreadingHTTPServer((host, port), Handler)
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
