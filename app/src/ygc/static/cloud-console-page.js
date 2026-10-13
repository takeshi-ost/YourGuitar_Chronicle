import {createAuthDialog,authLabel} from './cloud-auth-dialog.js';
import {createDisputes} from './cloud-account-disputes.js';
import {createApplicationBrowser} from './cloud-console-applications.js';
import {createUserBrowser} from './cloud-console-users.js';
import {createCrawlBrowser} from './cloud-console-crawl.js';
import {createBackupBrowser} from './cloud-console-backups.js';
import {createGuitarBrowser} from './cloud-console-guitars.js';
import {loadCloudAuth} from './cloud-auth-loader.js';
const $=id=>document.getElementById(id),t=key=>globalThis.YGCI18n.t(key);
const modes={normal:'ui.normal_a7248eeb',read_only:'ui.read_only_8ac76735',offline:'ui.offline_a1794783',admin_only:'console.admin_only'};
const defaultMessage=mode=>mode==='normal'?'':t('console.default_'+mode);
const authDialog=createAuthDialog({auth:()=>auth,onAuthenticated:result=>{if(result?.identity?.email_verified===true)location.reload()}});
$('consoleSignIn').textContent=authLabel();$('consoleSignIn').removeAttribute('data-i18n');$('consoleSignIn').onclick=event=>{event.preventDefault();authDialog.open({opener:event.currentTarget})};
let auth,settings=null,reviewState=null,reviewPending=null,authorized=false,busy=false,sessionEpoch=0;
const disputes=createDisputes({auth:()=>auth,state:()=>authorized?auth?.account:null,busy:()=>busy,work:action,admin:true,onUnauthorized:error,updated:()=>guitars.refresh()});
const backups=createBackupBrowser({request,authorized:()=>authorized,onUnauthorized:error,maintenanceMode:()=>!!settings&&settings.mode!=='normal'});
const crawl=createCrawlBrowser({request,authorized:()=>authorized,onUnauthorized:error});
const guitars=createGuitarBrowser({request,authorized:()=>authorized,onUnauthorized:error,auth:()=>auth,state:()=>authorized?auth?.account:null});
const applications=createApplicationBrowser({request,authorized:()=>authorized,onUnauthorized:error,onGuitar:id=>guitars.detail(id)});
$('consoleStatus').removeAttribute('data-i18n');
const users=createUserBrowser({request,authorized:()=>authorized,onUnauthorized:error,onGuitar:id=>guitars.detail(id)});
function controls(){
  disputes.render();applications.render();users.render();guitars.render();backups.render();crawl.render();
  $('consoleControls').hidden=!authorized;
  $('consoleRefresh').disabled=busy||!authorized;
  $('reviewToggle').disabled=busy||!authorized||reviewState===null;
  $('reviewConfirm').disabled=busy||!authorized||!reviewPending;
  $('operationsSave').disabled=busy||!authorized||!settings;
  $('operationsMode').disabled=$('operationsMessage').disabled=busy||!authorized||!settings;
  $('consoleSignOut').hidden=!auth?.signedIn;
  $('consoleSignOut').disabled=busy;
}
function clear(){sessionEpoch++;reviewState=null;reviewPending=null;globalThis.YGCOverlays.close($('reviewDialog'));$('reviewStatus').textContent='—';authorized=false;disputes.clear();applications.clear();users.clear();guitars.clear();backups.clear();crawl.clear();settings=null;$('operationsStatus').textContent='—';$('operationsMessage').value='';$('consoleIdentity').textContent='';controls()}
function error(error){
  settings=null;reviewState=null;
  if([401,403].includes(error.status)||error.code==='sign_in_required')clear();
  $('consoleStatus').textContent=t(error.status===409?'console.conflict':error.status===403?'console.admin_required':error.status===401||error.code==='sign_in_required'?'console.sign_in_required':'console.unavailable');
  controls();
}
async function request(path,options={},binary=false){
  const version=sessionEpoch,actor=auth?.account?.user?.app_user_id;
  const response=await auth.authorizedFetch(path,{...options,cache:'no-store'},Boolean(options.method&&!['GET','HEAD'].includes(options.method.toUpperCase())));
  if(version!==sessionEpoch||actor!==auth?.account?.user?.app_user_id)throw Object.assign(Error('Session changed'),{code:'stale_context'});
  if(!response.ok){let code;try{const body=await response.json();code=body.detail?.code}catch{}throw Object.assign(Error('Operation unavailable'),{status:response.status,code})}
  if(binary){if(!response.headers.get('Content-Type')?.startsWith('image/jpeg'))throw Error('Unexpected image');const blob=await response.blob();if(blob.size>25*1024*1024)throw Error('Image too large');return blob}
  const value=await response.json();
  if(version!==sessionEpoch||actor!==auth?.account?.user?.app_user_id)throw Object.assign(Error('Session changed'),{code:'stale_context'});
  return value;
}
function display(row){
  if(!row||!Object.hasOwn(modes,row.mode)||typeof row.message!=='string'||!Number.isInteger(row.version)||row.version<0)throw Error('Invalid service state');
  settings=row;
  $('operationsStatus').textContent=t(modes[row.mode]);
  $('operationsMode').value=row.mode;
  $('operationsMessage').value=row.message||defaultMessage(row.mode);
}
async function refreshDiagnostics(version=sessionEpoch){
  const current=()=>version===sessionEpoch&&authorized;
  try{
    const ready=await fetch('/ready',{cache:'no-store',credentials:'omit',redirect:'error'});
    if(current())$('databaseStatus').textContent=t(ready.ok?'console.connected':'console.unavailable');
  }catch{if(current())$('databaseStatus').textContent=t('console.unavailable')}
  if(!current())return;
  try{
    const storage=await request('/api/admin/operations/storage');
    if(!current())return;
    for(const scope of ['content','accounts'])$(scope+'StorageStatus').textContent=t(storage[scope]==='available'?'console.storage_readable':'console.unavailable');
  }catch(e){
    if(!current())return;
    if([401,403].includes(e.status)){error(e);return;}
    for(const scope of ['content','accounts'])$(scope+'StorageStatus').textContent=t('console.unavailable');
  }
  if(current())$('checkedAt').textContent=new Date().toLocaleString(globalThis.YGCI18n.locale);
}
async function refresh(){
  const version=sessionEpoch,current=()=>version===sessionEpoch&&authorized;
  settings=null;reviewState=null;controls();
  const results=await Promise.allSettled([
    request('/api/admin/operations').then(row=>{if(current()){display(row);controls()}}),
    request('/api/admin/operations/review').then(row=>{if(current()){displayReview(row);controls()}}),
  ]);
  if(!current())return;
  const failure=results.find(row=>row.status==='rejected');
  if(failure)throw failure.reason;
  $('webStatus').textContent=t('ui.responding_98047c1e');
  void refreshDiagnostics(version);
}
async function action(work){
  if(busy)return;busy=true;controls();
  try{await work()}catch(e){error(e)}finally{busy=false;controls()}
}
function displayReview(row){
  if(typeof row?.enabled!=='boolean')throw Error('Invalid review state');reviewState=row.enabled;
  $('reviewStatus').textContent=t(row.enabled?'review.on':'review.off');$('reviewToggle').textContent=t(row.enabled?'review.disable':'review.enable');
}
$('reviewToggle').onclick=()=>{
  if(busy||!authorized||reviewState===null)return;reviewPending={enabled:!reviewState,expected_enabled:reviewState};
  $('reviewWarning').textContent=t(reviewPending.enabled?'review.confirm_on':'review.confirm_off');controls();globalThis.YGCOverlays.open($('reviewDialog'));
};
$('reviewCancel').onclick=()=>globalThis.YGCOverlays.close($('reviewDialog'));
$('reviewDialog').addEventListener('ygc:closed',()=>{reviewPending=null;controls()});
$('reviewConfirm').onclick=()=>{
  if(busy||!authorized||!reviewPending)return;const payload={...reviewPending};globalThis.YGCOverlays.close($('reviewDialog'));
  action(async()=>{displayReview(await request('/api/admin/operations/review',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}));$('consoleStatus').textContent=t('ui.settings_saved_ae493e21');await applications.refresh()});
};
$('consoleRefresh').onclick=()=>action(async()=>{await refresh();$('consoleStatus').textContent=t('console.ready')});
$('operationsMode').onchange=()=>{$('operationsMessage').value=defaultMessage($('operationsMode').value)};
$('maintenanceForm').onsubmit=event=>{
  event.preventDefault();if(!authorized||!settings)return;
  const payload={mode:$('operationsMode').value,message:$('operationsMessage').value,version:settings.version};
  action(async()=>{
    display(await request('/api/admin/operations/mode',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}));
    $('consoleStatus').textContent=t('ui.settings_saved_ae493e21');
  });
};
$('consoleSignOut').onclick=()=>action(async()=>{clear();await auth.logout();$('consoleStatus').textContent=t('console.sign_in_required')});
document.querySelector('header .page-nav a[href="#cloudCrawl"]').onclick=()=>{if(authorized){select($('crawlTab'));$('operations').scrollIntoView({block:'start'})}};
document.querySelector('header .page-nav a[href="#guitarBrowser"]').onclick=()=>{if(authorized)$('cloudProductDetail').scrollIntoView({block:'start'})};
document.querySelector('header .page-nav a[href="#userBrowser"]').onclick=()=>{if(authorized)$('cloudUserDetail').scrollIntoView({block:'start'})};
const tabs=[$('statusTab'),$('maintenanceTab'),$('crawlTab')];
function select(tab){
  for(const button of tabs){const selected=button===tab;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;$(button.getAttribute('aria-controls')).hidden=!selected}
}
for(const tab of tabs)tab.onclick=()=>select(tab);
document.querySelector('.operations-menu').onkeydown=event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();const index=tabs.indexOf(document.activeElement);
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  select(tabs[next]);tabs[next].focus();
};
try{
  auth=await loadCloudAuth();
  const state=await auth.restore();
  auth.onIdentityChanged?.(()=>clear());
  if(!state?.user)$('consoleStatus').textContent=t('console.sign_in_required');
  else if(state.user.role!=='admin'||state.identity?.email_verified!==true)$('consoleStatus').textContent=t('console.admin_required');
  else{
    authorized=true;$('consoleIdentity').textContent=state.user.display_name;controls();
    const version=sessionEpoch;
    const target=new URLSearchParams(location.search).get('dispute');
    const operationsRead=refresh();
    const readDisputes=disputes.refresh().then(()=>{
      if(version===sessionEpoch&&authorized&&target&&/^[1-9][0-9]{0,18}$/.test(target))return disputes.openDispute(target);
    });
    const results=await Promise.allSettled([operationsRead,readDisputes,applications.refresh(),guitars.refresh(),users.refresh(),backups.refresh(),crawl.refresh()]);
    if(version===sessionEpoch&&authorized){
      const failure=results.find(row=>row.status==='rejected');
      if(failure){if([401,403].includes(failure.reason.status)||failure.reason.code==='sign_in_required')error(failure.reason);else $('consoleStatus').textContent=t('console.unavailable')}else $('consoleStatus').textContent=t('console.ready');
    }
  }
}catch(e){error(e)}
controls();
globalThis.YGCCloudConsoleReady=true;
