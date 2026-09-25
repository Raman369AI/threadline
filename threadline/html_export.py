"""Package the browser and frozen analysis into one serverless HTML file."""
from __future__ import annotations

import json
import os
import tempfile
from importlib.resources import files
from pathlib import Path

from .dataflow import build_dataflow
from .service import (
    SnapshotStore, ThreadlineError, _portable_evidence_ids, _source_info,
    _template_summary, add_evidence_ids,
)
from .workflows import generic_workflow

MAX_HTML_BYTES = 256 * 1024 * 1024


def _collect(query, field, **kwargs):
    result = query(cursor=0, limit=100, **kwargs)
    rows = list(result[field]['items'])
    cursor = result[field]['nextCursor']
    while cursor is not None:
        page = query(cursor=cursor, limit=100, **kwargs)
        rows.extend(page[field]['items'])
        cursor = page[field]['nextCursor']
    result[field] = rows
    return result


def _snapshot(store, model):
    snapshot = model['snapshotId']
    result = {
        'summary': store.summary(snapshot_id=snapshot),
        'catalog': add_evidence_ids(model['catalog']),
        'scopes': model['scopes'],
        'sources': {name: {'source': info['source'], 'hash': info['hash']}
                    for name, info in {**model['files'], **model.get('templateAssets', {})}.items()},
        'diagnostics': {'errors': model['errors'], 'excluded': model['excluded'],
                        'unmodeledCalls': model['coverage']['unmodeledCalls'],
                        **{key: value for key, value in model.get('changes', {}).items()
                           if isinstance(value, list)}},
        'methods': {},
    }
    config = _source_info(model, 'pyproject.toml')
    if config:
        result['sources']['pyproject.toml'] = config
    for symbol, scope in model['scopes'].items():
        if scope['kind'] in ('module', 'class'):
            continue
        graph = build_dataflow(model, symbol)
        graph['templates'] = _template_summary(model, symbol, graph.get('templates', []))
        # Model definitions have their own continuation, independent of events.
        while graph['nextModelOffset'] is not None:
            page = build_dataflow(model, symbol, model_offset=graph['nextModelOffset'])
            graph['models'].extend(page['models'])
            graph['nextModelOffset'] = page['nextModelOffset']
            graph['truncated'] = graph.get('truncated', False) or page.get('truncated', False)
            graph['omitted'] = max(graph.get('omitted', 0), page.get('omitted', 0))
        result['methods'][symbol] = {
            'overview': _collect(store.method_overview, 'callers', symbol_id=symbol, snapshot_id=snapshot),
            'tests': _collect(store.related_tests, 'items', symbol_id=symbol, snapshot_id=snapshot),
            'workflow': add_evidence_ids(generic_workflow(model, symbol)),
            'dataflow': _portable_evidence_ids(graph),
        }
    return result


def _comparisons(store):
    changes = store.current.get('changes')
    result = {}
    if not changes:
        return result
    for side, snapshot in [('working', store.current_id), ('base', changes['baseSnapshotId'])]:
        changed_files = {row['path'] if side == 'working' else row.get('oldPath', row['path'])
                         for row in changes['files']}
        for symbol, scope in store.model(snapshot)['scopes'].items():
            if scope['kind'] in ('module', 'class') or scope['file'] not in changed_files:
                continue
            comparison = store.compare_change(symbol, side=side, limit=100)
            for key in ('before', 'after'):
                if comparison[key]:
                    comparison[key]['lines'] = comparison[key]['lines']['items']
            cursor = comparison['nextCursor']
            while cursor is not None:
                page = store.compare_change(symbol, side=side, cursor=cursor, limit=100)
                for key in ('before', 'after'):
                    if comparison[key]:
                        comparison[key]['lines'].extend(page[key]['lines']['items'])
                cursor = page['nextCursor']
            comparison['nextCursor'] = None
            result[side + ':' + symbol] = comparison
    return result


def write_html(store: SnapshotStore, output: str | Path) -> Path:
    """Write atomically; source remains inert JSON and every asset is embedded."""
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() not in ('.html', '.htm'):
        raise ThreadlineError('--output must name an .html or .htm file')
    assets = files('threadline.static')
    document = assets.joinpath('index.html').read_text(encoding='utf-8')
    document = document.replace('<link rel="stylesheet" href="styles.css">',
                                '<style>' + assets.joinpath('styles.css').read_text(encoding='utf-8') + '</style>')
    # Inline scripts run after the body exists, in the same order as deferred scripts.
    scripts = []
    for name in ('app', 'workflow', 'method', 'review_data', 'codefirst'):
        document = document.replace(f'<script src="{name}.js" defer></script>', '')
        scripts.append(assets.joinpath(name + '.js').read_text(encoding='utf-8'))
    policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    document = document.replace('<meta charset="utf-8">',
                                f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{policy}">')
    document = document.replace('<button id="refreshButton"', '<button hidden id="refreshButton"')
    document = document.replace('<span class="top-spacer"></span>',
                                '<span class="top-spacer"></span><span title="Regenerate this HTML to read changed files">Saved HTML review</span>')
    prefix, suffix = document.split('</body>', 1)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.threadline-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            size = 0

            def write(text):
                nonlocal size
                size += len(text.encode('utf-8'))
                if size > MAX_HTML_BYTES:
                    raise ThreadlineError('HTML exceeds 256 MiB; narrow the review with --source-root or --exclude')
                stream.write(text)

            def data(value):
                for chunk in json.JSONEncoder(ensure_ascii=True, separators=(',', ':')).iterencode(value):
                    # A repository string must never close its script element.
                    write(chunk.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))

            write(prefix + '<script id="threadline-snapshot" type="application/json">{"current":')
            data(store.current_id)
            write(',"snapshots":{')
            for index, (snapshot, model) in enumerate(store._models.items()):
                if index:
                    write(',')
                data(snapshot)
                write(':')
                data(_snapshot(store, model))
            write('},"comparisons":')
            data(_comparisons(store))
            write('}</script>\n')
            for script in [assets.joinpath('offline.js').read_text(encoding='utf-8'), *scripts]:
                write('<script>\n' + script + '\n</script>\n')
            write('</body>' + suffix)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
