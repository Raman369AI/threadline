'use strict';

// Snapshot-pinned data flow and method workspace controls.
const dataflowCache = new Map();
const dataflowPending = new Map();
const modelFocusByMethod = new Map();
const flowFocusByMethod = new Map();
let dataflowRequest = 0;
let selectedNode = null;
let selectedDirection = 'both';
let sidebarCollapsed = false;
let distractionMode = false;
let callerCompareStack = [];
let callerCompareFocus = null;
let callerCompareRequest = 0;
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
function flowCertainty(value) {
  return value && !['supported', 'syntax', 'source'].includes(value) ? ` · ${value}` : '';
}
async function loadDataflow(id, force = false) {
  const captured = model;
  const request = ++dataflowRequest;
  const key = flowKey(id);
  const host = $('#dataflowOverview');
  selectedNode = null;
  $('#dataflowTrace').replaceChildren();
  host.replaceChildren(el('p', 'source-peek', 'Reading method data flow…'));
  try {
    const result = force ? await fetchCompleteDataflow(id, captured) : await getFlowOverview(id, captured);
    if (captured !== model || state.scope !== id || request !== dataflowRequest) return;
    rememberFlow(key, result);
    renderDataflow(result, host, id);
    renderDataModels(result, $('#dataModelContent'), id, modelFocusByMethod.get(key));
    const prior = flowFocusByMethod.get(key);
    const node = prior && flowNodes(result).find(item => item.id === prior.nodeId);
    if (node) await selectFlowNode(id, node, prior.direction, false);
  } catch (error) {
    if (captured !== model || state.scope !== id || request !== dataflowRequest) return;
    host.replaceChildren(el('p', 'error', 'Data flow unavailable: ' + error.message), button('Retry', 'quiet-button', () => loadDataflow(id, true)));
    $('#dataModelContent').replaceChildren(el('p', 'source-peek', 'Data definitions are unavailable for this method.'));
  }
}
function rememberFlow(key, data) {
  dataflowCache.delete(key);
  dataflowCache.set(key, data);
  while (dataflowCache.size > 8) {
    const oldest = dataflowCache.keys().next().value;
    dataflowCache.delete(oldest);
    modelFocusByMethod.delete(oldest);
    flowFocusByMethod.delete(oldest);
  }
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
function groupedFlowNodes(data) {
  const groups = {
    inputs: [],
    values: [],
    outputs: [],
    references: []
  };
  for (const node of flowNodes(data)) {
    const kind = String(node.kind || '').toLowerCase();
    if (/model|class|import|reference/.test(kind)) {
      groups.references.push(node);
    } else if (/return|yield|output|sink|write/.test(kind)) {
      groups.outputs.push(node);
    } else if (/param|input|dependency|capture|global|external|constant/.test(kind)) {
      groups.inputs.push(node);
    } else {
      groups.values.push(node);
    }
  }
  return groups;
}
function renderValueButton(node, onSelect) {
  const item = button('', 'dataflow-item', () => onSelect(node));
  item.dataset.node = node.id;
  item.append(el('strong', '', node.name || node.expression || node.id));
  const meta = [node.kind, node.inputKind, node.annotation || node.shape || 'type unknown', node.default !== undefined && node.default !== null ? 'default ' + node.default : '', node.version !== undefined && node.version !== null ? 'version ' + node.version : '', node.expression || '', sourcePlace(node.span), flowCertainty(node.certainty)].filter(Boolean).join(' · ');
  item.append(el('small', '', meta));
  return item;
}
function renderFlowGroups(data, host, onSelect, onFollow = null) {
  host.replaceChildren();
  const groups = groupedFlowNodes(data);
  for (const [title, list] of [['At entry', groups.inputs], ['Created or changed', groups.values], ['Used or leaving', groups.outputs]]) {
    const section = el('section', 'dataflow-group');
    section.append(el('h2', '', title));
    if (list.length) {
      for (const node of list) section.append(renderValueButton(node, onSelect));
    } else section.append(el('p', 'source-peek', title === 'At entry' ? 'No source-declared input was found.' : title === 'Used or leaving' ? 'No explicit output was found.' : 'No additional named value was found.'));
    host.append(section);
    if (title === 'Created or changed') {
      const changes = el('section', 'dataflow-group');
      changes.append(el('h2', '', 'Changes in source order'));
      for (const event of flowItems(data.events)) changes.append(renderFlowEvent(event, onSelect, data, onFollow));
      if (!flowItems(data.events).length) changes.append(el('p', 'source-peek', 'No modeled changes in this page.'));
      host.append(changes);
    }
  }
  if (groups.references.length) {
    const references = el('section', 'dataflow-group');
    references.append(el('h2', '', 'Model and source references'));
    for (const node of groups.references) references.append(renderValueButton(node, onSelect));
    host.append(references);
  }
  if (data.templates?.links?.length) host.append(renderTemplateLinks(data, onSelect));
  if (data.truncated || data.omitted || data.events?.omitted) {
    host.append(el('p', 'dataflow-gap', 'This source-backed flow is incomplete. ' + [data.omitted, data.events?.omitted].filter(Boolean).join(' more records may be omitted. ')));
  }
  for (const gap of data.gaps || []) host.append(el('p', 'dataflow-gap', `${gap.kind || 'Unknown'}: ${gap.message || gap.expression || 'Relationship not established'} · ${sourcePlace(gap.span)}`));
}
function renderTemplateLinks(data, onSelect) {
  const templates = el('section', 'dataflow-group');
  templates.append(el('h2', '', 'Template and later browser data'));
  for (const link of data.templates.links) {
    const record = el('div', 'dataflow-event');
    record.append(el('strong', '', `${link.name || link.file || 'Template'} · ${link.status || 'source link'}`));
    if (link.contextKeys?.length) record.append(el('p', '', `Context sent: ${link.contextKeys.join(', ')}`));
    if (usableFlowSpan(link.span)) {
      record.append(button('Template call source', 'data-model-source',
        () => showSource(link.span, link.name || 'Template call', 'Context assembly in the selected method.')));
    }
    for (const asset of link.assets || []) {
      record.append(el('p', 'source-peek', `Template ${asset.file} · ${asset.lines} retained lines`));
      if (asset.truncated) record.append(el('p', 'dataflow-gap', 'Template references are truncated.'));
    }
    for (const use of link.contextUses || []) {
      record.append(el('p', '', `${use.expression || use.key || 'Context use'} · ${sourcePlace(use.span)}`));
    }
    for (const use of link.uses || []) {
      const linked = flowNodes(data).find(node => use.sourceNodes?.includes(node.id));
      const label = `${use.expression} · possible template use · ${sourcePlace(use.span)}`;
      record.append(linked
        ? button(label, 'data-model-source', () => onSelect(linked))
        : el('p', 'source-peek', label));
    }
    for (const fetch of link.clientFetches || []) {
      record.append(el('p', 'dataflow-gap',
        `${fetch.path} · later client request, separate from this method’s return · ${sourcePlace(fetch.span)}`));
    }
    if (link.omittedCandidates || link.omittedContextUses || link.omittedClientFetches || link.omittedUses) {
      record.append(el('p', 'dataflow-gap', 'Some template references are omitted.'));
    }
    templates.append(record);
  }
  for (const gap of data.templates.gaps || []) {
    templates.append(el('p', 'dataflow-gap', gap.message || gap.reason || 'Template relationship unresolved.'));
  }
  if (data.templates.truncated || data.templates.omitted) {
    templates.append(el('p', 'dataflow-gap', 'Template references are incomplete.'));
  }
  return templates;
}
function mergeById(a, b) {
  const identity = item => item.id || item.qualified || item.name;
  const found = new Set(a.map(identity));
  return [...a, ...b.filter(item => !found.has(identity(item)))];
}
function renderFlowEvent(event, onSelect, data, onFollow = null) {
  const item = el('div', 'dataflow-event');
  const title = button(event.label || event.kind || event.expression || 'Source change', '', () => {
    const next = flowNodes(data).find(node => event.outputs?.includes(node.id)) || flowNodes(data).find(node => event.inputs?.includes(node.id));
    if (next) {
      onSelect(next);
    } else if (usableFlowSpan(event.span)) {
      showSource(event.span, event.label || event.kind, 'Source-backed change' + flowCertainty(event.certainty));
    }
  });
  item.append(title);
  if (event.expression) item.append(el('div', '', event.expression));
  const indexed = new Map(flowNodes(data).map(node => [node.id, node]));
  const names = ids => ids.map(id => indexed.get(id)).filter(Boolean).map(node => node.name + (node.version ? ` [${node.version}]` : ''));
  const incoming = names(event.inputs || []),
    outgoing = names(event.outputs || []);
  if (incoming.length || outgoing.length) item.append(el('div', 'dataflow-link', `${incoming.join(', ') || 'source or constant'} → ${outgoing.join(', ') || 'effect or exit'}`));
  if (event.guards?.length) item.append(el('small', '', `When ${event.guards.map(guard => typeof guard === 'string' ? guard : `${guard.condition || 'branch'}${guard.branch ? ' → ' + guard.branch : ''}`).join(' and ')}`));
  if (event.details) appendEventDetails(item, event, indexed, onFollow);
  item.append(el('small', '', `${sourcePlace(event.span)}${flowCertainty(event.certainty)}`));
  return item;
}
function appendEventDetails(item, event, indexed, onFollow) {
  const details = event.details;
  if (typeof details === 'string') {
    item.append(el('small', '', details));
    return;
  }
  if (details.previous || details.next) {
    item.append(el('small', '',
      `Earlier ${indexed.get(details.previous)?.name || 'value'} → ${indexed.get(details.next)?.name || 'new version'}`));
  }
  if (details.added || details.removed) {
    const changes = [details.added && `Added ${details.added}`, details.removed && `Removed ${details.removed}`].filter(Boolean);
    item.append(el('small', '', changes.join(' · ')));
  }
  if (details.callReason) item.append(el('small', '', `${details.callStatus || 'unknown'} target · ${details.callReason}`));
  if (details.queryShape) {
    item.append(el('small', '', `Query expression: ${details.queryShape}${details.queryRowsUnproven ? ' · returned rows unknown' : ''}`));
  }
  if (details.elementsMayAliasInput) item.append(el('small', '', 'New container; elements may still reference input objects.'));
  if (details.zeroIterationsPossible) item.append(el('small', '', 'The loop may perform zero iterations.'));
  if (details.mayBeEmpty) item.append(el('small', '', 'The result may be empty.'));
  if (details.declaredIn) item.append(el('small', '', `Declaration in ${details.declaredIn} · ${sourcePlace(details.definitionSpan)}`));
  if (details.boundary) item.append(el('small', '', details.boundary));
  if (details.alternatives?.length) item.append(el('small', '', `Possible origins: ${details.alternatives.join(' or ')}`));
  if (details.templateBoundary) item.append(el('small', '', 'Template/context boundary; rendering is not proven.'));
  if (details.targets?.length && onFollow) {
    const targets = el('div', 'flow-targets');
    for (const target of details.targets) {
      const label = `${details.callStatus === 'supported' ? 'Follow' : 'Possible target'} → ${model.scopes[target]?.qualified || target}`;
      targets.append(button(label, 'scope-jump', () => onFollow(target, event)));
    }
    item.append(targets);
  }
  if (details.crossMethod) item.append(renderCrossMethod(details.crossMethod, event, onFollow));
}
function renderCrossMethod(link, event, onFollow) {
  const section = el('div', 'cross-method');
  section.append(el('strong', '', `Across method · ${link.lineageCertainty || 'possible'} source link`));
  if (link.executionUnproven) {
    section.append(el('p', '', 'The source connects these expressions; execution and runtime values are unproven.'));
  }
  for (const binding of link.parameterLinks || []) {
    const label = `${binding.argument} → ${binding.parameter} · ${binding.bindingCertainty || 'source'} binding · ${sourcePlace(binding.parameterSpan)}`;
    section.append(onFollow
      ? button(label, 'data-model-source', () => onFollow(link.calleeScope, event, binding.parameterSpan))
      : el('p', '', label));
  }
  for (const returned of link.returnSites || []) {
    const label = `Possible return site: ${returned.expression} · ${sourcePlace(returned.span)}`;
    section.append(onFollow
      ? button(label, 'data-model-source', () => onFollow(link.calleeScope, event, returned.span))
      : el('p', '', label));
  }
  for (const mutation of link.mutationSites || []) {
    const label = `Possible mutation through ${mutation.parameter}: ${mutation.expression} · ${sourcePlace(mutation.span)}`;
    section.append(onFollow
      ? button(label, 'data-model-source', () => onFollow(link.calleeScope, event, mutation.span))
      : el('p', '', label));
  }
  if (link.resultBoundary) section.append(el('p', '', link.resultBoundary));
  return section;
}

async function followFlowCall(target, event, evidenceSpan, originId) {
  await enterScope(target, {
    scope: originId,
    destination: event.expression || event.label || 'call result'
  });
  if (evidenceSpan && state.scope === target) {
    await showSource(evidenceSpan, model.scopes[target]?.qualified || 'Callee evidence', 'Source-backed cross-method reference.');
  }
}
function renderDataflow(data, host, id) {
  // Keep a selected value's trace ahead of the potentially long value list.
  host.before($('#dataflowTrace'));
  renderFlowGroups(data, host, node => selectFlowNode(id, node),
    (target, event, span) => followFlowCall(target, event, span, id));
  if (selectedNode) {
    const selected = host.querySelectorAll('.dataflow-item');
    for (const item of selected) item.classList.toggle('active', item.dataset.node === selectedNode);
  }
}
async function selectFlowNode(id, node, direction = 'both', showEvidence = true) {
  selectedNode = node.id;
  selectedDirection = direction;
  flowFocusByMethod.set(flowKey(id), {
    nodeId: node.id,
    direction
  });
  for (const item of $('#dataflowOverview').querySelectorAll('.dataflow-item')) item.classList.toggle('active', item.dataset.node === node.id);
  const span = node.span;
  if (showEvidence && usableFlowSpan(span)) showSource(span, node.name || node.expression || 'Value', `${node.kind || 'Value'}${flowCertainty(node.certainty)}`);
  const key = flowKey(id),
    data = dataflowCache.get(key);
  modelFocusByMethod.set(key, node.modelId || node.name);
  if (data) renderDataModels(data, $('#dataModelContent'), id, node.modelId || node.name);
  const host = $('#dataflowTrace');
  host.setAttribute('role', 'region');
  host.setAttribute('aria-label', 'Data flow trace for ' + (node.name || node.id));
  host.tabIndex = 0;
  host.replaceChildren(el('p', 'source-peek', 'Tracing ' + (node.name || node.id) + '…'));
  if (showEvidence && !$('#dataflowPanel').hidden) {
    host.focus({preventScroll: true});
    $('.review').scrollTop = 0;
  }
  const captured = model,
    wanted = node.id;
  try {
    const result = await fetchCompleteDataflow(id, captured, wanted, direction);
    if (captured !== model || state.scope !== id || selectedNode !== wanted) return;
    renderFlowTrace(result, host, id, node);
  } catch (error) {
    if (captured === model && state.scope === id && selectedNode === wanted) host.replaceChildren(el('p', 'error', 'Trace unavailable: ' + error.message), button('Retry', 'quiet-button', () => selectFlowNode(id, node, direction)));
  }
}
function renderFlowTrace(data, host, id, node) {
  host.replaceChildren(el('h2', '', 'Trace · ' + (node.name || node.id)));
  const controls = el('div', 'trace-links');
  for (const [direction, label] of [['upstream', 'Where from'], ['downstream', 'Where used'], ['both', 'Both']]) {
    const choice = button(label, 'quiet-button', () => selectFlowNode(id, node, direction));
    choice.setAttribute('aria-pressed', String(selectedDirection === direction));
    controls.append(choice);
  }
  host.append(controls);
  const trace = data.trace;
  if (!trace) {
    host.append(el('p', 'source-peek', 'No trace returned for this value.'));
    return;
  }
  const nodes = new Map([...flowNodes(dataflowCache.get(flowKey(id))), ...flowNodes(data)].map(item => [item.id, item]));
  const events = new Map([...flowItems(data.events), ...(data.eventReferences || [])].map(item => [item.id, item]));
  for (const eventId of trace.eventIds || []) {
    const event = events.get(eventId);
    if (event) host.append(renderFlowEvent(event, next => selectFlowNode(id, next), data,
      (target, callEvent, span) => followFlowCall(target, callEvent, span, id)));
  }
  const list = el('div', 'dataflow-group');
  list.append(el('h2', '', 'Connected values'));
  for (const nodeId of trace.nodeIds || []) {
    const next = nodes.get(nodeId);
    if (next) {
      list.append(renderValueButton(next, value => selectFlowNode(id, value)));
    } else {
      list.append(el('p', 'source-peek', 'Value ' + nodeId + ' is outside this page.'));
    }
  }
  if (list.childElementCount === 1) list.append(el('p', 'source-peek', 'No further source-backed value was found in this direction.'));
  host.append(list);
  for (const gap of data.gaps || []) host.append(el('p', 'dataflow-gap', gap.message || 'The source does not establish this link.'));
  if (data.truncated || data.omitted) host.append(el('p', 'dataflow-gap', 'Trace is incomplete or bounded.'));
}
function methodDataGroups(nodes) {
  const named = new Map();
  const keys = new Map();
  for (const node of nodes) {
    if (['parameter', 'local', 'field', 'object_state'].includes(node.kind)) {
      const name = node.name || node.id;
      if (!named.has(name)) named.set(name, []);
      named.get(name).push(node);
    } else if (node.kind === 'key') {
      const name = node.name || node.id;
      const bracket = name.lastIndexOf('[');
      const owner = bracket > 0 ? name.slice(0, bracket) : name;
      if (!keys.has(owner)) keys.set(owner, []);
      keys.get(owner).push(node);
    }
  }
  return {named, keys};
}
function methodKeyName(node) {
  const match = String(node.name || '').match(/\[(['"])(.*?)\1\]$/);
  return match ? match[2] : node.name || node.id;
}
function methodKeyGroupName(owner, rows, nodes) {
  if (!owner.startsWith('{')) return owner;
  const first = rows[0];
  const mutation = nodes.find(node => node.kind === 'object_state' &&
    usableFlowSpan(node.span) && usableFlowSpan(first.span) &&
    node.span.file === first.span.file &&
    node.span.start <= first.span.start && node.span.end >= first.span.end);
  if (mutation) {
    const kind = rows.find(node => methodKeyName(node) === 'kind');
    const literal = String(kind?.expression || '').match(/^(['"])(.*?)\1$/);
    return `${mutation.name} item${literal ? ' · ' + literal[2] : ''}`;
  }
  const context = nodes.filter(node => node.kind === 'template_context');
  if (context.length && rows.every(node => context.some(value => value.name === 'context.' + methodKeyName(node)))) {
    return 'Template context';
  }
  return `Object literal · ${sourcePlace(first.span)}`;
}
function renderMethodData(data, host, focus, expanded) {
  const nodes = flowNodes(data);
  const groups = methodDataGroups(nodes);
  const named = [...groups.named];
  const keys = [...groups.keys];
  const addedKeys = keys.reduce((count, [, rows]) => count + rows.length, 0);
  const mutations = nodes.filter(node => node.kind === 'object_state').length;
  const section = el('details', 'data-model-item');
  section.dataset.modelKey = 'section:method-data';
  const focused = node => focus && (focus === node.id || focus === node.name);
  section.open = Boolean(expanded.has(section.dataset.modelKey) ||
    named.some(([, rows]) => rows.some(focused)) ||
    keys.some(([, rows]) => rows.some(focused)));
  section.append(el('summary', '', `Method data · ${named.length} named values, ${addedKeys} added keys, ${mutations} mutations`));
  const body = el('div', 'data-model-body');
  if (!named.length && !keys.length) body.append(el('p', 'source-peek', 'No named data definition was modeled.'));
  if (named.length) body.append(el('h3', '', 'Parameters, locals and assigned fields'));
  for (const [name, rows] of named) {
    const item = el('details', 'data-model-item');
    item.dataset.modelKey = 'value:' + name;
    const match = rows.some(focused);
    item.open = Boolean(match || expanded.has(item.dataset.modelKey));
    if (match) item.classList.add('focused');
    const declaration = rows.find(node => node.kind !== 'object_state') || rows[0];
    item.append(el('summary', '', `${name}${declaration.annotation ? ' : ' + declaration.annotation : ''}`));
    const detail = el('div', 'data-model-body');
    for (const node of rows) {
      const label = node.kind === 'object_state' ? 'Mutation' : node.kind === 'field' ? 'Assigned field' : node.kind === 'parameter' ? 'Parameter' : 'Local';
      detail.append(el('p', '', `${label}${node.version ? ' · version ' + node.version : ''} · ${node.expression || 'source-declared value'}${flowCertainty(node.certainty)}`));
      if (node.default !== undefined && node.default !== null) detail.append(el('p', '', 'Default: ' + node.default));
      if (node.shape) detail.append(el('p', '', 'Source-supported shape: ' + node.shape));
      if (usableFlowSpan(node.span)) detail.append(sourceButton(node.span, 'Show source'));
    }
    item.append(detail);
    body.append(item);
  }
  if (keys.length) body.append(el('h3', '', 'Keys added to data structures'));
  for (const [owner, rows] of keys) {
    const item = el('details', 'data-model-item');
    item.dataset.modelKey = 'keys:' + owner;
    const match = rows.some(focused);
    item.open = Boolean(match || expanded.has(item.dataset.modelKey));
    if (match) item.classList.add('focused');
    item.append(el('summary', '', `${methodKeyGroupName(owner, rows, nodes)} · ${rows.length} keys`));
    const detail = el('div', 'data-model-body');
    const fields = el('ul', 'data-model-fields');
    for (const node of rows) {
      const row = el('li');
      row.append(el('code', '', methodKeyName(node)));
      row.append(document.createTextNode(` = ${node.expression || 'value unknown'}${flowCertainty(node.certainty)}`));
      if (usableFlowSpan(node.span)) row.append(document.createTextNode(' '), sourceButton(node.span, 'source'));
      fields.append(row);
    }
    detail.append(fields);
    item.append(detail);
    body.append(item);
  }
  section.append(body);
  host.append(section);
}
function renderDataModels(data, host, id, focus = null, inline = false, preserve = false) {
  const currentKey = flowKey(id);
  const expanded = host.dataset.scopeKey === currentKey
    ? new Set([...host.querySelectorAll('.data-model-item[open]')].map(item => item.dataset.modelKey))
    : new Set();
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
  const indexed = models.filter(definition => definition.status !== 'external')
    .map((definition, index) => ({definition, index}))
    .sort((left, right) => {
      const leftUse = firstUse.get(left.definition.name) ?? Infinity;
      const rightUse = firstUse.get(right.definition.name) ?? Infinity;
      return leftUse === rightUse ? left.index - right.index : leftUse - rightUse;
    })
    .map(item => item.definition);
  const external = models.filter(definition => definition.status === 'external');
  const modelTotal = data.modelTotal ?? models.length;
  host.append(el('h3', '', `Referenced models · ${indexed.length}`));
  if (!indexed.length) host.append(el('p', 'source-peek', 'No indexed model definition was linked to this method.'));
  for (const definition of indexed) {
    const item = el('details', 'data-model-item');
    item.dataset.modelKey = definition.id || definition.name;
    const match = focus && (focus === definition.id || focus === definition.name || focus === definition.qualified || String(focus).endsWith('.' + definition.name));
    item.open = Boolean(match || expanded.has(item.dataset.modelKey));
    if (match) item.classList.add('focused');
    item.append(el('summary', '', definition.qualified || definition.name || 'Unnamed model'));
    const body = el('div', 'data-model-body');
    body.append(el('p', '', `Indexed source definition · ${definition.file || sourcePlace(definition.span)}`));
    if (definition.bases?.length) body.append(el('p', '', `Bases: ${definition.bases.map(base => typeof base === 'string' ? base : base.expression || base.name || base.id).join(', ')}`));
    if (usableFlowSpan(definition.span)) body.append(sourceButton(definition.span, 'Show declaration'));
    const fields = el('ul', 'data-model-fields');
    for (const field of definition.fields || []) {
      const row = el('li');
      row.append(el('code', '', field.name || 'field'));
      row.append(document.createTextNode(`${field.annotation ? ' : ' + field.annotation : ''}${field.default !== undefined && field.default !== null ? ' = ' + field.default : ''}${field.owner ? ' · declared by ' + field.owner : ''}${field.kind ? ' · ' + field.kind : ''}`));
      if (usableFlowSpan(field.span)) row.append(document.createTextNode(' '), sourceButton(field.span, 'source'));
      fields.append(row);
    }
    if (!fields.childElementCount) fields.append(el('li', '', 'No indexed fields; the source may define them dynamically.'));
    body.append(fields);
    item.append(body);
    host.append(item);
    if (definition.fieldsTruncated || definition.omittedFields) item.append(el('p', 'dataflow-gap', `${definition.omittedFields || 'Some'} fields omitted by the analysis budget.`));
  }
  if (external.length) {
    const item = el('details', 'data-model-item');
    item.dataset.modelKey = 'section:external-types';
    const match = external.some(definition => focus &&
      (focus === definition.id || focus === definition.name || focus === definition.qualified));
    item.open = Boolean(match || expanded.has(item.dataset.modelKey));
    if (match) item.classList.add('focused');
    item.append(el('summary', '', `External types · ${external.length}`));
    const body = el('div', 'data-model-body');
    const fields = el('ul', 'data-model-fields');
    for (const definition of external) {
      const row = el('li');
      row.append(el('code', '', definition.name || definition.qualified));
      row.append(document.createTextNode(` · ${definition.qualified || 'definition outside indexed source'}`));
      fields.append(row);
    }
    body.append(fields);
    item.append(body);
    host.append(item);
  }
  if (data.nextModelOffset !== null && data.nextModelOffset !== undefined) {
    host.append(button('Load more models', 'quiet-button data-model-more', () =>
      loadMoreModels(data, host, id, focus, inline)));
  } else if (modelTotal > models.length) {
    host.append(el('p', 'dataflow-gap', `${modelTotal - models.length} model definitions were omitted from this response.`));
  }
  renderMethodData(data, host, focus, expanded);
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
function sourceButton(span, label) {
  return button(label, 'data-model-source', async event => {
    const item = event.currentTarget.closest('.data-model-item'),
      existing = item?.querySelector('.reference-excerpt');
    if (existing) {
      existing.remove();
      return;
    }
    const excerpt = el('div', 'reference-excerpt code-window wrap-code');
    excerpt.textContent = 'Loading declaration…';
    item?.querySelector('.data-model-body')?.append(excerpt);
    try {
      const result = await api('/api/source', {
        snapshot: model.snapshotId,
        file: span.file,
        start: span.start,
        end: Math.min(span.end, span.start + 199)
      });
      if (!excerpt.isConnected) return;
      excerpt.replaceChildren(...result.source.split('\n').map((value, index) => codeLine(span.start + index, value)));
      if (span.end > result.span.end) excerpt.append(button('Show more declaration lines', 'scope-jump', async () => {
        let start = result.span.end + 1;
        while (start <= span.end) {
          const page = await api('/api/source', {
            snapshot: model.snapshotId,
            file: span.file,
            start,
            end: Math.min(span.end, start + 199)
          });
          if (!excerpt.isConnected) return;
          for (const [index, value] of page.source.split('\n').entries()) excerpt.append(codeLine(start + index, value));
          start = page.span.end + 1;
        }
        excerpt.querySelector('.scope-jump')?.remove();
      }));
    } catch (error) {
      excerpt.textContent = error.message;
    }
  });
}
function setCodeFull(full) {
  $('.workspace').classList.toggle('code-full', full);
  $('#fullCode').hidden = full;
  $('#restoreCode').hidden = !full;
  $('#sourceMethodTitle').hidden = !full;
  $('#sourceMethodTitle').textContent = model?.scopes[state.scope]?.qualified || 'Selected method';
  if (full) {
    $('#sourceCode').focus({
      preventScroll: true
    });
    announce('Method code fills the workspace.');
  }
}
function restoreAnalysis() {
  selectTab(lastAnalysisView || 'dataflow', true);
}
$('#fullCode').addEventListener('click', () => selectTab('code'));
$('#restoreCode').addEventListener('click', restoreAnalysis);
function updateSidebar() {
  const hidden = sidebarCollapsed || distractionMode,
    workspace = $('.workspace');
  workspace.classList.toggle('sidebar-collapsed', sidebarCollapsed && !distractionMode);
  workspace.classList.toggle('no-distraction', distractionMode);
  $('#sidebarToggle').textContent = hidden ? 'Show sidebar' : 'Hide sidebar';
  $('#sidebarToggle').setAttribute('aria-expanded', String(!hidden));
  $('#focusMode').setAttribute('aria-pressed', String(distractionMode));
  announce(hidden ? 'Sidebar hidden.' : 'Sidebar shown.');
}
$('#sidebarToggle').addEventListener('click', () => {
  if (distractionMode) {
    distractionMode = false;
    sidebarCollapsed = false;
  } else sidebarCollapsed = !sidebarCollapsed;
  updateSidebar();
});
$('#focusMode').addEventListener('click', () => {
  distractionMode = !distractionMode;
  updateSidebar();
});
const codeResize = $('#codeResize');
function resizeCodeAt(clientX) {
  const workspace = $('.workspace'),
    nav = $('#repositoryNavigator'),
    navWidth = nav.offsetParent ? nav.getBoundingClientRect().width : 0;
  const available = workspace.getBoundingClientRect().width - navWidth - 8;
  const desired = workspace.getBoundingClientRect().right - clientX;
  const width = Math.max(Math.min(desired, Math.max(260, available - 260)), Math.min(260, available / 2));
  workspace.style.setProperty('--code-width', Math.round(width) + 'px');
  codeResize.setAttribute('aria-valuenow', String(Math.round(width / available * 100)));
  codeResize.setAttribute('aria-valuetext', `${Math.round(width)} pixels`);
}
codeResize.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  codeResize.setPointerCapture(event.pointerId);
  resizeCodeAt(event.clientX);
});
codeResize.addEventListener('pointermove', event => {
  if (codeResize.hasPointerCapture(event.pointerId)) resizeCodeAt(event.clientX);
});
codeResize.addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
  event.preventDefault();
  if (event.key === 'Home') {
    $('.workspace').style.removeProperty('--code-width');
    codeResize.setAttribute('aria-valuenow', '42');
    return;
  }
  const x = $('.source-panel').getBoundingClientRect().left + (event.key === 'ArrowLeft' ? -20 : 20);
  resizeCodeAt(x);
});
$('#resetCodeWidth').addEventListener('click', () => {
  $('.workspace').style.removeProperty('--code-width');
  codeResize.setAttribute('aria-valuenow', '42');
  announce('Code width reset.');
});
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
function closeCallerComparison() {
  ++callerCompareRequest;
  callerCompareStack = [];
  $('#callerComparisonPanel').hidden = true;
  $('.workspace').classList.remove('caller-comparing');
  const prior = callerCompareFocus;
  callerCompareFocus = null;
  if (prior?.isConnected) {
    prior.focus({ preventScroll: true });
  } else {
    $('#tab-callers').focus({ preventScroll: true });
  }
}
async function openCallerComparison(row, calledId = null) {
  if (!callerCompareStack.length) {
    callerCompareFocus = document.activeElement;
  } else {
    const previous = callerCompareStack.at(-1),
      panel = $('#callerComparisonPanel');
    previous.dom = [...panel.childNodes];
    previous.scroll = panel.scrollTop;
    previous.focus = document.activeElement;
  }
  callerCompareStack.push({
    calledId: calledId || state.scope,
    row
  });
  $('.workspace').classList.remove('code-full');
  $('.workspace').classList.add('caller-comparing');
  $('#callerComparisonPanel').hidden = false;
  renderCallerComparison();
}
function backCallerComparison() {
  if (callerCompareStack.length <= 1) {
    closeCallerComparison();
    return;
  }
  callerCompareStack.pop();
  ++callerCompareRequest;
  const previous = callerCompareStack.at(-1),
    panel = $('#callerComparisonPanel');
  if (previous.dom) {
    panel.replaceChildren(...previous.dom);
    panel.scrollTop = previous.scroll;
    previous.focus?.focus({
      preventScroll: true
    });
  } else renderCallerComparison();
}
async function renderCallerComparison() {
  const descriptor = callerCompareStack.at(-1),
    request = ++callerCompareRequest,
    captured = model,
    host = $('#callerComparisonPanel');
  if (!descriptor) return;
  host.replaceChildren(el('p', 'source-peek', 'Loading caller comparison…'));
  try {
    const [called, caller] = await Promise.all([comparisonSideData(descriptor.calledId, captured), comparisonSideData(descriptor.row.id, captured)]);
    const callLookup = await findComparisonCall(caller.scope.id, called.scope.id, descriptor.row.callsite, captured);
    if (request !== callerCompareRequest || captured !== model) return;
    const heading = el('div', 'caller-comparison-heading');
    const back = button('← Back', 'quiet-button', backCallerComparison);
    heading.append(back, el('h1', '', 'Caller and called method'), button('Close', 'quiet-button', closeCallerComparison));
    const columns = el('div', 'caller-columns');
    const entry = {
      file: called.scope.file,
      start: called.source.span.start,
      end: called.source.span.start
    };
    columns.append(renderCallerSide(called, 'Called method', entry), renderCallerSide(caller, 'Caller', descriptor.row.callsite));
    host.replaceChildren(heading, el('p', 'comparison-notice', `${descriptor.row.reason || 'Source call relationship'} · ${certaintyLabel(descriptor.row.status)} · callsite ${sourcePlace(descriptor.row.callsite)}. Values and effects shown here are source-backed, not observed execution.`), renderComparisonBinding(callLookup, called.scope.id), columns);
    back.focus({
      preventScroll: true
    });
  } catch (error) {
    if (request === callerCompareRequest && captured === model) host.replaceChildren(el('p', 'error', error.message), button('← Back', 'quiet-button', backCallerComparison), button('Retry', 'quiet-button', renderCallerComparison));
  }
}
async function findComparisonCall(callerId, calledId, callsite, captured) {
  if (!callsite) return { call: null, reason: 'The indexed caller has no callsite location.' };
  try {
    const records = await collectComparisonOperations(callerId, captured, call =>
      call.span?.file === callsite.file &&
      call.span.start === callsite.start &&
      call.span.col === callsite.col &&
      call.targets?.includes(calledId));
    return {
      call: records.match,
      reason: records.truncated
        ? 'The callsite lies beyond this comparison’s bounded step search.'
        : null
    };
  } catch (error) {
    return { call: null, reason: 'Callsite details could not be loaded: ' + error.message };
  }
}

async function collectComparisonOperations(id, captured, matchesCall = null) {
  const records = [];
  const budget = { pages: 0, truncated: false, match: null };

  async function visit(operation, arm, cursor, depth, branchLabel) {
    if (budget.match) return;
    if (budget.pages >= 40) {
      budget.truncated = true;
      return;
    }
    budget.pages++;
    const params = { symbol: id, snapshot: captured.snapshotId, cursor, limit: 20 };
    const path = operation ? '/api/branch' : '/api/scope';
    if (operation) {
      params.operation = operation;
      params.arm = arm;
    } else {
      params.shallow = 1;
    }
    const page = await api(path, params);
    for (const node of page.flow.items) {
      records.push({ node, depth, branchLabel });
      if (matchesCall) {
        budget.match = (node.calls || []).find(matchesCall) || null;
        if (budget.match) return;
      }
      for (const [index, branch] of (node.branches || []).entries()) {
        if (branch.total) await visit(node.id, branch.arm ?? index, 0, depth + 1, branch.label);
        if (budget.match) return;
      }
    }
    if (page.flow.nextCursor !== null) {
      await visit(operation, arm, page.flow.nextCursor, depth, branchLabel);
    }
  }

  await visit(null, 0, 0, 0, '');
  return { items: records, match: budget.match, truncated: budget.truncated };
}
function renderComparisonBinding(lookup, calledId) {
  const box = el('section', 'caller-binding');
  box.append(el('h2', '', 'Call relationship'));
  const call = lookup.call;
  if (!call) {
    box.append(el('p', 'source-peek', lookup.reason || 'The indexed caller identifies this callsite, but an explicit argument map is unavailable here. Inspect the two source panes.'));
    return box;
  }
  const bindings = call.bindings?.[calledId] || [];
  if (bindings.length) {
    for (const binding of bindings) box.append(el('p', '', `${binding.argument} → ${binding.parameter}${binding.certainty === 'syntax' ? '' : ' · ' + binding.certainty}`));
  } else box.append(el('p', 'source-peek', 'No explicit parameters were mapped.'));
  if (call.destination) box.append(el('p', '', `Return used as: ${call.destination}`));
  if (call.status !== 'supported') box.append(el('p', 'dataflow-gap', 'The call target is possible; the mapping is one source-backed alternative.'));
  return box;
}
async function comparisonSideData(id, captured) {
  const scope = await ensureScope(id, captured),
    key = captured.snapshotId + '|' + id;
  const [data, source] = await Promise.all([getFlowOverview(id, captured), boundedMethodLines(id, captured.snapshotId)]);
  rememberFlow(key, data);
  return {
    scope,
    data,
    source
  };
}
function renderCallerSide({
  scope,
  data,
  source
}, role, focusSpan) {
  const side = el('section', 'caller-side');
  side.setAttribute('aria-label', role + ' ' + scope.qualified);
  side.append(el('h2', '', role + ' · ' + scope.qualified), el('p', 'method-where', `${scope.file}:${source.span?.start || scope.span.start}–${source.span?.end || scope.span.end}`));
  const code = el('div', 'comparison-code wrap-code');
  code.tabIndex = 0;
  code.setAttribute('role', 'region');
  code.setAttribute('aria-label', role + ' Python source');
  for (const row of source.rows) code.append(codeLine(row.number, row.text, Boolean(focusSpan && focusSpan.file === scope.file && row.number >= focusSpan.start && row.number <= focusSpan.end)));
  side.append(code);
  const tabs = el('div', 'side-tabs'),
    overview = el('div', 'dataflow-overview'),
    models = el('aside', 'data-model-pane');
  models.hidden = true;
  models.setAttribute('aria-label', role + ' data models');
  let view = 'flow';
  let stepsPromise = null;
  const flowButton = button('Data flow', 'quiet-button', () => setView('flow'));
  const stepsButton = button('Steps', 'quiet-button', () => setView('steps'));
  const modelButton = button('Data models', 'quiet-button', () => {
    models.hidden = !models.hidden;
    modelButton.setAttribute('aria-expanded', String(!models.hidden));
    if (!models.hidden) renderDataModels(data, models, scope.id, null, true);
  });
  modelButton.setAttribute('aria-expanded', 'false');
  tabs.append(flowButton, stepsButton, modelButton);
  side.append(tabs, overview, models);
  function selectValue(node) {
    if (usableFlowSpan(node.span) && node.span.file === scope.file) markCodeRange(code, node.span, true);
    models.hidden = false;
    modelButton.setAttribute('aria-expanded', 'true');
    renderDataModels(data, models, scope.id, node.modelId || node.name, true);
  }
  function setView(next) {
    view = next;
    flowButton.setAttribute('aria-pressed', String(view === 'flow'));
    stepsButton.setAttribute('aria-pressed', String(view === 'steps'));
    if (view === 'flow') {
      renderFlowGroups(data, overview, selectValue);
    } else {
      overview.replaceChildren(el('p', 'source-peek', 'Loading this method’s steps…'));
      stepsPromise ||= collectComparisonOperations(scope.id, model);
      stepsPromise.then(records => {
        if (view === 'steps') renderComparisonSteps(records, overview, code);
      }).catch(error => {
        stepsPromise = null;
        if (view === 'steps') overview.replaceChildren(el('p', 'error', error.message));
      });
    }
  }
  setView('flow');
  const callers = button('See this method’s callers', 'quiet-button', async () => {
    callers.disabled = true;
    try {
      const result = await api('/api/overview', {
        symbol: scope.id,
        snapshot: model.snapshotId,
        limit: 20
      });
      if (!side.isConnected) return;
      const list = el('div', 'test-list');
      for (const row of result.callers.items) list.append(linkRow(row, 'caller', scope.id));
      if (!list.childElementCount) list.append(el('p', 'source-peek', 'No indexed callers.'));
      callers.after(list);
    } catch (error) {
      callers.after(el('p', 'error', error.message));
      callers.disabled = false;
    }
  });
  side.append(callers);
  return side;
}
function renderComparisonSteps(records, host, code) {
  host.replaceChildren();
  for (const { node, depth, branchLabel } of records.items) {
    const item = button(node.label || node.kind || 'Step', 'dataflow-item', () => {
      if (usableFlowSpan(node.span)) markCodeRange(code, node.span, true);
    });
    item.style.marginLeft = Math.min(depth, 8) * 12 + 'px';
    item.style.width = `calc(100% - ${Math.min(depth, 8) * 12}px)`;
    item.append(el('small', '', `${branchLabel ? branchLabel + ' · ' : ''}${sourcePlace(node.span)}`));
    host.append(item);
  }
  if (records.truncated) host.append(el('p', 'dataflow-gap', 'Additional steps remain beyond this comparison’s bounded page budget. Open the method’s Steps view to continue.'));
  if (!records.items.length) host.append(el('p', 'source-peek', 'No represented steps.'));
}
