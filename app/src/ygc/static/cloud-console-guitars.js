// Console data access remains separate from Operations availability.
export function createGuitarBrowser({request,authorized,onUnauthorized}){
  const $=id=>document.getElementById(id),t=(key,params={})=>YGCI18n.t(key,params);
  let busy=false,epoch=0,next=null,history=[0],query='',selectedId=null,claimNext=null,claimHistory=[0];
  let pending=null;
  const dialog=document.createElement('dialog');dialog.id='claimDecisionDialog';
  const title=document.createElement('h2'),description=document.createElement('p'),selection=document.createElement('select'),confirm=document.createElement('button'),cancel=document.createElement('button');
  selection.id='claimDecisionValue';confirm.id='claimDecisionConfirm';cancel.id='claimDecisionCancel';
  dialog.append(title,description,selection,confirm,cancel);document.body.append(dialog);
  const decisionStatus=document.createElement('p');decisionStatus.id='claimDecisionStatus';decisionStatus.setAttribute('role','status');$('chroniclePanel').append(decisionStatus);
  function closeDecision(){globalThis.YGCOverlays.close(dialog);pending=null}
  dialog.addEventListener('ygc:closed',()=>{pending=null});
  cancel.onclick=closeDecision;
  function decide(row){
    if(busy||!authorized())return;
    pending={individual:selectedId,claim:row.id,revision:row.revision};
    title.textContent=t('chronicle.admin_decision');description.textContent=t('chronicle.decision_warning',{id:row.id,state:t('chronicle.'+row.verification_status)});
    selection.replaceChildren();for(const state of ['positive','negative','unverified']){const option=document.createElement('option');option.value=state;option.textContent=t('chronicle.'+state);selection.append(option)}
    selection.value=row.verification_status;selection.setAttribute('aria-label',t('chronicle.admin_decision'));
    confirm.textContent=t('chronicle.apply_decision');cancel.textContent=t('chronicle.cancel_decision');
    globalThis.YGCOverlays.open(dialog,{initialFocus:'#claimDecisionValue'});
  }
  confirm.onclick=()=>{
    if(!pending||busy||!authorized())return;
    const saved={...pending,action:selection.value};closeDecision();
    action(async current=>{
      try{
        await request('/api/admin/guitars/'+saved.individual+'/claims/'+saved.claim+'/verification',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:saved.action,revision:saved.revision})});
        if(current!==epoch)return;
        await page(current);await loadDetail(saved.individual,current,false);
        if(current===epoch)decisionStatus.textContent=t('chronicle.decision_saved');
      }catch(error){
        if(current!==epoch)return;
        if([401,403].includes(error.status)){clear();onUnauthorized(error)}
        decisionStatus.textContent=t(error.status===409?'chronicle.decision_conflict':'chronicle.decision_unavailable');
      }
    });
  };
  const fields=['id','manufacturer','model','finish','year','serial_number','location_country','location_region','current_owner_name','current_owner_type'];
  function render(){
    $('guitarBrowser').hidden=$('cloudProductDetail').hidden=!authorized();
    for(const id of ['guitarSearch','guitarSearchSubmit','guitarRefresh'])$(id).disabled=busy||!authorized();
    $('guitarPrevious').disabled=busy||!authorized()||history.length<2;
    $('guitarNext').disabled=busy||!authorized()||next===null;
    $('chroniclePanel').hidden=!authorized()||selectedId===null;
    $('chronicleRefresh').disabled=busy||!authorized()||selectedId===null;
    $('chroniclePrevious').disabled=busy||!authorized()||claimHistory.length<2;
    $('chronicleNext').disabled=busy||!authorized()||claimNext===null;
    for(const button of document.querySelectorAll('#guitarRows button,#chronicleRows button'))button.disabled=busy||!authorized();
  }
  function clear(){closeDecision();decisionStatus.textContent='';selectedId=null;claimNext=null;claimHistory=[0];$('chronicleRows').replaceChildren();$('chronicleStatus').textContent='';epoch++;next=null;history=[0];query='';$('guitarRows').replaceChildren();$('guitarDetailFields').replaceChildren();$('guitarStatus').textContent='';$('guitarSearch').value='';$('guitarDetailEmpty').hidden=false;render()}
  function failed(error){
    selectedId=null;claimNext=null;$('chronicleRows').replaceChildren();$('chronicleStatus').textContent='';
    $('guitarRows').replaceChildren();$('guitarDetailFields').replaceChildren();$('guitarDetailEmpty').hidden=false;next=null;
    if([401,403].includes(error.status)){clear();onUnauthorized(error)}
    $('guitarStatus').textContent=t(error.status===404?'guitars.missing':'guitars.unavailable');
  }
  async function action(work){
    if(busy||!authorized())return;
    busy=true;const current=++epoch;render();
    try{await work(current)}catch(error){if(current===epoch)failed(error)}finally{busy=false;render()}
  }
  async function page(current){
    const params=new URLSearchParams({q:query,limit:'25'}),after=history.at(-1);if(after)params.set('after',String(after));
    const result=await request('/api/admin/guitars?'+params);
    if(current!==epoch)return;
    if(typeof result.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(result.total)||!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||typeof result.next_after==='string'&&/^[1-9][0-9]*$/.test(result.next_after)))throw Error('Invalid page');
    $('guitarRows').replaceChildren();next=result.next_after;
    for(const row of result.items){
      const tr=document.createElement('tr');
      for(const field of ['manufacturer','model','year','serial_number']){const td=document.createElement('td');td.textContent=row[field]??'—';tr.append(td)}
      const td=document.createElement('td'),button=document.createElement('button');button.textContent=t('action.detail');button.onclick=()=>detail(row.id);td.append(button);tr.append(td);$('guitarRows').append(tr);
    }
    $('guitarStatus').textContent=t('guitars.total_count',{count:result.total});
  }
  async function chronicle(current){
    const params=new URLSearchParams({limit:'25'}),after=claimHistory.at(-1);if(after)params.set('after',after);
    const result=await request('/api/admin/guitars/'+selectedId+'/chronicle?'+params);
    if(current!==epoch)return;
    if(typeof result.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(result.total)||!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||typeof result.next_after==='string'&&/^[1-9][0-9]*$/.test(result.next_after)))throw Error('Invalid Chronicle');
    claimNext=result.next_after;$('chronicleRows').replaceChildren();
    for(const row of result.items){
      const card=document.createElement('details'),summary=document.createElement('summary');
      const state=['positive','negative','unverified'].includes(row.verification_status)?row.verification_status:'unverified';
      card.className='chronicle-record '+state+(row.effective_status!=='active'?' inactive':'');
      card.open=state==='positive'&&row.effective_status==='active';
      const key='chronicle.type_'+row.claim_type,label=t(key),type=label===key?row.claim_type:label,name=row.ownership_kind?type+' / '+row.ownership_kind:type;
      summary.textContent=state==='negative'?'●':name+(row.effective_status!=='active'?' · '+t('chronicle.inactive'):'');
      summary.setAttribute('aria-label',name+' · '+t('chronicle.'+state));summary.title=name;
      card.append(summary);
      const meta=document.createElement('p');meta.textContent='#'+row.id+' · '+(row.occurred_at||row.created_at||'—')+' · '+(row.author_name||'—')+' · '+t('chronicle.'+state)+(row.effective_status!=='active'?' · '+t('chronicle.inactive'):'');card.append(meta);
      const values=document.createElement('dl');
      for(const item of [{field_name:row.field_name,value_text:row.value_text},...(row.items||[])]){if(!item.field_name||!item.value_text)continue;const dt=document.createElement('dt'),dd=document.createElement('dd');const key='guitars.field_'+item.field_name;const label=t(key);dt.textContent=label===key?item.field_name:label;dd.textContent=item.value_text;values.append(dt,dd)}
      card.append(values);if(row.body){const body=document.createElement('p');body.textContent=row.body;card.append(body)}if(typeof row.revision==='string'&&/^[0-9a-f]{64}$/.test(row.revision)){
        const button=document.createElement('button');button.className='claim-admin-decision';button.textContent=t('chronicle.admin_decision');button.onclick=()=>decide(row);card.append(button);
      }$('chronicleRows').append(card);
    }
    $('chronicleStatus').textContent=t(result.total==='0'?'chronicle.empty':'chronicle.total',{count:result.total});
  }
  function refresh(){return action(page)}
  async function loadDetail(id,current,jump=true){
    closeDecision();decisionStatus.textContent='';
    if(typeof id!=='string'||!/^[1-9][0-9]*$/.test(id))throw Error('Invalid identifier');
    const row=await request('/api/admin/guitars/'+id);
    if(current!==epoch)return;
    $('guitarDetailFields').replaceChildren();
    for(const field of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t('guitars.field_'+field);dd.textContent=row[field]??'—';$('guitarDetailFields').append(dt,dd)}
    selectedId=id;claimNext=null;claimHistory=[0];$('chronicleRows').replaceChildren();$('chronicleStatus').textContent='';render();await chronicle(current);if(current!==epoch)return;
    $('guitarDetailEmpty').hidden=true;if(jump)$('cloudProductDetail').scrollIntoView({block:'start'});
  }
  function detail(id){return action(current=>loadDetail(id,current))}
  $('guitarSearchForm').onsubmit=event=>{event.preventDefault();if(busy)return;query=$('guitarSearch').value.trim();history=[0];refresh()};
  $('guitarRefresh').onclick=()=>refresh();
  $('guitarNext').onclick=()=>{if(busy||next===null)return;history.push(next);refresh()};
  $('guitarPrevious').onclick=()=>{if(busy||history.length<2)return;history.pop();refresh()};
  $('chronicleRefresh').onclick=()=>{if(selectedId!==null){claimHistory=[0];action(chronicle)}};
  $('chronicleNext').onclick=()=>{if(busy||claimNext===null)return;claimHistory.push(claimNext);action(chronicle)};
  $('chroniclePrevious').onclick=()=>{if(busy||claimHistory.length<2)return;claimHistory.pop();action(chronicle)};
  return {render,clear,refresh,detail};
}
