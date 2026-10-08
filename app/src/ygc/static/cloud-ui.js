import {createPublicCatalog} from './cloud-public-catalog.js';
import {loadCloudAuth} from './cloud-auth-loader.js';

// Reuse the canonical Identity Platform adapter. The local prototype's actor
// selectors, viewer_id URLs and ownership repositories never run in this page.
const $=id=>document.getElementById(id);
const words={
  en:{top:'Top Page',products:'Products',members:'Members',profile:'Your profile',notifications:'Notifications',account:'Your account',signin:'Sign In',signout:'SignOut',register:'Create Account',guest:'Explore guitar histories. Add yours when you are ready.',loading:'Loading user information…',blocked:'Session needs verification. Refresh or sign in again.',email:'Email',password:'Password',cancel:'Cancel',notice:'Your email and password are sent to Google for authentication.',failed:'Sign in could not be completed. Check your details and try again.',logoutFailed:'SignOut could not be confirmed. Refresh to check your session.',pending:'Signing in…',registration:'Complete your registration from Your account.',unverified:'Verify your email from Your account to use member features.',maker:'Maker',model:'Model',finish:'Finish',year:'Year',serial:'Serial'},
  ja:{top:'トップページ',products:'ギター一覧',members:'会員検索',profile:'自分のプロフィール',notifications:'通知',account:'アカウント',signin:'サインイン',signout:'サインアウト',register:'アカウント作成',guest:'ギターの歴史を探す。あなたの記録も加えましょう。',loading:'ユーザー情報を読み込み中…',blocked:'セッションを確認できません。再取得またはサインインしてください。',email:'メールアドレス',password:'パスワード',cancel:'キャンセル',notice:'メールアドレスとパスワードは認証のためGoogleへ送信されます。',failed:'サインインできませんでした。入力内容を確認して再試行してください。',logoutFailed:'サインアウトの完了を確認できません。再取得してセッションを確認してください。',pending:'サインイン中…',registration:'アカウント画面で登録を完了してください。',unverified:'会員機能を使うにはアカウント画面でメール確認を完了してください。',maker:'メーカー',model:'モデル',finish:'仕上げ',year:'製造年',serial:'シリアル'}
};
let locale='en',auth=null,authPromise=null,busy=false,active=true,lastState=null,noticeKey=null;
const t=key=>words[locale][key];
const dialog=$('shellSignInDialog');
function clearCredentials(){$('shellEmail').value='';$('shellPassword').value=''}
function notice(key){noticeKey=key;$('shellStatus').textContent=key?t(key):'';$('shellStatus').hidden=!key}
function header(state){
  lastState=state;auth=state.auth;locale=state.locale;notice(noticeKey);
  const account=active&&!state.blocked?auth?.account:null,user=account?.user;
  const labels={shellTitle:'top',shellProducts:'products',shellMembers:'members',shellProfile:'profile',shellNotifications:'notifications',accountLink:'account',shellSignIn:'signin',shellSignOut:'signout',shellSignInTitle:'signin',shellEmailLabel:'email',shellPasswordLabel:'password',shellCancel:'cancel',shellRegister:'register',shellCredentialsNotice:'notice',columnMaker:'maker',columnModel:'model',columnFinish:'finish',columnYear:'year',columnSerial:'serial'};
  for(const [id,key] of Object.entries(labels))$(id).textContent=t(key);
  $('shellSubmit').textContent=t(busy?'pending':'signin');
  $('shellSignIn').hidden=Boolean(user);$('shellSignIn').disabled=busy||!auth;
  $('shellSignOut').hidden=!auth?.signedIn;$('shellSignOut').disabled=busy;
  $('shellSubmit').disabled=busy||!auth;
  $('shellAccountLinks').hidden=!user;
  $('shellIdentity').textContent=!active?'':state.blocked?t('blocked'):user?String(user.display_name||''):auth?.signedIn?t('registration'):auth?t('guest'):t('loading');
  $('productDetailShell').classList.toggle('compact-open',state.detailOpen);
}
const catalog=createPublicCatalog({basePath:'/ui',accountPath:'/ui/profile',listStyle:'table',onState:header,
  loadAuth:()=>authPromise??=loadCloudAuth().catch(error=>{authPromise=null;throw error})});
function render(){if(lastState)header(lastState)}
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
const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',document.querySelector('.sticky-header').getBoundingClientRect().height+'px'));
observer.observe(document.querySelector('.sticky-header'));
window.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||document.querySelector('dialog[open]')||!window.matchMedia('(max-width:900px)').matches||!lastState?.detailOpen)return;
  event.preventDefault();void catalog.navigate('/ui'+window.location.search).then(()=>$('listHeading').focus());
});
window.addEventListener('pagehide',()=>{active=false;clearCredentials();notice('');globalThis.YGCOverlays.close(dialog);$('shellIdentity').textContent='';$('shellAccountLinks').hidden=true});
window.addEventListener('pageshow',()=>{active=true});
await catalog.start();
globalThis.YGCCloudUIReady=true;
