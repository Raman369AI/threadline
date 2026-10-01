import * as vscode from 'vscode';
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {ReviewSession} from '../extension';

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(check: () => boolean, label: string) {
  const end = Date.now() + 25000;
  while (!check()) { if (Date.now() > end) throw new Error('Timed out: ' + label); await delay(100); }
}

export async function run() {
  const extension = vscode.extensions.getExtension('Raman369AI.threadline-review')!;
  assert.ok(extension, 'extension is installed in the development host');
  const api = await extension.activate();
  const folder = vscode.workspace.workspaceFolders![0];
  const uri = vscode.Uri.joinPath(folder.uri, 'demo.py');
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, {selection:new vscode.Range(4, 8, 4, 8)});
  // Before any review is open, a Python file offers one from the status bar, and the manifest is as described.
  assert.equal(api.status.command, 'threadline.reviewFunction');
  assert.ok(api.status.text.includes('Threadline'));
  const manifest = extension.packageJSON;
  assert.equal(manifest.contributes.walkthroughs[0].id, 'threadline.gettingStarted');
  assert.deepEqual([...manifest.contributes.menus['editor/title'], ...manifest.contributes.menus['editor/context']].map((item: any) => item.when), ['resourceLangId == python', 'resourceLangId == python']);
  assert.equal(manifest.contributes.commands.find((item: any) => item.command === 'threadline.reviewFunction').title, 'Review Function at Cursor');
  const session = await vscode.commands.executeCommand<ReviewSession>('threadline.reviewFunction');
  assert.ok(session);
  await until(() => !!session.ready, 'webview fully loads the selected function');
  assert.equal(session.ready!.scope, (await session.locate('demo.py', 5)).id);
  assert.equal(api.current, session);
  const snapshot = session.ready!.snapshot;
  assert.equal((await session.openSource({snapshot, file:'demo.py', line:5})).scheme, 'file');
  assert.equal(vscode.window.activeTextEditor!.selection.active.line, 4);
  // Unsaved edits must never masquerade as the source shown in the review.
  const edit = new vscode.WorkspaceEdit(); edit.insert(uri, new vscode.Position(0, 0), '# unsaved edit\n');
  assert.ok(await vscode.workspace.applyEdit(edit));
  await until(() => session.stale, 'edit marks snapshot stale');
  assert.equal((await session.openSource({snapshot, file:'demo.py', line:5})).scheme, 'threadline-source');
  assert.equal(vscode.window.activeTextEditor!.document.getText().includes('# unsaved'), false);
  await document.save();
  await delay(600); // Let the filesystem watcher observe the save before refreshing.
  await vscode.commands.executeCommand('threadline.refresh');
  await until(() => !!session.ready && session.ready.snapshot !== snapshot, 'refresh publishes a new snapshot in the webview');
  assert.equal(session.stale, false);
  const target = vscode.Uri.file(process.env.THREADLINE_TEST_OUTPUT!);
  await session.exportHTML(target);
  const html = await readFile(target.fsPath, 'utf8');
  assert.ok(html.includes('threadlineOffline'));
  assert.ok(html.includes('# unsaved edit'));
  assert.ok(!html.includes('acquireVsCodeApi'));
  assert.equal((await session.openSource({snapshot, file:'demo.py', line:5})).scheme, 'threadline-source');
  await assert.rejects(session.openSource({snapshot, file:'../secret', line:1}));
  const oldClient = session.client!;
  // Saved edits refresh the open review without a command.
  const before = session.ready!.snapshot;
  const saved = await vscode.workspace.openTextDocument(uri);
  const append = new vscode.WorkspaceEdit(); append.insert(uri, new vscode.Position(saved.lineCount, 0), '\ndef added():\n    return entry(2)\n');
  assert.ok(await vscode.workspace.applyEdit(append)); await saved.save();
  await until(() => !!session.ready && session.ready.snapshot !== before && !session.stale, 'saving refreshes the review');
  // Another review of the same folder reuses the open panel and its analyzer.
  const workspace = await vscode.commands.executeCommand<ReviewSession>('threadline.reviewWorkspace');
  assert.equal(workspace, session); await until(() => !!workspace.ready, 'workspace review opens');
  assert.equal(oldClient.stopped, false);
  assert.equal(workspace.ready!.scope, null);
  const editor = await vscode.window.showTextDocument(saved, {viewColumn:vscode.ViewColumn.One, selection:new vscode.Range(saved.lineCount - 2, 4, saved.lineCount - 2, 4)});
  assert.ok(editor.document.getText().includes('def added'));
  const again = await vscode.commands.executeCommand<ReviewSession>('threadline.reviewFunction');
  assert.equal(again, session); await until(() => !!session.ready, 'reused panel selects the function');
  assert.equal(session.ready!.scope, (await session.locate('demo.py', saved.lineCount - 1)).id);
  // The editor button works from any file and never fails for lack of a function.
  const notes = vscode.Uri.joinPath(folder.uri, 'notes.txt'); await writeFile(notes.fsPath, 'not python\n');
  await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(notes));
  assert.equal(await vscode.commands.executeCommand<ReviewSession>('threadline.reviewFunction'), session);
  await until(() => !!session.ready, 'non-Python file opens the workspace review');
  assert.equal(session.ready!.scope, null);
  // Exercise the actual Git command, including accepting its default HEAD revision.
  const opening = vscode.commands.executeCommand<ReviewSession>('threadline.reviewChanges');
  await delay(700);
  await vscode.commands.executeCommand('workbench.action.acceptSelectedQuickOpenItem');
  const changes = await opening;
  assert.ok(changes); await until(() => !!changes.ready, 'Git changes webview opens');
  assert.equal(oldClient.stopped, true);
  const summary = await changes.client!.request({op:'query', path:'/api/summary'});
  assert.ok(summary.changes.baseSnapshotId);
  const original = await changes.client!.request({op:'source', snapshot:summary.changes.baseSnapshotId, file:'demo.py', line:1});
  assert.equal(original.source.startsWith('def helper'), true);
  // A deleted source file is still navigable as historical evidence.
  await writeFile(uri.fsPath, 'def replacement():\n    return 42\n');
  assert.equal((await changes.openSource({snapshot:summary.changes.baseSnapshotId, file:'demo.py', line:1})).scheme, 'threadline-source');
  changes.panel!.dispose();
  assert.equal(changes.client!.stopped, true);
  console.log('Threadline VS Code integration: cursor, real webview, source jumps, dirty edits, refresh, HTML export, workspace, Git baseline, isolation, and teardown passed.');
}
