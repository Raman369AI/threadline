"""Run keyboard, reflow, and axe checks in Chrome or native macOS Safari.

Only Threadline executes. The reviewed fixture is copied and parsed as source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from threadline.server import make_server
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['chrome', 'safari'], default='chrome')
    parser.add_argument('--report', type=Path, default=ROOT/'artifacts'/'accessibility.json')
    args = parser.parse_args()
    axe = ROOT/'tests'/'browser-tools'/'node_modules'/'axe-core'/'axe.min.js'
    if not axe.is_file(): parser.error('Run npm ci --prefix tests/browser-tools --ignore-scripts first')
    if args.browser == 'safari' and sys.platform != 'darwin': parser.error('Native Safari requires macOS')
    checks, audits, viewports = {}, [], []
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='threadline-accessibility-') as directory:
        fixture=Path(directory)
        for source in (ROOT/'example').glob('*.py'): shutil.copyfile(source,fixture/source.name)
        (fixture/'routes.py').write_text('from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/items")\ndef list_items():\n    return []\n@router.post("/items")\ndef create_item():\n    return {}\n')
        (fixture/'deleted.py').write_text('def removed(value):\n    return value\n')
        (fixture/'impact.py').write_text('from deleted import removed\ndef still_calls(value):\n    return removed(value)\n')
        for command in (['init','-q'], ['config','user.email','test@example.invalid'], ['config','user.name','Test'], ['add','.'], ['commit','-qm','baseline']):
            subprocess.run(['git',*command],cwd=fixture,check=True)
        (fixture/'deleted.py').unlink()
        (fixture/'impact.py').write_text('from deleted import removed\ndef still_calls(value):\n    return removed(value + 1)\n')
        server=make_server(fixture,port=0,base='HEAD')
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        driver=None
        try:
            if args.browser == 'safari':
                driver=webdriver.Safari()
            else:
                options=webdriver.ChromeOptions()
                for flag in ('--headless=new','--no-sandbox','--disable-dev-shm-usage'):
                    options.add_argument(flag)
                driver=webdriver.Chrome(options=options)
            driver.set_window_size(1440,1000)
            driver.set_script_timeout(30)
            driver.get(f'http://127.0.0.1:{server.server_port}/')
            wait=WebDriverWait(driver,15)
            wait.until(lambda d:d.execute_script("return typeof workflowState!=='undefined' && workflowState.initialized && !document.querySelector('#startPage').hidden"))

            def js(expression):
                result=driver.execute_async_script('const done=arguments[arguments.length-1];Promise.resolve().then(async()=>('+expression+')).then(value=>done({value}),error=>done({error:String(error)}));')
                if 'error' in result: raise AssertionError(result['error'])
                return result.get('value')

            def check(name, condition):
                checks[name]=bool(condition)

            def key(value): ActionChains(driver).send_keys(value).perform()

            def tab_to(selector, maximum=150):
                trail=[]
                for _ in range(maximum):
                    focused=driver.execute_script('const e=document.activeElement;return {matches:e.matches(arguments[0]),tag:e.tagName,id:e.id,text:e.textContent.slice(0,50)}',selector)
                    if focused['matches']: return
                    trail.append(focused)
                    if args.browser=='safari':
                        ActionChains(driver).key_down(Keys.ALT).send_keys(Keys.TAB).key_up(Keys.ALT).perform()
                    else: key(Keys.TAB)
                raise AssertionError('Keyboard could not reach '+selector+'; recent focus: '+json.dumps(trail[-8:]))

            def audit(name):
                driver.execute_script(axe.read_text())
                result=js("axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}})")
                audits.append({'state':name,'violations':result['violations'],'incomplete':result['incomplete']})
                check('axe_'+name,not result['violations'])

            audit('chooser')
            tab_to('#verb-All');key(Keys.ARROW_RIGHT)
            wait.until(lambda d:d.execute_script("return document.querySelector('#verb-GET').getAttribute('aria-selected')==='true' && document.querySelectorAll('#endpointResults .start-item').length===1"))
            check('keyboard_endpoint_tabs',js("document.activeElement.id==='verb-GET' && document.querySelector('#endpointResults').textContent.includes('list_items')"))
            audit('endpoint_tab')
            for width in (720,390):
                driver.set_window_size(width,900)
                check('endpoints_reflow_'+str(width),js('document.documentElement.scrollWidth<=innerWidth'))
                audit('endpoints_reflow_'+str(width))
            driver.set_window_size(1440,1000)
            tab_to('#methodsTab');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'.module-item')))
            check('keyboard_methods_page',js("catalogPage==='methods' && document.querySelector('#startGroups [data-category=http]')===null"))
            audit('methods_page')
            tab_to('.module-item[data-file="api.py"]');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'#moduleResults [data-scope]')))
            check('keyboard_module_selection',js("document.activeElement.classList.contains('module-heading') && new URL(location.href).searchParams.get('module')==='api.py'"))
            audit('selected_module')
            tab_to('.module-heading button');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'.module-item')))
            check('keyboard_back_to_modules',js("document.querySelectorAll('#moduleResults [data-scope]').length===0"))
            tab_to('#changesTab');key(Keys.ENTER)
            audit('changes')
            tab_to('[data-category=files] .change-record button');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'[data-category=files] .change-source-excerpt .code-line')))
            check('keyboard_change_source',js("document.activeElement.classList.contains('change-source-excerpt')"))
            audit('change_source')
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'[data-category=changedMethods] .change-record button')))
            tab_to('[data-category=changedMethods] .change-record button:nth-child(2)');key(Keys.ENTER)
            wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#comparisonPanel .code-line'))>0)
            check('keyboard_comparison',True)
            audit('comparison')
            for width in (720,390):
                driver.set_window_size(width,900)
                check('comparison_reflow_'+str(width),js('document.documentElement.scrollWidth<=innerWidth'))
                audit('comparison_reflow_'+str(width))
            driver.set_window_size(1440,1000)
            tab_to('#comparisonPanel button');key(Keys.ENTER)
            check('comparison_close_focus',js("document.activeElement.textContent==='Compare before / after'"))
            tab_to('#changesBrowser [data-category=baselineCallers] > summary');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'[data-category=baselineCallers] a')))
            check('keyboard_baseline_callers',True)
            audit('baseline_callers')
            for width in (720,390):
                driver.set_window_size(width,900)
                check('changes_reflow_'+str(width),js('document.documentElement.scrollWidth<=innerWidth'))
                audit('changes_reflow_'+str(width))
            driver.set_window_size(1440,1000)
            js("(async()=>{const rows=await api('/api/symbols',{q:'submit_order',snapshot:model.snapshotId});await startReview(rows.symbols.items[0].id);})()")
            wait.until(lambda d:d.execute_script("return workflowState.mode==='workflow'"))
            audit('workflow')
            # Enter the primary task using only keyboard focus and activation.
            driver.find_element(By.TAG_NAME,'body').send_keys('/')
            wait.until(lambda d:d.switch_to.active_element.get_attribute('id')=='search')
            check('keyboard_search',js("document.activeElement.id==='search'"))
            key('place_order')
            wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,'#navigation .nav-item'))==1)
            tab_to('#navigation .nav-item');key(Keys.ENTER)
            wait.until(lambda d:d.find_element(By.ID,'methodName').text=='place_order')
            check('default_dataflow_and_models',js("document.querySelector('#tab-dataflow').getAttribute('aria-selected')==='true' && document.querySelector('#dataModelPane').getBoundingClientRect().width>0"))
            audit('dataflow_method')
            tab_to('#tab-dataflow');key(Keys.ARROW_RIGHT)
            wait.until(lambda d:d.execute_script("return document.querySelector('#tab-steps').getAttribute('aria-selected')==='true'"))
            check('keyboard_steps_view',js("document.activeElement.id==='tab-steps' && !document.querySelector('#stepsPanel').hidden"))
            # Source, branch, and call controls must remain keyboard reachable.
            tab_to('#flow .op-head');key(Keys.ENTER)
            wait.until(lambda d:bool(d.find_elements(By.CSS_SELECTOR,'#sourceCode .focus')))
            check('keyboard_source_selection',True)
            tab_to('#flow .branch > summary')
            was_open=js('document.activeElement.parentElement.open')
            key(Keys.ENTER)
            wait.until(lambda d:d.execute_script('return document.activeElement.parentElement.open')!=was_open)
            check('keyboard_branch_toggle',True)
            if not js('document.activeElement.parentElement.open'): key(Keys.ENTER)
            tab_to('#flow .call-open');key(Keys.ENTER)
            wait.until(lambda d:d.switch_to.active_element.get_attribute('aria-expanded')=='true')
            check('keyboard_call_expansion',True)
            check('focus_is_visible',js("getComputedStyle(document.activeElement).outlineStyle!=='none' && parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2"))
            audit('expanded_method')
            tab_to('#fullCode');key(Keys.ENTER)
            check('keyboard_full_width_code',js("document.querySelector('.workspace').classList.contains('code-full') && document.querySelector('#sourceCode').textContent.includes('def place_order')"))
            audit('full_width_code')
            tab_to('#restoreCode');key(Keys.ENTER)
            check('keyboard_restore_analysis',js("!document.querySelector('.workspace').classList.contains('code-full') && !document.querySelector('#stepsPanel').hidden && document.querySelector('#dataModelPane').getBoundingClientRect().width>0"))
            tab_to('#codeResize')
            before=js("document.querySelector('#codeResize').getAttribute('aria-valuenow')")
            key(Keys.ARROW_LEFT)
            check('keyboard_code_resize',js("document.querySelector('#codeResize').getAttribute('aria-valuenow')")!=before)
            before=js("document.querySelector('#codeResize').getAttribute('aria-valuenow')")
            ActionChains(driver).click_and_hold(driver.find_element(By.ID,'codeResize')).move_by_offset(-60,0).release().perform()
            check('pointer_code_resize',js("document.querySelector('#codeResize').getAttribute('aria-valuenow')")!=before)
            tab_to('#resetCodeWidth');key(Keys.ENTER)
            tab_to('#sidebarToggle');key(Keys.ENTER)
            check('keyboard_sidebar_collapse',js("document.querySelector('.workspace').classList.contains('sidebar-collapsed') && document.querySelector('#sidebarToggle').textContent.includes('Show sidebar')"))
            tab_to('#sidebarToggle');key(Keys.ENTER)
            tab_to('#focusMode');key(Keys.ENTER)
            check('keyboard_no_distraction',js("document.querySelector('.workspace').classList.contains('no-distraction') && document.querySelector('#dataModelPane').getBoundingClientRect().width>0"))
            audit('no_distraction')
            tab_to('#focusMode');key(Keys.ENTER)
            # A nonmodal coverage region must accept focus and return it on Escape.
            tab_to('#coverageButton');key(Keys.ENTER)
            wait.until(lambda d:not d.find_element(By.ID,'coveragePanel').get_attribute('hidden'))
            check('coverage_focus',js("document.querySelector('#coveragePanel').contains(document.activeElement)"))
            audit('coverage')
            key(Keys.ESCAPE)
            check('coverage_focus_return',js("document.activeElement.id==='coverageButton' && document.querySelector('#coveragePanel').hidden"))
            # A 720 CSS-pixel viewport models the reflow available at 200% desktop zoom.
            for width in (720,390):
                driver.set_window_size(width,900)
                viewports.append({'requestedWidth':width,'actualInnerWidth':js('innerWidth')})
                check('reflow_'+str(width),js('document.documentElement.scrollWidth<=innerWidth'))
                audit('reflow_'+str(width))
            driver.set_window_size(1440,1000)
            if args.browser == 'chrome':
                driver.execute_cdp_cmd('Accessibility.enable',{})
                tree=driver.execute_cdp_cmd('Accessibility.getFullAXTree',{})['nodes']
                visible=[node for node in tree if not node.get('ignored')]
                names={node.get('name',{}).get('value') for node in visible}
                roles={node.get('role',{}).get('value') for node in visible}
                check('accessibility_landmarks',{'main','complementary'}<=roles)
                check('accessible_source_and_search',{'Original Python source','Search routes, commands, and methods'}<=names)
                check('live_announcements',any(any(prop['name']=='live' and prop['value'].get('value')=='polite' for prop in node.get('properties',[])) for node in visible))
            # Browser layout zoom, rather than a screenshot-only scale factor.
            driver.execute_script("document.documentElement.style.zoom='2'")
            check('zoom_200_percent',js('document.documentElement.scrollWidth<=innerWidth'))
            audit('zoom_200_percent')
            driver.execute_script("document.documentElement.style.zoom=''")
            js("(async()=>{window.__originalFetch=fetch;window.fetch=async(...args)=>{if(String(args[0]).includes('/api/starts')){window.fetch=window.__originalFetch;throw new Error('Temporary search failure');}return window.__originalFetch(...args);};document.querySelector('#search').value='place_order';await navigation();})()")
            check('visible_retry_error',js("!document.querySelector('#reviewError').hidden && document.querySelector('#reviewError [role=alert]').textContent.includes('Temporary search failure')"))
            audit('retry_error')
            tab_to('#reviewError button');key(Keys.ENTER)
            wait.until(lambda d:d.find_element(By.ID,'reviewError').get_attribute('hidden'))
            check('keyboard_error_retry',True)
            check('source_view_remains_usable',js("!document.querySelector('#flow .error')"))
            report={'browser':driver.capabilities.get('browserName'),'version':driver.capabilities.get('browserVersion'),
                    'platform':sys.platform,'viewports':viewports,'checks':checks,'audits':audits,'passed':all(checks.values()),
                    'scope':'Automated keyboard, accessibility-tree, axe and reflow checks; no claim of a human screen-reader session.'}
            args.report.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({'browser':report['browser'],'version':report['version'],'checks':checks,'report':str(args.report)},indent=2))
            if not report['passed']:raise SystemExit(1)
        finally:
            if not args.report.exists(): args.report.write_text(json.dumps({'checks':checks,'audits':audits,'passed':False},indent=2)+'\n')
            if driver:
                driver.save_screenshot(str(args.report.with_suffix('.png')))
                driver.quit()
            server.shutdown();server.server_close();worker.join()


if __name__=='__main__': main()
