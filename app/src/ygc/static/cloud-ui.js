import {createDetailDispute} from './cloud-detail-dispute.js';
import {createOwnership} from './cloud-account-ownership.js';
import {createDisputes} from './cloud-account-disputes.js';
import {createNotifications} from './cloud-account-notifications.js';
import {createGuitars} from './cloud-account-guitars.js';
import {createDetailClaimActions} from './cloud-detail-claim-actions.js';
import {createAccountHub} from './cloud-account-hub.js';
import {createApplications} from './cloud-account-applications.js';
import {createClaims} from './cloud-account-claims.js';
import {createPublicCatalog} from './cloud-public-catalog.js';
import {createCatalogInsights} from './cloud-catalog-insights.js';
import {loadCloudAuth} from './cloud-auth-loader.js';

// Reuse the canonical Identity Platform adapter. The local prototype's actor
// selectors, viewer_id URLs and ownership repositories never run in this page.
const $=id=>document.getElementById(id);
const words={
  en:{top:'Top Page',products:'Products',members:'Members',profile:'Your profile',notifications:'Notifications',account:'Your account',signin:'Sign In',signout:'SignOut',register:'Create Account',guest:'Explore guitar histories. Add yours when you are ready.',loading:'Loading user information…',restricted:'Service access is temporarily restricted.',blocked:'Session needs verification. Refresh or sign in again.',email:'Email',password:'Password',cancel:'Cancel',notice:'Your email and password are sent to Google for authentication.',failed:'Sign in could not be completed. Check your details and try again.',logoutFailed:'SignOut could not be confirmed. Refresh to check your session.',pending:'Signing in…',registration:'Complete your registration from Your account.',unverified:'Verify your email from Your account to use member features.',maker:'Maker',model:'Model',finish:'Finish',year:'Year',serial:'Serial'},
  ja:{top:'トップページ',products:'ギター一覧',members:'会員検索',profile:'自分のプロフィール',notifications:'通知',account:'アカウント',signin:'サインイン',signout:'サインアウト',register:'アカウント作成',guest:'ギターの歴史を探す。あなたの記録も加えましょう。',loading:'ユーザー情報を読み込み中…',restricted:'サービスの利用を一時的に制限しています。',blocked:'セッションを確認できません。再取得またはサインインしてください。',email:'メールアドレス',password:'パスワード',cancel:'キャンセル',notice:'メールアドレスとパスワードは認証のためGoogleへ送信されます。',failed:'サインインできませんでした。入力内容を確認して再試行してください。',logoutFailed:'サインアウトの完了を確認できません。再取得してセッションを確認してください。',pending:'サインイン中…',registration:'アカウント画面で登録を完了してください。',unverified:'会員機能を使うにはアカウント画面でメール確認を完了してください。',maker:'メーカー',model:'モデル',finish:'仕上げ',year:'製造年',serial:'シリアル'}
};
let locale='en',auth=null,authPromise=null,busy=false,active=true,lastState=null,noticeKey=null;
const t=key=>words[locale][key];
const dialog=$('shellSignInDialog');
const accountHub=createAccountHub({auth:()=>auth,state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null});
$('shellSignIn').after($('accountLink'));
const notificationBackdrop=document.createElement('div');notificationBackdrop.id='formalNotifications';notificationBackdrop.className='modal-backdrop';
const notificationPanel=document.createElement('div');notificationPanel.className='modal notification-modal';notificationPanel.setAttribute('role','dialog');notificationPanel.setAttribute('aria-modal','true');notificationPanel.setAttribute('aria-labelledby','notificationHeading');
const notificationRoot=document.createElement('section');notificationRoot.id='selfNotifications';notificationPanel.append(notificationRoot);notificationBackdrop.append(notificationPanel);document.body.append(notificationBackdrop);
const notificationDestination=(kind,id,claim)=>{const query=new URLSearchParams({notice:kind,target:id});if(claim)query.set('claim',claim);location.assign('/ui/profile?'+query)};
const notifications=createNotifications({formal:true,auth:()=>auth,state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null,busy:()=>busy,work:async fn=>{if(busy)return;busy=true;notifications.render();try{return await fn()}finally{busy=false;notifications.render();render()}},openTransfer:id=>notificationDestination('transfer',id),openOwner:(id,claim)=>notificationDestination('owner',id,claim),openDispute:id=>notificationDestination('dispute',id),openDisputeOption:id=>notificationDestination('dispute_option',id)});
const notificationClose=document.createElement('button');notificationClose.type='button';notificationClose.dataset.uiAction='close';notificationClose.textContent=globalThis.YGCI18n.t('action.close');notificationClose.onclick=()=>globalThis.YGCOverlays.close(notificationBackdrop);
const notificationActions=document.createElement('div');notificationActions.className='modal-actions';notificationActions.append($('notificationMarkAll'),notificationClose);notificationPanel.append(notificationActions);
$('shellNotifications').onclick=async event=>{event.preventDefault();if(busy||!active||lastState?.blocked||lastState?.authPending||auth?.account?.identity?.email_verified!==true)return;globalThis.YGCOverlays.open(notificationBackdrop,{opener:event.currentTarget});await notifications.refresh({reuse:true})};

function clearCredentials(){$('shellEmail').value='';$('shellPassword').value=''}
function notice(key){noticeKey=key;$('shellStatus').textContent=key?t(key):'';$('shellStatus').hidden=!key}
function header(state){
  lastState=state;auth=state.auth;locale=state.locale;notice(noticeKey);
  const account=active&&!state.blocked&&!state.authPending?auth?.account:null,user=account?.user;
  const labels={shellTitle:'top',shellProducts:'products',shellMembers:'members',shellProfile:'profile',shellNotifications:'notifications',accountLink:'account',shellSignIn:'signin',shellSignOut:'signout',shellSignInTitle:'signin',shellEmailLabel:'email',shellPasswordLabel:'password',shellCancel:'cancel',shellRegister:'register',shellCredentialsNotice:'notice',columnMaker:'maker',columnModel:'model',columnFinish:'finish',columnYear:'year',columnSerial:'serial'};
  for(const [id,key] of Object.entries(labels))$(id).textContent=t(key);
  $('shellSubmit').textContent=t(busy?'pending':'signin');
  $('shellSignIn').hidden=Boolean(user)||!auth||!active||state.authPending||state.blockCode==='service_restricted'; $('shellSignIn').disabled=busy||!auth;
  $('shellSignOut').hidden=!auth?.signedIn;$('shellSignOut').disabled=busy;
  $('shellSubmit').disabled=busy||!auth;
  $('shellAccountLinks').hidden=!user;$('shellGuestSpacer').hidden=Boolean(user);
  $('shellIdentity').className=user?'account-hub-name':'account-hub-guest-title';
  if(!auth?.signedIn){$('accountLink').textContent=t('register');$('accountLink').href='/ui/profile?register=1';$('accountLink').classList.add('primary');$('accountLink').dataset.uiAction='primary'}
  else{$('accountLink').href='/ui/profile';$('accountLink').classList.remove('primary');delete $('accountLink').dataset.uiAction}
  $('shellIdentity').textContent=!active?'':state.authPending?t('loading'):state.blocked?t(state.blockCode==='service_restricted'?'restricted':'blocked'):user?String(user.display_name||''):auth?.signedIn?t('registration'):auth?t('guest'):t('loading');
  $('productDetailShell').classList.toggle('compact-open',state.detailOpen);accountHub.render();notifications.render();if(!user||state.blocked){notifications.clear();globalThis.YGCOverlays.close(notificationBackdrop)}
}
const important=document.createElement('section');important.id='importantInformation';important.className='unanswered-requests';important.hidden=true;const applicationRoot=document.createElement('section');important.append(applicationRoot);$('publicCatalog').prepend(important);
const applicationWork=async fn=>{if(busy)return;busy=true;applications.render();try{await fn()}finally{busy=false;applications.render();render()}};
const applications=createApplications({formal:true,auth:()=>auth,state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null,busy:()=>busy,work:applicationWork,root:applicationRoot,intentRoot:document.createElement('section')});
const ownershipRoot=document.createElement('section');ownershipRoot.id='selfOwnership';const ownershipIntent=document.createElement('section');ownershipIntent.id='catalogOwnershipIntent';ownershipIntent.hidden=true;document.body.append(ownershipIntent);
const disputeRoot=document.createElement('section');disputeRoot.id='selfDisputes';const ownerAcquireRoot=document.createElement('section');ownerAcquireRoot.hidden=true;important.append(ownerAcquireRoot,ownershipRoot,disputeRoot);
const participantState=()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null;
const participantWork=async fn=>{if(busy)return;busy=true;ownership.render();disputes.render();try{return await fn()}finally{busy=false;ownership.render();disputes.render();render()}};
const ownership=createOwnership({formal:true,auth:()=>auth,state:participantState,busy:()=>busy,work:participantWork,updated:()=>catalog.refresh()});
const disputes=createDisputes({formal:true,auth:()=>auth,state:participantState,busy:()=>busy,work:participantWork,updated:()=>catalog.refresh()});
$('applicationListing').hidden=true;let applicationIdentity=null;
function syncApplications(state){const key=state.authPending||state.blocked||state.auth?.account?.identity?.email_verified!==true?null:state.auth?.account?.user?.app_user_id;if(key!==applicationIdentity){applicationIdentity=key;applications.clear();ownership.clear();disputes.clear();owners.clear();if(key){void applications.refresh();void ownership.refresh();void disputes.refresh();void owners.refreshInbox()}}applications.render();ownership.render();disputes.render();important.hidden=(applicationRoot.hidden&&ownershipRoot.hidden&&disputeRoot.hidden&&ownerAcquireRoot.hidden)||state.serviceMode==='read_only'||state.serviceMode==='offline'}
for(const root of [applicationRoot,ownershipRoot,disputeRoot,ownerAcquireRoot])new MutationObserver(()=>{important.hidden=(applicationRoot.hidden&&ownershipRoot.hidden&&disputeRoot.hidden&&ownerAcquireRoot.hidden)||lastState?.serviceMode==='read_only'||lastState?.serviceMode==='offline'}).observe(root,{attributes:true,attributeFilter:['hidden']});
const claims=createClaims({formal:true,auth:()=>auth,state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null,busy:()=>busy,root:document.createElement('section'),intentRoot:document.createElement('section'),work:async fn=>{if(busy)return;busy=true;claims.render();try{await fn()}finally{busy=false;claims.render();render()}},onSaved:()=>catalog.refresh({preserveView:true})});
const owners=createGuitars({root:document.createElement('section'),inboxRoot:ownerAcquireRoot,auth:()=>auth,state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null,busy:()=>busy,work:async fn=>{if(busy)return;busy=true;owners.render();try{return await fn()}finally{busy=false;owners.render();render()}},onOwnerSaved:()=>catalog.refresh({preserveView:true})});
const detailActions=createDetailClaimActions({state:()=>active&&!lastState?.blocked&&!lastState?.authPending?auth?.account:null,busy:()=>busy,owners,claims});
const detailDispute=createDetailDispute({auth:()=>auth,state:participantState,busy:()=>busy,openDispute:id=>disputes.openDispute(id)});
const insights=createCatalogInsights({read:(path,signal)=>catalog.read(path,signal),onSelect:id=>catalog.select(id),onRefresh:()=>catalog.refresh()});
const catalog=createPublicCatalog({basePath:'/ui',accountPath:'/ui/profile',listStyle:'table',onChronicle:(root,id)=>queueMicrotask(()=>detailActions.load(root,id)),onClaimPopup:detailActions.popup,onState:state=>{header(state);void insights.sync(state);claims.render();owners.render();detailActions.render();syncApplications(state);void detailDispute.sync(state)},onClaim:(id,type)=>claims.openCreate(id,type),onAcquire:id=>detailDispute.blocked()?undefined:applications.openAcquire(id),onOwnership:id=>detailDispute.blocked()?undefined:ownership.openGuitar(id),
  loadAuth:()=>authPromise??=loadCloudAuth().catch(error=>{authPromise=null;throw error})});
function render(){if(lastState)header(lastState);detailActions.render();detailDispute.render()}
$('shellSignIn').onclick=()=>{
  if(busy||!auth)return;
  clearCredentials();$('shellLoginStatus').textContent='';
  globalThis.YGCOverlays.open(dialog,{opener:$('shellSignIn'),initialFocus:'#shellEmail'});
};
$('shellCancel').onclick=()=>globalThis.YGCOverlays.close(dialog);
dialog.addEventListener('ygc:closed',clearCredentials);
$('shellSignInForm').onsubmit=async event=>{
  event.preventDefault();if(busy||!auth)return;
  const credentials={email:$('shellEmail').value,password:$('shellPassword').value};
  clearCredentials();busy=true;render();$('shellLoginStatus').textContent=t('pending');notice('');
  try{
    const result=await auth.signIn(credentials);
    if(!active)return;
    globalThis.YGCOverlays.close(dialog);
    await catalog.refresh();
    if(result?.registration_required)notice('registration');
    else if(result?.identity?.email_verified!==true)notice('unverified');
  }catch{if(active)$('shellLoginStatus').textContent=t('failed')}
  finally{credentials.email=credentials.password='';busy=false;if(active)render()}
};
$('shellSignOut').onclick=async()=>{
  if(busy||!auth)return;
  busy=true;notice('');globalThis.YGCOverlays.close(dialog);catalog.invalidateIdentity();render();
  try{
    await auth.logout();
    // Flush the SDK principal change before starting a fresh catalog epoch.
    // Some SDK observers arrive only on the next canonical restore.
    await auth.restore();
    if(active)await catalog.refresh();
  }
  catch{if(active)notice('logoutFailed')}
  finally{busy=false;if(active)render()}
};
const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',Math.ceil(document.querySelector('.sticky-header').getBoundingClientRect().height)+'px'));
observer.observe(document.querySelector('.sticky-header'));
window.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||document.querySelector('dialog[open]')||!window.matchMedia('(max-width:900px)').matches||!lastState?.detailOpen)return;
  event.preventDefault();catalog.closeDetail();$('listHeading').focus();
});
document.addEventListener('pointerdown',event=>{if(!window.matchMedia('(max-width:900px)').matches||event.target.closest('#productDetailShell,.modal-backdrop.open,dialog[open]'))return;catalog.closeDetail()});
window.addEventListener('pagehide',()=>{active=false;insights.clear({pause:true});detailDispute.clear();notifications.clear();globalThis.YGCOverlays.close(notificationBackdrop);detailActions.clear();owners.clear();claims.clear();applications.clear();ownership.clear();disputes.clear();clearCredentials();notice('');globalThis.YGCOverlays.close(dialog);$('shellIdentity').textContent='';$('shellAccountLinks').hidden=true});
window.addEventListener('pageshow',()=>{active=true;insights.resume()});
await catalog.start();
await insights.whenReady();
await catalog.selectInitial(insights.pickDiscovery());
globalThis.YGCCloudUIReady=true;
