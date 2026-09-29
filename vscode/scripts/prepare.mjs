import {mkdir, readdir, copyFile, rm} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const project = path.dirname(root.replace(/\/$/, ''));
const build = path.join(root, 'build');
await rm(build, {recursive:true, force:true});
for (const dir of ['python/threadline/static', 'media']) await mkdir(path.join(build, dir), {recursive:true});
for (const name of await readdir(path.join(project, 'threadline'))) {
  if (name.endsWith('.py')) await copyFile(path.join(project, 'threadline', name), path.join(build, 'python/threadline', name));
}
for (const name of await readdir(path.join(project, 'threadline/static'))) {
  if (!/\.(py|js|css|html)$/.test(name)) continue;
  await copyFile(path.join(project, 'threadline/static', name), path.join(build, 'python/threadline/static', name));
  if (!name.endsWith('.py')) await copyFile(path.join(project, 'threadline/static', name), path.join(build, 'media', name));
}
for (const name of ['bridge.js', 'vscode.css']) await copyFile(path.join(root, 'media', name), path.join(build, 'media', name));
await copyFile(path.join(root, 'python/runner.py'), path.join(build, 'python/runner.py'));
await copyFile(path.join(project, 'LICENSE'), path.join(root, 'LICENSE'));
