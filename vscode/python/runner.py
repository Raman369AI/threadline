"""Private JSON-lines transport. Launch with Python -I -S -u; never import a target."""
from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath
import sys

# Only the analyzer shipped inside the extension is added to the isolated path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


class Bridge:
    def __init__(self):
        self.store = None
        self.options = {}

    def refresh(self):
        from threadline.service import SnapshotStore
        from threadline.changes import review_changes
        candidate = SnapshotStore(self.options['root'], retention=4,
                                  source_roots=self.options.get('sourceRoots'),
                                  exclude=self.options.get('exclude'))
        if self.store:
            candidate._models = dict(self.store._models)
            candidate._order = copy.copy(self.store._order)
        candidate.refresh()
        candidate._models[candidate.current_id] = copy.deepcopy(candidate.current)
        if self.options.get('base'):
            candidate.current['changes'] = review_changes(self.options['root'], self.options['base'], None, candidate)
        self.store = candidate  # A failed refresh leaves the previous store intact.
        return candidate.summary()

    def dispatch(self, request):
        if sys.version_info < (3, 12):
            raise ValueError('Threadline requires Python 3.12 or newer. Set threadline.pythonPath to a compatible interpreter.')
        from threadline.query_api import query_api
        from threadline.service import _source_info
        op = request.get('op')
        if op == 'init':
            if self.store:
                raise ValueError('Already initialized')
            self.options = request['options']
            if not Path(self.options['root']).is_dir():
                raise ValueError('Workspace folder does not exist')
            return self.refresh()
        if self.store is None:
            raise ValueError('Initialize the workspace first')
        if op == 'query':
            path = request['path']
            if path == '/api/session':
                return {'token': 'stdio'}
            if path == '/api/reindex':
                return self.refresh()
            params = request.get('params', {})
            if not isinstance(params, dict) or any(not isinstance(v, (str, int, float, bool)) for v in params.values()):
                raise ValueError('Query parameters must be scalar values')
            return query_api(self.store, path, {key: [str(value)] for key, value in params.items()})
        if op in ('locate', 'source'):
            file, line = request['file'], request['line']
            path = PurePosixPath(file)
            if path.is_absolute() or '..' in path.parts or '\\' in file or not isinstance(line, int) or line < 1:
                raise ValueError('Invalid source location')
            model = self.store.model(request.get('snapshot'))
            info = _source_info(model, file)
            if info is None or line > max(1, len(info['source'].splitlines())):
                raise ValueError('Source location is not in this snapshot')
            if op == 'source':
                return {'source': info['source'], 'hash': info['hash'], 'file': file,
                        'line': line, 'snapshot': model['snapshotId']}
            scopes = [scope for scope in model['scopes'].values()
                      if scope['file'] == file and scope['kind'] not in ('module', 'class')
                      and scope['span']['start'] <= line <= scope['span']['end']]
            if not scopes:
                raise ValueError('Place the cursor inside a saved Python function or method.')
            scope = min(scopes, key=lambda s: (s['span']['end'] - s['span']['start'], -s['span']['start']))
            return {'id': scope['id'], 'snapshot': model['snapshotId'], 'name': scope['qualified']}
        if op == 'export':
            from threadline.html_export import write_html
            return {'path': str(write_html(self.store, request['path']))}
        raise ValueError('Unknown bridge operation')


def main():
    bridge = Bridge()
    while True:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if not raw:
            break
        if len(raw) > MAX_REQUEST:
            break  # Do not parse a truncated frame or buffer an unbounded request.
        request = {}
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or not isinstance(request.get('id'), int):
                raise ValueError('A numeric request id is required')
            response = {'id': request['id'], 'result': bridge.dispatch(request)}
            encoded = json.dumps(response, ensure_ascii=True)
            if len(encoded) > MAX_RESPONSE:
                raise ValueError('Response exceeds 16 MiB. Narrow threadline.sourceRoots or add exclusions.')
        except Exception as exc:
            request_id = request.get('id') if isinstance(request, dict) else None
            encoded = json.dumps({'id': request_id, 'error': str(exc)}, ensure_ascii=True)
        sys.stdout.write(encoded + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
