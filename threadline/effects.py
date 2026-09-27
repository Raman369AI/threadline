"""Effect catalog: what a method does outside the program, and which call it does it through.

Known library calls map to effect classes, split by direction where it matters:
DB read/write, network read/write, file read/write, process, logging, and raises.
Effects of resolved project calls propagate to their callers with the path they came by,
so a handler can show "DB write via crud.update_user".

Certainty is `definite` when Threadline identified the library target (a typed receiver,
an import, or a builtin), and `possible` when only a name suggests it (an untyped
`session.commit()`), when it arrives through a probable call, or when the call only
creates a coroutine or generator. Effects describe source, not observed execution.
"""
from __future__ import annotations

import re
from typing import Any, Callable

MAX_DEPTH = 5  # longest `via` path kept
MAX_RECURSION = 200
MAX_EFFECTS_PER_SCOPE = 40

_WRITE_SQL = re.compile(r'^\s*(insert|update|delete|merge|replace|upsert|create|drop|alter|truncate)\b', re.I)
_READ_SQL = re.compile(r'^\s*(select|with|show|explain)\b', re.I)
_STATEMENT = re.compile(r'^\s*(?:[\w.]+\.)?(select|insert|update|delete)\s*\(')
_READ_VERBS = {'get', 'head', 'options'}
_WRITE_VERBS = {'post', 'put', 'patch', 'delete'}
_LOG_LEVELS = r'(debug|info|warning|warn|error|exception|critical|fatal|log)'
_DB_WRITES = {'add', 'add_all', 'delete', 'merge', 'flush', 'commit', 'bulk_save_objects',
              'bulk_insert_mappings', 'bulk_update_mappings'}
_DB_READS = {'get', 'get_one', 'scalar', 'scalars', 'refresh', 'query'}
_DB_STATEMENTS = {'execute', 'exec', 'stream', 'executemany', 'exec_driver_sql'}


def _literal(text: str) -> str | None:
    text = text.strip()
    if len(text) >= 2 and text[0] in '"\'' and text[-1] == text[0]:
        return text[1:-1]
    return None


def _statement_mode(call: dict[str, Any]) -> str:
    """select(...) or "SELECT ..." reads; insert/update/delete writes; anything else is unknown."""
    arguments = [arg for arg in call.get('arguments', []) if '=' not in arg.split('(')[0]]
    if not arguments:
        return 'access'
    first = arguments[0]
    statement = _STATEMENT.match(first)
    if statement:
        return 'read' if statement.group(1) == 'select' else 'write'
    sql = _literal(first)
    if sql is None and first.startswith('text(') and first.endswith(')'):
        sql = _literal(first[len('text('):-1])
    if sql:
        return 'read' if _READ_SQL.match(sql) else 'write' if _WRITE_SQL.match(sql) else 'access'
    return 'access'


def _method_mode(method: str) -> str:
    return 'write' if method in _DB_WRITES else 'read' if method in _DB_READS else ''


def _db_mode(call: dict[str, Any], method: str) -> str:
    return _statement_mode(call) if method in _DB_STATEMENTS else _method_mode(method)


def _open_mode(call: dict[str, Any], position: int) -> str:
    """open(path, "w") writes; open(path) reads; a mode that is not a literal is unknown."""
    arguments = call.get('arguments', [])
    mode = next((arg.split('=', 1)[1] for arg in arguments if arg.startswith('mode=')), None)
    positional = [arg for arg in arguments if not re.match(r'^\w+=', arg) and not arg.startswith('*')]
    if mode is None and len(positional) > position:
        mode = positional[position]
    if mode is None:
        return 'read'
    literal = _literal(mode)
    if literal is None:
        return 'access'
    return 'write' if set(literal) & set('wax+') else 'read'


def _verb_mode(verb: str) -> str:
    verb = verb.lower()
    return 'read' if verb in _READ_VERBS else 'write' if verb in _WRITE_VERBS else 'access'


def _request_mode(call: dict[str, Any], method: str) -> str:
    if method in ('request', 'stream', 'send'):
        first = next(iter(call.get('arguments', [])), '')
        literal = _literal(first.split('=', 1)[-1])
        return _verb_mode(literal) if literal else 'access'
    return _verb_mode(method)


Rule = tuple[re.Pattern[str], str, Callable[[dict[str, Any], re.Match[str]], str]]

# Library name patterns: (pattern, category, mode for the call and match).
_RULES: list[Rule] = [
    (re.compile(r'^(?:sqlalchemy|sqlmodel|flask_sqlalchemy)(?:\.\w+)*\.(?:AsyncSession|Session|scoped_session|async_scoped_session|SignallingSession)\.(\w+)$'),
     'db', lambda call, m: _db_mode(call, m.group(1))),
    (re.compile(r'^sqlalchemy(?:\.\w+)*\.(?:Connection|AsyncConnection|Engine|AsyncEngine)\.(execute|exec_driver_sql|commit)$'),
     'db', lambda call, m: 'write' if m.group(1) == 'commit' else _statement_mode(call)),
    (re.compile(r'^(?:sqlite3|psycopg|psycopg2|pymysql|MySQLdb|asyncpg|aiosqlite)(?:\.\w+)*\.(execute|executemany|executescript|commit|fetch|fetchrow|fetchval)$'),
     'db', lambda call, m: 'write' if m.group(1) == 'commit' else 'read' if m.group(1).startswith('fetch') else _statement_mode(call)),
    (re.compile(r'^(?:requests|httpx)\.(get|head|options|post|put|patch|delete|request|stream)$'),
     'network', lambda call, m: _request_mode(call, m.group(1))),
    (re.compile(r'^(?:requests|httpx|aiohttp)(?:\.\w+)*\.(?:Session|Client|AsyncClient|ClientSession)\.(get|head|options|post|put|patch|delete|request|stream|send)$'),
     'network', lambda call, m: _request_mode(call, m.group(1))),
    (re.compile(r'^urllib\.request\.urlopen$'),
     'network', lambda call, m: 'write' if len(call.get('arguments', [])) > 1 or any(a.startswith('data=') for a in call.get('arguments', [])) else 'read'),
    (re.compile(r'^(?:builtins|io|codecs|aiofiles)\.open$'), 'file', lambda call, m: _open_mode(call, 1)),
    (re.compile(r'^pathlib\.(?:Path|PurePath|PosixPath|WindowsPath)\.(write_text|write_bytes|unlink|mkdir|rmdir|rename|replace|touch|chmod|symlink_to|hardlink_to)$'),
     'file', lambda call, m: 'write'),
    (re.compile(r'^pathlib\.(?:Path|PurePath|PosixPath|WindowsPath)\.(read_text|read_bytes|iterdir|glob|rglob)$'),
     'file', lambda call, m: 'read'),
    (re.compile(r'^pathlib\.(?:Path|PosixPath|WindowsPath)\.open$'), 'file', lambda call, m: _open_mode(call, 0)),
    (re.compile(r'^os\.(remove|unlink|rename|renames|replace|makedirs|mkdir|rmdir|removedirs|chmod|chown|symlink|link|truncate|utime)$'),
     'file', lambda call, m: 'write'),
    (re.compile(r'^os\.(listdir|scandir|walk)$'), 'file', lambda call, m: 'read'),
    (re.compile(r'^shutil\.(copy|copy2|copyfile|copyfileobj|copytree|move|rmtree|make_archive|unpack_archive)$'),
     'file', lambda call, m: 'write'),
    (re.compile(r'^(?:json|pickle|marshal)\.dump$'), 'file', lambda call, m: 'write'),
    (re.compile(r'^(?:json|pickle|marshal)\.load$'), 'file', lambda call, m: 'read'),
    (re.compile(r'^yaml\.(?:safe_)?dump$'), 'file',
     lambda call, m: 'write' if len(call.get('arguments', [])) > 1 else ''),
    (re.compile(r'^subprocess\.(run|call|check_call|check_output|Popen|getoutput|getstatusoutput)$'), 'process', lambda call, m: ''),
    (re.compile(r'^os\.(system|popen|exec\w*|spawn\w*|posix_spawn\w*)$'), 'process', lambda call, m: ''),
    (re.compile(r'^asyncio\.create_subprocess_(exec|shell)$'), 'process', lambda call, m: ''),
    (re.compile(r'^logging(?:\.getLogger|\.Logger|\.LoggerAdapter|\.root)?\.' + _LOG_LEVELS + '$'), 'logging', lambda call, m: ''),
    (re.compile(r'^loguru\.logger\.' + _LOG_LEVELS + '$'), 'logging', lambda call, m: ''),
    (re.compile(r'^structlog\.(?:get_logger|getLogger)\.' + _LOG_LEVELS + '$'), 'logging', lambda call, m: ''),
]

# Untyped receivers whose name makes the effect likely: session.commit(), logger.info().
_DB_NAMES = {'session', 'db', 'db_session', 'dbsession', 'sess', 'async_session'}
_LOG_NAMES = {'logger', 'log', '_logger', '_log', 'LOGGER', 'LOG'}


def _effect(category: str, mode: str) -> str:
    return f'{category} {mode}' if mode else category


def call_effects(call: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    """(category, mode, certainty, library) for one call, from the catalog or a strong name."""
    found = []
    for library in call.get('library') or []:
        for pattern, category, mode_of in _RULES:
            match = pattern.match(library)
            if match:
                mode = mode_of(call, match)
                if mode is not None and (mode or category in ('process', 'logging')):
                    found.append((category, mode, 'definite', library))
                break
    if found or call.get('status') != 'unknown':
        return found
    parts = call.get('name', '').split('.')
    if len(parts) < 2 or not re.fullmatch(r'[\w.]+', call.get('name', '')):
        return []
    receiver, method = parts[-2], parts[-1]
    if receiver in _DB_NAMES and (method in _DB_WRITES | _DB_READS | _DB_STATEMENTS):
        mode = _db_mode(call, method)
        return [('db', mode, 'possible', None)] if mode else []
    if receiver in _LOG_NAMES and re.fullmatch(_LOG_LEVELS, method):
        return [('logging', '', 'possible', None)]
    if method in ('write_text', 'write_bytes'):
        return [('file', 'write', 'possible', None)]
    if method in ('read_text', 'read_bytes'):
        return [('file', 'read', 'possible', None)]
    return []


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes:
        yield node
        for branch in node.get('branches', []):
            yield from _walk(branch['nodes'])


def _raised(node: dict[str, Any]) -> str:
    label = node.get('label', '')
    if not label.startswith('Raise ') or label == 'Raise current exception':
        return 're-raise'
    return re.split(r'[\s(]', label[len('Raise '):], maxsplit=1)[0] or 're-raise'


def attach_effects(model: dict[str, Any]) -> None:
    """Add `sideEffects` to every callable scope that has any, direct or inherited."""
    scopes = model['scopes']
    initializers = {scope['parent']: scope['id'] for scope in scopes.values()
                    if scope['name'] == '__init__' and scope['parent'] in scopes
                    and scopes[scope['parent']]['kind'] == 'class'}
    memo: dict[str, list[dict[str, Any]]] = {}
    active: set[str] = set()

    def effects_of(scope_id: str, depth: int) -> list[dict[str, Any]]:
        if scope_id in memo:
            return memo[scope_id]
        scope = scopes[scope_id]
        if scope['kind'] == 'class':
            initializer = initializers.get(scope_id)
            return effects_of(initializer, depth) if initializer else []
        if scope_id in active or depth > MAX_RECURSION:
            return []  # a recursive cycle, or a chain too deep to follow here
        active.add(scope_id)
        records: dict[tuple, dict[str, Any]] = {}

        def add(record: dict[str, Any]) -> None:
            key = (record['effect'], record.get('detail'), tuple(record['via'][:1]))
            known = records.get(key)
            if known is None:
                if len(records) < MAX_EFFECTS_PER_SCOPE:
                    records[key] = record
            else:
                if record['certainty'] == 'definite':
                    known['certainty'] = 'definite'
                known['lines'] = sorted(set(known['lines']) | set(record['lines']))
        try:
            for node in _walk(scope.get('flow', [])):
                if node.get('kind') == 'Raise':
                    add({'effect': 'raises', 'category': 'raises', 'mode': '', 'detail': _raised(node),
                         'certainty': 'definite', 'via': [], 'through': None, 'call': None, 'library': None,
                         'file': node['span']['file'], 'lines': [node['span']['start']]})
                for call in node.get('calls', []):
                    # An unawaited coroutine, a generator, or a scheduled task may not run here.
                    deferred = str(call.get('execution', '')).startswith(('deferred', 'background'))
                    for category, mode, certainty, library in call_effects(call):
                        add({'effect': _effect(category, mode), 'category': category, 'mode': mode, 'detail': None,
                             'certainty': 'possible' if deferred else certainty, 'via': [], 'through': None, 'call': call['name'],
                             'library': library, 'file': call['span']['file'], 'lines': [call['span']['start']]})
                    if call.get('status') not in ('supported', 'possible'):
                        continue
                    for target in call.get('targets', []):
                        for inherited in effects_of(target, depth + 1):
                            if len(inherited['via']) >= MAX_DEPTH:
                                continue
                            weaker = call['status'] == 'possible' or deferred or inherited['certainty'] == 'possible'
                            add({**inherited, 'certainty': 'possible' if weaker else 'definite',
                                 'via': [scopes[target]['qualified']] + inherited['via'], 'through': target,
                                 'call': call['name'], 'file': call['span']['file'], 'lines': [call['span']['start']]})
        finally:
            active.discard(scope_id)
        result = sorted(records.values(), key=lambda r: (bool(r['via']), r['effect'], r.get('detail') or '', r['via']))
        memo[scope_id] = result
        return result

    for scope_id, scope in scopes.items():
        if scope['kind'] in ('module', 'class'):
            continue
        effects = effects_of(scope_id, 0)
        if effects:
            scope['sideEffects'] = effects
