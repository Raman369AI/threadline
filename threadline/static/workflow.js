/* Cross-file workflow for the currently selected method. */
const workflowState = { mode:'starts', profile:null, stage:null, initialized:false };

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
  host.append(el('h2','workflow-title',workflow.title),el('p','workflow-intro',workflow.description||'Select a step to inspect its logic and original source.'));
  if(!workflow.stages.length){host.append(button('Build workflow for selected method →','workflow-primary-action',showSelectedWorkflow));host.scrollTop=scroll;return;}
  const list=el('div','workflow-stages');
  for(const [index,stage] of workflow.stages.entries()){
    if(stage.parent){
      const link=workflow.links.find(item=>item.to===stage.id),parent=workflow.stages.find(item=>item.id===stage.parent),group=el('div','workflow-nested-step');
      group.style.marginLeft=Math.min(stage.depth||1,3)*6+'px';
      group.append(el('div','workflow-nest-label',(link?.kind==='possible_event'?'⋯ possible event route':'↳ called inside '+(parent?.label||'selected method'))),stageButton(stage,index));
      if(link) group.append(button('Inspect connection evidence','workflow-link-evidence',()=>inspectWorkflowLink(link)));
      list.append(group);
    }else list.append(stageButton(stage,index));
  }
  host.append(list);
  host.append(el('p','source-peek',workflow.stages.length+' of '+workflow.totalStages+' steps · '+workflow.alternatives.length+' of '+workflow.totalAlternatives+' alternatives · '+workflow.uncertainties.length+' of '+workflow.totalUncertainties+' uncertainty records'));
  if(workflow.nextCursor!==null) {
    const more=button(workflow.loading?'Loading…':'Load more workflow details','quiet-button',loadMoreWorkflow);
    more.disabled=Boolean(workflow.loading);host.append(more);
  }
  for(const [label,rows] of [['Control-flow alternatives',workflow.alternatives],['Uncertainty details',workflow.uncertainties]]) {
    if(!rows.length) continue;
    const details=el('details','workflow-provenance');details.append(el('summary','',label));
    for(const row of rows) details.append(button(row.label || row.reason,'workflow-link-evidence',()=>showSource(row.span,label,row.reason || row.arms.join(' / '))));
    host.append(details);
  }
  if(workflow.truncated) host.append(el('p','status unknown',workflow.omitted+' call sites or nested expansions omitted by safety limits (500 stages / 100 call levels).'));
  const note=el('details','workflow-provenance');note.append(el('summary','','How this workflow was built'),el('p','',workflow.provenance));host.append(note);
  host.scrollTop=scroll;
}
function stageButton(stage,index) {
  const scope=model.scopes[stage.scope],b=button('','workflow-stage'+(stage.id===workflowState.stage?' active':''),()=>selectWorkflowStage(stage.id));
  b.title=stage.condition+' · '+(scope?.qualified||stage.label);b.dataset.stage=stage.id;b.setAttribute('aria-pressed',String(stage.id===workflowState.stage));
  b.append(el('span','workflow-stage-number',String(index+1).padStart(2,'0')),el('strong','workflow-stage-title',stage.label),el('code','workflow-stage-method',scope?.qualified||stage.label),...(stage.parent?[el('span','workflow-stage-data',stage.data)]:[]),el('span','workflow-stage-condition',stage.condition));
  if(stage.moduleLink)b.append(el('span','workflow-module-link',stage.moduleLink.from+' → '+stage.moduleLink.to));
  if(stage.status&&!['supported','source-linked'].includes(stage.status)) b.append(el('span','status '+stage.status,stage.status==='possible'?'Possible target':stage.status==='unknown'?'Unknown target':stage.status==='external'?'External target':stage.status));
  return b;
}
async function selectWorkflowStage(id) {
  const stage=workflowState.profile?.stages.find(s=>s.id===id);if(!stage)return;
  workflowState.stage=id;
  $('#workflowBrowser').querySelectorAll('.workflow-stage').forEach(b=>{b.classList.toggle('active',b.dataset.stage===id);b.setAttribute('aria-pressed',String(b.dataset.stage===id));});
  if(!await chooseScope(stage.scope))return;renderWorkflowContext();
  if(stage.callsite&&stage.evidence?.length) showSource(stage.evidence[0].span,stage.label,stage.condition);
  announce('Workflow stage: '+stage.label);
}
function renderWorkflowContext() {
  const host=$('#workflowContext'),relatedOpen=Boolean(host.querySelector('.related-methods')?.open);host.replaceChildren();
  const workflow=workflowState.profile,stage=workflow?.stages.find(s=>s.id===workflowState.stage);if(!stage)return;
  const index=workflow.stages.indexOf(stage);host.append(el('div','workflow-context-kicker','STEP '+(index+1)+' OF '+workflow.stages.length+' · '+stage.label));
  if(stage.methods.includes(state.scope)&&state.scope===stage.scope) $('#scopeTitle').textContent=stage.label;
  if(stage.methods.length>1){
    const related=el('details','related-methods');related.open=relatedOpen;related.append(el('summary','','Possible methods ('+stage.methods.length+')'));
    const methods=el('div','workflow-stage-methods');
    for(const id of stage.methods){const b=button(model.scopes[id]?.qualified||id,'workflow-method'+(state.scope===id?' active':''),()=>chooseScope(id));b.dataset.scope=id;methods.append(b);}
    related.append(methods);host.append(related);
  }
  if(!stage.methods.includes(state.scope)) host.append(el('div','workflow-inspected-method','Reading '+scopeName(state.scope)+' · '+stage.label+' stays selected.'));
}
function syncWorkflowMethod() {
  if(workflowState.initialized&&workflowState.mode==='workflow') renderWorkflowContext();
}
function inspectWorkflowLink(link) {
  const kind=link.kind==='possible_event'?'POSSIBLE EVENT ROUTE':'CALL SITE';
  inspectWorkflowEvidence(link.label,link.description+'\nData: '+link.data+'\nConnection type: '+kind+' · '+link.status,link.evidence);
}
function inspectWorkflowEvidence(title,description,evidence) {
  const previousScroll=$('.review').scrollTop;renderWorkflowContext();
  const box=el('div','workflow-evidence'),head=el('div','workflow-evidence-head');head.append(el('strong','',title),button('Close evidence','workflow-close',()=>{renderWorkflowContext();$('.review').scrollTop=previousScroll;}));box.append(head,el('p','',description));
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
