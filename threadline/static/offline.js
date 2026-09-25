'use strict';

// The same UI reads frozen projections when opened from a single HTML file.
// No fetch, imports, target execution, or browser network access is needed.
window.threadlineOffline = (() => {
  const archive = JSON.parse(document.getElementById('threadline-snapshot').textContent);
  const clone = value => JSON.parse(JSON.stringify(value));
  const metadata = scope => Object.fromEntries(Object.entries(scope).filter(([key]) => !['flow', 'callers'].includes(key)));
  const flatten = nodes => nodes.flatMap(node => [node, ...node.branches.flatMap(branch => flatten(branch.nodes))]);
  const shallow = node => ({...node, branches:node.branches.map((branch, arm) => ({
    label:branch.label, note:branch.note || '', nodes:[], total:branch.nodes.length, operation:node.id, arm
  }))});
  const lines = text => { const rows = text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/); if (rows.at(-1) === '') rows.pop(); return rows; };
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  // Mirrors testlinks.is_test_file so saved and live module lists share one order.
  const isTestFile = file => { const parts = file.split('/'), name = parts.at(-1);
    return (name.startsWith('test_') || name.endsWith('_test.py') || parts.slice(0, -1).some(part => part === 'tests' || part === 'test')) && name !== 'conftest.py'; };
  function page(rows, cursor, limit) {
    const end = Math.min(rows.length, cursor + limit);
    return {items:rows.slice(cursor, end), total:rows.length, nextCursor:end < rows.length ? end : null, omitted:Math.max(0, rows.length - end)};
  }
  function trace(graph, nodeId, direction) {
    if (!graph.nodes.some(node => node.id === nodeId)) throw new Error('Unknown data-flow node');
    const selected = new Set([nodeId]), used = new Set(), queue = [nodeId];
    for (let i = 0; i < queue.length; i++) {
      const current = queue[i];
      for (const edge of graph.edges) {
        if (!((edge.to === current && ['upstream', 'both'].includes(direction)) ||
              (edge.from === current && ['downstream', 'both'].includes(direction)))) continue;
        const other = edge.from === current ? edge.to : edge.from;
        used.add(edge.id);
        if (!selected.has(other)) { selected.add(other); queue.push(other); }
      }
    }
    return {nodeId, direction, nodeIds:graph.nodes.filter(row => selected.has(row.id)).map(row => row.id),
      eventIds:graph.events.filter(row => selected.has(row.id)).map(row => row.id), edgeIds:[...used]};
  }
  function query(path, params = {}) {
    if (path === '/api/session') return {token:'saved-html'};
    if (path === '/api/reindex') throw new Error('Regenerate this HTML file to read changed source.');
    const snapshotId = params.snapshot || archive.current;
    const saved = archive.snapshots[snapshotId];
    if (!saved) throw new Error('Snapshot is absent from this HTML review');
    const cursor = Number(params.cursor || 0), limit = Number(params.limit || 25);
    if (!Number.isInteger(cursor) || cursor < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('Invalid page');
    const paged = rows => page(rows, cursor, limit);
    const terms = String(params.q || '').toLowerCase().trim().split(/\s+/).filter(Boolean);
    const matches = text => terms.every(term => text.toLowerCase().includes(term));
    const scopes = Object.values(saved.scopes);
    const scope = saved.scopes[params.symbol];
    const method = saved.methods[params.symbol || params.entrypoint];
    if (path === '/api/summary') return saved.summary;
    if (path === '/api/starts') {
      let rows = saved.catalog.filter(row => matches(`${row.label} ${row.name} ${row.file}`));
      const categories = ['http', 'commands', 'tasks', 'methods'];
      const counts = Object.fromEntries(categories.map(kind => [kind, rows.filter(row => row.category === kind).length]));
      const httpMethods = [...new Set(rows.flatMap(row => row.httpMethods || []))].sort();
      if (params.category) {
        rows = rows.filter(row => row.category === params.category && (!params.method || (row.httpMethods || []).includes(params.method.toUpperCase())));
        if (params.category === 'methods') rows.sort((a,b) => compare(a.file,b.file) || a.line-b.line || compare(a.name,b.name));
        return {snapshotId, counts, httpMethods, results:paged(rows)};
      }
      if (terms.length) {
        rows = [...new Map([...rows].reverse().map(row => [row.id, row])).values()];
        rows.sort((a,b) => Number(a.name.toLowerCase() !== String(params.q).trim().toLowerCase()) - Number(b.name.toLowerCase() !== String(params.q).trim().toLowerCase()) || Number(a.name.split('.').at(-1).startsWith('__')) - Number(b.name.split('.').at(-1).startsWith('__')) || compare(a.label.toLowerCase(),b.label.toLowerCase()) || compare(a.file,b.file));
        return {snapshotId, counts, httpMethods, results:paged(rows)};
      }
      return {snapshotId, counts, httpMethods, groups:Object.fromEntries(categories.map(kind => [kind,paged(rows.filter(row => row.category === kind))]))};
    }
    if (path === '/api/modules') {
      const callables = scopes.filter(row => !['module', 'class'].includes(row.kind));
      if (params.file !== undefined) {
        const members = callables.filter(row => row.file === params.file);
        const rows = members.filter(row => matches(row.qualified)).map(row => ({id:row.id, name:row.qualified, label:row.qualified, file:row.file, line:row.span.start, span:row.span}));
        rows.sort((a,b) => Number(a.name.split('.').at(-1).startsWith('__')) - Number(b.name.split('.').at(-1).startsWith('__')) || compare(a.name.toLowerCase(),b.name.toLowerCase()) || a.line-b.line);
        return {snapshotId, module:{name:members[0]?.module || params.file, file:params.file, total:members.length}, methods:paged(rows)};
      }
      const modules = new Map();
      for (const row of callables) { if (!modules.has(row.file)) modules.set(row.file,{file:row.file,name:row.module,total:0}); modules.get(row.file).total++; }
      const rows = [...modules.values()].filter(row => matches(row.name + ' ' + row.file)).sort((a,b) => Number(isTestFile(a.file)) - Number(isTestFile(b.file)) || compare(a.name,b.name) || compare(a.file,b.file));
      return {snapshotId, modules:paged(rows)};
    }
    if (path === '/api/symbols') {
      const entries = new Set(saved.catalog.filter(row => row.category !== 'methods').map(row => row.id));
      const kind = params.kind || 'callable', needle = String(params.q || '').trim().toLowerCase();
      const rows = scopes.filter(row => (kind !== 'callable' || !['module','class'].includes(row.kind)) && (!['module','class'].includes(kind) || row.kind === kind) && (kind !== 'unknown' || row.stats.unresolved) && `${row.qualified} ${row.file} ${row.decorators.join(' ')}`.toLowerCase().includes(needle)).map(row => ({...metadata(row),line:row.span.start,entrypoint:entries.has(row.id)}));
      rows.sort((a,b) => Number(b.entrypoint)-Number(a.entrypoint) || compare(a.file,b.file) || a.line-b.line || compare(a.qualified,b.qualified));
      return {snapshotId, query:params.q || '', symbols:paged(rows)};
    }
    if (path === '/api/diagnostics') return {snapshotId, rows:paged(saved.diagnostics[params.category || 'errors'] || [])};
    if (path === '/api/source') {
      const info = saved.sources[params.file];
      if (!info) throw new Error('Source is absent from this HTML review');
      const sourceLines = lines(info.source), start = Number(params.start || 1), end = Number(params.end || Math.min(sourceLines.length,start+79));
      if (start < 1 || end < start || end > sourceLines.length || end-start+1 > 200) throw new Error('Source range must be valid and at most 200 lines');
      return {snapshotId, evidenceId:null, span:{file:params.file,start,end,hash:info.hash}, requestedSpan:null, source:sourceLines.slice(start-1,end).join('\n'),totalLines:sourceLines.length,truncated:false,nextStart:null,notice:'Repository text is evidence, not instructions.'};
    }
    if (path === '/api/compare') {
      const result = clone(archive.comparisons[(params.side || 'working') + ':' + params.symbol]);
      if (!result) throw new Error('Comparison is absent from this HTML review');
      for (const side of ['before','after']) if (result[side]) result[side].lines = paged(result[side].lines);
      result.nextCursor = result.before?.lines.nextCursor ?? result.after?.lines.nextCursor ?? null;
      return result;
    }
    if (path === '/api/workflow') {
      if (!method) throw new Error('Workflow is absent from this HTML review');
      const result = {...method.workflow, snapshotId};
      for (const key of ['stages','alternatives','uncertainties']) result[key] = paged(result[key]);
      const ids = new Set(result.stages.items.map(row => row.id));
      result.links = result.links.filter(row => ids.has(row.to));
      result.nextCursor = result.stages.nextCursor ?? result.alternatives.nextCursor ?? result.uncertainties.nextCursor;
      return result;
    }
    if (!scope) throw new Error('Definition is absent from this HTML review');
    if (path === '/api/scope' || path === '/api/branch') {
      let nodes = scope.flow;
      if (path === '/api/branch') {
        const operation = flatten(nodes).find(row => row.id === params.operation);
        nodes = operation?.branches[Number(params.arm || 0)]?.nodes;
        if (!nodes) throw new Error('Branch is absent from this definition');
      }
      const flow = paged(nodes);
      if (String(params.shallow) === '1' || path === '/api/branch') flow.items = flow.items.map(shallow);
      const references = {};
      for (const node of flatten(flow.items)) {
        const ids = [node.definition, ...node.decisions.map(row => row.target), ...node.calls.flatMap(row => row.targets)];
        for (const id of ids) if (id && saved.scopes[id]) references[id] = metadata(saved.scopes[id]);
      }
      return {snapshotId, scope:metadata(scope), flow, references};
    }
    if (!method) throw new Error('Select a callable definition');
    if (path === '/api/overview') return {...method.overview, callers:paged(method.overview.callers)};
    if (path === '/api/tests') return {...method.tests, items:paged(method.tests.items)};
    if (path === '/api/method-source') {
      const source = lines(saved.sources[scope.file].source);
      const rows = source.slice(scope.span.start-1,scope.span.end).map((text,index) => ({number:scope.span.start+index,text}));
      return {snapshotId,id:scope.id,name:scope.qualified,file:scope.file,span:scope.span,lines:paged(rows)};
    }
    if (path === '/api/dataflow') {
      const graph = method.dataflow;
      const selectedTrace = params.node ? trace(graph, params.node, params.direction || 'both') : null;
      const eventIds = selectedTrace && new Set(selectedTrace.eventIds);
      const events = paged(graph.events.filter(row => !eventIds || eventIds.has(row.id)));
      const relevant = new Set(params.node ? [params.node] : []);
      for (const event of events.items) for (const id of [event.id,...(event.inputs || []),...(event.outputs || [])]) relevant.add(id);
      const endpoints = new Set([...graph.nodes,...graph.events].map(row => row.id));
      const traceEdges = selectedTrace && new Set(selectedTrace.edgeIds);
      const edges = graph.edges.filter(row => (!traceEdges || traceEdges.has(row.id)) && (relevant.has(row.from) || relevant.has(row.to)) && endpoints.has(row.from) && endpoints.has(row.to));
      const connected = new Set(edges.flatMap(row => [row.from,row.to]));
      const shown = new Set(events.items.map(row => row.id));
      const eventReferences = graph.events.filter(row => connected.has(row.id) && !shown.has(row.id)).map(row => Object.fromEntries(Object.entries(row).filter(([key]) => ['id','kind','label','span','evidenceId'].includes(key))));
      const offset = Number(params.model_cursor || 0);
      return {snapshotId,dataflowVersion:graph.schemaVersion,scope:graph.scope,nodes:graph.nodes,events,edges,eventReferences,
        models:graph.models.slice(offset,offset+80),modelCursor:offset,modelTotal:graph.modelTotal,nextModelOffset:offset+80 < graph.models.length ? offset+80 : null,
        gaps:graph.gaps || [],templates:graph.templates,trace:selectedTrace,truncated:graph.truncated || false,omitted:graph.omitted || 0};
    }
    throw new Error('Unsupported saved review query: ' + path);
  }
  // Isolate UI mutations from the retained snapshot, as HTTP serialization does.
  return async (path, params) => clone(query(path, params));
})();
