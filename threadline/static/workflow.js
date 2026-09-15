/* Cross-file workflow for the currently selected method. */
const workflowState = { mode:'methods', profile:null, stage:null, initialized:false };

async function initializeWorkflows(refresh=false) {
  if(!state.scope || !model.scopes[state.scope]) return;
  workflowState.profile=await loadCallWorkflow(state.scope);
  workflowState.stage=workflowState.profile.stages.find(s=>s.id===workflowState.stage)?.id || workflowState.profile.stages[0]?.id;
  const firstLoad=!workflowState.initialized;
  workflowState.initialized=true;
  if(firstLoad) setWorkflowMode('workflow');
  else {renderWorkflow();setWorkflowMode(workflowState.mode);}
  if(firstLoad && workflowState.stage) await selectWorkflowStage(workflowState.stage);
  if(!refresh && firstLoad && new URLSearchParams(location.search).get('trace')==='1') showSelectedWorkflow();
}
function setWorkflowMode(mode) {
  workflowState.mode=mode;
  $('#repositoryBrowser').hidden=mode==='workflow';
  $('#workflowBrowser').hidden=mode!=='workflow';
  $('#workflowContext').hidden=mode!=='workflow';
  $('.workspace').classList.toggle('workflow-mode',mode==='workflow');
  $('#workflowTab').setAttribute('aria-pressed',String(mode==='workflow'));
  $('#methodsTab').setAttribute('aria-pressed',String(mode==='methods'));
  if(mode==='workflow'){renderWorkflow();renderWorkflowContext();}
}
function makeCallWorkflow(scopeId) {
  return model.generatedWorkflows?.[scopeId] || {id:'entrypoint-calls',title:'Workflow for selected method',description:'',provenance:'Generated from source syntax.',stages:[],links:[],outcomes:[],nested:true};
}
async function loadCallWorkflow(scopeId) {
  const captured=model;
  if(captured.generatedWorkflows?.[scopeId]) return captured.generatedWorkflows[scopeId];
  let cursor=0,workflow=null,stages=[],links=[],alternatives=[],uncertainties=[];
  do {
    const url='/api/workflow?entrypoint='+encodeURIComponent(scopeId)+'&snapshot='+encodeURIComponent(captured.snapshotId)+'&cursor='+cursor+'&limit=100';
    const response=await fetch(url);
    if(!response.ok) throw new Error((await response.json()).error||'Unable to build workflow');
    const page=await response.json();
    if(!workflow) workflow=page;
    stages.push(...page.stages.items);links.push(...page.links);alternatives.push(...(page.alternatives?.items||[]));uncertainties.push(...(page.uncertainties?.items||[]));cursor=page.stages.nextCursor ?? page.alternatives?.nextCursor ?? page.uncertainties?.nextCursor ?? null;
  } while(cursor!==null);
  workflow.stages=stages;workflow.links=links;workflow.alternatives=alternatives;workflow.uncertainties=uncertainties;
  captured.generatedWorkflows ||= {};captured.generatedWorkflows[scopeId]=workflow;
  return workflow;
}
async function showSelectedWorkflow() {
  const selected=state.scope, captured=model;
  announce('Building workflow…');
  try {
    const profile=await loadCallWorkflow(selected);
    if(captured!==model || selected!==state.scope)return;
    workflowState.profile=profile;workflowState.stage='entry';
    setWorkflowMode('workflow');renderWorkflow();await selectWorkflowStage('entry');announce('Workflow ready.');
  } catch(error){announce(error.message);}
}
function renderWorkflow() {
  const host=$('#workflowBrowser'),scroll=host.scrollTop;host.replaceChildren();
  const workflow=workflowState.profile;if(!workflow)return;
  if(model.changes?.changedMethods?.length){
    const changed=el('details','workflow-changes');changed.open=true;changed.append(el('summary','',model.changes.changedMethods.length+' changed methods · '+model.changes.base));
    for(const item of model.changes.changedMethods) changed.append(button(item.name+' · '+item.file+':'+item.span.start,'workflow-change',async()=>{await chooseScope(item.id);await showSelectedWorkflow();}));
    host.append(changed);
  }
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
  if(workflow.truncated) host.append(el('p','status unknown',workflow.omitted+' call sites or nested expansions omitted by safety limits (500 stages / 100 call levels).'));
  const note=el('details','workflow-provenance');note.append(el('summary','','How this workflow was built'),el('p','',workflow.provenance));host.append(note);
  host.scrollTop=scroll;
}
function stageButton(stage,index) {
  const scope=model.scopes[stage.scope],b=button('','workflow-stage'+(stage.id===workflowState.stage?' active':''),()=>selectWorkflowStage(stage.id));
  b.title=stage.condition+' · '+(scope?.qualified||stage.label);b.dataset.stage=stage.id;b.setAttribute('aria-pressed',String(stage.id===workflowState.stage));
  b.append(el('span','workflow-stage-number',String(index+1).padStart(2,'0')),el('strong','workflow-stage-title',stage.label),el('code','workflow-stage-method',scope?.qualified||stage.label),...(stage.parent?[el('span','workflow-stage-data',stage.data)]:[]),el('span','workflow-stage-condition',stage.condition));
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
$('#methodsTab').addEventListener('click',()=>setWorkflowMode('methods'));
