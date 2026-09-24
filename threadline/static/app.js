'use strict';
let model;
const $ = selector => document.querySelector(selector);
const state = { scope: null, focus: null, stack: [], selectedElement: null, sourceWhole: false, wrap: true };
const format = value => Number(value).toLocaleString();
function el(tag, cls, content) { const node = document.createElement(tag); if (cls) node.className = cls; if (cls === 'op-glyph') node.setAttribute('aria-hidden','true'); if (content !== undefined) node.textContent = content; return node; }
function button(label, cls, handler) { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', handler); return b; }
function walk(nodes) { return nodes.flatMap(node => [node, ...node.branches.flatMap(branch => walk(branch.nodes))]); }
function scopeName(id) { return model.scopes[id]?.qualified || id; }
function announce(message) { $('#announcement').textContent = message; }
function clearError(key) {
  const host = $('#reviewError');
  if (key && host.dataset.operation !== key) return;
  host.hidden = true; host.replaceChildren();
}
function reportError(error, retry, key) {
  const host = $('#reviewError');
  host.dataset.operation = key;
  const message = el('p', '', error.message || String(error));
  message.setAttribute('role', 'alert');
  host.replaceChildren(message);
  if (retry) host.append(button('Retry', 'quiet-button', () => { clearError(key); retry(); }));
  host.append(button('Dismiss', 'quiet-button', () => clearError(key)));
  host.hidden = false;
}
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
  const page = await api('/api/scope', {symbol:id, snapshot:captured.snapshotId, limit:20, shallow:1});
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
        const page = await api('/api/scope', {symbol:scope.id, snapshot:captured.snapshotId, cursor:scope.nextCursor, limit:20, shallow:1});
        if (captured !== model) return;
        for (const [key, value] of Object.entries(page.references)) captured.scopes[key] ||= value;
        const canonical=captured.scopes[scope.id];
        const known=new Set(canonical.flow.map(node=>node.id));
        canonical.flow.push(...page.flow.items.filter(node=>!known.has(node.id)));canonical.nextCursor=page.flow.nextCursor;
        scope.nextCursor=page.flow.nextCursor;
        if(canonical.nextCursor===null&&state.scope===scope.id)$('#flow .scope-end').textContent='End of body · if control reaches here, Python returns None (or the generator terminates).';
        clearError('statements');
        const extra=el('div'); more.replaceWith(extra);
        appendScopeFlow(extra, {...scope, flow:page.flow.items}, ancestry, depth);
      } catch(error) {if(captured===model) reportError(error,()=>more.click(),'statements'); more.disabled=false;}
    });
    host.append(more);
  }
}
const startLabels={http:'HTTP routes',commands:'CLI commands',tasks:'Tasks & callbacks',methods:'Functions & methods'};
let startRequest=0;
function startButton(row) {
  const item=button('', 'start-item',()=>startReview(row.id));item.dataset.scope=row.id;
  item.append(el('strong','',row.label),el('span','start-method',row.label===row.name?row.file:row.name+' · '+row.file));
  return item;
}
let catalogPage='endpoints';
const catalogTitles={endpoints:'Endpoints',commands:'Commands & tasks',methods:'Modules & methods'};
async function loadStartGroup(category,host,cursor=0,method='') {
  const captured=model, request=String(Number(host.dataset.request||0)+1);
  host.dataset.request=request;
  host.replaceChildren(el('p','source-peek','Loading…'));
  try {
    const result=await api('/api/starts',{snapshot:captured.snapshotId,category,cursor,limit:20,...(method?{method}:{})});
    if(captured!==model || !host.isConnected || host.dataset.request!==request)return;
    renderStartGroup(category,host,result.results,cursor,method);
  } catch(error) {if(captured===model && host.dataset.request===request)host.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>loadStartGroup(category,host,cursor,method)));}
}
function renderStartGroup(category,host,page,cursor=0,method='') {
  host.replaceChildren();
  for(const row of page.items)host.append(startButton(row));
  if(!page.total)host.append(el('p','source-peek','No '+startLabels[category].toLowerCase()+' in this snapshot.'));
  const controls=el('div','catalog-pagination');
  controls.append(el('span','source-peek',page.total?`${cursor+1}–${cursor+page.items.length} of ${page.total}`:'0 results'));
  if(cursor)controls.append(button('Previous','quiet-button',()=>loadStartGroup(category,host,Math.max(0,cursor-20),method)));
  if(page.nextCursor!==null)controls.append(button('More '+startLabels[category].toLowerCase(),'quiet-button',()=>loadStartGroup(category,host,page.nextCursor,method)));
  host.append(controls);
}
async function modulePicker(host, initialFile=null) {
  host.id='moduleBrowser';
  let selectedFile=initialFile, request=0, timer;
  const heading=el('div','module-heading'), filter=el('input','module-filter'), list=el('div','module-results');
  filter.type='search';list.id='moduleResults';
  host.replaceChildren(heading,filter,list);
  async function loadModules(cursor=0,focusHeading=false) {
    const current=++request, captured=model, file=selectedFile;
    filter.placeholder=file?'Filter methods in this module…':'Filter modules…';
    filter.setAttribute('aria-label',file?'Filter methods in selected module':'Filter modules');
    list.replaceChildren(el('p','source-peek','Loading…'));
    try {
      const result=await api('/api/modules',{snapshot:captured.snapshotId,q:filter.value,cursor,limit:20,...(file?{file}:{})});
      if(current!==request || captured!==model || !host.isConnected)return;
      heading.replaceChildren();
      if(file) {
        heading.append(button('← All modules','quiet-button',()=>selectModule(null)),el('h2','',result.module.name),el('p','source-peek',result.module.file));
      } else heading.append(el('h2','', 'Choose a module'));
      heading.tabIndex=-1;
      if(focusHeading)heading.focus({preventScroll:true});
      const page=file?result.methods:result.modules;
      list.replaceChildren();list.classList.toggle('module-grid',!file);
      for(const row of page.items) {
        if(file)list.append(startButton(row));
        else {
          const item=button('','start-item module-item',()=>selectModule(row.file));item.dataset.file=row.file;
          item.append(el('strong','',row.name),el('span','start-method',row.file),el('span','module-count',row.total+' functions & methods'));
          list.append(item);
        }
      }
      if(!page.total)list.append(el('p','source-peek',file?'No matching methods.':'No matching modules.'));
      const controls=el('div','catalog-pagination');
      controls.append(el('span','source-peek',page.total?`${cursor+1}–${cursor+page.items.length} of ${page.total}`:'0 results'));
      if(cursor)controls.append(button('Previous','quiet-button',()=>loadModules(Math.max(0,cursor-20))));
      if(page.nextCursor!==null)controls.append(button(file?'More methods':'More modules','quiet-button',()=>loadModules(page.nextCursor)));
      list.append(controls);
    } catch(error) {if(current===request && captured===model && host.isConnected)list.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>loadModules(cursor)));}
  }
  function selectModule(file) {
    selectedFile=file;filter.value='';clearTimeout(timer);
    const url=new URL(location.href);if(file)url.searchParams.set('module',file);else url.searchParams.delete('module');
    history.replaceState(null,'',url);loadModules(0,true);
  }
  filter.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>loadModules(),150);});
  await loadModules();
}
function endpointTabs(section,host,methods) {
  const tabs=el('div','endpoint-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','HTTP method');
  host.id='endpointResults';host.setAttribute('role','tabpanel');
  const order=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','WS','ROUTE'];
  const verbs=['All',...methods.slice().sort((a,b)=>(order.includes(a)?order.indexOf(a):99)-(order.includes(b)?order.indexOf(b):99))];
  for(const verb of verbs) {
    const tab=button(verb,'endpoint-tab',()=>{
      for(const sibling of tabs.children){sibling.setAttribute('aria-selected',String(sibling===tab));sibling.tabIndex=sibling===tab?0:-1;}
      host.setAttribute('aria-labelledby',tab.id);
      loadStartGroup('http',host,0,verb==='All'?'':verb);
    });
    tab.id='verb-'+verb;tab.dataset.method=verb;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',host.id);
    tab.setAttribute('aria-selected',String(verb==='All'));tab.tabIndex=verb==='All'?0:-1;
    tab.addEventListener('keydown',event=>{
      const buttons=[...tabs.children],index=buttons.indexOf(tab);
      const next=event.key==='ArrowRight'?(index+1)%buttons.length:event.key==='ArrowLeft'?(index+buttons.length-1)%buttons.length:event.key==='Home'?0:event.key==='End'?buttons.length-1:null;
      if(next!==null){event.preventDefault();buttons[next].focus();buttons[next].click();}
    });
    tabs.append(tab);
  }
  host.setAttribute('aria-labelledby','verb-All');section.append(tabs);
}
async function showStartPage(page=null) {
  const captured=model, request=++startRequest;
  ++selectionRequest; ++navigationRequest;
  closeComparison();$('#search').value='';$('#navigation').replaceChildren();
  setWorkflowMode('starts');
  const host=$('#startGroups');host.replaceChildren(el('p','source-peek','Loading…'));
  try {
    const result=await api('/api/starts',{snapshot:captured.snapshotId,limit:20});
    if(captured!==model || request!==startRequest)return;
    const requested=page || new URLSearchParams(location.search).get('page');
    catalogPage=Object.hasOwn(catalogTitles,requested)?requested:result.counts.http?'endpoints':result.counts.commands+result.counts.tasks?'commands':'methods';
    const url=new URL(location.href);url.hash='';url.searchParams.set('page',catalogPage);if(page || catalogPage!=='methods')url.searchParams.delete('module');history.replaceState(null,'',url);
    setWorkflowMode('starts');
    $('#startProject').textContent=model.project+' · '+model.coverage.files+' Python files';
    host.replaceChildren();host.classList.toggle('single-page',catalogPage!=='commands');
    const categories=catalogPage==='endpoints'?['http']:catalogPage==='commands'?['commands','tasks']:['methods'];
    for(const category of categories) {
      const section=el('section','start-group');section.dataset.category=category;
      if(catalogPage==='commands')section.append(el('h2','',startLabels[category]+' · '+result.counts[category]));
      const content=el('div');
      if(category==='http' && result.counts.http)endpointTabs(section,content,result.httpMethods);
      section.append(content);host.append(section);
      if(category==='methods')await modulePicker(content,new URLSearchParams(location.search).get('module'));
      else await loadStartGroup(category,content);
      if(captured!==model || request!==startRequest)return;
    }
    workflowState.initialized=true;
  } catch(error) {if(captured===model && request===startRequest)host.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>showStartPage(page)));}
}
async function startReview(id, keepChanges=false) {
  const request=++startRequest;$('#search').value='';
  if(!await chooseScope(id))return;
  await showSelectedWorkflow();
  if(request===startRequest && keepChanges)setWorkflowMode('changes');
}
async function navigation(cursor=0) {
  const request=++navigationRequest, captured=model, query=$('#search').value.trim();
  const host=$('#navigation');
  if(!query){host.replaceChildren();setWorkflowMode(workflowState.mode);return;}
  $('#repositoryBrowser').hidden=false;$('#workflowBrowser').hidden=true;$('#changesBrowser').hidden=true;
  try {
    const data=await api('/api/starts',{q:query,snapshot:captured.snapshotId,cursor,limit:20});
    if(request!==navigationRequest || captured!==model)return;
    clearError('navigation');host.replaceChildren();
    for(const row of data.results.items){const item=startButton(row);item.classList.add('nav-item');host.append(item);}
    if(!data.results.total)host.append(el('p','nav-empty','No matches. Try a method name, route, or file.'));
    host.append(el('p','source-peek',data.results.total+' matches'));
    if(cursor)host.append(button('Previous matches','quiet-button',()=>navigation(Math.max(0,cursor-20))));
    if(data.results.nextCursor!==null)host.append(button('More matches','quiet-button',()=>navigation(data.results.nextCursor)));
  } catch(error) {if(request===navigationRequest && captured===model)reportError(error,()=>navigation(cursor),'navigation');}
}

async function chooseScope(id, opts={}) {
  const request=++selectionRequest, captured=model;
  try {await ensureScope(id, captured);} catch(error) {if(request===selectionRequest && captured===model) reportError(error,()=>chooseScope(id,opts),'selection'); return false;}
  if(request!==selectionRequest || captured!==model) return false;
  clearError('selection');closeComparison();
  $('.workspace').classList.remove('choosing');$('#startPage').hidden=true;$('#workflowTab').hidden=false;
  if (!opts.keepStack) state.stack = [];
  state.scope = id; if(workflowState.mode==='starts')setWorkflowMode('workflow'); state.focus = null; state.sourceWhole = false; state.selectedElement = null;
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
  renderPayloads(); navigation(); if (typeof loadTests === 'function') loadTests(id);
  await showSource(scope.span, scope.qualified, 'Original source for this scope. Select an operation to focus its evidence.');
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
  if (frame.focus) await showSource(frame.focus.span, frame.focus.title, frame.focus.details, false, null, frame.focus.snapshotId);
  frame.selectedElement?.querySelector('button')?.focus({preventScroll:true});
}

function renderLazyBranch(branch, scope, ancestry, depth, node) {
  const region=el('details','branch'), summary=el('summary');
  summary.append(el('span','',branch.label),el('span','branch-count',branch.total+' statements'));
  region.append(summary);
  if(branch.note) region.append(el('div','branch-note',branch.note));
  const contents=el('div');region.append(contents);
  const captured=model;
  let cursor=0, loading=false, loaded=false;
  async function loadPage() {
    if(loading || captured!==model) return;
    loading=true;
    const controls=contents.querySelector('.branch-controls'), hadFocus=Boolean(controls?.contains(document.activeElement));if(controls) controls.remove();
    const status=el('div','branch-controls');status.append(el('p','source-peek','Loading branch…'));contents.append(status);
    try {
      const page=await api('/api/branch',{symbol:scope.id,operation:branch.operation,arm:branch.arm,snapshot:captured.snapshotId,cursor,limit:20});
      if(captured!==model) return;
      for(const [id,value] of Object.entries(page.references)) captured.scopes[id] ||= value;
      const body=renderList(page.flow.items,scope,ancestry,depth);status.replaceWith(body);
      if(hadFocus && region.isConnected && document.activeElement===document.body)body.querySelector('button')?.focus({preventScroll:true});
      loaded=true;cursor=page.flow.nextCursor;
      if(cursor!==null) {
        const next=el('div','branch-controls');next.append(button('Load more branch statements','quiet-button',loadPage));contents.append(next);
      }
    } catch(error) {
      if(captured!==model) return;
      const message=el('p','error',error.message);message.setAttribute('role','alert');
      status.replaceChildren(message,button('Retry branch','quiet-button',loadPage));
    } finally {loading=false;}
  }
  region.addEventListener('toggle',()=>{if(region.open&&!loaded)loadPage();});
  return region;
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
      if(branch.total!==undefined && branch.total>0) {branches.append(renderLazyBranch(branch,scope,ancestry,depth,node));continue;}
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
      const hadFocus=document.activeElement===toggle;
      toggle.disabled=true;
      try {await fillCall(contents,call,scope,ancestry,depth);clearError('call');}
      catch(error){contents.replaceChildren();if(host.isConnected) reportError(error,()=>toggle.click(),'call');return;}
      finally {toggle.disabled=false;if(hadFocus && host.isConnected && document.activeElement===document.body)toggle.focus({preventScroll:true});}
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
async function showSource(span,title,details='',preserveScroll=false,pageStart=null,snapshotId=null) {
  const request=++sourceRequest, captured=model;
  state.focus={span,title,details,snapshotId};
  const start=pageStart || (state.sourceWhole?1:Math.max(1,span.start-4));
  try {
    const result=await api('/api/source',{snapshot:snapshotId||captured.snapshotId,file:span.file,start});
    if(request!==sourceRequest || captured!==model) return;
    clearError('source');
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
    if(start>1)controls.append(button('Previous source lines','scope-jump',()=>showSource(span,title,details,false,Math.max(1,start-80),snapshotId)));
    if(result.span.end<result.totalLines) controls.append(button('Next source lines →','scope-jump',()=>showSource(span,title,details,false,result.span.end+1,snapshotId)));
    controls.append(button('Start of file','scope-jump',()=>showSource(span,title,details,false,1,snapshotId)));
    const entireSelection=span.start>=start&&span.end<=result.span.end;
    controls.append(button(entireSelection?'Copy exact selection':'Copy visible source','scope-jump',async()=>{
      try {await navigator.clipboard.writeText(entireSelection?lines.slice(span.start-start,span.end-start+1).join('\n'):result.source);announce('Source copied');}
      catch {announce('Clipboard unavailable; select and copy the source.');}
    }));
    controls.append(button(state.wrap?'Unwrap lines':'Wrap lines','scope-jump',()=>{state.wrap=!state.wrap;showSource(span,title,details,true,start,snapshotId);}));
    host.append(controls);$('#snapshotLabel').textContent='Snapshot '+(snapshotId||captured.snapshotId).slice(0,8);
  } catch(error) {if(request===sourceRequest && captured===model){$('#sourceCode').replaceChildren(el('p','error',error.message));reportError(error,()=>showSource(span,title,details,preserveScroll,pageStart,snapshotId),'source');}}
}
function analysisStatus() {
  const errors=model.diagnostics?.analysisErrors?.total??model.diagnostics?.parseErrors?.total??0;
  const skipped=Math.max(0,(model.coverage?.discovered||0)-(model.coverage?.files||0));
  const badge=$('#analysisStatus');
  badge.hidden=!errors&&!skipped;
  badge.textContent=errors?`${errors} analysis ${errors===1?'issue':'issues'} · review incomplete`:`${skipped} skipped ${skipped===1?'file':'files'} · review incomplete`;
  badge.setAttribute('aria-label',badge.textContent+'. Open source coverage.');
}
function coverage() {
  const c=model.coverage, host=$('#coveragePanel');host.replaceChildren(el('h2','','Source coverage'),el('p','',model.root));
  const grid=el('div','coverage-grid');
  for(const [value,label] of [[`${format(c.files)}/${format(c.discovered)}`,'Python files parsed'],[format(c.definitions),'functions, methods & lambdas'],[`${format(c.representedStatements)}/${format(c.statements)}`,'statements represented'],[`${format(c.representedCalls)}/${format(c.calls)}`,'explicit call sites represented']]) {const stat=el('div','coverage-stat');stat.append(el('strong','',value),el('span','',label));grid.append(stat);}host.append(grid);
  host.append(el('p','',Object.entries(c.statuses).map(([k,v])=>`${format(v)} ${k}`).join(' · ')));
  for(const limit of model.limits)host.append(el('p','',limit));
  for(const [label,category,count] of [['Excluded paths','excluded',model.diagnostics?.excluded?.total||0],['Analysis issues','errors',model.diagnostics?.analysisErrors?.total??model.diagnostics?.parseErrors?.total??0],['Unmodeled call syntax','unmodeledCalls',c.unmodeledCalls||0]]) {
    const section=el('details');section.append(el('summary','',label+' · '+count));
    const content=el('div');section.append(content);host.append(section);
    section.addEventListener('toggle',()=>{if(section.open&&!content.childNodes.length)loadDiagnostics(content,category);});
  }
}
let comparisonRequest=0;
function closeComparison() {
  ++comparisonRequest;
  $('#comparisonPanel').hidden=true;
  $('.workspace').classList.remove('comparing');
}
async function showComparison(id, side='working', cursor=0) {
  const captured=model, request=++comparisonRequest;
  const host=$('#comparisonPanel');host.hidden=false;
  $('.workspace').classList.add('comparing');
  const origin=document.activeElement;
  const close=button('Close comparison','quiet-button',()=>{closeComparison();if(origin?.isConnected && origin!==document.body)origin.focus();else if(state.scope)$('#flow').focus();else $('#methodsTab').focus();});
  host.replaceChildren(close,el('p','source-peek','Loading comparison…'));
  try {
    const result=await api('/api/compare',{symbol:id,side,snapshot:captured.snapshotId,cursor,limit:40});
    if(captured!==model || request!==comparisonRequest) return;
    const heading=el('div','comparison-heading');heading.append(el('h1','','Before / after'),close);
    host.replaceChildren(heading,el('p','comparison-notice',result.notice));
    const columns=el('div','comparison-columns');
    for(const [label,page] of [['Before · baseline',result.before],['After · working source',result.after]]) {
      const column=el('section','comparison-side');column.setAttribute('aria-label',label);
      column.append(el('h2','',label));
      if(page) {
        column.append(el('p','source-file',page.name+' · '+page.span.file),el('p','source-peek','Snapshot '+page.snapshotId.slice(0,8)));
        const code=el('div','comparison-code wrap-code');code.tabIndex=0;code.setAttribute('role','region');code.setAttribute('aria-label',label+' Python source');
        for(const row of page.lines.items) {
          const line=el('div','code-line'), text=el('span','line-content');text.innerHTML=syntax(row.text)||' ';
          line.append(el('span','line-number',row.line),text);code.append(line);
        }
        if(!page.lines.items.length) code.append(el('p','source-peek','End of this definition.'));
        column.append(code);
      } else column.append(el('p','',result.match==='ambiguous'?'No unique counterpart established.':result.match==='added'?'Definition added.':'Definition deleted.'));
      columns.append(column);
    }
    host.append(columns);
    const controls=el('div','source-peek');
    if(cursor) controls.append(button('Previous comparison lines','quiet-button',()=>showComparison(id,side,Math.max(0,cursor-40))));
    if(result.nextCursor!==null) controls.append(button('Next comparison lines','quiet-button',()=>showComparison(id,side,result.nextCursor)));
    host.append(controls);announce('Before and after source loaded.');
  } catch(error) {
    if(captured!==model || request!==comparisonRequest) return;
    const message=el('p','error',error.message);message.setAttribute('role','alert');
    host.replaceChildren(close,message,button('Retry comparison','quiet-button',()=>showComparison(id,side,cursor)));
  }
}
function baselineLink(row, label) {
  const link=el('a','scope-jump change-name',label);
  link.href='?'+new URLSearchParams({snapshot:model.changes.baseSnapshotId,returnSnapshot:model.snapshotId})+'#'+encodeURIComponent(row.id);
  return link;
}
function renderChanges() {
  const host=$('#changesBrowser'), changes=model.changes;
  $('#changesTab').hidden=!changes?.baseSnapshotId;
  host.replaceChildren();
  if(!changes?.baseSnapshotId) return;
  host.append(el('h2','workflow-title','Changes from '+changes.base),el('p','workflow-intro','Changed files and edits outside methods are listed here. Caller lists cover direct source relationships; other effects may remain unassessed.'));
  const categories=[['Changed files','files'],['Changes outside methods','unassessedChanges'],['Changed methods','changedMethods'],['Moved methods · source unchanged','renamedMethods'],['Previous methods','previousMethods'],['Previous moved methods','previousRenamedMethods'],['Current callers','knownCallers'],['Baseline callers','baselineCallers'],['Possible impact','possibleImpact']];
  for(const [label,category] of categories) {
    const section=el('details','change-section'), count=changes.counts[category] || 0;
    section.dataset.category=category;
    section.append(el('summary','',label+' · '+count));
    const content=el('div','change-records');section.append(content);host.append(section);
    if(category==='possibleImpact') content.append(el('p','workflow-intro','Possible callers under static dispatch assumptions; runtime targets remain uncertain.'));
    if(category==='baselineCallers') content.append(el('p','workflow-intro','Historical calls to previous definitions, including deleted targets. These links do not establish current resolution.'));
    if(category==='unassessedChanges') content.append(el('p','workflow-intro','These edits are visible, but their effect on methods and callers has not been established.'));
    const rows=el('div');content.append(rows);
    section.addEventListener('toggle',()=>{if(section.open&&!rows.childNodes.length)loadDiagnostics(rows,category);});
    section.open=category==='files' || category==='unassessedChanges' && count>0 || category===(changes.counts.changedMethods?'changedMethods':'previousMethods');
  }
}
async function loadDiagnostics(host,category,cursor=0) {
  const captured=model;
  try {
    const result=await api('/api/diagnostics',{snapshot:captured.snapshotId,category,cursor,limit:25});
    if(captured!==model || !host.isConnected)return;
    host.replaceChildren(el('p','',result.rows.total ? result.rows.total+' records' : 'No records in this category.'));
    for(const row of result.rows.items) {
      const record=el('div','change-record');
      if(category==='files') {
        const status=({A:'Added',D:'Deleted',M:'Modified',R:'Renamed',C:'Copied'})[row.status]||row.status;
        const label=status+' · '+(row.oldPath?row.oldPath+' → ':'')+row.path;
        record.append(el('p','',label));
        const baseline=row.status==='D';
        const file=baseline?(row.oldPath||row.path):row.path;
        record.append(button(baseline?'Open baseline source':'Open working source','scope-jump',()=>showSource({file,start:1,end:1},label,'Changed file; callable impact is listed separately.',false,null,baseline?model.changes.baseSnapshotId:null)));
      } else if(category==='unassessedChanges') {
        const side=row.side==='base'?'Baseline':'Working source';
        const label=side+' · '+row.file+(row.span?':'+row.span.start:'')+' · '+row.reason;
        record.append(el('p','',label));
        if(row.span) record.append(button('Open exact source','scope-jump',()=>showSource(row.span,label,row.reason,false,null,row.side==='base'?model.changes.baseSnapshotId:null)));
        if(row.analysisError)record.append(el('p','status unknown','Source unavailable: '+row.analysisError));
      } else if(row.id && ['previousMethods','previousRenamedMethods','baselineCallers'].includes(category) && model.changes?.baseSnapshotId) {
        const label=row.name+' · '+row.file+':'+row.span.start;
        record.append(baselineLink(row,label+' · Open baseline'));
        if(['previousMethods','previousRenamedMethods'].includes(category))record.append(button('Compare before / after','scope-jump',()=>showComparison(row.id,'base')));
        if(row.calls) record.append(el('p','source-peek','Previously called: '+[...new Set(row.calls.map(call=>call.target.name))].join(', ')));
      } else if(row.id) {
        const label=row.name+' · '+row.file+':'+row.span.start;
        record.append(button(label,'scope-jump change-name',()=>startReview(row.id,true)));
        if(['changedMethods','renamedMethods'].includes(category))record.append(button('Compare before / after','scope-jump',()=>showComparison(row.id,'working')));
        record.append(button('Trace workflow','scope-jump',async()=>{if(await chooseScope(row.id))await showSelectedWorkflow();}));
      } else record.append(el('p','',[row.file||row.path||row.span?.file,row.reason||row.message||row.expression].filter(Boolean).join(' · ')));
      host.append(record);
    }
    if(cursor)host.append(button('Previous records','quiet-button',()=>loadDiagnostics(host,category,Math.max(0,cursor-25))));
    if(result.rows.nextCursor!==null)host.append(button('More records →','quiet-button',()=>loadDiagnostics(host,category,result.rows.nextCursor)));
  }catch(error){if(captured===model && host.isConnected){const message=el('p','error',error.message);message.setAttribute('role','alert');host.replaceChildren(message,button('Retry','quiet-button',()=>loadDiagnostics(host,category,cursor)));}}
}
async function load(refresh=false) {
  const b=$('#refreshButton'); b.disabled=true;b.textContent=refresh?'Reading source…':'Indexing…';
  try {
    const requestedSnapshot=new URLSearchParams(location.search).get('snapshot');
    if(!sessionToken)sessionToken=(await api('/api/session')).token;
    const summary=refresh?await api('/api/reindex',{}, {method:'POST',headers:{'X-Threadline-Token':sessionToken}}):await api('/api/summary', requestedSnapshot?{snapshot:requestedSnapshot}:{});
    clearError();closeComparison();
    model={...summary,scopes:{},files:{},generatedWorkflows:{}};
    ++selectionRequest; ++sourceRequest;
    for(const scope of summary.entrypoints.items)model.scopes[scope.id]=scope;
    if(refresh && requestedSnapshot) history.replaceState(null,'',location.pathname+location.hash);
    $('#projectName').textContent=model.project;
    analysisStatus();coverage();renderChanges();
    const returnSnapshot=new URLSearchParams(location.search).get('returnSnapshot'), notice=$('#baselineNotice');
    notice.hidden=!returnSnapshot || refresh;
    notice.replaceChildren();
    if(!notice.hidden) {
      const link=el('a','scope-jump','Return to change review');
      link.href='?'+new URLSearchParams({snapshot:returnSnapshot});
      notice.append(el('strong','','Baseline source · '),link);
    }
    const preferred=(refresh && workflowState.mode!=='starts' ? state.scope : null) || decodeURIComponent(location.hash.slice(1));
    if(preferred) {
      if(await chooseScope(preferred))await initializeWorkflows(refresh);
      else await showStartPage();
    } else await showStartPage();
    announce(refresh?'Source refreshed. Flow and source refer to the same snapshot.':'Repository ready.');
  }catch(error){reportError(new Error('Unable to load the source index: '+error.message),()=>load(refresh),'load');}
  finally{b.disabled=false;b.textContent='↻ Refresh source';}
}
let searchTimer; $('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>navigation(),150);});
function toggleCoverage() {const h=$('#coveragePanel');h.hidden=!h.hidden;$('#coverageButton').setAttribute('aria-expanded',String(!h.hidden));if(!h.hidden)h.focus();}
$('#coverageButton').addEventListener('click',toggleCoverage);
$('#analysisStatus').addEventListener('click',toggleCoverage);
$('#refreshButton').addEventListener('click',()=>load(true));
$('#expandBranches').addEventListener('click',()=>{$('#flow').querySelectorAll('details.branch').forEach(d=>d.open=true);});
$('#collapseCalls').addEventListener('click',()=>{$('#flow').querySelectorAll('.call').forEach(call=>{const content=call.children[1];content.hidden=true;const b=call.querySelector(':scope > .call-row > .call-open');b.textContent=b.dataset.closedLabel;b.setAttribute('aria-expanded','false');});});
$('#clearFocus').addEventListener('click',()=>{const s=model.scopes[state.scope];if(!s)return;showSource(s.span,s.qualified,'Original source for the selected method.');});
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('#search').focus();}if(event.key==='Escape'){if(!$('#coveragePanel').hidden)$('#coverageButton').focus();$('#coveragePanel').hidden=true;$('#coverageButton').setAttribute('aria-expanded','false');}});
window.addEventListener('hashchange',async()=>{
  if(!model) return;
  try {
    const id=decodeURIComponent(location.hash.slice(1));
    if(!id)await showStartPage();
    else if(id!==state.scope)await startReview(id);
  } catch(error) {reportError(error,null,'selection');}
});
load();
