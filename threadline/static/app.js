'use strict';
let model;
const $ = selector => document.querySelector(selector);
const state = { scope: null, stack: [] };
const format = value => Number(value).toLocaleString();
function el(tag, cls, content) { const node = document.createElement(tag); if (cls) node.className = cls; if (content !== undefined) node.textContent = content; return node; }
function button(label, cls, handler) { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', handler); return b; }
function scopeName(id) { return model.scopes[id]?.qualified || id; }
const certaintyLabels = {supported:'Calls', possible:'Probably calls', external:'Library', unknown:"Can't tell"};
function certaintyLabel(status) { return certaintyLabels[status] || status; }
function announce(message) { $('#announcement').textContent = message; }
function reviewURL() { return new URL(window.threadlineHost?.location || location.href); }
function replaceReviewURL(url) {
  if (window.threadlineHost) { window.threadlineHost.location = new URL(url, reviewURL()).href; return; }
  try { history.replaceState(null, '', url); }
  catch (error) {
    // A downloaded review can also run in a sandboxed blob preview. Browsers
    // restrict URL changes there; navigation still works using in-memory state.
    if (error.name !== 'SecurityError' || !window.threadlineOffline) throw error;
  }
}
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

let sessionToken = '', navigationRequest = 0, selectionRequest = 0;
async function api(path, params={}, options={}) {
  if (window.threadlineHost) return window.threadlineHost.request(path, params, options);
  if (window.threadlineOffline) return window.threadlineOffline(path, params);
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
const startLabels={http:'HTTP routes',commands:'CLI commands',tasks:'Tasks & callbacks',testCommands:'Test modules',methods:'Functions & methods'};
const emptyStartLabels={http:'No HTTP routes in this snapshot.',commands:'No CLI commands in this snapshot.',tasks:'No tasks or callbacks in this snapshot.',testCommands:'No runnable test modules in this snapshot.',methods:'No functions or methods in this snapshot.'};
const plural=(count,one,many)=>count+' '+(count===1?one:many);
let startRequest=0;
// Inside a module's list the file is already in the heading, so the card gives the line instead.
function startButton(row, inModule=false) {
  const item=button('', 'start-item',()=>startReview(row.id));item.dataset.scope=row.id;
  const place=inModule?'line '+row.line:row.label===row.name||row.name==='<module>'?row.file:row.name+' · '+row.file;
  item.append(el('strong','',row.label),el('span','start-method',place));
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
  if(!page.total){host.append(el('p','source-peek',emptyStartLabels[category]));return;}
  const controls=el('div','catalog-pagination');
  controls.append(el('span','source-peek',`${cursor+1}–${cursor+page.items.length} of ${page.total}`));
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
        if(file)list.append(startButton(row,true));
        else {
          const item=button('','start-item module-item',()=>selectModule(row.file));item.dataset.file=row.file;
          item.append(el('strong','',row.name),el('span','start-method',row.file),el('span','module-count',plural(row.total,'function','functions')));
          list.append(item);
        }
      }
      if(!page.total){list.append(el('p','source-peek',file?'No matching methods.':'No matching modules.'));return;}
      const controls=el('div','catalog-pagination');
      controls.append(el('span','source-peek',`${cursor+1}–${cursor+page.items.length} of ${page.total}`));
      if(cursor)controls.append(button('Previous','quiet-button',()=>loadModules(Math.max(0,cursor-20))));
      if(page.nextCursor!==null)controls.append(button(file?'More methods':'More modules','quiet-button',()=>loadModules(page.nextCursor)));
      list.append(controls);
    } catch(error) {if(current===request && captured===model && host.isConnected)list.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>loadModules(cursor)));}
  }
  function selectModule(file) {
    selectedFile=file;filter.value='';clearTimeout(timer);
    const url=reviewURL();if(file)url.searchParams.set('module',file);else url.searchParams.delete('module');
    replaceReviewURL(url);loadModules(0,true);
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
    const requested=page || reviewURL().searchParams.get('page');
    const available={endpoints:result.counts.http>0,commands:result.counts.commands+result.counts.tasks>0,methods:true};
    $('#endpointsTab').hidden=!available.endpoints;$('#commandsTab').hidden=!available.commands;
    catalogPage=Object.hasOwn(catalogTitles,requested)&&available[requested]?requested:result.counts.http?'endpoints':result.counts.commands+result.counts.tasks?'commands':'methods';
    const url=reviewURL();url.hash='';url.searchParams.set('page',catalogPage);if(page || catalogPage!=='methods')url.searchParams.delete('module');replaceReviewURL(url);
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
      if(category==='methods')await modulePicker(content,reviewURL().searchParams.get('module'));
      else await loadStartGroup(category,content);
      if(captured!==model || request!==startRequest)return;
    }
    if(catalogPage==='commands' && result.counts.testCommands) {
      // Test files with a main guard are runnable, but rarely where a review starts.
      const tests=el('details','start-group test-commands'), content=el('div');
      tests.append(el('summary','','Test modules you can run · '+result.counts.testCommands),content);
      tests.addEventListener('toggle',()=>{if(tests.open && !content.childElementCount)loadStartGroup('testCommands',content);});
      host.append(tests);
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
  state.scope = id; if(workflowState.mode==='starts')setWorkflowMode('workflow');
  const scope = model.scopes[id];
  $('#methodName').textContent = scope.kind === 'module' ? scope.module + ' (module body)' : scope.qualified;
  renderPathBar(); navigation();
  // Building the call map selects the entry method again; keep the view already drawn for it.
  if (codeFirst.rendered !== captured.snapshotId + '|' + id) await renderCodeFirst(id);
  if(request!==selectionRequest || captured!==model)return false;
  if (!opts.keepScroll) $('.review').scrollTop = 0;
  replaceReviewURL('#' + encodeURIComponent(id));
  if (typeof syncWorkflowMethod === 'function') syncWorkflowMethod(id);
  return true;
}

// Opening a method keeps where you were; Back restores its highlight and side view.
async function enterScope(id, call={}) {
  state.stack.push({scope: state.scope, destination: call.destination, scroll: $('.review').scrollTop,
    highlight: codeFirst.highlight, beside: codeFirst.beside});
  await chooseScope(id, {keepStack:true});
}
async function returnTo(index) {
  if (index < 0 || index >= state.stack.length) return;
  state.stack.length = index + 1;
  await returnToCaller();
}
async function returnToCaller() {
  const frame = state.stack.pop(); if (!frame) return;
  codeFirst.scope = frame.scope; codeFirst.highlight = frame.highlight; codeFirst.beside = frame.beside;
  if(!await chooseScope(frame.scope, {keepStack:true, keepScroll:true}))return;
  $('.review').scrollTop = frame.scroll;
}



function escaped(str) { return str.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function syntax(line) {
  const regex = /#[^\n]*|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:async|await|def|class|return|if|elif|else|raise|try|except|finally|from|import|for|while|with|as|match|case|in|None|True|False|not|and|or|yield|break|continue|assert|lambda|pass)\b|\b\d+(?:\.\d+)?\b/g;
  let out='',end=0,match;
  while((match=regex.exec(line))) { out+=escaped(line.slice(end,match.index)); const token=match[0],type=token.startsWith('#')?'comment':/^["']/.test(token)?'str':/^\d/.test(token)?'num':'key'; out+=`<span class="tok-${type}">${escaped(token)}</span>`; end=match.index+token.length; }
  return out+escaped(line.slice(end));
}
function codeLine(number, value, marked=false) {
  const line=el('div','code-line'+(marked?' focus':''));line.dataset.line=String(number);
  const content=el('span','line-content');content.innerHTML=syntax(value)||' ';
  line.append(el('span','line-number',String(number)),content);
  return line;
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
  const c=model.coverage, host=$('#coveragePanel');host.replaceChildren(el('p','',model.root));
  const grid=el('div','coverage-grid');
  for(const [value,label] of [[`${format(c.files)}/${format(c.discovered)}`,'Python files parsed'],[format(c.definitions),'functions, methods & lambdas'],[`${format(c.representedStatements)}/${format(c.statements)}`,'statements read'],[`${format(c.representedCalls)}/${format(c.calls)}`,'calls read']]) {const stat=el('div','coverage-stat');stat.append(el('strong','',value),el('span','',label));grid.append(stat);}host.append(grid);
  const st=c.statuses||{}, total=Object.values(st).reduce((sum,value)=>sum+value,0);
  if(total)host.append(el('p','',`Of ${format(total)} calls, ${format(st.supported||0)} go to one project function, ${format(st.possible||0)} probably do, ${format(st.external||0)} go to libraries, and ${format(st.unknown||0)} can't be told from source. Those are usually methods on objects that are passed in or built at runtime.`));
  if(model.limits.length) {
    const limits=el('details');limits.append(el('summary','','Limits of reading source without running it'));
    for(const limit of model.limits)limits.append(el('p','',limit));
    host.append(limits);
  }
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
  const close=button('Close comparison','quiet-button',()=>{closeComparison();if(origin?.isConnected && origin!==document.body)origin.focus();else if(state.scope)$('#cfCode').focus();else $('#methodsTab').focus();});
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
async function showChangeSource(record,span,snapshotId,label) {
  const previous=record.querySelector('.change-source-excerpt');
  if(previous){previous.remove();return;}
  const excerpt=el('div','change-source-excerpt code-window wrap-code');
  excerpt.tabIndex=0;
  excerpt.setAttribute('role','region');
  excerpt.setAttribute('aria-label','Exact source for '+label);
  excerpt.textContent='Loading exact source…';
  record.append(excerpt);
  const captured=model;
  try{
    excerpt.replaceChildren();
    async function loadPage(start){
      const page=await api('/api/source',{snapshot:snapshotId,file:span.file,start,end:Math.min(span.end,start+79)});
      if(captured!==model || !excerpt.isConnected)return;
      const lines=page.source.split('\n').slice(0,page.span.end-start+1);
      excerpt.append(...lines.map((line,index)=>codeLine(start+index,line)));
      const next=page.span.end+1;
      if(next<=span.end){
        const more=button('Load more exact source lines','scope-jump',async()=>{
          more.remove();
          try{await loadPage(next);}
          catch(error){if(excerpt.isConnected)excerpt.append(el('p','error','Source unavailable: '+error.message));}
        });
        excerpt.append(more);
      }
    }
    await loadPage(span.start);
    excerpt.focus({preventScroll:true});
    excerpt.scrollIntoView({block:'nearest'});
  }catch(error){if(excerpt.isConnected)excerpt.replaceChildren(el('p','error','Source unavailable: '+error.message));}
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
        record.append(button(baseline?'Open baseline source':'Open working source','scope-jump',
          ()=>showChangeSource(record,{file,start:1,end:1},baseline?model.changes.baseSnapshotId:model.snapshotId,label)));
      } else if(category==='unassessedChanges') {
        const side=row.side==='base'?'Baseline':'Working source';
        const label=side+' · '+row.file+(row.span?':'+row.span.start:'')+' · '+row.reason;
        record.append(el('p','',label));
        if(row.span) record.append(button('Open exact source','scope-jump',
          ()=>showChangeSource(record,row.span,row.side==='base'?model.changes.baseSnapshotId:model.snapshotId,label)));
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
    const requestedSnapshot=reviewURL().searchParams.get('snapshot');
    if(!sessionToken)sessionToken=(await api('/api/session')).token;
    const summary=refresh?await api('/api/reindex',{}, {method:'POST',headers:{'X-Threadline-Token':sessionToken}}):await api('/api/summary', requestedSnapshot?{snapshot:requestedSnapshot}:{});
    const [schemaMajor,schemaMinor]=String(summary.schemaVersion||'').split('.').map(Number);
    if (schemaMajor!==1 || !Number.isInteger(schemaMinor) || schemaMinor<2 || typeof renderCodeFirst!=='function') {
      throw new Error('This review server does not support the page. Restart Threadline review, then reload this page.');
    }
    clearError();closeComparison();
    model={...summary,scopes:{},files:{},generatedWorkflows:{}};
    ++selectionRequest;
    for(const scope of summary.entrypoints.items)model.scopes[scope.id]=scope;
    if(refresh && requestedSnapshot) replaceReviewURL(reviewURL().pathname+reviewURL().hash);
    $('#projectName').textContent=model.project;
    analysisStatus();coverage();renderChanges();
    const returnSnapshot=reviewURL().searchParams.get('returnSnapshot'), notice=$('#baselineNotice');
    notice.hidden=!returnSnapshot || refresh;
    notice.replaceChildren();
    if(!notice.hidden) {
      const link=el('a','scope-jump','Return to change review');
      link.href='?'+new URLSearchParams({snapshot:returnSnapshot});
      notice.append(el('strong','','Baseline source · '),link);
    }
    const preferred=(refresh && workflowState.mode!=='starts' ? state.scope : null) || decodeURIComponent(reviewURL().hash.slice(1));
    if(preferred) {
      if(await chooseScope(preferred))await initializeWorkflows(refresh);
      else await showStartPage();
    } else await showStartPage();
    window.threadlineHost?.ready({snapshot:model.snapshotId, scope:state.scope});
    announce(refresh?'Source refreshed. Flow and source refer to the same snapshot.':'Repository ready.');
  }catch(error){
    const message=error.message.startsWith('This review server')?error.message:'Unable to load the source index: '+error.message;
    reportError(new Error(message),()=>load(refresh),'load');
  }
  finally{b.disabled=false;b.textContent='↻ Refresh source';}
}
let searchTimer; $('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>navigation(),150);});
$('#analysisStatus').addEventListener('click',()=>toggleHelp(true,'coverage'));
$('#refreshButton').addEventListener('click',()=>load(true));
document.addEventListener('keydown',event=>{if(event.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('#search').focus();}});
window.addEventListener('hashchange',async()=>{
  if(!model) return;
  try {
    const id=decodeURIComponent(reviewURL().hash.slice(1));
    if(!id)await showStartPage();
    else if(id!==state.scope)await startReview(id);
  } catch(error) {reportError(error,null,'selection');}
});
// Deferred scripts run before DOMContentLoaded, so workflow.js and codefirst.js
// are defined even when a slow download finishes after the first API reply.
document.addEventListener('DOMContentLoaded',()=>load(),{once:true});
