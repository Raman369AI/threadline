// Fetch only source data. Repository code is never imported or evaluated.
export const LIMITS = Object.freeze({files:1500, bytes:16 * 1024 * 1024, fileBytes:2 * 1024 * 1024});
const EXCLUDED = new Set(['.git','.venv','venv','env','__pycache__','node_modules','dist','build','.tox','.mypy_cache','.pytest_cache']);
const TEMPLATE = /\.(html?|jinja2?|j2)$/i;
const SHA = /^[a-f0-9]{40}$/;

export function parseRepository(value) {
  let url;
  try { url = new URL(value.trim()); } catch { throw new Error('Paste a full repository URL, such as https://github.com/owner/repository.'); }
  const parts = url.pathname.replace(/\/$/, '').split('/').slice(1);
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password ||
      parts.length !== 2 || !/^[\w-]+$/.test(parts[0]) || !/^[\w.-]+$/.test(parts[1]) || ['.','..'].includes(parts[1])) {
    throw new Error('Use https://github.com/owner/repository. Put a branch or tag in the optional branch field.');
  }
  const repo = parts[1].replace(/\.git$/, '');
  if (!repo || ['.','..'].includes(repo)) throw new Error('Enter a valid GitHub repository name.');
  return {owner:parts[0], repo};
}

export function sourceFolder(value) {
  const folder = value.trim().replace(/\/$/, '');
  if (!folder || folder === '.') return '';
  if (!safePath(folder)) throw new Error('Use a relative source folder such as src, with no dot or parent segments.');
  return folder;
}

// Review links carry only the request; each visitor's browser fetches and analyzes the source again.
export function reviewLink({owner, repo, ref = '', folder = ''}, base) {
  const url = new URL(base);
  url.search = ''; url.hash = '';
  url.searchParams.set('repo', `${owner}/${repo}`);
  if (ref) url.searchParams.set('ref', ref);
  if (folder) url.searchParams.set('folder', folder);
  return url.href;
}

export function linkRequest(search) {
  const params = new URLSearchParams(search), value = params.get('repo')?.trim();
  if (!value) return null;
  const ref = (params.get('ref') || '').trim();
  if (ref.length > 255 || /[\x00-\x1f\x7f]/.test(ref)) throw new Error('The link has an invalid branch, tag, or commit.');
  return {...parseRepository(value.includes('://') ? value : `https://github.com/${value}`), ref, folder:sourceFolder(params.get('folder') || '')};
}

export function badgeMarkdown(link) {
  return `[![Explore in Threadline](https://img.shields.io/badge/Explore_in-Threadline-18634f)](${link})`;
}

function safePath(path) {
  return typeof path === 'string' && path.length > 0 && !/[\\\x00-\x1f\x7f]/.test(path) &&
    path.split('/').every(part => part && part !== '.' && part !== '..');
}

export function selectFiles(tree, folder = '') {
  if (tree.truncated) throw new Error('GitHub returned an incomplete file listing. Use the local CLI for this repository.');
  if (!Array.isArray(tree.tree)) throw new Error('GitHub returned an invalid file listing.');
  const files = [], seen = new Set();
  let bytes = 0, skippedLinks = 0;
  for (const entry of tree.tree) {
    if (!safePath(entry.path)) throw new Error('The repository contains an unsupported file path. Use the local CLI.');
    if (entry.path.split('/').some(part => EXCLUDED.has(part))) continue;
    if (folder && !entry.path.startsWith(folder + '/') && entry.path !== 'pyproject.toml') continue;
    if (entry.type === 'commit' || entry.mode === '120000') { skippedLinks++; continue; }
    if (entry.type !== 'blob') continue;
    if (!entry.path.endsWith('.py') && entry.path !== 'pyproject.toml' && !TEMPLATE.test(entry.path)) continue;
    if (!['100644','100755'].includes(entry.mode) || !SHA.test(entry.sha) || seen.has(entry.path)) {
      throw new Error('GitHub returned an unsupported source file entry.');
    }
    seen.add(entry.path);
    if (!Number.isSafeInteger(entry.size) || entry.size < 0 || entry.size > LIMITS.fileBytes) {
      throw new Error(`${entry.path} exceeds the 2 MiB file limit. Choose a narrower source folder or use the local CLI.`);
    }
    files.push(entry); bytes += entry.size;
  }
  if (!files.some(file => file.path.endsWith('.py'))) throw new Error('No Python files found in the selected repository or source folder.');
  if (files.length > LIMITS.files || bytes > LIMITS.bytes) {
    throw new Error('This selection exceeds 1,500 files or 16 MiB. Choose a narrower source folder or use the local CLI.');
  }
  return {files, bytes, skippedLinks};
}

async function checkedFetch(url, signal, fetcher) {
  let response;
  try { response = await fetcher(url, {signal, credentials:'omit', referrerPolicy:'no-referrer'}); }
  catch (error) {
    if (signal?.aborted || error.name === 'AbortError') throw error;
    throw new Error('Could not reach GitHub. Check your connection and try again.');
  }
  if (!response.ok) {
    if (response.status === 403 || response.status === 429) {
      const reset = Number(response.headers.get('x-ratelimit-reset'));
      const retry = reset ? ` Try again after ${new Date(reset * 1000).toLocaleTimeString()}.` : ' Wait a little and try again.';
      throw new Error('GitHub refused the request, possibly because of its rate limit.' + retry);
    }
    if (response.status === 404) throw new Error('Repository, branch, or file not found. Check the URL and branch; this version supports public repositories only.');
    if (response.status === 409) throw new Error('This repository is empty or has no available commit.');
    throw new Error(`GitHub could not provide the source (HTTP ${response.status}). Try again later.`);
  }
  return response;
}

export async function fetchRepository({owner, repo, ref = '', folder = ''}, {signal, onProgress = () => {}, fetcher = fetch} = {}) {
  const api = `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  const json = async path => (await checkedFetch(api + path, signal, fetcher)).json();
  onProgress('Finding the repository…');
  const metadata = await json('');
  if (metadata.private) throw new Error('This version supports public repositories only.');
  const commit = await json('/commits/' + encodeURIComponent(ref.trim() || metadata.default_branch));
  if (!SHA.test(commit.sha) || !SHA.test(commit.commit?.tree?.sha)) throw new Error('GitHub returned an invalid commit.');
  onProgress('Listing source files…');
  const tree = await json(`/git/trees/${commit.commit.tree.sha}?recursive=1`);
  const selected = selectFiles(tree, folder);
  let next = 0, completed = 0;
  const sources = new Array(selected.files.length);
  // Raw URLs avoid one API request per file, and all files use the same commit.
  const reader = async () => {
    while (next < selected.files.length) {
      const index = next++, entry = selected.files[index];
      const path = entry.path.split('/').map(encodeURIComponent).join('/');
      const url = `https://raw.githubusercontent.com/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${commit.sha}/${path}`;
      const response = await checkedFetch(url, signal, fetcher);
      const stream = response.body.getReader(), chunks = [];
      let size = 0;
      try {
        while (true) {
          const {value, done} = await stream.read();
          if (done) break;
          size += value.length;
          if (size > entry.size || size > LIMITS.fileBytes) throw new Error(`Source size changed for ${entry.path}. Please retry.`);
          chunks.push(value);
        }
      } catch (error) { await stream.cancel(); throw error; }
      finally { stream.releaseLock(); }
      if (size !== entry.size) throw new Error(`Source is incomplete for ${entry.path}. Please retry.`);
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      const header = new TextEncoder().encode(`blob ${size}\0`);
      const blob = new Uint8Array(header.length + size);
      blob.set(header); blob.set(bytes, header.length);
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-1', blob));
      const hash = [...digest].map(byte => byte.toString(16).padStart(2, '0')).join('');
      if (hash !== entry.sha) throw new Error(`Source verification failed for ${entry.path}. Please retry.`);
      sources[index] = {path:entry.path, bytes};
      onProgress(`Fetching source · ${++completed} of ${sources.length} files`, completed, sources.length);
    }
  };
  await Promise.all(Array.from({length:Math.min(6, sources.length)}, reader));
  return {owner, repo, sha:commit.sha, folder, sources, skippedLinks:selected.skippedLinks};
}
