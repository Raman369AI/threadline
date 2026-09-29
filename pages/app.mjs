import {parseRepository, sourceFolder, fetchRepository, reviewLink, linkRequest, badgeMarkdown} from './github.mjs';

const $ = selector => document.querySelector(selector);
let active = null, reviewURL = null;
function status(message, value, max) {
  $('#status').textContent = message;
  if (max) { $('#progress').max = max; $('#progress').value = value; }
  else $('#progress').removeAttribute('value');
}
function busy(value) {
  for (const input of document.querySelectorAll('form input, #generate')) input.disabled = value;
  $('#cancel').hidden = !value;
  $('#progress').hidden = !value;
  $('#review-form').setAttribute('aria-busy', String(value));
}
function finish(run) {
  run.controller.abort();
  run.worker?.terminate();
  clearTimeout(run.timer);
  if (active === run) { active = null; busy(false); }
}
function fail(run, message) {
  if (active !== run) return;
  finish(run);
  status('Review could not be generated.');
  $('#error').textContent = message;
  $('#error').hidden = false;
}
$('#cancel').addEventListener('click', () => {
  if (!active) return;
  finish(active);
  status('Cancelled. You can start another review.');
  $('#generate').focus();
});
$('#review-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (active) return;
  $('#error').hidden = true;
  let request;
  try { request = {...parseRepository($('#repository').value), ref:$('#ref').value.trim(), folder:sourceFolder($('#folder').value)}; }
  catch (error) { $('#error').textContent = error.message; $('#error').hidden = false; return; }
  if (!window.isSecureContext || !window.Worker || !window.WebAssembly) {
    $('#error').textContent = 'Use a current browser over HTTPS (or localhost) to run Threadline.';
    $('#error').hidden = false; return;
  }
  const link = reviewLink(request, location.href);
  history.replaceState(null, '', link);
  const run = {controller:new AbortController(), worker:null, timer:null};
  active = run; busy(true);
  $('#result').hidden = true;
  $('#preview').removeAttribute('src');
  $('#download').removeAttribute('href');
  if (reviewURL) { URL.revokeObjectURL(reviewURL); reviewURL = null; }
  run.timer = setTimeout(() => fail(run, 'This review took longer than five minutes. Try a smaller source folder or use the local CLI.'), 5 * 60 * 1000);
  try {
    const source = await fetchRepository(request, {signal:run.controller.signal, onProgress:(...args) => {
      if (active === run) status(...args);
    }});
    if (active !== run) return;
    const worker = run.worker = new Worker(new URL('./worker.js', import.meta.url));
    worker.onerror = event => fail(run, event.message || 'The browser could not run the analyzer. Try reloading or using the local CLI.');
    worker.onmessage = ({data}) => {
      if (active !== run) return;
      if (data.type === 'progress') { status(data.message); return; }
      if (data.type === 'error') { fail(run, data.message); return; }
      if (data.type !== 'complete') return;
      reviewURL = URL.createObjectURL(new Blob([data.html], {type:'text/html;charset=utf-8'}));
      $('#download').href = reviewURL;
      $('#download').download = `${source.owner}-${source.repo}-${source.sha.slice(0, 7)}-review.html`;
      $('#result-title').textContent = source.owner + '/' + source.repo;
      $('#result-info').textContent = `${data.summary.files} Python files · ${data.summary.methods} methods · Commit ${source.sha.slice(0, 7)}`;
      const notes = [source.folder ? `Source folder: ${source.folder}.` : 'Entire repository, with standard build and environment folders excluded.'];
      if (source.skippedLinks) notes.push(`${source.skippedLinks} symbolic links or submodules were not followed.`);
      if (data.summary.errors) notes.push(`${data.summary.errors} analysis problems; see Instructions → Coverage in the review.`);
      $('#coverage-note').textContent = notes.join(' ');
      $('#review-link').value = link;
      $('#badge-markdown').value = badgeMarkdown(link);
      $('#preview').src = reviewURL;
      $('#result').hidden = false;
      finish(run);
      status('Your review is ready.');
      $('#result-title').focus();
    };
    worker.postMessage(source, source.sources.map(file => file.bytes.buffer));
  } catch (error) { if (active === run) fail(run, error.message); }
});
for (const button of document.querySelectorAll('[data-copy]')) {
  button.addEventListener('click', async () => {
    const field = $('#' + button.dataset.copy), label = button.textContent;
    try { await navigator.clipboard.writeText(field.value); button.textContent = 'Copied'; }
    catch { field.select(); button.textContent = 'Press Ctrl+C'; }
    setTimeout(() => { button.textContent = label; }, 2000);
  });
}
// A review link (?repo=owner/name&ref=…&folder=…) fills the form and starts the review.
try {
  const request = linkRequest(location.search);
  if (request) {
    $('#repository').value = `https://github.com/${request.owner}/${request.repo}`;
    $('#ref').value = request.ref;
    $('#folder').value = request.folder;
    if (request.ref || request.folder) $('#options').open = true;
    $('#review-form').requestSubmit();
  }
} catch (error) { $('#error').textContent = error.message; $('#error').hidden = false; }
