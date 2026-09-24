'use strict';
// Related tests for the selected method, and a second code pane that shows a
// test (or the code a test exercises) beside the method's own source.
let testsRequest = 0, pairRequest = 0, testsShown = null;
const relationLabels = {direct:'Direct', route:'Route', indirect:'Indirect', name:'Name match'};

function closePair() {
  ++pairRequest;
  $('#pairPane').hidden = true; $('#pairCode').replaceChildren();
  $('.source-panel').classList.remove('paired');
  document.querySelectorAll('#testsPanel .test-row.active').forEach(row => row.classList.remove('active'));
}

async function loadTests(id, cursor=0) {
  const host = $('#testsPanel'), scope = model.scopes[id];
  // Opening a workflow selects its entry method again; keep the list and any open test.
  if (cursor === 0 && testsShown?.model === model && testsShown.id === id) return;
  const request = ++testsRequest, captured = model;
  if (cursor === 0) { closePair(); testsShown = {model, id}; }
  host.hidden = !scope || ['module', 'class'].includes(scope.kind);
  if (host.hidden) return;
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
    const heading = el('div', 'tests-heading');
    heading.append(el('span', 'payload-label', isTest ? 'This test exercises' : 'Tests'));
    heading.append(el('span', 'tests-count', isTest ? `${page.total} method${page.total === 1 ? '' : 's'}`
      : page.total ? `${page.total} related` : ''));
    host.replaceChildren(heading);
    if (!page.total) {
      host.append(el('p', 'tests-empty', isTest ? 'No calls from this test resolve to indexed source.'
        : result.testCount ? 'No test reaches this method through calls, routes, or names.'
        : 'No tests were found in the analyzed source. If tests live outside the source root, include their folder.'));
      return;
    }
    host.append(el('p', 'tests-hint', `Select one to see its code next to this ${isTest ? 'test' : 'method'}. Linked from source; tests were not run.`), el('div', 'test-list'));
  }
  const list = host.querySelector('.test-list');
  host.querySelector('.tests-more')?.remove();
  for (const row of page.items) list.append(testRow(row, isTest));
  if (page.nextCursor !== null) {
    const more = button(`Show ${Math.min(20, page.total - page.nextCursor)} more`, 'quiet-button tests-more', () => { more.disabled = true; loadTests(id, page.nextCursor); });
    host.append(more);
  }
}

function testRow(row, isTest) {
  const item = el('div', 'test-row ' + (isTest ? 'direct' : row.relation) + (row.status === 'possible' ? ' uncertain' : ''));
  const pick = button('', 'test-pick', () => showPair(row, isTest, item));
  pick.setAttribute('aria-label', `${isTest ? 'Show code for' : 'Show test'} ${row.name}: ${row.reason}`);
  const top = el('span', 'test-top');
  if (!isTest) top.append(el('span', 'test-badge', relationLabels[row.relation]));
  top.append(el('code', 'test-name', row.name));
  pick.append(top, el('span', 'test-reason', row.reason + (row.status === 'possible' ? ' · possible' : '')), el('span', 'test-file', `${row.file}:${row.line}`));
  const open = button('Open →', 'test-open', () => startReview(row.id));
  open.title = 'Review this ' + (isTest ? 'method' : 'test') + "'s flow";
  open.setAttribute('aria-label', `Open ${row.name}`);
  item.append(pick, open);
  return item;
}

async function showPair(row, isTest, item) {
  const request = ++pairRequest, captured = model;
  document.querySelectorAll('#testsPanel .test-row.active').forEach(other => other.classList.remove('active'));
  item.classList.add('active');
  $('#pairLabel').textContent = isTest ? 'CODE UNDER TEST' : 'TEST CODE';
  $('#pairTitle').textContent = row.name;
  $('#pairFile').textContent = `${row.file}:${row.line}`;
  $('#pairPane').hidden = false; $('.source-panel').classList.add('paired');
  const code = $('#pairCode'); code.replaceChildren(el('p', 'source-peek', 'Loading…'));
  // A test's call site is the evidence; for code under test, the definition is.
  const focus = isTest ? row.span : row.callsite, span = row.span;
  const start = span.start, end = Math.min(span.end, start + 199);
  try {
    const result = await api('/api/source', {snapshot:captured.snapshotId, file:span.file, start, end});
    if (request !== pairRequest || captured !== model) return;
    code.replaceChildren(); code.classList.toggle('wrap-code', state.wrap);
    result.source.split('\n').forEach((value, index) => {
      const number = start + index, marked = !isTest && focus.file === span.file && number >= focus.start && number <= focus.end;
      const line = el('div', 'code-line' + (marked ? ' focus' : '')); line.dataset.line = String(number);
      const content = el('span', 'line-content'); content.innerHTML = syntax(value) || ' ';
      line.append(el('span', 'line-number', String(number)), content); code.append(line);
    });
    if (result.truncated) code.append(el('p', 'source-peek', 'Showing the first 200 lines. Open it to read the rest.'));
    const marked = code.querySelector('.code-line.focus');
    code.scrollTop = marked ? Math.max(0, marked.offsetTop - code.offsetTop - 46) : 0;
    announce(`${isTest ? 'Code' : 'Test'} ${row.name} shown beside the method`);
  } catch (error) {
    if (request === pairRequest && captured === model) code.replaceChildren(el('p', 'error', error.message), button('Retry', 'quiet-button', () => showPair(row, isTest, item)));
  }
}

$('#pairClose').addEventListener('click', () => { const active = $('#testsPanel .test-row.active .test-pick'); closePair(); active?.focus(); });
