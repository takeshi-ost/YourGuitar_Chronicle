export function createCrawlBrowser({request,authorized,onUnauthorized}){
 const $=id=>document.getElementById(id),t=k=>YGCI18n.t(k);
 let busy=false,epoch=0,timer=null,available=false,pending=false;
 function render(){
  $('cloudCrawl').hidden=!authorized();
  for(const id of ['crawlNow','crawlConfigSave','crawlAuto','crawlYearMin','crawlYearMax','crawlInterval'])$(id).disabled=busy||pending||!available||!authorized();
  $('crawlAuto').disabled=busy||!available||!authorized();
  $('crawlRefresh').disabled=busy||!authorized();
 }
 function clear(){epoch++;clearTimeout(timer);timer=null;available=false;pending=false;$('crawlRows').replaceChildren();$('crawlStatus').textContent='';$('crawlLastAt').textContent='—';render()}
 function display(row){
  available=row.available===true;$('crawlAuto').checked=row.enabled;
  $('crawlYearMin').value=row.year_min;$('crawlYearMax').value=row.year_max;$('crawlInterval').value=row.interval_hours;
  $('crawlLastAt').textContent=row.last_at||'—';
  pending=['starting','running','unknown'].includes(row.request.state)&&!row.request.retry_allowed;
  $('crawlStatus').textContent=t(!available?'crawl.unavailable':row.request.state==='idle'?'crawl.ready':'crawl.'+row.request.state);
  $('crawlRows').replaceChildren();
  for(const item of row.runs){const tr=document.createElement('tr');for(const value of [item.started_at,item.status,item.phase||'',item.pages_discovered,item.pages_fetched,item.observations_created]){const td=document.createElement('td');td.textContent=String(value??'');tr.append(td)}$('crawlRows').append(tr)}
  if(pending&&authorized())timer=setTimeout(()=>refresh(),5000);render();
 }
 async function refresh(){
  if(busy||!authorized())return;clearTimeout(timer);timer=null;busy=true;const current=++epoch;render();
  try{const row=await request('/api/admin/crawl');if(current===epoch)display(row)}
  catch(error){if(current!==epoch)return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else $('crawlStatus').textContent=t('crawl.failed')}
  finally{busy=false;render()}
 }
 async function action(path,payload,method){
  if(busy||(pending&&method==='POST')||!available||!authorized())return;clearTimeout(timer);busy=true;const current=++epoch;render();
  try{await request(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(current!==epoch)return;busy=false;await refresh()}
  catch(error){if(current!==epoch)return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else{$('crawlStatus').textContent=t(error.status===409?'crawl.busy':'crawl.unknown');timer=setTimeout(()=>refresh(),5000)}}
  finally{busy=false;render()}
 }
 function config(){return {year_min:Number($('crawlYearMin').value),year_max:Number($('crawlYearMax').value),interval_hours:Number($('crawlInterval').value),enabled:$('crawlAuto').checked}}
 $('crawlConfig').onsubmit=event=>{event.preventDefault();action('/api/admin/crawl',config(),'PUT')};
 $('crawlAuto').onchange=()=>{if(!$('crawlConfig').checkValidity()){ $('crawlAuto').checked=!$('crawlAuto').checked;return;}action('/api/admin/crawl',config(),'PUT')};
 $('crawlNow').onclick=()=>{if(!$('crawlConfig').reportValidity())return;const row=config();action('/api/admin/crawl/start',{year_min:row.year_min,year_max:row.year_max,request_id:crypto.randomUUID()},'POST')};
 $('crawlRefresh').onclick=()=>refresh();return {render,clear,refresh};
}
