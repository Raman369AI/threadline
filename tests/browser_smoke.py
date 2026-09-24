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
(fixture_root/'progressive.py').write_text('def leaf(value):\n    return value\ndef progressive(value):\n'+''.join('    leaf(value)\n' for _ in range(65))+'    if value:\n'+''.join(f'        value += {i}\n' for i in range(55))+'    return value\n')
(fixture_root/'cli_demo.py').write_text('def main():\n    return 0\n')
(fixture_root/'routes_demo.py').write_text('from fastapi import APIRouter\nrouter = APIRouter(prefix="/api")\n@router.post("/tasks")\ndef create_task():\n    return {}\n@router.get("/tasks")\ndef list_tasks():\n    return []\n')
(fixture_root/'oo_review.py').write_text(
    'class Repo:\n'
    '    def __init__(self):\n        pass\n'
    '    def get(self):\n        return 1\n'
    'class Service:\n'
    '    def __init__(self, repo: Repo):\n        self.repo = repo\n'
    '    def entry(self):\n        return self.repo.get()\n'
    'def conditional(flag):\n    return Repo().get() if flag else 0\n'
    'def unreachable():\n    return 0\n    Repo().get()\n'
    'def built():\n    return Repo()\n'
)
(fixture_root/'test_oo_review.py').write_text('from oo_review import Repo, Service\ndef test_entry_reads_repo():\n    assert Service(Repo()).entry() == 1\n')
(fixture_root/'pyproject.toml').write_text('[project.scripts]\ndemo="cli_demo:main"\n')
change_review='--changes' in sys.argv
if change_review:
    (fixture_root/'deleted.py').write_text('def removed(value):\n    return value\n')
    (fixture_root/'impact.py').write_text('from deleted import removed\ndef still_calls(value):\n    return removed(value)\n')
    (fixture_root/'changed.py').write_text(''.join(f'def changed_{i}():\n    return {i}\n' for i in range(35)))
    (fixture_root/'constants.py').write_text('FEE = 1\ndef total(value):\n    return value * FEE\n')
    for args in (['init','-q'], ['config','user.email','test@example.invalid'], ['config','user.name','Test'], ['add','.'], ['commit','-qm','baseline']):
        subprocess.run(['git',*args],cwd=fixture_root,check=True)
    (fixture_root/'deleted.py').unlink()
    (fixture_root/'changed.py').write_text(''.join(f'def changed_{i}():\n    return {i+100}\n' for i in range(35)))
    (fixture_root/'constants.py').write_text('FEE = 2\ndef total(value):\n    return value * FEE\n')
server=make_server(fixture_root,port=0,base='HEAD' if change_review else None);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
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
            'no_arbitrary_initial_method':js("state.scope===null && workflowState.profile===null && !document.querySelector('#startPage').hidden"),
            'endpoints_default_page':js("catalogPage==='endpoints' && document.querySelector('#startGroups [data-category=http] .start-item')!==null"),
            'methods_separate_from_endpoints':js("document.querySelector('#startGroups [data-category=methods]')===null"),
            'only_present_verb_tabs':js("[...document.querySelectorAll('.endpoint-tab')].map(b=>b.textContent).join(',')==='All,GET,POST'"),
            'search_always_visible':js("document.querySelector('#search').getBoundingClientRect().height>0"),
            'no_scope_filter':js("document.querySelector('#kindFilter')===null"),
        }
        screenshot=command('Page.captureScreenshot',{'format':'png'})
        (Path(tempfile.gettempdir())/'threadline-workflow-chooser.png').write_bytes(base64.b64decode(screenshot['data']))
        for verb, expected in (('GET','list_tasks'),('POST','create_task')):
            js("document.querySelector('[data-method="+verb+"]').click()")
            for _ in range(100):
                if js("document.querySelector('#endpointResults .start-item')?.textContent.includes("+json.dumps(expected)+")"):break
                time.sleep(.02)
            checks[verb+'_filters_endpoints']=js("document.querySelectorAll('#endpointResults .start-item').length===1 && document.querySelector('#endpointResults .start-item').textContent.includes("+json.dumps(expected)+")")
        js("showStartPage('methods')")
        checks['modules_first_without_methods']=js("document.querySelectorAll('.module-item').length>0 && document.querySelectorAll('#moduleResults [data-scope]').length===0 && state.scope===null")
        js("document.querySelector('.module-item[data-file=\"api.py\"]').click()")
        for _ in range(100):
            if js("document.querySelector('#moduleResults [data-scope]')!==null"):break
            time.sleep(.02)
        checks['module_reveals_only_its_methods']=js("[...document.querySelectorAll('#moduleResults .start-item')].every(b=>b.textContent.includes('api.py')) && state.scope===null")
        js("[...document.querySelectorAll('#moduleResults .start-item')].find(b=>b.textContent.includes('submit_order')).click()")
        for _ in range(100):
            if js("workflowState.profile?.root===state.scope && document.querySelector('#methodName').textContent==='submit_order'"):break
            time.sleep(.02)
        checks['module_method_opens_same_workflow']=js("workflowState.profile.stages.some(s=>s.depth>1) && document.querySelectorAll('.workflow-module-link').length>0")

        for category, page, expected in (('http','endpoints','list_tasks'),('commands','commands','main')):
            js("showStartPage("+json.dumps(page)+")")
            js("document.querySelector('#startGroups [data-category="+category+"] .start-item').click()")
            for _ in range(100):
                if js("workflowState.profile?.root===state.scope && document.querySelector('#methodName').textContent==="+json.dumps(expected)):break
                time.sleep(.02)
            checks[category+'_opens_workflow_in_one_click']=js("workflowState.profile?.root===state.scope && document.querySelector('#methodName').textContent==="+json.dumps(expected))
        js("showStartPage('endpoints')")
        checks['changes_tab_availability']=js("document.querySelector('#changesTab').hidden==="+json.dumps(not change_review))
        if change_review:
            js("document.querySelector('#changesTab').click()")
            for _ in range(100):
                if js("document.querySelector('[data-category=unassessedChanges]').textContent.includes('constants.py')"):break
                time.sleep(.02)
            checks['changed_files_and_unassessed_constant_visible']=js("document.querySelector('[data-category=files]').textContent.includes('constants.py') && document.querySelector('[data-category=unassessedChanges]').textContent.includes('constants.py')")
            js("[...document.querySelectorAll('[data-category=unassessedChanges] .change-record')].find(r=>r.textContent.includes('Working source')&&r.textContent.includes('constants.py')).querySelector('button').click()")
            for _ in range(100):
                if js("document.querySelector('#sourceCode').textContent.includes('FEE = 2')"):break
                time.sleep(.02)
            checks['unassessed_change_opens_exact_source']=js("document.querySelector('#sourceCode').textContent.includes('FEE = 2')")
            for _ in range(100):
                if js("document.querySelectorAll('[data-category=changedMethods] .change-record').length===25"):break
                time.sleep(.02)
            checks['changes_visible_and_paged']=js("!document.querySelector('#changesBrowser').hidden && document.querySelectorAll('[data-category=changedMethods] .change-record').length===25 && document.querySelector('[data-category=changedMethods]').textContent.includes('More records')")
            js("[...document.querySelectorAll('[data-category=changedMethods] button')].find(b=>b.textContent==='More records →').click()")
            for _ in range(100):
                if js("document.querySelectorAll('[data-category=changedMethods] .change-record').length===10"):break
                time.sleep(.02)
            checks['changes_continuation']=js("document.querySelectorAll('[data-category=changedMethods] .change-record').length===10")
            js("document.querySelector('[data-category=changedMethods] .change-record button').click()")
            for _ in range(100):
                if js("document.querySelector('#methodName').textContent==='changed_25' && document.querySelector('#sourceCode').textContent.includes('125')"):break
                time.sleep(.02)
            checks['change_opens_current_source']=js("document.querySelector('#methodName').textContent==='changed_25' && document.querySelector('#sourceCode').textContent.includes('125')")
            js("[...document.querySelectorAll('[data-category=changedMethods] .change-record button')].find(b=>b.textContent==='Compare before / after').click()")
            for _ in range(100):
                if js("document.querySelectorAll('#comparisonPanel .comparison-side .code-line').length>0"):break
                time.sleep(.02)
            checks['integrated_comparison']=js("!document.querySelector('#comparisonPanel').hidden && document.querySelectorAll('#comparisonPanel .comparison-side').length===2 && document.querySelector('#comparisonPanel').textContent.includes('return 25') && document.querySelector('#comparisonPanel').textContent.includes('return 125')")
            screenshot=command('Page.captureScreenshot',{'format':'png'})
            (Path(tempfile.gettempdir())/'threadline-comparison.png').write_bytes(base64.b64decode(screenshot['data']))
            js("document.querySelector('#comparisonPanel button').click();[...document.querySelectorAll('[data-category=changedMethods] .change-record button')].find(b=>b.textContent==='Trace workflow').click()")
            for _ in range(100):
                if js("workflowState.mode==='workflow' && workflowState.profile.root===state.scope"):break
                time.sleep(.02)
            checks['change_traces_workflow']=js("workflowState.mode==='workflow' && workflowState.profile.root===state.scope")
            js("document.querySelector('#changesTab').click();document.querySelector('[data-category=baselineCallers]').open=true")
            for _ in range(100):
                if js("document.querySelector('[data-category=baselineCallers] a')!==null"):break
                time.sleep(.02)
            checks['historical_caller_visible']=js("document.querySelector('[data-category=baselineCallers]').textContent.includes('still_calls') && document.querySelector('[data-category=baselineCallers]').textContent.includes('Previously called: removed')")
            baseline_url=js("document.querySelector('[data-category=baselineCallers] a').href")
            command('Page.navigate',{'url':baseline_url})
            for _ in range(100):
                if js("typeof workflowState!=='undefined' && workflowState.initialized && document.querySelector('#methodName').textContent==='still_calls'"):break
                time.sleep(.02)
            checks['baseline_source_and_return']=js("!document.querySelector('#baselineNotice').hidden && document.querySelector('#sourceCode').textContent.includes('removed(value)') && model.snapshotId===new URL(location.href).searchParams.get('snapshot')")
            command('Page.navigate',{'url':js("document.querySelector('#baselineNotice a').href")})
            for _ in range(100):
                if js("typeof workflowState!=='undefined' && workflowState.initialized && workflowState.mode==='starts'"):break
                time.sleep(.02)
            checks['return_to_review_chooser']=js("workflowState.mode==='starts' && !document.querySelector('#changesTab').hidden")
        js("(async()=>{document.querySelector('#search').value='submit order';await navigation();})()")
        checks['method_search_is_simple']=js("document.querySelectorAll('#navigation .nav-item').length===1")
        js("window.__selectedSmokeScope=document.querySelector('#navigation .nav-item').dataset.scope;document.querySelector('#navigation .nav-item').click()")
        for _ in range(100):
            if js("workflowState.profile?.root===window.__selectedSmokeScope"):break
            time.sleep(.05)
        checks['one_click_method_builds_workflow']=js("workflowState.profile.root===window.__selectedSmokeScope")
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
        checks['keyboard_search_shortcut']=js("document.activeElement.id==='search'")
        js("(async()=>{document.querySelector('#search').value='searchable_';await navigation();})()")
        checks['search_is_paged']=js("document.querySelectorAll('#navigation .nav-item').length===20 && document.querySelector('#navigation').textContent.includes('More matches')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'many',snapshot:model.snapshotId});await chooseScope(rows.symbols.items[0].id);})()")
        checks['method_is_paged']=js("document.querySelectorAll('#flow .operation').length===20 && document.querySelector('#flow').textContent.includes('Load more statements')")
        js("[...document.querySelectorAll('#flow button')].find(b=>b.textContent==='Load more statements →').click()")
        for _ in range(100):
            if js("document.querySelectorAll('#flow .operation').length===40"):break
            time.sleep(.02)
        checks['method_continuation']=js("document.querySelectorAll('#flow .operation').length===40")
        js("(async()=>{const result=await api('/api/symbols',{q:'progressive',snapshot:model.snapshotId});const scope=result.symbols.items.find(s=>s.name==='progressive');const start=performance.now();await chooseScope(scope.id);window.__methodAndSourceMs=performance.now()-start;window.__workflowStart=performance.now();await showSelectedWorkflow();window.__firstWorkflowMs=performance.now()-window.__workflowStart;})()")
        checks['workflow_first_page_only']=js("workflowState.profile.stages.length===20 && workflowState.profile.nextCursor===20 && workflowState.profile.totalStages===66")
        js("loadMoreWorkflow()")
        checks['workflow_continuation']=js("workflowState.profile.stages.length===40 && workflowState.profile.nextCursor===40")
        js("(async()=>{while(model.scopes[state.scope].nextCursor!==null){[...document.querySelectorAll('#flow button')].find(b=>b.textContent==='Load more statements →').click();await new Promise(resolve=>setTimeout(resolve,30));}})()")
        checks['branch_initially_unloaded']=js("document.querySelector('#flow details.branch') && !document.querySelector('#flow details.branch').open && document.querySelectorAll('#flow details.branch .operation').length===0")
        js("window.__branchStart=performance.now();document.querySelector('#flow details.branch').open=true")
        for _ in range(100):
            if js("document.querySelectorAll('#flow details.branch .operation').length===20"):break
            time.sleep(.02)
        checks['branch_first_page']=js("document.querySelectorAll('#flow details.branch .operation').length===20")
        js("window.__branchFirstMs=performance.now()-window.__branchStart;[...document.querySelectorAll('#flow details.branch button')].find(b=>b.textContent==='Load more branch statements').click()")
        for _ in range(100):
            if js("document.querySelectorAll('#flow details.branch .operation').length===40"):break
            time.sleep(.02)
        checks['branch_continuation']=js("document.querySelectorAll('#flow details.branch .operation').length===40")
        (Path(tempfile.gettempdir())/('threadline-changes-performance.json' if change_review else 'threadline-browser-performance.json')).write_text(json.dumps(js("({methodAndSourceMs:window.__methodAndSourceMs,workflowFirstPageMs:window.__firstWorkflowMs,branchFirstPageMs:window.__branchFirstMs})"),indent=2)+'\n')
        js("load(true)")
        checks['authorized_browser_refresh']=js("!document.querySelector('#flow .error') && !document.querySelector('#refreshButton').disabled")
        # Inject transient request failures, then recover through the visible UI.
        js("window.__originalFetch=window.fetch;window.__failOnce=(path)=>{window.fetch=async(...args)=>{if(String(args[0]).includes(path)){window.fetch=window.__originalFetch;throw new Error('Temporary request failure');}return window.__originalFetch(...args);};}")
        js("(async()=>{document.querySelector('#search').value='searchable';window.__failOnce('/api/starts');await navigation();})()")
        checks['search_error_visible']=js("!document.querySelector('#reviewError').hidden && document.querySelector('#reviewError [role=alert]').textContent.includes('Temporary request failure')")
        js("document.querySelector('#reviewError button').click()")
        for _ in range(100):
            if js("document.querySelector('#reviewError').hidden"):break
            time.sleep(.02)
        checks['search_retry_recovers']=js("document.querySelector('#reviewError').hidden && document.querySelectorAll('#navigation .nav-item').length>0")
        js("(async()=>{const result=await api('/api/symbols',{q:'searchable_119',snapshot:model.snapshotId});window.__retryScope=result.symbols.items[0].id;window.__failOnce('/api/scope');await chooseScope(window.__retryScope);})()")
        checks['selection_error_visible']=js("!document.querySelector('#reviewError').hidden")
        js("document.querySelector('#reviewError button').click()")
        for _ in range(100):
            if js("state.scope===window.__retryScope && document.querySelector('#sourceCode').textContent.includes('119')"):break
            time.sleep(.02)
        checks['selection_retry_recovers']=js("document.querySelector('#reviewError').hidden && state.scope===window.__retryScope && document.querySelector('#sourceCode').textContent.includes('119')")
        js("(async()=>{delete model.generatedWorkflows[state.scope];window.__failOnce('/api/workflow');await showSelectedWorkflow();})()")
        checks['workflow_error_visible']=js("!document.querySelector('#reviewError').hidden")
        js("document.querySelector('#reviewError button').click()")
        for _ in range(100):
            if js("workflowState.profile.root===window.__retryScope"):break
            time.sleep(.02)
        checks['workflow_retry_recovers']=js("document.querySelector('#reviewError').hidden && workflowState.profile.root===window.__retryScope")
        js("(async()=>{window.__beforeRefresh=model;window.__sourceBeforeRefresh=document.querySelector('#sourceCode').textContent;window.__failOnce('/api/reindex');await load(true);})()")
        checks['failed_refresh_preserves_review']=js("model===window.__beforeRefresh && document.querySelector('#sourceCode').textContent===window.__sourceBeforeRefresh && !document.querySelector('#reviewError').hidden")
        js("document.querySelector('#reviewError button').click()")
        for _ in range(100):
            if js("!document.querySelector('#refreshButton').disabled && document.querySelector('#reviewError').hidden"):break
            time.sleep(.02)
        checks['refresh_retry_recovers']=js("!document.querySelector('#refreshButton').disabled && document.querySelector('#reviewError').hidden")
        js("(async()=>{document.querySelector('#search').value='searchable';let rejectOld;window.fetch=(...args)=>{window.fetch=window.__originalFetch;return new Promise((resolve,reject)=>{rejectOld=reject;});};const old=navigation();await navigation();rejectOld(new Error('Obsolete failure'));await old;})()")
        checks['stale_errors_ignored']=js("document.querySelector('#reviewError').hidden")
        if change_review:
            js("document.querySelector('#changesTab').click()")
            for width in (800,390):
                command('Emulation.setDeviceMetricsOverride',{'width':width,'height':850,'deviceScaleFactor':1,'mobile':width<600})
                checks[f'changes_no_horizontal_overflow_{width}']=js('document.documentElement.scrollWidth<=innerWidth')
            command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':900,'deviceScaleFactor':1,'mobile':False})
        js("(async()=>{delete model.generatedWorkflows[state.scope];let release;window.fetch=(...args)=>{if(String(args[0]).includes('/api/workflow')){window.fetch=window.__originalFetch;return new Promise(resolve=>{release=()=>resolve(window.__originalFetch(...args));});}return window.__originalFetch(...args);};const pending=showSelectedWorkflow();await showStartPage();release();await pending;})()")
        checks['late_workflow_keeps_chooser_open']=js("workflowState.mode==='starts' && !document.querySelector('#startPage').hidden")
        checks['buttons_have_names']=js("[...document.querySelectorAll('button')].every(b=>(b.getAttribute('aria-label')||b.textContent).trim().length)")
        checks['no_browser_errors']=not errors
        screenshot=command('Page.captureScreenshot',{'format':'png'})
        (Path(tempfile.gettempdir())/('threadline-changes-browser.png' if change_review else 'threadline-browser.png')).write_bytes(base64.b64decode(screenshot['data']))
        (fixture_root/'routes_demo.py').unlink()
        js("(async()=>{history.replaceState(null,'',location.pathname);await load(true);})()")
        checks['commands_default_without_endpoints']=js("catalogPage==='commands' && workflowState.mode==='starts'")
        (fixture_root/'pyproject.toml').unlink()
        js("(async()=>{history.replaceState(null,'',location.pathname);await load(true);})()")
        checks['methods_default_without_entrypoints']=js("catalogPage==='methods' && workflowState.mode==='starts'")
        if change_review:
            js("document.querySelector('#changesTab').click()")
            for _ in range(100):
                if js("document.querySelector('[data-category=unassessedChanges]').textContent.includes('pyproject.toml')"):break
                time.sleep(.02)
            checks['configuration_deletion_visible_as_unassessed']=js("document.querySelector('[data-category=files]').textContent.includes('pyproject.toml') && document.querySelector('[data-category=unassessedChanges]').textContent.includes('pyproject.toml')")
            js("[...document.querySelectorAll('[data-category=unassessedChanges] .change-record')].find(r=>r.textContent.includes('pyproject.toml')&&r.textContent.includes('Baseline')).querySelector('button').click()")
            for _ in range(100):
                if js("document.querySelector('#sourceCode').textContent.includes('[project.scripts]')"):break
                time.sleep(.02)
            checks['configuration_baseline_source_opens']=js("document.querySelector('#sourceCode').textContent.includes('[project.scripts]')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'Service.entry',snapshot:model.snapshotId});window.__ooEntry=rows.symbols.items.find(s=>s.name==='entry').id;await chooseScope(window.__ooEntry);await showSelectedWorkflow();window.__ooStage=workflowState.profile.stages.find(s=>s.status==='possible'&&s.targetLabels&&Object.values(s.targetLabels).some(n=>n.endsWith('Repo.get')));await selectWorkflowStage(window.__ooStage.id);})()")
        checks['possible_workflow_target_requires_explicit_open']=js("state.scope===window.__ooEntry && [...document.querySelectorAll('.workflow-candidates button')].some(b=>b.textContent.includes('Repo.get'))")
        checks['receiver_candidate_provenance_visible']=js("[...document.querySelectorAll('#workflowContext button')].some(b=>b.textContent.includes('Why is this receiver a candidate?')) && window.__ooStage.candidateEvidence?.some(p=>p.evidenceId && p.label && p.span)")
        js("[...document.querySelectorAll('.workflow-candidates button')].find(b=>b.textContent.includes('Repo.get')).click()")
        for _ in range(100):
            if js("state.scope!==window.__ooEntry && document.querySelector('.caller-strip')!==null"):break
            time.sleep(.02)
        checks['possible_target_keeps_caller_return']=js("state.scope!==window.__ooEntry && document.querySelector('.caller-strip')?.textContent.includes('Back to caller')")
        js("document.querySelector('.caller-strip button').click()")
        for _ in range(100):
            if js("state.scope===window.__ooEntry"):break
            time.sleep(.02)
        checks['possible_target_returns_to_callsite']=js("state.scope===window.__ooEntry")
        js("(async()=>{const rows=await api('/api/symbols',{q:'Repo.get',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.qualified==='Repo.get').id);})()")
        for _ in range(100):
            if js("document.querySelector('#testsCount').textContent==='1'"):break
            time.sleep(.02)
        checks['tab_counts_and_summary']=js("document.querySelector('#testsCount').textContent==='1' && document.querySelector('#methodSummary').textContent.startsWith('Takes no input.') && document.querySelector('#tab-steps').getAttribute('aria-selected')==='true' && document.querySelector('#testsPanel').hidden")
        js("document.querySelector('#tab-tests').click()")
        for _ in range(100):
            if js("document.querySelector('#testsPanel .test-row')!==null"):break
            time.sleep(.02)
        checks['related_test_listed_with_reason']=js("document.querySelector('#testsPanel .test-row.indirect')?.textContent.includes('test_entry_reads_repo') && document.querySelector('#testsPanel').textContent.includes('through Service.entry')")
        js("document.querySelector('#testsPanel .test-pick').click()")
        for _ in range(100):
            if js("document.querySelector('#pairCode').textContent.includes('Service(Repo()).entry()')"):break
            time.sleep(.02)
        checks['test_source_beside_method']=js("!document.querySelector('#pairPane').hidden && document.querySelector('#pairCode .code-line.focus')?.textContent.includes('entry()') && document.querySelector('#sourceCode').textContent.includes('def get')")
        js("document.querySelector('#testsPanel .test-open').click()")
        for _ in range(100):
            if js("document.querySelector('#methodName').textContent==='test_entry_reads_repo' && document.querySelector('#testsCount').textContent!==''"):break
            time.sleep(.02)
        checks['new_method_opens_on_steps']=js("document.querySelector('#tab-steps').getAttribute('aria-selected')==='true' && document.querySelector('#tab-tests').textContent.startsWith('Exercises')")
        js("document.querySelector('#tab-tests').click()")
        for _ in range(100):
            if js("document.querySelector('#methodName').textContent==='test_entry_reads_repo' && document.querySelector('#testsPanel').textContent.includes('Service.entry')"):break
            time.sleep(.02)
        checks['selected_test_lists_exercised_code']=js("document.querySelector('#testsPanel').textContent.includes('This test exercises') && document.querySelector('#testsPanel').textContent.includes('Service.entry') && document.querySelector('#pairPane').hidden")
        # Opening a test selects it again for its workflow entry; the list must not reload.
        js("(async()=>{await selectWorkflowStage('entry');})()")
        checks['reselecting_method_keeps_tests']=js("performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/tests?symbol='+encodeURIComponent(state.scope))).length===1 && !document.querySelector('#testsPanel').hidden && document.querySelector('#testsPanel').textContent.includes('This test exercises')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'Repo.get',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.qualified==='Repo.get').id);document.querySelector('#tab-callers').click();})()")
        for _ in range(100):
            if js("document.querySelector('#callersPanel .test-row')!==null"):break
            time.sleep(.02)
        checks['callers_tab_lists_callers']=js("[...document.querySelectorAll('#callersPanel .test-name')].some(n=>n.textContent==='Service.entry') && document.querySelector('#callersPanel').textContent.includes('Probably calls')")
        js("document.body.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',bubbles:true}))")
        checks['keyboard_tab_shortcut']=js("document.querySelector('#tab-steps').getAttribute('aria-selected')==='true' && !document.querySelector('#stepsPanel').hidden")
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'j',bubbles:true}))")
        checks['keyboard_next_step']=js("state.selectedElement!==null && document.activeElement.classList.contains('op-head')")
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true}))")
        checks['help_opens_with_legend']=js("!document.querySelector('#helpPanel').hidden && document.querySelector('#helpPanel').textContent.includes('Probably calls') && document.querySelector('#helpButton').getAttribute('aria-expanded')==='true'")
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        checks['help_closes_on_escape']=js("document.querySelector('#helpPanel').hidden")
        js("(async()=>{const rows=await api('/api/symbols',{q:'unreachable',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='unreachable').id);await showSelectedWorkflow();})()")
        checks['unreachable_workflow_stage_marked']=js("[...document.querySelectorAll('.workflow-stage.unreachable')].some(b=>b.textContent.includes('Unreachable'))")
        js("(async()=>{const rows=await api('/api/symbols',{q:'conditional',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='conditional').id);await showSelectedWorkflow();})()")
        checks['conditional_workflow_stage_marked']=js("[...document.querySelectorAll('.workflow-stage')].some(b=>b.textContent.includes('Runs only if'))")
        js("(async()=>{const rows=await api('/api/symbols',{q:'built',snapshot:model.snapshotId});window.__built=rows.symbols.items.find(s=>s.name==='built').id;await chooseScope(window.__built);await showSelectedWorkflow();const stage=workflowState.profile.stages.find(s=>s.construction);await selectWorkflowStage(stage.id);})()")
        checks['construction_does_not_open_class_body_as_call']=js("state.scope===window.__built && document.querySelector('#workflowContext').textContent.includes('Constructing an object') && document.querySelector('#workflowContext').textContent.includes('Go to Repo.__init__')")
        (fixture_root/'broken.py').write_text('def incomplete(:\n')
        js("load(true)")
        checks['parse_failure_prominent_and_retrievable']=js("!document.querySelector('#analysisStatus').hidden && document.querySelector('#analysisStatus').textContent.includes('1 analysis issue') && document.querySelector('#coveragePanel').textContent.includes('Analysis issues · 1')")
        js("document.querySelector('#analysisStatus').click()")
        checks['parse_failure_badge_opens_coverage']=js("!document.querySelector('#coveragePanel').hidden")
        (fixture_root/'broken.py').unlink()
        (fixture_root/'pyproject.toml').write_bytes(b'\xff')
        js("load(true)")
        checks['configuration_error_prominent']=js("!document.querySelector('#analysisStatus').hidden && document.querySelector('#analysisStatus').textContent.includes('1 analysis issue') && document.querySelector('#coveragePanel').textContent.includes('Analysis issues · 1')")
        print(json.dumps(checks,indent=2))
        if not all(checks.values()): raise SystemExit(1)
        ws.close()
    finally:
        browser.terminate();browser.wait(timeout=5);server.shutdown();server.server_close();worker.join();fixture.cleanup()
