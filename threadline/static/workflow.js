/* Cross-file workflow for the currently selected method. */
const workflowState = { mode:'starts', profile:null, stage:null, initialized:false, showLibrary:false };

async function initializeWorkflows(refresh=false) {
  if(!state.scope || !model.scopes[state.scope]) {await showStartPage();return;}
  const captured=model, selected=state.scope;
  const profile=await loadCallWorkflow(selected);
  if(captured!==model || selected!==state.scope) return;
  workflowState.profile=profile;
  workflowState.stage=workflowState.profile.stages.find(s=>s.id===workflowState.stage)?.id || workflowState.profile.stages[0]?.id;
  const firstLoad=!workflowState.initialized;
  workflowState.initialized=true;
  setWorkflowMode('workflow');
  if(firstLoad && workflowState.stage) await selectWorkflowStage(workflowState.stage);
  if(!refresh && firstLoad && new URLSearchParams(location.search).get('trace')==='1') showSelectedWorkflow();
}
function setWorkflowMode(mode) {
  if(mode==='changes' && !model.changes?.baseSnapshotId) mode='starts';
  workflowState.mode=mode;
  const choosing=mode==='starts' || !state.scope;
  $('.workspace').classList.toggle('choosing',choosing);
  $('#startPage').hidden=!choosing;
  $('#startGroups').hidden=mode==='changes';
  $('#startTitle').textContent=mode==='changes'?'Choose a changed method':catalogTitles[catalogPage];
  $('#startHint').textContent=mode==='changes'?'Select a method to review its workflow, or compare its before and after source.':catalogPage==='endpoints'?'Choose an endpoint to open its workflow and source. Paths are shown as declared in source.':catalogPage==='commands'?'Choose a command or task to open its workflow and source.':'Choose a module, then a method. Follow its calls across modules in the same workflow.';
  $('#repositoryBrowser').hidden=true;
  $('#changesBrowser').hidden=mode!=='changes';
  $('#changesTab').setAttribute('aria-pressed',String(mode==='changes'));
  $('#workflowBrowser').hidden=mode!=='workflow';
  $('#workflowContext').hidden=mode!=='workflow';
  $('.workspace').classList.add('workflow-mode');
  $('#workflowTab').setAttribute('aria-pressed',String(mode==='workflow'));
  for(const [page,id] of Object.entries({endpoints:'endpointsTab',commands:'commandsTab',methods:'methodsTab'}))$('#'+id).setAttribute('aria-pressed',String(mode==='starts' && catalogPage===page));
  if(mode==='workflow'){renderWorkflow();renderWorkflowContext();}
}
function makeCallWorkflow(scopeId) {
  return model.generatedWorkflows?.[scopeId] || {id:'entrypoint-calls',title:'Workflow for selected method',description:'',provenance:'Generated from source syntax.',stages:[],links:[],outcomes:[],nested:true};
}
async function loadCallWorkflow(scopeId) {
  const captured=model;
  if(captured.generatedWorkflows?.[scopeId]) return captured.generatedWorkflows[scopeId];
  captured.workflowRequests ||= {};
  if(captured.workflowRequests[scopeId]) return captured.workflowRequests[scopeId];
  const request=(async()=>{
    const page=await api('/api/workflow',{entrypoint:scopeId,snapshot:captured.snapshotId,cursor:0,limit:20});
    const workflow={...page,stages:[],links:[],alternatives:[],uncertainties:[]};
    mergeWorkflowPage(workflow,page);
    captured.generatedWorkflows[scopeId]=workflow;
    return workflow;
  })();
  captured.workflowRequests[scopeId]=request;
  try {return await request;} finally {delete captured.workflowRequests[scopeId];}
}
function mergeWorkflowPage(workflow,page) {
  workflow.stages.push(...page.stages.items);
  workflow.links.push(...page.links);
  workflow.alternatives.push(...page.alternatives.items);
  workflow.uncertainties.push(...page.uncertainties.items);
  workflow.nextCursor=page.nextCursor;
  workflow.totalStages=page.stages.total;
  workflow.totalAlternatives=page.alternatives.total;
  workflow.totalUncertainties=page.uncertainties.total;
}
async function loadMoreWorkflow() {
  const captured=model, workflow=workflowState.profile;
  if(!workflow || workflow.nextCursor===null || workflow.loading) return;
  const hadFocus=$('#workflowBrowser').contains(document.activeElement), firstNewIndex=workflow.stages.length;
  workflow.loading=true;renderWorkflow();
  try {
    const page=await api('/api/workflow',{entrypoint:workflow.root,snapshot:captured.snapshotId,cursor:workflow.nextCursor,limit:20});
    if(captured!==model) return;
    mergeWorkflowPage(workflow,page);clearError('workflow');
    announce('Loaded '+workflow.stages.length+' of '+workflow.totalStages+' workflow steps.');
  } catch(error) {if(captured===model && workflow===workflowState.profile) reportError(error,loadMoreWorkflow,'workflow');}
  finally {
    workflow.loading=false;
    if(captured===model && workflow===workflowState.profile) {
      renderWorkflow();
      if(hadFocus && document.activeElement===document.body) {
        const stage=workflow.stages[firstNewIndex];
        [...$('#workflowBrowser').querySelectorAll('.workflow-stage')].find(button=>button.dataset.stage===stage?.id)?.focus({preventScroll:true});
      }
    }
  }
}
async function showSelectedWorkflow() {
  if(!state.scope){await showStartPage();return;}
  const selected=state.scope, captured=model, request=startRequest;
  announce('Building workflow…');
  try {
    const profile=await loadCallWorkflow(selected);
    if(captured!==model || selected!==state.scope || request!==startRequest)return;
    clearError('workflow');
    workflowState.profile=profile;workflowState.stage='entry';
    setWorkflowMode('workflow');renderWorkflow();await selectWorkflowStage('entry');announce('Workflow ready.');
  } catch(error){if(captured===model && selected===state.scope && request===startRequest) reportError(error,showSelectedWorkflow,'workflow');}
}
function renderWorkflow() {
  const host=$('#workflowBrowser'),scroll=host.scrollTop;host.replaceChildren();
  const workflow=workflowState.profile;if(!workflow)return;
  host.append(el('h2','workflow-title','Call map'),el('p','workflow-intro','Every call reachable from '+scopeName(workflow.root)+', nested under its caller.'));
  if(!workflow.stages.length){host.append(button('Build workflow for selected method →','workflow-primary-action',showSelectedWorkflow));host.scrollTop=scroll;return;}
  // Library calls (str, len, dict.get…) are resolved, not gaps; fold them away by default.
  // The map lists project functions; library and untraced leaf calls stay one toggle away.
  const library=workflow.stages.filter(stage=>['external','unknown'].includes(stage.status) && stage.id!==workflowState.stage && !workflow.stages.some(child=>child.parent===stage.id));
  const kind=' library & untraced calls';
  if(library.length){
    const toggle=button((workflowState.showLibrary?'Hide ':'Show ')+library.length+kind,'quiet-button workflow-library-toggle',()=>{workflowState.showLibrary=!workflowState.showLibrary;renderWorkflow();});
    toggle.setAttribute('aria-pressed',String(workflowState.showLibrary));host.append(toggle);
  }
  const hidden=new Set(workflowState.showLibrary?[]:library.map(stage=>stage.id));
  const list=el('div','workflow-stages');
  for(const [index,stage] of workflow.stages.entries()){
    if(hidden.has(stage.id))continue;
    if(stage.parent){
      const link=workflow.links.find(item=>item.to===stage.id),parent=workflow.stages.find(item=>item.id===stage.parent),group=el('div','workflow-nested-step');
      group.style.marginLeft=Math.min(stage.depth||1,3)*6+'px';
      if(link?.kind==='possible_event')group.append(el('div','workflow-nest-label','⋯ probably triggered by an event'));
      group.append(stageButton(stage,index));
      list.append(group);
    }else list.append(stageButton(stage,index));
  }
  host.append(list);
  const untraced=workflow.stages.filter(stage=>stage.status==='unknown').length;
  host.append(el('p','source-peek',(workflow.nextCursor!==null?workflow.stages.length+' of ':'')+workflow.totalStages+' steps'+(untraced?' · '+untraced+" Threadline can't trace":'')));
  if(workflow.nextCursor!==null) {
    const more=button(workflow.loading?'Loading…':'Load more steps','quiet-button',loadMoreWorkflow);
    more.disabled=Boolean(workflow.loading);host.append(more);
  }
  for(const [label,rows] of [['Decision points',workflow.alternatives],["Calls Threadline can't pin down",workflow.uncertainties]]) {
    if(!rows.length) continue;
    const details=el('details','workflow-provenance');details.append(el('summary','',label));
    for(const row of rows) {
      const description=(row.reason || row.arms?.join(' / ') || '')+(row.unreachable?' · Unreachable after an unconditional exit.':'');
      details.append(button((row.kind==='expression'?'Expression choice · ':'')+(row.label || row.reason),'workflow-link-evidence',()=>showSource(row.span,label,description)));
    }
    host.append(details);
  }
  if(workflow.truncated) host.append(el('p','status unknown',workflow.omitted+' more calls were left out to keep the map readable (limit: 500 steps, 100 levels deep).'));
  const note=el('details','workflow-provenance');note.append(el('summary','','How this workflow was built'),el('p','',workflow.provenance));host.append(note);
  host.scrollTop=scroll;
}
// Every call in an async body is formally deferred; that only matters when the
// coroutine itself is not awaited (inherited), or the call creates one unawaited.
// Deferral is also inherited through awaited calls; follow deferredBy to the call that
// actually defers. An unloaded source stage keeps the conservative answer.
function runsLater(stage,seen=new Set()) {
  const context=stage.executionContext||{};
  if(/deferred (coroutine|generator)|background/.test(stage.condition||'') || (context.deferred && context.kind!=='coroutine body')) return true;
  if(!context.inheritedDeferred || seen.has(stage.id)) return false;
  seen.add(stage.id);
  const source=workflowState.profile?.stages.find(item=>item.id===context.deferredBy);
  return source?runsLater(source,seen):true;
}
// Every step reads the same way: number, name, tags; then the line that calls it.
const stageTags={possible:['probably','The likely target; inheritance or a reassignment could change it'],unknown:["can't tell",'The target is decided at runtime'],external:['library','Code outside this repository']};
function stageButton(stage,index) {
  const scope=model.scopes[stage.scope],b=button('','workflow-stage'+(stage.id===workflowState.stage?' active':'')+(stage.unreachable?' unreachable':''),()=>selectWorkflowStage(stage.id));
  b.title=stage.condition+' · '+(scope?.qualified||stage.label);b.dataset.stage=stage.id;b.setAttribute('aria-pressed',String(stage.id===workflowState.stage));
  const head=el('span','workflow-stage-head');
  head.append(el('strong','workflow-stage-title',stage.label));
  const tags=[];
  if(stageTags[stage.status])tags.push([...stageTags[stage.status],stage.status]);
  if(stage.conditional)tags.push(['if','Runs only when a condition holds','conditional']);
  if(runsLater(stage))tags.push(['later','Runs later, if at all','later']);
  if(stage.construction)tags.push(['new object','Creates an object; its initializer runs','construct']);
  if(stage.unreachable)tags.push(['unreachable','Written after an unconditional exit','unreachable']);
  for(const [label,title,kind] of tags){const tag=el('span','stage-tag tag-'+kind,label);tag.title=title;head.append(tag);}
  // One location for every step: the line that makes the call (the entry: its definition).
  const span=index?(stage.evidence?.[0]?.span||stage.span):scope?.span;
  b.append(head);
  if(span){const place=el('span','workflow-stage-place',(index?'called at ':'')+span.file.split('/').slice(-2).join('/')+':'+span.start);place.title=span.file+':'+span.start;b.append(place);}
  return b;
}
async function selectWorkflowStage(id) {
  const stage=workflowState.profile?.stages.find(s=>s.id===id);if(!stage)return;
  workflowState.stage=id;
  $('#workflowBrowser').querySelectorAll('.workflow-stage').forEach(b=>{b.classList.toggle('active',b.dataset.stage===id);b.setAttribute('aria-pressed',String(b.dataset.stage===id));});
  const readCallsite=stage.callsite||stage.construction||stage.unreachable;
  const initialScope=readCallsite?(stage.callerScope||stage.evidence?.[0]?.scope||stage.scope):stage.scope;
  if(!await chooseScope(initialScope))return;renderWorkflowContext();
  if(readCallsite&&stage.evidence?.length) showSource(stage.evidence[0].span,stage.label,stage.condition);
  announce('Workflow stage: '+stage.label);
}
function workflowGuardText(guard) {
  return [guard.kind,guard.condition,guard.branch||guard.requirement].filter(Boolean).join(' · ');
}
async function openWorkflowCandidate(stage,id) {
  const caller=stage.callerScope||stage.evidence?.[0]?.scope||stage.scope;
  if(state.scope!==caller && !await chooseScope(caller))return;
  await enterScope(id,{scope:caller,destination:stage.destination||'the caller'});
}
function renderWorkflowContext() {
  const host=$('#workflowContext');host.replaceChildren();
  const workflow=workflowState.profile,stage=workflow?.stages.find(s=>s.id===workflowState.stage);if(!stage)return;
  const kicker=el('div','workflow-context-kicker','Call map');
  if(stage.status&&!['supported','source-linked'].includes(stage.status))kicker.append(el('span','certainty '+stage.status,certaintyLabel(stage.status)));
  host.append(kicker);
  const methods=stage.methods||[];
  if(stage.parent&&stage.data)host.append(el('p','workflow-context-data','Passes '+stage.data));
  if(stage.unreachable)host.append(el('p','status unknown','Written after an unconditional exit, so it cannot run from here.'));
  if(stage.conditional)host.append(el('p','workflow-intro','Runs only when its condition holds.'));
  for(const guard of stage.guards||[])host.append(el('p','workflow-context-data',workflowGuardText(guard)));
  if(runsLater(stage))host.append(el('p','workflow-intro','This body runs later, if at all; creating it does not run it.'));
  if(stage.reason && stage.status!=='supported')host.append(el('p','workflow-intro',stage.reason));
  if(stage.construction)host.append(el('p','workflow-intro','Constructing an object runs its initializer, not its class body.'));
  const candidates=stage.construction?(stage.constructorCandidates||[]):stage.status==='possible'?methods:[];
  if(candidates.length) {
    const group=el('div','workflow-candidates');
    group.append(el('p','',stage.construction?'Creating it probably runs:':'Probably calls one of:'));
    for(const id of candidates)group.append(button('Go to '+(stage.targetLabels?.[id]||model.scopes[id]?.qualified||id)+' →','workflow-method',()=>openWorkflowCandidate(stage,id)));
    host.append(group);
  }
  const why=el('div','workflow-why');
  if(stage.candidateEvidence?.length) why.append(button('Why is this receiver a candidate?','workflow-link-evidence',()=>inspectWorkflowEvidence('Why this receiver','The source suggests this type. What actually runs can differ.',stage.candidateEvidence)));
  const link=workflow.links.find(item=>item.to===stage.id);
  if(link) why.append(button('Why is this linked?','workflow-link-evidence',()=>inspectWorkflowLink(link)));
  if(stage.construction && stage.scope) why.append(button('Go to class →','scope-jump',()=>openWorkflowCandidate(stage,stage.scope)));
  if(why.childNodes.length)host.append(why);
  if(!methods.includes(state.scope)) host.append(el('div','workflow-inspected-method',stage.callsite&&state.scope===(stage.callerScope||stage.evidence?.[0]?.scope)?'Showing '+scopeName(state.scope)+', where this call is written.':'The call map still has '+stage.label+' selected.'));
}
function syncWorkflowMethod() {
  if(workflowState.initialized&&workflowState.mode==='workflow') renderWorkflowContext();
}
function inspectWorkflowLink(link) {
  const kind=link.kind==='possible_event'?'Probable event route':'Call';
  inspectWorkflowEvidence(link.label,kind+' · '+certaintyLabel(link.status)+'\n'+link.description+(link.data?'\nPasses: '+link.data:''),link.evidence);
}
function inspectWorkflowEvidence(title,description,evidence) {
  const previousScroll=$('.review').scrollTop;renderWorkflowContext();
  const box=el('div','workflow-evidence'),head=el('div','workflow-evidence-head');head.append(el('strong','',title),button('Close','workflow-close',()=>{renderWorkflowContext();$('.review').scrollTop=previousScroll;}));box.append(head,el('p','',description));
  const list=el('div','workflow-evidence-list');
  for(const proof of evidence) list.append(button(proof.label+' · L'+proof.span.start,'workflow-evidence-item',()=>{showSource(proof.span,title,proof.label+'\n'+description);list.querySelectorAll('button').forEach(b=>b.classList.remove('active'));announce(proof.label);}));
  box.append(list);if(!evidence.length)box.append(el('p','status unknown','No verified evidence in this snapshot.'));
  $('#workflowContext').append(box);$('.review').scrollTop=0;if(evidence.length)showSource(evidence[0].span,title,evidence[0].label+'\n'+description);
}
$('#workflowTab').addEventListener('click',showSelectedWorkflow);
$('#changesTab').addEventListener('click',()=>setWorkflowMode('changes'));
$('#endpointsTab').addEventListener('click',()=>showStartPage('endpoints'));
$('#commandsTab').addEventListener('click',()=>showStartPage('commands'));
$('#methodsTab').addEventListener('click',()=>showStartPage('methods'));
