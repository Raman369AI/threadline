'use strict';
// Snapshot-pinned method data: data flow (for calls and changes), model
// definitions shown as source, bounded method lines, and the sidebar toggle.
const dataflowCache = new Map();
const dataflowPending = new Map();
let sidebarCollapsed = false;
function flowItems(page) {
  return Array.isArray(page) ? page : page?.items || [];
}
function flowNodes(data) {
  return Array.isArray(data?.nodes) ? data.nodes : Object.values(data?.nodes || {});
}
function flowModels(data) {
  return Array.isArray(data?.models) ? data.models : Object.values(data?.models || {});
}
function flowKey(id) {
  return model.snapshotId + '|' + id;
}
function usableFlowSpan(span) {
  return span && span.file && Number.isInteger(span.start) && Number.isInteger(span.end);
}
function sourcePlace(span) {
  return usableFlowSpan(span) ? `${span.file}:${span.start}${span.end === span.start ? '' : '–' + span.end}` : 'Source location unavailable';
}
function rememberFlow(key, data) {
  dataflowCache.delete(key);
  dataflowCache.set(key, data);
  while (dataflowCache.size > 8) dataflowCache.delete(dataflowCache.keys().next().value);
}
async function getFlowOverview(id, captured) {
  const key = captured.snapshotId + '|' + id;
  if (dataflowCache.has(key)) return dataflowCache.get(key);
  if (!dataflowPending.has(key)) {
    const pending = fetchCompleteDataflow(id, captured).then(result => {
      rememberFlow(key, result);
      return result;
    }).finally(() => dataflowPending.delete(key));
    dataflowPending.set(key, pending);
  }
  return dataflowPending.get(key);
}
async function fetchCompleteDataflow(id, captured, nodeId = null, direction = 'both') {
  let cursor = 0;
  let result = null;
  while (cursor !== null) {
    const page = await api('/api/dataflow', {
      symbol: id,
      snapshot: captured.snapshotId,
      cursor,
      limit: 100,
      ...(nodeId ? {
        node: nodeId,
        direction
      } : {})
    });
    if (!result) {
      result = page;
    } else {
      result.nodes = mergeById(flowNodes(result), flowNodes(page));
      result.edges = mergeById(result.edges || [], page.edges || []);
      result.gaps = mergeById(result.gaps || [], page.gaps || []);
      result.events = {
        ...page.events,
        items: [...flowItems(result.events), ...flowItems(page.events)]
      };
      result.truncated = result.truncated || page.truncated;
      result.omitted = Math.max(result.omitted || 0, page.omitted || 0);
    }
    cursor = page.events?.nextCursor ?? null;
  }
  return result;
}
function mergeById(a, b) {
  const identity = item => item.id || item.qualified || item.name;
  const found = new Set(a.map(identity));
  return [...a, ...b.filter(item => !found.has(identity(item)))];
}
function renderDataModels(data, host, id, focus = null, inline = false, preserve = false) {
  const currentKey = flowKey(id);
  const sameMethod = host.dataset.scopeKey === currentKey;
  const expanded = new Set([...host.querySelectorAll('.data-model-item[open]')].map(item => item.dataset.modelKey));
  const collapsed = new Set([...host.querySelectorAll('.data-model-item:not([open])')].map(item => item.dataset.modelKey));
  const scrollPane = host.closest('.data-model-pane');
  const scrollTop = scrollPane?.scrollTop || 0;
  host.replaceChildren();
  host.dataset.scopeKey = currentKey;
  const models = flowModels(data);
  const firstUse = new Map();
  for (const node of flowNodes(data)) {
    if (node.kind !== 'model_reference' || !usableFlowSpan(node.span)) continue;
    const position = node.span.start * 10000 + (node.span.col || 0);
    firstUse.set(node.name, Math.min(firstUse.get(node.name) ?? Infinity, position));
  }
  const indexed = models.filter(definition => definition.status !== 'external' && usableFlowSpan(definition.span))
    .map((definition, index) => ({definition, index}))
    .sort((left, right) => {
      const leftUse = firstUse.get(left.definition.name) ?? Infinity;
      const rightUse = firstUse.get(right.definition.name) ?? Infinity;
      return leftUse === rightUse ? left.index - right.index : leftUse - rightUse;
    })
    .map(item => item.definition);
  const modelTotal = data.modelTotal ?? models.length;
  if (!indexed.length) host.append(el('p', 'source-peek', 'No models referenced.'));
  for (const [index, definition] of indexed.entries()) {
    const item = el('details', 'data-model-item');
    const key = item.dataset.modelKey = definition.id || definition.name;
    const match = focus && (focus === definition.id || focus === definition.name || focus === definition.qualified || String(focus).endsWith('.' + definition.name));
    // The first few open on their own; the reader's own open/close choices are kept.
    item.open = Boolean(match || expanded.has(key) || (!collapsed.has(key) && (!sameMethod || !expanded.size) && index < 3));
    if (match) item.classList.add('focused');
    const summary = el('summary');
    summary.append(el('span', 'data-model-name', definition.name || definition.qualified || 'Model'),
      el('span', 'data-model-place', `${definition.span.file}:${definition.span.start}`));
    item.append(summary);
    const code = el('div', 'data-model-code code-window wrap-code');
    item.append(code);
    const load = () => { if (item.open && !code.childElementCount) loadModelSource(code, definition.span); };
    item.addEventListener('toggle', load);
    host.append(item);
    load();
  }
  if (data.nextModelOffset !== null && data.nextModelOffset !== undefined) {
    host.append(button('Load more models', 'quiet-button data-model-more', () =>
      loadMoreModels(data, host, id, focus, inline)));
  } else if (modelTotal > models.length) {
    host.append(el('p', 'dataflow-gap', `${modelTotal - models.length} model definitions were omitted from this response.`));
  }
  if (preserve && scrollPane) scrollPane.scrollTop = scrollTop;
  const chosen = host.querySelector('.data-model-item.focused');
  if (chosen && !inline && !preserve) chosen.scrollIntoView({
    block: 'nearest'
  });
}
async function loadMoreModels(data, host, id, focus, inline) {
  const next = data.nextModelOffset;
  if (next === null || next === undefined) return;
  const captured = model;
  const control = host.querySelector('.data-model-more');
  if (control) {
    control.disabled = true;
    control.textContent = 'Loading models…';
  }
  try {
    const page = await api('/api/dataflow', {
      symbol: id,
      snapshot: captured.snapshotId,
      cursor: 0,
      limit: 1,
      model_cursor: next
    });
    if (captured !== model || !host.isConnected) return;
    const existing = new Set(flowModels(data).map(item => item.id || item.qualified || item.name));
    data.models = mergeById(flowModels(data), flowModels(page));
    data.modelTotal = page.modelTotal ?? data.modelTotal;
    data.nextModelOffset = page.nextModelOffset ?? null;
    renderDataModels(data, host, id, focus, inline, true);
    const added = [...host.querySelectorAll('.data-model-item')].find(item =>
      !existing.has(item.dataset.modelKey));
    (added?.querySelector('summary') || host.querySelector('.data-model-more'))?.focus({ preventScroll: true });
  } catch (error) {
    if (control?.isConnected) {
      control.disabled = false;
      control.textContent = 'Retry loading models';
      control.after(el('p', 'error', 'Model definitions unavailable: ' + error.message));
    }
  }
}
async function loadModelSource(host, span) {
  const captured = model;
  host.append(el('p', 'source-peek', 'Loading…'));
  try {
    let start = span.start, first = true;
    while (start <= span.end) {
      const page = await api('/api/source', {snapshot: captured.snapshotId, file: span.file, start, end: Math.min(span.end, start + 199)});
      if (captured !== model || !host.isConnected) return;
      if (first) { host.replaceChildren(); first = false; }
      for (const [index, value] of page.source.split('\n').entries()) host.append(codeLine(start + index, value));
      start = page.span.end + 1;
    }
  } catch (error) {
    if (host.isConnected) host.replaceChildren(el('p', 'error', error.message));
  }
}
async function boundedMethodLines(id, snapshot = model.snapshotId) {
  let cursor = 0,
    span = null,
    rows = [];
  while (cursor !== null) {
    const page = await api('/api/method-source', {
      symbol: id,
      snapshot,
      cursor,
      limit: 100
    });
    span = page.span;
    rows.push(...page.lines.items);
    cursor = page.lines.nextCursor;
  }
  return {
    span,
    rows
  };
}
$('#sidebarToggle').addEventListener('click', () => {
  sidebarCollapsed = !sidebarCollapsed;
  $('.workspace').classList.toggle('sidebar-collapsed', sidebarCollapsed);
  $('#sidebarToggle').textContent = sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar';
  $('#sidebarToggle').setAttribute('aria-expanded', String(!sidebarCollapsed));
  announce(sidebarCollapsed ? 'Sidebar hidden.' : 'Sidebar shown.');
});
