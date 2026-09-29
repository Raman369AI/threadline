"""Transport-independent, read-only review queries."""
from .service import ThreadlineError


class UnknownQuery(ThreadlineError):
    pass


def query_api(pinned, path, query):
    if path == '/api/scope': return pinned.get_scope(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20), shallow=_one(query, 'shallow') == '1')
    if path == '/api/branch': return pinned.get_branch(_one(query, 'symbol', required=True), _one(query, 'operation', required=True), _int(query, 'arm', 0), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20))
    if path == '/api/compare': return pinned.compare_change(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), side=_one(query, 'side', 'working'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 40))
    if path == '/api/overview': return pinned.method_overview(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20))
    if path == '/api/tests': return pinned.related_tests(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20))
    if path == '/api/diagnostics': return pinned.diagnostics(snapshot_id=_one(query, 'snapshot'), category=_one(query, 'category', 'errors'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25))
    if path == '/api/index':
        return pinned.model(_one(query, 'snapshot'))
    if path == '/api/summary': return pinned.summary(snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25))
    if path == '/api/modules': return pinned.modules(snapshot_id=_one(query, 'snapshot'), file=_one(query, 'file'), query=_one(query, 'q', ''), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 20))
    if path == '/api/starts': return pinned.starts(snapshot_id=_one(query, 'snapshot'), query=_one(query, 'q', ''), category=_one(query, 'category'), method=_one(query, 'method'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 6))
    if path == '/api/symbols': return pinned.find_symbols(_one(query, 'q', ''), kind=_one(query, 'kind', 'callable'), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 25))
    if path == '/api/workflow': return pinned.get_workflow(_one(query, 'entrypoint', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 40))
    if path == '/api/method': return pinned.get_method(_one(query, 'symbol', required=True), snapshot_id=_one(query, 'snapshot'), cursor=_int(query, 'cursor', 0), limit=_int(query, 'limit', 50))
    if path == '/api/method-source':
        snapshot = _one(query, 'snapshot')
        cursor = _int(query, 'cursor', 0)
        if cursor and not snapshot:
            raise ThreadlineError('snapshot is required for a later method-source page')
        return pinned.get_method_source(
            _one(query, 'symbol', required=True), snapshot_id=snapshot,
            cursor=cursor, limit=_int(query, 'limit', 100))
    if path == '/api/dataflow':
        snapshot = _one(query, 'snapshot')
        cursor = _int(query, 'cursor', 0)
        model_cursor = _int(query, 'model_cursor', 0)
        node = _one(query, 'node')
        if (cursor > 0 or model_cursor > 0 or node) and not snapshot:
            raise ThreadlineError('snapshot is required for data-flow continuation')
        return pinned.get_dataflow(
            _one(query, 'symbol', required=True), snapshot_id=snapshot,
            node_id=node, direction=_one(query, 'direction', 'both'),
            cursor=cursor, limit=_int(query, 'limit', 25),
            model_cursor=model_cursor)
    if path == '/api/source': return pinned.get_source(snapshot_id=_one(query, 'snapshot'), evidence=_one(query, 'evidence'), file=_one(query, 'file'), start=_optional_int(query, 'start'), end=_optional_int(query, 'end'))
    raise UnknownQuery('Not found')

def _one(query, key, default=None, required=False):
    value = query.get(key, [default])[0]
    if required and not value: raise ThreadlineError(f'{key} is required')
    return value

def _int(query, key, default): return int(_one(query, key, default))
def _optional_int(query, key):
    value = _one(query, key)
    return int(value) if value is not None else None
