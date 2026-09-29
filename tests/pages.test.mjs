import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash, webcrypto} from 'node:crypto';
import {parseRepository, sourceFolder, selectFiles, fetchRepository, LIMITS, reviewLink, linkRequest, badgeMarkdown} from '../pages/github.mjs';

globalThis.crypto ??= webcrypto;
const sha = 'a'.repeat(40), treeSha = 'b'.repeat(40);
function entry(path, source = 'def hello():\n    return 1\n', mode = '100644') {
  const bytes = Buffer.from(source);
  return {path, type:'blob', mode, size:bytes.length, sha:createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex')};
}
test('accepts public repo URLs and .git; rejects other hosts and ambiguous branch URLs', () => {
  assert.deepEqual(parseRepository(' https://github.com/owner/project.git/ '), {owner:'owner', repo:'project'});
  for (const url of ['http://github.com/o/r','https://github.com.evil.test/o/r','https://user@github.com/o/r','https://github.com/o/r/tree/main','https://github.com/o/r%2fx','https://github.com/o/.git']) {
    assert.throws(() => parseRepository(url));
  }
});
test('review links round-trip requests and reject unsafe parameters', () => {
  const base = 'https://raman369ai.github.io/threadline/?old=1#top';
  const link = reviewLink({owner:'owner', repo:'project', ref:'release/1.0', folder:'src/pkg'}, base);
  assert.equal(link, 'https://raman369ai.github.io/threadline/?repo=owner%2Fproject&ref=release%2F1.0&folder=src%2Fpkg');
  assert.deepEqual(linkRequest(new URL(link).search), {owner:'owner', repo:'project', ref:'release/1.0', folder:'src/pkg'});
  assert.deepEqual(linkRequest('?repo=https://github.com/o/r'), {owner:'o', repo:'r', ref:'', folder:''});
  assert.equal(reviewLink({owner:'o', repo:'r'}, base), 'https://raman369ai.github.io/threadline/?repo=o%2Fr');
  assert.equal(linkRequest(''), null);
  assert.equal(linkRequest('?repo='), null);
  for (const search of ['?repo=o','?repo=o/r/tree/main','?repo=https://evil.test/o/r','?repo=o/r&folder=../x','?repo=o/r&ref=a%0Ab',`?repo=o/r&ref=${'a'.repeat(256)}`]) {
    assert.throws(() => linkRequest(search));
  }
  assert.equal(badgeMarkdown(link), `[![Explore in Threadline](https://img.shields.io/badge/Explore_in-Threadline-18634f)](${link})`);
});
test('source folders cannot escape the virtual repository', () => {
  assert.equal(sourceFolder(' src/pkg/ '), 'src/pkg');
  assert.equal(sourceFolder('.'), '');
  for (const path of ['../src','src/../lib','/src','src//lib','src\\lib','src/\0bad']) assert.throws(() => sourceFolder(path));
});
test('selects Python, root configuration, and template source with explicit scope', () => {
  const tree = {tree:[entry('src/app.py'), entry('src/templates/index.html'), entry('pyproject.toml'), entry('other.py'), entry('.venv/a.py'), entry('src/pic.png'), entry('src/link.py','app.py','120000'), {path:'src/submodule',type:'commit',mode:'160000'}]};
  const selected = selectFiles(tree, 'src');
  assert.deepEqual(selected.files.map(row => row.path), ['src/app.py','src/templates/index.html','pyproject.toml']);
  assert.equal(selected.skippedLinks, 2);
});
test('refuses incomplete trees, unsafe paths, missing Python, duplicate files, and oversize selections', () => {
  assert.throws(() => selectFiles({truncated:true,tree:[entry('a.py')]}), /incomplete/);
  assert.throws(() => selectFiles({tree:[entry('../escape.py')]}), /unsupported file path/);
  assert.throws(() => selectFiles({tree:[entry('README.md')]}), /No Python/);
  assert.throws(() => selectFiles({tree:[entry('a.py'),entry('a.py')]}), /unsupported source/);
  assert.throws(() => selectFiles({tree:[{...entry('a.py'),size:LIMITS.fileBytes + 1}]}), /2 MiB/);
  assert.throws(() => selectFiles({tree:Array.from({length:1501}, (_, index) => entry(`${index}.py`))}), /1,500/);
  assert.throws(() => selectFiles({tree:Array.from({length:9}, (_, index) => ({...entry(`${index}.py`),size:LIMITS.fileBytes}))}), /16 MiB/);
});
function mockGitHub({body = 'def hello():\n    return 1\n', wrongSource = false} = {}) {
  const calls = [], sourceEntry = entry('src/space name.py', body);
  return {calls, fetcher:async (url, options) => {
    calls.push({url, options});
    if (url.endsWith('/repos/owner/repo')) return Response.json({default_branch:'feature/review',private:false});
    if (url.includes('/commits/')) return Response.json({sha,commit:{tree:{sha:treeSha}}});
    if (url.includes('/git/trees/')) return Response.json({tree:[sourceEntry],truncated:false});
    if (url.startsWith('https://raw.githubusercontent.com/')) return new Response(wrongSource ? body.replace('1','2') : body);
    throw new Error('Unexpected request: ' + url);
  }};
}
test('fetches immutable source with few API requests, verifies bytes, and preserves file content', async () => {
  const mock = mockGitHub(), progress = [];
  const result = await fetchRepository({owner:'owner',repo:'repo'}, {...mock,onProgress:message => progress.push(message)});
  assert.equal(result.sha, sha);
  assert.equal(new TextDecoder().decode(result.sources[0].bytes), 'def hello():\n    return 1\n');
  assert.equal(mock.calls.length, 4);
  assert.ok(mock.calls[1].url.endsWith('/commits/feature%2Freview'));
  assert.ok(mock.calls[2].url.includes(treeSha));
  assert.equal(mock.calls[3].url, `https://raw.githubusercontent.com/owner/repo/${sha}/src/space%20name.py`);
  assert.ok(mock.calls.every(call => call.options.credentials === 'omit'));
  assert.match(progress.at(-1), /1 of 1/);
});
test('rejects same-sized source that differs from the pinned tree', async () => {
  await assert.rejects(fetchRepository({owner:'owner',repo:'repo'}, mockGitHub({wrongSource:true})), /verification failed/);
});
test('bounds streamed downloads even when headers cannot be trusted', async () => {
  const mock = mockGitHub(), original = mock.fetcher;
  mock.fetcher = (url, options) => url.startsWith('https://raw.') ? new Response('x'.repeat(10000)) : original(url, options);
  await assert.rejects(fetchRepository({owner:'owner',repo:'repo'}, mock), /Source size changed/);
});
test('reports private or missing repos, API limits, and network failures', async () => {
  for (const [code, message] of [[404,/public repositories/],[403,/rate limit/],[429,/rate limit/],[409,/empty/],[500,/HTTP 500/]]) {
    await assert.rejects(fetchRepository({owner:'owner',repo:'repo'}, {fetcher:async () => new Response('', {status:code})}), message);
  }
  await assert.rejects(fetchRepository({owner:'owner',repo:'repo'}, {fetcher:async () => { throw new TypeError('fetch failed'); }}), /connection/);
});
test('propagates cancellation without turning it into a network error', async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(fetchRepository({owner:'owner',repo:'repo'}, {signal:controller.signal,fetcher:async (_, {signal}) => { throw signal.reason; }}), {name:'AbortError'});
});
