"""Retain direct template references as bounded, source-only snapshot assets."""

from __future__ import annotations

import ast
from bisect import bisect_right
import hashlib
import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .analyzer import EXCLUDED, read_source_bytes


MAX_TEMPLATE_REFERENCES = 256
MAX_TEMPLATE_ASSETS = 256
MAX_TEMPLATE_FILE_BYTES = 512 * 1024
MAX_TEMPLATE_TOTAL_BYTES = 8 * 1024 * 1024
MAX_TEMPLATE_WALK_ENTRIES = 50_000
MAX_TEMPLATE_WALK_SECONDS = 3.0
MAX_TEMPLATE_TAGS = 512
MAX_CLIENT_FETCHES = 128
MAX_CONTEXT_USE_LINKS = 512
MAX_LINK_CLIENT_FETCHES = 128
TEMPLATE_SUFFIXES = ('.html', '.htm', '.jinja', '.jinja2', '.j2')
_JINJA_TAG = re.compile(r'\{\{(.*?)\}\}|\{%\s*(.*?)\s*%\}', re.DOTALL)
_CLIENT_FETCH = re.compile(r"\bapiFetch\s*\(\s*(['\"])(/[^'\"\n]*)\1")
_FOR_TAG = re.compile(r'^for\s+([A-Za-z_]\w*)\s+in\s+(.+)$', re.DOTALL)
_TEMPLATE_MODULES = {'fastapi.templating', 'starlette.templating'}


def _assigned_names(statement: ast.AST) -> set[str]:
    """Return lexical names bound by a statement without visiting nested bodies."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {alias.asname or alias.name.split('.')[0] for alias in statement.names}
    targets = (statement.targets if isinstance(statement, ast.Assign) else
               [statement.target] if isinstance(statement, (ast.AnnAssign, ast.AugAssign)) else [])
    return {node.id for target in targets for node in ast.walk(target)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}


def _template_objects(tree: ast.AST) -> set[str]:
    """Find one-time module bindings to a known Jinja2Templates constructor."""
    body = getattr(tree, 'body', [])
    bindings: dict[str, int] = {}
    factories: set[str] = set()
    for statement in body:
        for name in _assigned_names(statement):
            bindings[name] = bindings.get(name, 0) + 1
        if isinstance(statement, ast.ImportFrom) and statement.module in _TEMPLATE_MODULES:
            factories.update(alias.asname or alias.name for alias in statement.names
                             if alias.name == 'Jinja2Templates')
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name in _TEMPLATE_MODULES:
                    factories.add((alias.asname or alias.name) + '.Jinja2Templates')
    factories = {name for name in factories
                 if bindings.get(name.split('.')[0]) == 1}
    objects: set[str] = set()
    for statement in body:
        value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Call):
            continue
        called = ast.unparse(value.func)
        if called not in factories:
            continue
        for name in _assigned_names(statement):
            if bindings.get(name) == 1:
                objects.add(name)
    # Reject later conditional/global rebinding that a top-level-only count
    # would miss. Attribute writes such as templates.env[...] do not rebind it.
    for name in list(objects):
        stores = sum(1 for statement in body
                     if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     for node in ast.walk(statement)
                     if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
                     and node.id == name)
        if stores != 1:
            objects.remove(name)
    return objects


def _provider_supported(tree: ast.AST, call: ast.Call, objects: set[str]) -> bool:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == 'TemplateResponse'
            and isinstance(func.value, ast.Name) and func.value.id in objects):
        return False
    receiver = func.value.id
    # A local binding anywhere in the containing function makes global
    # provenance uncertain, even when the call appears before that binding.
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                 and getattr(node, 'lineno', 0) <= call.lineno <= getattr(node, 'end_lineno', 0)]
    if not functions:
        return True
    scope = min(functions, key=lambda node: node.end_lineno - node.lineno)
    args = scope.args
    parameters = {arg.arg for arg in args.posonlyargs + args.args + args.kwonlyargs}
    parameters.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
    if receiver in parameters:
        return False
    for node in ast.walk(scope):
        if node is scope:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == receiver:
            return False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == receiver:
            return False
        if isinstance(node, ast.ExceptHandler) and node.name == receiver:
            return False
        if isinstance(node, (ast.Global, ast.Nonlocal)) and receiver in node.names:
            return False
    return True


def _span(file: str, info: dict[str, Any], node: ast.AST) -> dict[str, Any]:
    return {'file': file, 'start': getattr(node, 'lineno', 1),
            'end': getattr(node, 'end_lineno', getattr(node, 'lineno', 1)),
            'col': getattr(node, 'col_offset', 0),
            'endCol': getattr(node, 'end_col_offset', 0), 'hash': info['hash']}


def _scope_for(model: dict[str, Any], file: str, node: ast.AST) -> str | None:
    start = getattr(node, 'lineno', 1)
    end = getattr(node, 'end_lineno', start)
    choices = (scope for scope in model['scopes'].values()
               if scope['file'] == file and scope['span']['start'] <= start
               and scope['span']['end'] >= end)
    narrowest = min(choices,
                    key=lambda scope: (scope['span']['end'] - scope['span']['start'],
                                       scope['kind'] in ('module', 'class'),
                                       -scope['span']['start']), default=None)
    return narrowest['id'] if narrowest else None


def _literal_template(call: ast.Call) -> str | None:
    choices = [keyword.value for keyword in call.keywords if keyword.arg in ('name', 'template')]
    choices.extend(call.args[:3])
    for candidate in choices:
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            if candidate.value.lower().endswith(TEMPLATE_SUFFIXES):
                return candidate.value
    return None


def _context_dicts(call: ast.Call) -> list[ast.Dict]:
    """Return only the context slot adjacent to a literal template name."""
    explicit = [keyword.value for keyword in call.keywords if keyword.arg == 'context']
    if explicit:
        return [value for value in explicit if isinstance(value, ast.Dict)]
    for index, candidate in enumerate(call.args[:3]):
        if (isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
                and candidate.value.lower().endswith(TEMPLATE_SUFFIXES)):
            next_index = index + 1
            if next_index < len(call.args) and isinstance(call.args[next_index], ast.Dict):
                return [call.args[next_index]]
            return []
    return []


def _context_keys(call: ast.Call) -> list[str]:
    choices = _context_dicts(call)
    keys: set[str] = set()
    for candidate in choices:
        if isinstance(candidate, ast.Dict):
            keys.update(key.value for key in candidate.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str))
    return sorted(keys)


def literal_template_names(sources: dict[str, str]) -> set[str]:
    """Collect literal TemplateResponse names from retained Python source."""
    names: set[str] = set()
    for file, source in sorted(sources.items()):
        if 'TemplateResponse' not in source:
            continue
        try:
            tree = ast.parse(source, filename=file)
        except (SyntaxError, RecursionError):
            continue
        objects = _template_objects(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
            if called != 'TemplateResponse' or not _provider_supported(tree, node, objects):
                continue
            name = _literal_template(node)
            if name and _valid_name(name):
                names.add(name)
                if len(names) > MAX_TEMPLATE_REFERENCES:
                    raise ValueError('template reference budget reached')
    return names


def _references(model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    links: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for file, info in sorted(model['files'].items()):
        if 'TemplateResponse' not in info['source']:
            continue
        try:
            tree = ast.parse(info['source'], filename=file)
        except (SyntaxError, RecursionError) as exc:
            gaps.append({'file': file, 'reason': f'template scan could not parse source: {exc}'})
            continue
        objects = _template_objects(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ''
            if name != 'TemplateResponse':
                continue
            if len(links) >= MAX_TEMPLATE_REFERENCES:
                gaps.append({'file': file, 'reason': 'template reference budget reached'})
                return links, gaps
            literal = _literal_template(node)
            provider_status = ('supported' if _provider_supported(tree, node, objects)
                               else 'unknown')
            if provider_status == 'unknown':
                gaps.append({'file': file,
                             'reason': 'TemplateResponse provider is unknown or shadowed'})
            links.append({'scope': _scope_for(model, file, node), 'file': file,
                          'name': literal, 'contextKeys': _context_keys(node),
                          'span': _span(file, info, node), 'candidates': [],
                          'providerStatus': provider_status,
                          'status': ('unknown-provider' if provider_status == 'unknown' else
                                     'unresolved' if literal else 'dynamic')})
    return links, gaps


def _valid_name(name: str) -> bool:
    path = PurePosixPath(name.replace('\\', '/'))
    return not path.is_absolute() and bool(path.parts) and all(part not in ('', '.', '..') for part in path.parts)


def _excluded(path: Path, root: Path, user_excluded: set[str]) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(relative == prefix or relative.startswith(prefix + '/') for prefix in user_excluded)


def _scan_asset(source: str, file: str, hash_value: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    newlines = [index for index, char in enumerate(source) if char == '\n']
    line_at = lambda offset: bisect_right(newlines, offset) + 1
    uses: list[dict[str, Any]] = []
    truncated = False
    for match in _JINJA_TAG.finditer(source):
        if len(uses) >= MAX_TEMPLATE_TAGS:
            truncated = True
            break
        expression = (match.group(1) or match.group(2) or '').strip()
        line = line_at(match.start())
        uses.append({'expression': expression, 'span': {'file': file, 'start': line,
                    'end': line_at(match.end() - 1),
                    'col': 0, 'endCol': 0, 'hash': hash_value}})
    fetches: list[dict[str, Any]] = []
    for match in _CLIENT_FETCH.finditer(source):
        if len(fetches) >= MAX_CLIENT_FETCHES:
            truncated = True
            break
        line = line_at(match.start())
        fetches.append({'path': match.group(2), 'kind': 'later-client-request',
                        'span': {'file': file, 'start': line, 'end': line,
                                 'col': 0, 'endCol': 0, 'hash': hash_value}})
    return uses, fetches, truncated


def _context_uses(uses: list[dict[str, Any]], keys: list[str],
                  limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Link direct Jinja expressions to literal context keys, conservatively."""
    references: list[dict[str, Any]] = []
    active_aliases: list[tuple[str, str] | None] = []
    for use in uses:
        expression = use['expression']
        if expression.startswith('endfor'):
            if active_aliases:
                active_aliases.pop()
            continue
        aliases = {alias: key for item in active_aliases if item
                   for alias, key in [item]}
        for key in keys:
            if re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', expression):
                if len(references) >= limit:
                    return references, True
                references.append({'contextKey': key, 'expression': expression,
                                   'span': use['span'], 'certainty': 'possible'})
        for alias, key in aliases.items():
            match = re.search(r'(?<!\w)' + re.escape(alias) + r'((?:\.[A-Za-z_]\w*)*)', expression)
            if match:
                if len(references) >= limit:
                    return references, True
                references.append({'contextKey': key, 'expression': expression,
                                   'path': match.group(0), 'via': alias,
                                   'span': use['span'], 'certainty': 'possible'})
        loop = _FOR_TAG.match(expression)
        if loop:
            source = loop.group(2)
            source_key = next((key for key in keys
                               if re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', source)), None)
            if source_key is None:
                source_key = next((key for alias, key in aliases.items()
                                   if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', source)), None)
            active_aliases.append((loop.group(1), source_key) if source_key else None)
    return references, False


def attach_template_assets(model: dict[str, Any], root: str | Path) -> None:
    """Attach direct template candidates without rendering or importing targets.

    The input model is an unpublished analysis model. This function reads only
    literal ``TemplateResponse`` candidates beneath ``root``. Every read is
    bounded and refuses symlinks. Missing, ambiguous, and truncated matches
    remain visible rather than implying a rendered template was identified.
    """
    root = Path(root).resolve()
    links, gaps = _references(model)
    assets: dict[str, dict[str, Any]] = {}
    manifest: dict[str, Any] = {}
    user_excluded = set(model.get('analysisOptions', {}).get('exclude', []))
    wanted = {PurePosixPath(link['name'].replace('\\', '/')).name
              for link in links if link['providerStatus'] == 'supported'
              and link['name'] and _valid_name(link['name'])}
    total_bytes = 0
    visited = 0
    started = time.monotonic()
    if wanted:
        for base, dirs, names in os.walk(root, followlinks=False):
            base_path = Path(base)
            dirs[:] = sorted(directory for directory in dirs
                       if directory not in EXCLUDED
                       and not (base_path / directory).is_symlink()
                       and not _excluded(base_path / directory, root, user_excluded))
            visited += len(dirs) + len(names)
            if visited > MAX_TEMPLATE_WALK_ENTRIES or time.monotonic() - started > MAX_TEMPLATE_WALK_SECONDS:
                gaps.append({'file': '', 'reason': 'template discovery budget reached'})
                break
            for filename in sorted(names):
                if filename not in wanted:
                    continue
                path = base_path / filename
                if path.is_symlink() or _excluded(path, root, user_excluded):
                    continue
                file = path.relative_to(root).as_posix()
                if len(assets) >= MAX_TEMPLATE_ASSETS:
                    gaps.append({'file': file, 'reason': 'template asset count budget reached'})
                    break
                try:
                    raw = read_source_bytes(path, root, limit=MAX_TEMPLATE_FILE_BYTES)
                    if total_bytes + len(raw) > MAX_TEMPLATE_TOTAL_BYTES:
                        gaps.append({'file': file, 'reason': 'template total byte budget reached'})
                        continue
                    source = raw.decode('utf-8')
                except (OSError, ValueError, UnicodeError) as exc:
                    manifest[file] = {'hash': None, 'status': 'error', 'reason': str(exc)}
                    gaps.append({'file': file, 'reason': f'template could not be read: {exc}'})
                    continue
                total_bytes += len(raw)
                hash_value = hashlib.sha256(raw).hexdigest()
                uses, fetches, truncated = _scan_asset(source, file, hash_value)
                assets[file] = {'source': source, 'hash': hash_value,
                                'lines': len(source.splitlines()),
                                'uses': uses, 'clientFetches': fetches,
                                'truncated': truncated}
                manifest[file] = {'hash': hash_value, 'status': 'read'}
                if truncated:
                    gaps.append({'file': file, 'reason': 'template expression budget reached'})
    for link in links:
        if link['providerStatus'] != 'supported':
            continue
        name = link['name']
        if name is None:
            continue
        if not _valid_name(name):
            link['status'] = 'invalid-name'
            gaps.append({'file': link['file'], 'reason': f'invalid template name: {name}'})
            continue
        parts = PurePosixPath(name.replace('\\', '/')).parts
        link['candidates'] = sorted(file for file in assets
                                    if PurePosixPath(file).parts[-len(parts):] == parts)
        link['status'] = ('missing' if not link['candidates'] else
                          'matched' if len(link['candidates']) == 1 else 'ambiguous')
        link['contextUses'] = []
        for file in link['candidates']:
            remaining = MAX_CONTEXT_USE_LINKS - len(link['contextUses'])
            if remaining <= 0:
                link['contextUseTruncated'] = True
                break
            references, truncated = _context_uses(assets[file]['uses'],
                                                  link['contextKeys'], remaining)
            link['contextUses'].extend(dict(use, template=file) for use in references)
            if truncated:
                link['contextUseTruncated'] = True
                break
        if link.get('contextUseTruncated'):
            gaps.append({'file': link['file'], 'reason': 'template context use budget reached'})
        link['clientFetches'] = []
        for file in link['candidates']:
            for fetch in assets[file]['clientFetches']:
                if len(link['clientFetches']) >= MAX_LINK_CLIENT_FETCHES:
                    link['clientFetchesTruncated'] = True
                    break
                link['clientFetches'].append(dict(fetch, template=file))
            if link.get('clientFetchesTruncated'):
                gaps.append({'file': link['file'], 'reason': 'template client fetch budget reached'})
                break
        if not link['candidates']:
            manifest[f'@missing:{name}'] = {'hash': None, 'status': 'missing'}
    model['templateAssets'] = assets
    model['templateLinks'] = links
    model['templateManifest'] = manifest
    model['templateGaps'] = gaps
