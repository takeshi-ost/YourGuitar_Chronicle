// Console data access remains separate from Operations availability.
export function createGuitarBrowser({request,authorized,onUnauthorized}){
  const $=id=>document.getElementById(id),t=(key,params={})=>YGCI18n.t(key,params);
  let busy=false,epoch=0,next=null,history=[0],query='',selectedId=null,claimNext=null,claimHistory=[0];
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
    for(const button of $('guitarRows').querySelectorAll('button'))button.disabled=busy;
  }
  function clear(){selectedId=null;claimNext=null;claimHistory=[0];$('chronicleRows').replaceChildren();$('chronicleStatus').textContent='';epoch++;next=null;history=[0];query='';$('guitarRows').replaceChildren();$('guitarDetailFields').replaceChildren();$('guitarStatus').textContent='';$('guitarSearch').value='';$('guitarDetailEmpty').hidden=false;render()}
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
      card.append(values);if(row.body){const body=document.createElement('p');body.textContent=row.body;card.append(body)}$('chronicleRows').append(card);
    }
    $('chronicleStatus').textContent=t(result.total==='0'?'chronicle.empty':'chronicle.total',{count:result.total});
  }
  function refresh(){return action(page)}
  function detail(id){return action(async current=>{
    if(typeof id!=='string'||!/^[1-9][0-9]*$/.test(id))throw Error('Invalid identifier');
    const row=await request('/api/admin/guitars/'+id);
    if(current!==epoch)return;
    $('guitarDetailFields').replaceChildren();
    for(const field of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t('guitars.field_'+field);dd.textContent=row[field]??'—';$('guitarDetailFields').append(dt,dd)}
    selectedId=id;claimNext=null;claimHistory=[0];$('chronicleRows').replaceChildren();$('chronicleStatus').textContent='';render();await chronicle(current);if(current!==epoch)return;
    $('guitarDetailEmpty').hidden=true;$('cloudProductDetail').scrollIntoView({block:'start'});
  })}
  $('guitarSearchForm').onsubmit=event=>{event.preventDefault();if(busy)return;query=$('guitarSearch').value.trim();history=[0];refresh()};
  $('guitarRefresh').onclick=()=>refresh();
  $('guitarNext').onclick=()=>{if(busy||next===null)return;history.push(next);refresh()};
  $('guitarPrevious').onclick=()=>{if(busy||history.length<2)return;history.pop();refresh()};
  $('chronicleRefresh').onclick=()=>{if(selectedId!==null){claimHistory=[0];action(chronicle)}};
  $('chronicleNext').onclick=()=>{if(busy||claimNext===null)return;claimHistory.push(claimNext);action(chronicle)};
  $('chroniclePrevious').onclick=()=>{if(busy||claimHistory.length<2)return;claimHistory.pop();action(chronicle)};
  return {render,clear,refresh};
}
