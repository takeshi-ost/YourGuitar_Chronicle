import {createFavorites} from './cloud-account-favorites.js';
import {createVisibility} from './cloud-account-visibility.js';
import {loadCloudAuth} from './cloud-auth-loader.js';
import {createGuitars} from './cloud-account-guitars.js';
import {createProfile} from './cloud-account-profile.js';
import {createAvatar} from './cloud-account-avatar.js';
import {createApplications,readCatalogIntent,catalogIndividualId} from './cloud-account-applications.js';
import {createClaims,readClaimIntent} from './cloud-account-claims.js';
import {createOwnership,readOwnershipIntent} from './cloud-account-ownership.js';
import {createIdentityCorrections} from './cloud-account-identity.js';
import {createDisputes} from './cloud-account-disputes.js';
import {createNotifications} from './cloud-account-notifications.js';
const $=id=>document.getElementById(id);
const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
$('status').removeAttribute('data-i18n');
let auth,policies,mode=new URLSearchParams(location.search).get('register')==='1'?'register':'signin',busy=false,state=null,authPending=true,pageSuspended=false,sessionEpoch=0,formalView=null;
const formalProfile=document.body?.dataset?.formalProfile==='true',formalTotals={};
const favorites=createFavorites({tableLayout:formalProfile,guitarHref:formalProfile?id=>'/ui/profile/guitars/'+id:undefined,onNavigate:formalProfile?id=>formalView?.openGuitar(id):undefined,auth:()=>auth,state:()=>pageSuspended?null:auth?.account,busy:()=>busy,work:avatarAction});
const visibility=createVisibility({auth:()=>auth,state:()=>pageSuspended?null:auth?.account,busy:()=>busy,work:avatarAction});
const avatar=createAvatar({auth:()=>auth,state:()=>state,busy:()=>busy});
const profile=createProfile({formalProfile,auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:async()=>update(await auth.restore())});
const guitars=createGuitars({tableLayout:formalProfile,inboxRoot:document.getElementById('selfOwnerAcquire'),onOwnerSaved:()=>formalView?.refresh({preserveView:true}),onSelect:formalProfile?id=>formalView?.openGuitar(id):undefined,onTotal:(kind,total)=>{formalTotals[kind]=total;formalView?.render()},auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,openOwnership:id=>ownership.openGuitar(id)});
const ownership=createOwnership({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:refreshOwnershipViews});
const applications=createApplications({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction});
const claims=createClaims({onSaved:()=>formalView?.refresh({preserveView:true}),auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction});
const identityCorrections=createIdentityCorrections({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:refreshOwnershipViews});
const disputes=createDisputes({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:refreshOwnershipViews});
const notifications=createNotifications({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,openDispute:id=>disputes.openDispute(id),openDisputeOption:id=>disputes.openDisputeOption(id),openTransfer:id=>ownership.openTransfer(id),openOwner:(id,claim)=>guitars.openOwner(id,claim)});
async function refreshOwnershipViews(){
  const actor=state?.user?.app_user_id,version=sessionEpoch;
  await guitars.refreshHistory();
  if(pageSuspended||version!==sessionEpoch||actor!==state?.user?.app_user_id)return;
  await formalView?.refresh();
}
let acquireIntent=readCatalogIntent(location.search),claimIntent=readClaimIntent(location.search),ownershipIntent=readOwnershipIntent(location.search);
applications.setCatalogIntent(acquireIntent);claims.setCatalogIntent(claimIntent);ownership.setCatalogIntent(ownershipIntent);
let resumedFormalIntent=null;
async function resumeFormalIntent(){
  if(!formalProfile||busy||!formalView||!state?.user||state.identity?.email_verified!==true)return;
  const query=location.search,actor=state.user.app_user_id,key=JSON.stringify([actor,query]);
  const entries=[['acquire',readCatalogIntent(query)],['claim',readClaimIntent(query)],['ownership',readOwnershipIntent(query)]].filter(([,id])=>id!==null);
  if(!entries.length||resumedFormalIntent===key)return;
  resumedFormalIntent=key;
  if(entries.length!==1||!catalogIndividualId(entries[0][1])){$('status').textContent=t('catalog.acquire_invalid');return}
  const [kind,id]=entries[0];
  try{
    await formalView.openGuitar(id);
    if(state?.user?.app_user_id!==actor||state.identity?.email_verified!==true||pageSuspended||location.pathname!=='/ui/profile/guitars/'+id)return;
    if(kind==='acquire')await applications.openAcquire(id);
    else if(kind==='ownership')await ownership.openGuitar(id);
    else $('addClaimMenu')?.classList.add('open');
  }catch{$('status').textContent=t('catalog.acquire_unavailable')}
}
globalThis.addEventListener('popstate',()=>{acquireIntent=readCatalogIntent(location.search);claimIntent=readClaimIntent(location.search);ownershipIntent=readOwnershipIntent(location.search);applications.setCatalogIntent(acquireIntent);claims.setCatalogIntent(claimIntent);ownership.setCatalogIntent(ownershipIntent);resumedFormalIntent=null;if(formalProfile&&!busy)void avatarAction(loadAvatar)});
let serviceBlocked=false;
function render(){
  const registered=Boolean(state?.user),resume=Boolean(state?.registration_required);
  $('emailVerification').hidden=!registered;
  const verified=state?.identity?.email_verified===true;
  $('verificationStatus').textContent=t(verified?'cloud.email_verified':'cloud.email_unverified');
  $('sendVerification').hidden=verified;
  $('sendVerification').disabled=$('refreshVerification').disabled=busy||!registered;
  $('accountSummary').hidden=!registered;
  $('consoleLink').hidden=!(registered&&verified&&state.user.role==='admin');
  if(registered)$('accountSummary').textContent=t('cloud.signed_in',{name:state.user.display_name});
  $('authActions').hidden=serviceBlocked||authPending||pageSuspended||registered||resume;
  $('signOut').hidden=!auth?.signedIn;
  $('cloudAccountForm').hidden=serviceBlocked||authPending||pageSuspended||registered;
  $('profileFields').hidden=mode!=='register';
  $('profileFields').disabled=mode!=='register';
  $('credentialsFields').hidden=resume;
  $('credentialsFields').disabled=resume;
  $('displayName').required=mode==='register';
  $('terms').required=$('privacy').required=mode==='register';
  $('password').autocomplete=mode==='register'?'new-password':'current-password';
  $('submit').textContent=t(resume?'cloud.complete_registration':mode==='register'?'cloud.create_account':'account.sign_in');
  $('submit').removeAttribute('data-i18n');
  for(const id of ['submit','showSignIn','showRegistration'])$(id).disabled=busy||!auth||!policies;
  $('signOut').disabled=busy||!auth;
  favorites.render();visibility.render();avatar.render();profile.render();guitars.render();applications.render();claims.render();ownership.render();identityCorrections.render();notifications.render();disputes.render();formalView?.render();
}
async function documents(){
  policies=null;
  policies=await auth.documents();
  $('terms').checked=$('privacy').checked=false;
}
function clearPrivateAccount({preserveRetryMarkers=false}={}){
  formalView?.clear();favorites.clear();visibility.clear();avatar.clear();profile.clear();guitars.clear();applications.clear();claims.clear();ownership.clear();identityCorrections.clear({preserveRetryMarkers});notifications.clear();disputes.clear();
}
function suspendAccount(){
  // Navigation is not sign-out. Purge private views and invalidate async work,
  // but retain account-bound unknown-result markers for the next canonical read.
  pageSuspended=true;sessionEpoch++;state=null;clearPrivateAccount({preserveRetryMarkers:true});$('status').textContent='';render();
}
function update(result,refreshCatalog=false){
  if(result)serviceBlocked=false;
  if(pageSuspended&&result!==null)return;
  const changed=state?.user?.app_user_id!==result?.user?.app_user_id||state?.identity?.email_verified!==result?.identity?.email_verified;
  if(state?.user?.app_user_id!==result?.user?.app_user_id)clearPrivateAccount();
  state=result;
  if(changed||refreshCatalog){applications.setCatalogIntent(acquireIntent);claims.setCatalogIntent(claimIntent);ownership.setCatalogIntent(ownershipIntent)}
  if(result?.registration_required){mode='register';$('status').textContent=t('cloud.registration_required')}
  else $('status').textContent=result?.user?t('cloud.account_ready'):'';
  render();
}
function errorMessage(error){
  const codes={'auth/email-already-in-use':'cloud.email_exists','auth/invalid-credential':'cloud.invalid_credentials',
    'auth/invalid-email':'cloud.invalid_email','auth/weak-password':'cloud.weak_password',
    'auth/too-many-requests':'cloud.too_many_requests','auth/network-request-failed':'cloud.network_error',
    policy_changed:'cloud.policy_changed'};
  return t(codes[error.code]||'cloud.failed');
}
function policy(kind){
  const doc=policies[kind];$('policyTitle').textContent=doc.title;
  $('policyContent').replaceChildren();
  for(const text of [t('cloud.policy_version',{version:doc.version}),...doc.paragraphs]){
    const paragraph=document.createElement('p');paragraph.textContent=text;$('policyContent').append(paragraph);
  }
  YGCOverlays.open('policyDialog');
}
$('viewTerms').onclick=()=>policy('terms');$('viewPrivacy').onclick=()=>policy('privacy');
$('closePolicy').onclick=()=>YGCOverlays.close('policyDialog');
for(const [id,value] of [['showSignIn','signin'],['showRegistration','register']])$(id).onclick=()=>{
  mode=value;$('status').textContent='';$('password').value='';render();
};
$('cloudAccountForm').onsubmit=async event=>{
  event.preventDefault();if(busy||!auth)return;
  busy=true;render();$('status').textContent=t('cloud.working');
  const credentials={email:$('email').value.trim(),password:$('password').value};
  try{
    const result=mode==='signin'?await auth.signIn(credentials):await auth.register({
      display_name:$('displayName').value,account_type:$('accountType').value,
      terms_accepted:$('terms').checked,privacy_accepted:$('privacy').checked,
      terms_version:policies.terms.version,privacy_version:policies.privacy.version,
    },state?.registration_required?undefined:credentials);
    $('email').value='';update(result,true);
  }catch(error){
    if(error.code==='policy_changed'){
      try{await documents()}catch{error={code:'auth/network-request-failed'}}
    }
    if(auth.signedIn&&!auth.account&&error.status!==401&&error.status!==403){state={registration_required:true};mode='register'}
    $('status').textContent=errorMessage(error);
  }finally{$('password').value='';busy=false;render()}
  await hydrateAccount();
  await resumeFormalIntent();
};
$('signOut').onclick=async()=>{
  if(busy)return;busy=true;update(null);favorites.clear();visibility.clear();notifications.clear();disputes.clear();render();
  try{await auth.logout();mode='signin';$('cloudAccountForm').reset();update(null)}
  catch(error){$('status').textContent=errorMessage(error)}
  finally{busy=false;render()}
};
$('sendVerification').onclick=async()=>{
  if(busy||!state?.user)return;
  busy=true;render();
  try{
    const result=await auth.requestEmailVerification({language:document.documentElement.lang||'en',acquire:acquireIntent||undefined,...(claimIntent?{claim:claimIntent}:{})});
    update(result.account,true);
    $('status').textContent=t(result.sent?'cloud.verification_sent':'cloud.email_verified');
  }catch(error){$('status').textContent=errorMessage(error)}
  finally{busy=false;render()}
};
$('refreshVerification').onclick=async()=>{
  if(busy||!state?.user)return;
  busy=true;render();
  try{
    const result=await auth.refreshVerification();update(result,true);
    if(result?.user)$('status').textContent=t(result.identity?.email_verified===true?'cloud.email_verified':'cloud.verification_pending');
  }catch(error){$('status').textContent=errorMessage(error)}
  finally{busy=false;render()}
  await hydrateAccount();
  await resumeFormalIntent();
};
async function loadAvatar(){
  const actor=state?.user?.app_user_id,version=sessionEpoch;
  const current=()=>actor&&actor===state?.user?.app_user_id&&version===sessionEpoch&&!pageSuspended&&state?.identity?.email_verified===true;
  if(!current())return;
  // Start the visible profile and lists first. authorizedFetch retains the
  // shared two-request limit; unrelated panels cannot block these reads.
  const primary=await Promise.allSettled([profile.refresh({reuse:true}).catch(profile.failed),guitars.refresh(),favorites.refresh({reuse:true})]);
  if(!current())return;
  const secondary=await Promise.allSettled([
    formalView?.refresh(),...formalProfile?[]:[visibility.refresh()],disputes.refresh(),notifications.refresh({reuse:true}),
    identityCorrections.refresh(),ownership.refresh(),applications.refresh().catch(applications.failed),
    avatar.refresh().catch(avatar.failed),
  ]);
  if(!current())return;
  const failure=[...primary,...secondary].find(result=>result.status==='rejected');
  if(failure)throw failure.reason;
}
async function hydrateAccount(){
  const actor=state?.user?.app_user_id,version=sessionEpoch;
  try{await loadAvatar()}
  catch(error){if(!pageSuspended&&version===sessionEpoch&&actor===state?.user?.app_user_id)$('status').textContent=errorMessage(error)}
}
async function avatarAction(work){
  if(busy)return;busy=true;render();
  try{await work()}catch(error){avatar.failed(error)}finally{busy=false;render()}
  await resumeFormalIntent();
}
globalThis.addEventListener('pagehide',suspendAccount);
globalThis.addEventListener('pageshow',async event=>{
  if(!event.persisted||!auth)return;
  busy=true;authPending=true;suspendAccount();const current=sessionEpoch;
  try{const restored=await auth.restore();if(current!==sessionEpoch)return;pageSuspended=false;authPending=false;update(restored,true)}
  catch(error){if(current!==sessionEpoch)return;pageSuspended=false;authPending=false;update(null);$('status').textContent=errorMessage(error)}
  finally{if(current===sessionEpoch&&!pageSuspended){busy=false;render()}}
  if(current===sessionEpoch&&!pageSuspended)await hydrateAccount();
});
$('avatarForm').onsubmit=event=>{event.preventDefault();avatarAction(()=>avatar.save($('avatarFile').files[0]))};
$('avatarRemove').onclick=()=>avatarAction(()=>avatar.remove());
$('avatarRefresh').onclick=()=>avatarAction(()=>avatar.refresh());
if(formalProfile){
  const {createFormalProfileView}=await import('./cloud-ui-profile.js');
  formalView=createFormalProfileView({auth:()=>auth,state:()=>pageSuspended?null:state,busy:()=>busy,totals:formalTotals,owners:guitars,claims,openDispute:id=>disputes.openDispute(id),selectedActions:id=>guitars.selectedActions(id),openClaim:(id,type)=>claims.openCreate(id,type),openAcquire:id=>applications.openAcquire(id),openOwnership:id=>ownership.openGuitar(id),refreshAccount:async()=>{auth?.invalidateUserData?.();await avatarAction(async()=>{update(await auth.restore(),true)});await hydrateAccount()}});
}
try{auth=await loadCloudAuth();auth.onIdentityChanged?.(()=>{serviceBlocked=false;update(null);if(!authPending)$('status').textContent=t('cloud.session_changed')});auth.onUserDataInvalidated?.((reason,error)=>{if(reason==='blocked'){serviceBlocked=error?.code==='service_restricted';update(null);$('status').textContent=t('self_profile.restricted')}});const [restored]=await Promise.all([auth.restore(),documents()]);authPending=false;update(restored);if(state?.user&&state.identity?.email_verified===true)await hydrateAccount()}
catch(error){authPending=false;$('status').removeAttribute('data-i18n');$('status').textContent=errorMessage(error);render()}
$('status').removeAttribute('data-i18n');
// Navigation from Top notifications is a hint; each destination rechecks its API.
if(formalProfile&&state?.user&&state.identity?.email_verified===true){
 const query=new URLSearchParams(location.search),kind=query.get('notice'),id=query.get('target'),claim=query.get('claim');
 const valid=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&BigInt(value)<=9223372036854775807n;
 if(valid(id)&&['transfer','owner','dispute','dispute_option'].includes(kind)&&(kind!=='owner'||valid(claim))){
  history.replaceState(null,'',location.pathname);
  if(kind==='transfer')await ownership.openTransfer(id);
  else if(kind==='owner')await guitars.openOwner(id,claim);
  else if(kind==='dispute')await disputes.openDispute(id);
  else await disputes.openDisputeOption(id);
 }
}
globalThis.YGCCloudAccountReady=true;
