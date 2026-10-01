"""Exercise the real Pyodide worker, HTML preview, and download in Chrome.

Build first with scripts/build_pages.py. GitHub responses are deterministic
fixtures by default; --live additionally fetches a public repository directly.
The submitted Python is parsed, never imported or executed.
"""
from __future__ import annotations

import argparse
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from threadline.service import SnapshotStore
from threadline.html_export import write_html

SOURCES = {
    'app.py': (
        'from fastapi import FastAPI\napp = FastAPI()\n'
        'def double(value):\n    return value * 2\n'
        '@app.get("/items")\ndef items():\n    return double(21)\n'
        'raise RuntimeError("Target code must never run")\n'
        'PAYLOAD = "</script><script>window.__sourceExecuted=true</script>"\n'
    ),
    'test_app.py': 'from app import double\ndef test_double():\n    assert double(2) == 4\n',
    'pyproject.toml': '[project]\nname = "demo"\nversion = "0.0.1"\n',
}


def snapshot(html):
    return json.loads(html.split('<script id="threadline-snapshot" type="application/json">', 1)[1].split('</script>', 1)[0])


def github_fixture():
    tree = []
    for path, source in SOURCES.items():
        raw = source.encode()
        tree.append({'path':path, 'type':'blob', 'mode':'100644', 'size':len(raw),
                     'sha':hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()})
    return r'''
const realFetch = window.fetch.bind(window);
const sources = SOURCES, tree = TREE;
window.fetch = async function(url, options) {
  url = String(url);
  if (url.startsWith('https://api.github.com/')) {
    if (url.includes('/missing')) return new Response('{}', {status:404});
    if (url.includes('/git/trees/')) return Response.json({tree, truncated:false});
    if (url.includes('/commits/')) return Response.json({sha:'a'.repeat(40), commit:{tree:{sha:'b'.repeat(40)}}});
    return Response.json({default_branch:'main', private:false});
  }
  if (url.startsWith('https://raw.githubusercontent.com/')) {
    const path = decodeURIComponent(new URL(url).pathname.split('/').slice(4).join('/'));
    if (Object.hasOwn(sources, path)) return new Response(sources[path]);
    return new Response('', {status:404});
  }
  return realFetch(url, options);
};
'''.replace('SOURCES', json.dumps(SOURCES)).replace('TREE', json.dumps(tree))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not (ROOT / 'build/pages/build.json').is_file():
        parser.error('Run python scripts/build_pages.py first')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'build')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    driver = None
    checks = []
    try:
        options = webdriver.ChromeOptions()
        for flag in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage'):
            options.add_argument(flag)
        driver = webdriver.Chrome(options=options)
        driver.set_script_timeout(90)
        driver.set_window_size(1440, 1100)
        fixture_id = driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':github_fixture()})['identifier']
        url = f'http://127.0.0.1:{server.server_port}/pages/'
        driver.get(url)
        wait = WebDriverWait(driver, 180)

        def check(name, condition):
            if not condition:
                raise AssertionError(name)
            checks.append(name)
            print('PASS', name, flush=True)

        def js(expression):
            result = driver.execute_async_script('const done=arguments[arguments.length-1]; Promise.resolve().then(async()=>(' + expression + ')).then(value=>done({value}),error=>done({error:String(error)}));')
            if 'error' in result:
                raise AssertionError(result['error'])
            return result.get('value')

        def generate(repo='https://github.com/owner/demo'):
            field = driver.find_element(By.ID, 'repository')
            field.clear(); field.send_keys(repo)
            driver.find_element(By.ID, 'generate').click()

        def ready():
            wait.until(lambda d: d.find_element(By.ID, 'result').is_displayed() or d.find_element(By.ID, 'error').is_displayed())
            error = driver.find_element(By.ID, 'error')
            if error.is_displayed():
                raise AssertionError(error.text)
            return js("fetch(document.querySelector('#download').href).then(r=>r.text())")

        axe = ROOT / 'tests/browser-tools/node_modules/axe-core/axe.min.js'
        if not axe.is_file():
            raise AssertionError('Run npm ci --prefix tests/browser-tools --ignore-scripts first')
        driver.execute_script(axe.read_text())
        violations = js("axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','best-practice']}}).then(r=>r.violations)")
        check('landing accessibility', not violations)
        for width in (390, 768, 1440):
            driver.set_window_size(width, 1100)
            check(f'landing fits {width}px', js('document.documentElement.scrollWidth <= innerWidth'))

        generate('https://github.com/owner/missing')
        wait.until(lambda d: d.find_element(By.ID, 'error').is_displayed())
        check('missing repository reports error and enables retry', 'public repositories' in driver.find_element(By.ID, 'error').text and driver.find_element(By.ID, 'generate').is_enabled())
        generate()
        wait.until(lambda d: 'Loading Python' in d.find_element(By.ID, 'status').text or d.find_element(By.ID, 'result').is_displayed())
        driver.find_element(By.ID, 'cancel').click()
        check('cancel terminates the worker and restores the form', driver.find_element(By.ID, 'generate').is_enabled() and 'Cancelled' in driver.find_element(By.ID, 'status').text)
        generate()
        html = ready()
        check('HTML download is standalone', '<script src=' not in html and "connect-src 'none'" in html)
        check('download name includes immutable commit', driver.find_element(By.ID, 'download').get_attribute('download') == 'owner-demo-aaaaaaa-review.html')
        link = url + '?repo=owner%2Fdemo'
        check('address bar and share field hold the review link', driver.current_url == link and driver.find_element(By.ID, 'review-link').get_attribute('value') == link)
        check('badge Markdown points at the review link', driver.find_element(By.ID, 'badge-markdown').get_attribute('value').endswith(f'({link})'))
        web = snapshot(html)
        with tempfile.TemporaryDirectory(prefix='threadline-pages-') as directory:
            fixture = Path(directory) / 'demo'
            fixture.mkdir()
            for path, source in SOURCES.items():
                (fixture / path).write_text(source)
            store = SnapshotStore(fixture); store.refresh()
            expected = snapshot(write_html(store, Path(directory) / 'expected.html').read_text())
            browser_model = web['snapshots'][web['current']]
            native_model = expected['snapshots'][expected['current']]
            check('browser analysis matches native source and method evidence', browser_model['sources'] == native_model['sources'] and browser_model['methods'] == native_model['methods'])
            driver.switch_to.frame(driver.find_element(By.ID, 'preview'))
            wait.until(lambda d: d.execute_script("return typeof workflowState !== 'undefined' && workflowState.initialized"))
            check('sandboxed preview initializes without executing target source', js("!window.__sourceExecuted && !document.querySelector('#startPage').hidden"))
            check('preview contains the HTTP endpoint', '/items' in driver.find_element(By.ID, 'startGroups').text)
            driver.find_element(By.CSS_SELECTOR, '#startGroups .start-item').click()
            wait.until(lambda d: d.execute_script('return state.scope !== null'))
            check('preview opens a method', js("model.scopes[state.scope].name === 'items'"))
            driver.find_element(By.ID, 'methodsTab').click()
            wait.until(lambda d: d.execute_script("return catalogPage === 'methods' && document.querySelector('#startGroups .mod-item') !== null"))
            driver.find_element(By.CSS_SELECTOR, '#startGroups .mod-item summary').click()
            wait.until(lambda d: 'double' in d.find_element(By.ID, 'startGroups').text)
            check('preview module navigation survives restricted history', 'double' in driver.find_element(By.ID, 'startGroups').text)
            driver.switch_to.default_content()
            (ROOT / 'artifacts').mkdir(exist_ok=True)
            driver.save_screenshot(str(ROOT / 'artifacts/github-pages.png'))
            for width in (390, 1440):
                driver.set_window_size(width, 1100)
                check(f'result fits {width}px', js('document.documentElement.scrollWidth <= innerWidth'))
            exported = Path(directory) / 'review.html'
            exported.write_text(html)
            driver.get(exported.as_uri())
            wait.until(lambda d: d.execute_script("return typeof workflowState !== 'undefined' && workflowState.initialized"))
            check('download reopens independently', '/items' in driver.find_element(By.ID, 'startGroups').text)

        driver.get(url + '?repo=owner/demo&ref=v1')
        check('review link fills the form', driver.find_element(By.ID, 'ref').get_attribute('value') == 'v1' and driver.find_element(By.ID, 'options').get_attribute('open') is not None)
        ready()
        check('review link starts the review', driver.find_element(By.ID, 'result-title').text == 'owner/demo')
        driver.get(url + '?repo=owner/demo/tree/main')
        check('invalid review link reports an error without starting', driver.find_element(By.ID, 'error').is_displayed() and driver.find_element(By.ID, 'result').get_attribute('hidden') is not None)

        if args.live:
            driver.execute_cdp_cmd('Page.removeScriptToEvaluateOnNewDocument', {'identifier':fixture_id})
            driver.get(url)
            driver.find_element(By.CSS_SELECTOR, '#options summary').click()
            driver.find_element(By.ID, 'folder').send_keys('src/requests')
            generate('https://github.com/psf/requests')
            live = snapshot(ready())
            model = live['snapshots'][live['current']]
            check('live GitHub repository generates HTML with real Python source',
                  'src/requests/sessions.py' in model['sources'] and any(
                      scope['name'] == 'request' and scope['file'] == 'src/requests/sessions.py'
                      for scope in model['scopes'].values()))
            driver.save_screenshot(str(ROOT / 'artifacts/github-pages-live.png'))
        print(json.dumps({'passed':len(checks), 'checks':checks}, indent=2))
    finally:
        if driver:
            driver.quit()
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
