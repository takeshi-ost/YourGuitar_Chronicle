import {loadCloudAuth} from './cloud-auth-loader.js';
const $=id=>document.getElementById(id);
const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
$('status').removeAttribute('data-i18n');
let auth,policies,mode='signin',busy=false,state=null;
function render(){
  const registered=Boolean(state?.user),resume=Boolean(state?.registration_required);
  $('accountSummary').hidden=!registered;
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
}
async function documents(){
  policies=null;
  policies=await auth.documents();
  $('terms').checked=$('privacy').checked=false;
}
function update(result){
  state=result;
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
    $('email').value='';update(result);
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
try{auth=await loadCloudAuth();await documents();update(await auth.restore())}
catch(error){$('status').removeAttribute('data-i18n');$('status').textContent=errorMessage(error);render()}
$('status').removeAttribute('data-i18n');
globalThis.YGCCloudAccountReady=true;
