"""Bounded, source-only data flow for one retained Python function.

The graph describes syntactic origins and uses. It deliberately does not infer
runtime values, database rows, branch execution, or effects of unknown calls.
"""

from __future__ import annotations

import ast
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .templates import _context_dicts


SCHEMA_VERSION = '1.0'
MAX_SOURCE_NODES = 100_000
MAX_SECONDS = 3.0
MAX_NODES = 800
MAX_FIELDS_PER_MODEL = 200
MAX_TOTAL_FIELDS = 800
MAX_TEMPLATE_LINKS = 20
MAX_TEMPLATE_USES = 200
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_SCOPES = _FUNCTIONS + (ast.ClassDef,)
_MUTATORS = {'append', 'extend', 'insert', 'add', 'update', 'setdefault', 'remove', 'discard', 'pop', 'popitem', 'clear', 'sort', 'reverse'}
_CONTAINER_BUILTINS = {'list': 'list', 'sorted': 'list', 'dict': 'dict', 'set': 'set'}


def _text(node: ast.AST | None) -> str:
    if node is None:
        return 'None'
    try:
        return ast.unparse(node)
    except (ValueError, RecursionError):
        return type(node).__name__


def _short(value: str, limit: int = 180) -> str:
    value = ' '.join(value.split())
    return value if len(value) <= limit else value[:limit - 1] + '…'


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _references_context_field(expression: str, context: str, field: str) -> bool:
    """Recognize one literal field use without matching a sibling or nested root."""
    if not context.isidentifier():
        return False
    root = rf'(?<![\w.]){re.escape(context)}'
    if field.isidentifier() and re.search(root + rf'\s*\.\s*{re.escape(field)}(?!\w)', expression):
        return True
    return any(re.search(root + rf'\s*\[\s*{quote}{re.escape(field)}{quote}\s*\]', expression)
               for quote in ("'", '"'))


@dataclass
class _Value:
    sources: list[str] = field(default_factory=list)
    object_id: str | None = None
    shape: str | None = None


@dataclass
class _State:
    names: dict[str, str] = field(default_factory=dict)
    fields: dict[tuple[str, str], str] = field(default_factory=dict)
    objects: dict[str, str] = field(default_factory=dict)
    dict_keys: dict[str, set[str] | None] = field(default_factory=dict)
    live: bool = True

    def fork(self) -> _State:
        return _State(self.names.copy(), self.fields.copy(), self.objects.copy(),
                      {key: value.copy() if value is not None else None
                       for key, value in self.dict_keys.items()}, self.live)


class _LimitReached(Exception):
    pass


class _Builder:
    def __init__(self, model: dict[str, Any], scope_id: str, max_events: int,
                 max_edges: int, max_models: int, model_offset: int):
        self.model = model
        try:
            self.scope = model['scopes'][scope_id]
        except KeyError as exc:
            raise ValueError(f'unknown scope: {scope_id}') from exc
        if self.scope['kind'] in ('module', 'class'):
            raise ValueError('data flow requires a function or method scope')
        self.file = self.scope['file']
        self.source = model['files'][self.file]['source']
        self.hash = model['files'][self.file]['hash']
        self.max_events = max_events
        self.max_edges = max_edges
        self.max_models = max_models
        self.model_offset = model_offset
        self.model_total = 0
        self.next_model_offset: int | None = None
        self.started = time.monotonic()
        self.nodes: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.models: list[dict[str, Any]] = []
        self.templates: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = []
        self._node_by_id: dict[str, dict[str, Any]] = {}
        self._event_count = 0
        self._edge_count = 0
        self._versions: dict[str, int] = {}
        self._object_count = 0
        self._field_count = 0
        self._external: dict[str, str] = {}
        self._state = _State()
        self._guards: list[dict[str, Any]] = []
        self._truncated = False
        self._omitted = 0
        self._trees: dict[str, ast.AST] = {}
        self._imports: dict[str, str] = {}
        self._shadowed_builtins: set[str] = set()
        self._class_index: dict[str, list[dict[str, Any]]] = {}
        self._owner_declarations: list[dict[str, Any]] | None = None
        self._call_index: dict[str, dict[str, Any]] = {}
        self._literal_dict_keys: dict[tuple[int, int], str] = {}
        self._literal_dict_objects: dict[int, str] = {}
        self._template_context_nodes: dict[tuple[int, int, int, int], dict[str, str]] = {}
        self._template_context_fields: dict[tuple[int, int, int, int], dict[str, dict[str, str]]] = {}
        self.tree = self._parse(self.file)
        self.method = self._find_node(self.tree, self.scope)
        if self.method is None:
            raise ValueError('selected scope is absent from retained source')
        self._index_imports()
        self._index_builtin_shadows()
        self._index_classes()
        self._index_calls()

    def _parse(self, file: str) -> ast.AST:
        if file not in self._trees:
            source = self.model['files'][file]['source']
            try:
                tree = ast.parse(source, filename=file, type_comments=True)
            except (SyntaxError, RecursionError) as exc:
                raise ValueError('retained source could not be parsed for method data flow') from exc
            if sum(1 for _ in ast.walk(tree)) > MAX_SOURCE_NODES:
                raise ValueError('source syntax exceeds method data-flow budget')
            self._trees[file] = tree
        return self._trees[file]

    @staticmethod
    def _find_node(tree: ast.AST, scope: dict[str, Any]) -> ast.AST | None:
        # Scope IDs include the filename, which may legally contain a colon.
        # Split from the right to recover the source position unambiguously.
        parts = scope['id'].rsplit(':', 6)
        if len(parts) != 7:
            return None
        _, start, col, end, end_col, _, _ = parts
        for node in ast.walk(tree):
            if not isinstance(node, _SCOPES):
                continue
            if (getattr(node, 'lineno', 0) == int(start)
                    and getattr(node, 'col_offset', 0) == int(col)
                    and getattr(node, 'end_lineno', 0) == int(end)
                    and getattr(node, 'end_col_offset', 0) == int(end_col)):
                return node
        return None

    def _span(self, node: ast.AST, file: str | None = None) -> dict[str, Any]:
        file = file or self.file
        start = getattr(node, 'lineno', 1)
        return {'file': file, 'start': start, 'end': getattr(node, 'end_lineno', start),
                'col': getattr(node, 'col_offset', 0),
                'endCol': getattr(node, 'end_col_offset', 0),
                'hash': self.model['files'][file]['hash']}

    def _check_time(self) -> None:
        if time.monotonic() - self.started > MAX_SECONDS:
            self._truncated = True
            self._omitted += 1
            raise _LimitReached

    def _node(self, name: str, kind: str, node: ast.AST, *, expression: str | None = None,
              annotation: str | None = None, certainty: str = 'source',
              object_id: str | None = None, shape: str | None = None,
              span: dict[str, Any] | None = None) -> str:
        self._check_time()
        if len(self.nodes) >= MAX_NODES:
            self._truncated = True
            self._omitted += 1
            raise _LimitReached
        version = self._versions.get(name, -1) + 1
        self._versions[name] = version
        identifier = f'n{len(self.nodes) + 1}'
        row = {'id': identifier, 'name': name, 'kind': kind, 'version': version,
               'expression': _short(expression if expression is not None else name),
               'annotation': annotation, 'span': span or self._span(node),
               'certainty': certainty}
        if object_id is not None:
            row['objectId'] = object_id
        if shape is not None:
            row['shape'] = shape
        self.nodes.append(row)
        self._node_by_id[identifier] = row
        return identifier

    def _object(self) -> str:
        self._object_count += 1
        return f'o{self._object_count}'

    def _edge(self, source: str, target: str, kind: str, node: ast.AST,
              certainty: str = 'source', span: dict[str, Any] | None = None) -> None:
        if len(self.edges) >= self.max_edges:
            self._truncated = True
            self._omitted += 1
            return
        self._edge_count += 1
        self.edges.append({'id': f'x{self._edge_count}', 'from': source, 'to': target,
                           'kind': kind, 'span': span or self._span(node), 'certainty': certainty})

    def _event(self, kind: str, node: ast.AST, inputs: list[str], outputs: list[str],
               *, label: str | None = None, certainty: str = 'source',
               details: dict[str, Any] | None = None,
               span: dict[str, Any] | None = None) -> str:
        self._check_time()
        if len(self.events) >= self.max_events:
            self._truncated = True
            self._omitted += 1
            raise _LimitReached
        self._event_count += 1
        identifier = f'e{self._event_count}'
        row = {'id': identifier, 'kind': kind, 'label': label or kind.replace('_', ' '),
               'expression': _short(_text(node)), 'span': span or self._span(node),
               'inputs': _unique(inputs), 'outputs': _unique(outputs),
               'guards': [guard.copy() for guard in self._guards], 'certainty': certainty}
        if details:
            row['details'] = details
        self.events.append(row)
        for source in row['inputs']:
            self._edge(source, identifier, 'input', node, certainty, span)
        for target in row['outputs']:
            self._edge(identifier, target, 'output', node, certainty, span)
        return identifier

    def _gap(self, kind: str, message: str, node: ast.AST,
             span: dict[str, Any] | None = None) -> None:
        if len(self.gaps) < 100:
            self.gaps.append({'id': f'g{len(self.gaps) + 1}', 'kind': kind,
                              'message': message, 'expression': _short(_text(node)),
                              'span': span or self._span(node)})
        else:
            self._truncated = True
            self._omitted += 1

    def _index_calls(self) -> None:
        def walk(rows: list[dict[str, Any]]) -> None:
            for row in rows:
                for call in row.get('calls', []):
                    self._call_index[call['id']] = call
                for branch in row.get('branches', []):
                    walk(branch.get('nodes', []))
                walk(row.get('body', []))
                for child in row.get('children', []):
                    walk([child])
        walk(self.scope.get('flow', []))

    def _call_key(self, node: ast.Call) -> str:
        return f'{self.file}:{node.lineno}:{node.col_offset}:{node.end_lineno}:{node.end_col_offset}:Call'

    def _template_link(self, node: ast.Call) -> dict[str, Any] | None:
        span = self._span(node)
        return next((link for link in self.model.get('templateLinks', [])
                     if link.get('scope') == self.scope['id'] and link.get('span') == span), None)

    def _index_imports(self) -> None:
        # Imports are references, not input records. Module imports and local
        # imports are indexed only as names; timing and shadowing remain open.
        module_body = getattr(self.tree, 'body', [])
        method_body = [] if isinstance(self.method, ast.Lambda) else getattr(self.method, 'body', [])
        body = list(module_body) + list(method_body)
        for statement in body:
            if isinstance(statement, ast.ImportFrom):
                if statement.level:
                    parts = self.scope['module'].split('.')
                    if not self.file.endswith('__init__.py'):
                        parts.pop()
                    if statement.level > 1:
                        parts = parts[:-(statement.level - 1)]
                    prefix = '.'.join(parts + ([statement.module] if statement.module else []))
                else:
                    prefix = statement.module or ''
                for alias in statement.names:
                    self._imports[alias.asname or alias.name] = f'{prefix}.{alias.name}'.strip('.')
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    self._imports[alias.asname or alias.name.split('.')[0]] = (
                        alias.name if alias.asname else alias.name.split('.')[0])

    def _index_classes(self) -> None:
        for scope in self.model['scopes'].values():
            if scope['kind'] != 'class':
                continue
            self._class_index.setdefault(scope['name'], []).append(scope)
            self._class_index.setdefault(f"{scope['module']}.{scope['qualified']}", []).append(scope)

    def _index_builtin_shadows(self) -> None:
        # Search the selected method and module bindings. Another method's
        # parameter cannot shadow this method's builtin lookup.
        names = set(_CONTAINER_BUILTINS)
        roots = [self.method]
        for statement in getattr(self.tree, 'body', []):
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if statement.name in names:
                    self._shadowed_builtins.add(statement.name)
                continue
            roots.append(statement)
        for node in (child for root in roots for child in ast.walk(root)):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if node.id in names:
                    self._shadowed_builtins.add(node.id)
            elif isinstance(node, ast.arg) and node.arg in names:
                self._shadowed_builtins.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
                self._shadowed_builtins.add(node.name)
        self._shadowed_builtins.update(names & self._imports.keys())

    def _external_node(self, name: str, node: ast.AST) -> str:
        if name in self._external:
            return self._external[name]
        imported = self._imports.get(name)
        candidates = self._class_index.get(imported or name, [])
        kind = 'model_reference' if candidates else 'import_reference' if imported else 'external'
        identifier = self._node(name, kind, node, expression=imported or name,
                                certainty='reference' if imported or candidates else 'unknown')
        self._external[name] = identifier
        if kind == 'external':
            self._gap('unbound_read', f'{name} is not bound in this method; its source is not established', node)
        return identifier

    def _value_for_name(self, name: str, node: ast.AST) -> _Value:
        identifier = self._state.names.get(name) or self._external_node(name, node)
        row = self._node_by_id[identifier]
        object_id = row.get('objectId')
        latest = self._state.objects.get(object_id) if object_id else None
        sources = [identifier] + ([latest] if latest and latest != identifier else [])
        return _Value(sources, object_id, row.get('shape'))

    def _field_key(self, node: ast.Attribute | ast.Subscript) -> tuple[str, str] | None:
        if isinstance(node.value, ast.Name):
            base = self._state.names.get(node.value.id)
            if base:
                object_id = self._node_by_id[base].get('objectId')
                if object_id:
                    if isinstance(node, ast.Attribute):
                        return object_id, node.attr
                    if isinstance(node.slice, ast.Constant):
                        return object_id, repr(node.slice.value)
        return None

    def _read_field(self, node: ast.Attribute | ast.Subscript) -> _Value:
        key = self._field_key(node)
        if key and key in self._state.fields:
            identifier = self._state.fields[key]
            row = self._node_by_id[identifier]
            return _Value([identifier], row.get('objectId'), row.get('shape'))
        if (key and isinstance(node, ast.Attribute) and
                isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls')):
            owner = self.model['scopes'].get(self.scope.get('parent'))
            if owner and owner['kind'] == 'class':
                if self._owner_declarations is None:
                    self._owner_declarations = self._model_fields(owner, set())
                declarations = [item for item in self._owner_declarations
                                if item['name'] == node.attr]
                if declarations:
                    base = self._eval(node.value)
                    annotation = declarations[0].get('annotation')
                    object_id = self._object() if annotation in self._class_index else None
                    identifier = self._node(_text(node), 'field_read', node,
                                            expression=_text(node), annotation=annotation,
                                            certainty='possible', object_id=object_id)
                    self._state.fields[key] = identifier
                    self._event('read_declared_field', node, base.sources, [identifier],
                                label=f'possible read of {_text(node)}', certainty='possible',
                                details={'definitionSpan': declarations[0]['span'],
                                         'declaredIn': declarations[0]['owner'],
                                         'declarationIsNotRuntimeValue': True})
                    return _Value([identifier], object_id)
        base = self._eval(node.value)
        if isinstance(node, ast.Subscript):
            base.sources += self._eval(node.slice).sources
        elif isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls'):
            self._gap('unresolved_instance_attribute',
                      f'no indexed declaration establishes {_text(node)} as an input field', node)
        return _Value(_unique(base.sources))

    def _eval_guarded(self, expression: ast.expr, start: _State,
                      guard: dict[str, Any]) -> tuple[_Value, _State]:
        saved = self._state
        self._state = start.fork()
        self._guards.append(guard)
        try:
            value = self._eval(expression)
            return value, self._state
        finally:
            self._guards.pop()
            self._state = saved

    def _eval(self, node: ast.AST | None) -> _Value:
        if node is None:
            return _Value()
        self._check_time()
        if isinstance(node, ast.Name):
            return self._value_for_name(node.id, node)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            base = self._eval(node.value)
            bounds = []
            for item in (node.slice.lower, node.slice.upper, node.slice.step):
                bounds.extend(self._eval(item).sources)
            object_id = self._object()
            result = self._node(_short(_text(node), 80), 'container', node,
                                expression=_text(node), certainty='possible',
                                object_id=object_id, shape=base.shape or 'slice')
            self._event('slice', node, _unique(base.sources + bounds), [result],
                        label='new slice', certainty='possible',
                        details={'elementsMayAliasInput': True})
            return _Value([result], object_id, base.shape or 'slice')
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            return self._read_field(node)
        if isinstance(node, ast.Constant):
            return _Value()
        if isinstance(node, ast.NamedExpr):
            value = self._eval(node.value)
            self._assign(node.target, value, node)
            return value
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            parts = []
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    parts.extend(self._eval(key).sources)
                    parts.extend(self._eval(value).sources)
            else:
                for element in node.elts:
                    parts.extend(self._eval(element).sources)
            shape = type(node).__name__.lower()
            object_id = self._object()
            if isinstance(node, ast.Dict):
                self._state.dict_keys[object_id] = (
                    {repr(key.value) for key in node.keys if isinstance(key, ast.Constant)}
                    if all(isinstance(key, ast.Constant) for key in node.keys) else None)
                self._literal_dict_objects[id(node)] = object_id
            result = self._node(_short(_text(node), 80), 'container', node,
                                expression=_text(node), object_id=object_id, shape=shape)
            self._event('new_container', node, _unique(parts), [result], label=f'new {shape}')
            if isinstance(node, ast.Dict):
                for index, (key, value) in enumerate(zip(node.keys, node.values)):
                    if isinstance(key, ast.Constant):
                        field_name = repr(key.value)
                        field_id = self._node(f'{_short(_text(node), 50)}[{field_name}]', 'key', value,
                                              expression=_text(value))
                        self._state.fields[(object_id, field_name)] = field_id
                        self._literal_dict_keys[(id(node), index)] = field_id
                        self._event('added_key', value, self._read_sources(value), [field_id],
                                    label=f'added key {field_name}')
            return _Value([result], object_id, shape)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            first_iter = self._eval(node.generators[0].iter) if node.generators else _Value()
            inputs = list(first_iter.sources)
            guards = [_text(condition) for generator in node.generators
                      for condition in generator.ifs]
            shape = ('generator' if isinstance(node, ast.GeneratorExp) else
                     'dict' if isinstance(node, ast.DictComp) else
                     'set' if isinstance(node, ast.SetComp) else 'list')
            if not isinstance(node, ast.GeneratorExp):
                before = self._state.fork()
                saved = self._state
                self._state = before.fork()
                self._guards.append(self._guard(node, 'one or more elements', 'comprehension'))
                try:
                    for index, generator in enumerate(node.generators):
                        iterable = first_iter if index == 0 else self._eval(generator.iter)
                        inputs.extend(iterable.sources)
                        if isinstance(generator.target, ast.Name):
                            item = self._node(generator.target.id, 'comprehension_item', generator.target,
                                              expression=_text(generator.iter), certainty='possible',
                                              object_id=self._object())
                            self._state.names[generator.target.id] = item
                            self._event('iteration_item', generator.target, iterable.sources, [item],
                                        label=f'possible element of {_short(_text(generator.iter))}',
                                        certainty='possible')
                            inputs.append(item)
                        for condition in generator.ifs:
                            inputs.extend(self._eval(condition).sources)
                    self._guards.append(self._guard(node, 'filters pass', 'comprehension'))
                    try:
                        if isinstance(node, ast.DictComp):
                            inputs.extend(self._eval(node.key).sources)
                            inputs.extend(self._eval(node.value).sources)
                        else:
                            inputs.extend(self._eval(node.elt).sources)
                    finally:
                        self._guards.pop()
                    after = self._state
                    # Comprehension target names do not escape the expression.
                    after.names = before.names.copy()
                finally:
                    self._guards.pop()
                    self._state = saved
                self._state = self._join([before, after], node)
            object_id = self._object()
            result = self._node(_short(_text(node), 80), 'container', node,
                                expression=_text(node), object_id=object_id, shape=shape,
                                certainty='possible')
            kind = 'deferred_generator' if isinstance(node, ast.GeneratorExp) else 'comprehension'
            self._event(kind, node, _unique(inputs), [result],
                        label=f'{"deferred " if kind == "deferred_generator" else "new "}{shape} from comprehension',
                        certainty='possible', details={'filters': guards, 'mayBeEmpty': True,
                                                        'elementsMayAliasInput': True,
                                                        'bodyDeferred': kind == 'deferred_generator'})
            return _Value([result], object_id, shape)
        if isinstance(node, ast.IfExp):
            test = self._eval(node.test)
            before = self._state.fork()
            yes, yes_state = self._eval_guarded(node.body, before,
                                                self._guard(node.test, 'true'))
            no, no_state = self._eval_guarded(node.orelse, before,
                                              self._guard(node.test, 'false'))
            self._state = self._join([yes_state, no_state], node)
            result = self._node(_short(_text(node), 80), 'conditional_value', node,
                                expression=_text(node), certainty='possible')
            self._event('conditional_value', node, test.sources + yes.sources + no.sources,
                        [result], certainty='possible',
                        details={'condition': _text(node.test), 'alternatives': [_text(node.body), _text(node.orelse)]})
            return _Value([result])
        if isinstance(node, ast.BoolOp):
            parts = [self._eval(node.values[0])]
            for previous, expression in zip(node.values, node.values[1:]):
                before = self._state.fork()
                branch = 'previous truthy' if isinstance(node.op, ast.And) else 'previous falsy'
                value, after = self._eval_guarded(expression, before,
                                                  self._guard(previous, branch, 'short-circuit'))
                self._state = self._join([before, after], node)
                parts.append(value)
            result = self._node(_short(_text(node), 80), 'conditional_value', node,
                                expression=_text(node), certainty='possible')
            self._event('short_circuit', node, [item for part in parts for item in part.sources], [result],
                        certainty='possible', details={'alternatives': [_text(v) for v in node.values]})
            return _Value([result])
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            value = self._eval(node.value)
            output = self._node('yield', 'output', node,
                                expression=_text(node.value), object_id=value.object_id)
            self._event('yield', node, value.sources, [output],
                        label=f'yield {_short(_text(node.value))}')
            return _Value([output], value.object_id, value.shape)
        if isinstance(node, (ast.Await, ast.Starred)):
            return self._eval(node.value)
        if isinstance(node, ast.Lambda):
            result = self._node(_short(_text(node), 80), 'deferred_callable', node, expression=_text(node))
            self._event('deferred_callable', node, [], [result], label='lambda body is deferred')
            return _Value([result])
        sources = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                sources.extend(self._eval(child).sources)
        return _Value(_unique(sources))

    def _read_sources(self, node: ast.AST | None) -> list[str]:
        # Inspect source names without repeating call/container events.
        if node is None:
            return []
        rows = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                rows.extend(self._value_for_name(child.id, child).sources)
        return _unique(rows)

    def _call(self, node: ast.Call) -> _Value:
        receiver = None
        if isinstance(node.func, ast.Attribute):
            receiver = self._eval(node.func.value)
        elif not isinstance(node.func, ast.Name):
            receiver = self._eval(node.func)
        args = []
        argument_nodes: dict[str, list[str]] = {}
        for arg in node.args:
            sources = self._eval(arg).sources
            args.extend(sources)
            argument_nodes[_text(arg)] = sources
        for keyword in node.keywords:
            sources = self._eval(keyword.value).sources
            args.extend(sources)
            argument_nodes[_text(keyword.value)] = sources
        call = self._call_index.get(self._call_key(node))
        status = call['status'] if call else 'unknown'
        targets = call.get('targets', []) if call else []
        name = _text(node.func)
        method_name = node.func.attr if isinstance(node.func, ast.Attribute) else name
        template_link = self._template_link(node) if method_name == 'TemplateResponse' else None
        supported_template = bool(template_link and template_link.get('providerStatus') == 'supported')
        known_constructor = any(scope['kind'] == 'class' for scope in
                                (self.model['scopes'].get(target, {}) for target in targets))
        shape = (_CONTAINER_BUILTINS.get(name)
                 if isinstance(node.func, ast.Name) and name not in self._shadowed_builtins
                 else None)
        object_id = self._object() if known_constructor or shape else None
        result = self._node(_short(_text(node), 80), 'call_result', node,
                            expression=_text(node), certainty='possible',
                            object_id=object_id, shape=shape)
        details = {'callStatus': status, 'targets': targets,
                   'callReason': call.get('reason', 'not represented by call analyzer') if call else
                   'not represented by call analyzer',
                   'bindings': call.get('bindings', {}) if call else {},
                   'receiverBindings': call.get('receiverBindings', {}) if call else {}}
        if status in ('supported', 'possible') and len(targets) == 1:
            cross_method = self._cross_method(node, call, targets[0], result,
                                              argument_nodes, receiver, status)
            if cross_method:
                details['crossMethod'] = cross_method
        if method_name in ('select', 'count') and node.args:
            details['queryShape'] = _text(node.args[0])
            details['queryRowsUnproven'] = True
        if supported_template:
            details['templateBoundary'] = True
        inputs = _unique(args + (receiver.sources if receiver else []))
        self._event('call', node, inputs, [result], label=f'call {name}',
                    certainty='possible', details=details)
        # An arbitrary callee can mutate a passed dictionary. Exact key
        # membership learned from a fresh literal no longer survives the call.
        for source in inputs:
            object_ref = self._node_by_id.get(source, {}).get('objectId')
            if object_ref in self._state.dict_keys:
                self._state.dict_keys[object_ref] = None
        if details.get('crossMethod', {}).get('mutationSites'):
            self._post_call_state(node, details['crossMethod'])
        if supported_template:
            self._template_context(node)
        elif template_link and template_link.get('providerStatus') != 'supported':
            self._gap('unknown_template_provider',
                      'TemplateResponse name is shadowed or its provider is not established', node)
        if method_name in _MUTATORS and isinstance(node.func, ast.Attribute):
            self._mutate_receiver(node, receiver, method_name, args)
        elif receiver and receiver.object_id:
            self._gap('possible_call_effect', f'{name} may change the receiver; effect is not modeled', node)
        if status in ('external', 'unknown') and (name not in ('len', 'str', 'int', 'bool')
                                                 and shape is None):
            self._gap('opaque_call_result', f'{name} result and effects are not known from indexed source', node)
        return _Value([result], object_id, shape)

    def _post_call_state(self, call_node: ast.Call, cross_method: dict[str, Any]) -> None:
        """Join a source-backed possible write with the unchanged caller state."""
        links = cross_method['parameterLinks']
        changed: set[str] = set()
        for site in cross_method['mutationSites']:
            for link in links:
                if link['parameter'] != site['parameter']:
                    continue
                candidates = [self._node_by_id[item] for item in link['argumentNodes']
                              if item in self._node_by_id and self._node_by_id[item].get('objectId')]
                if len({item['objectId'] for item in candidates}) != 1:
                    continue
                object_id = candidates[0]['objectId']
                if object_id in changed:
                    continue
                changed.add(object_id)
                before = self._state.fork()
                prior = before.objects.get(object_id) or candidates[0]['id']
                next_state = self._node(candidates[0]['name'], 'object_state', call_node,
                                        expression=f'possible effect of {_text(call_node)}',
                                        certainty='possible', object_id=object_id)
                self._event('possible_callee_mutation', call_node, [prior], [next_state],
                            label=f'possible callee change to {candidates[0]["name"]}',
                            certainty='possible',
                            details={'calleeScope': cross_method['calleeScope'],
                                     'mutationSpan': site['span'], 'parameter': site['parameter'],
                                     'executionUnproven': True})
                after = before.fork()
                after.objects[object_id] = next_state
                self._state = self._join([before, after], call_node)

    def _cross_method(self, call_node: ast.Call, call: dict[str, Any] | None,
                      target_id: str, result_id: str,
                      argument_nodes: dict[str, list[str]],
                      receiver: _Value | None, call_status: str) -> dict[str, Any] | None:
        target = self.model['scopes'].get(target_id)
        if not target or target['kind'] == 'class':
            return None
        callee = self._find_node(self._parse(target['file']), target)
        if not isinstance(callee, _FUNCTIONS):
            return None
        param_spans = {}
        for parameter in (callee.args.posonlyargs + callee.args.args +
                          callee.args.kwonlyargs +
                          [item for item in (callee.args.vararg, callee.args.kwarg) if item]):
            param_spans[parameter.arg] = self._span(parameter, target['file'])
        bindings = call.get('bindings', {}).get(target_id, []) if call else []
        receiver_binding = call.get('receiverBindings', {}).get(target_id, {}) if call else {}
        parameter_links = []
        for binding in bindings[:50]:
            argument = binding['argument']
            source_ids = argument_nodes.get(argument, [])
            if (receiver and receiver_binding.get('mode') == 'implicit'
                    and target['params'] and binding['parameter'] == target['params'][0]['name']):
                source_ids = receiver.sources
            parameter_links.append({'argument': argument, 'argumentNodes': source_ids,
                                    'parameter': binding['parameter'],
                                    'parameterSpan': param_spans.get(binding['parameter']),
                                    'bindingCertainty': binding['certainty'],
                                    'lineageCertainty': 'possible'})
        if len(bindings) > 50:
            self._truncated = True
            self._omitted += len(bindings) - 50
            self._gap('cross_method_limit', 'additional argument bindings omitted', call_node)

        def own_nodes(root: ast.AST):
            for child in ast.iter_child_nodes(root):
                if isinstance(child, _SCOPES):
                    continue
                yield child
                yield from own_nodes(child)

        return_sites = []
        mutation_sites = []
        omitted_returns = 0
        omitted_mutations = 0
        parameter_names = {row['name'] for row in target['params']}
        roots = callee.body if not isinstance(callee, ast.Lambda) else [callee.body]
        def body_nodes():
            for root in roots:
                yield root
                yield from own_nodes(root)
        for child in body_nodes():
            self._check_time()
            if isinstance(child, ast.Return):
                if len(return_sites) < 20:
                    return_sites.append({'expression': _text(child.value),
                                         'span': self._span(child, target['file']),
                                         'certainty': 'static return expression; execution unproven'})
                else:
                    omitted_returns += 1
            mutation_param = None
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
                targets = (child.targets if isinstance(child, (ast.Assign, ast.Delete)) else
                           [child.target])
                for written in targets:
                    if (isinstance(written, (ast.Attribute, ast.Subscript)) and
                            isinstance(written.value, ast.Name) and
                            written.value.id in parameter_names):
                        mutation_param = written.value.id
                        break
            elif (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                  and isinstance(child.func.value, ast.Name)
                  and child.func.value.id in parameter_names):
                mutation_param = child.func.value.id
            if mutation_param:
                if len(mutation_sites) < 20:
                    mutation_sites.append({'parameter': mutation_param,
                                           'expression': _short(_text(child)),
                                           'span': self._span(child, target['file']),
                                           'certainty': 'possible effect; execution unproven'})
                else:
                    omitted_mutations += 1
        if omitted_returns or omitted_mutations:
            self._truncated = True
            self._omitted += omitted_returns + omitted_mutations
            self._gap('cross_method_limit',
                      'additional callee return or parameter-effect sites omitted', call_node)
        if mutation_sites:
            self._gap('possible_callee_mutation',
                      f'{target["qualified"]} contains a write or method call through a parameter; caller state may change',
                      call_node)
        return {'calleeScope': target_id, 'callSpan': self._span(call_node),
                'resultNode': result_id, 'parameterLinks': parameter_links,
                'returnSites': return_sites if not target.get('generator') else [],
                'mutationSites': mutation_sites,
                'callTargetCertainty': call_status, 'lineageCertainty': 'possible',
                'executionUnproven': True,
                'resultBoundary': ('generator body is deferred' if target.get('generator') else
                                   'coroutine body runs when awaited or scheduled' if target.get('async')
                                   and not (call and call.get('awaited')) else
                                   'return expression is a source reference, not a proven value')}

    def _mutate_receiver(self, node: ast.Call, receiver: _Value | None,
                         method_name: str, args: list[str]) -> None:
        if receiver is None or receiver.object_id is None:
            self._gap('possible_mutation', f'{method_name} may mutate its receiver; alias is not established', node)
            return
        prior = self._state.objects.get(receiver.object_id)
        display = _text(node.func.value) if isinstance(node.func, ast.Attribute) else 'receiver'
        next_state = self._node(display, 'object_state', node, expression=_text(node),
                                certainty='possible', object_id=receiver.object_id)
        self._state.objects[receiver.object_id] = next_state
        kind = 'removed_item' if method_name in ('remove', 'discard', 'pop', 'popitem', 'clear') else 'added_item' if method_name in ('append', 'extend', 'insert', 'add') else 'updated_object'
        self._event(kind, node, _unique(([prior] if prior else receiver.sources) + args), [next_state],
                    label=f'{method_name} on {display}', certainty='possible',
                    details={'objectId': receiver.object_id, 'method': method_name,
                             'effect': 'possible mutation; method dispatch is not proven'})

    def _template_context(self, node: ast.Call) -> None:
        site = (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)
        context_nodes = self._template_context_nodes.setdefault(site, {})
        context_fields = self._template_context_fields.setdefault(site, {})
        for context in _context_dicts(node):
            for index, (key, value) in enumerate(zip(context.keys, context.values)):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    self._gap('dynamic_context_key', 'template context key is not a literal string', value)
                    continue
                source_ids = self._read_sources(value)
                literal_key = self._literal_dict_keys.get((id(context), index))
                if literal_key:
                    source_ids.append(literal_key)
                target = self._node(f'context.{key.value}', 'template_context', value,
                                    expression=_text(value))
                self._event('template_context', value, _unique(source_ids), [target],
                            label=f'context key {key.value}',
                            details={'key': key.value, 'boundary': 'template input; rendering is not proven'})
                context_nodes[key.value] = target
                object_id = None
                if isinstance(value, ast.Name):
                    name_id = self._state.names.get(value.id)
                    if name_id:
                        object_id = self._node_by_id[name_id].get('objectId')
                elif isinstance(value, ast.Dict):
                    object_id = self._literal_dict_objects.get(id(value))
                if object_id not in self._literal_dict_objects.values():
                    continue
                fields = {}
                for (owner, field_name), field_id in self._state.fields.items():
                    if owner != object_id:
                        continue
                    try:
                        literal = ast.literal_eval(field_name)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(literal, str):
                        fields[literal] = field_id
                context_fields[key.value] = fields

    def _assign(self, target: ast.AST, value: _Value, statement: ast.AST,
                *, annotation: str | None = None, augmented: bool = False) -> None:
        if isinstance(target, ast.Name):
            previous = self._state.names.get(target.id)
            identifier = self._node(target.id, 'local', target, expression=_text(statement),
                                    annotation=annotation, object_id=value.object_id,
                                    shape=value.shape)
            self._state.names[target.id] = identifier
            kind = 'augmented_assignment' if augmented else 'reassigned_name' if previous else 'new_value'
            inputs = value.sources + ([previous] if augmented and previous else [])
            self._event(kind, statement, inputs, [identifier], label=f'{kind.replace("_", " ")} {target.id}',
                        details={'previous': previous, 'next': identifier,
                                 'aliasOf': value.sources[0] if value.object_id and len(value.sources) == 1 else None})
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and isinstance(statement.value, ast.Dict) and value.object_id:
                for (object_id, field_name), field_id in list(self._state.fields.items()):
                    if object_id == value.object_id:
                        self._node_by_id[field_id]['name'] = f'{target.id}[{field_name}]'
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._assign(element, value, statement)
            self._gap('unpack_shape', 'unpacking positions are possible origins; exact element mapping is not established', statement)
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            key = self._field_key(target)
            name = _text(target)
            previous = self._state.fields.get(key) if key else None
            known_keys = self._state.dict_keys.get(key[0]) if key else None
            if isinstance(target, ast.Attribute):
                kind, prior_presence = 'assigned_field', 'unknown'
            elif known_keys is None or key is None:
                kind, prior_presence = 'assigned_key', 'unknown'
            elif key[1] in known_keys:
                kind, prior_presence = 'updated_key', 'present'
            else:
                kind, prior_presence = 'added_key', 'absent'
            base = self._state.names.get(target.value.id) if isinstance(target.value, ast.Name) else None
            receiver_possible = bool(base and self._node_by_id[base]['certainty'] == 'possible')
            declaration = None
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in ('self', 'cls'):
                owner = self.model['scopes'].get(self.scope.get('parent'))
                if owner and owner['kind'] == 'class':
                    if self._owner_declarations is None:
                        self._owner_declarations = self._model_fields(owner, set())
                    declaration = next((row for row in self._owner_declarations
                                        if row['name'] == target.attr), None)
            identifier = self._node(name, 'field' if isinstance(target, ast.Attribute) else 'key', target,
                                    expression=_text(statement), annotation=annotation,
                                    certainty='source' if key and not receiver_possible
                                    and not isinstance(target, ast.Attribute) else 'possible')
            if key:
                self._state.fields[key] = identifier
                if known_keys is not None and isinstance(target, ast.Subscript):
                    known_keys.add(key[1])
            else:
                self._gap('unresolved_write_receiver', f'object identity for {name} is not established', target)
            receiver_sources = (self._value_for_name(target.value.id, target.value).sources
                                if isinstance(target.value, ast.Name) else [])
            inputs = value.sources + receiver_sources + ([previous] if augmented and previous else [])
            self._event(kind, statement, inputs, [identifier], label=f'{kind.replace("_", " ")} {name}',
                        certainty='source' if key and not receiver_possible
                        and not isinstance(target, ast.Attribute) else 'possible',
                        details={'previous': previous, 'next': identifier,
                                 'priorPresence': prior_presence,
                                 'possibleAddition': prior_presence == 'unknown',
                                 'declarationKnown': declaration is not None,
                                 'declarationSpan': declaration['span'] if declaration else None})
            if key:
                object_id = key[0]
                prior_state = self._state.objects.get(object_id)
                base_node = (self._state.names.get(target.value.id)
                             if isinstance(target.value, ast.Name) else None)
                next_state = self._node(_text(target.value), 'object_state', statement,
                                        expression=_text(statement), object_id=object_id)
                self._state.objects[object_id] = next_state
                self._event('updated_object', statement,
                            _unique(([prior_state or base_node] if prior_state or base_node else []) + [identifier]), [next_state],
                            label=f'object state after {name}',
                            details={'objectId': object_id, 'field': name})
            return
        self._gap('unsupported_assignment_target', f'assignment target {_text(target)} is not modeled', target)

    def _delete(self, target: ast.AST, statement: ast.AST) -> None:
        if isinstance(target, ast.Name):
            previous = self._state.names.pop(target.id, None)
            self._event('removed_name', statement, [previous] if previous else [], [],
                        label=f'removed name {target.id}')
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            key = self._field_key(target)
            previous = self._state.fields.pop(key, None) if key else None
            known_keys = self._state.dict_keys.get(key[0]) if key else None
            if isinstance(target, ast.Attribute):
                kind, prior_presence = 'possible_remove_field', 'unknown'
            elif key is None or known_keys is None:
                kind, prior_presence = 'possible_remove_key', 'unknown'
            elif key[1] in known_keys:
                kind, prior_presence = 'removed_key', 'present'
                known_keys.remove(key[1])
            else:
                kind, prior_presence = 'attempted_remove_key', 'absent'
            removed = self._node(_text(target), 'removal', target,
                                 expression=_text(statement),
                                 certainty='source' if kind == 'removed_key' else 'possible')
            self._event(kind,
                        statement, [previous] if previous else self._read_sources(target), [removed],
                        label=f'{kind.replace("_", " ")} {_text(target)}',
                        certainty='source' if kind == 'removed_key' else 'possible',
                        details={'priorPresence': prior_presence,
                                 'mayRaiseIfAbsent': kind != 'removed_key'})
            if key is None:
                self._gap('unresolved_delete_receiver', 'deleted receiver identity is not established', target)
            else:
                if kind != 'removed_key':
                    self._gap('uncertain_delete',
                              'source does not establish that the key or field existed before deletion; this may raise',
                              target)
                prior_state = self._state.objects.get(key[0])
                base_node = (self._state.names.get(target.value.id)
                             if isinstance(target.value, ast.Name) else None)
                next_state = self._node(_text(target.value), 'object_state', statement,
                                        expression=_text(statement), object_id=key[0])
                self._state.objects[key[0]] = next_state
                self._event('updated_object', statement,
                            _unique([source for source in (prior_state or base_node, removed) if source]),
                            [next_state], label=f'object state after deleting {_text(target)}',
                            certainty='source' if kind == 'removed_key' else 'possible',
                            details={'objectId': key[0], 'removed': _text(target)})
            return
        self._gap('unsupported_delete_target', f'delete target {_text(target)} is not modeled', target)

    def _guard(self, condition: ast.AST, branch: str, kind: str = 'branch') -> dict[str, Any]:
        return {'kind': kind, 'condition': _short(_text(condition)), 'branch': branch,
                'span': self._span(condition)}

    def _join(self, states: list[_State], node: ast.AST) -> _State:
        live = [state for state in states if state.live]
        if not live:
            return _State(live=False)
        if len(live) == 1:
            return live[0]
        result = live[0].fork()
        for attr in ('names', 'fields', 'objects'):
            keys = set().union(*(getattr(state, attr) for state in live))
            merged = getattr(result, attr)
            merged.clear()
            for key in sorted(keys, key=str):
                origins = _unique([getattr(state, attr)[key] for state in live if key in getattr(state, attr)])
                if len(origins) == 1 and all(key in getattr(state, attr) for state in live):
                    merged[key] = origins[0]
                    continue
                label = key if isinstance(key, str) else key[1] if attr == 'fields' else str(key)
                if attr == 'objects':
                    # Object keys are internal ids (o2); readers know the object by its value's name.
                    label = next((self._node_by_id[origin]['name'] for origin in origins
                                  if origin in self._node_by_id), label)
                identifier = self._node(label, 'join', node, expression=f'possible values of {label}',
                                        certainty='possible')
                self._event('join', node, origins, [identifier], label=f'possible {label} after branch',
                            certainty='possible', details={'alternatives': origins,
                                                            'mayBeUnbound': len(origins) < len(live)})
                merged[key] = identifier
        all_dicts = set().union(*(state.dict_keys for state in live))
        result.dict_keys = {}
        for object_id in all_dicts:
            choices = [state.dict_keys.get(object_id) for state in live]
            result.dict_keys[object_id] = (choices[0].copy() if choices[0] is not None
                                           and all(choice == choices[0] for choice in choices)
                                           else None)
        return result

    def _block(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self._check_time()
            if not self._state.live:
                self._gap('unreachable_source', 'source follows an unconditional return or raise on this path', statement)
                break
            self._statement(statement)

    def _branch_block(self, statements: list[ast.stmt], start: _State,
                      guard: dict[str, Any]) -> _State:
        saved = self._state
        self._state = start.fork()
        self._guards.append(guard)
        try:
            self._block(statements)
            return self._state
        finally:
            self._guards.pop()
            self._state = saved

    def _statement(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Assign):
            value = self._eval(node.value)
            for target in node.targets:
                self._assign(target, value, node)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self._assign(node.target, self._eval(node.value), node,
                             annotation=_text(node.annotation))
            elif isinstance(node.target, ast.Name):
                identifier = self._node(node.target.id, 'annotation', node.target,
                                        annotation=_text(node.annotation), expression=_text(node))
                self._event('declared_name', node, [], [identifier],
                            label=f'declared {node.target.id}')
        elif isinstance(node, ast.AugAssign):
            value = self._eval(node.value)
            prior = self._eval(node.target)
            self._assign(node.target, _Value(_unique(prior.sources + value.sources), prior.object_id),
                         node, augmented=True)
        elif isinstance(node, ast.Expr):
            value = self._eval(node.value)
            if not isinstance(node.value, ast.Call):
                self._event('used_value', node, value.sources, [], label='used value')
        elif isinstance(node, (ast.Return, ast.Raise)):
            value = self._eval(node.value if isinstance(node, ast.Return) else node.exc)
            name = 'return' if isinstance(node, ast.Return) else 'raise'
            output = self._node(name, 'output', node, expression=_text(node.value if isinstance(node, ast.Return) else node.exc),
                                object_id=value.object_id)
            self._event(name, node, value.sources, [output], label=f'{name} {_short(_text(node), 100)}')
            self._state.live = False
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                self._delete(target, node)
        elif isinstance(node, ast.If):
            test = self._eval(node.test)
            self._event('condition', node.test, test.sources, [], label=f'if {_short(_text(node.test))}')
            before = self._state.fork()
            yes = self._branch_block(node.body, before, self._guard(node.test, 'true'))
            no = self._branch_block(node.orelse, before, self._guard(node.test, 'false')) if node.orelse else before
            self._state = self._join([yes, no], node)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            iterable = self._eval(node.iter)
            self._event('iteration', node.iter, iterable.sources, [],
                        label=f'iterate {_short(_text(node.iter))}', certainty='possible',
                        details={'zeroIterationsPossible': True})
            before = self._state.fork()
            if isinstance(node.target, ast.Name):
                object_id = self._object()
                item = self._node(node.target.id, 'iteration_item', node.target,
                                  expression=_text(node.iter), certainty='possible',
                                  object_id=object_id)
                self._state.names[node.target.id] = item
                self._state.objects[object_id] = item
                self._event('iteration_item', node.target, iterable.sources, [item],
                            label=f'possible element of {_short(_text(node.iter))}',
                            certainty='possible')
            else:
                self._assign(node.target, _Value(iterable.sources), node)
            body_start = self._state.fork()
            after = self._branch_block(node.body, body_start, self._guard(node.iter, 'one or more iterations', 'loop'))
            self._state = self._join([before, after], node)
            if node.orelse:
                self._state = self._branch_block(node.orelse, self._state, self._guard(node.iter, 'loop else', 'loop'))
        elif isinstance(node, ast.While):
            test = self._eval(node.test)
            self._event('condition', node.test, test.sources, [], label=f'while {_short(_text(node.test))}',
                        certainty='possible')
            before = self._state.fork()
            after = self._branch_block(node.body, before, self._guard(node.test, 'one or more iterations', 'loop'))
            self._state = self._join([before, after], node)
            if node.orelse:
                self._state = self._branch_block(node.orelse, self._state, self._guard(node.test, 'loop else', 'loop'))
        elif isinstance(node, (ast.Try, getattr(ast, 'TryStar', ast.Try))):
            before = self._state.fork()
            output_start = len(self.nodes)
            normal = self._branch_block(node.body + node.orelse, before,
                                        self._guard(node, 'normal completion', 'try'))
            alternatives = [(normal, [row for row in self.nodes[output_start:]
                                      if row['kind'] == 'output' and row['name'] == 'return'])]
            for handler in node.handlers:
                output_start = len(self.nodes)
                handled = self._branch_block(handler.body, before,
                                             self._guard(handler, _text(handler.type), 'except'))
                alternatives.append((handled, [row for row in self.nodes[output_start:]
                                               if row['kind'] == 'output' and row['name'] == 'return']))
            if node.finalbody:
                finished = []
                for index, (path, returns) in enumerate(alternatives):
                    saved = self._state
                    self._state = path.fork()
                    self._state.live = True
                    output_start = len(self.nodes)
                    self._guards.append(self._guard(node, f'exit path {index + 1}', 'finally'))
                    try:
                        self._block(node.finalbody)
                        after = self._state
                    finally:
                        self._guards.pop()
                        self._state = saved
                    final_outputs = [row for row in self.nodes[output_start:]
                                     if row['kind'] == 'output']
                    if final_outputs:
                        self._gap('finally_override',
                                  'finally may override an earlier return or exception', node.finalbody[-1])
                    else:
                        for output in returns:
                            object_id = output.get('objectId')
                            if not object_id:
                                continue
                            latest = after.objects.get(object_id)
                            previous = path.objects.get(object_id)
                            if latest and latest != previous:
                                self._edge(latest, output['id'], 'possible_finally_effect',
                                           node.finalbody[-1], 'possible')
                    if not path.live and after.live:
                        after.live = False
                    finished.append(after)
                self._state = self._join(finished, node)
            else:
                self._state = self._join([path for path, _ in alternatives], node)
        elif isinstance(node, ast.Match):
            subject = self._eval(node.subject)
            self._event('match', node.subject, subject.sources, [], label=f'match {_short(_text(node.subject))}')
            before = self._state.fork()
            branches = [self._branch_block(case.body, before,
                        self._guard(case.pattern, f'case {_text(case.pattern)}', 'match')) for case in node.cases]
            self._state = self._join([before] + branches, node)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                source = self._eval(item.context_expr)
                self._event('context_manager', item.context_expr, source.sources, [],
                            label=f'enter {_short(_text(item.context_expr))}', certainty='possible')
                if item.optional_vars:
                    self._assign(item.optional_vars, _Value(source.sources), node)
            self._block(node.body)
            self._gap('context_exit_effect', 'context manager exit effects are not modeled', node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifier = self._node(node.name, 'deferred_definition', node, expression=node.name)
            self._state.names[node.name] = identifier
            self._event('definition', node, [], [identifier], label=f'defined {node.name}; body not traversed')
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]
                identifier = self._node(name, 'import_reference', node, expression=_text(node),
                                        certainty='reference')
                self._state.names[name] = identifier
                self._event('import_reference', node, [], [identifier], label=f'import {name}')
        elif isinstance(node, (ast.Pass, ast.Global, ast.Nonlocal, ast.Break, ast.Continue)):
            if isinstance(node, (ast.Break, ast.Continue)):
                self._gap('loop_control', f'{type(node).__name__.lower()} changes which loop paths continue', node)
        else:
            sources = self._read_sources(node)
            self._event('unsupported_statement', node, sources, [], certainty='possible')
            self._gap('unsupported_statement', f'{type(node).__name__} data effects are not modeled', node)

    def _model_fields(self, class_scope: dict[str, Any], seen: set[str]) -> list[dict[str, Any]]:
        if class_scope['id'] in seen:
            return []
        seen.add(class_scope['id'])
        tree = self._parse(class_scope['file'])
        node = self._find_node(tree, class_scope)
        if not isinstance(node, ast.ClassDef):
            return []
        owner = class_scope['qualified']
        fields = []
        for statement in node.body:
            targets: list[ast.AST] = []
            annotation = None
            default = None
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
                annotation = _text(statement.annotation)
                default = _text(statement.value) if statement.value is not None else None
            elif isinstance(statement, ast.Assign):
                targets = statement.targets
                default = _text(statement.value)
            elif isinstance(statement, (_FUNCTIONS)) and statement.name == '__init__':
                for child in ast.walk(statement):
                    if isinstance(child, (ast.Assign, ast.AnnAssign)):
                        inner = child.targets if isinstance(child, ast.Assign) else [child.target]
                        for target in inner:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                fields.append({'name': target.attr, 'annotation': _text(child.annotation) if isinstance(child, ast.AnnAssign) else None,
                                               'default': _text(child.value) if child.value is not None else None,
                                               'owner': owner, 'span': self._span(child, class_scope['file']),
                                               'kind': 'instance_assignment'})
            for target in targets:
                if isinstance(target, ast.Name):
                    fields.append({'name': target.id, 'annotation': annotation, 'default': default,
                                   'owner': owner, 'span': self._span(statement, class_scope['file']),
                                   'kind': 'declaration'})
        for base in node.bases:
            candidates = self._class_index.get(_text(base), [])
            if len(candidates) == 1:
                fields.extend(self._model_fields(candidates[0], seen))
        return fields

    def _models(self) -> None:
        referenced = set()
        dotted: set[str] = set()
        owner = self.model['scopes'].get(self.scope.get('parent'))
        if owner and owner['kind'] == 'class':
            referenced.add(owner['qualified'])
            if self._owner_declarations is None:
                self._owner_declarations = self._model_fields(owner, set())
            for field_row in self._owner_declarations:
                annotation = field_row.get('annotation') or ''
                referenced.update(part for part in
                                  annotation.replace('[', ' ').replace(']', ' ').replace('|', ' ').replace(',', ' ').split()
                                  if part.isidentifier())
        for node in ast.walk(self.method):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                referenced.add(node.id)
            if isinstance(node, ast.Attribute):
                dotted.add(_text(node))
        for param in self.scope['params']:
            annotation = param.get('annotation')
            if annotation:
                referenced.update(part for part in annotation.replace('[', ' ').replace(']', ' ').replace('|', ' ').replace(',', ' ').split()
                                  if part.isidentifier())
        for name in sorted(referenced | dotted):
            self._check_time()
            if owner and owner['kind'] == 'class' and name == owner['qualified']:
                imported = None
                candidates = [owner['id']]
            elif '.' in name:
                prefix, suffix = name.split('.', 1)
                imported = f'{self._imports[prefix]}.{suffix}' if prefix in self._imports else None
                candidates = _unique([scope['id'] for scope in
                                      self._class_index.get(imported or name, [])])
            else:
                imported = self._imports.get(name)
                candidates = _unique([scope['id'] for scope in
                                      self._class_index.get(imported or name, [])])
            if len(candidates) > 1:
                self._gap('ambiguous_model', f'{name} has multiple indexed class definitions', self.method)
            if candidates:
                for scope_id in candidates:
                    self.model_total += 1
                    if self.model_total <= self.model_offset or len(self.models) >= self.max_models:
                        continue
                    class_scope = self.model['scopes'][scope_id]
                    class_node = self._find_node(self._parse(class_scope['file']), class_scope)
                    bases = []
                    if isinstance(class_node, ast.ClassDef):
                        for base in class_node.bases:
                            rows = self._class_index.get(_text(base), [])
                            bases.append({'expression': _text(base),
                                          'scope': rows[0]['id'] if len(rows) == 1 else None,
                                          'span': self._span(base, class_scope['file'])})
                    fields = self._model_fields(class_scope, set())
                    allowed = max(0, min(MAX_FIELDS_PER_MODEL, MAX_TOTAL_FIELDS - self._field_count))
                    omitted_fields = max(0, len(fields) - allowed)
                    if omitted_fields:
                        self._truncated = True
                        self._omitted += omitted_fields
                        self._gap('model_field_limit',
                                  f'{omitted_fields} fields of {class_scope["qualified"]} omitted by response budget; open class source',
                                  class_node or self.method, class_scope['span'])
                    fields = fields[:allowed]
                    self._field_count += len(fields)
                    self.models.append({'id': scope_id, 'name': name,
                                        'qualified': class_scope['qualified'],
                                        'file': class_scope['file'], 'span': class_scope['span'],
                                        'fields': fields, 'fieldsTruncated': bool(omitted_fields),
                                        'omittedFields': omitted_fields,
                                        'bases': bases, 'status': 'indexed' if len(candidates) == 1 else 'possible'})
            elif (imported and name.rsplit('.', 1)[-1][:1].isupper()
                  and not ('.' in name and self._imports.get(name.split('.', 1)[0])
                           in self._class_index)):
                self.model_total += 1
                if self.model_total <= self.model_offset or len(self.models) >= self.max_models:
                    continue
                self.models.append({'id': f'external:{imported}', 'name': name,
                                    'qualified': imported, 'file': None,
                                    'span': None, 'fields': [], 'bases': [], 'status': 'external'})
        end = self.model_offset + len(self.models)
        self.next_model_offset = end if end < self.model_total else None

    def _templates(self) -> None:
        """Connect literal context names to retained template text as possible uses.

        Jinja syntax is kept as source text. Lexical matches are possibilities,
        not proof that a template branch ran or that the variable was rendered.
        """
        field_nodes = {row['name']: row['id'] for row in self.nodes if row['kind'] == 'field'}
        assets = self.model.get('templateAssets', {})
        use_count = 0
        for link in self.model.get('templateLinks', []):
            if link.get('scope') != self.scope['id']:
                continue
            self._check_time()
            if len(self.templates) >= MAX_TEMPLATE_LINKS:
                self._truncated = True
                self._omitted += 1
                self._gap('template_link_limit', 'additional template links omitted by response budget', self.method)
                return
            row = {'name': link.get('name'), 'status': link.get('status', 'unresolved'),
                   'span': link.get('span'), 'contextKeys': list(link.get('contextKeys', [])),
                   'candidates': list(link.get('candidates', [])), 'uses': [],
                   'clientFetches': list(link.get('clientFetches', []))[:128]}
            self.templates.append(row)
            if row['status'] != 'matched' or len(row['candidates']) != 1:
                continue
            span = link['span']
            site = (span['start'], span['col'], span['end'], span['endCol'])
            context_nodes = self._template_context_nodes.get(site, {})
            context_fields = self._template_context_fields.get(site, {})
            asset = assets.get(row['candidates'][0], {})
            aliases: dict[str, str] = {}
            for use in asset.get('uses', []):
                self._check_time()
                if use_count >= MAX_TEMPLATE_USES:
                    row['usesTruncated'] = True
                    self._truncated = True
                    self._omitted += 1
                    self._gap('template_use_limit', 'additional template uses omitted by response budget', self.method)
                    return
                use_count += 1
                expression = use['expression']
                loop = re.search(r'\bfor\s+(\w+)\s+in\s+(\w+)', expression)
                if loop and loop.group(2) in context_nodes:
                    aliases[loop.group(1)] = loop.group(2)
                sources = []
                linked = [item for item in link.get('contextUses', [])
                          if item.get('expression') == expression and item.get('span') == use['span']]
                for item in linked:
                    identifier = context_nodes.get(item.get('contextKey'))
                    if identifier:
                        sources.append(identifier)
                for key, identifier in context_nodes.items():
                    if re.search(rf'\b{re.escape(key)}\b', expression):
                        sources.append(identifier)
                for alias, key in aliases.items():
                    if re.search(rf'\b{re.escape(alias)}\b', expression):
                        sources.append(context_nodes[key])
                for context_key, fields in context_fields.items():
                    for field_name, identifier in fields.items():
                        if _references_context_field(expression, context_key, field_name):
                            sources.append(identifier)
                for field_name, identifier in field_nodes.items():
                    if re.search(rf'(?<!\w){re.escape(field_name)}\b', expression):
                        sources.append(identifier)
                use_row = {'expression': expression, 'span': use['span'],
                           'sourceNodes': _unique(sources), 'certainty': 'possible'}
                row['uses'].append(use_row)
                if not sources:
                    continue
                marker = ast.Constant(value=expression)
                target = self._node(_short(expression, 80), 'template_use', marker,
                                    expression=expression, certainty='possible',
                                    span=use['span'])
                self._event('template_use', marker, _unique(sources), [target],
                            label=f'template uses {_short(expression, 90)}',
                            certainty='possible', span=use['span'],
                            details={'template': row['candidates'][0],
                                     'boundary': 'lexical template reference; rendering is not proven'})
            if not row['clientFetches']:
                row['clientFetches'] = list(asset.get('clientFetches', []))[:128]

    def build(self) -> dict[str, Any]:
        args = getattr(self.method, 'args', None)
        parameter_nodes: dict[str, ast.arg] = {}
        defaults: dict[str, ast.expr] = {}
        if args:
            positional = args.posonlyargs + args.args
            for item in positional + args.kwonlyargs:
                parameter_nodes[item.arg] = item
            for item in (args.vararg, args.kwarg):
                if item:
                    parameter_nodes[item.arg] = item
            for item, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                defaults[item.arg] = default
            for item, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    defaults[item.arg] = default
        try:
            for parameter in self.scope['params']:
                name = parameter['name']
                node = parameter_nodes.get(name, self.method)
                object_id = self._object()
                identifier = self._node(name, 'parameter', node,
                                        expression=name, annotation=parameter.get('annotation'),
                                        object_id=object_id)
                default = defaults.get(name)
                if default is not None:
                    self._node_by_id[identifier]['default'] = _text(default)
                    dependency = (isinstance(default, ast.Call) and
                                  isinstance(default.func, ast.Name) and
                                  self._imports.get(default.func.id) in
                                  ('fastapi.Depends', 'fastapi.Security'))
                    self._node_by_id[identifier]['inputKind'] = ('framework_dependency'
                                                                  if dependency else 'default_expression')
                    if dependency and default.args:
                        self._node_by_id[identifier]['declaredProvider'] = _text(default.args[0])
                self._state.names[name] = identifier
                self._state.objects[object_id] = identifier
            if isinstance(self.method, ast.Lambda):
                value = self._eval(self.method.body)
                output = self._node('return', 'output', self.method.body,
                                    expression=_text(self.method.body), object_id=value.object_id)
                self._event('return', self.method.body, value.sources, [output])
            else:
                self._block(self.method.body)
            self._models()
            self._templates()
        except _LimitReached:
            self._gap('analysis_limit', 'method flow stopped at the analysis budget', self.method)
        return {'schemaVersion': SCHEMA_VERSION,
                'scope': {'id': self.scope['id'], 'name': self.scope['qualified'],
                          'file': self.file, 'span': self.scope['span'],
                          'params': self.scope['params'], 'output': self.scope['output']},
                'nodes': self.nodes, 'events': self.events, 'edges': self.edges,
                'models': self.models, 'templates': self.templates,
                'modelTotal': self.model_total, 'nextModelOffset': self.next_model_offset,
                'gaps': self.gaps, 'trace': None,
                'truncated': self._truncated, 'omitted': self._omitted}


def _trace(result: dict[str, Any], node_id: str, direction: str) -> dict[str, Any]:
    ids = {row['id'] for row in result['nodes']}
    if node_id not in ids:
        raise ValueError(f'unknown data-flow node: {node_id}')
    if direction not in ('upstream', 'downstream', 'both'):
        raise ValueError('direction must be upstream, downstream, or both')
    selected = {node_id}
    used_edges = set()
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        for edge in result['edges']:
            follow = ((edge['to'] == current and direction in ('upstream', 'both')) or
                      (edge['from'] == current and direction in ('downstream', 'both')))
            if not follow:
                continue
            other = edge['from'] if edge['to'] == current else edge['to']
            used_edges.add(edge['id'])
            if other not in selected:
                selected.add(other)
                queue.append(other)
    result['trace'] = {'nodeId': node_id, 'direction': direction,
                       'nodeIds': [row['id'] for row in result['nodes'] if row['id'] in selected],
                       'eventIds': [row['id'] for row in result['events'] if row['id'] in selected],
                       'edgeIds': [row['id'] for row in result['edges'] if row['id'] in used_edges]}
    return result


def build_dataflow(model: dict[str, Any], scope_id: str, *, node_id: str | None = None,
                   direction: str = 'both', max_events: int = 400,
                   max_edges: int = 800, max_models: int = 80,
                   model_offset: int = 0) -> dict[str, Any]:
    """Build a deterministic method graph from retained source, never target execution.

    IDs are stable for a given snapshot and budget. An optional node trace marks
    reachable graph records; callers may page the overview or selected trace.
    """
    if not (1 <= max_events <= 2000 and 1 <= max_edges <= 4000 and 1 <= max_models <= 300):
        raise ValueError('data-flow budgets are outside supported bounds')
    if model_offset < 0:
        raise ValueError('model_offset must be zero or greater')
    if direction not in ('upstream', 'downstream', 'both'):
        raise ValueError('direction must be upstream, downstream, or both')
    result = _Builder(model, scope_id, max_events, max_edges, max_models, model_offset).build()
    return _trace(result, node_id, direction) if node_id is not None else result
