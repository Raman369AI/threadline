"""Read Python syntax and build an evidence-linked review model. Never imports targets."""
from __future__ import annotations

import ast
import hashlib
import os
import tokenize
from collections import Counter
from pathlib import Path

EXCLUDED = {'.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules', 'dist', 'build', '.tox', '.mypy_cache', '.pytest_cache'}
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
        self.scopes = {}
        self.ast_scopes = {}
        self.node_files = {}
        self.parents = {}
        self.symbols = {}
        self.module_scopes = {}
        self.module_aliases = {}
        self.instances = {}
        self.rebindings = {}
        self.excluded = []
        self.errors = []
        self.calls = []
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
        return f"{file}:{getattr(node, 'lineno', 1)}:{getattr(node, 'col_offset', 0)}:{type(node).__name__}{suffix}"

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
                    if path.is_symlink():
                        self.excluded.append({'path': file, 'reason': 'symlink'}); continue
                    try:
                        raw = path.read_bytes()
                        with tokenize.open(path) as stream: source = stream.read()
                        tree = ast.parse(source, filename=file, type_comments=True)
                    except (SyntaxError, UnicodeError, OSError) as exc:
                        self.errors.append({'file': file, 'message': str(exc)}); continue
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
        scope = {'id': scope_id, 'file': file, 'name': name, 'qualified': qualified, 'module': module, 'kind': kind,
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
        self.ast_scopes[id(node)] = scope_id
        if parent:
            parent['symbols'][name] = scope_id
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
            if name in cursor['symbols']:
                return [cursor['symbols'][name]], 'definition in lexical scope'
            if name in cursor['imports']:
                imported = cursor['imports'][name]
                return self.symbols.get(imported, []), f'import {imported}'
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
                        scope['imports'][alias.asname or alias.name] = f'{prefix}.{alias.name}'
                elif isinstance(child, ast.Import):
                    for alias in child.names:
                        scope['imports'][alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
                self.collect_imports(child, scope)

    def imported_name(self, scope, name):
        cursor = scope
        while cursor:
            if name in cursor['imports']:
                return cursor['imports'][name]
            cursor = self.scopes.get(cursor['parent'])
        return name

    def instance_type(self, scope, name):
        cursor = scope
        while cursor:
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
            cursor = self.scopes.get(cursor['parent'])
        return None

    def collect_bindings(self, node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                if isinstance(arg.annotation, (ast.Name, ast.Attribute)):
                    self.instances[(scope['id'], arg.arg)] = (text(arg.annotation), scope['id'], 'parameter annotation')
        def visit(child):
            if isinstance(child, SCOPE_TYPES):
                self.collect_bindings(child, self.scopes[self.ast_scopes[id(child)]])
                return
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    name = text(target)
                    self.rebindings.setdefault(scope['id'], set()).add(name)
                    if isinstance(child.value, ast.Call):
                        self.instances[(scope['id'], name)] = (text(child.value.func), scope['id'], 'constructor-shaped assignment')
                    elif isinstance(child, ast.AnnAssign) and isinstance(child.annotation, (ast.Name, ast.Attribute)):
                        self.instances[(scope['id'], name)] = (text(child.annotation), scope['id'], 'annotation')
            for sub in ast.iter_child_nodes(child):
                visit(sub)
        for child in ast.iter_child_nodes(node):
            visit(child)

    def resolve(self, func, scope):
        name = text(func)
        targets, reason = [], ''
        if isinstance(func, ast.Lambda):
            targets, reason = [self.ast_scopes[id(func)]], 'literal lambda'
        elif isinstance(func, ast.Name):
            targets, reason = self.lexical(scope, func.id)
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in ('self', 'cls'):
                parent = self.scopes.get(scope['parent'])
                while parent and parent['kind'] != 'class':
                    parent = self.scopes.get(parent['parent'])
                if parent and func.attr in parent['symbols']:
                    return [parent['symbols'][func.attr]], 'possible', 'class member; overrides or rebinding can change dispatch'
            base_name = text(func.value)
            inferred = self.instance_type(scope, base_name)
            if inferred:
                class_name, origin_id, evidence = inferred
                origin = self.scopes[origin_id]
                class_targets, _ = self.lexical(origin, class_name)
                members = [self.scopes[t]['symbols'][func.attr] for t in class_targets if self.scopes[t]['kind'] == 'class' and func.attr in self.scopes[t]['symbols']]
                if members:
                    return members, 'possible', f'{evidence}: {base_name} may be {class_name}; runtime dispatch can vary'
                imported_class = self.imported_name(origin, class_name)
                if imported_class != class_name and not class_targets:
                    return [], 'external', f'{evidence}: candidate {imported_class}.{func.attr}; implementation outside index'
            cursor = scope
            while cursor:
                if base_name in cursor['imports']:
                    path = cursor['imports'][base_name] + '.' + func.attr
                    targets, reason = self.symbols.get(path, []), f'import {path}'
                    break
                cursor = self.scopes.get(cursor['parent'])
        if targets:
            decorated = any(self.scopes[t]['decorators'] for t in targets)
            shadowed = any(p['name'] == name for p in scope['params']) or name in self.rebindings.get(scope['id'], set())
            return targets, 'possible' if decorated or shadowed or len(targets) != 1 else 'supported', reason + ('; decorators may wrap the target' if decorated else '') + ('; local binding may shadow the definition' if shadowed else '')
        if reason.startswith('import '):
            return [], 'external', reason + '; implementation not indexed'
        builtins = {'str', 'int', 'bool', 'float', 'list', 'dict', 'set', 'tuple', 'len', 'print', 'range', 'enumerate', 'zip', 'sum', 'min', 'max', 'sorted', 'isinstance', 'getattr', 'setattr', 'hasattr', 'open', 'super', 'Exception', 'ValueError', 'TypeError', 'RuntimeError', 'next', 'iter', 'any', 'all', 'repr'}
        if isinstance(func, ast.Name) and name in builtins:
            return [], 'external', 'builtin candidate; runtime rebinding is possible'
        return [], 'unknown', 'dynamic receiver, callback, alias, or target not resolved by this analyzer'

    def binding(self, call, target):
        if target['kind'] == 'class':
            initializer = target['symbols'].get('__init__')
            if initializer:
                target = self.scopes[initializer]
        params = target['params']
        rows = []
        if (isinstance(call.func, ast.Attribute) or target['kind'] == 'method') and params and params[0]['name'] in ('self', 'cls'):
            rows.append({'argument': text(call.func.value) if isinstance(call.func, ast.Attribute) else 'new instance (implicit)', 'parameter': params[0]['name'], 'certainty': 'possible receiver'})
            params = params[1:]
        positional = [p for p in params if p['kind'] in ('positional', 'posonly')]
        consumed = set()
        uncertain = False
        for i, arg in enumerate(call.args):
            if isinstance(arg, ast.Starred):
                uncertain = True
            dest = positional[i]['name'] if i < len(positional) and not uncertain else '*arguments (binding unresolved)'
            consumed.add(dest)
            rows.append({'argument': text(arg), 'parameter': dest, 'certainty': 'possible' if uncertain else 'syntax'})
        for kw in call.keywords:
            dest = kw.arg or '**keywords (binding unresolved)'
            consumed.add(dest)
            rows.append({'argument': text(kw.value), 'parameter': dest, 'certainty': 'syntax' if kw.arg else 'possible'})
        for param in params:
            if param['name'] not in consumed and param.get('default') is not None:
                rows.append({'argument': param['default'], 'parameter': param['name'], 'certainty': 'default unless unpacking supplies it'})
        return rows

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
                call = {'id': self.ident(node, file), 'scope': scope['id'], 'name': text(node.func), 'expression': short(text(node), 180),
                        'span': self.span(node, file), 'targets': targets, 'status': status, 'reason': reason,
                        'arguments': [text(arg) for arg in node.args] + [(kw.arg + '=' if kw.arg else '**') + text(kw.value) for kw in node.keywords],
                        'bindings': {t: self.binding(node, self.scopes[t]) for t in targets}, 'destination': self.return_destination(node),
                        'conditional': any(isinstance(a, (ast.BoolOp, ast.IfExp, ast.comprehension, ast.GeneratorExp)) for a in self.ancestors(node, scope)),
                        'awaited': isinstance(self.parents.get(id(node)), ast.Await)}
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
            if any(k in name for k in ('commit', 'flush', 'execute', '.add', '.delete', '.write', '.send', 'publish', '.put', '.start', 'create_task', 'subprocess', 'logger.', 'logging.', 'print', 'open')):
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
        for scope in self.scopes.values():
            own_calls = [c for c in self.calls if c['scope'] == scope['id']]
            scope['stats'] = {'calls': len(own_calls), 'unresolved': sum(c['status'] == 'unknown' for c in own_calls), 'branches': sum(len(n['branches']) + len(n['decisions']) for n in self.walk_flow(scope['flow']))}
            scope['callers'] = list(dict.fromkeys(c['scope'] for c in self.calls if scope['id'] in c['targets']))
            scope.pop('symbols')
            scope.pop('imports')
        return {'project': self.root.name, 'root': str(self.root), 'files': {f: {'source': i['source'], 'hash': i['hash'], 'lines': i['lines']} for f, i in self.files.items()},
                'scopes': self.scopes, 'errors': self.errors, 'excluded': self.excluded,
                'coverage': {'files': len(self.files), 'discovered': len(self.files) + len(self.errors), 'kinds': dict(kinds), 'definitions': sum(v for k, v in kinds.items() if k not in ('module', 'class')), 'statements': statement_total, 'representedStatements': modeled_statements, 'calls': len(all_calls), 'representedCalls': len(represented_calls), 'statuses': dict(statuses), 'unmodeledCalls': unmodeled_calls, 'constructs': dict(self.construct_counts)},
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
    from .workflows import generic_workflow, suggested_entrypoints
    model["entrypoints"] = suggested_entrypoints(model)
    model["generatedWorkflows"] = {scope["id"]: generic_workflow(model, scope["id"]) for scope in model["entrypoints"][:1]}
    return model
