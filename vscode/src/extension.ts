import * as vscode from 'vscode';
import * as path from 'node:path';
import {execFile} from 'node:child_process';
import {readFile, realpath} from 'node:fs/promises';
import {createHash, randomBytes} from 'node:crypto';
import {AnalyzerClient} from './client';

interface SourceLocation {file: string; line: number; snapshot?: string}
interface SnapshotSource extends SourceLocation {source: string; hash: string; snapshot: string}
const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
const inside = (root: string, file: string) => { const relative = path.relative(root, file); return relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative); };
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const isPython = (uri: vscode.Uri) => uri.scheme === 'file' && uri.fsPath.endsWith('.py');
const cancelled = 'Review cancelled';
const queries = new Set(['session', 'scope', 'branch', 'compare', 'overview', 'tests', 'diagnostics', 'summary', 'modules', 'starts', 'symbols', 'workflow', 'method', 'method-source', 'dataflow', 'source'].map(name => '/api/' + name));

/** Raised when no configured or default interpreter can run the analyzer. */
class PythonSetupError extends Error {}

class SnapshotDocuments implements vscode.TextDocumentContentProvider, vscode.Disposable {
  private sources = new Map<string, string>();
  private bytes = 0;
  readonly registration = vscode.workspace.registerTextDocumentContentProvider('threadline-source', this);
  provideTextDocumentContent(uri: vscode.Uri): string {
    const source = this.sources.get(uri.toString());
    if (source === undefined) throw new Error('This snapshot document has expired. Open it again from the review.');
    return source;
  }
  uri(source: SnapshotSource): vscode.Uri {
    const uri = vscode.Uri.from({scheme:'threadline-source', path:`/${source.snapshot}/${source.file}`, query:source.hash});
    const key = uri.toString();
    if (!this.sources.has(key)) {
      this.sources.set(key, source.source); this.bytes += Buffer.byteLength(source.source);
      while (this.bytes > 24 * 1024 * 1024 && this.sources.size > 1) {
        const first = this.sources.keys().next().value!;
        this.bytes -= Buffer.byteLength(this.sources.get(first)!); this.sources.delete(first);
      }
    }
    return uri;
  }
  dispose() { this.registration.dispose(); this.sources.clear(); }
}

export class ReviewSession implements vscode.Disposable {
  panel?: vscode.WebviewPanel;
  client?: AnalyzerClient;
  ready?: {snapshot: string; scope: string | null};
  stale = false;
  private revision = 0;
  private refreshing?: Promise<any>;
  private autoRefresh?: NodeJS.Timeout;
  private subscriptions: vscode.Disposable[] = [];
  private disposed = false;
  private readyEvent = new vscode.EventEmitter<void>();
  private changeEvent = new vscode.EventEmitter<void>();
  readonly onReady = this.readyEvent.event;
  /** Fires when the panel's freshness, refresh state, or lifetime changes. */
  readonly onDidChange = this.changeEvent.event;
  constructor(readonly folder: vscode.WorkspaceFolder, private context: vscode.ExtensionContext,
              private documents: SnapshotDocuments, private output: vscode.OutputChannel, readonly base?: string) {
    // Threadline only reads Python source, so other files (Git metadata, notes, build output) never make it stale.
    const changed = (uri: vscode.Uri) => { if (isPython(uri) && inside(folder.uri.fsPath, uri.fsPath)) this.markStale(); };
    this.subscriptions.push(vscode.workspace.onDidChangeTextDocument(event => { if (event.contentChanges.length) changed(event.document.uri); }));
    this.subscriptions.push(vscode.workspace.onDidSaveTextDocument(document => changed(document.uri)));
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, '**/*.py'));
    this.subscriptions.push(watcher, watcher.onDidCreate(changed), watcher.onDidChange(changed), watcher.onDidDelete(changed));
  }
  get closed(): boolean { return this.disposed || !!this.client?.stopped; }
  get isRefreshing(): boolean { return !!this.refreshing; }
  private get refreshOnSave(): boolean { return vscode.workspace.getConfiguration('threadline', this.folder.uri).get<boolean>('refreshOnSave', true); }
  dirty(): boolean {
    return vscode.workspace.textDocuments.some(document => document.isDirty && isPython(document.uri) && inside(this.folder.uri.fsPath, document.uri.fsPath));
  }
  private markStale() { ++this.revision; this.stale = true; this.sendStatus(); this.scheduleRefresh(); }
  /** Refresh through the webview once saved source settles, so its view and the snapshot stay in step. */
  private scheduleRefresh() {
    clearTimeout(this.autoRefresh);
    if (!this.refreshOnSave || !this.ready || this.closed) return;
    this.autoRefresh = setTimeout(() => {
      if (this.closed || !this.stale || this.dirty()) return;
      if (this.refreshing) { this.scheduleRefresh(); return; }
      this.panel?.webview.postMessage({type:'refresh'});
    }, 800);
  }
  private sendStatus() {
    let message = `Saved source snapshot${this.base ? ' · changes against ' + this.base : ''} · Python code was not executed.`;
    if (this.stale && this.dirty()) message = 'Unsaved Python edits. Save them to update the review; this panel shows the previous snapshot.';
    else if (this.stale && this.refreshOnSave) message = 'Python source changed. Refreshing…';
    else if (this.stale) message = 'Python source changed. Select Refresh source to include it; this panel shows the previous snapshot.';
    this.panel?.webview.postMessage({type:'stale', message});
    this.changeEvent.fire();
  }
  async initialize(): Promise<void> {
    const config = vscode.workspace.getConfiguration('threadline', this.folder.uri);
    const configured = config.get<string>('pythonPath', '').trim();
    const candidates = configured ? [configured] : process.platform === 'win32' ? ['python', 'python3'] : ['python3', 'python'];
    const revision = this.revision;
    const errors: string[] = [];
    for (const python of candidates) {
      if (this.disposed) throw new Error(cancelled);
      const client = new AnalyzerClient(python, this.context.asAbsolutePath('build/python/runner.py'), this.context.extensionPath, text => this.output.appendLine(text));
      this.client = client;
      try {
        await client.request({op:'init', options:{root:this.folder.uri.fsPath, base:this.base,
          sourceRoots:config.get<string[]>('sourceRoots', []), exclude:config.get<string[]>('exclude', [])}});
        this.stale = revision !== this.revision || this.dirty();
        this.output.appendLine(`Analyzing ${this.folder.uri.fsPath} with ${python}.`);
        return;
      } catch (error) { client.dispose(); errors.push(`${python}: ${errorText(error)}`); }
    }
    if (this.disposed) throw new Error(cancelled);
    this.output.appendLine(errors.join('\n'));
    throw new PythonSetupError(`Could not start the analyzer with ${candidates.join(' or ')}. Threadline needs Python 3.12 or newer.`);
  }
  async locate(file: string, line: number): Promise<{id: string; snapshot: string; name: string}> {
    return this.client!.request({op:'locate', file, line});
  }
  /** Bring the analyzer up to date with saved source before a command reads from it. */
  async catchUp(): Promise<void> {
    if (this.stale) await this.refresh();
  }
  private startFragment(symbol?: string): string {
    return symbol ? '#' + encodeURIComponent(symbol) : '?page=methods' + (this.base ? '&changes=1' : '');
  }
  private label(name?: string): string {
    return 'Threadline · ' + (name || (this.base ? 'changes vs ' + this.base : this.folder.name));
  }
  async show(symbol?: string, name?: string): Promise<void> {
    if (this.disposed) throw new Error(cancelled);
    const media = vscode.Uri.joinPath(this.context.extensionUri, 'build', 'media');
    const panel = vscode.window.createWebviewPanel('threadline.review', this.label(name),
      vscode.ViewColumn.Beside, {enableScripts:true, retainContextWhenHidden:true, localResourceRoots:[media]});
    this.panel = panel;
    this.subscriptions.push(panel.onDidDispose(() => this.dispose()));
    this.subscriptions.push(panel.webview.onDidReceiveMessage(message => this.handleMessage(message)));
    let html = await readFile(vscode.Uri.joinPath(media, 'index.html').fsPath, 'utf8');
    const nonce = randomBytes(24).toString('hex');
    const resource = (name: string) => panel.webview.asWebviewUri(vscode.Uri.joinPath(media, name)).toString();
    html = html.replace(/\b(src|href)="([a-z_]+\.(?:js|css))"/g, (_, attr, name) => `${attr}="${resource(name)}"`);
    html = html.replace(/<script /g, `<script nonce="${nonce}" `);
    const policy = `default-src 'none'; script-src 'nonce-${nonce}'; style-src ${panel.webview.cspSource} 'unsafe-inline'; img-src ${panel.webview.cspSource} data:; connect-src 'none'; base-uri 'none'; form-action 'none';`;
    const start = this.startFragment(symbol).replace(/&/g, '&amp;');
    html = html.replace('<meta charset="utf-8">', `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><meta name="threadline-start" content="${start}"><script nonce="${nonce}" src="${resource('bridge.js')}"></script>`);
    html = html.replace('</head>', `<link rel="stylesheet" href="${resource('vscode.css')}"></head>`);
    html = html.replace('<span class="top-spacer"></span>', '<span class="top-spacer"></span><button id="hostExport" class="quiet-button" type="button">Export HTML</button>');
    html = html.replace('</header>', '</header><div id="hostStatus" class="host-status" role="status">Reading saved source…</div>');
    panel.webview.html = html;
    this.changeEvent.fire();
  }
  /** Reuse the open panel and its index instead of analyzing the workspace again. */
  navigate(symbol?: string, name?: string) {
    if (!this.panel) throw new Error('Open a Threadline review first.');
    this.ready = undefined;
    this.panel.title = this.label(name);
    this.panel.webview.postMessage({type:'navigate', start:this.startFragment(symbol)});
    this.panel.reveal(this.panel.viewColumn, true);
  }
  private async handleMessage(message: any) {
    if (!message || typeof message !== 'object' || JSON.stringify(message).length > 1024 * 1024) return;
    if (message.type === 'ready') {
      if (typeof message.snapshot !== 'string') return;
      this.ready = {snapshot:message.snapshot, scope:typeof message.scope === 'string' ? message.scope : null};
      this.sendStatus(); this.readyEvent.fire();
      if (this.stale) this.scheduleRefresh();
      return;
    }
    if (!Number.isSafeInteger(message.id)) return;
    try {
      let result: unknown;
      if (message.type === 'query') {
        if (message.path === '/api/reindex' && message.method === 'POST') result = await this.refresh();
        else if (queries.has(message.path) && message.method === 'GET') result = await this.client!.request({op:'query', path:message.path, params:message.params});
        else throw new Error('Unsupported review request');
      } else if (message.type === 'source') result = (await this.openSource(message)).toString();
      else if (message.type === 'export') result = await this.exportHTML();
      else throw new Error('Unknown review message');
      this.panel?.webview.postMessage({type:'response', id:message.id, result});
    } catch (error) { this.panel?.webview.postMessage({type:'response', id:message.id, error:errorText(error)}); }
  }
  async refresh(): Promise<any> {
    if (this.refreshing) return this.refreshing;
    const revision = this.revision;
    this.refreshing = this.client!.request({op:'query', path:'/api/reindex'}).then(summary => {
      this.stale = revision !== this.revision || this.dirty();
      if (this.stale) this.scheduleRefresh();  // Source changed again while indexing.
      return summary;
    }).catch(error => { this.stale = true; this.output.appendLine('Refresh failed: ' + errorText(error)); throw error; })
      .finally(() => { this.refreshing = undefined; this.sendStatus(); });
    this.changeEvent.fire();
    return this.refreshing;
  }
  async openSource(location: SourceLocation): Promise<vscode.Uri> {
    if (typeof location.file !== 'string' || !Number.isSafeInteger(location.line) || typeof location.snapshot !== 'string') throw new Error('Invalid source location');
    const source = await this.client!.request<SnapshotSource>({op:'source', file:location.file, line:location.line, snapshot:location.snapshot});
    let uri = this.documents.uri(source);
    // Only jump to a real file if it still matches the evidence. Otherwise show a read-only snapshot.
    try {
      const root = await realpath(this.folder.uri.fsPath), file = await realpath(path.resolve(root, source.file));
      const fileUri = vscode.Uri.file(file);
      const dirty = vscode.workspace.textDocuments.some(doc => doc.uri.fsPath === file && doc.isDirty);
      if (inside(root, file) && !dirty && hash(await readFile(file)) === source.hash) uri = fileUri;
    } catch { /* Deleted or inaccessible source remains available in the snapshot. */ }
    const document = await vscode.workspace.openTextDocument(uri);
    const line = Math.min(source.line - 1, document.lineCount - 1);
    await vscode.window.showTextDocument(document, {viewColumn:vscode.ViewColumn.One, selection:new vscode.Range(line, 0, line, 0), preview:true});
    if (uri.scheme === 'threadline-source') vscode.window.setStatusBarMessage('Threadline: showing the reviewed snapshot because the file has changed since.', 5000);
    return uri;
  }
  async exportHTML(target?: vscode.Uri): Promise<string | undefined> {
    target ??= await vscode.window.showSaveDialog({title:'Export current Threadline snapshot', defaultUri:vscode.Uri.joinPath(this.folder.uri, 'threadline-review.html'), filters:{HTML:['html']}});
    if (!target) return;
    if (target.scheme !== 'file') throw new Error('Choose a filesystem destination for the HTML export');
    const result = await vscode.window.withProgress({location:vscode.ProgressLocation.Notification, title:'Threadline: exporting review'},
      () => this.client!.request<{path:string}>({op:'export', path:target!.fsPath}, 240000));
    vscode.window.showInformationMessage('Threadline review exported to ' + path.basename(result.path), 'Open in Browser', 'Reveal File').then(choice => {
      if (choice === 'Open in Browser') vscode.env.openExternal(vscode.Uri.file(result.path));
      else if (choice === 'Reveal File') vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(result.path));
    });
    return result.path;
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true; clearTimeout(this.autoRefresh); this.client?.dispose(); this.panel?.dispose();
    this.changeEvent.fire();
    this.subscriptions.forEach(item => item.dispose()); this.readyEvent.dispose(); this.changeEvent.dispose();
  }
}

const run = (file: string, args: string[], cwd?: string) => new Promise<string>((resolve, reject) =>
  execFile(file, args, {cwd, timeout:10000, windowsHide:true}, (error, stdout) => error ? reject(error) : resolve(stdout)));

/** Offer HEAD and recent branches, while still accepting any typed revision. */
async function pickBase(folder: vscode.WorkspaceFolder): Promise<string | undefined> {
  const refs = await run('git', ['for-each-ref', '--sort=-committerdate', '--count=40', '--format=%(refname)', 'refs/heads', 'refs/remotes', 'refs/tags'], folder.uri.fsPath)
    .then(out => out.split('\n').filter(ref => ref && !ref.endsWith('/HEAD')), () => [] as string[]);
  const kind = (ref: string) => ref.startsWith('refs/heads/') ? 'branch' : ref.startsWith('refs/tags/') ? 'tag' : 'remote branch';
  const fixed: vscode.QuickPickItem[] = [{label:'HEAD', description:'Staged and unstaged changes since the last commit'},
    ...refs.map(ref => ({label:ref.replace(/^refs\/(heads|tags|remotes)\//, ''), description:kind(ref)}))];
  const quick = vscode.window.createQuickPick();
  quick.title = 'Threadline: compare saved files against';
  quick.placeholder = 'Choose a branch or tag, or type any Git revision';
  quick.items = fixed;
  quick.onDidChangeValue(value => {
    const typed = value.trim();
    quick.items = typed && !fixed.some(item => item.label === typed) ? [{label:typed, description:'Git revision'}, ...fixed] : fixed;
  });
  return new Promise(resolve => {
    quick.onDidAccept(() => { resolve(quick.selectedItems[0]?.label || quick.value.trim() || undefined); quick.hide(); });
    quick.onDidHide(() => { resolve(undefined); quick.dispose(); });
    quick.show();
  });
}

export function activate(context: vscode.ExtensionContext) {
  const output = vscode.window.createOutputChannel('Threadline');
  const documents = new SnapshotDocuments();
  const status = vscode.window.createStatusBarItem('threadline.status', vscode.StatusBarAlignment.Left, 50);
  status.name = 'Threadline';
  let current: ReviewSession | undefined, opening = false, watching: vscode.Disposable | undefined;
  const updateStatus = () => {
    const open = !!current && !current.closed;
    vscode.commands.executeCommand('setContext', 'threadline.reviewOpen', open);
    if (opening) {
      status.text = '$(sync~spin) Threadline: indexing…'; status.tooltip = 'Reading saved Python source'; status.command = 'threadline.showLog';
    } else if (!open) { status.hide(); return; }
    else if (current!.isRefreshing) {
      status.text = '$(sync~spin) Threadline'; status.tooltip = 'Refreshing the review'; status.command = 'threadline.showReview';
    } else if (current!.stale) {
      const dirty = current!.dirty();
      status.text = '$(warning) Threadline: ' + (dirty ? 'unsaved' : 'stale');
      status.tooltip = dirty ? 'Save Python edits to update the review' : 'Python source changed. Click to refresh the review.';
      status.command = dirty ? 'threadline.showReview' : 'threadline.refresh';
    } else {
      status.text = '$(type-hierarchy) Threadline'; status.tooltip = 'Show the Threadline review' + (current!.base ? ` (changes against ${current!.base})` : '');
      status.command = 'threadline.showReview';
    }
    status.show();
  };
  const adopt = (session: ReviewSession) => {
    if (current !== session) current?.dispose();
    current = session; watching?.dispose(); watching = session.onDidChange(updateStatus); updateStatus();
  };
  const start = async (kind: 'function' | 'workspace' | 'changes', options: {folder?: vscode.WorkspaceFolder; base?: string; fresh?: boolean} = {}) => {
    if (!vscode.workspace.isTrusted) throw new Error('Trust the workspace before starting Threadline.');
    if (opening) throw new Error('A review is already opening. Wait for it to finish or cancel it.');
    // The editor button works on any file: it selects the function at the cursor when there is one,
    // and otherwise opens the workspace review of the file's folder.
    const editor = vscode.window.activeTextEditor;
    const document = kind === 'function' && editor?.document.uri.scheme === 'file' ? editor.document : undefined;
    if (document?.isDirty && isPython(document.uri)) await document.save();
    const folders = vscode.workspace.workspaceFolders || [];
    let folder = options.folder || (editor && vscode.workspace.getWorkspaceFolder(editor.document.uri));
    if (!folder) folder = folders.length === 1 ? folders[0] : await vscode.window.showQuickPick(folders.map(item => ({label:item.name, description:item.uri.fsPath, folder:item})), {title:'Threadline: choose a workspace folder to review'}).then(item => item?.folder);
    if (!folder) { if (!folders.length) throw new Error('Open a local project folder first.'); return; }
    if (folder.uri.scheme !== 'file') throw new Error('Threadline needs a filesystem workspace.');
    let base = options.base;
    if (kind === 'changes' && base === undefined) {
      base = await pickBase(folder);
      if (base === undefined) return;
    }
    const cursor = document && isPython(document.uri) && !document.isDirty && inside(folder.uri.fsPath, document.uri.fsPath)
      ? {file:path.relative(folder.uri.fsPath, document.uri.fsPath).split(path.sep).join('/'), line:editor!.selection.active.line + 1} : undefined;
    const locate = async (session: ReviewSession) => {
      if (!cursor) return undefined;
      try { return await session.locate(cursor.file, cursor.line); }
      catch (error) {
        // Not a function, excluded, or not analyzable: show the workspace review rather than an error.
        output.appendLine(`No function selected for ${cursor.file}:${cursor.line}: ${errorText(error)}`);
        vscode.window.setStatusBarMessage('Threadline: no function at the cursor, showing the workspace review', 5000);
        return undefined;
      }
    };
    const reusable = current && !current.closed && !options.fresh && current.folder.uri.toString() === folder.uri.toString() && current.base === base;
    opening = true; updateStatus();
    if (reusable) {
      const session = current!;
      try {
        await vscode.window.withProgress({location:vscode.ProgressLocation.Window, title:'Threadline'}, async () => {
          await session.catchUp();
          const selected = await locate(session);
          session.navigate(selected?.id, selected?.name);
        });
        return session;
      } finally { opening = false; updateStatus(); }
    }
    const session = new ReviewSession(folder, context, documents, output, base);
    try {
      await vscode.window.withProgress({location:vscode.ProgressLocation.Notification, title:'Threadline: reading saved Python source', cancellable:true}, async (_, token) => {
        const cancel = token.onCancellationRequested(() => session.dispose());
        try {
          await session.initialize();
          if (token.isCancellationRequested) throw new Error(cancelled);
          const selected = await locate(session);
          await session.show(selected?.id, selected?.name);
          opening = false; adopt(session);
        } finally { cancel.dispose(); }
      });
      return session;
    } catch (error) { session.dispose(); throw error; }
    finally { opening = false; updateStatus(); }
  };
  const choosePython = async () => {
    const picked = await vscode.window.showOpenDialog({title:'Choose a Python 3.12+ executable for Threadline', canSelectMany:false, canSelectFolders:false, openLabel:'Use for Threadline'});
    if (!picked?.length) return;
    const python = picked[0].fsPath;
    const version = await run(python, ['-I', '-S', '-c', 'import sys; print("%d.%d" % sys.version_info[:2])']).then(out => out.trim(), () => '');
    const [major, minor] = version.split('.').map(Number);
    if (!version) throw new Error(`${python} could not be run as Python.`);
    if (major < 3 || (major === 3 && minor < 12)) throw new Error(`${python} is Python ${version}. Threadline needs Python 3.12 or newer.`);
    await vscode.workspace.getConfiguration('threadline').update('pythonPath', python, vscode.ConfigurationTarget.Global);
    vscode.window.showInformationMessage(`Threadline will use Python ${version} at ${python}.`);
  };
  const reopen = () => current && !current.closed && start(current.base === undefined ? 'workspace' : 'changes', {folder:current.folder, base:current.base, fresh:true});
  const command = (name: string, action: () => unknown) => context.subscriptions.push(vscode.commands.registerCommand(name, async () => {
    try { return await action(); }
    catch (error) {
      const text = errorText(error);
      if (text === cancelled) return;
      output.appendLine(text);
      const actions = error instanceof PythonSetupError ? ['Choose Python…', 'Open Settings', 'Show Log'] : !vscode.workspace.isTrusted ? ['Manage Workspace Trust'] : ['Show Log'];
      vscode.window.showErrorMessage('Threadline: ' + text, ...actions).then(choice => {
        if (choice === 'Choose Python…') vscode.commands.executeCommand('threadline.choosePython');
        else if (choice === 'Open Settings') vscode.commands.executeCommand('workbench.action.openSettings', 'threadline.pythonPath');
        else if (choice === 'Show Log') output.show(true);
        else if (choice === 'Manage Workspace Trust') vscode.commands.executeCommand('workbench.trust.manage');
      });
    }
  }));
  const requireReview = () => { if (!current || current.closed) throw new Error('Open a Threadline review first.'); return current; };
  command('threadline.reviewFunction', () => start('function'));
  command('threadline.reviewWorkspace', () => start('workspace'));
  command('threadline.reviewChanges', () => start('changes'));
  command('threadline.refresh', () => { const session = requireReview(); session.panel!.reveal(session.panel!.viewColumn, true); session.panel!.webview.postMessage({type:'refresh'}); });
  command('threadline.exportHTML', () => requireReview().exportHTML());
  command('threadline.showReview', () => { const session = requireReview(); session.panel!.reveal(session.panel!.viewColumn); });
  command('threadline.choosePython', choosePython);
  command('threadline.showLog', () => output.show(true));
  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
    if (!current || current.closed || opening) return;
    if (!['pythonPath', 'sourceRoots', 'exclude'].some(key => event.affectsConfiguration('threadline.' + key, current!.folder.uri))) return;
    vscode.window.showInformationMessage('Threadline settings changed. Reopen the review to apply them.', 'Reopen Review').then(choice => {
      if (choice) vscode.commands.executeCommand('threadline.reopen');
    });
  }));
  command('threadline.reopen', () => reopen());
  context.subscriptions.push(output, documents, status, {dispose:() => { watching?.dispose(); current?.dispose(); }});
  return {get current() { return current; }};
}
