#!/usr/bin/env python3
"""Cross-check Threadline's call targets against pyright, an independent static resolver.

For a deterministic sample of calls, ask pyright's language server where each call goes.
The check fails when pyright names a different project function for a call Threadline
labels supported. Pyright having no answer is not a failure: it may lack a type that
Threadline read from source. Mismatches on possible calls, and project targets pyright
finds for calls Threadline cannot resolve, are reported but do not fail.

Pyright is a development tool only; Threadline does not depend on it. Targets are parsed
as source and never installed, imported, or executed; pyright runs the Python interpreter
once to find search paths.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from online_repo_smoke import checkout  # noqa: E402
from threadline.service import SnapshotStore  # noqa: E402

DEFAULT_PYRIGHT = ROOT / 'tests' / 'browser-tools' / 'node_modules' / 'pyright' / 'langserver.index.js'


class Pyright:
    """A minimal language-server client: open files and ask for definitions."""

    def __init__(self, server: Path, root: Path):
        self.root = root
        self.process = subprocess.Popen(['node', str(server), '--stdio'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.next_id = 0
        self.pending: dict[int, tuple[threading.Event, list]] = {}
        self.opened: set[str] = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()
        self._request('initialize', {'processId': None, 'rootUri': root.as_uri(),
                                     'workspaceFolders': [{'uri': root.as_uri(), 'name': 'target'}],
                                     'capabilities': {'workspace': {'configuration': True}}})
        self._notify('initialized', {})

    def _send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message).encode()
        assert self.process.stdin is not None
        self.process.stdin.write(b'Content-Length: %d\r\n\r\n' % len(body) + body)
        self.process.stdin.flush()

    def _read(self) -> None:
        stream = self.process.stdout
        assert stream is not None
        while True:
            header = b''
            while not header.endswith(b'\r\n\r\n'):
                chunk = stream.read(1)
                if not chunk:
                    return
                header += chunk
            length = next(int(line.split(':')[1]) for line in header.decode().split('\r\n')
                          if line.lower().startswith('content-length'))
            message = json.loads(stream.read(length))
            if 'id' in message and 'method' in message:
                result = None
                if message['method'] == 'workspace/configuration':
                    result = [{'diagnosticMode': 'openFilesOnly'} if item.get('section') == 'python.analysis' else {}
                              for item in message['params']['items']]
                self._send({'jsonrpc': '2.0', 'id': message['id'], 'result': result})
            elif 'id' in message and message['id'] in self.pending:
                event, box = self.pending.pop(message['id'])
                box.append(message)
                event.set()

    def _request(self, method: str, params: Any, timeout: float = 120) -> Any:
        with self.lock:
            self.next_id += 1
            identifier = self.next_id
            event: threading.Event = threading.Event()
            box: list = []
            self.pending[identifier] = (event, box)
            self._send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params})
        if not event.wait(timeout):
            raise TimeoutError(method)
        if 'error' in box[0]:
            raise RuntimeError(box[0]['error'])
        return box[0].get('result')

    def _notify(self, method: str, params: Any) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params})

    def definitions(self, file: str, line: int, column: int) -> list[tuple[Path, int, int]]:
        path = (self.root / file).resolve()
        uri = path.as_uri()
        if uri not in self.opened:
            self._notify('textDocument/didOpen', {'textDocument': {'uri': uri, 'languageId': 'python',
                                                                   'version': 1, 'text': path.read_text()}})
            self.opened.add(uri)
        position = {'textDocument': {'uri': uri}, 'position': {'line': line - 1, 'character': column}}
        rows = self._locations(self._request('textDocument/definition', position))
        if rows and not all(defines(*row) for row in rows):
            # A variable: follow it to the function or class it holds.
            rows = self._locations(self._request('textDocument/typeDefinition', position))
        return rows

    @staticmethod
    def _locations(result: Any) -> list[tuple[Path, int, int]]:
        items = [result] if isinstance(result, dict) else result or []
        rows = []
        for item in items:
            target = item.get('targetUri') or item.get('uri')
            span = item.get('targetSelectionRange') or item.get('range')
            rows.append((Path(unquote(urlparse(target).path)).resolve(), span['start']['line'] + 1,
                         span['start']['character']))
        return rows

    def close(self) -> None:
        try:
            self._request('shutdown', None, timeout=10)
            self._notify('exit', None)
        except Exception:
            pass
        self.process.kill()


def defines(path: Path, line: int, column: int) -> bool:
    """True at the name of a def or class statement, not at a parameter on that line."""
    try:
        text = path.read_text().splitlines()[line - 1]
    except (OSError, IndexError):
        return False
    return (text[:column].rstrip().endswith(('def', 'class'))
            and text.strip().startswith(('def ', 'async def ', 'class ')))


def call_position(root: Path, call: dict[str, Any]) -> tuple[int, int] | None:
    """Line and column of the called name: the attribute in a.b(), the name in f()."""
    span = call['span']
    if call['name'].endswith(')'):
        return None  # f(x)(y) calls a call's result; there is no single name to ask about
    text = (root / span['file']).read_text().splitlines()[span['start'] - 1]
    attribute = call['name'].split('.')[-1]
    # A whole-word match, so .get does not match inside .get_new_headers.
    pattern = (r'\.\s*' if '.' in call['name'] else r'(?<![\w.])') + re.escape(attribute) + r'\b'
    match = re.compile(pattern).search(text, span['col'])
    if match is None:
        return None
    return span['start'], match.end() - len(attribute)


def project_targets(model: dict[str, Any], root: Path, definitions: list[tuple[Path, int, int]]) -> set[str]:
    targets = set()
    for path, line, column in definitions:
        if root not in path.parents or not defines(path, line, column):
            continue
        file = path.relative_to(root).as_posix()
        enclosing = [scope for scope in model['scopes'].values() if scope['file'] == file
                     and scope['kind'] != 'module' and scope['span']['start'] <= line <= scope['span']['end']]
        if enclosing:
            targets.add(min(enclosing, key=lambda scope: scope['span']['end'] - scope['span']['start'])['id'])
    return targets


def evenly(rows: list[Any], limit: int) -> list[Any]:
    """A deterministic, evenly spaced sample in source order."""
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(index * step)] for index in range(limit)]


def check_project(name: str, root: Path, server: Path, limit: int,
                  source_roots: list[str] | None = None, exclude: list[str] | None = None) -> dict[str, Any]:
    started = time.time()
    model = SnapshotStore(root, source_roots=source_roots, exclude=exclude).current

    def calls(nodes):
        for node in nodes:
            yield from node.get('calls', [])
            for branch in node.get('branches', []):
                yield from calls(branch['nodes'])

    every = sorted((call for scope in model['scopes'].values() for call in calls(scope['flow'])),
                   key=lambda call: (call['span']['file'], call['span']['start'], call['span']['col']))
    label = lambda ids: sorted(model['scopes'][item]['qualified'] for item in ids)  # noqa: E731
    counts: dict[str, dict[str, int]] = {status: {} for status in ('supported', 'possible', 'unknown')}
    disagreements, examples = [], {'possibleOutsideCandidates': [], 'foundWhereThreadlineCannotTell': []}
    pyright = Pyright(server, root)
    try:
        for status in counts:
            for call in evenly([call for call in every if call['status'] == status], limit):
                position = call_position(root, call)
                if position is None:
                    outcome = 'not located'
                else:
                    found = project_targets(model, root, pyright.definitions(call['span']['file'], *position))
                    mine = set(call['targets'])
                    where = f"{call['span']['file']}:{call['span']['start']} {call['name']}"
                    if not found:
                        outcome = 'no project answer'
                    elif status == 'unknown':
                        outcome = 'found'
                        examples['foundWhereThreadlineCannotTell'].append(f'{where} -> {label(found)}')
                    elif found & mine:
                        outcome = 'agrees'
                    else:
                        outcome = 'disagrees'
                        row = f'{where}: Threadline {label(mine)}, pyright {label(found)}'
                        (disagreements if status == 'supported' else examples['possibleOutsideCandidates']).append(row)
                counts[status][outcome] = counts[status].get(outcome, 0) + 1
    finally:
        pyright.close()
    return {'name': name, 'calls': len(every), 'sampledPerStatus': limit, 'outcomes': counts,
            'supportedDisagreements': disagreements,
            'examples': {key: rows[:10] for key, rows in examples.items()},
            'seconds': round(time.time() - started, 1), 'passed': not disagreements}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', action='append', type=Path, default=[], help='a local project; repeatable')
    parser.add_argument('--repo', action='append', default=[], help='a pinned public repository by name; repeatable')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'tests' / 'online_repositories.json')
    parser.add_argument('--limit', type=int, default=300, help='calls sampled per Threadline status (default 300)')
    parser.add_argument('--pyright', type=Path, default=DEFAULT_PYRIGHT, help='pyright langserver.index.js')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not args.pyright.is_file():
        parser.error(f'pyright not found at {args.pyright}; run npm ci --prefix tests/browser-tools')
    if not args.project and not args.repo:
        parser.error('give --project or --repo')

    results = []
    for project in args.project:
        results.append(check_project(project.resolve().name, project.resolve(), args.pyright, args.limit))
    if args.repo:
        specs = {spec['name']: spec for spec in json.loads(args.manifest.read_text())['repositories']}
        with tempfile.TemporaryDirectory(prefix='threadline-pyright-') as cache:
            for name in args.repo:
                spec = specs[name]
                target = Path(cache) / name
                checkout(spec, target, offline=False)
                results.append(check_project(name, target, args.pyright, args.limit,
                                             spec.get('sourceRoots'), spec.get('exclude')))
    for result in results:
        outcome = 'PASS' if result['passed'] else 'FAIL'
        print(f"{outcome} {result['name']}: {json.dumps(result['outcomes'])} in {result['seconds']}s")
        for row in result['supportedDisagreements']:
            print(f'  supported disagreement: {row}')
    report = {'tool': 'pyright', 'passed': all(result['passed'] for result in results), 'projects': results}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
