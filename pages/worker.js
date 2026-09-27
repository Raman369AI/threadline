/* Python runs off the UI thread. Terminating this worker cancels analysis. */
'use strict';
self.onmessage = async ({data}) => {
  const progress = message => self.postMessage({type:'progress', message});
  try {
    progress('Loading Python for your browser…');
    importScripts('./pyodide/pyodide.js');
    const pyodide = await loadPyodide({indexURL:new URL('./pyodide/', self.location.href).href});
    const manifest = await fetch('./build.json').then(response => {
      if (!response.ok) throw new Error('The analyzer package is unavailable. Reload the page and try again.');
      return response.json();
    });
    const response = await fetch(manifest.bundle);
    if (!response.ok) throw new Error('The analyzer package could not be loaded. Reload the page and try again.');
    // This archive contains this site's trusted Threadline package, never target source.
    pyodide.unpackArchive(await response.arrayBuffer(), 'zip', {extractDir:'/opt/threadline'});
    pyodide.runPython("import sys; sys.path.insert(0, '/opt/threadline')");
    const root = '/sources/' + data.repo;
    pyodide.FS.mkdirTree(root);
    for (const file of data.sources) {
      if (!file.path || /[\\\x00-\x1f\x7f]/.test(file.path) || file.path.split('/').some(part => !part || part === '.' || part === '..')) {
        throw new Error('Unsupported repository path.');
      }
      const destination = root + '/' + file.path;
      pyodide.FS.mkdirTree(destination.slice(0, destination.lastIndexOf('/')));
      pyodide.FS.writeFile(destination, file.bytes);
    }
    // Pass values as data, never interpolate repository strings into Python.
    pyodide.globals.set('review_root', root);
    pyodide.globals.set('review_folder', data.folder);
    progress('Analyzing Python source…');
    pyodide.runPython(`
from threadline.service import SnapshotStore
from threadline.html_export import write_html
store = SnapshotStore(review_root, source_roots=[review_folder] if review_folder else None)
model = store.refresh()
if not model['files']:
    raise ValueError('No Python files could be parsed. Try the local CLI to inspect source diagnostics.')
`);
    progress('Building your HTML review…');
    pyodide.runPython("write_html(store, '/tmp/review.html')");
    const summary = JSON.parse(pyodide.runPython(`
import json
json.dumps({'files':len(model['files']), 'methods':sum(s['kind'] not in ('module','class') for s in model['scopes'].values()), 'errors':len(model['errors'])})
`));
    const html = pyodide.FS.readFile('/tmp/review.html');
    self.postMessage({type:'complete', html, summary}, [html.buffer]);
  } catch (error) {
    // Keep the Python stack in developer tools; show its actionable last line.
    console.error(error);
    const lines = String(error.message || error).trim().split('\n');
    self.postMessage({type:'error', message:lines.at(-1).replace(/^(?:ValueError|ThreadlineError|AnalysisLimitError):\s*/, '')});
  }
};
