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
// ---- Catalog pages: endpoints, commands and tasks, modules and methods ----
// A page holds at most this many rows; past it the page says so and the header search reaches the rest.
let catalogCap=2000, moduleCap=5000;
const ICON_PATHS={
  file:'M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5zM14 3v5h5',
  folder:'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z',
  arrow:'M5 12h14m-6-6l6 6-6 6',
  terminal:'M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
  search:'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
  chevron:'M9 6l6 6-6 6'
};
function icon(name,size=14) {
  const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg'), path=document.createElementNS(ns,'path');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',width:size,height:size,fill:'none',stroke:'currentColor','stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(key,value);
  svg.classList.add('icon');path.setAttribute('d',ICON_PATHS[name]);svg.append(path);
  return svg;
}
const badge=(text,kind='')=>el('span','badge'+(kind?' badge-'+kind:''),text);
const baseName=file=>file.split('/').at(-1);
const effectLabel=name=>(typeof EFFECT_LABELS!=='undefined' && EFFECT_LABELS[name])||name;
const isWrite=name=>/write|process/.test(name);
// The path of a route without its leading verb: "GET /items" becomes "/items".
function routePath(row) {
  const verbs=new Set(row.httpMethods||[]);
  let path=String(row.label);
  for(let found=path.match(/^([A-Z]+)(?:\s|,)*/);found && verbs.has(found[1]);found=path.match(/^([A-Z]+)(?:\s|,)*/))path=path.slice(found[0].length);
  return path||row.label;
}
function effectBadges(row) {
  return (row.effects||[]).map(name=>badge(effectLabel(name),isWrite(name)?'write':'effect'));
}
// "calls" is the number of project methods this one calls: the same list as Calls in the review bar.
function callsFact(row) {
  const fact=el('span','',`calls: ${row.calls}`);
  fact.title='Project methods this one calls, counted once each';
  return fact;
}
function searchField(placeholder,onInput) {
  const wrap=el('label','catalog-search'), input=el('input');
  input.type='search';input.placeholder=placeholder;input.setAttribute('aria-label',placeholder.replace(/…$/,''));
  let timer;input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>onInput(input.value.trim().toLowerCase()),120);});
  wrap.append(icon('search',16),input);
  return wrap;
}
function selectField(label,options,onChange) {
  const wrap=el('label','catalog-select'), select=el('select');
  for(const [value,text] of options){const option=el('option','',text);option.value=value;select.append(option);}
  select.addEventListener('change',()=>onChange(select.value));
  wrap.append(el('span','',label),select);
  return wrap;
}
// Every row of a paged query, up to a cap: page one gives the total, then the other pages are requested together.
async function fetchPages(path,params,pick,cap=Infinity) {
  const first=pick(await api(path,{...params,cursor:0,limit:100})), rows=[...first.items];
  const offsets=[];
  for(let cursor=100;cursor<Math.min(first.total,cap);cursor+=100)offsets.push(cursor);
  for(const page of await Promise.all(offsets.map(cursor=>api(path,{...params,cursor,limit:100}))))rows.push(...pick(page).items);
  return {rows:rows.slice(0,cap),total:first.total};
}
// Every row of a catalog category, up to the cap. total says how many exist.
async function fetchStarts(category,captured) {
  const result=await fetchPages('/api/starts',{snapshot:captured.snapshotId,category},page=>page.results,catalogCap);
  return captured===model?result:null;
}
function capNote(loaded,total,noun) {
  if(loaded>=total)return null;
  return el('p','catalog-note',`Showing the first ${loaded.toLocaleString()} of ${total.toLocaleString()} ${noun}, so counts here cover only those. The search box in the header reaches all of them.`);
}
// Sidebar list of files with their counts; choosing one narrows the page, choosing All clears it.
function fileGroups(tree,title,rows,onSelect) {
  const groups=new Map();
  for(const row of rows)groups.set(row.file,(groups.get(row.file)||0)+1);
  const names=new Map();
  for(const file of groups.keys())names.set(baseName(file),(names.get(baseName(file))||0)+1);
  const label=file=>names.get(baseName(file))>1?file.split('/').slice(-2).join('/'):baseName(file);
  const list=el('div','tree-list'), entries=[['',rows.length,'All'],...[...groups].sort((a,b)=>a[0]<b[0]?-1:1).map(([file,count])=>[file,count,label(file)])];
  for(const [file,count,text] of entries) {
    const item=button('','tree-file',()=>{
      list.querySelectorAll('.tree-file').forEach(other=>other.setAttribute('aria-pressed',String(other===item)));
      onSelect(file);
    });
    item.setAttribute('aria-pressed',String(file===''));item.title=file||'All files';
    item.append(icon(file?'file':'folder',14),el('span','tree-name',text),el('span','tree-count',String(count)));
    list.append(item);
  }
  tree.replaceChildren(el('p','nav-label',title),list);
  treeKeys(tree);
  tree.hidden=false;
}
// Arrow keys move through the sidebar list; Right opens a folder and Left closes it or goes to its parent.
function treeKeys(tree) {
  if(tree.dataset.keys)return;
  tree.dataset.keys='1';
  tree.addEventListener('keydown',event=>{
    if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const items=[...tree.querySelectorAll('summary, .tree-file')].filter(item=>item.offsetParent!==null);
    const item=event.target.closest('summary, .tree-file'), index=items.indexOf(item);
    if(index<0)return;
    const go=target=>{event.preventDefault();items[Math.max(0,Math.min(items.length-1,target))]?.focus();};
    const folder=item.tagName==='SUMMARY'?item.parentElement:null;
    if(event.key==='ArrowDown')go(index+1);
    else if(event.key==='ArrowUp')go(index-1);
    else if(event.key==='Home')go(0);
    else if(event.key==='End')go(items.length-1);
    else if(event.key==='ArrowRight' && folder) {event.preventDefault();if(!folder.open)item.click();else go(index+1);}
    else if(event.key==='ArrowLeft') {
      if(folder?.open){event.preventDefault();item.click();return;}
      const parent=(folder||item.parentElement).parentElement?.closest('details')?.querySelector(':scope>summary');
      if(parent){event.preventDefault();parent.focus();}
    }
  });
}

// ---- The preview beside a catalog page: what a row is, before opening it ----
let inspectorRequest=0;
// Splits "(a: int, b: dict[str, int] = {}) -> Page" into parameters and the return annotation.
function parseSignature(text) {
  let depth=0,end=-1;
  for(let i=0;i<text.length;i++) {
    if('([{'.includes(text[i]))depth++;
    else if(')]}'.includes(text[i])){depth--;if(depth===0){end=i;break;}}
  }
  if(end<0)return {params:[],returns:''};
  const inside=text.slice(1,end), parts=[];
  let current='',nesting=0,quote='';
  for(const char of inside) {
    if(quote){current+=char;if(char===quote)quote='';continue;}
    if(char==='"'||char==="'"){quote=char;current+=char;continue;}
    if('([{'.includes(char))nesting++;
    if(')]}'.includes(char))nesting--;
    if(char===','&&nesting===0){parts.push(current.trim());current='';continue;}
    current+=char;
  }
  if(current.trim())parts.push(current.trim());
  return {params:parts.map(part=>{
    const found=part.match(/^(\*{0,2}\w+)\s*(?::\s*([^=]+?))?\s*(?:=\s*([\s\S]+))?$/);
    return found?{name:found[1],annotation:found[2]||'',default:found[3]||''}:{name:part,annotation:'',default:''};
  }),returns:text.slice(end+1).replace(/^\s*->\s*/,'')};
}
function inspectorHost() {
  const host=$('#startInspector');
  return host.offsetParent===null?null:host;
}
// What to show before any row is chosen: real counts from the rows loaded for the page.
function inspectorOverview(title,stats,hint) {
  const host=inspectorHost();
  if(!host)return;
  ++inspectorRequest;
  const grid=el('div','insp-stats');
  for(const [label,value] of stats) {
    const tile=el('div','insp-stat');tile.append(el('span','insp-stat-label',label),el('strong','insp-stat-value',String(value)));
    grid.append(tile);
  }
  host.replaceChildren(el('h2','insp-title',title),grid,el('p','insp-hint',hint));
}
async function previewRow(row,kind) {
  const host=inspectorHost();
  if(!host)return;
  const captured=model, token=++inspectorRequest;
  const card=el('div','insp-card'), top=el('div','insp-top');
  top.append(badge(kind==='route'?'Route':kind==='command'?'Command':kind==='task'?'Task':'Method',kind==='route'?'route':'class'));
  if(row.async)top.append(badge('async','async'));
  card.append(top);
  const title=el('div','insp-name');
  if(kind==='route'){for(const verb of row.httpMethods||[])title.append(badge(verb,'verb verb-'+verb.toLowerCase()));title.append(routePath(row));}
  else title.append(row.label||row.name);
  card.append(title);
  if(kind==='route')card.append(el('div','insp-handler',row.name+'()'));
  card.append(el('div','insp-place',`${row.file}:${row.line}`));
  const sections=[card];
  if(row.params) {
    const {params,returns}=parseSignature(row.params), section=el('section','insp-section'), list=el('div','insp-list');
    section.append(el('h3','','Parameters'));
    if(!params.length)list.append(el('p','insp-none','None'));
    for(const param of params) {
      const line=el('div','insp-param'), provided=/^Depends\(/.test(param.default);
      line.append(el('span','insp-param-name',param.name));
      if(param.annotation)line.append(el('span','insp-param-type',param.annotation));
      if(provided)line.append(badge('provided','effect'));
      else if(param.default)line.append(el('span','insp-param-default','= '+param.default));
      list.append(line);
    }
    if(returns){const line=el('div','insp-param');line.append(el('span','insp-param-name','returns'),el('span','insp-param-type',returns));list.append(line);}
    section.append(list);sections.push(section);
  }
  const effects=el('section','insp-section'), facts=el('div','insp-list');
  effects.append(el('h3','','Reaches'));
  if(row.calls!==undefined){const fact=callsFact(row);fact.className='insp-fact';fact.textContent=plural(row.calls,'project method','project methods')+' called';facts.append(fact);}
  const kinds=el('div','insp-badges');
  kinds.append(...(effectBadges(row).length?effectBadges(row):[el('span','insp-none','No database, network, or file effects found')]));
  facts.append(kinds);effects.append(facts);sections.push(effects);
  const tests=el('section','insp-section'), callers=el('section','insp-section');
  tests.append(el('h3','','Linked tests'),el('p','insp-none','Finding tests…'));
  callers.append(el('h3','','Called by'),el('p','insp-none','Finding callers…'));
  sections.push(tests,callers);
  const open=button('Open review','insp-open',()=>startReview(row.id));
  open.append(icon('arrow',14));
  host.replaceChildren(sections[0],open,...sections.slice(1));
  captured.previews ||= new Map();
  if(!captured.previews.has(row.id)) {
    captured.previews.set(row.id,Promise.all([
      api('/api/tests',{symbol:row.id,snapshot:captured.snapshotId,cursor:0,limit:4}),
      overviewOf(row.id,captured)]));
    captured.previews.get(row.id).catch(()=>captured.previews.delete(row.id));
  }
  try {
    const [testResult,overview]=await captured.previews.get(row.id);
    if(token!==inspectorRequest || captured!==model)return;
    const page=testResult.items;
    tests.replaceChildren(el('h3','','Linked tests '+(page.total?`· ${page.total}`:'')));
    if(!page.total)tests.append(el('p','insp-none','No test reaches this through calls, routes, or names.'));
    for(const test of page.items) {
      const line=el('div','insp-test');line.append(el('span','insp-test-name',test.name),el('span','insp-test-place',`${test.file}:${test.line}`));
      tests.append(line);
    }
    if(page.total>page.items.length)tests.append(el('p','insp-none',`+${page.total-page.items.length} more in the review`));
    const total=overview.callers.total;
    callers.replaceChildren(el('h3','','Called by '+(total?`· ${total}`:'')));
    callers.append(el('p','insp-none',total?plural(total,'method calls','methods call')+' this directly.':'Nothing in the analyzed source calls this directly. Frameworks call routes and commands.'));
  } catch(error) {
    if(token===inspectorRequest){tests.replaceChildren(el('h3','','Linked tests'),el('p','error',error.message));callers.replaceChildren();}
  }
}
// Hover or focus previews a row; the last preview stays until another row is chosen.
function bindPreview(item,row,kind) {
  let timer;
  const show=()=>{clearTimeout(timer);timer=setTimeout(()=>previewRow(row,kind),90);};
  item.addEventListener('mouseenter',show);
  item.addEventListener('focus',show);
  item.addEventListener('mouseleave',()=>clearTimeout(timer));
  return item;
}

// Start-page rows that link to a review. Search results in the sidebar use the compact form.
function startButton(row) {
  const item=button('','start-item',()=>startReview(row.id));item.dataset.scope=row.id;
  const place=row.label===row.name||row.name==='<module>'?row.file:row.name+' · '+row.file;
  item.append(el('strong','',row.label),el('span','start-method',place));
  return item;
}
function routeRow(row) {
  const item=button('','start-item route-row',()=>startReview(row.id));item.dataset.scope=row.id;
  const main=el('span','route-main');
  for(const verb of row.httpMethods||[])main.append(badge(verb,'verb verb-'+verb.toLowerCase()));
  main.append(el('span','route-path',routePath(row)),icon('arrow',14),el('span','route-handler',row.name+'()'),el('span','route-place',`${baseName(row.file)}:${row.line}`));
  const side=el('span','route-side');
  if(row.async)side.append(badge('async','async'));
  side.append(...effectBadges(row),icon('chevron',16));
  item.append(main,side);
  return bindPreview(item,row,'route');
}
function commandCard(row,category) {
  const item=button('','start-item command-card',()=>startReview(row.id));item.dataset.scope=row.id;
  const top=el('span','card-top');
  top.append(badge(category==='tasks'?'Task or callback':'CLI command',category==='tasks'?'task':'cli'),el('span','card-place',`${row.file}:${row.line}`),icon('terminal',16));
  const body=el('span','card-body');
  body.append(el('strong','command-title',row.label));
  if(row.params!==undefined && row.name!=='<module>')body.append(el('code','command-code',`${row.async?'async ':''}def ${row.name}${row.params}`));
  const foot=el('span','card-foot'), facts=el('span','card-facts');
  if(row.calls!==undefined)facts.append(callsFact(row));
  facts.append(...effectBadges(row));
  const open=el('span','card-open','Inspect');open.append(icon('arrow',14));
  foot.append(facts,open);
  item.append(top,body,foot);
  return bindPreview(item,row,category==='tasks'?'task':'command');
}

// Endpoints: verb filter, search, grouping, and the routes with what each one reaches.
async function endpointsPage(host,controls,tree,captured,request) {
  const loaded=await fetchStarts('http',captured);
  if(!loaded || request!==startRequest)return;
  const {rows,total}=loaded;
  let verb='',query='',file='',group='file',shown=300;
  const section=el('section','start-group'), results=el('div','route-list');
  section.dataset.category='http';results.id='endpointResults';results.setAttribute('role','tabpanel');
  const note=capNote(rows.length,total,'routes');
  section.append(...(note?[note]:[]),results);host.append(section);
  const counts=new Map();
  for(const row of rows)for(const name of row.httpMethods||[])counts.set(name,(counts.get(name)||0)+1);
  const order=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','WS','ROUTE'];
  const rank=name=>order.includes(name)?order.indexOf(name):99;
  const verbs=['All',...[...counts.keys()].sort((a,b)=>rank(a)-rank(b))];
  const tabs=el('div','catalog-chips endpoint-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','HTTP method');
  function render() {
    const matching=rows.filter(row=>(!verb || (row.httpMethods||[]).includes(verb)) && (!file || row.file===file) &&
      (!query || `${row.label} ${row.name} ${row.file}`.toLowerCase().includes(query)));
    const first=row=>(row.httpMethods||[])[0]||'';
    matching.sort((a,b)=>(group==='verb'?rank(first(a))-rank(first(b)):0)||(a.file<b.file?-1:a.file>b.file?1:a.line-b.line));
    results.replaceChildren();
    const visible=matching.slice(0,shown), groups=new Map();
    for(const row of visible) {
      const key=group==='file'?row.file:group==='verb'?first(row):'';
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(row);
    }
    for(const [key,items] of groups) {
      if(group!=='none') {
        const size=matching.filter(row=>(group==='file'?row.file:first(row))===key).length, head=el('div','group-head');
        if(group==='file')head.append(icon('file',14),el('strong','',key));
        else head.append(badge(key||'other','verb verb-'+key.toLowerCase()));
        head.append(badge(plural(size,'route','routes')));
        results.append(head);
      }
      results.append(...items.map(routeRow));
    }
    if(!matching.length)results.append(el('p','source-peek','No routes match.'));
    if(matching.length>shown)results.append(button(`Show more routes (${matching.length-shown} left)`,'quiet-button',()=>{shown+=300;render();}));
    announce(plural(matching.length,'route','routes')+'.');
  }
  for(const name of verbs) {
    const tab=button('','endpoint-tab',()=>{
      for(const sibling of tabs.children){sibling.setAttribute('aria-selected',String(sibling===tab));sibling.tabIndex=sibling===tab?0:-1;}
      results.setAttribute('aria-labelledby',tab.id);
      verb=name==='All'?'':name;shown=300;render();
    });
    tab.id='verb-'+name;tab.dataset.method=name;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','endpointResults');
    tab.setAttribute('aria-selected',String(name==='All'));tab.tabIndex=name==='All'?0:-1;
    tab.append(name,el('span','chip-count',String(name==='All'?rows.length:counts.get(name))));
    tab.addEventListener('keydown',event=>{
      const buttons=[...tabs.children],index=buttons.indexOf(tab);
      const next=event.key==='ArrowRight'?(index+1)%buttons.length:event.key==='ArrowLeft'?(index+buttons.length-1)%buttons.length:event.key==='Home'?0:event.key==='End'?buttons.length-1:null;
      if(next!==null){event.preventDefault();buttons[next].focus();buttons[next].click();}
    });
    tabs.append(tab);
  }
  results.setAttribute('aria-labelledby','verb-All');
  controls.append(tabs,searchField('Filter routes, e.g. /tasks or list_items…',value=>{query=value;shown=300;render();}),
    selectField('Group by',[['file','Router file'],['verb','HTTP verb'],['none','None']],value=>{group=value;shown=300;render();}));
  fileGroups(tree,'Routers',rows,value=>{file=value;shown=300;render();});
  const writes=rows.filter(row=>(row.effects||[]).some(isWrite)).length;
  inspectorOverview('Endpoints',[['Routes',total],['Files',new Set(rows.map(row=>row.file)).size],['Async',rows.filter(row=>row.async).length],['Write effects',writes]],
    'Hover or focus a route to preview it. Select it to open its review.');
  render();
}

// Commands and tasks: one card each, filtered by kind and text.
async function commandsPage(host,controls,tree,captured,request,counts) {
  const kinds=['commands','tasks'].filter(kind=>counts[kind]>0);
  const loaded=await Promise.all(kinds.map(kind=>fetchStarts(kind,captured)));
  if(loaded.some(result=>!result) || request!==startRequest)return;
  const byKind=Object.fromEntries(kinds.map((kind,index)=>[kind,loaded[index].rows]));
  const all=kinds.flatMap(kind=>byKind[kind].map(row=>({row,kind})));
  let kind='',query='',file='';
  const sections=new Map();
  for(const name of kinds) {
    const section=el('section','start-group'), grid=el('div','command-grid');
    section.dataset.category=name;
    const note=capNote(byKind[name].length,loaded[kinds.indexOf(name)].total,name==='commands'?'commands':'tasks');
    section.append(...(note?[note]:[]),grid);host.append(section);sections.set(name,{section,grid});
  }
  function render() {
    for(const name of kinds) {
      const {section,grid}=sections.get(name);
      const matching=byKind[name].filter(row=>(!file || row.file===file) && (!query || `${row.label} ${row.name} ${row.file}`.toLowerCase().includes(query)));
      grid.replaceChildren(...matching.map(row=>commandCard(row,name)));
      section.hidden=(kind && kind!==name) || !matching.length;
    }
    if(sections.size && [...sections.values()].every(({section})=>section.hidden)) {
      const empty=host.querySelector('.command-empty')||host.appendChild(el('p','source-peek command-empty','No commands or tasks match.'));
      empty.hidden=false;
    } else host.querySelector('.command-empty')?.setAttribute('hidden','');
  }
  const tabs=el('div','catalog-chips');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Kind');
  const entries=[['','All',all.length],...kinds.map(name=>[name,name==='commands'?'CLI commands':'Tasks & callbacks',byKind[name].length])];
  for(const [name,label,count] of entries) {
    const tab=button('','command-tab',()=>{
      kind=name;tabs.querySelectorAll('.command-tab').forEach(other=>other.setAttribute('aria-pressed',String(other===tab)));render();
    });
    tab.setAttribute('aria-pressed',String(name===''));tab.append(label,el('span','chip-count',String(count)));
    tabs.append(tab);
  }
  controls.append(...(kinds.length>1?[tabs]:[]),searchField('Search commands, tasks, and files…',value=>{query=value;render();}));
  fileGroups(tree,'Files',all.map(({row})=>row),value=>{file=value;render();});
  inspectorOverview('Commands & tasks',[['Commands',counts.commands],['Tasks',counts.tasks],['Files',new Set(all.map(({row})=>row.file)).size],
    ['Write effects',all.filter(({row})=>(row.effects||[]).some(isWrite)).length]],'Hover or focus a card to preview it. Select it to open its review.');
  render();
}

let catalogPage='endpoints';
const catalogTitles={endpoints:'Endpoints',commands:'Commands & tasks',methods:'Modules & methods'};
// The test modules you can run with python -m: a plain list, folded away.
async function loadStartGroup(category,host,cursor=0) {
  const captured=model, request=String(Number(host.dataset.request||0)+1);
  host.dataset.request=request;
  host.replaceChildren(el('p','source-peek','Loading…'));
  try {
    const result=await api('/api/starts',{snapshot:captured.snapshotId,category,cursor,limit:20});
    if(captured!==model || !host.isConnected || host.dataset.request!==request)return;
    const page=result.results;
    host.replaceChildren(...page.items.map(startButton));
    if(!page.total){host.append(el('p','source-peek',emptyStartLabels[category]));return;}
    const controls=el('div','catalog-pagination');
    controls.append(el('span','source-peek',`${cursor+1}–${cursor+page.items.length} of ${page.total}`));
    if(cursor)controls.append(button('Previous','quiet-button',()=>loadStartGroup(category,host,Math.max(0,cursor-20))));
    if(page.nextCursor!==null)controls.append(button('More '+startLabels[category].toLowerCase(),'quiet-button',()=>loadStartGroup(category,host,page.nextCursor)));
    host.append(controls);
  } catch(error) {if(captured===model && host.dataset.request===request)host.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>loadStartGroup(category,host,cursor)));}
}

// Methods of one file in source order, cached per snapshot. Used by the module cards and the review bar.
function methodsInFile(file, captured=model) {
  captured.fileMethods ||= new Map();
  if(!captured.fileMethods.has(file)) {
    const promise=fetchPages('/api/modules',{snapshot:captured.snapshotId,file},page=>page.methods)
      .then(({rows})=>rows.sort((a,b)=>a.line-b.line||a.name.localeCompare(b.name)));
    captured.fileMethods.set(file,promise);
    promise.catch(()=>captured.fileMethods.delete(file));
  }
  return captured.fileMethods.get(file);
}
// Directories of the module files: single-child chains join (src/pkg), and each file shows its method count.
function directoryTree(rows) {
  const root={name:'',path:'',dirs:new Map(),files:[]};
  for(const row of rows) {
    const parts=row.file.split('/'),leaf=parts.pop();
    let node=root;
    for(const part of parts) {
      if(!node.dirs.has(part))node.dirs.set(part,{name:part,path:node.path+part+'/',dirs:new Map(),files:[]});
      node=node.dirs.get(part);
    }
    node.files.push({...row,leaf});
  }
  const compress=node=>{
    for(const child of [...node.dirs.values()]) {
      while(child.dirs.size===1 && !child.files.length) {
        const [only]=child.dirs.values();
        child.name+='/'+only.name;child.path=only.path;child.dirs=only.dirs;child.files=only.files;
      }
      compress(child);
    }
  };
  compress(root);
  return root;
}
const treeModules=node=>node.files.length+[...node.dirs.values()].reduce((sum,child)=>sum+treeModules(child),0);
// The directory that holds most of the modules (descending while one subfolder keeps 60% or more): its subfolders become the filter chips.
function packageRoot(root,total) {
  let node=root;
  for(;;) {
    const largest=[...node.dirs.values()].sort((a,b)=>treeModules(b)-treeModules(a))[0];
    if(!largest || treeModules(largest)<total*.6)return node;
    node=largest;
  }
}

// Modules: names only until one is chosen. The sidebar tree, the folder chips, and the cards lead to the same module.
async function modulePicker(host, tree, controls, initialFile=null) {
  host.id='moduleBrowser';
  const captured=model, request=++moduleRequest;
  let openFile=initialFile, text='', dir=null, shown=100, sort='path';
  const {rows,total:listed}=await fetchPages('/api/modules',{snapshot:captured.snapshotId},page=>page.modules,moduleCap);
  if(captured!==model || request!==moduleRequest || !host.isConnected)return;
  const list=el('div','mod-list'), more=el('div','catalog-pagination'), note=capNote(rows.length,listed,'modules');
  list.id='moduleResults';host.replaceChildren(...(note?[note]:[]),list,more);
  const inDir=row=>!dir || row.file.startsWith(dir.prefix);
  const passes=row=>inDir(row) && (!text || `${row.name} ${row.file}`.toLowerCase().includes(text));
  const setOpen=file=>{
    openFile=file;
    const url=reviewURL();if(file)url.searchParams.set('module',file);else url.searchParams.delete('module');
    replaceReviewURL(url);
    tree.querySelectorAll('.tree-file').forEach(item=>{
      const active=item.dataset.file===file;
      item.classList.toggle('active',active);
      if(active){for(let node=item.parentElement;node && node!==tree;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;item.scrollIntoView({block:'nearest'});}
    });
  };
  async function fillModule(body,file) {
    body.replaceChildren(el('p','source-peek','Loading…'));
    try {
      const methods=await methodsInFile(file,captured);
      if(captured!==model || !body.isConnected)return;
      body.replaceChildren();
      const groups=new Map([['',[]]]), nested=new Set(methods.map(row=>row.name));
      for(const row of methods) {
        const parts=row.name.split('.'),leaf=parts.pop(),key=parts.join('.');
        if(!groups.has(key))groups.set(key,[]);
        groups.get(key).push({row,leaf});
      }
      if(!groups.get('').length)groups.delete('');
      if(!groups.size)body.append(el('p','source-peek','No functions in this module.'));
      for(const [key,items] of groups) {
        const wrap=key?el('details','mod-class'):el('div','mod-plain'), inner=el('div','mod-methods');
        if(key) {
          // A group named after a function in the same file holds its inner functions; any other holds a class.
          const head=el('summary','mod-head');head.append(badge(nested.has(key)?'nested':'class','class'),el('strong','',key),el('span','module-count',plural(items.length,'method','methods')));
          wrap.append(head);wrap.open=groups.size===1;
        }
        for(const {row,leaf} of items)inner.append(methodRow(row,leaf));
        wrap.append(inner);body.append(wrap);
      }
    } catch(error) {if(captured===model && body.isConnected)body.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>fillModule(body,file)));}
  }
  function methodRow(row,leaf) {
    const item=button('','mod-method',()=>startReview(row.id));item.dataset.scope=row.id;item.title=row.name;
    const top=el('span','mm-top');
    if(row.async)top.append(badge('async','async'));
    for(const route of row.routes||[]) {
      const tag=badge(route,'verb verb-'+route.split(' ')[0].toLowerCase());tag.title=route;
      top.append(tag);
    }
    if(!row.routes?.length && leaf.startsWith('_') && !leaf.startsWith('__'))top.append(badge('helper','helper'));
    top.append(el('span','mm-name',leaf));
    if(row.params!==undefined)top.append(el('span','mm-params',row.params));
    const meta=el('span','mm-meta');
    if(row.calls!==undefined)meta.append(callsFact(row));
    meta.append(...effectBadges(row),el('span','',`line ${row.line}`));
    const main=el('span','mm-main');main.append(top,meta);
    const open=el('span','mm-open','Inspect');open.append(icon('arrow',14));
    item.append(main,open);
    return bindPreview(item,row,'method');
  }
  function moduleCard(row) {
    const box=el('details','mod-item'), head=el('summary','mod-head'), body=el('div','mod-body');
    box.dataset.file=row.file;
    head.append(icon('file',18),el('strong','mod-file',baseName(row.file)),el('span','mod-path',row.file));
    const badges=el('span','mod-badges');
    badges.append(badge(plural(row.total,'method','methods')));
    if(row.routes)badges.append(badge(plural(row.routes,'route','routes'),'route'));
    if(row.async)badges.append(badge(`${row.async} async`,'async'));
    head.append(badges);
    head.title=`${row.name} · ${row.file}`;
    box.append(head,body);
    box.addEventListener('toggle',()=>{
      if(!box.open){if(openFile===row.file)setOpen(null);return;}
      list.querySelectorAll('details.mod-item[open]').forEach(other=>{if(other!==box)other.open=false;});
      setOpen(row.file);
      if(!body.childElementCount)fillModule(body,row.file);
      box.scrollIntoView({block:'nearest'});
    });
    if(row.file===openFile)box.open=true;
    return box;
  }
  function renderCards() {
    const matching=rows.filter(passes);
    if(sort==='methods')matching.sort((a,b)=>b.total-a.total||(a.file<b.file?-1:1));
    else if(sort==='name')matching.sort((a,b)=>baseName(a.file)<baseName(b.file)?-1:baseName(a.file)>baseName(b.file)?1:a.file<b.file?-1:1);
    const visible=matching.slice(0,Math.max(shown,matching.findIndex(row=>row.file===openFile)+1));
    list.replaceChildren(...visible.map(moduleCard));
    if(!matching.length)list.append(el('p','source-peek','No matching modules.'));
    more.replaceChildren(el('span','source-peek',`${plural(visible.length,'module','modules')} of ${matching.length}`));
    if(visible.length<matching.length)more.append(button('More modules','quiet-button',()=>{shown+=100;renderCards();}));
  }
  // The folder filter: chips for the main package's subfolders and for other top folders, or a folder chosen in the sidebar.
  const treeRoot=directoryTree(rows), main=packageRoot(treeRoot,rows.length);
  const chips=el('div','catalog-chips');chips.setAttribute('role','group');chips.setAttribute('aria-label','Folder');
  const folderNote=el('p','catalog-note folder-note');folderNote.hidden=true;
  const byCount=nodes=>[...nodes].sort((a,b)=>treeModules(b)-treeModules(a));
  const inside=byCount(main.dirs.values()).slice(0,6);
  const outside=main===treeRoot?[]:byCount(treeRoot.dirs.values()).filter(node=>!main.path.startsWith(node.path)).slice(0,2);
  const chipNodes=[...inside,...outside].slice(0,8);
  const chipButtons=new Map();
  function setDir(node) {
    dir=node?{prefix:node.path,name:node.name}:null;shown=100;
    for(const [path,chip] of chipButtons)chip.setAttribute('aria-pressed',String(dir?path===dir.prefix:path===''));
    folderNote.replaceChildren();
    if(dir && !chipButtons.has(dir.prefix)) {
      folderNote.append(`Showing modules in ${dir.prefix} `,button('Show all','quiet-button',()=>setDir(null)));
      folderNote.hidden=false;
    } else folderNote.hidden=true;
    renderCards();
  }
  if(chipNodes.length>1) {
    for(const [node,label,count] of [[null,'All',rows.length],...chipNodes.map(child=>[child,child.name,treeModules(child)])]) {
      const chip=button('','command-tab',()=>setDir(node));
      chip.append(label,el('span','chip-count',String(count)));
      chipButtons.set(node?node.path:'',chip);chips.append(chip);
    }
    chipButtons.get('').setAttribute('aria-pressed','true');
    for(const [path,chip] of chipButtons)if(path)chip.setAttribute('aria-pressed','false');
  }
  const search=searchField('Filter modules by name or path…',value=>{text=value;shown=100;renderCards();});
  const sorter=selectField('Sort',[['path','Path'],['methods','Most methods'],['name','Name']],value=>{sort=value;renderCards();});
  controls.append(...(chipNodes.length>1?[chips]:[]),search,sorter,folderNote);
  const root=$('#startRoot');root.textContent=(main.path||'').replace(/\/$/,'');root.hidden=!main.path;
  // Choosing a module keeps the filters that already include it, and clears the rest so its card is in the list.
  function openModule(file) {
    const row=rows.find(entry=>entry.file===file);
    if(row && !inDir(row))setDir(null);
    if(row && text && !passes(row)){text='';search.querySelector('input').value='';}
    openFile=file;renderCards();
    const card=list.querySelector(`details.mod-item[data-file="${CSS.escape(file)}"]`);
    if(card){card.open=true;card.scrollIntoView({block:'start'});}
  }
  // Sidebar: the directory tree. Opening a folder shows its modules; closing it lifts that filter.
  const fileButton=(row,label)=>{
    const item=button('','tree-file',()=>openModule(row.file));
    item.dataset.file=row.file;item.title=row.file;
    item.append(icon('file',14),el('span','tree-name',label),el('span','tree-count',row.total+'m'));
    return item;
  };
  function treeNode(node,open) {
    const box=el('details','tree-dir'), head=el('summary','tree-head'), inner=el('div','tree-children');
    head.append(icon('folder',14),el('span','tree-name',node.name),el('span','tree-count',plural(treeModules(node),'mod','mods')));
    head.addEventListener('click',()=>{
      // The click has not toggled the folder yet: box.open is its state before.
      if(!box.open)setDir(node);
      else if(dir?.prefix===node.path)setDir(null);
    });
    for(const child of [...node.dirs.values()].sort((a,b)=>a.name<b.name?-1:1))inner.append(treeNode(child,false));
    for(const row of node.files.sort((a,b)=>a.leaf<b.leaf?-1:1))inner.append(fileButton(row,row.leaf));
    box.append(head,inner);box.open=open;
    return box;
  }
  const tops=byCount(treeRoot.dirs.values());
  tree.replaceChildren(el('p','nav-label','Package directory tree'),
    ...tops.map((node,index)=>treeNode(node,index===0)),...treeRoot.files.map(row=>fileButton(row,baseName(row.file))));
  treeKeys(tree);
  tree.hidden=false;
  inspectorOverview('Modules & methods',[['Modules',listed],['Methods',rows.reduce((sum,row)=>sum+row.total,0)],['Async',rows.reduce((sum,row)=>sum+row.async,0)],['Routes',rows.reduce((sum,row)=>sum+row.routes,0)]],
    'Open a module, then hover or focus a method to preview it. Select it to open its review.');
  renderCards();
  if(openFile)setOpen(openFile);
}
let moduleRequest=0;

async function showStartPage(page=null) {
  const captured=model, request=++startRequest;
  ++selectionRequest; ++navigationRequest;
  closeComparison();$('#search').value='';$('#navigation').replaceChildren();
  setWorkflowMode('starts');
  const controls=$('#startControls'), tree=$('#sideTree'), root=$('#startRoot');
  controls.replaceChildren();tree.replaceChildren();tree.hidden=true;root.hidden=true;
  $('#startInspector').replaceChildren();
  const host=$('#startGroups');host.replaceChildren(el('p','source-peek','Loading…'));
  try {
    const [result,moduleList]=await Promise.all([api('/api/starts',{snapshot:captured.snapshotId,limit:1}),api('/api/modules',{snapshot:captured.snapshotId,limit:1})]);
    if(captured!==model || request!==startRequest)return;
    const requested=page || reviewURL().searchParams.get('page');
    const available={endpoints:result.counts.http>0,commands:result.counts.commands+result.counts.tasks>0,methods:true};
    $('#endpointsTab').hidden=!available.endpoints;$('#commandsTab').hidden=!available.commands;
    $('#endpointsTab .tab-count').textContent=result.counts.http||'';$('#commandsTab .tab-count').textContent=result.counts.commands+result.counts.tasks||'';
    $('#methodsTab .tab-count').textContent=moduleList.modules.total||'';
    catalogPage=Object.hasOwn(catalogTitles,requested)&&available[requested]?requested:result.counts.http?'endpoints':result.counts.commands+result.counts.tasks?'commands':'methods';
    const url=reviewURL();url.hash='';url.searchParams.set('page',catalogPage);if(page || catalogPage!=='methods')url.searchParams.delete('module');replaceReviewURL(url);
    setWorkflowMode('starts');
    $('#startProject').textContent=model.project+' · '+model.coverage.files+' Python files';
    host.replaceChildren();host.classList.add('single-page');
    if(catalogPage==='endpoints')await endpointsPage(host,controls,tree,captured,request);
    else if(catalogPage==='commands') {
      await commandsPage(host,controls,tree,captured,request,result.counts);
      if(captured===model && request===startRequest && result.counts.testCommands) {
        // Test files with a main guard are runnable, but rarely where a review starts.
        const tests=el('details','start-group test-commands'), content=el('div','test-list');
        tests.append(el('summary','','Test modules you can run · '+result.counts.testCommands),content);
        tests.addEventListener('toggle',()=>{if(tests.open && !content.childElementCount)loadStartGroup('testCommands',content);});
        host.append(tests);
      }
    } else {
      const content=el('div');host.append(content);
      await modulePicker(content,tree,controls,reviewURL().searchParams.get('module'));
    }
    if(captured!==model || request!==startRequest)return;
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
  $('#repositoryBrowser').hidden=false;$('#workflowBrowser').hidden=true;$('#changesBrowser').hidden=true;$('#sideTree').hidden=true;
  if(typeof isNarrow==='function' && isNarrow() && sidebarCollapsed)setSidebar(false,false);
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
  const b=$('#refreshButton'); b.disabled=true;b.querySelector('.sr-only').textContent=refresh?'Reading source…':'Indexing…';b.classList.add('busy');
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
    $('#sideFooter').replaceChildren(el('span','side-status','Source only · not executed'),el('span','side-files',plural(model.coverage.files,'file','files')));
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
  finally{b.disabled=false;b.classList.remove('busy');b.querySelector('.sr-only').textContent='Refresh source';}
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
