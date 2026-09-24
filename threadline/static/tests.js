'use strict';
// Related tests for the selected method, and a second code pane that shows a
// test (or the code a test exercises) beside the method's own source.
let testsRequest = 0, pairRequest = 0, testsShown = null, relatedRequest = 0, relatedId = null;
const relationLabels = {direct:'Direct', route:'Route', indirect:'Indirect', name:'Name match'};

function closePair() {
  ++pairRequest;
  $('#pairPane').hidden = true; $('#pairCode').replaceChildren();
  $('.source-panel').classList.remove('paired');
  document.querySelectorAll('.tab-panel .test-row.active').forEach(row => row.classList.remove('active'));
}

async function loadTests(id, cursor=0) {
  const host = $('#testsPanel'), scope = model.scopes[id];
  // Opening a workflow selects its entry method again; keep the list and any open test.
  if (cursor === 0 && testsShown?.model === model && testsShown.id === id) return;
  const request = ++testsRequest, captured = model;
  if (cursor === 0) { closePair(); testsShown = {model, id}; }
  if (!scope || ['module', 'class'].includes(scope.kind)) return;
  if (cursor === 0) host.replaceChildren(el('p', 'source-peek', 'Finding related tests…'));
  try {
    const result = await api('/api/tests', {symbol:id, snapshot:captured.snapshotId, cursor, limit:20});
    if (request !== testsRequest || captured !== model || state.scope !== id) return;
    renderTests(host, id, result, cursor);
  } catch (error) {
    if (request !== testsRequest || captured !== model) return;
    if (cursor === 0) testsShown = null;
    host.replaceChildren(el('p', 'error', error.message), button('Retry', 'quiet-button', () => loadTests(id, cursor)));
  }
}

function renderTests(host, id, result, cursor) {
  const isTest = result.role === 'test', page = result.items;
  if (cursor === 0) {
    host.replaceChildren();
    if (!page.total) {
      host.append(el('p', 'tests-empty', isTest ? 'No calls from this test lead to code Threadline could find.'
        : result.testCount ? 'No test reaches this method through calls, routes, or names.'
        : 'No tests were found. If your tests live outside the analyzed folders, include them with --source-root.'));
      return;
    }
    host.append(el('p', 'tests-count-line', isTest
      ? `This test exercises ${page.total} method${page.total === 1 ? '' : 's'}. Select one to see it beside the test.`
      : `${page.total} test${page.total === 1 ? ' reaches' : 's reach'} this method. Select one to see it beside the code.`), el('div', 'test-list'));
  }
  const list = host.querySelector('.test-list');
  host.querySelector('.tests-more')?.remove();
  for (const row of page.items) list.append(linkRow(row, isTest ? 'subject' : 'test'));
  if (page.nextCursor !== null) {
    const more = button(`Show ${Math.min(20, page.total - page.nextCursor)} more`, 'quiet-button tests-more', () => { more.disabled = true; loadTests(id, page.nextCursor); });
    host.append(more);
  }
}

// kind: 'test' (a test of this method), 'subject' (code a test exercises), or 'caller'.
function linkRow(row, kind, calledId=null) {
  const uncertain = row.status === 'possible';
  const item = el('div', 'test-row ' + (kind === 'test' ? row.relation : 'direct') + (uncertain ? ' uncertain' : ''));
  const pick = button('', 'test-pick', () => kind === 'caller' ? openCallerComparison(row,calledId) : showPair(row, kind, item));
  pick.setAttribute('aria-label', `${kind === 'caller' ? 'Compare caller' : 'Show '+(kind === 'test' ? 'test' : 'code of')} ${row.name}: ${row.reason}`);
  const top = el('span', 'test-top');
  top.append(el('span', 'test-badge', kind === 'test' ? relationLabels[row.relation] : certaintyLabel(row.status)));
  top.append(el('code', 'test-name', row.name));
  const reason = kind === 'caller' ? `Line ${row.callsite.start}` : row.reason;
  pick.append(top, el('span', 'test-reason', reason + (uncertain && kind === 'test' ? ' · probably' : '')), el('span', 'test-file', `${row.file}:${row.line}`));
  const open = button(kind === 'caller' ? 'Compare →' : 'Go to →', 'test-open', () => kind === 'caller' ? openCallerComparison(row,calledId) : startReview(row.id));
  open.setAttribute('aria-label', `${kind === 'caller'?'Compare':'Go to'} ${row.name}`);
  item.append(pick, open);
  return item;
}

async function showPair(row, kind, item) {
  const request = ++pairRequest, captured = model;
  document.querySelectorAll('.tab-panel .test-row.active').forEach(other => other.classList.remove('active'));
  item.classList.add('active');
  $('#pairLabel').textContent = {test:'TEST', subject:'CODE UNDER TEST', caller:'CALLER'}[kind];
  $('#pairTitle').textContent = row.name;
  $('#pairFile').textContent = `${row.file}:${row.line}`;
  $('#pairPane').hidden = false; $('.source-panel').classList.add('paired');
  const code = $('#pairCode'); code.replaceChildren(el('p', 'source-peek', 'Loading…'));
  // Tests and callers highlight the line that makes the call; tested code shows its definition.
  const focus = kind === 'subject' ? null : row.callsite, span = row.span;
  const start = span.start, end = Math.min(span.end, start + 199);
  try {
    const result = await api('/api/source', {snapshot:captured.snapshotId, file:span.file, start, end});
    if (request !== pairRequest || captured !== model) return;
    code.replaceChildren(); code.classList.toggle('wrap-code', state.wrap);
    result.source.split('\n').forEach((value, index) => {
      const number = start + index, marked = focus && focus.file === span.file && number >= focus.start && number <= focus.end;
      const line = el('div', 'code-line' + (marked ? ' focus' : '')); line.dataset.line = String(number);
      const content = el('span', 'line-content'); content.innerHTML = syntax(value) || ' ';
      line.append(el('span', 'line-number', String(number)), content); code.append(line);
    });
    if (result.truncated) code.append(el('p', 'source-peek', 'Showing the first 200 lines. Use Go to → to read the rest.'));
    const marked = code.querySelector('.code-line.focus');
    code.scrollTop = marked ? Math.max(0, marked.offsetTop - code.offsetTop - 46) : 0;
    announce(`${row.name} shown beside the method`);
  } catch (error) {
    if (request === pairRequest && captured === model) code.replaceChildren(el('p', 'error', error.message), button('Retry', 'quiet-button', () => showPair(row, kind, item)));
  }
}

$('#pairClose').addEventListener('click', () => { const active = $('.tab-panel .test-row.active .test-pick'); closePair(); active?.focus(); });

function prepareRelatedTests(id) {
  relatedId=id; ++relatedRequest;
  $('#relatedTests').open=false;
  $('#relatedTestsContent').replaceChildren();
  $('#relatedTestsCount').textContent='';
}

async function loadRelatedTests(id,cursor=0) {
  const request=++relatedRequest,captured=model,host=$('#relatedTestsContent');
  if(cursor===0)host.replaceChildren(el('p','source-peek','Finding related tests…'));
  try{
    const result=await api('/api/tests',{symbol:id,snapshot:captured.snapshotId,cursor,limit:20});
    if(request!==relatedRequest||captured!==model||relatedId!==id||state.scope!==id)return;
    if(cursor===0){
      host.replaceChildren();
      $('#relatedTestsCount').textContent=result.items.total?'· '+result.items.total:'';
      $('#relatedTests').firstElementChild.firstChild.textContent=result.role==='test'?'Related code ':'Related tests ';
      if(!result.items.total)host.append(el('p','source-peek',result.role==='test'?'No linked code was found.':'No related test was found in the indexed source. A link does not prove a test ran or covered every path.'));
    }
    host.querySelector('.tests-more')?.remove();
    for(const row of result.items.items)host.append(relatedTestItem(row,result.role==='test'));
    if(result.items.nextCursor!==null){
      const more=button('Show more related tests','quiet-button tests-more',()=>loadRelatedTests(id,result.items.nextCursor));host.append(more);
    }
  }catch(error){
    if(request!==relatedRequest||captured!==model)return;
    host.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>loadRelatedTests(id,cursor)));
  }
}

function relatedTestItem(row,isTest){
  const item=el('details','related-test');
  item.append(el('summary','',`${row.name} · ${row.file}:${row.line}`),el('span','test-reason',`${row.reason} · ${row.status==='possible'?'possible link':'source-backed link'}; execution and path coverage are not measured.`));
  const code=el('div','code-window wrap-code');code.setAttribute('role','region');code.setAttribute('aria-label',`${isTest?'Related method':'Related test'} ${row.name} source`);code.tabIndex=0;item.append(code);
  let loaded=false;
  item.addEventListener('toggle',async()=>{
    if(!item.open||loaded)return;
    const captured=model;code.replaceChildren(el('p','source-peek','Loading bounded source…'));
    try{
      const source=await boundedMethodLines(row.id,captured.snapshotId);
      if(captured!==model||!item.isConnected)return;
      code.replaceChildren(...source.rows.map(line=>codeLine(line.number,line.text,Boolean(row.callsite&&line.number>=row.callsite.start&&line.number<=row.callsite.end))));
      loaded=true;
    }catch(error){if(captured===model&&item.isConnected)code.replaceChildren(el('p','error',error.message),button('Retry','quiet-button',()=>{item.open=false;item.open=true;}));}
  });
  return item;
}

$('#relatedTests').addEventListener('toggle',()=>{
  if($('#relatedTests').open && relatedId===state.scope && !$('#relatedTestsContent').childElementCount)loadRelatedTests(state.scope);
});
