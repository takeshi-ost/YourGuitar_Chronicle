import {createDetailDispute} from './cloud-detail-dispute.js';
import {createDetailClaimActions} from './cloud-detail-claim-actions.js';
import {createProfileConnections} from './cloud-profile-connections.js';
import {createAccountHub} from './cloud-account-hub.js';
import {selectProfileGuitar} from './cloud-profile-list.js';
import {createPublicCatalog} from './cloud-public-catalog.js';
// Presentation of the canonical self-account controllers. No actor selector or
// additional profile projection: all writes retain their original API guards.
export function createFormalProfileView({auth,state,busy,totals,refreshAccount,selectedActions,openClaim,openAcquire,openOwnership,openDispute,owners,claims}){
  const $=id=>document.getElementById(id),t=(k,p={})=>globalThis.YGCI18n.t(k,p);
  const detailDispute=createDetailDispute({auth,state,busy,openDispute});
  const detailActions=createDetailClaimActions({state,busy,owners,claims});
  let catalog=null,started=false,selectionAttempted=false,selectionEpoch=0;
  const column=$('profileColumn'),hub=document.querySelector('#accountHub .account-hub-user');
  const important=document.createElement('section');important.id='importantInformation';important.className='unanswered-requests';important.append($('selfOwnerAcquire'),$('selfApplications'),$('selfOwnership'),$('selfDisputes'));$('publicCatalog').prepend(important);
  const syncImportant=()=>{important.hidden=$('selfOwnerAcquire').hidden&&$('selfApplications').hidden&&$('selfOwnership').hidden&&$('selfDisputes').hidden};for(const id of ['selfOwnerAcquire','selfApplications','selfOwnership','selfDisputes'])new MutationObserver(syncImportant).observe($(id),{attributes:true,attributeFilter:['hidden']});syncImportant();
  $('selfGuitars_owned').append($('applicationListing'));
  $('shellTitle').textContent=t('ui.user_profile_ee7672e2');$('catalogLanguage').value=globalThis.YGCI18n.locale||'en';$('catalogLanguage').onchange=()=>{localStorage.setItem('ygc_ui_language',$('catalogLanguage').value);location.reload()};
  for(const id of ['shellSignIn','shellSignOut','shellSignInDialog','shellRegister'])$(id)?.remove();
  $('shellIdentity').textContent='';hub.append($('accountSummary'));
  $('signOut').classList.add('account-hub-action');document.querySelector('#accountHub>.account-hub-actions:last-child').append($('signOut'));
  $('accountLink').href='/ui';$('accountLink').textContent=t('catalog.browse');
  $('shellProducts').href='/ui';$('shellMembers').href='/ui/members';
  $('shellProfile').textContent=t('self_profile.heading');$('shellNotifications').textContent=t('notifications.heading');
  const nav=document.createElement('nav');nav.className='page-nav';
  for(const [id,key] of [['selfProfile','ui.user_profile_ee7672e2'],['selfGuitars_owned','ui.owned_guitars_bb07d3cd'],['selfGuitars_formerly_owned','ui.formerly_owned_guitars_0769f4fa'],['selfFavorites','ui.favorite_guitars_e1514ac1'],['formalUserChronicle','ui.user_chronicle_78bcd753']]){
    const a=document.createElement('a');a.href='#'+id;a.textContent=t(key);a.onclick=event=>{
      if(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
      event.preventDefault();history.replaceState(history.state,'',location.pathname+location.search+'#'+id);
      $(id)?.scrollIntoView({block:'start'});
    };nav.append(a);
  }
  const oldNav=document.querySelector('header .page-nav');nav.prepend($('shellProducts'));nav.append($('catalogLanguage').closest('.language-picker'));$('shellMembers').hidden=true;document.body.append($('shellMembers'));oldNav.replaceWith(nav);
  const reload=document.createElement('button');reload.id='formalProfileRefresh';reload.type='button';reload.textContent=t('action.refresh');reload.onclick=refreshAccount;column.prepend(reload);reload.hidden=true;const access=document.createElement('section');access.id='formalAccountAccess';access.className='panel';for(const id of ['authActions','cloudAccountForm','emailVerification','consoleLink','status'])access.append($(id));const notice=column.querySelector('[data-i18n="cloud.credentials_notice"]');if(notice)access.querySelector('#cloudAccountForm').prepend(notice);reload.after(access);for(const id of ['catalogAcquireIntent','catalogClaimIntent','catalogOwnershipIntent'])$(id).classList.add('panel');
  const sections=['selfProfile','selfGuitars','selfFavorites','selfVisibility','accountAvatar','selfClaims','selfNotifications','selfIdentityCorrections'];
  for(const id of sections){const el=$(id);if(id!=='selfGuitars')el.classList.add('panel','profile-panel','page-section');column.append(el)}
  const hero=document.createElement('div');hero.className='profile-hero';const identity=document.createElement('div');identity.className='profile-identity';identity.append($('selfProfileValues'));$('avatarPreview').classList.add('profile-avatar');const actions=document.createElement('div');actions.className='profile-actions';actions.append($('selfProfileEdit'));hero.append($('avatarPreview'),identity,actions);$('selfProfile').prepend(hero);const profileHeading=$('selfProfile').querySelector('h2');profileHeading.textContent=t('ui.user_profile_ee7672e2');profileHeading.removeAttribute('data-i18n');$('selfProfile').prepend(profileHeading);$('selfProfileRefresh').hidden=true;
  const stats=document.createElement('div');stats.id='formalProfileStats';stats.className='profile-stats';identity.append(stats);
  const chronicle=document.createElement('section');chronicle.className='panel profile-panel';chronicle.id='formalUserChronicle';
  const title=document.createElement('h2'),message=document.createElement('p');title.textContent=t('ui.user_chronicle_78bcd753');const chronicleList=document.createElement('div');chronicleList.id='userChronicleList';chronicleList.className='profile-activity-list';title.dataset.countItems='#userChronicleList > .profile-chronicle-row';title.dataset.countPending='true';chronicle.append(title,message,chronicleList);column.append(chronicle);
  let chronicleEpoch=0;
  async function refreshChronicle(){
    const version=++chronicleEpoch,actor=state()?.user?.app_user_id;chronicleList.replaceChildren();title.dataset.countPending='true';message.textContent=t('cloud.working');if(!actor)return;
    try{const response=await auth().authorizedFetch('/api/auth/profile/chronicle',{cache:'no-store'},false);if(!response.ok)throw Error();const data=await response.json();if(version!==chronicleEpoch||actor!==state()?.user?.app_user_id)return;
      if(!Array.isArray(data.items)||data.items.length>100)throw Error();
      for(const item of data.items){if(!['User','Social','Product','Claim','Other'].includes(item.category)||['event_at','subject','message'].some(key=>typeof item[key]!=='string')||!(item.individual_id===null||typeof item.individual_id==='string'&&/^[1-9][0-9]{0,18}$/.test(item.individual_id)&&BigInt(item.individual_id)<=9223372036854775807n))throw Error();}
      for(const item of data.items){const row=document.createElement('div');row.className='profile-chronicle-row'+(item.individual_id?' clickable':'');if(item.individual_id){row.setAttribute('role','button');row.tabIndex=0;row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();row.click()}};row.onclick=()=>{if(version===chronicleEpoch&&actor===state()?.user?.app_user_id)void catalog?.navigate('/ui/profile/guitars/'+item.individual_id)}}
        const tag=document.createElement('span');tag.className='profile-chronicle-tag '+item.category.toLowerCase();tag.textContent=item.category;
        const time=document.createElement('span');time.className='profile-chronicle-time';const date=new Date(item.event_at);time.textContent=Number.isNaN(date.getTime())?item.event_at:date.toLocaleString();
        const story=document.createElement('span');story.className='profile-chronicle-story';story.textContent=item.subject+' '+item.message;const line=document.createElement('span');line.className='profile-chronicle-line';line.setAttribute('aria-hidden','true');row.append(tag,line,time,story);chronicleList.append(row);}
      title.dataset.countPending='false';message.textContent=data.items.length?'':t('ui.no_chronicle_entries_yet_f608f326');
    }catch{if(version===chronicleEpoch&&actor===state()?.user?.app_user_id){chronicleList.replaceChildren();message.textContent=t('users.profile_unavailable')}}
  }

  const notifications=document.createElement('div');notifications.id='formalNotifications';notifications.className='modal-backdrop';
  const notificationModal=document.createElement('div');notificationModal.className='modal notification-modal';notificationModal.setAttribute('role','dialog');notificationModal.setAttribute('aria-modal','true');notificationModal.setAttribute('aria-labelledby','notificationHeading');
  const closeNotifications=document.createElement('button');closeNotifications.type='button';closeNotifications.dataset.uiAction='close';closeNotifications.textContent=t('action.close');closeNotifications.onclick=()=>globalThis.YGCOverlays.close(notifications);
  const notificationActions=document.createElement('div');notificationActions.className='modal-actions';notificationActions.append($('notificationMarkAll'),closeNotifications);notificationModal.append($('selfNotifications'),notificationActions);notifications.append(notificationModal);document.body.append(notifications);
  $('selfNotifications').classList.remove('panel','profile-panel','page-section');
  const openNotifications=event=>{event?.preventDefault();if(state()?.user)globalThis.YGCOverlays.open(notifications,{opener:event?.currentTarget})};
  $('shellNotifications').onclick=openNotifications;
  const connections=createProfileConnections({auth,state,onUpdate:render});
  const accountHub=createAccountHub({auth,state,onUpdate:render,readAvatar:false,readNotifications:false});
  const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',Math.ceil(document.querySelector('.sticky-header').getBoundingClientRect().height)+'px'));observer.observe(document.querySelector('.sticky-header'));
  function render(){
    const user=state()?.user,eligible=Boolean(user&&state()?.identity?.email_verified===true);
    $('accountLink').textContent=t('catalog.browse');$('shellProducts').textContent=t('ui.top_page_272373b6');$('shellMembers').textContent=t('members.title');document.title=(user?.display_name||t('self_profile.heading'))+' — Your Guitar Chronicle';$('shellAccountLinks').hidden=!user;nav.hidden=chronicle.hidden=!eligible;access.hidden=eligible&&$('status').textContent===t('cloud.account_ready');
    $('formalProfileRefresh').disabled=busy();for(const button of document.querySelectorAll('#formalOwnershipActions button,#addClaimMenu [data-ownership-entry]'))button.disabled=busy();stats.replaceChildren();if(eligible)for(const [kind,key] of [['owned','users.owned'],['formerly_owned','users.formerly_owned']])if(totals[kind]!=null){const span=document.createElement('span');span.className='profile-stat';const strong=document.createElement('strong');strong.textContent=totals[kind];span.append(strong,document.createTextNode(' '+t(key)));stats.append(span)}if(eligible&&accountHub.counts){const span=document.createElement('span');span.className='profile-stat';const strong=document.createElement('strong');strong.textContent=accountHub.counts.claim_count;span.append(strong,document.createTextNode(' '+t('ui.claims_1c85c122')));stats.append(span)}connections.appendStats(stats);accountHub.render();detailActions.render();detailDispute.render();
  }
  function clear(){detailDispute.clear();chronicleEpoch++;chronicleList.replaceChildren();title.dataset.countPending='true';message.textContent='';detailActions.clear();connections.clear();accountHub.clear();selectionEpoch++;selectionAttempted=false;globalThis.YGCOverlays.close(notifications);catalog?.invalidateIdentity();stats.replaceChildren()}
  async function refresh({preserveView=false}={}){
    if(!state()?.user)return;
    if(!selectionAttempted&&location.pathname==='/ui/profile'&&!location.search){
      selectionAttempted=true;const owner=state().user.app_user_id,version=selectionEpoch,url=location.href;
      const owned=[...$('selfGuitars_owned').querySelectorAll('tr[data-guitar-id]')].map(row=>row.dataset.guitarId);
      let signature=null;
      try{const response=await auth().authorizedFetch('/api/auth/settings/signature',{cache:'no-store'},false);if(response.ok){const data=await response.json();if(data&&Object.keys(data).length===1&&owned.includes(data.individual_id))signature=data.individual_id}}catch{/* Existing list selection remains available when signature cannot be read. */}
      if(owner!==state()?.user?.app_user_id||version!==selectionEpoch||location.href!==url)return;
      const target=signature||owned[0]||$('selfGuitars_formerly_owned').querySelector('tr[data-guitar-id]')?.dataset.guitarId||$('selfFavorites').querySelector('tr[data-guitar-id]')?.dataset.guitarId;
      if(target)history.replaceState(history.state,'','/ui/profile/guitars/'+encodeURIComponent(target)+location.hash);
    }
    if(!catalog)catalog=createPublicCatalog({basePath:'/ui/profile',accountPath:'/ui/profile',detailOnly:true,onChronicle:detailActions.load,onClaimPopup:detailActions.popup,onClaim:openClaim,onAcquire:id=>detailDispute.blocked()?undefined:openAcquire(id),onOwnership:id=>detailDispute.blocked()?undefined:openOwnership(id),loadAuth:async()=>auth(),restoredAccount:state,onState:s=>{selectProfileGuitar(s.selectedId);$('formalOwnershipActions')?.remove();$('addClaimMenu')?.querySelector('[data-ownership-entry]')?.remove();const actions=selectedActions?.(s.selectedId);if(actions){const entry=actions.querySelector('[data-ownership-entry]');if(entry){$('addClaimMenu')?.querySelector('[data-catalog-ownership]')?.remove();entry.onclick=()=>{if(detailDispute.blocked()||busy())return;document.getElementById('addClaimMenu')?.classList.remove('open');return openOwnership(s.selectedId)};$('addClaimMenu')?.append(entry);$('acquireLink').hidden=true;}if(actions.children.length)$('detailContent').querySelector('.detail-header')?.append(actions)}$('productDetailShell').classList.toggle('compact-open',s.detailOpen);for(const button of document.querySelectorAll('#formalOwnershipActions button,#addClaimMenu [data-ownership-entry]'))button.disabled=busy();void detailDispute.sync(s)}});
    const firstLoad=!started;
    if(!started){started=true;await catalog.start()}else await catalog.refresh({reuseUserData:true,preserveView});
    // Account controllers choose their language during initialization.
    $('catalogLanguage').onchange=()=>{localStorage.setItem('ygc_ui_language',$('catalogLanguage').value);location.reload()};
    await Promise.all([firstLoad?accountHub.ready():accountHub.refresh({reuse:true}),connections.refresh(),refreshChronicle()]);if(location.hash==='#selfNotifications')openNotifications();
    render();
  }
  window.addEventListener('keydown',event=>{if(event.key==='Escape'&&!document.querySelector('dialog[open]')&&window.matchMedia('(max-width:900px)').matches&&$('productDetailShell').classList.contains('compact-open')){event.preventDefault();catalog?.closeDetail()}});
  document.addEventListener('pointerdown',event=>{if(!window.matchMedia('(max-width:900px)').matches||!$('productDetailShell').classList.contains('compact-open')||event.target.closest('#productDetailShell,.modal-backdrop.open,dialog[open]'))return;catalog?.closeDetail()});
  render();return {render,clear,refresh,openGuitar:id=>catalog?.navigate('/ui/profile/guitars/'+encodeURIComponent(id))};
}
