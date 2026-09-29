import {runTests} from '@vscode/test-electron';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import os from 'node:os';
import path from 'node:path';
const extension = fileURLToPath(new URL('../', import.meta.url));
const temp = await mkdtemp(path.join(os.tmpdir(), 'threadline-vscode-'));
const workspace = path.join(temp, 'project');
await mkdir(workspace);
await writeFile(path.join(workspace, 'demo.py'), 'def helper(value):\n    return value + 1\n\ndef entry(value):\n    return helper(value)\n');
await writeFile(path.join(workspace, 'test_demo.py'), 'from demo import entry\ndef test_entry():\n    assert entry(1) == 2\n');
const git = args => execFileSync('git', ['-C', workspace, ...args], {stdio:'pipe'});
git(['init', '-q']); git(['add', '.']); git(['-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'baseline']);
const userData = path.join(temp, 'user');
await mkdir(path.join(userData, 'User'), {recursive:true});
await writeFile(path.join(userData, 'User/settings.json'), JSON.stringify({'security.workspace.trust.enabled':false, 'workbench.startupEditor':'none', 'update.mode':'none', 'extensions.autoUpdate':false, 'telemetry.telemetryLevel':'off', 'threadline.pythonPath':process.env.THREADLINE_TEST_PYTHON || 'python3'}));
try {
  await runTests({extensionDevelopmentPath:extension, extensionTestsPath:path.join(extension, 'dist/test/integration.js'),
    ...(process.env.VSCODE_EXECUTABLE ? {vscodeExecutablePath:process.env.VSCODE_EXECUTABLE} : {}),
    extensionTestsEnv:{THREADLINE_TEST_OUTPUT:path.join(temp, 'review.html')},
    launchArgs:[workspace, '--user-data-dir=' + userData, '--extensions-dir=' + path.join(temp, 'extensions'), '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', '--disable-gpu', '--no-sandbox']});
} finally { await rm(temp, {recursive:true, force:true}); }
