'use strict';
// The review: the selected method's code with a one-line summary. Names highlight
// their uses; project calls, tests, and callers open beside the code; referenced
// models show as source.
// rendered: the snapshot and method whose view is complete, so selecting it again does not redraw it.
const codeFirst = {request: 0, scope: null, highlight: null, beside: null, lineMarks: new Map(), rendered: null};

// Calls resolved to this repository.
function projectCalls(data) {
  return flowItems(data.events).filter(event => event.kind === 'call' && usableFlowSpan(event.span) &&
    ['supported', 'possible'].includes(event.details?.callStatus) && event.details?.targets?.length);
}
function calleeName(event) {
  return String(event.label || '').replace(/^call /, '') || String(event.expression || '').split('(')[0];
}
// The methods a method calls: the analyzer's complete list, or, from a server or saved review that predates it,
// the calls the flow view lays out.
function calleesFrom(overview, calls, id) {
  if (overview?.callees) return overview.callees;
  const seen = new Map();
  for (const call of calls) {
    const target = call.details.targets[0];
    if (target !== id && !seen.has(target)) seen.set(target, call);
  }
  const items = [...seen].map(([target, call]) => {
    const info = model.scopes[target];
    return {id: target, name: info?.qualified || calleeName(call), file: info?.file || '', line: info?.span.start || 0,
      callLine: call.span.start, status: call.details.callStatus};
  });
  return {items, total: items.length};
}
function isCallable(scope) {
  return !['module', 'class'].includes(scope.kind);
}

async function renderCodeFirst(id) {
  const request = ++codeFirst.request, captured = model, scope = captured.scopes[id];
  const code = $('#cfCode'), summary = $('#cfSummary'), context = $('#cfContext');
  if (codeFirst.scope !== id) { codeFirst.highlight = null; codeFirst.beside = null; }
  codeFirst.scope = id; codeFirst.rendered = null;
  $('#methodWhere').replaceChildren(`${scope.file}:${scope.span.start} · `, el('span', 'cf-kind', `${scope.async ? 'async ' : ''}${scope.kind}`));
  if (window.threadlineHost) $('#methodWhere').append(button('Open in editor', 'quiet-button', () => window.threadlineHost.openSource({snapshot:captured.snapshotId,file:scope.file,line:scope.span.start})));
  summary.replaceChildren(el('p', 'source-peek', 'Reading…'));
  code.replaceChildren(el('p', 'source-peek', 'Loading code…'));
  context.replaceChildren();
  try {
    if (!isCallable(scope)) {
      summary.replaceChildren(el('p', 'source-peek', scope.kind === 'module' ? 'Module body: code that runs when the module is imported or run.' : 'Class body.'));
      renderReviewNav(id);
      await renderScopeSource(code, scope, scope.span.start, request);
      if (request === codeFirst.request) { renderContext(context, null, id); codeFirst.rendered = captured.snapshotId + '|' + id; }
      return;
    }
    const [source, data, overview] = await Promise.all([boundedMethodLines(id, captured.snapshotId), getFlowOverview(id, captured), overviewOf(id, captured).catch(() => null)]);
    if (request !== codeFirst.request || captured !== model || state.scope !== id) return;
    const calls = projectCalls(data);
    renderCodeLines(code, source.rows, calls);
    renderSummary(summary, scope, data, calls, calleesFrom(overview, calls, id));
    renderContext(context, data, id);
    renderReviewNav(id, calls);
    if (codeFirst.highlight) highlightName(codeFirst.highlight, false);
    if (codeFirst.beside) openBeside(codeFirst.beside, false);
    codeFirst.rendered = captured.snapshotId + '|' + id;
  } catch (error) {
    if (request !== codeFirst.request || captured !== model) return;
    code.replaceChildren(el('p', 'error', 'Code unavailable: ' + error.message),
      button('Retry', 'quiet-button', () => renderCodeFirst(id)));
  }
}

// Module and class bodies can be long: 200 lines at a time.
async function renderScopeSource(host, scope, start, request) {
  const captured = model, end = Math.min(scope.span.end, start + 199);
  const page = await api('/api/source', {snapshot: captured.snapshotId, file: scope.file, start, end});
  if (request !== codeFirst.request || captured !== model) return;
  if (start === scope.span.start) host.replaceChildren();
  host.querySelector('.cf-more')?.remove();
  page.source.split('\n').forEach((text, index) => host.append(codeLine(start + index, text)));
  if (end < scope.span.end) {
    host.append(button('Show more lines', 'quiet-button cf-more', () => renderScopeSource(host, scope, end + 1, request)));
  }
}

function renderCodeLines(host, rows, calls) {
  const byLine = new Map();
  for (const call of calls) {
    if (!byLine.has(call.span.start)) byLine.set(call.span.start, []);
    byLine.get(call.span.start).push(call);
  }
  host.replaceChildren();
  let defined = false;
  for (const row of rows) {
    const line = codeLine(row.number, row.text);
    // The definition line carries the accent bar, as the decorator lines above it do not.
    if (!defined && /^\s*(async\s+)?def\s/.test(row.text)) { defined = true; line.classList.add('cf-def-line'); }
    markNames(line.querySelector('.line-content'), row.text, byLine.get(row.number) || []);
    host.append(line);
  }
}

// Wraps identifiers outside strings and comments; project calls become buttons.
function markNames(content, text, calls) {
  const links = new Map();
  for (const call of calls) {
    const last = calleeName(call).split('.').pop().replace(/[^\w]/g, '');
    if (!last) continue;
    const pattern = new RegExp('\\b' + last + '\\s*\\(', 'g');
    pattern.lastIndex = call.span.col || 0;
    const found = pattern.exec(text);
    if (found && !links.has(found.index)) links.set(found.index, call);
  }
  let column = 0;
  const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
  const pieces = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) { pieces.push([node, column]); column += node.textContent.length; }
  for (const [node, start] of pieces) {
    if (node.parentElement.matches('.tok-str, .tok-comment, .tok-key, .tok-num')) continue;
    const value = node.textContent, fragment = document.createDocumentFragment();
    let last = 0;
    for (const match of value.matchAll(/[A-Za-z_]\w*/g)) {
      fragment.append(value.slice(last, match.index));
      const at = start + match.index, name = match[0];
      const attribute = text[at - 1] === '.';
      const call = links.get(at);
      let token;
      if (call) {
        const target = call.details.targets[0];
        token = button(name, 'cf-name cf-call', () => openCall(target));
        token.title = 'Open ' + calleeName(call) + ' beside the code';
        token.dataset.target = target;
      } else if (attribute) {
        token = el('span', /^\s*\(/.test(text.slice(at + name.length)) ? 'cf-attr cf-fn' : 'cf-attr', name);
      } else {
        token = el('span', 'cf-name', name);
        const following = text.slice(at + name.length);
        // Calls read as functions, Capitalized names as classes, and the name after def as the definition.
        if (/^\s*\(/.test(following)) token.classList.add(/\b(?:def|class)\s+$/.test(text.slice(0, at)) ? 'cf-def' : 'cf-fn');
        else if (/^[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*$/.test(name)) token.classList.add('cf-cls');
        token.addEventListener('click', () => highlightName(name));
      }
      if (!attribute) {
        token.dataset.name = name;
        const after = text.slice(at + name.length), before = text.slice(0, at);
        if (/^\s*(=(?!=)|[-+*/%@&|^]=|:\s*[^=\s])/.test(after) && !/[(,]\s*$/.test(before) || /\b(for|as)\s+$/.test(before))
          token.classList.add('cf-write');
      }
      fragment.append(token);
      last = match.index + name.length;
    }
    fragment.append(value.slice(last));
    node.replaceWith(fragment);
  }
}

function clearCodeMarks() {
  const code = $('#cfCode');
  code.querySelectorAll('.cf-hit').forEach(item => item.classList.remove('cf-hit'));
  code.querySelectorAll('.cf-hit-line, .cf-focus-line').forEach(item => item.classList.remove('cf-hit-line', 'cf-focus-line'));
}
function highlightName(name, toggle = true) {
  const code = $('#cfCode');
  if (toggle && codeFirst.highlight === name) name = null;
  codeFirst.highlight = name;
  clearCodeMarks();
  $('#cfSummary').querySelectorAll('.cf-chip[aria-pressed]').forEach(chip => chip.setAttribute('aria-pressed', String(chip.dataset.name === name)));
  if (!name) { announce('Highlight cleared.'); return; }
  if (codeFirst.lineMarks.has(name)) {
    const wanted = codeFirst.lineMarks.get(name);
    const lines = [...code.querySelectorAll('.code-line')].filter(line => wanted.has(Number(line.dataset.line)));
    lines.forEach(line => line.classList.add('cf-hit-line'));
    announce(`${lines.length} ${lines.length === 1 ? 'line' : 'lines'}.`);
    return;
  }
  if (name === 'return') {
    const lines = [...code.querySelectorAll('.code-line')].filter(line => /^\s*(return|yield)\b/.test(line.querySelector('.line-content').textContent));
    lines.forEach(line => line.classList.add('cf-hit-line'));
    announce(`${lines.length} return ${lines.length === 1 ? 'statement' : 'statements'}.`);
    return;
  }
  const hits = [...code.querySelectorAll('[data-name]')].filter(item => item.dataset.name === name);
  for (const hit of hits) { hit.classList.add('cf-hit'); hit.closest('.code-line').classList.add('cf-hit-line'); }
  const writes = hits.filter(hit => hit.classList.contains('cf-write')).length;
  announce(`${name}: ${hits.length} ${hits.length === 1 ? 'use' : 'uses'}${writes ? `, ${writes} assigned` : ''}.`);
}

function chip(label, handler, title = '') {
  const item = button(label, 'cf-chip', handler);
  if (title) item.title = title;
  return item;
}
function renderSummary(host, scope, data, calls, callees) {
  host.replaceChildren();
  const group = (label, items, empty) => {
    const row = el('div', 'cf-group');
    row.dataset.kind = label.toLowerCase();
    row.append(el('span', 'cf-label', label));
    if (items.length) row.append(...items); else row.append(el('span', 'cf-none', empty));
    host.append(row);
    return row;
  };
  // key names what the chip highlights: a name in the code, or a set of lines in codeFirst.lineMarks.
  const nameChip = (name, title, key = name) => {
    const item = chip(name, () => highlightName(key), title);
    item.dataset.name = key; item.setAttribute('aria-pressed', 'false');
    return item;
  };
  const lineChip = (name, title, key, lines) => {
    codeFirst.lineMarks.set(key, lines);
    return nameChip(name, title, key);
  };
  codeFirst.lineMarks = new Map();
  const params = scope.params.filter(param => !['self', 'cls'].includes(param.name));
  group('In', params.map(param => {
    const provided = /^Depends\(/.test(param.default || '');
    const item = nameChip(param.name, (param.annotation || '') + (provided ? ' · provided by the framework' : ''));
    if (provided) item.classList.add('cf-provided');
    return item;
  }), 'nothing');
  // The methods this one calls come from the analyzer's complete list, not only the calls the flow view lays out.
  const projectChips = callees.items.map(row => {
    const item = chip(row.name, () => openCall(row.id), 'Open beside the code');
    item.dataset.target = row.id;
    if (row.status === 'possible') { item.classList.add('cf-possible'); item.title = 'Probably calls this; open beside the code'; }
    return item;
  });
  // Calls on what the method receives, such as repository.save(order) or db.commit(), are often its
  // real side effects: library methods on a typed receiver, or targets that cannot be told from source.
  // Builtin-typed parameters and string methods such as email.strip() are not collaborators.
  const builtin = /^(Optional\[)?(str|int|float|bool|bytes|list|dict|set|tuple|frozenset|Decimal)\b/;
  const received = new Set(scope.params.filter(param => !builtin.test(param.annotation || '')).map(param => param.name));
  const readOnly = new Set(['strip', 'lstrip', 'rstrip', 'lower', 'upper', 'split', 'join', 'startswith', 'endswith',
    'replace', 'format', 'encode', 'decode']);
  const unresolved = new Map();
  for (const call of flowItems(data.events)) {
    if (call.kind !== 'call' || !['unknown', 'external'].includes(call.details?.callStatus) || !usableFlowSpan(call.span)) continue;
    const name = calleeName(call), parts = name.split('.');
    if (!/^\w+(\.\w+)+$/.test(name) || !received.has(parts[0]) || readOnly.has(parts.at(-1))) continue;
    if (!unresolved.has(name)) unresolved.set(name, {lines: new Set(), call});
    unresolved.get(name).lines.add(call.span.start);
  }
  const receivedChips = [...unresolved].map(([name, {lines, call}]) => {
    const library = call.details.callStatus === 'external';
    const target = String(call.details.callReason || '').split('outside index: ')[1];
    const title = library ? `Library call${target ? ': ' + target : ''}. Highlight the line.`
      : `Can't tell which method this calls: ${name.split('.')[0]} is passed in. Highlight the line.`;
    const item = lineChip(name, title, 'call:' + name, lines);
    if (!library) item.classList.add('cf-possible');
    return item;
  });
  group('Calls', capChips([...projectChips, ...receivedChips], 14), 'no project functions');
  // A name is a definite change if any write to it is; otherwise it is only a possible effect.
  // self and cls keep their attribute (self.items); a chip for those highlights the changing lines.
  const changed = new Map();
  for (const node of flowNodes(data).filter(node => ['object_state', 'field'].includes(node.kind))) {
    const parts = String(node.name).split('.');
    const name = ['self', 'cls'].includes(parts[0]) && parts.length > 1 ? parts.slice(0, 2).join('.') : parts[0];
    if (!/^[A-Za-z_]\w*(\.[A-Za-z_]\w*)?$/.test(name)) continue;
    const possible = node.certainty === 'possible';
    const entry = changed.get(name) || {possible: node, lines: new Set()};
    if (!possible) entry.possible = null;
    if (usableFlowSpan(node.span)) entry.lines.add(node.span.start);
    changed.set(name, entry);
  }
  group('Changes', [...changed].map(([name, {possible, lines}]) => {
    const title = possible ? `May change: ${possible.expression}` : 'Highlight where it is used and changed';
    const item = name.includes('.') ? lineChip(name, title, 'change:' + name, lines) : nameChip(name, title);
    if (possible) item.classList.add('cf-possible');
    return item;
  }), 'nothing it receives');
  renderEffects(group, lineChip, scope.sideEffects || []);
  const output = scope.output || {};
  const returned = output.responseModel && output.responseModel !== 'None' ? output.responseModel : output.annotation ||
    (output.returns?.length ? [...new Set(output.returns)].join(' | ') : '');
  group('Returns', returned ? [chip(returned, () => highlightName('return'), 'Highlight return statements')] : [], 'nothing explicit');
  const raised = new Map();
  for (const event of flowItems(data.events).filter(event => event.kind === 'raise' && usableFlowSpan(event.span))) {
    const expression = String(event.expression || '').replace(/^raise\b\s*/, '');
    const name = expression ? expression.split(/[\s(]/)[0] : 're-raise';
    if (!raised.has(name)) raised.set(name, new Set());
    raised.get(name).add(event.span.start);
  }
  // Exceptions raised by called project functions follow the ones raised here.
  const inherited = new Map();
  for (const effect of (scope.sideEffects || []).filter(effect => effect.effect === 'raises' && effect.via.length && !raised.has(effect.detail))) {
    if (!inherited.has(effect.detail)) inherited.set(effect.detail, effect);
  }
  const raisedChips = [...raised].map(([name, lines]) => lineChip(name, 'Highlight where it is raised', 'raise:' + name, lines));
  const inheritedChips = [...inherited.values()].map(effect => effectChip(`${effect.detail} via ${shortName(effect.via[0])}`, [effect], null));
  if (raised.size || inherited.size) group('Raises', capChips([...raisedChips, ...inheritedChips], 8), '');
}

// Effects: what the method does outside the program, directly or through the project code it calls.
const EFFECT_ORDER = ['db write', 'db read', 'db access', 'network write', 'network read', 'network access',
  'file write', 'file read', 'file access', 'process', 'logging'];
const EFFECT_LABELS = {'db write': 'DB write', 'db read': 'DB read', 'db access': 'DB access',
  'network write': 'network write', 'network read': 'network read', 'network access': 'network',
  'file write': 'file write', 'file read': 'file read', 'file access': 'file access',
  'process': 'runs process', 'logging': 'logging'};
function shortName(qualified) {
  return String(qualified).split('.').slice(-2).join('.');
}
function effectSource(effect) {
  const where = effect.via.length ? 'via ' + effect.via.join(' → ') : `${effect.call || 'raise'} (line ${effect.lines.join(', ')})`;
  return `${where}${effect.library ? ' · ' + effect.library : ''}${effect.certainty === 'possible' ? ' · possible' : ''}`;
}
function effectChip(label, effects, lineKey, lineChip) {
  const direct = effects.filter(effect => !effect.via.length);
  const title = effects.slice(0, 8).map(effectSource).join('\n') + (effects.length > 8 ? `\n+${effects.length - 8} more` : '');
  let item;
  if (direct.length && lineKey && lineChip) {
    item = lineChip(label, title, lineKey, new Set(direct.flatMap(effect => effect.lines)));
  } else {
    const through = effects.find(effect => effect.through)?.through;
    item = chip(label, () => through && openCall(through), title);
  }
  if (!effects.some(effect => effect.certainty === 'definite')) item.classList.add('cf-possible');
  return item;
}
function capChips(chips, limit) {
  if (chips.length <= limit) return chips;
  const more = el('span', 'cf-none', `+${chips.length - limit} more`);
  more.title = chips.slice(limit).map(item => item.textContent).join('\n');
  return [...chips.slice(0, limit), more];
}
function renderEffects(group, lineChip, effects) {
  const byEffect = new Map();
  for (const effect of effects.filter(effect => effect.effect !== 'raises')) {
    if (!byEffect.has(effect.effect)) byEffect.set(effect.effect, []);
    byEffect.get(effect.effect).push(effect);
  }
  const chips = EFFECT_ORDER.filter(name => byEffect.has(name)).map(name => {
    const found = byEffect.get(name), direct = found.some(effect => !effect.via.length);
    const hops = [...new Set(found.filter(effect => effect.via.length).map(effect => effect.via[0]))];
    const label = EFFECT_LABELS[name] + (direct ? '' : hops.length === 1 ? ` via ${shortName(hops[0])}` : ` via ${hops.length} calls`);
    return effectChip(label, found, 'effect:' + name, lineChip);
  });
  const empty = el('span', 'cf-none', 'none found');
  empty.title = 'Only known library calls are recognized: databases, HTTP, files, processes, and logging.';
  const row = group('Effects', chips, '');
  if (!chips.length) row.querySelector('.cf-none').replaceWith(empty);
}

// Right side: whatever is opened beside the code, then tests, callers, and models.
function renderContext(host, data, id) {
  host.replaceChildren();
  const beside = el('section', 'cf-beside'); beside.id = 'cfBeside'; beside.hidden = true;
  host.append(beside);
  if (isCallable(model.scopes[id])) {
    const tests = el('section', 'cf-section'); tests.id = 'cfTests';
    const callers = el('section', 'cf-section'); callers.id = 'cfCallers';
    host.append(tests, callers);
    loadTestList(tests, id);
    loadCallerList(callers, id);
  }
  if (data) {
    const models = el('section', 'cf-section cf-models');
    models.append(el('h2', '', 'Models'));
    const list = el('div'); models.append(list);
    host.append(models);
    renderDataModels(data, list, id, null, true);
  }
}

// A drawer heading: the title, then its count as a pill.
function cfHeading(title, count) {
  const heading = el('h2', '', title + (count === undefined ? '' : ' '));
  if (count !== undefined) heading.append(el('span', 'cf-count', String(count)));
  return heading;
}
function listRow(label, place, detail, open) {
  const row = button('', 'cf-row', open);
  row.append(el('code', 'cf-row-name', label), el('span', 'cf-row-place', place));
  if (detail) row.append(el('span', 'cf-row-detail', detail));
  return row;
}
async function loadTestList(host, id, cursor = 0) {
  const captured = model;
  if (!cursor) host.replaceChildren(el('h2', '', 'Tests'), el('p', 'source-peek', 'Finding tests…'));
  try {
    const result = await api('/api/tests', {symbol: id, snapshot: captured.snapshotId, cursor, limit: 20});
    if (captured !== model || state.scope !== id || !host.isConnected) return;
    const page = result.items, isTest = result.role === 'test';
    if (!cursor) {
      host.replaceChildren(cfHeading(isTest ? 'Code this test reaches' : 'Tests', page.total));
      if (!page.total) host.append(el('p', 'source-peek', isTest ? 'No linked code found.'
        : result.testCount ? 'No test reaches this method through calls, routes, or names.'
        : 'No tests found. If tests live outside the analyzed folders, include them with --source-root.'));
    }
    host.querySelector('.cf-list-more')?.remove();
    for (const row of page.items) {
      host.append(listRow(row.name, `${row.file}:${row.line}`, row.reason + (row.status === 'possible' ? ' · probably' : ''),
        () => openBeside({id: row.id, title: row.name, focus: isTest ? null : row.callsite, kind: isTest ? 'Code under test' : 'Test'})));
    }
    if (page.nextCursor !== null) host.append(button('More tests', 'quiet-button cf-list-more', () => loadTestList(host, id, page.nextCursor)));
  } catch (error) {
    if (captured === model && host.isConnected) host.replaceChildren(el('h2', '', 'Tests'), el('p', 'error', error.message),
      button('Retry', 'quiet-button', () => loadTestList(host, id, cursor)));
  }
}
async function loadCallerList(host, id, cursor = 0) {
  const captured = model;
  if (!cursor) host.replaceChildren(el('h2', '', 'Callers'), el('p', 'source-peek', 'Finding callers…'));
  try {
    const result = await api('/api/overview', {symbol: id, snapshot: captured.snapshotId, cursor, limit: 20});
    if (captured !== model || state.scope !== id || !host.isConnected) return;
    const page = result.callers;
    if (!cursor) {
      host.replaceChildren(cfHeading('Callers', page.total));
      if (!page.total) host.append(el('p', 'source-peek', 'Nothing in the analyzed source calls this directly. Routes, commands, and callbacks are called by frameworks.'));
    }
    host.querySelector('.cf-list-more')?.remove();
    for (const row of page.items) {
      host.append(listRow(row.name, `${row.file}:${row.callsite.start}`, row.status === 'possible' ? 'probably' : '',
        () => openBeside({id: row.id, title: row.name, focus: row.callsite, kind: 'Caller'})));
    }
    if (page.nextCursor !== null) host.append(button('More callers', 'quiet-button cf-list-more', () => loadCallerList(host, id, page.nextCursor)));
  } catch (error) {
    if (captured === model && host.isConnected) host.replaceChildren(el('h2', '', 'Callers'), el('p', 'error', error.message),
      button('Retry', 'quiet-button', () => loadCallerList(host, id, cursor)));
  }
}

function openCall(target) {
  $('#cfCode').querySelectorAll('.cf-call').forEach(item => item.classList.toggle('cf-active', item.dataset.target === target));
  openBeside({id: target, kind: 'Called'});
}
// item: {id} for a definition, or {span} for a source excerpt; focus marks lines.
async function openBeside(item, toggle = true) {
  const host = $('#cfBeside');
  if (!host) return;
  const key = item.id || `${item.span?.file}:${item.span?.start}`;
  const same = codeFirst.beside && (codeFirst.beside.id || `${codeFirst.beside.span?.file}:${codeFirst.beside.span?.start}`) === key;
  if (toggle && same && !host.hidden) { closeBeside(); return; }
  codeFirst.beside = item;
  const captured = model;
  host.hidden = false;
  host.replaceChildren(el('p', 'source-peek', 'Loading…'));
  try {
    let title = item.title, place, rows, scope = null;
    if (item.id) {
      scope = await ensureScope(item.id, captured);
      title ||= scope.qualified; place = `${scope.file}:${scope.span.start}`;
      if (isCallable(scope)) rows = (await boundedMethodLines(item.id, captured.snapshotId)).rows;
      else {
        const page = await api('/api/source', {snapshot: captured.snapshotId, file: scope.file, start: scope.span.start, end: Math.min(scope.span.end, scope.span.start + 199)});
        rows = page.source.split('\n').map((text, index) => ({number: scope.span.start + index, text}));
      }
    } else {
      const span = item.span, end = Math.min(span.end, span.start + 199);
      const page = await api('/api/source', {snapshot: item.snapshotId || captured.snapshotId, file: span.file, start: span.start, end});
      place = sourcePlace(span);
      rows = page.source.split('\n').map((text, index) => ({number: span.start + index, text}));
    }
    if (captured !== model || codeFirst.beside !== item) return;
    const head = el('div', 'cf-beside-head');
    if (item.kind) head.append(el('span', 'cf-beside-kind', item.kind));
    head.append(el('h2', '', title), el('span', 'data-model-place', place));
    const actions = el('div', 'cf-beside-actions');
    if (scope && scope.id !== state.scope) actions.append(button('Open →', 'quiet-button', () => enterScope(scope.id, {scope: state.scope, destination: 'the caller'})));
    if (window.threadlineHost) actions.append(button('Open in editor', 'quiet-button', () => window.threadlineHost.openSource({snapshot:item.snapshotId || captured.snapshotId,file:scope?.file || item.span.file,line:scope?.span.start || item.span.start})));
    actions.append(button('Close', 'quiet-button', closeBeside));
    head.append(actions);
    const focus = item.focus;
    const code = el('div', 'data-model-code code-window wrap-code');
    code.setAttribute('role', 'region'); code.setAttribute('aria-label', (title || 'Source') + ' source'); code.tabIndex = 0;
    code.append(...rows.map(row => codeLine(row.number, row.text, Boolean(focus && row.number >= focus.start && row.number <= focus.end))));
    if (item.details) head.append(el('p', 'cf-beside-detail', item.details));
    host.replaceChildren(head, code);
    // Keep the header in view; scroll the bounded code to the marked line.
    $('#cfContext').scrollTop = 0;
    host.scrollIntoView({block: 'nearest'});
    const marked = code.querySelector('.code-line.focus');
    if (marked) code.scrollTop = Math.max(0, marked.offsetTop - code.offsetTop - 40);
    announce(`Showing ${title} beside the code.`);
  } catch (error) {
    if (captured === model && codeFirst.beside === item) host.replaceChildren(el('p', 'error', error.message), button('Close', 'quiet-button', closeBeside));
  }
}
function closeBeside() {
  codeFirst.beside = null;
  const host = $('#cfBeside');
  if (host) { host.hidden = true; host.replaceChildren(); }
  $('#cfCode').querySelectorAll('.cf-active').forEach(item => item.classList.remove('cf-active'));
}

// Source evidence (call-map steps, changes, diagnostics): lines inside the
// selected method are marked in its code; anything else opens beside it.
function showSource(span, title = '', details = '', snapshotId = null) {
  const scope = model?.scopes[state.scope];
  if (!scope || !usableFlowSpan(span)) return;
  const inside = (!snapshotId || snapshotId === model.snapshotId) && span.file === scope.file &&
    span.start >= scope.span.start && span.end <= scope.span.end;
  if (!inside) { openBeside({span, title: title || sourcePlace(span), details, snapshotId, kind: 'Source'}); return; }
  clearCodeMarks();
  const lines = [...$('#cfCode').querySelectorAll('.code-line')].filter(line => {
    const number = Number(line.dataset.line);
    return number >= span.start && number <= span.end;
  });
  lines.forEach(line => line.classList.add('cf-focus-line'));
  lines[0]?.scrollIntoView({block: 'center'});
  announce(`${title ? title + ': ' : ''}line ${span.start}${span.end === span.start ? '' : '–' + span.end}.`);
}

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || event.target.closest?.('input, textarea')) return;
  if (codeFirst.highlight) highlightName(null, false);
  else if (codeFirst.beside) closeBeside();
});

// The divider between the code and the side pane sets the code's share of the width (30–80%).
(() => {
  const splitter = $('#cfSplitter'), body = splitter.parentElement, key = 'threadline-code-width', initial = 60;
  const set = (share, save = false) => {
    share = Math.round(Math.min(80, Math.max(30, share)));
    body.style.setProperty('--cf-code', share + '%');
    splitter.setAttribute('aria-valuenow', String(share));
    splitter.setAttribute('aria-valuetext', `Code ${share}% of the width`);
    if (save) try { localStorage.setItem(key, String(share)); } catch { /* Storage can be blocked. */ }
  };
  let saved = null;
  try { saved = Number(localStorage.getItem(key)); } catch { /* Use the default. */ }
  set(saved || initial);
  const share = event => (event.clientX - body.getBoundingClientRect().left) / body.getBoundingClientRect().width * 100;
  splitter.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add('dragging'); document.body.classList.add('resizing');
  });
  splitter.addEventListener('pointermove', event => { if (splitter.hasPointerCapture(event.pointerId)) set(share(event)); });
  const finish = event => {
    if (!splitter.classList.contains('dragging')) return;
    splitter.classList.remove('dragging'); document.body.classList.remove('resizing');
    set(share(event), true);
  };
  splitter.addEventListener('pointerup', finish);
  splitter.addEventListener('pointercancel', finish);
  splitter.addEventListener('dblclick', () => set(initial, true));
  splitter.addEventListener('keydown', event => {
    const current = Number(splitter.getAttribute('aria-valuenow'));
    const next = {ArrowLeft: current - 5, ArrowRight: current + 5, Home: 30, End: 80, Enter: initial}[event.key];
    if (next === undefined) return;
    event.preventDefault(); set(next, true);
  });
})();


// Review bar: previous and next method in the file, the method that led here, and menus of
// its callers and of the methods it calls.
const reviewNav = {request: 0, previous: null, next: null};
function overviewOf(id, captured = model) {
  captured.overviews ||= new Map();
  if (!captured.overviews.has(id)) {
    const promise = api('/api/overview', {symbol: id, snapshot: captured.snapshotId, cursor: 0, limit: 100});
    captured.overviews.set(id, promise);
    promise.catch(() => captured.overviews.delete(id));
  }
  return captured.overviews.get(id);
}
function navMenu(label, rows, empty, total = rows.length) {
  const box = el('details', 'nav-menu'), head = el('summary', '');
  box.dataset.kind = label.toLowerCase().replace(/\s+/g, '-');
  head.append(el('span', '', label), el('span', 'nav-count', String(total)));
  const list = el('div', 'nav-menu-list');
  if (!rows.length) list.append(el('p', 'source-peek', empty));
  for (const row of rows) {
    const item = listRow(row.name, row.place, row.detail, () => { box.open = false; row.open(); });
    if (row.possible) item.classList.add('cf-possible');
    list.append(item);
  }
  if (total > rows.length) list.append(el('p', 'source-peek', `+${total - rows.length} more in the review`));
  box.append(head, list);
  box.addEventListener('toggle', () => {
    if (!box.open) return;
    document.querySelectorAll('.nav-menu[open]').forEach(other => { if (other !== box) other.open = false; });
    // Keep the list inside the review column, whichever side of the bar the button is on.
    const bounds = ($('.cf-main') || document.body).getBoundingClientRect(), anchor = box.getBoundingClientRect();
    const width = list.getBoundingClientRect().width;
    const left = Math.max(bounds.left + 8, Math.min(anchor.left, bounds.right - width - 8));
    list.style.left = (left - anchor.left) + 'px'; list.style.right = 'auto';
  });
  return box;
}
async function renderReviewNav(id, calls = []) {
  const request = ++reviewNav.request, captured = model, scope = captured.scopes[id], host = $('#reviewNav');
  const stale = () => request !== reviewNav.request || captured !== model || state.scope !== id;
  reviewNav.previous = reviewNav.next = null;
  let siblings = [], callers = [], callersTotal = 0, callees = {items: [], total: 0};
  try {
    let overview = null;
    [siblings, overview] = await Promise.all([methodsInFile(scope.file, captured), isCallable(scope) ? overviewOf(id, captured) : null]);
    if (overview) {
      callers = [...new Map(overview.callers.items.map(row => [row.id, row])).values()];
      callersTotal = overview.callers.total;
      callees = calleesFrom(overview, calls, id);
    }
  } catch { /* The bar shows what it could read. */ }
  if (stale()) return;
  const index = siblings.findIndex(row => row.id === id);
  const previous = index > 0 ? siblings[index - 1] : null, next = siblings[index + 1] || null;
  const go = row => row && chooseScope(row.id);
  reviewNav.previous = previous && (() => go(previous)); reviewNav.next = next && (() => go(next));
  const step = (text, row, none) => {
    const item = button(text, 'quiet-button nav-step', () => go(row));
    if (row) item.title = `${row.name} · line ${row.line}` ; else { item.disabled = true; item.title = none; }
    return item;
  };
  const group = el('div', 'nav-group');
  group.append(step('‹ Previous', previous, 'First method in this file'), step('Next method ›', next, 'Last method in this file'));
  const bar = [group];
  const where = el('span', 'nav-where');
  where.append(el('strong', '', index >= 0 ? `${index + 1} of ${siblings.length}` : `${siblings.length} methods`), ' in ' + scope.file);
  where.title = scope.file;
  bar.push(where);
  // The method you came from comes first: "Called by" when it really calls this one, "Back to" when you went the other way.
  // With no such method, the first caller found in the source.
  const via = state.stack.at(-1)?.scope, first = callers.find(row => row.id !== id);
  if (via && via !== id) {
    const callsThis = callers.some(row => row.id === via);
    const link = button('', 'nav-primary', () => returnToCaller());
    link.append(el('span', '', callsThis ? '↑ Called by ' : '← Back to '), el('code', '', scopeName(via)));
    link.title = callsThis ? 'Go back to the method that called this one' : 'Go back to the method you came from';
    bar.push(link);
  } else if (first) {
    const link = button('', 'nav-primary', () => enterScope(first.id, {destination: 'the caller'}));
    link.append(el('span', '', '↑ Called by '), el('code', '', first.name));
    link.title = 'Open the method that calls this one';
    bar.push(link);
  }
  if (isCallable(scope)) {
    bar.push(navMenu('Called by', callers.filter(row => row.id !== id).map(row => ({
      name: row.name, place: `${row.file}:${row.callsite.start}`, detail: row.status === 'possible' ? 'probably' : '',
      possible: row.status === 'possible', open: () => enterScope(row.id, {destination: 'the caller'})})),
      'Nothing in the analyzed source calls this directly.', callersTotal));
    const called = callees.items.map(row => ({
      name: row.name, place: `${row.file}:${row.line}`,
      detail: `line ${row.callLine}` + (row.status === 'possible' ? ' · probably' : ''),
      possible: row.status === 'possible', open: () => enterScope(row.id, {destination: 'the caller'})}));
    bar.push(navMenu('Calls', called, 'No project methods are called here.', callees.total));
  }
  host.replaceChildren(...bar);
  host.hidden = false;
}
document.addEventListener('click', event => {
  document.querySelectorAll('.nav-menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    const open = document.querySelector('.nav-menu[open]');
    if (open) { open.open = false; open.querySelector('summary').focus(); event.stopImmediatePropagation(); }
    return;
  }
  if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.('input, textarea, select, [contenteditable]')) return;
  if (!state.scope || $('.workspace').classList.contains('choosing') || !$('#comparisonPanel').hidden) return;
  if (event.key === ']' && reviewNav.next) { event.preventDefault(); reviewNav.next(); }
  if (event.key === '[' && reviewNav.previous) { event.preventDefault(); reviewNav.previous(); }
}, true);
