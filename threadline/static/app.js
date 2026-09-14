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

function navigation() {
  const query = $('#search').value.toLowerCase().trim();
  const filter = $('#kindFilter').value;
  const oldOpen = new Set([...$('#navigation').querySelectorAll('details[open]')].map(d => d.dataset.file));
  const host = $('#navigation'); host.replaceChildren();
  const files = new Map();
  for (const scope of Object.values(model.scopes)) {
    if (query && !`${scope.qualified} ${scope.file} ${scope.decorators.join(' ')}`.toLowerCase().includes(query)) continue;
    if (filter === 'callable' && ['module', 'class'].includes(scope.kind)) continue;
    if (['class', 'module'].includes(filter) && scope.kind !== filter) continue;
    if (filter === 'unknown' && !scope.stats.unresolved) continue;
    if (!files.has(scope.file)) files.set(scope.file, []);
    files.get(scope.file).push(scope);
  }
  if (!files.size) host.append(el('p', 'nav-empty', 'No matching definitions.'));
  for (const [file, scopes] of [...files.entries()].sort((a,b) => a[0].localeCompare(b[0]))) {
    const group = el('details', 'file-group'); group.dataset.file = file;
    group.open = Boolean(query) || oldOpen.has(file) || file === model.scopes[state.scope]?.file;
    const summary = el('summary'); summary.title = file; summary.append(el('span', 'file-name', file), el('span', 'file-count', String(scopes.length))); group.append(summary);
    scopes.sort((a,b) => a.span.start - b.span.start);
    for (const scope of scopes) {
      const item = button('', 'nav-item' + (scope.id === state.scope ? ' active' : ''), () => chooseScope(scope.id));
      item.dataset.scope = scope.id; item.title = `${scope.qualified} · ${scope.kind} · line ${scope.span.start}`;
      item.append(el('span', 'nav-icon', scope.kind === 'class' ? 'C' : scope.kind === 'module' ? '▤' : 'ƒ'), el('span', 'name', scope.kind === 'module' ? 'Module body' : scope.qualified));
      if (scope.stats.unresolved) item.append(el('span', 'nav-unknown', '?'));
      group.append(item);
    }
    host.append(group);
  }
}

function chooseScope(id, opts={}) {
  if (!model.scopes[id]) return;
  if (!opts.keepStack) state.stack = [];
  state.scope = id; state.focus = null; state.sourceWhole = false; state.selectedElement = null;
  const scope = model.scopes[id];
  $('#scopePath').textContent = scope.file + (scope.parent && model.scopes[scope.parent]?.kind !== 'module' ? ' / ' + scopeName(scope.parent) : '');
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
  $('#flow').append(renderList(scope.flow, scope, [scope.id], 0));
  $('#flow').append(el('div', 'scope-end', ['module','class'].includes(scope.kind) ? 'End of body · definitions remain individually accessible.' : 'End of body · if control reaches here, Python returns None (or the generator terminates).'));
  renderPayloads(); navigation(); showSource(scope.span, scope.qualified, 'Original source for this scope. Select an operation to focus its evidence.');
  $('.review').scrollTop = 0;
  const activeNav = $('#navigation .nav-item.active');
  if (activeNav) $('#navigation').scrollTop += activeNav.getBoundingClientRect().top - $('#navigation').getBoundingClientRect().top - 100;
  history.replaceState(null, '', '#' + encodeURIComponent(id));
  if (typeof syncWorkflowMethod === 'function') syncWorkflowMethod(id);
}

function enterScope(id, call) {
  const frame = { scope: state.scope, invoker: call.scope || state.scope, scroll: $('.review').scrollTop, dom: [...$('#flow').childNodes], focus: state.focus, destination: call.destination, selectedElement: state.selectedElement };
  state.stack.push(frame);
  chooseScope(id, {keepStack:true});
}
function returnToCaller() {
  const frame = state.stack.pop(); if (!frame) return;
  chooseScope(frame.scope, {keepStack:true});
  state.focus = frame.focus; state.selectedElement = frame.selectedElement;
  $('#flow').replaceChildren(...frame.dom); renderPayloads();
  $('.review').scrollTop = frame.scroll;
  if (frame.focus) showSource(frame.focus.span, frame.focus.title, frame.focus.details);
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
  const toggle = button(call.targets.length ? 'Open call ↳' : 'Inspect ?', 'call-open', () => {
    const opening = contents.hidden;
    if (opening && !contents.childNodes.length) fillCall(contents,call,scope,ancestry,depth);
    contents.hidden = !opening; toggle.textContent = opening ? 'Close ↥' : call.targets.length ? 'Open call ↳' : 'Inspect ?'; toggle.setAttribute('aria-expanded', String(opening));

  }); toggle.setAttribute('aria-expanded','false'); toggle.dataset.closedLabel = call.targets.length ? 'Open call ↳' : 'Inspect ?'; row.append(toggle); host.append(row,contents); return host;
}
function fillCall(host,call,scope,ancestry,depth) {
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
      box.append(renderList(target.flow,target,[...ancestry,targetId],depth+1));
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
function showSource(span,title,details='',preserveScroll=false) {
  state.focus = {span,title,details};
  const file = model.files[span.file]; if(!file) return;
  $('#sourceFile').textContent = span.file;
  $('#sourceContext').replaceChildren(el('strong','',title),el('div','',`Lines ${span.start}–${span.end}`));
  const lines=file.source.split('\n');
  const enclosing=Object.values(model.scopes).filter(s=>s.file===span.file && s.span.start<=span.start && s.span.end>=span.end).sort((a,b)=>(a.span.end-a.span.start)-(b.span.end-b.span.start))[0];
  const start=state.sourceWhole?1:Math.max(1,Math.min(span.start-4,enclosing?.span.start || span.start));
  const end=state.sourceWhole?lines.length:Math.min(lines.length,Math.max(span.end+5,Math.min(enclosing?.span.end || span.end,span.end+70)));
  const code=$('#sourceCode'), oldScroll=code.scrollTop; code.replaceChildren(); code.classList.toggle('wrap-code',state.wrap);
  for(let number=start;number<=end;number++) {
    const line=el('div','code-line'+(number>=span.start && number<=span.end?(span.end-span.start>12?' scope-focus':' focus'):''));
    line.dataset.line=String(number);
    const content=el('span','line-content'); content.innerHTML=syntax(lines[number-1]) || ' ';
    line.append(el('span','line-number',String(number)),content); code.append(line);
  }
  if(preserveScroll) code.scrollTop=oldScroll;
  else { const selectedLine=code.querySelector('[data-line="'+span.start+'"]');code.scrollTop=selectedLine?Math.max(0,selectedLine.getBoundingClientRect().top-code.getBoundingClientRect().top+code.scrollTop-46):0; }
  const detailHost=$('#sourceDetails'); detailHost.replaceChildren();
  for(const line of details.split('\n').filter(Boolean)) detailHost.append(el('div','',line));
  const buttonRow=el('div','source-peek');
  buttonRow.append(button(state.sourceWhole?'Show focused source':'Show entire file','scope-jump',()=>{state.sourceWhole=!state.sourceWhole;showSource(span,title,details);}),document.createTextNode(' · '),button('Copy exact selection','scope-jump',async()=>{try{await navigator.clipboard.writeText(lines.slice(span.start-1,span.end).join('\n'));announce('Source copied');}catch{announce('Clipboard unavailable; select and copy the source.');}}));
  buttonRow.append(document.createTextNode(' · '),button(state.wrap?'Unwrap lines':'Wrap lines','scope-jump',()=>{state.wrap=!state.wrap;showSource(span,title,details);}));
  detailHost.append(buttonRow);
  $('#snapshotLabel').textContent='Snapshot '+file.hash.slice(0,8);
}
function coverage() {
  const c=model.coverage, host=$('#coveragePanel');host.replaceChildren(el('h2','','Source coverage'),el('p','',model.root));
  const grid=el('div','coverage-grid');
  for(const [value,label] of [[`${format(c.files)}/${format(c.discovered)}`,'Python files parsed'],[format(c.definitions),'functions, methods & lambdas'],[`${format(c.representedStatements)}/${format(c.statements)}`,'statements represented'],[`${format(c.representedCalls)}/${format(c.calls)}`,'explicit call sites represented']]) {const stat=el('div','coverage-stat');stat.append(el('strong','',value),el('span','',label));grid.append(stat);}host.append(grid);
  host.append(el('p','',Object.entries(c.statuses).map(([k,v])=>`${format(v)} ${k}`).join(' · ')));
  const types=el('p','',Object.entries(c.kinds).map(([k,v])=>`${format(v)} ${k}`).join(' · '));host.append(types);
  for(const limit of model.limits)host.append(el('p','',limit));
  for(const [label,rows] of [['Excluded paths',model.excluded.map(x=>x.path+' — '+x.reason)],['Parse errors',model.errors.map(x=>x.file+' — '+x.message)],['Unmodeled call syntax',c.unmodeledCalls.map(x=>x.span.file+':'+x.span.start+' '+x.expression)]]) {const d=el('details'),s=el('summary','',`${label} (${rows.length})`),list=el('ul');rows.forEach(row=>list.append(el('li','',row)));d.append(s,list);host.append(d);}
}
async function load(refresh=false) {
  const b=$('#refreshButton'); b.disabled=true;b.textContent=refresh?'Reading source…':'Indexing…';
  try {
    const requestedSnapshot=new URLSearchParams(location.search).get('snapshot');
    const indexUrl=!refresh&&requestedSnapshot?'/api/index?snapshot='+encodeURIComponent(requestedSnapshot):'/api/index';
    const response=await fetch(refresh?'/api/reindex':indexUrl,{method:refresh?'POST':'GET'});if(!response.ok)throw new Error(`HTTP ${response.status}`);
    model=await response.json();
    if(refresh && requestedSnapshot) history.replaceState(null,'',location.pathname+location.hash);
    $('#projectName').textContent=model.project;$('#fileCount').textContent=model.coverage.files+' files';
    coverage();
    let preferred=state.scope || decodeURIComponent(location.hash.slice(1));
    if(!model.scopes[preferred]) preferred=model.entrypoints?.find(e=>model.scopes[e.id]?.kind!=='module')?.id || Object.values(model.scopes).find(s=>['function','method'].includes(s.kind))?.id || Object.keys(model.scopes)[0];
    if(preferred) chooseScope(preferred);else $('#flow').replaceChildren(el('p','error','No readable Python source. Open Coverage to inspect parse errors and excluded files.'));
    if (typeof initializeWorkflows === 'function') initializeWorkflows(refresh);
    announce(refresh?'Source refreshed. Flow and source refer to the same snapshot.':'Repository ready.');
  }catch(error){$('#flow').replaceChildren(el('p','error','Unable to load the source index: '+error.message));}
  finally{b.disabled=false;b.textContent='↻ Refresh source';}
}
$('#search').addEventListener('input',navigation);$('#kindFilter').addEventListener('change',navigation);
$('#coverageButton').addEventListener('click',()=>{const h=$('#coveragePanel');h.hidden=!h.hidden;$('#coverageButton').setAttribute('aria-expanded',String(!h.hidden));});
$('#refreshButton').addEventListener('click',()=>load(true));
$('#expandBranches').addEventListener('click',()=>{$('#flow').querySelectorAll('details.branch').forEach(d=>d.open=true);});
$('#collapseCalls').addEventListener('click',()=>{$('#flow').querySelectorAll('.call').forEach(call=>{const content=call.children[1];content.hidden=true;const b=call.querySelector(':scope > .call-row > .call-open');b.textContent=b.dataset.closedLabel;b.setAttribute('aria-expanded','false');});});
$('#clearFocus').addEventListener('click',()=>{const s=model.scopes[state.scope];showSource(s.span,s.qualified,'Original source for the selected method.');});
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('#search').focus();}if(event.key==='Escape'){$('#coveragePanel').hidden=true;$('#coverageButton').setAttribute('aria-expanded','false');}});
load();
