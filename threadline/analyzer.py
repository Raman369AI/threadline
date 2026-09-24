"""Read Python syntax and build an evidence-linked review model. Never imports targets."""
from __future__ import annotations

import ast
import hashlib
import io
import stat
import time
import os
import tokenize
from collections import Counter, defaultdict
from pathlib import Path

EXCLUDED = {'.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules', 'dist', 'build', '.tox', '.mypy_cache', '.pytest_cache'}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 10000
MAX_AST_NODES = 2_000_000
MAX_ANALYSIS_SECONDS = 60


class AnalysisLimitError(ValueError):
    """Source exceeds the supported analysis budget; narrow the source roots."""


def read_source_bytes(path, root, limit=MAX_FILE_BYTES):
    """Read one regular file, refusing symlinks and oversized inputs."""
    relative = path.relative_to(root)
    # On POSIX, pin every directory component to prevent symlink swaps.
    descriptors = []
    try:
        if os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW'):
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            descriptors.append(parent)
            for part in relative.parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(parent)
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        else:
            if any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts)+1)):
                raise OSError('symlink source is not allowed')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError('source is not a regular file')
        if info.st_size > limit:
            raise AnalysisLimitError(f'{relative}: exceeds {limit} byte file budget; use --exclude')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise AnalysisLimitError(f'{relative}: exceeds file byte budget')
        return raw
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def short(text, limit=110):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def text(node):
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


class Analyzer:
    def __init__(self, root, source_roots=None, exclude=None):
        self.root = Path(root).resolve()
        self.source_roots = [self._inside(path) for path in (source_roots or ['.'])]
        self.user_excluded = {Path(path).as_posix().strip('/') for path in (exclude or [])}
        self.files = {}
        self.discovery_manifest = {}
        self.scopes = {}
        self.scope_nodes = {}
        self.ast_scopes = {}
        self.node_files = {}
        self.parents = {}
        self.symbols = {}
        self.module_scopes = {}
        self.module_aliases = {}
        self.instances = {}
        self.class_attributes = defaultdict(lambda: defaultdict(list))
        self.parameter_nodes = {}
        self.class_nodes = {}
        self.mro_cache = {}
        self.local_bindings = defaultdict(set)
        self.declarations = defaultdict(lambda: {'global': set(), 'nonlocal': set()})
        self.rebindings = {}
        self.duplicate_definitions = defaultdict(list)
        self.ambiguous_imports = set()
        self.import_nodes = defaultdict(list)
        self.excluded = []
        self.errors = []
        self.calls = []
        self.started = time.monotonic()
        self.total_bytes = 0
        self.total_nodes = 0
        configuration_path = self.root / 'pyproject.toml'
        configuration_raw = None
        try:
            configuration_raw = read_source_bytes(configuration_path, self.root)
            self.configuration = configuration_raw.decode('utf-8')
            self.configuration_manifest = {'present': True, 'hash': hashlib.sha256(configuration_raw).hexdigest()}
        except (OSError, UnicodeError) as exc:
            self.configuration = ''
            present = configuration_path.exists() or configuration_path.is_symlink()
            self.configuration_manifest = {'present': present, 'hash': hashlib.sha256(configuration_raw).hexdigest() if configuration_raw is not None else None}
            if present:
                self.configuration_manifest['error'] = type(exc).__name__ + ': ' + str(exc)
                self.errors.append({
                    'file': 'pyproject.toml',
                    'message': 'Configuration could not be read: ' + self.configuration_manifest['error'],
                    'kind': 'configuration',
                })
        self.construct_counts = Counter()


    def _inside(self, value):
        path = (self.root / value).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f'source root is outside repository: {value}')
        if not path.is_dir():
            raise ValueError(f'source root is not a directory: {value}')
        return path

    def is_user_excluded(self, path):
        relative = path.relative_to(self.root).as_posix()
        return any(relative == prefix or relative.startswith(prefix + '/') for prefix in self.user_excluded)

    def span(self, node, file):
        start = getattr(node, 'lineno', 1)
        end = getattr(node, 'end_lineno', start)
        return {'file': file, 'start': start, 'end': end,
                'col': getattr(node, 'col_offset', 0), 'endCol': getattr(node, 'end_col_offset', 0),
                'hash': self.files[file]['hash']}

    def ident(self, node, file, suffix=''):
        return (f"{file}:{getattr(node, 'lineno', 1)}:{getattr(node, 'col_offset', 0)}:"
                f"{getattr(node, 'end_lineno', getattr(node, 'lineno', 1))}:"
                f"{getattr(node, 'end_col_offset', getattr(node, 'col_offset', 0))}:"
                f"{type(node).__name__}{suffix}")

    def discover(self):
        seen = set()
        for scan_root in self.source_roots:
            for base, dirs, names in os.walk(scan_root, followlinks=False):
                for name in list(dirs):
                    path = Path(base) / name
                    if name in EXCLUDED or path.is_symlink() or self.is_user_excluded(path):
                        self.excluded.append({'path': str(path.relative_to(self.root)), 'reason': 'symlink' if path.is_symlink() else 'configured exclusion' if self.is_user_excluded(path) else 'environment / generated directory'})
                        dirs.remove(name)
                for name in sorted(names):
                    if not name.endswith('.py'):
                        continue
                    path = Path(base) / name
                    file = path.relative_to(self.root).as_posix()
                    if file in seen or self.is_user_excluded(path):
                        continue
                    seen.add(file)
                    if len(seen) > MAX_FILES or time.monotonic() - self.started > MAX_ANALYSIS_SECONDS:
                        raise AnalysisLimitError('Analysis budget exceeded; narrow --source-root or --exclude')
                    if path.is_symlink():
                        self.excluded.append({'path': file, 'reason': 'symlink'}); continue
                    raw = None
                    try:
                        raw = read_source_bytes(path, self.root)
                        self.discovery_manifest[file] = {'hash': hashlib.sha256(raw).hexdigest(), 'status': 'read'}
                        self.total_bytes += len(raw)
                        if self.total_bytes > MAX_TOTAL_BYTES:
                            raise AnalysisLimitError('Repository byte budget exceeded; narrow --source-root')
                        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                        source = raw.decode(encoding)
                        tree = ast.parse(source, filename=file, type_comments=True)
                    except (SyntaxError, UnicodeError, OSError, RecursionError) as exc:
                        self.discovery_manifest[file] = {
                            'hash': hashlib.sha256(raw).hexdigest() if raw is not None else None,
                            'status': 'error', 'error': type(exc).__name__ + ': ' + str(exc),
                        }
                        self.errors.append({'file': file, 'message': str(exc)}); continue
                    self.total_nodes += sum(1 for _ in ast.walk(tree))
                    if self.total_nodes > MAX_AST_NODES:
                        raise AnalysisLimitError('AST node budget exceeded; narrow --source-root')
                    self.discovery_manifest[file]['status'] = 'parsed'
                    self.files[file] = {'source': source, 'hash': hashlib.sha256(raw).hexdigest(), 'tree': tree, 'lines': len(source.splitlines())}
                    parts = list(path.relative_to(scan_root).with_suffix('').parts)
                    if scan_root == self.root and 'src' in parts:
                        parts = parts[parts.index('src') + 1:]
                    if parts[-1] == '__init__': parts.pop()
                    module = '.'.join(parts)
                    if scan_root == self.root and 'src' not in path.relative_to(scan_root).parts and len(parts) > 1 and not (self.root / parts[0] / '__init__.py').exists():
                        self.module_aliases.setdefault(module, set()).add('.'.join(parts[1:]))
                    scope = self.register(tree, file, None, module, '<module>', 'module')
                    self.module_scopes[module] = scope['id']
                    for node in ast.walk(tree):
                        self.node_files[id(node)] = file
                        for child in ast.iter_child_nodes(node): self.parents[id(child)] = node
                    self.index_children(tree, file, scope, module)

    def register(self, node, file, parent, module, name, kind):
        scope_id = self.ident(node, file, ':scope')
        qualified = name if parent is None or parent['kind'] == 'module' else parent['qualified'] + '.' + name
        span = self.span(node, file)
        if kind == 'module':
            span['end'] = self.files[file]['lines']
        decorators = [text(d) for d in getattr(node, 'decorator_list', [])]
        if getattr(node, 'decorator_list', []):
            span['start'] = node.decorator_list[0].lineno
        args = getattr(node, 'args', None)
        params = []
        if args:
            positional = args.posonlyargs + args.args
            defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
            for index, (arg, default) in enumerate(zip(positional, defaults)):
                params.append({'name': arg.arg, 'kind': 'posonly' if index < len(args.posonlyargs) else 'positional', 'default': text(default) if default is not None else None, 'annotation': text(arg.annotation) if arg.annotation else None})
            if args.vararg:
                params.append({'name': args.vararg.arg, 'kind': 'varargs', 'default': None})
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                params.append({'name': arg.arg, 'kind': 'keyword', 'default': text(default) if default is not None else None, 'annotation': text(arg.annotation) if arg.annotation else None})
            if args.kwarg:
                params.append({'name': args.kwarg.arg, 'kind': 'kwargs', 'default': None})
        scope = {'id': scope_id, 'symbolKey': f'{module}:{qualified}:{kind}', 'file': file, 'name': name, 'qualified': qualified, 'module': module, 'kind': kind,
                 'parent': parent['id'] if parent else None, 'span': span, 'params': params, 'async': isinstance(node, ast.AsyncFunctionDef), 'generator': False,
                 'signature': short(text(node).split('\n')[0], 240), 'decorators': decorators, 'symbols': {}, 'imports': {}, 'flow': []}
        def own_yield(current):
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.Yield, ast.YieldFrom)):
                    return True
                if not isinstance(child, SCOPE_TYPES) and own_yield(child):
                    return True
            return False
        scope['generator'] = own_yield(node) if kind not in ('module', 'class') else False
        returns = []
        def own_returns(current):
            if isinstance(current, ast.Return):
                returns.append(text(current.value) if current.value is not None else 'None')
            for child in ast.iter_child_nodes(current):
                if not isinstance(child, SCOPE_TYPES):
                    own_returns(child)
        if kind not in ('module', 'class'):
            own_returns(node)
        if isinstance(node, ast.Lambda):
            returns.append(text(node.body))
        response_model = None
        for decorator in getattr(node, 'decorator_list', []):
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg == 'response_model':
                        response_model = text(keyword.value)
        scope['output'] = {
            'annotation': text(node.returns) if getattr(node, 'returns', None) else None,
            'returns': returns,
            'responseModel': response_model,
        }
        self.scopes[scope_id] = scope
        self.scope_nodes[scope_id] = node
        self.ast_scopes[id(node)] = scope_id
        if isinstance(node, ast.ClassDef):
            self.class_nodes[scope_id] = node
        if parent:
            parent['symbols'][name] = scope_id
            self.duplicate_definitions[(parent['id'], name)].append(scope_id)
        self.symbols.setdefault(f'{module}.{qualified}', []).append(scope_id)
        return scope

    def index_children(self, node, file, parent, module):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPE_TYPES):
                if isinstance(child, ast.ClassDef):
                    kind, name = 'class', child.name
                elif isinstance(child, ast.Lambda):
                    kind, name = 'lambda', f'<lambda@{child.lineno}:{child.col_offset}>'
                else:
                    kind = 'method' if parent['kind'] == 'class' else 'nested function' if parent['kind'] not in ('module', 'class') else 'function'
                    name = child.name
                scope = self.register(child, file, parent, module, name, kind)
                self.index_children(child, file, scope, module)
            else:
                self.index_children(child, file, parent, module)

    def lexical(self, scope, name):
        cursor = scope
        while cursor:
            declarations = self.declarations[cursor['id']]
            if name in declarations['global'] and cursor['kind'] != 'module':
                cursor = self.scopes.get(self.module_scopes.get(cursor['module']))
                if cursor and cursor['kind'] != 'module':
                    cursor = None
                continue
            if name in declarations['nonlocal']:
                cursor = self.scopes.get(cursor['parent'])
                continue
            # A class suite is not an enclosing lexical namespace for a method.
            if cursor is not scope and cursor['kind'] == 'class':
                cursor = self.scopes.get(cursor['parent'])
                continue
            if name in cursor['symbols']:
                return self.duplicate_definitions.get((cursor['id'], name), [cursor['symbols'][name]]), 'definition in lexical scope'
            if name in cursor['imports']:
                imported = cursor['imports'][name]
                return self.symbols.get(imported, []), f'import {imported}'
            if name in self.local_bindings[cursor['id']]:
                return [], 'local binding shadows enclosing definitions'
            cursor = self.scopes.get(cursor['parent'])
        return [], ''

    def import_path(self, scope, node):
        prefix = node.module or ''
        if node.level:
            parts = scope['module'].split('.')
            if not scope['file'].endswith('__init__.py'):
                parts.pop()
            if node.level > 1:
                parts = parts[:-(node.level - 1)]
            prefix = '.'.join(parts + ([prefix] if prefix else []))
        return prefix

    def collect_imports(self, node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPE_TYPES):
                self.collect_imports(child, self.scopes[self.ast_scopes[id(child)]])
            else:
                if isinstance(child, ast.ImportFrom):
                    prefix = self.import_path(scope, child)
                    for alias in child.names:
                        key = alias.asname or alias.name
                        if key in scope['imports']: self.ambiguous_imports.add((scope['id'], key))
                        scope['imports'][key] = f'{prefix}.{alias.name}'
                        self.import_nodes[(scope['id'], key)].append(child)
                elif isinstance(child, ast.Import):
                    for alias in child.names:
                        key = alias.asname or alias.name.split('.')[0]
                        if key in scope['imports']: self.ambiguous_imports.add((scope['id'], key))
                        scope['imports'][key] = alias.name if alias.asname else alias.name.split('.')[0]
                        self.import_nodes[(scope['id'], key)].append(child)
                self.collect_imports(child, scope)

    def imported_name(self, scope, name):
        cursor = scope
        while cursor:
            if cursor is not scope and cursor['kind'] == 'class':
                cursor = self.scopes.get(cursor['parent'])
                continue
            if name in cursor['imports']:
                return cursor['imports'][name]
            cursor = self.scopes.get(cursor['parent'])
        return name

    def imported_path(self, scope, node):
        """Return a source-backed import path for a dotted expression."""
        if isinstance(node, ast.Name):
            cursor = scope
            while cursor:
                if cursor is not scope and cursor['kind'] == 'class':
                    cursor = self.scopes.get(cursor['parent'])
                    continue
                if node.id in cursor['imports']:
                    return cursor['imports'][node.id]
                cursor = self.scopes.get(cursor['parent'])
            return None
        if isinstance(node, ast.Attribute):
            base = self.imported_path(scope, node.value)
            return base + '.' + node.attr if base else None
        return None

    @staticmethod
    def bound_names(target):
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from Analyzer.bound_names(element)
        elif isinstance(target, ast.Starred):
            yield from Analyzer.bound_names(target.value)

    @staticmethod
    def pattern_names(pattern):
        if isinstance(pattern, ast.MatchAs) and pattern.name:
            yield pattern.name
        if isinstance(pattern, ast.MatchStar) and pattern.name:
            yield pattern.name
        if isinstance(pattern, ast.MatchMapping) and pattern.rest:
            yield pattern.rest
        for child in ast.iter_child_nodes(pattern):
            yield from Analyzer.pattern_names(child)

    def add_instance(self, scope, name, type_name, evidence, origin_id=None):
        key = (scope['id'], name)
        candidate = (type_name, origin_id or scope['id'], evidence)
        self.instances.setdefault(key, [])
        if candidate not in self.instances[key]:
            self.instances[key].append(candidate)

    def value_type_candidates(self, value, scope):
        if isinstance(value, ast.Call):
            return [(text(value.func), scope['id'], 'constructor-shaped assignment')]
        if isinstance(value, ast.Name):
            return [(type_name, origin, 'forwarded from ' + value.id + ' (' + evidence + ')')
                    for type_name, origin, evidence in self.instance_type(scope, value.id)]
        if isinstance(value, ast.IfExp):
            return self.value_type_candidates(value.body, scope) + self.value_type_candidates(value.orelse, scope)
        return []

    def instance_type(self, scope, name):
        cursor = scope
        while cursor:
            if cursor is not scope and cursor['kind'] == 'class':
                cursor = self.scopes.get(cursor['parent'])
                continue
            key = (cursor['id'], name)
            if key in self.instances:
                return self.instances[key]
            imported = cursor['imports'].get(name)
            if imported:
                for module, module_id in self.module_scopes.items():
                    if imported.startswith(module + '.'):
                        found = self.instances.get((module_id, imported[len(module) + 1:]))
                        if found:
                            return found
            if name in self.local_bindings[cursor['id']]:
                return []
            cursor = self.scopes.get(cursor['parent'])
        return []

    def collect_bindings(self, node, scope):
        """Collect Python local binders without crossing a nested scope boundary."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs + [a for a in (args.vararg, args.kwarg) if a]:
                self.local_bindings[scope['id']].add(arg.arg)
                if isinstance(arg.annotation, (ast.Name, ast.Attribute)):
                    self.add_instance(scope, arg.arg, text(arg.annotation), 'parameter annotation')
                    self.parameter_nodes[(scope['id'], arg.arg)] = arg

        def declarations(child):
            if isinstance(child, SCOPE_TYPES):
                return
            if isinstance(child, ast.Global):
                self.declarations[scope['id']]['global'].update(child.names)
            elif isinstance(child, ast.Nonlocal):
                self.declarations[scope['id']]['nonlocal'].update(child.names)
            for sub in ast.iter_child_nodes(child):
                declarations(sub)

        for child in ast.iter_child_nodes(node):
            declarations(child)

        def remember(target, value=None, annotation=None, source_node=None):
            names = list(self.bound_names(target))
            for name in names:
                if name not in self.declarations[scope['id']]['global'] | self.declarations[scope['id']]['nonlocal']:
                    self.local_bindings[scope['id']].add(name)
                    self.rebindings.setdefault(scope['id'], set()).add(name)
                candidates = self.value_type_candidates(value, scope) if len(names) == 1 else []
                if isinstance(annotation, (ast.Name, ast.Attribute)):
                    candidates.append((text(annotation), scope['id'], 'annotation'))
                for type_name, origin, evidence in candidates:
                    self.add_instance(scope, name, type_name, evidence, origin)
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in ('self', 'cls'):
                owner = self.scopes.get(scope['parent'])
                if owner and owner['kind'] == 'class':
                    candidates = self.value_type_candidates(value, scope)
                    if isinstance(annotation, (ast.Name, ast.Attribute)):
                        candidates.append((text(annotation), scope['id'], 'instance attribute annotation'))
                    for candidate in candidates:
                        parameter = self.parameter_nodes.get((scope['id'], value.id)) if isinstance(value, ast.Name) else None
                        documented = (*candidate, source_node or target, parameter)
                        if documented not in self.class_attributes[owner['id']][target.attr]:
                            self.class_attributes[owner['id']][target.attr].append(documented)

        def visit(child):
            if isinstance(child, SCOPE_TYPES):
                self.collect_bindings(child, self.scopes[self.ast_scopes[id(child)]])
                return
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    remember(target, child.value, source_node=child)
            elif isinstance(child, ast.AnnAssign):
                remember(child.target, child.value, child.annotation, child)
            elif isinstance(child, ast.AugAssign):
                remember(child.target)
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                remember(child.target)
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    if item.optional_vars:
                        remember(item.optional_vars)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                remember(ast.Name(id=child.name, ctx=ast.Store()))
            elif isinstance(child, ast.NamedExpr):
                remember(child.target, child.value)
            elif isinstance(child, ast.match_case):
                for name in self.pattern_names(child.pattern):
                    remember(ast.Name(id=name, ctx=ast.Store()))
            elif isinstance(child, ast.Delete):
                for target in child.targets:
                    remember(target)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    name = alias.asname or (alias.name.split('.')[0] if isinstance(child, ast.Import) else alias.name)
                    self.local_bindings[scope['id']].add(name)
            for sub in ast.iter_child_nodes(child):
                visit(sub)
        for child in ast.iter_child_nodes(node):
            visit(child)

    def enclosing_class(self, scope):
        cursor = scope
        while cursor:
            cursor = self.scopes.get(cursor['parent'])
            if cursor and cursor['kind'] == 'class':
                return cursor
        return None

    def class_reference(self, node, scope):
        if isinstance(node, ast.Name):
            targets, _ = self.lexical(scope, node.id)
        else:
            path = self.imported_path(scope, node)
            targets = self.symbols.get(path, []) if path else []
        return [target for target in targets if self.scopes[target]['kind'] == 'class']

    def class_reference_text(self, name, scope):
        try:
            expression = ast.parse(name, mode='eval').body
        except SyntaxError:
            return []
        return self.class_reference(expression, scope)

    def member_targets(self, class_id, member, seen=None):
        """Find source candidates in a class and statically identifiable bases."""
        seen = set() if seen is None else seen
        if class_id in seen:
            return []
        seen.add(class_id)
        scope = self.scopes[class_id]
        direct = self.duplicate_definitions.get((class_id, member), [])
        if direct:
            return direct
        order = self.class_mro(class_id)
        if order is not None:
            for base_id in order[1:]:
                direct = self.duplicate_definitions.get((base_id, member), [])
                if direct:
                    return direct
            return []
        node = self.class_nodes.get(class_id)
        if not node:
            return []
        origin = self.scopes.get(scope['parent'])
        inherited = []
        for base in node.bases:
            for base_id in self.class_reference(base, origin):
                inherited.extend(self.member_targets(base_id, member, seen.copy()))
        return list(dict.fromkeys(inherited))

    def class_mro(self, class_id, active=None):
        """Return source-class C3 order only when every base is unambiguous."""
        if class_id in self.mro_cache:
            return self.mro_cache[class_id]
        active = set() if active is None else active
        if class_id in active:
            return None
        active.add(class_id)
        node = self.class_nodes.get(class_id)
        if node is None or node.keywords or self.scopes[class_id]['decorators']:
            return None
        origin = self.scopes.get(self.scopes[class_id]['parent'])
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == 'object' and self.lexical(origin, 'object') == ([], ''):
                continue
            candidates = self.class_reference(base, origin)
            if len(candidates) != 1:
                self.mro_cache[class_id] = None
                return None
            bases.append(candidates[0])
        sequences = []
        for base_id in bases:
            base_order = self.class_mro(base_id, active.copy())
            if base_order is None:
                self.mro_cache[class_id] = None
                return None
            sequences.append(list(base_order))
        sequences.append(list(bases))
        order = [class_id]
        while any(sequences):
            candidate = next((sequence[0] for sequence in sequences if sequence
                              and not any(sequence[0] in other[1:] for other in sequences)), None)
            if candidate is None:
                self.mro_cache[class_id] = None
                return None
            order.append(candidate)
            for sequence in sequences:
                if sequence and sequence[0] == candidate:
                    sequence.pop(0)
        self.mro_cache[class_id] = order
        return order

    def descriptor_methods(self, targets):
        descriptor = []
        ordinary = []
        for target_id in targets:
            decorators = self.scopes[target_id]['decorators']
            if any(decorator.split('(')[0].split('.')[-1] in ('property', 'cached_property', 'setter', 'deleter')
                   for decorator in decorators):
                descriptor.append(target_id)
            else:
                ordinary.append(target_id)
        return ordinary, descriptor

    def callable_member_result(self, targets, status, reason, scope=None, receiver=None, call_node=None):
        ordinary, descriptors = self.descriptor_methods(targets)
        if descriptors and not ordinary:
            return [], 'unknown', 'descriptor getter is accessed before this call; its callable result is not resolved'
        if descriptors:
            status = 'possible'
            reason += '; a descriptor may instead supply the callable result'
        return self.target_result(ordinary, status, reason, scope, receiver, call_node)

    def class_attribute_candidates(self, class_id, attribute, seen=None):
        seen = set() if seen is None else seen
        if class_id in seen:
            return []
        seen.add(class_id)
        own = list(self.class_attributes[class_id].get(attribute, []))
        node = self.class_nodes.get(class_id)
        if not node:
            return own
        origin = self.scopes.get(self.scopes[class_id]['parent'])
        for base in node.bases:
            for base_id in self.class_reference(base, origin):
                own.extend(self.class_attribute_candidates(base_id, attribute, seen.copy()))
        return list(dict.fromkeys(own))

    def inferred_instance_candidates(self, receiver, scope):
        if isinstance(receiver, ast.Name):
            return self.instance_type(scope, receiver.id)
        if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) and receiver.value.id in ('self', 'cls'):
            owner = self.enclosing_class(scope)
            if owner:
                return self.class_attribute_candidates(owner['id'], receiver.attr)
        if isinstance(receiver, ast.Call):
            class_ids = self.class_reference(receiver.func, scope)
            return [(self.scopes[class_id]['name'], class_id, 'constructor expression') for class_id in class_ids]
        if isinstance(receiver, ast.Attribute):
            path = self.imported_path(scope, receiver)
            if path:
                for module, module_id in self.module_scopes.items():
                    if path.startswith(module + '.'):
                        candidates = self.instances.get((module_id, path[len(module) + 1:]), [])
                        if candidates:
                            return candidates
        return []

    def receiver_evidence(self, func, scope, targets):
        if not isinstance(func, ast.Attribute) or not targets:
            return []
        rows = []
        seen = set()
        for candidate in self.inferred_instance_candidates(func.value, scope):
            if len(candidate) < 4:
                continue
            class_name, origin_id, explanation, assignment = candidate[:4]
            origin = self.scopes[origin_id]
            classes = ([origin_id] if origin['kind'] == 'class' and origin['name'] == class_name
                       else self.class_reference_text(class_name, origin))
            if not any(target in self.member_targets(class_id, func.attr)
                       for class_id in classes for target in targets):
                continue
            for node, label in ((assignment, 'Instance attribute assignment: ' + explanation),
                                (candidate[4] if len(candidate) > 4 else None,
                                 'Parameter type annotation for the assigned value')):
                if node is None:
                    continue
                file = self.node_files.get(id(node), origin['file'])
                span = self.span(node, file)
                key = (file, span['start'], span['col'], span['end'], span['endCol'], class_name)
                if key not in seen:
                    seen.add(key)
                    rows.append({'scope': origin_id, 'receiverType': class_name, 'label': label, 'span': span})
        return rows

    def binding_timing_note(self, scope, name, call_node):
        """An in-scope import or definition must be reached before it binds."""
        if name not in scope['symbols'] and name not in scope['imports']:
            return ''
        if name in scope['symbols'] and name in scope['imports']:
            return 'multiple local definitions and imports can bind this name'
        if name in scope['symbols']:
            nodes = [self.scope_nodes[target]
                     for target in self.duplicate_definitions.get((scope['id'], name), [])]
        else:
            nodes = self.import_nodes[(scope['id'], name)]
        owner = self.scope_nodes[scope['id']]
        call_position = (call_node.lineno, call_node.col_offset)
        if any(self.parents.get(id(node)) is owner
               and (node.lineno, node.col_offset) < call_position for node in nodes):
            return ''
        return 'local definition or import may not be bound before this call'

    def target_result(self, targets, status, reason, scope=None, receiver=None, call_node=None):
        targets = list(dict.fromkeys(targets))
        if not targets:
            return [], status, reason
        decorated = any(self.scopes[target]['decorators'] for target in targets)
        shadowed = False
        if scope and receiver:
            cursor = scope
            while cursor:
                shadowed |= receiver in self.rebindings.get(cursor['id'], set())
                shadowed |= any(param['name'] == receiver for param in cursor['params'])
                shadowed |= (cursor['id'], receiver) in self.ambiguous_imports
                cursor = self.scopes.get(cursor['parent'])
        if decorated or shadowed or len(targets) != 1:
            status = 'possible'
        timing = self.binding_timing_note(scope, receiver, call_node) if scope and receiver and call_node else ''
        if timing:
            status = 'possible'
            reason += '; ' + timing
        if decorated:
            reason += '; decorators may wrap the target'
        if shadowed:
            reason += '; local binding may shadow the definition'
        return targets, status, reason

    def comprehension_binds(self, node, name, scope):
        """Comprehension targets are local to that expression, not its function."""
        cursor = node
        while cursor and self.ast_scopes.get(id(cursor)) != scope['id']:
            if isinstance(cursor, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                first_iter = cursor.generators[0].iter if cursor.generators else None
                ancestor = node
                in_first_iter = False
                while ancestor and ancestor is not cursor:
                    if ancestor is first_iter:
                        in_first_iter = True
                        break
                    ancestor = self.parents.get(id(ancestor))
                if not in_first_iter and any(name in self.bound_names(generator.target) for generator in cursor.generators):
                    return True
            cursor = self.parents.get(id(cursor))
        return False

    def in_comprehension_body(self, node, scope):
        cursor = node
        while cursor and self.ast_scopes.get(id(cursor)) != scope['id']:
            if isinstance(cursor, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                first_iter = cursor.generators[0].iter if cursor.generators else None
                ancestor = node
                while ancestor and ancestor is not cursor and ancestor is not first_iter:
                    ancestor = self.parents.get(id(ancestor))
                if ancestor is not first_iter:
                    return True
            cursor = self.parents.get(id(cursor))
        return False

    def in_generator_body(self, node, scope):
        cursor = node
        while cursor and self.ast_scopes.get(id(cursor)) != scope['id']:
            if isinstance(cursor, ast.GeneratorExp):
                first_iter = cursor.generators[0].iter if cursor.generators else None
                ancestor = node
                while ancestor and ancestor is not cursor and ancestor is not first_iter:
                    ancestor = self.parents.get(id(ancestor))
                if ancestor is not first_iter:
                    return True
            cursor = self.parents.get(id(cursor))
        return False

    @staticmethod
    def root_name(node):
        while isinstance(node, (ast.Attribute, ast.Call)):
            node = node.value if isinstance(node, ast.Attribute) else node.func
        return node.id if isinstance(node, ast.Name) else None

    def resolve(self, func, scope):
        name = text(func)
        root = self.root_name(func)
        if root and self.comprehension_binds(func, root, scope):
            return [], 'unknown', 'comprehension-local binding; inspect its iterable'
        if scope['kind'] == 'class' and self.in_comprehension_body(func, scope):
            # Comprehension bodies run in an implicit function scope, where the
            # surrounding class suite is not available as a lexical namespace.
            scope = self.scopes[scope['parent']]
        if isinstance(func, ast.Lambda):
            return [self.ast_scopes[id(func)]], 'supported', 'literal lambda'
        if isinstance(func, ast.Name):
            targets, reason = self.lexical(scope, func.id)
            if targets:
                return self.target_result(targets, 'supported', reason, scope, func.id, func)
            if reason.startswith('import '):
                return [], 'external', reason + '; implementation not indexed'
            if reason.startswith('local binding'):
                return [], 'unknown', reason + '; inspect its assignment or parameter'
            builtins = {'str', 'int', 'bool', 'float', 'list', 'dict', 'set', 'tuple', 'len', 'print', 'range', 'enumerate', 'zip', 'sum', 'min', 'max', 'sorted', 'isinstance', 'getattr', 'setattr', 'hasattr', 'open', 'super', 'Exception', 'ValueError', 'TypeError', 'RuntimeError', 'next', 'iter', 'any', 'all', 'repr'}
            if name in builtins:
                return [], 'external', 'builtin candidate; runtime rebinding is possible'
        if isinstance(func, ast.Attribute):
            receiver = func.value
            if isinstance(receiver, ast.Name) and receiver.id in ('self', 'cls'):
                owner = self.enclosing_class(scope)
                if owner:
                    targets = self.member_targets(owner['id'], func.attr)
                    if targets:
                        return self.callable_member_result(targets, 'possible', 'instance or class member; overrides and runtime dispatch may vary')
            if (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name)
                    and receiver.func.id == 'super' and self.lexical(scope, 'super') == ([], '')):
                owner = self.enclosing_class(scope)
                if owner:
                    order = self.class_mro(owner['id'])
                    if order is not None:
                        targets = next((self.duplicate_definitions[(base_id, func.attr)]
                                        for base_id in order[1:]
                                        if (base_id, func.attr) in self.duplicate_definitions), [])
                    else:
                        node = self.class_nodes[owner['id']]
                        origin = self.scopes.get(owner['parent'])
                        targets = [target for base in node.bases for base_id in self.class_reference(base, origin)
                                   for target in self.member_targets(base_id, func.attr)]
                    if targets:
                        return self.callable_member_result(targets, 'possible', 'super member candidate; MRO and runtime dispatch may vary')
            # Class attribute access is an explicit, unbound method access unless
            # a descriptor such as classmethod establishes a bound receiver.
            class_ids = self.class_reference(receiver, scope)
            if class_ids:
                targets = [target for class_id in class_ids for target in self.member_targets(class_id, func.attr)]
                if targets:
                    return self.callable_member_result(targets, 'supported', 'member of source class', scope,
                                                       receiver.id if isinstance(receiver, ast.Name) else None, func)
            inferred = self.inferred_instance_candidates(receiver, scope)
            if inferred:
                members = []
                external = []
                for candidate in inferred:
                    class_name, origin_id, evidence = candidate[:3]
                    origin = self.scopes[origin_id]
                    class_targets = [origin_id] if origin['kind'] == 'class' and origin['name'] == class_name else self.class_reference_text(class_name, origin)
                    members.extend(target for class_id in class_targets for target in self.member_targets(class_id, func.attr))
                    if not class_targets:
                        imported = self.imported_name(origin, class_name)
                        if imported != class_name:
                            external.append(imported + '.' + func.attr)
                if members:
                    return self.callable_member_result(members, 'possible', 'inferred receiver ' + text(receiver) + '; runtime dispatch can vary')
                if external:
                    return [], 'external', 'receiver type candidate outside index: ' + ', '.join(external)
            path = self.imported_path(scope, func)
            if path:
                targets = self.symbols.get(path, [])
                if targets:
                    root = name.split('.')[0]
                    return self.target_result(targets, 'supported', 'import ' + path, scope, root, func)
                return [], 'external', 'import ' + path + '; implementation not indexed'
            if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name) and receiver.value.id in ('self', 'cls'):
                return [], 'unknown', 'instance attribute ' + text(receiver) + ' has no source-backed type candidate; inspect its initializer'
            if isinstance(receiver, ast.Call):
                return [], 'unknown', 'call result has no source-backed class candidate; inspect the constructor or factory'
        return [], 'unknown', 'dynamic receiver, callback, alias, or target not resolved by this analyzer'

    def binding(self, call, target, scope):
        """Map arguments from Python call syntax without inventing a receiver."""
        constructor = target['kind'] == 'class'
        if constructor:
            initializer = target['symbols'].get('__init__')
            if initializer:
                target = self.scopes[initializer]
        params = list(target['params'])
        rows = []
        receiver = None
        receiver_certainty = 'possible receiver'
        if constructor and params:
            receiver = 'new instance (implicit)'
        elif target['kind'] == 'method' and isinstance(call.func, ast.Attribute) and params:
            owner = self.scopes.get(target['parent'])
            base = call.func.value
            decorators = {decorator.split('(')[0].split('.')[-1] for decorator in target['decorators']}
            if 'staticmethod' not in decorators:
                if 'classmethod' in decorators:
                    if isinstance(base, ast.Name) and base.id == 'cls':
                        receiver = 'cls (implicit)'
                    elif self.class_reference(base, scope):
                        receiver = text(base) + ' (implicit class)'
                    elif isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == 'super':
                        receiver = 'class selected by super() (implicit)'
                    else:
                        receiver = 'type(' + text(base) + ') (implicit)'
                elif isinstance(base, ast.Name) and base.id in ('self', 'cls'):
                    receiver = text(base)
                elif isinstance(base, ast.Call) and self.class_reference(base.func, scope):
                    receiver = text(base)
                elif isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == 'super':
                    receiver = text(base)
                elif not self.class_reference(base, scope) and self.inferred_instance_candidates(base, scope):
                    receiver = text(base)
            if receiver is not None and owner and params[0]['name'] not in ('self', 'cls'):
                # A source-defined method may have any first parameter name.
                receiver_certainty = 'possible receiver'
        if receiver is not None and params:
            rows.append({'argument': receiver, 'parameter': params[0]['name'], 'certainty': receiver_certainty})
            params = params[1:]

        positional = [param for param in params if param['kind'] in ('positional', 'posonly')]
        varargs = next((param for param in params if param['kind'] == 'varargs'), None)
        kwargs = next((param for param in params if param['kind'] == 'kwargs'), None)
        consumed = set()
        uncertain = False
        position = 0
        for arg in call.args:
            if isinstance(arg, ast.Starred):
                uncertain = True
                rows.append({'argument': text(arg), 'parameter': '*arguments (binding unresolved)', 'certainty': 'possible'})
                continue
            if uncertain:
                dest, certainty = '*arguments (binding unresolved)', 'possible'
            elif position < len(positional):
                dest, certainty = positional[position]['name'], 'syntax'
                consumed.add(dest)
            elif varargs:
                dest, certainty = varargs['name'], 'syntax'
            else:
                dest, certainty = '*arguments (no declared positional parameter)', 'unresolved'
            rows.append({'argument': text(arg), 'parameter': dest, 'certainty': certainty})
            position += 1
        for keyword in call.keywords:
            if keyword.arg is None:
                uncertain = True
                rows.append({'argument': '**' + text(keyword.value), 'parameter': '**keywords (binding unresolved)', 'certainty': 'possible'})
                continue
            param = next((candidate for candidate in params if candidate['name'] == keyword.arg), None)
            if param and param['kind'] not in ('posonly', 'varargs'):
                dest, certainty = param['name'], 'syntax'
                consumed.add(dest)
            elif kwargs:
                dest, certainty = kwargs['name'] + '[' + keyword.arg + ']', 'syntax'
            else:
                dest, certainty = keyword.arg + ' (no declared keyword parameter)', 'unresolved'
            rows.append({'argument': text(keyword.value), 'parameter': dest, 'certainty': certainty})
        for param in params:
            if param['name'] not in consumed and param.get('default') is not None:
                rows.append({'argument': param['default'], 'parameter': param['name'],
                             'certainty': 'default possible' if uncertain else 'default'})
        if constructor:
            mode = 'construction'
        elif target['kind'] == 'method':
            mode = 'implicit' if receiver is not None else 'explicit'
        else:
            mode = 'not-applicable'
        receiver_binding = {
            'mode': mode,
            'expression': receiver,
            'certainty': 'possible' if mode in ('construction', 'implicit')
            else 'syntax' if mode == 'explicit' else 'not-applicable',
        }
        return rows, receiver_binding

    def return_destination(self, call):
        node = self.parents.get(id(call))
        if isinstance(node, ast.Await):
            node = self.parents.get(id(node))
        if isinstance(node, ast.Assign):
            return ', '.join(text(t) for t in node.targets)
        if isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            return text(node.target)
        if isinstance(node, ast.Return):
            return 'caller return value'
        if isinstance(node, ast.Expr):
            return 'value discarded; caller continues'
        return 'enclosing expression: ' + short(text(node), 90) if node else 'enclosing scope'

    def expression_guards(self, node, scope):
        guards = []
        child = node
        parent = self.parents.get(id(child))
        while parent and self.ast_scopes.get(id(parent)) != scope['id']:
            if isinstance(parent, ast.IfExp):
                if child is parent.body or child is parent.orelse:
                    guards.append({'kind': 'if-expression', 'condition': text(parent.test),
                                   'branch': 'true' if child is parent.body else 'false',
                                   'span': self.span(parent.test, scope['file'])})
            elif isinstance(parent, ast.BoolOp) and child in parent.values:
                index = parent.values.index(child)
                if index:
                    condition = ' and '.join(text(value) for value in parent.values[:index]) if isinstance(parent.op, ast.And) else ' or '.join(text(value) for value in parent.values[:index])
                    guards.append({'kind': 'short-circuit', 'condition': condition,
                                   'requirement': 'all prior operands truthy' if isinstance(parent.op, ast.And) else 'all prior operands falsy',
                                   'span': self.span(parent, scope['file'])})
            elif isinstance(parent, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                first_iter = parent.generators[0].iter if parent.generators else None
                ancestor = node
                in_first_iter = False
                while ancestor and ancestor is not parent:
                    if ancestor is first_iter:
                        in_first_iter = True
                        break
                    ancestor = self.parents.get(id(ancestor))
                if not in_first_iter:
                    guards.append({'kind': 'comprehension', 'condition': text(parent),
                                   'requirement': 'iteration and applicable filters reach this expression',
                                   'span': self.span(parent, scope['file'])})
            child = parent
            parent = self.parents.get(id(child))
        return guards

    def execution_context(self, node, scope):
        if any(isinstance(ancestor, ast.TypeAlias) for ancestor in self.ancestors(node, scope)):
            return {'kind': 'type alias value', 'deferred': True}
        if scope['async']:
            return {'kind': 'coroutine body', 'deferred': True}
        if scope['generator']:
            return {'kind': 'generator body', 'deferred': True}
        if self.in_generator_body(node, scope):
            return {'kind': 'generator expression', 'deferred': True}
        if scope['kind'] == 'class':
            return {'kind': 'class definition', 'deferred': False}
        if scope['kind'] == 'module':
            return {'kind': 'module execution', 'deferred': False}
        return {'kind': 'function body', 'deferred': False}

    @staticmethod
    def reason_code(status, reason):
        if 'descriptor getter is accessed before this call' in reason:
            return 'descriptor_result'
        if 'may not be bound before this call' in reason or 'multiple local definitions and imports' in reason:
            return 'binding_not_established'
        if 'comprehension-local binding' in reason:
            return 'comprehension_binding'
        if 'local binding shadows' in reason:
            return 'local_binding'
        if 'instance attribute' in reason and 'no source-backed' in reason:
            return 'untyped_instance_attribute'
        if 'call result has no' in reason:
            return 'untyped_call_result'
        if 'inferred receiver' in reason:
            return 'inferred_receiver'
        if 'instance or class member' in reason or 'super member' in reason:
            return 'dynamic_method_dispatch'
        if status == 'external':
            return 'external_source'
        if status == 'unknown':
            return 'unresolved_target'
        return 'source_definition'

    def expression_info(self, roots, scope):
        calls, decisions, reads, writes = [], [], [], []
        file = scope['file']
        def visit(node):
            if node is None:
                return
            if isinstance(node, ast.Lambda):
                decisions.append({'id': self.ident(node, file), 'label': 'Lambda definition; body is deferred', 'span': self.span(node, file), 'target': self.ast_scopes[id(node)]})
                return
            if isinstance(node, ast.BoolOp):
                decisions.append({'id': self.ident(node, file), 'label': f'Short-circuit {type(node.op).__name__.lower()}: ' + short(text(node)), 'span': self.span(node, file), 'alternatives': ['evaluate next operand', 'stop at first falsy operand' if isinstance(node.op, ast.And) else 'stop at first truthy operand']})
            if isinstance(node, ast.IfExp):
                decisions.append({'id': self.ident(node, file), 'label': 'Conditional value: ' + short(text(node.test)), 'span': self.span(node, file), 'alternatives': ['true → ' + short(text(node.body)), 'false → ' + short(text(node.orelse))]})
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                decisions.append({'id': self.ident(node, file), 'label': ('Deferred generator' if isinstance(node, ast.GeneratorExp) else 'Comprehension') + ': ' + short(text(node)), 'span': self.span(node, file), 'alternatives': [f'{"async " if g.is_async else ""}for {text(g.target)} in {text(g.iter)}' + ''.join(' · filter ' + text(c) for c in g.ifs) for g in node.generators] + ['exhausted → result; filters can skip elements']})
            if isinstance(node, (ast.Yield, ast.YieldFrom, ast.Await)):
                decisions.append({'id': self.ident(node, file), 'label': type(node).__name__ + ': suspension / resumption point', 'span': self.span(node, file)})
            if isinstance(node, ast.Compare) and len(node.ops) > 1:
                decisions.append({'id': self.ident(node, file), 'label': 'Chained comparison: stop on first false comparison', 'span': self.span(node, file)})
            if isinstance(node, ast.Name):
                (writes if isinstance(node.ctx, (ast.Store, ast.Del)) else reads).append(node.id)
            elif isinstance(node, ast.Attribute):
                (writes if isinstance(node.ctx, (ast.Store, ast.Del)) else reads).append(text(node))
            for child in ast.iter_child_nodes(node):
                visit(child)
            if isinstance(node, ast.Call):
                targets, status, reason = self.resolve(node.func, scope)
                guards = self.expression_guards(node, scope)
                bindings = {}
                receiver_bindings = {}
                for target_id in targets:
                    bindings[target_id], receiver_bindings[target_id] = self.binding(
                        node, self.scopes[target_id], scope)
                call = {'id': self.ident(node, file), 'scope': scope['id'], 'name': text(node.func), 'expression': short(text(node), 180),
                        'span': self.span(node, file), 'targets': targets, 'status': status, 'reason': reason,
                        'reasonCode': self.reason_code(status, reason),
                        'arguments': [text(arg) for arg in node.args] + [(kw.arg + '=' if kw.arg else '**') + text(kw.value) for kw in node.keywords],
                        'bindings': bindings, 'receiverBindings': receiver_bindings,
                        'candidateEvidence': self.receiver_evidence(node.func, scope, targets),
                        'destination': self.return_destination(node),
                        'conditional': bool(guards),
                        'awaited': isinstance(self.parents.get(id(node)), ast.Await),
                        'guards': guards, 'executionContext': self.execution_context(node, scope), 'unreachable': False}
                call['execution'] = 'ordinary call'
                if call['awaited']:
                    call['execution'] = 'await: suspension and resumption; exceptions can propagate'
                elif targets and any(self.scopes[t]['generator'] for t in targets):
                    call['execution'] = 'deferred generator: body runs when the iterator is advanced'
                elif targets and any(self.scopes[t]['async'] for t in targets):
                    call['execution'] = 'deferred coroutine: body runs only when awaited or scheduled'
                function_path = self.imported_name(scope, text(node.func))
                if function_path in ('asyncio.create_task', 'asyncio.ensure_future', 'asyncio.gather'):
                    call['execution'] = 'background scheduling boundary: work may interleave; delivery/completion is not established here'
                if call['executionContext']['kind'] == 'type alias value':
                    call['execution'] = 'deferred type alias: value is evaluated when requested'
                calls.append(call)
                self.calls.append(call)
        for root in roots:
            visit(root)
        return calls, decisions, sorted(set(reads)), sorted(set(writes))

    def ancestors(self, node, scope):
        cursor = self.parents.get(id(node))
        while cursor and self.ast_scopes.get(id(cursor)) != scope['id']:
            yield cursor
            cursor = self.parents.get(id(cursor))

    def block(self, statements, scope):
        result = []
        terminal = False
        for node in statements:
            item = self.statement(node, scope)
            if terminal:
                item['unreachable'] = True
                for nested in self.walk_flow([item]):
                    nested['unreachable'] = True
                    for call in nested['calls']:
                        call['unreachable'] = True
            result.append(item)
            if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                terminal = True
        return result

    def statement(self, node, scope):
        file = scope['file']
        kind = type(node).__name__
        self.construct_counts[kind] += 1
        item = {'id': self.ident(node, file), 'kind': kind, 'span': self.span(node, file), 'label': short(text(node).split('\n')[0]), 'branches': [], 'effects': [], 'definition': None, 'terminal': kind in ('Return', 'Raise', 'Break', 'Continue')}
        roots = []
        def branch(label, body, note=''):
            item['branches'].append({'label': label, 'note': note, 'nodes': self.block(body, scope)})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            item['definition'] = self.ast_scopes[id(node)]
            item['label'] = 'Define ' + ('class ' if isinstance(node, ast.ClassDef) else 'function ') + node.name
            item['effects'] = ['definition-time decorators / defaults; function body runs only when called'] if not isinstance(node, ast.ClassDef) else ['class body executes at definition time']
            roots = list(node.decorator_list)
            if isinstance(node, ast.ClassDef):
                roots += list(node.bases) + [kw.value for kw in node.keywords]
            else:
                roots += list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]
                roots += [a.annotation for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if a.annotation]
                if node.returns:
                    roots.append(node.returns)
        elif isinstance(node, ast.If):
            item['label'] = 'If ' + short(text(node.test))
            roots = [node.test]
            branch('True', node.body)
            branch('False', node.orelse, 'continue' if not node.orelse else '')
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            if isinstance(node, ast.While):
                roots = [node.test]
                item['label'] = 'While ' + short(text(node.test))
            else:
                roots = [node.target, node.iter]
                item['label'] = ('Async for ' if isinstance(node, ast.AsyncFor) else 'For ') + text(node.target) + ' in ' + short(text(node.iter))
            branch('Loop body · repeat', node.body, 'continue returns to loop; break skips loop else')
            branch('Normal exhaustion / condition false', node.orelse, 'continue after loop' if not node.orelse else 'else runs only without break')
            item['effects'] = ['body represented once; exhaustion or a false condition bypasses it']
        elif isinstance(node, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            item['label'] = 'Try' + (' · exception groups' if kind == 'TryStar' else '')
            branch('Protected body', node.body)
            for handler in node.handlers:
                roots += [handler.type] if handler.type else []
                branch('Except ' + (text(handler.type) if handler.type else 'any exception') + (f' as {handler.name}' if handler.name else ''), handler.body, 'exception handler; matching may be unresolved')
            if node.orelse:
                branch('Else · body completed without exception', node.orelse)
            if node.finalbody:
                branch('Finally · on normal and exceptional exits', node.finalbody, 'cleanup can override return or exception')
            item['effects'] = ['unmatched exceptions propagate to caller']
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            roots = [x.context_expr for x in node.items] + [x.optional_vars for x in node.items if x.optional_vars]
            item['label'] = ('Async with ' if isinstance(node, ast.AsyncWith) else 'With ') + ', '.join(text(x.context_expr) for x in node.items)
            branch('Inside context', node.body)
            item['effects'] = ['implicit enter / exit calls; cleanup runs on exit; suppression depends on context manager']
        elif isinstance(node, ast.Match):
            roots = [node.subject]
            item['label'] = 'Match ' + short(text(node.subject))
            for case in node.cases:
                roots += [case.pattern] + ([case.guard] if case.guard else [])
                branch('Case ' + text(case.pattern) + (' if ' + text(case.guard) if case.guard else ''), case.body, 'first matching pattern with a true guard')
            def irrefutable(pattern):
                return (isinstance(pattern, ast.MatchAs) and pattern.pattern is None) or (isinstance(pattern, ast.MatchOr) and any(irrefutable(p) for p in pattern.patterns))
            if not any(case.guard is None and irrefutable(case.pattern) for case in node.cases):
                branch('No case matched', [], 'continue after the match')
        elif isinstance(node, ast.Assert):
            roots = [node.test] + ([node.msg] if node.msg else [])
            item['label'] = 'Assert ' + short(text(node.test))
            branch('True', [], 'continue')
            branch('False', [], 'raise AssertionError; assertions may be removed by Python optimization')
        else:
            roots = list(ast.iter_child_nodes(node))
            if isinstance(node, ast.Return):
                item['label'] = 'Return ' + (short(text(node.value)) if node.value else 'None')
            elif isinstance(node, ast.Raise):
                item['label'] = 'Raise ' + (short(text(node.exc)) if node.exc else 'current exception')
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                item['effects'] = ['import may execute module initialization; target is not imported by Threadline']
            elif isinstance(node, ast.Delete):
                item['effects'] = ['deletion / mutation']
            elif isinstance(node, ast.AugAssign):
                item['effects'] = ['read, modify, write; in-place protocol may run']
            known = (ast.Return, ast.Raise, ast.Break, ast.Continue, ast.Pass, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Delete, ast.Global, ast.Nonlocal)
            if not isinstance(node, known):
                item['unsupported'] = True
                item['effects'].append('syntax retained; behavioral model unsupported')
        item['expression'] = None
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            item['label'] = 'Set ' + short(', '.join(text(t) for t in targets), 90)
            item['expression'] = short(text(node.value), 160) if node.value else 'annotation only'
        elif isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                item['label'] = 'Source note'
                item['expression'] = short(node.value.value, 140)
                item['note'] = True
            else:
                value = node.value.value if isinstance(node.value, ast.Await) else node.value
                if isinstance(value, ast.Call):
                    item['label'] = ('Await ' if isinstance(node.value, ast.Await) else 'Call ') + text(value.func)
                    item['expression'] = short(', '.join(text(a) for a in value.args) + (', ' if value.args and value.keywords else '') + ', '.join((k.arg + '=' if k.arg else '**') + text(k.value) for k in value.keywords), 160)
        item['calls'], item['decisions'], item['reads'], item['writes'] = self.expression_info(roots, scope)
        for call in item['calls']:
            name = call['name'].lower()
            member = name.rsplit('.', 1)[-1]
            effect_members = {'commit', 'flush', 'execute', 'add', 'delete', 'write', 'send', 'publish',
                              'put', 'start', 'create_task', 'print', 'open'}
            if member in effect_members or name.startswith(('logger.', 'logging.', 'subprocess.')):
                item['effects'].append('possible effect: ' + call['name'])
        return item

    def run(self):
        self.discover()
        # Flat application directories (for example server/main.py importing routers)
        # receive conservative aliases. Collisions remain multiple possible targets.
        for key, targets in list(self.symbols.items()):
            for module, aliases in self.module_aliases.items():
                if key == module or key.startswith(module + '.'):
                    suffix = key[len(module):]
                    for alias in aliases: self.symbols.setdefault(alias + suffix, []).extend(t for t in targets if t not in self.symbols.get(alias + suffix, []))
        for module, aliases in self.module_aliases.items():
            for alias in aliases:
                if module in self.module_scopes: self.module_scopes.setdefault(alias, self.module_scopes[module])
        for file, info in self.files.items():
            self.collect_imports(info['tree'], self.scopes[self.ast_scopes[id(info['tree'])]])
        for file, info in self.files.items():
            self.collect_bindings(info['tree'], self.scopes[self.ast_scopes[id(info['tree'])]])
        for file, info in self.files.items():
            for node in ast.walk(info['tree']):
                if id(node) not in self.ast_scopes:
                    continue
                scope = self.scopes[self.ast_scopes[id(node)]]
                if isinstance(node, ast.Lambda):
                    synthetic = ast.Expr(value=node.body)
                    ast.copy_location(synthetic, node.body)
                    scope['flow'] = [self.statement(synthetic, scope)]
                else:
                    scope['flow'] = self.block(node.body, scope)
        all_calls = {self.ident(n, f) for f, info in self.files.items() for n in ast.walk(info['tree']) if isinstance(n, ast.Call)}
        represented_calls = {c['id'] for c in self.calls}
        # Any syntax not covered by modeled header/body expressions remains explicit.
        unmodeled_calls = []
        for file, info in self.files.items():
            for node in ast.walk(info['tree']):
                if isinstance(node, ast.Call) and self.ident(node, file) not in represented_calls:
                    unmodeled_calls.append({'expression': short(text(node)), 'span': self.span(node, file), 'reason': 'call in syntax outside modeled execution regions'})
        kinds = Counter(s['kind'] for s in self.scopes.values())
        statuses = Counter(c['status'] for c in {c['id']: c for c in self.calls}.values())
        statement_total = sum(sum(isinstance(n, ast.stmt) for n in ast.walk(info['tree'])) for info in self.files.values())
        modeled_statements = sum(self.construct_counts.values()) - kinds['lambda']
        calls_by_scope = defaultdict(list)
        callers_by_target = defaultdict(dict)
        for call in self.calls:
            calls_by_scope[call['scope']].append(call)
            for target in call['targets'] if call['status'] == 'supported' and not call['unreachable'] else []:
                callers_by_target[target][call['scope']] = None
        for scope in self.scopes.values():
            if time.monotonic() - self.started > MAX_ANALYSIS_SECONDS:
                raise AnalysisLimitError('Analysis time budget exceeded; narrow --source-root')
            own_calls = calls_by_scope[scope['id']]
            scope['stats'] = {'calls': len(own_calls), 'unresolved': sum(c['status'] == 'unknown' for c in own_calls), 'branches': sum(len(n['branches']) + len(n['decisions']) for n in self.walk_flow(scope['flow']))}
            scope['callers'] = list(callers_by_target[scope['id']])
            scope.pop('symbols')
            scope.pop('imports')
        router_prefixes = {}
        for file, info in self.files.items():
            for node in info['tree'].body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
                    continue
                if text(node.value.func).split('.')[-1] not in ('APIRouter', 'Blueprint'):
                    continue
                prefix = next((keyword.value.value for keyword in node.value.keywords
                               if keyword.arg in ('prefix', 'url_prefix')
                               and isinstance(keyword.value, ast.Constant)
                               and isinstance(keyword.value.value, str)), '')
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        router_prefixes[file + ':' + target.id] = prefix
        return {'analysisOptions': {'sourceRoots': [str(path.relative_to(self.root)) for path in self.source_roots], 'exclude': sorted(self.user_excluded)}, 'configuration': self.configuration, 'configurationManifest': self.configuration_manifest, 'project': self.root.name, 'root': str(self.root), 'files': {f: {'source': i['source'], 'hash': i['hash'], 'lines': i['lines']} for f, i in self.files.items()},
                'scopes': self.scopes, 'errors': self.errors, 'excluded': self.excluded,
                'discoveryManifest': self.discovery_manifest, 'routerPrefixes': router_prefixes,
                'coverage': {'files': len(self.files), 'discovered': len(self.discovery_manifest), 'kinds': dict(kinds), 'definitions': sum(v for k, v in kinds.items() if k not in ('module', 'class')), 'statements': statement_total, 'representedStatements': modeled_statements, 'calls': len(all_calls), 'representedCalls': len(represented_calls), 'statuses': dict(statuses), 'unmodeledCalls': unmodeled_calls, 'constructs': dict(self.construct_counts)},
                'limits': ['Source structure is exhaustive within parsed files; runtime paths and effects are not proven.', 'Dynamic dispatch, aliases, descriptors, decorators, callbacks, and implicit protocol calls may remain unresolved.', 'Data highlights show lexical definitions and uses; alias propagation and path feasibility are not proven.', 'Annotations are shown as source; evaluation depends on Python version and future imports.']}

    @staticmethod
    def walk_flow(nodes):
        for node in nodes:
            yield node
            for branch in node['branches']:
                yield from Analyzer.walk_flow(branch['nodes'])


def analyze(root, *, source_roots=None, exclude=None):
    from .workflows import build_workflows
    model = Analyzer(root, source_roots=source_roots, exclude=exclude).run()
    model["workflows"] = build_workflows(model)
    from .workflows import suggested_entrypoints
    model["entrypoints"] = suggested_entrypoints(model)
    return model
