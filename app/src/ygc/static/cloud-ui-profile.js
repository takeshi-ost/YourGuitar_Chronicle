import {createPublicCatalog} from './cloud-public-catalog.js';
// Presentation of the canonical self-account controllers. No actor selector or
// additional profile projection: all writes retain their original API guards.
export function createFormalProfileView({auth,state,busy,totals,refreshAccount}){
  const $=id=>document.getElementById(id),t=(k,p={})=>globalThis.YGCI18n.t(k,p);
  let catalog=null,started=false;
  const column=$('profileColumn'),hub=document.querySelector('#accountHub .account-hub-user');
  $('shellTitle').textContent=t('self_profile.heading');$('catalogLanguage').value=globalThis.YGCI18n.locale||'en';$('catalogLanguage').onchange=()=>{localStorage.setItem('ygc_ui_language',$('catalogLanguage').value);location.reload()};
  for(const id of ['shellSignIn','shellSignOut','shellSignInDialog','shellRegister'])$(id)?.remove();
  $('shellIdentity').textContent='';hub.append($('accountSummary'));
  document.querySelector('#accountHub>.account-hub-actions:last-child').append($('signOut'));
  $('accountLink').href='/ui';$('accountLink').textContent=t('catalog.browse');
  $('shellProducts').href='/ui';$('shellMembers').href='/ui/members';
  $('shellProfile').textContent=t('self_profile.heading');$('shellNotifications').textContent=t('notifications.heading');
  const nav=document.createElement('nav');nav.className='profile-sections';
  for(const [id,key] of [['selfProfile','self_profile.heading'],['selfGuitars_owned','users.owned'],['selfGuitars_formerly_owned','users.formerly_owned'],['selfFavorites','favorites.heading'],['selfApplications','applications.heading'],['selfClaims','claims.heading'],['selfNotifications','notifications.heading']]){
    const a=document.createElement('a');a.href='#'+id;a.textContent=t(key);nav.append(a);
  }
  const reload=document.createElement('button');reload.id='formalProfileRefresh';reload.type='button';reload.textContent=t('action.refresh');reload.onclick=refreshAccount;column.prepend(nav,reload);const access=document.createElement('section');access.id='formalAccountAccess';access.className='panel';for(const id of ['authActions','cloudAccountForm','emailVerification','consoleLink','status'])access.append($(id));const notice=column.querySelector('[data-i18n="cloud.credentials_notice"]');if(notice)access.querySelector('#cloudAccountForm').prepend(notice);reload.after(access);for(const id of ['catalogAcquireIntent','catalogClaimIntent','catalogOwnershipIntent'])$(id).classList.add('panel');
  const sections=['selfProfile','selfGuitars','selfFavorites','selfVisibility','accountAvatar','selfApplications','selfClaims','selfOwnership','selfNotifications','selfDisputes','selfIdentityCorrections'];
  for(const id of sections){const el=$(id);if(id!=='selfGuitars')el.classList.add('panel','profile-panel','page-section');column.append(el)}
  const hero=document.createElement('div');hero.className='profile-hero';const identity=document.createElement('div');identity.className='profile-identity';identity.append($('selfProfileValues'));$('avatarPreview').classList.add('profile-avatar');hero.append($('avatarPreview'),identity);$('selfProfile').insertBefore(hero,$('selfProfileEdit'));
  const stats=document.createElement('div');stats.id='formalProfileStats';stats.className='profile-stats';$('selfProfile').append(stats);
  const chronicle=document.createElement('section');chronicle.className='panel profile-panel';chronicle.id='formalUserChronicle';
  const title=document.createElement('h2'),message=document.createElement('p');title.textContent=t('ui.user_chronicle_78bcd753');message.textContent=document.documentElement.lang==='ja'?'全ギター横断のUser Chronicleは未接続です。各ギターのProduct Detailで公開Chronicleを確認できます。':'User Chronicle across all guitars is not connected yet. Open a guitar to view its public Chronicle.';chronicle.append(title,message);column.append(chronicle);
  const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',document.querySelector('.sticky-header').getBoundingClientRect().height+'px'));observer.observe(document.querySelector('.sticky-header'));
  function render(){
    const user=state()?.user,eligible=Boolean(user&&state()?.identity?.email_verified===true);
    $('accountLink').textContent=t('catalog.browse');$('shellProducts').textContent=t('catalog.browse');$('shellMembers').textContent=t('members.title');document.title='Your Guitar Chronicle — '+t('self_profile.heading');$('shellAccountLinks').hidden=!user;nav.hidden=chronicle.hidden=!eligible;access.hidden=eligible&&$('status').textContent===t('cloud.account_ready');
    $('formalProfileRefresh').disabled=busy();stats.replaceChildren();if(eligible)for(const [kind,key] of [['owned','users.owned'],['formerly_owned','users.formerly_owned']])if(totals[kind]!=null){const span=document.createElement('span');span.className='profile-stat';span.textContent=t(key)+': '+totals[kind];stats.append(span)}
  }
  function clear(){catalog?.invalidateIdentity();stats.replaceChildren()}
  async function refresh(){
    if(!state()?.user)return;
    if(!catalog)catalog=createPublicCatalog({basePath:'/ui/profile',accountPath:'/ui/profile',detailOnly:true,loadAuth:async()=>auth(),onState:s=>{$('productDetailShell').classList.toggle('compact-open',s.detailOpen);render()}});
    if(!started){started=true;await catalog.start()}else await catalog.refresh();
    // Account controllers choose their language during initialization.
    $('catalogLanguage').onchange=()=>{localStorage.setItem('ygc_ui_language',$('catalogLanguage').value);location.reload()};
    render();
  }
  window.addEventListener('keydown',event=>{if(event.key==='Escape'&&!document.querySelector('dialog[open]')&&window.matchMedia('(max-width:900px)').matches&&$('productDetailShell').classList.contains('compact-open')){event.preventDefault();void catalog?.navigate('/ui/profile')}});
  render();return {render,clear,refresh,openGuitar:id=>catalog?.navigate('/ui/profile/guitars/'+encodeURIComponent(id))};
}
