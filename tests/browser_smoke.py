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
    'def invoke_entry():\n    service = Service(Repo())\n    if service:\n        return service.entry()\n    return None\n'
    'def conditional(flag):\n    return Repo().get() if flag else 0\n'
    'def unreachable():\n    return 0\n    Repo().get()\n'
    'def built():\n    return Repo()\n'
)
(fixture_root/'test_oo_review.py').write_text('from oo_review import Repo, Service\ndef test_entry_reads_repo():\n    assert Service(Repo()).entry() == 1\n')
(fixture_root/'dataflow_dashboard.py').write_text((ROOT/'tests'/'fixtures'/'dataflow_dashboard.py').read_text())
(fixture_root/'many_models.py').write_text(
    ''.join(f'class Model{i}:\n    field_{i}: int\n' for i in range(85)) +
    'def use_models():\n    return (' + ', '.join(f'Model{i}' for i in range(85)) + ')\n')
dashboard_template=fixture_root/'templates'/'dashboard.html'
dashboard_template.parent.mkdir()
dashboard_template.write_text('<h1>{{ stats.total_projects }}</h1>\n{% for project in recent_projects %}\n<p>{{ project.task_count }}</p>\n{% endfor %}\n<script>apiFetch("/agents/usage")</script>\n')
(fixture_root/'pyproject.toml').write_text('[project.scripts]\ndemo="cli_demo:main"\n')
(fixture_root/'inert.py').write_text("raise RuntimeError('must not execute')\nPAYLOAD = '</script><script>window.__sourceExecuted=true</script>'\n")
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
html_review='--html' in sys.argv
if html_review:
    from threadline.agent_cli import main
    html_path=fixture_root/'review.html'
    args=['review',str(fixture_root),'--output',str(html_path),'--no-open']
    if change_review: args.extend(['--base','HEAD'])
    assert main(args)==0
    review_url=html_path.as_uri()
    server=worker=None
else:
    server=make_server(fixture_root,port=0,base='HEAD' if change_review else None)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    review_url=f'http://127.0.0.1:{server.server_address[1]}/'
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));debug=probe.getsockname()[1]
with tempfile.TemporaryDirectory(prefix='threadline-chrome-') as profile:
    browser=subprocess.Popen([chrome,'--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',f'--remote-debugging-port={debug}',f'--remote-allow-origins=http://127.0.0.1:{debug}',f'--user-data-dir={profile}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(400):
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{debug}/json/new?{review_url}',method='PUT')
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
        checks['module_method_opens_same_workflow']=js("workflowState.profile.stages.some(s=>s.depth>1) && [...document.querySelectorAll('.workflow-stage-place')].some(p=>p.textContent.startsWith('called at '))")

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
                if js("document.querySelector('[data-category=unassessedChanges] .change-source-excerpt')?.textContent.includes('FEE = 2')"):break
                time.sleep(.02)
            checks['unassessed_change_opens_exact_source']=js("document.querySelector('[data-category=unassessedChanges] .change-source-excerpt')?.textContent.includes('FEE = 2')")
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
                if js("document.querySelector('#methodName').textContent==='changed_25' && document.querySelector('#cfCode').textContent.includes('125')"):break
                time.sleep(.02)
            checks['change_opens_current_source']=js("document.querySelector('#methodName').textContent==='changed_25' && document.querySelector('#cfCode').textContent.includes('125')")
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
                if js("typeof workflowState!=='undefined' && workflowState.initialized && document.querySelector('#methodName').textContent==='still_calls' && document.querySelector('#cfCode').textContent.includes('removed(value)')"):break
                time.sleep(.05)
            checks['baseline_source_and_return']=js("!document.querySelector('#baselineNotice').hidden && document.querySelector('#cfCode').textContent.includes('removed(value)') && model.snapshotId===new URL(location.href).searchParams.get('snapshot')")
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
        js("(()=>{const s=model.scopes[state.scope];showSource(s.flow[0].span,s.flow[0].label);})()")
        checks['operation_opens_original_code']=js("document.querySelector('#cfCode .cf-focus-line')!==null")
        deep=js("Object.values(model.scopes).find(s=>s.name==='place_order').id")
        snapshot=js("model.snapshotId")
        from urllib.parse import quote
        command('Page.navigate',{'url':f'{review_url}?snapshot={snapshot}#{quote(deep,safe="")}'})
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
        for _ in range(100):
            if js("document.querySelectorAll('#cfCode .code-line').length>=47"):break
            time.sleep(.02)
        # The whole method is shown; bounded pages are joined before rendering.
        checks['long_method_code_complete']=js("document.querySelectorAll('#cfCode .code-line').length===47 && document.querySelector('#cfCode').textContent.includes('value += 44')")
        js("(async()=>{const result=await api('/api/symbols',{q:'progressive',snapshot:model.snapshotId});const scope=result.symbols.items.find(s=>s.name==='progressive');const start=performance.now();await chooseScope(scope.id);window.__methodAndSourceMs=performance.now()-start;window.__workflowStart=performance.now();await showSelectedWorkflow();window.__firstWorkflowMs=performance.now()-window.__workflowStart;})()")
        checks['workflow_first_page_only']=js("workflowState.profile.stages.length===20 && workflowState.profile.nextCursor===20 && workflowState.profile.totalStages===66")
        js("loadMoreWorkflow()")
        checks['workflow_continuation']=js("workflowState.profile.stages.length===40 && workflowState.profile.nextCursor===40")
        (Path(tempfile.gettempdir())/('threadline-changes-performance.json' if change_review else 'threadline-browser-performance.json')).write_text(json.dumps(js("({methodAndSourceMs:window.__methodAndSourceMs,workflowFirstPageMs:window.__firstWorkflowMs})"),indent=2)+'\n')
        if not html_review:
            js("load(true)")
            checks['authorized_browser_refresh']=js("!document.querySelector('#cfCode .error') && !document.querySelector('#refreshButton').disabled")
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
                if js("state.scope===window.__retryScope && document.querySelector('#cfCode').textContent.includes('119')"):break
                time.sleep(.02)
            checks['selection_retry_recovers']=js("document.querySelector('#reviewError').hidden && state.scope===window.__retryScope && document.querySelector('#cfCode').textContent.includes('119')")
            js("(async()=>{delete model.generatedWorkflows[state.scope];window.__failOnce('/api/workflow');await showSelectedWorkflow();})()")
            checks['workflow_error_visible']=js("!document.querySelector('#reviewError').hidden")
            js("document.querySelector('#reviewError button').click()")
            for _ in range(100):
                if js("workflowState.profile.root===window.__retryScope"):break
                time.sleep(.02)
            checks['workflow_retry_recovers']=js("document.querySelector('#reviewError').hidden && workflowState.profile.root===window.__retryScope")
            js("(async()=>{window.__beforeRefresh=model;window.__sourceBeforeRefresh=document.querySelector('#cfCode').textContent;window.__failOnce('/api/reindex');await load(true);})()")
            checks['failed_refresh_preserves_review']=js("model===window.__beforeRefresh && document.querySelector('#cfCode').textContent===window.__sourceBeforeRefresh && !document.querySelector('#reviewError').hidden")
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
        if not html_review:
            js("(async()=>{delete model.generatedWorkflows[state.scope];let release;window.fetch=(...args)=>{if(String(args[0]).includes('/api/workflow')){window.fetch=window.__originalFetch;return new Promise(resolve=>{release=()=>resolve(window.__originalFetch(...args));});}return window.__originalFetch(...args);};const pending=showSelectedWorkflow();await showStartPage();release();await pending;})()")
            checks['late_workflow_keeps_chooser_open']=js("workflowState.mode==='starts' && !document.querySelector('#startPage').hidden")
        else:
            js('showStartPage()')
        checks['buttons_have_names']=js("[...document.querySelectorAll('button')].every(b=>(b.getAttribute('aria-label')||b.textContent).trim().length)")
        checks['no_browser_errors']=not errors
        screenshot=command('Page.captureScreenshot',{'format':'png'})
        (Path(tempfile.gettempdir())/('threadline-changes-browser.png' if change_review else 'threadline-browser.png')).write_bytes(base64.b64decode(screenshot['data']))
        if not html_review:
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
                    if js("document.querySelector('[data-category=unassessedChanges] .change-source-excerpt')?.textContent.includes('[project.scripts]')"):break
                    time.sleep(.02)
                checks['configuration_baseline_source_opens']=js("document.querySelector('[data-category=unassessedChanges] .change-source-excerpt')?.textContent.includes('[project.scripts]')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'Service.entry',snapshot:model.snapshotId});window.__ooEntry=rows.symbols.items.find(s=>s.name==='entry').id;await chooseScope(window.__ooEntry);await showSelectedWorkflow();window.__ooStage=workflowState.profile.stages.find(s=>s.status==='possible'&&s.targetLabels&&Object.values(s.targetLabels).some(n=>n.endsWith('Repo.get')));await selectWorkflowStage(window.__ooStage.id);})()")
        checks['possible_workflow_target_requires_explicit_open']=js("state.scope===window.__ooEntry && [...document.querySelectorAll('.workflow-candidates button')].some(b=>b.textContent.includes('Repo.get'))")
        checks['receiver_candidate_provenance_visible']=js("[...document.querySelectorAll('#workflowContext button')].some(b=>b.textContent.includes('Why is this receiver a candidate?')) && window.__ooStage.candidateEvidence?.some(p=>p.evidenceId && p.label && p.span)")
        js("[...document.querySelectorAll('.workflow-candidates button')].find(b=>b.textContent.includes('Repo.get')).click()")
        for _ in range(100):
            if js("state.scope!==window.__ooEntry && !document.querySelector('.caller-strip').hidden"):break
            time.sleep(.02)
        checks['possible_target_keeps_caller_return']=js("state.scope!==window.__ooEntry && !document.querySelector('.caller-strip').hidden && document.querySelector('.caller-strip').textContent.includes('Back')")
        js("document.querySelector('.caller-strip button').click()")
        for _ in range(100):
            if js("state.scope===window.__ooEntry"):break
            time.sleep(.02)
        checks['possible_target_returns_to_callsite']=js("state.scope===window.__ooEntry")
        def wait_for(expression, tries=150):
            for _ in range(tries):
                if js(expression):break
                time.sleep(.02)
        js("(async()=>{const rows=await api('/api/symbols',{q:'Repo.get',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.qualified==='Repo.get').id);})()")
        wait_for("document.querySelector('#cfTests .cf-row')!==null && document.querySelector('#cfCallers .cf-row')!==null")
        checks['one_review_view']=js("document.querySelector('#methodTabs')===null && document.querySelector('.source-panel')===null && document.querySelector('#dataflowPanel')===null && !document.querySelector('#codeFirst').hidden")
        checks['tests_count_and_summary']=js("document.querySelector('#cfTests h2').textContent==='Tests · 1' && document.querySelector('#cfSummary').textContent.includes('Returns')")
        checks['method_source_bounded']=js("document.querySelector('#cfCode').textContent.includes('def get') && !document.querySelector('#cfCode').textContent.includes('class Service')")
        checks['related_test_listed_with_reason']=js("document.querySelector('#cfTests .cf-row').textContent.includes('test_entry_reads_repo') && document.querySelector('#cfTests').textContent.includes('through Service.entry')")
        js("document.querySelector('#cfTests .cf-row').click()")
        wait_for("document.querySelector('#cfBeside .code-line.focus')!==null")
        checks['test_source_beside_method']=js("!document.querySelector('#cfBeside').hidden && document.querySelector('#cfBeside .cf-beside-kind').textContent==='Test' && document.querySelector('#cfBeside .code-line.focus')?.textContent.includes('entry()') && document.querySelector('#cfCode').textContent.includes('def get')")
        js("document.body.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        checks['escape_closes_side_code']=js("document.querySelector('#cfBeside').hidden")
        checks['callers_listed']=js("document.querySelector('#cfCallers').textContent.includes('Service.entry') && document.querySelector('#cfCallers').textContent.includes('probably')")
        js("document.querySelector('#cfCallers .cf-row').click()")
        wait_for("document.querySelector('#cfBeside .code-line.focus')!==null")
        checks['caller_opens_beside_code']=js("document.querySelector('#cfBeside .cf-beside-kind').textContent==='Caller' && document.querySelector('#cfBeside .code-line.focus')?.textContent.includes('self.repo.get()')")
        js("document.querySelector('#cfBeside .cf-beside-actions button').click()")
        wait_for("document.querySelector('#methodName').textContent==='Service.entry'")
        checks['open_moves_into_method_with_back']=js("document.querySelector('#methodName').textContent==='Service.entry' && !document.querySelector('#pathBar').hidden && document.querySelector('#pathBar').textContent.includes('Repo.get')")
        js("document.body.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Backspace',bubbles:true}))")
        wait_for("document.querySelector('#methodName').textContent==='Repo.get' && document.querySelector('#cfBeside .code-line')!==null")
        checks['back_restores_side_code']=js("document.querySelector('#methodName').textContent==='Repo.get' && !document.querySelector('#cfBeside').hidden && document.querySelector('#cfBeside .cf-beside-kind').textContent==='Caller'")
        js("(async()=>{const rows=await api('/api/symbols',{q:'test_entry_reads_repo',snapshot:model.snapshotId});await chooseScope(rows.symbols.items[0].id);})()")
        wait_for("document.querySelector('#cfTests .cf-row')!==null")
        checks['selected_test_lists_exercised_code']=js("document.querySelector('#cfTests h2').textContent.startsWith('Code this test reaches') && document.querySelector('#cfTests').textContent.includes('Service.entry')")
        js("document.querySelector('#sidebarToggle').click()")
        checks['sidebar_can_collapse']=js("document.querySelector('.workspace').classList.contains('sidebar-collapsed') && document.querySelector('#sidebarToggle').textContent.includes('Show sidebar')")
        checks['sidebar_collapse_fills_width']=js("(()=>{const w=document.querySelector('.workspace').getBoundingClientRect(),r=document.querySelector('.review').getBoundingClientRect();return document.querySelector('#repositoryNavigator').getBoundingClientRect().width===0 && Math.abs(r.left-w.left)<2 && Math.abs(r.right-w.right)<2})()")
        command('Emulation.setDeviceMetricsOverride',{'width':390,'height':850,'deviceScaleFactor':1,'mobile':True})
        checks['sidebar_collapse_narrow_no_overflow']=js("document.documentElement.scrollWidth<=innerWidth")
        command('Emulation.setDeviceMetricsOverride',{'width':1280,'height':900,'deviceScaleFactor':1,'mobile':False})
        js("document.querySelector('#sidebarToggle').click()")
        js("document.body.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'?',bubbles:true}))")
        checks['help_opens_with_legend']=js("!document.querySelector('#helpPanel').hidden && document.querySelector('#helpPanel').textContent.includes('Probably calls') && document.querySelector('#helpButton').getAttribute('aria-expanded')==='true'")
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        checks['help_closes_on_escape']=js("document.querySelector('#helpPanel').hidden")
        js("(async()=>{const rows=await api('/api/symbols',{q:'unreachable',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='unreachable').id);await showSelectedWorkflow();workflowState.showLibrary=true;renderWorkflow();})()")
        checks['unreachable_workflow_stage_marked']=js("[...document.querySelectorAll('.workflow-stage.unreachable')].some(b=>b.querySelector('.stage-tag.tag-unreachable'))")
        js("(async()=>{const rows=await api('/api/symbols',{q:'conditional',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='conditional').id);await showSelectedWorkflow();})()")
        checks['conditional_workflow_stage_marked']=js("[...document.querySelectorAll('.workflow-stage')].some(b=>b.querySelector('.stage-tag.tag-conditional')?.textContent==='if')")
        checks['call_map_steps_uniform']=js("[...document.querySelectorAll('.workflow-stage')].every(b=>b.querySelector('.workflow-stage-title') && b.querySelector('.workflow-stage-place'))")
        js("workflowState.showLibrary=false")
        js("(async()=>{const rows=await api('/api/symbols',{q:'built',snapshot:model.snapshotId});window.__built=rows.symbols.items.find(s=>s.name==='built').id;await chooseScope(window.__built);await showSelectedWorkflow();const stage=workflowState.profile.stages.find(s=>s.construction);await selectWorkflowStage(stage.id);})()")
        checks['construction_does_not_open_class_body_as_call']=js("state.scope===window.__built && document.querySelector('#workflowContext').textContent.includes('Constructing an object') && document.querySelector('#workflowContext').textContent.includes('Go to Repo.__init__')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'dashboard',snapshot:model.snapshotId});const scope=rows.symbols.items.find(s=>s.file==='dataflow_dashboard.py'&&s.name==='dashboard');await chooseScope(scope.id);})()")
        wait_for("document.querySelector('#cfContext .cf-models').textContent.includes('description')")
        checks['dashboard_models_as_source']=js("(()=>{const t=document.querySelector('#cfContext .cf-models').textContent;return t.includes('Project') && t.includes('description') && t.includes('Task')})()")
        checks['dashboard_method_only_code']=js("document.querySelector('#cfCode').textContent.includes('async def dashboard') && !document.querySelector('#cfCode').textContent.includes('def edit_values')")
        js("(async()=>{const rows=await api('/api/symbols',{q:'use_models',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='use_models').id);})()")
        wait_for("document.querySelector('#cfContext .data-model-more')!==null")
        checks['models_page_first_80']=js("document.querySelector('#cfContext').textContent.includes('Model0') && !document.querySelector('#cfContext').textContent.includes('Model84') && document.querySelector('#cfContext .data-model-more')!==null")
        js("document.querySelector('#cfContext .data-model-more').click()")
        wait_for("document.querySelector('#cfContext').textContent.includes('Model84')")
        checks['models_page_reaches_all_definitions']=js("document.querySelector('#cfContext').textContent.includes('Model84') && document.querySelectorAll('#cfContext .data-model-item').length>=85 && document.querySelector('#cfContext .data-model-more')===null")
        js("(async()=>{const rows=await api('/api/symbols',{q:'submit_order',snapshot:model.snapshotId});await chooseScope(rows.symbols.items.find(s=>s.name==='submit_order').id);})()")
        wait_for("document.querySelector('#cfCode .cf-call')!==null && document.querySelector('#cfContext .data-model-item')!==null")
        checks['summary_lists_in_calls_returns']=js("(()=>{const t=document.querySelector('#cfSummary').textContent;return ['request','repository','notifier','place_order','OrderResponse'].every(w=>t.includes(w))})()")
        checks['shows_only_method_code']=js("document.querySelector('#cfCode').textContent.includes('def submit_order') && !document.querySelector('#cfCode').textContent.includes('def place_order')")
        js("document.querySelector('#cfSummary .cf-chip[data-name=request]').click()")
        checks['name_highlight']=js("document.querySelectorAll('#cfCode .cf-hit').length>=4 && document.querySelectorAll('#cfCode .cf-hit-line').length>=2")
        js("document.querySelector('#cfCode .cf-call').click()")
        wait_for("document.querySelector('#cfBeside .code-line')!==null")
        checks['call_opens_beside_code']=js("!document.querySelector('#cfBeside').hidden && document.querySelector('#cfBeside').textContent.includes('def place_order') && state.scope.includes('api.py')")
        checks['models_as_source']=js("[...document.querySelectorAll('#cfContext .data-model-item')].some(item=>item.textContent.includes('class Order'))")
        if not html_review:
            (fixture_root/'broken.py').write_text('def incomplete(:\n')
            js("load(true)")
            checks['parse_failure_prominent_and_retrievable']=js("!document.querySelector('#analysisStatus').hidden && document.querySelector('#analysisStatus').textContent.includes('1 analysis issue') && document.querySelector('#coveragePanel').textContent.includes('Analysis issues · 1')")
            js("document.querySelector('#analysisStatus').click()")
            checks['parse_failure_badge_opens_coverage']=js("!document.querySelector('#coveragePanel').hidden")
            (fixture_root/'broken.py').unlink()
            (fixture_root/'pyproject.toml').write_bytes(b'\xff')
            js("load(true)")
            checks['configuration_error_prominent']=js("!document.querySelector('#analysisStatus').hidden && document.querySelector('#analysisStatus').textContent.includes('1 analysis issue') && document.querySelector('#coveragePanel').textContent.includes('Analysis issues · 1')")
        else:
            checks['standalone_file_url']=js("location.protocol==='file:'")
            checks['refresh_hidden_for_saved_review']=js("document.querySelector('#refreshButton').hidden")
            checks['no_external_assets']=js("[...document.scripts].every(s=>!s.src) && !document.querySelector('link[rel=stylesheet]')")
            checks['source_script_not_executed']=js("window.__sourceExecuted===undefined")
            checks['no_network_requests']=js("performance.getEntriesByType('resource').length===0")
            (fixture_root/'routes_demo.py').unlink()
            checks['source_retained_after_deletion']=js("(async()=>{const r=await api('/api/source',{file:'routes_demo.py',start:1,end:3});return r.source.includes('APIRouter');})()")
        print(json.dumps(checks,indent=2))
        if not all(checks.values()): raise SystemExit(1)
        ws.close()
    finally:
        browser.terminate();browser.wait(timeout=5)
        if server:
            server.shutdown();server.server_close();worker.join()
        fixture.cleanup()
