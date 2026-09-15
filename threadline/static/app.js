'use strict';
let model;
const $ = selector => document.querySelector(selector);
const state = { scope: null, focus: null, stack: [], selectedElement: null, sourceWhole: false, wrap: true };
const format = value => Number(value).toLocaleString();
function el(tag, cls, content) { const node = document.createElement(tag); if (cls) node.className = cls; if (content !== undefined) node.textContent = content; return node; }
function button(label, cls, handler) { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', handler); return b; }
function walk(nodes) { return nodes.flatMap(node => [node, ...node.branches.flatMap(branch => walk(branch.nodes))]); }
function scopeName(id) { return model.scopes[id]?.qualified || id; }
function announce(message) { $('#announcement').textContent = message; }
function icon(kind) { return ({If:'◇',Match:'◇',Assert:'◇',For:'↻',AsyncFor:'↻',While:'↻',Try:'⑂',TryStar:'⑂',Return:'↩',Raise:'↗',Break:'↗',Continue:'↻',With:'▱',AsyncWith:'▱',FunctionDef:'ƒ',AsyncFunctionDef:'ƒ',ClassDef:'C',Import:'↓',ImportFrom:'↓'})[kind] || '·'; }

let sessionToken = '', navigationRequest = 0, selectionRequest = 0, sourceRequest = 0;
async function api(path, params={}, options={}) {
  const response = await fetch(path + '?' + new URLSearchParams(params), options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
async function ensureScope(id, captured=model) {
  if (captured.scopes[id]?.flow) return captured.scopes[id];
  const page = await api('/api/scope', {symbol:id, snapshot:captured.snapshotId, limit:20});
  for (const [key, value] of Object.entries(page.references)) captured.scopes[key] ||= value;
  captured.scopes[id] = {...page.scope, flow:page.flow.items, nextCursor:page.flow.nextCursor};
  return captured.scopes[id];
}
function appendScopeFlow(host, scope, ancestry, depth) {
  host.append(renderList(scope.flow, scope, ancestry, depth));
  if (scope.nextCursor !== null) {
    const more = button('Load more statements →', 'quiet-button', async () => {
      const captured = model; more.disabled = true;
      try {
        const page = await api('/api/scope', {symbol:scope.id, snapshot:captured.snapshotId, cursor:scope.nextCursor, limit:20});
        if (captured !== model) return;
        for (const [key, value] of Object.entries(page.references)) captured.scopes[key] ||= value;
        const canonical=captured.scopes[scope.id];
        const known=new Set(canonical.flow.map(node=>node.id));
        canonical.flow.push(...page.flow.items.filter(node=>!known.has(node.id)));canonical.nextCursor=page.flow.nextCursor;
        scope.nextCursor=page.flow.nextCursor;
        if(canonical.nextCursor===null&&state.scope===scope.id)$('#flow .scope-end').textContent='End of body · if control reaches here, Python returns None (or the generator terminates).';
        const extra=el('div'); more.replaceWith(extra);
        appendScopeFlow(extra, {...scope, flow:page.flow.items}, ancestry, depth);
      } catch(error) {announce(error.message); more.disabled=false;}
    });
    host.append(more);
  }
}
async function navigation(cursor=0) {
  const request=++navigationRequest, captured=model;
  try {
    const data=await api('/api/symbols', {q:$('#search').value, kind:$('#kindFilter').value, snapshot:captured.snapshotId, cursor, limit:50});
    if(request!==navigationRequest || captured!==model) return;
    const host=$('#navigation'); host.replaceChildren();
    for(const scope of data.symbols.items) {
      captured.scopes[scope.id] ||= scope;
      const item=button(scope.qualified, 'nav-item'+(scope.id===state.scope?' active':''),()=>chooseScope(scope.id));
      item.dataset.scope=scope.id; item.title=scope.file+':'+scope.line;
      item.append(el('small','', ' · '+scope.file+':'+scope.line));host.append(item);
    }
    if(!data.symbols.total) host.append(el('p','nav-empty','No matching definitions.'));
    host.append(el('p','source-peek', `${data.symbols.total} matching definitions`));
    if(cursor) host.append(button('Previous definitions','quiet-button',()=>navigation(Math.max(0,cursor-50))));
    if(data.symbols.nextCursor!==null) host.append(button('More definitions →','quiet-button',()=>navigation(data.symbols.nextCursor)));
  } catch(error) {if(request===navigationRequest) announce(error.message);}
}

async function chooseScope(id, opts={}) {
  const request=++selectionRequest, captured=model;
  try {await ensureScope(id, captured);} catch(error) {announce(error.message); return false;}
  if(request!==selectionRequest || captured!==model) return false;
  if (!opts.keepStack) state.stack = [];
  state.scope = id; state.focus = null; state.sourceWhole = false; state.selectedElement = null;
  const scope = model.scopes[id];
  $('#scopePath').textContent = scope.file + (scope.parent && model.scopes[scope.parent] && model.scopes[scope.parent].kind !== 'module' ? ' / ' + scopeName(scope.parent) : '');
  $('#scopeTitle').textContent = scope.kind === 'module' ? 'Module body' : scope.name.replace(/^_+/, '').replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  $('#methodName').textContent = scope.qualified;
  $('.method-details').open = false;
  $('#scopeKind').textContent = scope.kind;
  $('#scopeSummary').textContent = `${scope.stats.calls} explicit calls · ${scope.stats.branches} branch arms / expression decisions · ${scope.stats.unresolved} unknown targets. ${scope.kind === 'module' ? 'Top-level source, including definition-time operations.' : 'All local statements are represented; open a call for its own logic.'}`;
  if (scope.decorators.length) $('#scopeSummary').append(document.createTextNode(' Decorators: ' + scope.decorators.join(', ')));
  $('#flow').replaceChildren();
  if (state.stack.length) {
    const frame = state.stack.at(-1), strip = el('div','caller-strip');
    strip.append(el('span','', '↳ From ' + scopeName(frame.invoker || frame.scope) + ' · return → ' + frame.destination), button('Back to caller', 'quiet-button', returnToCaller));
    $('#flow').append(strip);
  }
  appendScopeFlow($('#flow'), scope, [scope.id], 0);
  $('#flow').append(el('div', 'scope-end', ['module','class'].includes(scope.kind) ? 'End of body · definitions remain individually accessible.' : (scope.nextCursor!==null?'More statements are available using Load more statements above.':'End of body · if control reaches here, Python returns None (or the generator terminates).')));
  renderPayloads(); navigation(); await showSource(scope.span, scope.qualified, 'Original source for this scope. Select an operation to focus its evidence.');
  if(request!==selectionRequest || captured!==model)return false;
  $('.review').scrollTop = 0;
  const activeNav = $('#navigation .nav-item.active');
  if (activeNav) $('#navigation').scrollTop += activeNav.getBoundingClientRect().top - $('#navigation').getBoundingClientRect().top - 100;
  history.replaceState(null, '', '#' + encodeURIComponent(id));
  if (typeof syncWorkflowMethod === 'function') syncWorkflowMethod(id);
  return true;
}

async function enterScope(id, call) {
  const frame = { scope: state.scope, invoker: call.scope || state.scope, scroll: $('.review').scrollTop, dom: [...$('#flow').childNodes], focus: state.focus, destination: call.destination, selectedElement: state.selectedElement };
  state.stack.push(frame);
  await chooseScope(id, {keepStack:true});
}
async function returnToCaller() {
  const frame = state.stack.pop(); if (!frame) return;
  if(!await chooseScope(frame.scope, {keepStack:true}))return;
  state.focus = frame.focus; state.selectedElement = frame.selectedElement;
  $('#flow').replaceChildren(...frame.dom); renderPayloads();
  $('.review').scrollTop = frame.scroll;
  if (frame.focus) await showSource(frame.focus.span, frame.focus.title, frame.focus.details);
  frame.selectedElement?.querySelector('button')?.focus({preventScroll:true});
}

function renderList(nodes, scope, ancestry, depth) {
  const list = el('div','flow-list');
  if (!nodes.length) { list.append(el('div','branch-note','Continue.')); return list; }
  for (const node of nodes) list.append(renderNode(node, scope, ancestry, depth));
  return list;
}
function renderNode(node, scope, ancestry, depth) {
  const host = el('section', 'operation' + (node.branches.length ? ' branching' : '') + (node.terminal ? ' terminal' : '') + (node.unreachable ? ' unreachable' : '') + (node.note ? ' source-note' : ''));
  host.dataset.node = node.id; host.dataset.scope = scope.id;
  let alternative = null;
  const card = el('div','op-card'); const head = button('', 'op-head', () => selectNode(node, scope, host));
  head.title = 'Inspect original source'; head.append(el('span','op-glyph',icon(node.kind)),el('span','op-label',node.label),el('span','op-line',`L${node.span.start}`));
  card.append(head);
  if (node.unreachable) card.append(el('div','op-description','Unreachable after the preceding unconditional exit in this block.'));
  if (node.unsupported) card.append(el('div','error','Source retained · behavioral model unsupported.'));
  if (node.expression) card.append(el('div','op-description expression-value',node.expression));
  if (node.writes.length && !['Assign','AnnAssign'].includes(node.kind)) card.append(el('div','op-description', 'Writes ' + node.writes.join(', ')));
  if (node.effects.length) card.append(el('div','effects',node.effects.join(' · ')));
  if (node.definition) {
    const definition = model.scopes[node.definition];
    const row = el('div','op-description');
    row.append(button((definition.kind === 'class' ? 'Inspect class body' : 'Inspect definition') + ' ↗', 'scope-jump', () => enterScope(definition.id, {destination:'definition site'})));
    card.append(row);
  }
  if (node.decisions.length) {
    const decisions = el('div','expression-decisions');
    for (const decision of node.decisions) {
      const box = el('div','expression-decision');
      box.append(button(decision.label, '', () => showSource(decision.span, 'Expression control flow', (decision.alternatives || []).join(' · '))));
      if (decision.alternatives) box.append(el('div','decision-arms',decision.alternatives.join(' / ')));
      if (decision.target) box.append(button('Open lambda ↗','scope-jump',()=>enterScope(decision.target,{destination:'lambda definition'})));
      decisions.append(box);
    }
    card.append(decisions);
  }
  if (node.calls.length) {
    const calls = el('div','calls');
    if (node.calls.length > 1) calls.append(el('div','source-peek','Expression call sites · nested arguments shown before their enclosing call'));
    for (const call of node.calls) calls.append(renderCall(call, scope, ancestry, depth));
    card.append(calls);
  }
  if (node.branches.length) {
    const branches = el('div','branches');
    for (const branch of node.branches) {
      if (node.kind === 'If' && branch.label === 'False' && branch.nodes.length === 1 && branch.nodes[0].kind === 'If' && branch.nodes[0].span.col === node.span.col) { alternative = branch.nodes[0]; continue; }
      if (!branch.nodes.length) { branches.append(button(branch.label + ' → ' + (branch.note || 'continue'), 'branch-outcome',()=>showSource(node.span,node.label,branch.label + ': ' + (branch.note || 'continue')))); continue; }
      const region = el('details','branch'); region.open = true;
      const summary = el('summary'); summary.append(el('span','',branch.label),el('span','branch-count',`${walk(branch.nodes).length} operations`));
      region.append(summary);
      if (branch.note) region.append(el('div','branch-note',branch.note));
      if (branch.nodes.length) region.append(renderList(branch.nodes, scope, ancestry, depth)); branches.append(region);
    }
    card.append(branches);
  }
  host.append(card);
  if (alternative) {
    const continuation = el('div','elif-continuation');
    continuation.append(el('div','branch-note','False → test the next condition. A taken arm skips remaining alternatives.'),renderNode(alternative,scope,ancestry,depth));
    host.append(continuation);
  }
  return host;
}
function selectNode(node, scope, host) {
  state.selectedElement?.classList.remove('selected'); state.selectedElement = host; host.classList.add('selected');
  const details = [node.kind, node.reads.length ? 'Reads: ' + node.reads.join(', ') : '', node.writes.length ? 'Writes: ' + node.writes.join(', ') : '', ...node.effects, node.terminal ? (node.kind === 'Return' ? 'Leaves this function; enclosing cleanup still applies.' : 'Transfers control; inspect enclosing loops and exception/cleanup regions.') : ''].filter(Boolean).join('\n');
  showSource(node.span,node.label,details); announce(`Source selected: ${scope.file}, line ${node.span.start}`);
}

function renderCall(call, scope, ancestry, depth) {
  const host = el('div','call'); host.dataset.call = call.id;
  const row = el('div','call-row'); row.append(el('span','call-title',call.name + (call.execution?.startsWith('deferred') ? ' · deferred' : call.execution?.startsWith('background') ? ' · background' : call.awaited ? ' · await' : '') + (call.conditional ? ' · conditional/deferred' : '')), el('span','status '+call.status,call.status === 'supported' ? 'source-linked' : call.status));
  const contents = el('div'); contents.hidden = true;
  const toggle = button(call.targets.length ? 'Open call ↳' : 'Inspect ?', 'call-open', async () => {
    const opening = contents.hidden;
    if (opening && !contents.childNodes.length) {
      toggle.disabled=true;
      try {await fillCall(contents,call,scope,ancestry,depth);}
      catch(error){contents.replaceChildren();announce(error.message);return;}
      finally {toggle.disabled=false;}
    }
    contents.hidden = !opening; toggle.textContent = opening ? 'Close ↥' : call.targets.length ? 'Open call ↳' : 'Inspect ?'; toggle.setAttribute('aria-expanded', String(opening));

  }); toggle.setAttribute('aria-expanded','false'); toggle.dataset.closedLabel = call.targets.length ? 'Open call ↳' : 'Inspect ?'; row.append(toggle); host.append(row,contents); return host;
}
async function fillCall(host,call,scope,ancestry,depth) {
  const captured=model;
  for(const id of call.targets) await ensureScope(id,captured);
  if(captured!==model) return;
  const info = el('div','call-detail');
  if (call.execution && call.execution !== 'ordinary call') host.append(el('div','call-execution',call.execution));
  info.append(document.createTextNode(call.reason + '. '),button('Call-site evidence','scope-jump',()=>showSource(call.span,call.expression,call.reason + '\nReturn destination: ' + call.destination)));
  host.append(info);
  if (!call.targets.length) {
    host.append(el('div','call-detail','Arguments: ' + (call.arguments.join(' · ') || '(none)')));
    host.append(el('div','call-detail','Return destination: ' + call.destination + '. May raise; external effects and dispatch are not established by this index.'));
    return;
  }
  for (const targetId of call.targets) {
    const target = model.scopes[targetId], box = el('div','call-expansion');
    const header = el('div','callee-header'); header.append(el('span','',target.qualified + ' · ' + target.file + ':' + target.span.start)); box.append(header);
    const map = el('div','mapping');
    for (const pair of call.bindings[targetId] || []) {
      const row = el('div','mapping-row');
      row.append(el('span','',pair.argument + ' → '),button(pair.parameter,'',()=>{showSource(target.span,target.qualified,'Parameter mapping from '+call.span.file+':'+call.span.start+' · '+pair.argument+' → '+pair.parameter);}),el('span','',pair.certainty === 'syntax' ? '' : '(' + pair.certainty + ')')); map.append(row);
    }
    if (!map.childNodes.length) map.textContent = 'No explicit parameters to map.';
    box.append(map);
    if (ancestry.includes(targetId)) {
      box.append(el('div','recursive-note','↻ Recursive reference to ' + target.qualified + '. Body is already open above; this call returns to ' + call.destination + '.'));
      box.append(button('Focus method','scope-jump',()=>enterScope(targetId,call)));
    } else if (depth >= 1) {
      box.append(el('div','call-detail',`${target.stats.branches} branch arms / decisions · ${target.stats.calls} calls. Open at full reading width; the caller and return point stay pinned.`));
      box.append(button('Read method with caller pinned →','quiet-button',()=>enterScope(targetId,call)));
    } else if (target.kind === 'class') {
      box.append(el('div','call-detail','Constructor target: class body is definition-time source. Instance construction may dispatch __new__, __init__, and metaclass hooks.'));
      const constructor = Object.values(model.scopes).find(s=>s.parent === targetId && s.name === '__init__');
      if (constructor) box.append(button('Read possible __init__ →','quiet-button',()=>enterScope(constructor.id,call)));
      box.append(button('Inspect class definition','scope-jump',()=>enterScope(targetId,call)));
    } else {
      header.append(button('Source','quiet-button',()=>showSource(target.span,target.qualified,'Original called function source.')));
      appendScopeFlow(box,target,[...ancestry,targetId],depth+1);
    }
    box.append(el('div','resume',(call.execution?.startsWith('deferred') ? '↩ Call produces a deferred object → ' : '↩ On normal return → ') + call.destination + ' · caller resumes at ' + call.span.file + ':' + call.span.end + '. Exceptions follow the enclosing handler / propagate.'));
    host.append(box);
  }
}

function renderPayloads() {
  const scope = model.scopes[state.scope], host = $('#payloadSummary');
  host.replaceChildren();
  $('#suppliedInputs').textContent = '';
  $('#returnDetails').textContent = '';
  host.hidden = ['module', 'class'].includes(scope.kind);
  if (host.hidden) return;
  const input = el('div', 'payload-block'), output = el('div', 'payload-block');
  input.append(el('span', 'payload-label', 'Comes in'));
  const params = scope.params.filter(p => !['self', 'cls'].includes(p.name));
  const supplied = params.filter(p => /^Depends\(/.test(p.default || ''));
  $('#suppliedInputs').textContent = supplied.length ? 'Provided by the app: ' + supplied.map(p => p.name + (p.annotation ? ': ' + p.annotation : '')).join(', ') : '';
  for (const param of params.filter(p => !supplied.includes(p))) {
    const prefix = param.kind === 'varargs' ? '*' : param.kind === 'kwargs' ? '**' : '';
    input.append(el('code', 'payload-value', prefix + param.name + (param.annotation ? ': ' + param.annotation : '')));
  }
  if (params.length === supplied.length) input.append(el('span', 'payload-empty', supplied.length ? 'Provided by the app' : 'No input'));
  output.append(el('span', 'payload-label', 'Goes out'));
  const boundary = scope.output;
  $('#returnDetails').textContent = boundary?.returns.length ? 'Return expressions: ' + [...new Set(boundary.returns)].join(' | ') : '';
  if (boundary?.responseModel && boundary.responseModel !== 'None') {
    output.append(el('code', 'payload-value', boundary.responseModel));
    output.append(el('span', 'payload-empty', 'Declared response'));
  } else if (scope.generator) {
    output.append(el('code', 'payload-value', boundary?.annotation || (scope.async ? 'Async generator' : 'Generator')));
  } else if (boundary?.annotation) {
    output.append(el('code', 'payload-value', boundary.annotation));
  } else if (boundary?.returns.length) {
    const values = [...new Set(boundary.returns)];
    const simple = values.every(v => /^[\w.]+$/.test(v));
    output.append(el('code', 'payload-value', simple ? values.join(' or ') : 'Type not declared'));
    output.append(el('span', 'payload-empty', 'From return statements'));
  } else {
    output.append(el('span', 'payload-empty', 'No explicit return value'));
  }
  host.append(input, output);
}
function escaped(str) { return str.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function syntax(line) {
  const regex = /#[^\n]*|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:async|await|def|class|return|if|elif|else|raise|try|except|finally|from|import|for|while|with|as|match|case|in|None|True|False|not|and|or|yield|break|continue|assert|lambda|pass)\b|\b\d+(?:\.\d+)?\b/g;
  let out='',end=0,match;
  while((match=regex.exec(line))) { out+=escaped(line.slice(end,match.index)); const token=match[0],type=token.startsWith('#')?'comment':/^["']/.test(token)?'str':/^\d/.test(token)?'num':'key'; out+=`<span class="tok-${type}">${escaped(token)}</span>`; end=match.index+token.length; }
  return out+escaped(line.slice(end));
}
async function showSource(span,title,details='',preserveScroll=false,pageStart=null) {
  const request=++sourceRequest, captured=model;
  state.focus={span,title,details};
  const start=pageStart || (state.sourceWhole?1:Math.max(1,span.start-4));
  try {
    const result=await api('/api/source',{snapshot:captured.snapshotId,file:span.file,start});
    if(request!==sourceRequest || captured!==model) return;
    $('#sourceFile').textContent=span.file;
    $('#sourceContext').replaceChildren(el('strong','',title),el('div','',`Evidence lines ${span.start}–${span.end} · showing ${result.span.start}–${result.span.end}`));
    const lines=result.source.split('\n'), code=$('#sourceCode'), oldScroll=code.scrollTop;
    code.replaceChildren(); code.classList.toggle('wrap-code',state.wrap);
    lines.forEach((value,index)=>{
      const number=start+index;
      const line=el('div','code-line'+(number>=span.start&&number<=span.end?' focus':''));line.dataset.line=String(number);
      const content=el('span','line-content');content.innerHTML=syntax(value)||' ';
      line.append(el('span','line-number',String(number)),content);code.append(line);
    });
    code.scrollTop=preserveScroll?oldScroll:0;
    const host=$('#sourceDetails');host.replaceChildren();
    for(const line of details.split('\n').filter(Boolean))host.append(el('div','',line));
    const controls=el('div','source-peek');
    if(start>1)controls.append(button('Previous source lines','scope-jump',()=>showSource(span,title,details,false,Math.max(1,start-80))));
    if(result.span.end<result.totalLines) controls.append(button('Next source lines →','scope-jump',()=>showSource(span,title,details,false,result.span.end+1)));
    controls.append(button('Start of file','scope-jump',()=>showSource(span,title,details,false,1)));
    const entireSelection=span.start>=start&&span.end<=result.span.end;
    controls.append(button(entireSelection?'Copy exact selection':'Copy visible source','scope-jump',async()=>{
      try {await navigator.clipboard.writeText(entireSelection?lines.slice(span.start-start,span.end-start+1).join('\n'):result.source);announce('Source copied');}
      catch {announce('Clipboard unavailable; select and copy the source.');}
    }));
    controls.append(button(state.wrap?'Unwrap lines':'Wrap lines','scope-jump',()=>{state.wrap=!state.wrap;showSource(span,title,details,true,start);}));
    host.append(controls);$('#snapshotLabel').textContent='Snapshot '+captured.snapshotId.slice(0,8);
  } catch(error) {if(request===sourceRequest){$('#sourceCode').replaceChildren(el('p','error',error.message));announce(error.message);}}
}
function coverage() {
  const c=model.coverage, host=$('#coveragePanel');host.replaceChildren(el('h2','','Source coverage'),el('p','',model.root));
  const grid=el('div','coverage-grid');
  for(const [value,label] of [[`${format(c.files)}/${format(c.discovered)}`,'Python files parsed'],[format(c.definitions),'functions, methods & lambdas'],[`${format(c.representedStatements)}/${format(c.statements)}`,'statements represented'],[`${format(c.representedCalls)}/${format(c.calls)}`,'explicit call sites represented']]) {const stat=el('div','coverage-stat');stat.append(el('strong','',value),el('span','',label));grid.append(stat);}host.append(grid);
  host.append(el('p','',Object.entries(c.statuses).map(([k,v])=>`${format(v)} ${k}`).join(' · ')));
  for(const limit of model.limits)host.append(el('p','',limit));
  for(const [label,category] of [['Excluded paths','excluded'],['Parse errors','errors'],['Unmodeled call syntax','unmodeledCalls'],['Changed methods','changedMethods'],['Previous methods','previousMethods'],['Known callers','knownCallers'],['Possible impact','possibleImpact']]) {
    const section=el('details');section.append(el('summary','',label));
    const content=el('div');section.append(content);host.append(section);
    section.addEventListener('toggle',()=>{if(section.open&&!content.childNodes.length)loadDiagnostics(content,category);});
  }
}
async function loadDiagnostics(host,category,cursor=0) {
  const captured=model;
  try {
    const result=await api('/api/diagnostics',{snapshot:captured.snapshotId,category,cursor,limit:25});
    if(captured!==model)return;
    host.replaceChildren(el('p','',result.rows.total+' records'));
    for(const row of result.rows.items) {
      const label=[row.name,row.file||row.path||row.span?.file,row.reason||row.message||row.expression].filter(Boolean).join(' · ');
      if(row.id&&category!=='previousMethods')host.append(button(label,'scope-jump',()=>chooseScope(row.id)));
      else if(row.id&&model.changes?.baseSnapshotId){const link=el('a','scope-jump',label);link.href='?snapshot='+encodeURIComponent(model.changes.baseSnapshotId)+'#'+encodeURIComponent(row.id);host.append(link);}
      else host.append(el('p','',label));
    }
    if(cursor)host.append(button('Previous records','quiet-button',()=>loadDiagnostics(host,category,Math.max(0,cursor-25))));
    if(result.rows.nextCursor!==null)host.append(button('More records →','quiet-button',()=>loadDiagnostics(host,category,result.rows.nextCursor)));
  }catch(error){host.replaceChildren(el('p','error',error.message));}
}
async function load(refresh=false) {
  const b=$('#refreshButton'); b.disabled=true;b.textContent=refresh?'Reading source…':'Indexing…';
  try {
    const requestedSnapshot=new URLSearchParams(location.search).get('snapshot');
    if(!sessionToken)sessionToken=(await api('/api/session')).token;
    const summary=refresh?await api('/api/reindex',{}, {method:'POST',headers:{'X-Threadline-Token':sessionToken}}):await api('/api/summary', requestedSnapshot?{snapshot:requestedSnapshot}:{});
    model={...summary,scopes:{},files:{},generatedWorkflows:{}};
    ++selectionRequest; ++sourceRequest;
    for(const scope of summary.entrypoints.items)model.scopes[scope.id]=scope;
    if(refresh && requestedSnapshot) history.replaceState(null,'',location.pathname+location.hash);
    $('#projectName').textContent=model.project;$('#fileCount').textContent=model.coverage.files+' files';
    coverage();
    let preferred=state.scope || decodeURIComponent(location.hash.slice(1));
    if(!preferred) preferred=summary.entrypoints.items[0]?.id;
    if(preferred) {if(!await chooseScope(preferred)) {preferred=summary.entrypoints.items[0]?.id;if(preferred)await chooseScope(preferred);}}else $('#flow').replaceChildren(el('p','error','No readable Python source. Open Coverage to inspect parse errors and excluded files.'));
    if (typeof initializeWorkflows === 'function') await initializeWorkflows(refresh);
    announce(refresh?'Source refreshed. Flow and source refer to the same snapshot.':'Repository ready.');
  }catch(error){$('#flow').replaceChildren(el('p','error','Unable to load the source index: '+error.message));}
  finally{b.disabled=false;b.textContent='↻ Refresh source';}
}
let searchTimer; $('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>navigation(),150);});$('#kindFilter').addEventListener('change',()=>navigation());
$('#coverageButton').addEventListener('click',()=>{const h=$('#coveragePanel');h.hidden=!h.hidden;$('#coverageButton').setAttribute('aria-expanded',String(!h.hidden));if(!h.hidden)h.focus();});
$('#refreshButton').addEventListener('click',()=>load(true));
$('#expandBranches').addEventListener('click',()=>{$('#flow').querySelectorAll('details.branch').forEach(d=>d.open=true);});
$('#collapseCalls').addEventListener('click',()=>{$('#flow').querySelectorAll('.call').forEach(call=>{const content=call.children[1];content.hidden=true;const b=call.querySelector(':scope > .call-row > .call-open');b.textContent=b.dataset.closedLabel;b.setAttribute('aria-expanded','false');});});
$('#clearFocus').addEventListener('click',()=>{const s=model.scopes[state.scope];showSource(s.span,s.qualified,'Original source for the selected method.');});
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();setWorkflowMode('methods');$('#search').focus();}if(event.key==='Escape'){if(!$('#coveragePanel').hidden)$('#coverageButton').focus();$('#coveragePanel').hidden=true;$('#coverageButton').setAttribute('aria-expanded','false');}});
load();
