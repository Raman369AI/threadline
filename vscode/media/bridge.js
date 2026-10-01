'use strict';
(() => {
  const vscode = acquireVsCodeApi(), pending = new Map();
  let serial = 0;
  const call = (type, data) => new Promise((resolve, reject) => {
    if (pending.size >= 64) { reject(new Error('Too many pending requests')); return; }
    const id = ++serial;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Threadline request timed out. Refresh the review.')); }, 240000);
    pending.set(id, {resolve, reject, timer});
    vscode.postMessage({id, type, ...data});
  });
  window.threadlineHost = {
    location: 'https://threadline.invalid/' + document.querySelector('meta[name="threadline-start"]').content,
    request: (path, params, options) => call('query', {path, params, method:options.method || 'GET'}),
    ready: data => {
      if (new URL(window.threadlineHost.location).searchParams.has('changes')) setWorkflowMode('changes');
      vscode.postMessage({type:'ready', ...data});
    },
    openSource: data => call('source', data).catch(error => reportError(error, null, 'editor'))
  };
  window.addEventListener('message', async ({data}) => {
    if (data.type === 'response') {
      const request = pending.get(data.id); if (!request) return;
      clearTimeout(request.timer); pending.delete(data.id);
      if (data.error) request.reject(new Error(data.error)); else request.resolve(data.result);
    } else if (data.type === 'stale') {
      document.querySelector('#hostStatus').textContent = data.message;
    } else if (data.type === 'refresh') {
      await load(true);
    } else if (data.type === 'navigate' && typeof data.start === 'string') {
      window.threadlineHost.location = new URL(data.start, 'https://threadline.invalid/').href;
      state.scope = null; state.stack = [];  // A host navigation starts a new reading path.
      await load();
    }
  });
  document.addEventListener('DOMContentLoaded', () => {
    const syncTheme = () => document.documentElement.dataset.theme = document.body.classList.contains('vscode-light') || document.body.classList.contains('vscode-high-contrast-light') ? 'light' : 'dark';
    syncTheme(); new MutationObserver(syncTheme).observe(document.body, {attributes:true, attributeFilter:['class']});
    document.querySelector('#hostExport').addEventListener('click', () => call('export', {}).catch(error => reportError(error, null, 'export')));
    document.addEventListener('click', event => {
      const anchor = event.target.closest('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (href?.startsWith('?') || href === '#') {
        event.preventDefault(); window.threadlineHost.location = new URL(href === '#' ? '/' : href, window.threadlineHost.location).href; load();
      }
    });
  }, {once:true});
})();
