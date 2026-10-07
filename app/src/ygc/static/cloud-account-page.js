import {loadCloudAuth} from './cloud-auth-loader.js';
import {createGuitars} from './cloud-account-guitars.js';
import {createProfile} from './cloud-account-profile.js';
import {createAvatar} from './cloud-account-avatar.js';
import {createApplications,readCatalogIntent} from './cloud-account-applications.js';
import {createClaims,readClaimIntent} from './cloud-account-claims.js';
import {createOwnership,readOwnershipIntent} from './cloud-account-ownership.js';
import {createIdentityCorrections} from './cloud-account-identity.js';
const $=id=>document.getElementById(id);
const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
$('status').removeAttribute('data-i18n');
let auth,policies,mode='signin',busy=false,state=null;
const avatar=createAvatar({auth:()=>auth,state:()=>state,busy:()=>busy});
const profile=createProfile({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:async()=>update(await auth.restore())});
const guitars=createGuitars({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,openOwnership:id=>ownership.openGuitar(id)});
const ownership=createOwnership({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:()=>guitars.refreshHistory()});
const applications=createApplications({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction});
const claims=createClaims({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction});
const identityCorrections=createIdentityCorrections({auth:()=>auth,state:()=>state,busy:()=>busy,work:avatarAction,updated:()=>guitars.refreshHistory()});
let acquireIntent=readCatalogIntent(location.search),claimIntent=readClaimIntent(location.search),ownershipIntent=readOwnershipIntent(location.search);
applications.setCatalogIntent(acquireIntent);claims.setCatalogIntent(claimIntent);ownership.setCatalogIntent(ownershipIntent);
globalThis.addEventListener('popstate',()=>{acquireIntent=readCatalogIntent(location.search);claimIntent=readClaimIntent(location.search);ownershipIntent=readOwnershipIntent(location.search);applications.setCatalogIntent(acquireIntent);claims.setCatalogIntent(claimIntent);ownership.setCatalogIntent(ownershipIntent)});
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
  $('authActions').hidden=registered||resume;
  $('signOut').hidden=!auth?.signedIn;
  $('cloudAccountForm').hidden=registered;
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
  avatar.render();profile.render();guitars.render();applications.render();claims.render();ownership.render();identityCorrections.render();
}
async function documents(){
  policies=null;
  policies=await auth.documents();
  $('terms').checked=$('privacy').checked=false;
}
function update(result,refreshCatalog=false){
  const changed=state?.user?.app_user_id!==result?.user?.app_user_id||state?.identity?.email_verified!==result?.identity?.email_verified;
  if(state?.user?.app_user_id!==result?.user?.app_user_id){avatar.clear();profile.clear();guitars.clear();applications.clear();claims.clear();ownership.clear();identityCorrections.clear()}
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
    $('email').value='';update(result,true);await loadAvatar();
  }catch(error){
    if(error.code==='policy_changed'){
      try{await documents()}catch{error={code:'auth/network-request-failed'}}
    }
    if(auth.signedIn&&!auth.account&&error.status!==401&&error.status!==403){state={registration_required:true};mode='register'}
    $('status').textContent=errorMessage(error);
  }finally{$('password').value='';busy=false;render()}
};
$('signOut').onclick=async()=>{
  if(busy)return;busy=true;render();
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
    const result=await auth.refreshVerification();update(result,true);await loadAvatar();
    if(result?.user)$('status').textContent=t(result.identity?.email_verified===true?'cloud.email_verified':'cloud.verification_pending');
  }catch(error){$('status').textContent=errorMessage(error)}
  finally{busy=false;render()}
};
async function loadAvatar(){
  if(state?.user&&state.identity?.email_verified===true)await identityCorrections.refresh();
  if(state?.user&&state.identity?.email_verified===true)await ownership.refresh();
  if(state?.user&&state.identity?.email_verified===true)await applications.refresh().catch(applications.failed);
  if(state?.user&&state.identity?.email_verified===true)await guitars.refresh();
  if(state?.user&&state.identity?.email_verified===true)await profile.refresh().catch(profile.failed);
  if(state?.user&&state.identity?.email_verified===true){
    try{await avatar.refresh()}catch(error){avatar.failed(error)}
  }
}
async function avatarAction(work){
  if(busy)return;busy=true;render();
  try{await work()}catch(error){avatar.failed(error)}finally{busy=false;render()}
}
$('avatarForm').onsubmit=event=>{event.preventDefault();avatarAction(()=>avatar.save($('avatarFile').files[0]))};
$('avatarRemove').onclick=()=>avatarAction(()=>avatar.remove());
$('avatarRefresh').onclick=()=>avatarAction(()=>avatar.refresh());
try{auth=await loadCloudAuth();await documents();update(await auth.restore());if(state?.user&&state.identity?.email_verified===true)await avatarAction(loadAvatar)}
catch(error){$('status').removeAttribute('data-i18n');$('status').textContent=errorMessage(error);render()}
$('status').removeAttribute('data-i18n');
globalThis.YGCCloudAccountReady=true;
