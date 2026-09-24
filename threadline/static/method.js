'use strict';
// Method page: summary sentence, Steps/Tests/Callers tabs, the path bar,
// the reading guide, and keyboard shortcuts.
let overviewRequest = 0, overviewShown = null, overviewData = null;
let selectedMethodView = 'dataflow', lastAnalysisView = 'dataflow';

function selectTab(name, focus=false) {
  const tabs = [...document.querySelectorAll('#methodTabs [role=tab]')];
  const tab = tabs.find(item => item.dataset.tab === name && !item.hidden) || tabs[0];
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
    if(item.dataset.tab!=='code')$('#' + item.getAttribute('aria-controls')).hidden = !selected;
  }
  selectedMethodView=tab.dataset.tab;
  if(selectedMethodView!=='code')lastAnalysisView=selectedMethodView;
  if(typeof setCodeFull==='function')setCodeFull(selectedMethodView==='code');
  if(selectedMethodView!=='tests')closePair();
  if (tab.dataset.tab === 'tests') loadTests(state.scope);
  if (tab.dataset.tab === 'callers') renderCallers();
  if(focus)(tab.dataset.tab==='code'?$('#restoreCode'):tab).focus();
}

async function loadOverview(id) {
  const scope = model.scopes[id];
  // A workflow selects its entry method again; keep the open tab and list.
  if (overviewShown?.model === model && overviewShown.id === id) return;
  overviewShown = {model, id}; overviewData = null;
  const request = ++overviewRequest, captured = model, callable = !['module', 'class'].includes(scope.kind);
  $('#methodWhere').textContent = `${scope.file}:${scope.span.start} · ${scope.async ? 'async ' : ''}${scope.kind}`;
  $('#methodSummary').textContent = '';
  $('#methodTabs').hidden = !callable;
  $('#testsCount').textContent = $('#callersCount').textContent = '';
  $('#callersPanel').replaceChildren();
  selectTab(selectedMethodView);
  if (!callable) return;
  try {
    const data = await api('/api/overview', {symbol:id, snapshot:captured.snapshotId, limit:20});
    if (request !== overviewRequest || captured !== model) return;
    overviewData = data;
    $('#methodSummary').textContent = data.summary;
    $('#tab-tests').firstChild.textContent = data.role === 'test' ? 'Exercises ' : 'Tests ';
    $('#testsCount').textContent = data.counts.tests;
    $('#callersCount').textContent = data.counts.callers;
    for (const [tab, count] of [['#tab-tests', data.counts.tests], ['#tab-callers', data.counts.callers]]) $(tab).classList.toggle('empty', !count);
    if (!$('#callersPanel').hidden) renderCallers();
  } catch (error) {
    if (request === overviewRequest && captured === model) { overviewShown = null; $('#methodSummary').textContent = 'Summary unavailable: ' + error.message; }
  }
}

async function renderCallers(cursor=0) {
  const host = $('#callersPanel'), data = overviewData;
  if (!data) { host.replaceChildren(el('p', 'source-peek', 'Finding callers…')); return; }
  let page = data.callers;
  if (cursor) {
    try {
      const more = await api('/api/overview', {symbol:data.symbol, snapshot:data.snapshotId, cursor, limit:20});
      if (overviewData !== data) return;
      page = more.callers;
    } catch (error) { host.append(el('p', 'error', error.message)); return; }
  } else {
    host.replaceChildren(el('p', 'tests-count-line', page.total
      ? `${page.total} ${page.total === 1 ? 'place calls' : 'places call'} this method. Select one to see the call beside this code.`
      : 'Nothing in the analyzed source calls this method directly. Routes, commands, and callbacks are called by frameworks instead.'), el('div', 'test-list'));
  }
  host.querySelector('.tests-more')?.remove();
  const list = host.querySelector('.test-list');
  for (const row of page.items) list.append(linkRow(row, 'caller'));
  if (page.nextCursor !== null) {
    const more = button(`Show ${Math.min(20, page.total - page.nextCursor)} more`, 'quiet-button tests-more', () => { more.disabled = true; renderCallers(page.nextCursor); });
    host.append(more);
  }
}

function renderPathBar() {
  const host = $('#pathBar');
  host.hidden = !state.stack.length;
  host.replaceChildren();
  if (host.hidden) return;
  const previous = state.stack.at(-1);
  const back = button('← Back to caller', 'quiet-button path-back', returnToCaller);
  back.title = `Return to ${scopeName(previous.invoker || previous.scope)}; this call's result goes to ${previous.destination}`;
  const trail = el('ol', 'path-trail');
  state.stack.forEach((frame, index) => {
    const item = el('li');
    item.append(button(scopeName(frame.scope), 'path-crumb', () => returnTo(index)));
    trail.append(item);
  });
  const current = el('li'), label = el('span', 'path-current', scopeName(state.scope));
  label.setAttribute('aria-current', 'page'); current.append(label); trail.append(current);
  host.append(back, trail);
}

function toggleHelp(open) {
  const panel = $('#helpPanel'), show = open ?? panel.hidden;
  panel.hidden = !show; $('#helpButton').setAttribute('aria-expanded', String(show));
  if (show) panel.focus(); else if (panel.contains(document.activeElement) || document.activeElement === document.body) $('#helpButton').focus();
}

function moveStep(offset) {
  if ($('#stepsPanel').hidden) selectTab('steps');
  const heads = [...$('#flow').querySelectorAll('.op-head')].filter(head => head.offsetParent !== null);
  if (!heads.length) return;
  const current = heads.indexOf(state.selectedElement?.querySelector(':scope > .op-card > .op-head'));
  const next = heads[current === -1 ? (offset > 0 ? 0 : heads.length - 1) : Math.min(heads.length - 1, Math.max(0, current + offset))];
  next.focus(); next.click(); next.scrollIntoView({block:'nearest'});
}

document.querySelectorAll('#methodTabs [role=tab]').forEach(tab => {
  tab.addEventListener('click', () => selectTab(tab.dataset.tab));
  tab.addEventListener('keydown', event => {
    const tabs = [...document.querySelectorAll('#methodTabs [role=tab]')], index = tabs.indexOf(tab);
    const target = {ArrowRight: tabs[(index + 1) % tabs.length], ArrowLeft: tabs[(index + tabs.length - 1) % tabs.length], Home: tabs[0], End: tabs.at(-1)}[event.key];
    if (target) { event.preventDefault(); selectTab(target.dataset.tab, true); }
  });
});
$('#helpButton').addEventListener('click', () => toggleHelp());
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest?.('input, textarea, select, [contenteditable]')) return;
  if (event.key === 'Escape' && !$('#helpPanel').hidden) { toggleHelp(false); return; }
  if (event.key === '?') { event.preventDefault(); toggleHelp(); return; }
  if (!state.scope || $('.workspace').classList.contains('choosing') || !$('#comparisonPanel').hidden) return;
  const tab = {d:'dataflow',s:'steps',t:'tests',c:'callers'}[event.key];
  if (tab && !$('#methodTabs').hidden) { event.preventDefault(); selectTab(tab, true); }
  else if (event.key === 'j' || event.key === 'k') { event.preventDefault(); moveStep(event.key === 'j' ? 1 : -1); }
  else if (event.key === 'Backspace' && state.stack.length) { event.preventDefault(); returnToCaller(); }
});
