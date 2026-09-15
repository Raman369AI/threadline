"""Headless release smoke test for the packaged browser. Run directly."""
import base64
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import websocket
from threadline.server import make_server
chrome=next((shutil.which(name) for name in ('google-chrome','google-chrome-stable','chromium','chromium-browser') if shutil.which(name)),None)
if not chrome: raise SystemExit('Chrome/Chromium is required for browser smoke tests')
fixture=tempfile.TemporaryDirectory(prefix='threadline-browser-source-')
fixture_root=Path(fixture.name)
for source in (ROOT/'example').glob('*.py'): shutil.copyfile(source,fixture_root/source.name)
(fixture_root/'large.py').write_text('def many(value):\n'+''.join(f'    value += {i}\n' for i in range(45))+'    return value\n' + ''.join(f'\ndef searchable_{i}():\n    return {i}\n' for i in range(120)))
server=make_server(fixture_root,port=0);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
port=server.server_address[1]
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));debug=probe.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='threadline-chrome-') as profile:
    browser=subprocess.Popen([chrome,'--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',f'--remote-debugging-port={debug}',f'--remote-allow-origins=http://127.0.0.1:{debug}',f'--user-data-dir={profile}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(400):
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{debug}/json/new?http://127.0.0.1:{port}',method='PUT')
                target=json.load(urllib.request.urlopen(request));break
            except Exception: time.sleep(.05)
        else:
            detail=browser.stderr.read().strip() if browser.poll() is not None else 'browser remained alive but DevTools did not answer within 20 seconds'
            raise RuntimeError('Chrome DevTools did not start: '+detail[-2000:])
        ws=websocket.create_connection(target['webSocketDebuggerUrl'],origin=f'http://127.0.0.1:{debug}')
        sequence=0;errors=[]
        def command(method,params=None):
            nonlocal_sequence[0]+=1;identifier=nonlocal_sequence[0]
            ws.send(json.dumps({'id':identifier,'method':method,'params':params or {}}))
            while True:
                result=json.loads(ws.recv())
                if result.get('method')=='Runtime.exceptionThrown': errors.append(result)
                if result.get('id')==identifier:return result.get('result',{})
        nonlocal_sequence=[sequence]
        def js(expression):
            result=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
            return result['result'].get('value')
        command('Runtime.enable');command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':900,'deviceScaleFactor':1,'mobile':False})
        for _ in range(100):
            if js("typeof workflowState!=='undefined' && workflowState.initialized"):break
            time.sleep(.05)
        checks={
            'simple_input_output':js("document.querySelectorAll('#payloadSummary .payload-block').length===2 && !document.querySelector('#payloadSummary button,#payloadSummary select')"),
            'workflow_first':js("workflowState.mode==='workflow' && workflowState.profile.stages.length>0"),
            'source_visible':js("document.querySelectorAll('#sourceCode .code-line').length>0"),
            'details_progressive':js("!document.querySelector('.method-details').open"),
        }
        js("(async()=>{window.__selectedSmokeScope=Object.values(model.scopes).find(s=>s.name==='submit_order').id;document.querySelector('#methodsTab').click();await chooseScope(window.__selectedSmokeScope);await showSelectedWorkflow();})()")
        for _ in range(100):
            if js("workflowState.profile?.root===window.__selectedSmokeScope"):break
            time.sleep(.05)
        checks['selected_method_builds_workflow']=js("workflowState.profile.root===window.__selectedSmokeScope")
        checks['nested_cross_file_workflow']=js("workflowState.profile.stages.some(s=>s.depth>1) && workflowState.profile.links.every(l=>l.evidence.length)")
        js("(async()=>{const s=model.scopes[state.scope];await showSource(s.flow[0].span,s.flow[0].label);})()")
        checks['operation_opens_original_code']=js("document.querySelector('#sourceCode .focus,#sourceCode .scope-focus')!==null")
        deep=js("Object.values(model.scopes).find(s=>s.name==='place_order').id")
        snapshot=js("model.snapshotId")
        from urllib.parse import quote
        command('Page.navigate',{'url':f'http://127.0.0.1:{port}/?snapshot={snapshot}#{quote(deep,safe="")}'})
        for _ in range(100):
            if js("typeof model!=='undefined' && state.scope==="+json.dumps(deep)):break
            time.sleep(.05)
        checks['snapshot_deep_link']=js("model.snapshotId==="+json.dumps(snapshot)+" && state.scope==="+json.dumps(deep))
        for width in (800,390):
            command('Emulation.setDeviceMetricsOverride',{'width':width,'height':850,'deviceScaleFactor':1,'mobile':width<600})
            checks[f'no_horizontal_overflow_{width}']=js('document.documentElement.scrollWidth<=innerWidth')
        checks['bounded_browser_requests']=js("performance.getEntriesByType('resource').every(e=>!e.name.includes('/api/index'))")
        command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':900,'deviceScaleFactor':1,'mobile':False})
        command('Input.dispatchKeyEvent',{'type':'keyDown','key':'/','code':'Slash','text':'/'})
        command('Input.dispatchKeyEvent',{'type':'keyUp','key':'/','code':'Slash'})
        checks['keyboard_search_shortcut']=js("document.activeElement.id==='search' && !document.querySelector('#repositoryBrowser').hidden")
        js("(async()=>{document.querySelector('#search').value='searchable_';await navigation();})()")
        checks['search_is_paged']=js("document.querySelectorAll('#navigation .nav-item').length===50 && document.querySelector('#navigation').textContent.includes('More definitions')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'many',snapshot:model.snapshotId});await chooseScope(rows.symbols.items[0].id);})()")
        checks['method_is_paged']=js("document.querySelectorAll('#flow .operation').length===20 && document.querySelector('#flow').textContent.includes('Load more statements')")
        js("[...document.querySelectorAll('#flow button')].find(b=>b.textContent==='Load more statements →').click()")
        for _ in range(100):
            if js("document.querySelectorAll('#flow .operation').length===40"):break
            time.sleep(.02)
        checks['method_continuation']=js("document.querySelectorAll('#flow .operation').length===40")
        js("load(true)")
        checks['authorized_browser_refresh']=js("!document.querySelector('#flow .error') && !document.querySelector('#refreshButton').disabled")
        checks['buttons_have_names']=js("[...document.querySelectorAll('button')].every(b=>(b.getAttribute('aria-label')||b.textContent).trim().length)")
        checks['no_browser_errors']=not errors
        screenshot=command('Page.captureScreenshot',{'format':'png'})
        (Path(tempfile.gettempdir())/'threadline-browser.png').write_bytes(base64.b64decode(screenshot['data']))
        print(json.dumps(checks,indent=2))
        if not all(checks.values()): raise SystemExit(1)
        ws.close()
    finally:
        browser.terminate();browser.wait(timeout=5);server.shutdown();server.server_close();worker.join();fixture.cleanup()
