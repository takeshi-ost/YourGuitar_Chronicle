// Console data access remains separate from Operations availability.
export function createGuitarBrowser({request,authorized,onUnauthorized}){
  const $=id=>document.getElementById(id),t=(key,params={})=>YGCI18n.t(key,params);
  let busy=false,epoch=0,next=null,history=[0],query='';
  const fields=['id','manufacturer','model','finish','year','serial_number','location_country','location_region','current_owner_name','current_owner_type'];
  function render(){
    $('guitarBrowser').hidden=$('cloudProductDetail').hidden=!authorized();
    for(const id of ['guitarSearch','guitarSearchSubmit','guitarRefresh'])$(id).disabled=busy||!authorized();
    $('guitarPrevious').disabled=busy||!authorized()||history.length<2;
    $('guitarNext').disabled=busy||!authorized()||next===null;
    for(const button of $('guitarRows').querySelectorAll('button'))button.disabled=busy;
  }
  function clear(){epoch++;next=null;history=[0];query='';$('guitarRows').replaceChildren();$('guitarDetailFields').replaceChildren();$('guitarStatus').textContent='';$('guitarSearch').value='';$('guitarDetailEmpty').hidden=false;render()}
  function failed(error){
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
    if(!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||typeof result.next_after==='string'&&/^[1-9][0-9]*$/.test(result.next_after)))throw Error('Invalid page');
    $('guitarRows').replaceChildren();next=result.next_after;
    for(const row of result.items){
      const tr=document.createElement('tr');
      for(const field of ['manufacturer','model','year','serial_number']){const td=document.createElement('td');td.textContent=row[field]??'—';tr.append(td)}
      const td=document.createElement('td'),button=document.createElement('button');button.textContent=t('action.detail');button.onclick=()=>detail(row.id);td.append(button);tr.append(td);$('guitarRows').append(tr);
    }
    $('guitarStatus').textContent=result.items.length?t('guitars.page_count',{count:result.items.length}):t('guitars.empty');
  }
  function refresh(){return action(page)}
  function detail(id){return action(async current=>{
    if(typeof id!=='string'||!/^[1-9][0-9]*$/.test(id))throw Error('Invalid identifier');
    const row=await request('/api/admin/guitars/'+id);
    if(current!==epoch)return;
    $('guitarDetailFields').replaceChildren();
    for(const field of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t('guitars.field_'+field);dd.textContent=row[field]??'—';$('guitarDetailFields').append(dt,dd)}
    $('guitarDetailEmpty').hidden=true;$('cloudProductDetail').scrollIntoView({block:'start'});
  })}
  $('guitarSearchForm').onsubmit=event=>{event.preventDefault();if(busy)return;query=$('guitarSearch').value.trim();history=[0];refresh()};
  $('guitarRefresh').onclick=()=>refresh();
  $('guitarNext').onclick=()=>{if(busy||next===null)return;history.push(next);refresh()};
  $('guitarPrevious').onclick=()=>{if(busy||history.length<2)return;history.pop();refresh()};
  return {render,clear,refresh};
}
