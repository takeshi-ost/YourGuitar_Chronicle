let individuals=[];
let newDiscoveries=[];
let activeUser=null;
let selectedIndividualId=null;
let currentClaims=[];
let ownershipAttention={attention_count:0};
let ownershipAttentionSequence=0;
let notificationData={unread_count:0,notifications:[]};
let pendingOwnershipClaimIndividualId=null;
let ownershipClaimMode='acquire';
let individualSortKey='id';
let individualSortDirection=-1;
const ACTIVE_USER_KEY='ygc_active_user_id';
// Prototype login belongs to this tab. Another console tab must not change
// the viewer of an already open profile or its Verification controls.
const launchUserId=new URLSearchParams(location.search).get('prototype_user_id');
if(launchUserId!==null){
  if(/^\d+$/.test(launchUserId)&&Number(launchUserId)>0)sessionStorage.setItem(ACTIVE_USER_KEY,launchUserId);
  else sessionStorage.removeItem(ACTIVE_USER_KEY);
  const cleaned=new URL(location.href);
  cleaned.searchParams.delete('prototype_user_id');
  history.replaceState(null,'',cleaned.pathname+cleaned.search+cleaned.hash);
}else if(sessionStorage.getItem(ACTIVE_USER_KEY)===null){
  const previous=localStorage.getItem(ACTIVE_USER_KEY);
  if(previous)sessionStorage.setItem(ACTIVE_USER_KEY,previous);
}
localStorage.removeItem(ACTIVE_USER_KEY);
function syncHeaderHeight(){
  const header=document.querySelector('.sticky-header');
  if(header)document.documentElement.style.setProperty('--header-height',Math.ceil(header.getBoundingClientRect().height)+'px');
}
if(typeof ResizeObserver==='function')new ResizeObserver(syncHeaderHeight).observe(document.querySelector('.sticky-header'));
window.addEventListener('resize',syncHeaderHeight);
syncHeaderHeight();
const PROFILE_USER_ID=Number((location.pathname.match(/^\/users\/(\d+)$/)||[])[1]||0);
let profileGuitars=[];
let profileFavorites=[];
let favoriteIds=new Set();
const profileSort={owned:{key:'id',direction:1},former:{key:'id',direction:1},favorites:{key:'id',direction:1}};
function applyTheme(theme){document.documentElement.dataset.theme=theme||'dark_default'}

const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
async function jfetch(url,opt={}){
  const headers=new Headers(opt.headers||{});
  headers.set('X-YGC-Timezone',Intl.DateTimeFormat().resolvedOptions().timeZone);
  const r=await fetch(url,{...opt,headers});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(globalThis.YGCI18n?.errorMessage(d,r.statusText)??(Array.isArray(d.detail)?d.detail.map(e=>e.msg).join(' / '):(d.detail||r.statusText)));
  return d;
}
function favoriteButton(id){
  if(!activeUser||!activeUser.user)return '';
  const selected=favoriteIds.has(Number(id));
  return '<button type="button" class="favorite-button'+(selected?' is-favorite':'')+'" aria-label="'+(selected?(globalThis.YGCI18n?.t("ui.remove_from_favorites_18720329",{},"Remove from favorites")??"Remove from favorites"):(globalThis.YGCI18n?.t("ui.add_to_favorites_7f3c0782",{},"Add to favorites")??"Add to favorites"))+'" aria-pressed="'+selected+'" title="'+(selected?(globalThis.YGCI18n?.t("ui.remove_from_favorites_18720329",{},"Remove from favorites")??"Remove from favorites"):(globalThis.YGCI18n?.t("ui.add_to_favorites_7f3c0782",{},"Add to favorites")??"Add to favorites"))+'" onclick="toggleFavorite(event,'+Number(id)+')">'+(selected?'♥':'♡')+'</button>';
}
async function toggleFavorite(event,id){
  event.stopPropagation();
  if(!activeUser||!activeUser.user)return;
  const wasFavorite=favoriteIds.has(Number(id));
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/favorites/'+id,{method:wasFavorite?'DELETE':'PUT'});
    if(wasFavorite)favoriteIds.delete(Number(id));else favoriteIds.add(Number(id));
    renderIndividuals();
    if(PROFILE_USER_ID){
      if(Number(activeUser.user.id)===PROFILE_USER_ID){
        const profile=await jfetch('/api/users/'+PROFILE_USER_ID+'/profile?viewer_id='+Number(activeUser.user.id));
        profileFavorites=profile.favorites||[];
      }
      for(const section of ['owned','former','favorites'])renderProfileGuitars(section);
    }
    document.querySelectorAll('#detail .favorite-button').forEach(button=>{
      if(Number(selectedIndividualId)!==Number(id))return;
      const selected=favoriteIds.has(Number(id));
      button.textContent=selected?'♥':'♡';button.classList.toggle('is-favorite',selected);
      button.setAttribute('aria-pressed',String(selected));
      button.setAttribute('aria-label',selected?(globalThis.YGCI18n?.t("ui.remove_from_favorites_18720329",{},"Remove from favorites")??"Remove from favorites"):(globalThis.YGCI18n?.t("ui.add_to_favorites_7f3c0782",{},"Add to favorites")??"Add to favorites"));
      button.title=button.getAttribute('aria-label');
    });
  }catch(e){alert((globalThis.YGCI18n?.t("ui.favorite_could_not_be_updated_3f3222a4",{},"Favorite could not be updated.")??"Favorite could not be updated.")+"\n"+e.message)}
}
function renderAccountHub(){
  const hub=document.getElementById('accountHub');
  if(!hub)return;
  if(!activeUser||!activeUser.user){
    hub.innerHTML=
      '<div class="account-hub-user">'+
        '<div class="account-hub-guest-mark">YGC</div>'+
        '<div class="account-hub-user-copy">'+
          ("<div class=\"account-hub-guest-title\">"+(globalThis.YGCI18n?.html("ui.explore_guitar_histories_add_yours_when_you_are_ready_41836874",{},"Explore guitar histories. Add yours when you are ready.")??"Explore guitar histories. Add yours when you are ready.")+"</div>")+
          ("<div class=\"account-hub-guest-copy\">"+(globalThis.YGCI18n?.html("ui.guests_can_browse_the_product_list_and_chronicle_create_an_4fb1442d",{},"Guests can browse the Product List and Chronicle. Create an account to contribute to the history of a guitar that matters to you.")??"Guests can browse the Product List and Chronicle. Create an account to contribute to the history of a guitar that matters to you.")+"</div>")+
        '</div>'+
      '</div>'+
      '<div></div>'+
      '<div class="account-hub-actions">'+
        ("<button class=\"account-hub-action\" type=\"button\" onclick=\"openAccountSignIn()\">"+(globalThis.YGCI18n?.html("account.sign_in",{},"Sign In")??"Sign In")+"</button>")+
        ("<button data-ui-action=\"primary\" class=\"account-hub-action primary\" type=\"button\" onclick=\"openAccountRegistration()\">"+(globalThis.YGCI18n?.html("account.create",{},"Create Account")??"Create Account")+"</button>")+
      '</div>';
    return;
  }
  const u=activeUser.user;
  const summary=activeUser.summary||{};
  const guitars=activeUser.guitars||[];
  const owned=summary.owned_count??guitars.filter(g=>g.ownership_status==='current_owner').length;
  const former=summary.former_count??guitars.filter(g=>g.ownership_status==='former_owner').length;
  const claims=summary.claim_count??0;
  const location=[u.location_country,u.location_region].filter(Boolean).join(' / ')||(globalThis.YGCI18n?.t("ui.location_not_set_0ccd1c0b",{},"Location not set")??"Location not set");
  hub.innerHTML=
    '<a class="account-hub-user account-hub-user-link" href="/users/'+Number(u.id)+'" aria-label="View '+esc(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+' profile">'+
      '<img class="account-hub-avatar" src="/api/users/'+u.id+'/avatar?viewer_id='+Number(activeUser.user.id)+'&v='+encodeURIComponent(u.updated_at||'')+'" alt="'+esc(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="account-hub-user-copy">'+
        '<div class="account-hub-name-row"><span class="account-hub-name">'+esc(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+'</span></div>'+
        '<div class="account-hub-location">'+esc(location)+'</div>'+
      '</div>'+
    '</a>'+
    '<div class="account-hub-summary">'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+owned+("</span><span class=\"account-hub-stat-label\">"+(globalThis.YGCI18n?.html("ui.owned_17b760c4",{},"Owned")??"Owned")+"</span></div>")+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+former+("</span><span class=\"account-hub-stat-label\">"+(globalThis.YGCI18n?.html("ui.formerly_owned_65b08593",{},"Formerly Owned")??"Formerly Owned")+"</span></div>")+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+claims+("</span><span class=\"account-hub-stat-label\">"+(globalThis.YGCI18n?.html("ui.claims_1c85c122",{},"Claims")??"Claims")+"</span></div>")+
    '</div>'+
    '<div class="account-hub-actions">'+
      ("<button class=\"account-hub-action\" type=\"button\" onclick=\"toggleNotifications()\">"+(globalThis.YGCI18n?.html("header.notifications",{},"Notifications")??"Notifications")+" "+"<span class=\"account-hub-count\" id=\"notificationCount\">")+Number(notificationData.unread_count||0)+'</span></button>'+
      ("<button class=\"account-hub-action\" type=\"button\" onclick=\"openDirectMessages()\">"+(globalThis.YGCI18n?.html("header.messages",{},"Messages")??"Messages")+" "+"<span class=\"account-hub-count\" id=\"directMessageCount\">")+Number(dmInbox.unread_count||0)+'</span></button>'+
      ("<button class=\"account-hub-action\" type=\"button\" onclick=\"logoutUser(this)\">"+(globalThis.YGCI18n?.html("account.sign_out",{},"SignOut")??"SignOut")+"</button>")+
    '</div>';
  updateUnreadHeaderAction('notificationCount',notificationData.unread_count);
  updateUnreadHeaderAction('directMessageCount',dmInbox.unread_count);
}

function updateUnreadHeaderAction(countId,unreadCount){
  const count=document.getElementById(countId);
  if(!count)return;
  count.textContent=String(Number(unreadCount||0));
  const button=count.closest('button');
  if(!button)return;
  const unread=Number(unreadCount||0)>0;
  button.classList.toggle('primary',unread);
  if(unread)button.setAttribute('data-ui-action','primary');
  else button.removeAttribute('data-ui-action');
}

let registrationDocuments=null;
async function openAccountRegistration(){
  closeAccountRequired();
  document.getElementById('accountRegistrationForm').reset();
  document.getElementById('accountRegistrationStatus').textContent='';
  YGCOverlays.open('accountRegistrationModal',{initialFocus:'#registrationEmail',onClose:()=>document.getElementById('accountRegistrationForm').reset()});
  registrationDocuments=null;
  document.getElementById('accountRegistrationSubmit').disabled=true;
  try{registrationDocuments=(await jfetch('/api/local-auth/registration')).documents;document.getElementById('accountRegistrationSubmit').disabled=false}
  catch(error){document.getElementById('accountRegistrationStatus').textContent=error.message}

}
function showRegistrationPolicy(kind){
  const policy=registrationDocuments?.[kind];if(!policy)return;
  document.getElementById('registrationPolicyTitle').textContent=policy.title;
  document.getElementById('registrationPolicyContent').innerHTML=("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.version_4c5726ee",{},"Version:")??"Version:")+" ")+esc(policy.version)+'</p>'+policy.paragraphs.map(text=>'<p>'+esc(text)+'</p>').join('');
  YGCOverlays.open('registrationPolicyModal');
}
let signInUserLoadSequence=0;
async function openAccountSignIn(){
  const sequence=++signInUserLoadSequence;
  closeAccountRequired();
  document.getElementById('accountSignInForm').reset();
  document.getElementById('accountSignInStatus').textContent='';
  const select=document.getElementById('signInUser');
  const submit=document.getElementById('accountSignInSubmit');
  select.disabled=true;submit.disabled=true;
  select.innerHTML=("<option value=\"\">"+(globalThis.YGCI18n?.html("ui.loading_users_904e120b",{},"Loading users...")??"Loading users...")+"</option>");
  YGCOverlays.open('accountSignInModal',{initialFocus:'#signInEmail',onClose:()=>{++signInUserLoadSequence;document.getElementById('accountSignInForm').reset()}});
  try{
    const users=await jfetch('/api/users');
    if(sequence!==signInUserLoadSequence)return;
    select.innerHTML=users.length?users.map(user=>'<option value="'+Number(user.id)+'">#'+Number(user.id)+' · '+esc(user.display_name)+'</option>').join(''):("<option value=\"\">"+(globalThis.YGCI18n?.html("ui.no_users_available_042f8655",{},"No users available")??"No users available")+"</option>");
    const last=sessionStorage.getItem('ygc_last_user_id');
    if(users.some(user=>String(user.id)===last))select.value=last;
    select.disabled=!users.length;submit.disabled=!users.length;
    if(!users.length)document.getElementById('accountSignInStatus').textContent=(globalThis.YGCI18n?.t("ui.create_an_account_first_to_use_test_sign_in_a9eba929",{},"Create an account first to use test sign-in.")??"Create an account first to use test sign-in.");
  }catch(error){if(sequence===signInUserLoadSequence)document.getElementById('accountSignInStatus').textContent=error.message}
}
let accountSignInBusy=false;
async function submitAccountSignIn(event){
  event.preventDefault();
  if(accountSignInBusy)return;
  const testUserId=Number(document.getElementById('signInUser').value);
  if(!testUserId)return;
  const button=document.getElementById('accountSignInSubmit');
  accountSignInBusy=true;button.disabled=true;
  try{
    // The dummy adapter discards these transient values without sending/storing them.
    await YGCAuth.signIn({email:document.getElementById('signInEmail').value,password:document.getElementById('signInPassword').value},{testUserId});
    document.getElementById('accountSignInForm').reset();
    location.assign('/user-view');
  }catch(error){document.getElementById('accountSignInStatus').textContent=error.message}
  finally{accountSignInBusy=false;button.disabled=false}
}
let accountRegistrationBusy=false;
async function submitAccountRegistration(event){
  event.preventDefault();
  if(accountRegistrationBusy)return;
  const form=document.getElementById('accountRegistrationForm');
  const button=document.getElementById('accountRegistrationSubmit');
  accountRegistrationBusy=true;button.disabled=true;
  try{
    // The credentials are intentionally neither read nor sent to the server.
    if(!registrationDocuments)throw Error((globalThis.YGCI18n?.t("ui.agreement_documents_are_not_available_2b118245",{},"Agreement documents are not available.")??"Agreement documents are not available."));
    await YGCAuth.register({account_type:document.getElementById('registrationAccountType').value,display_name:document.getElementById('registrationDisplayName').value.trim(),terms_accepted:document.getElementById('registrationTerms').checked,privacy_accepted:document.getElementById('registrationPrivacy').checked,terms_version:registrationDocuments.terms.version,privacy_version:registrationDocuments.privacy.version});
    form.reset();
    location.assign('/user-view');
  }catch(error){document.getElementById('accountRegistrationStatus').textContent=error.message}
  finally{accountRegistrationBusy=false;button.disabled=false}
}
async function logoutUser(button){
  button.disabled=true;
  try{await YGCLocalAuth.logout()}
  catch(error){alert(error.message);button.disabled=false}
}

function renderNotificationPanel(){
  const list=document.getElementById('notificationList');
  if(!list)return;
  const items=notificationData.notifications||[];
  list.innerHTML=items.length
    ? items.map(n=>
        '<button type="button" class="notification-item'+(Number(n.is_read)?'':' unread')+'" onclick="openNotification('+n.id+','+(n.individual_id===null?'null':Number(n.individual_id))+')">'+
          '<div class="notification-item-title">'+esc(n.title||(globalThis.YGCI18n?.t("ui.notification_7d31b833",{},"Notification")??"Notification"))+'</div>'+
          '<div class="notification-item-body">'+esc(n.body||'')+'</div>'+
          '<div class="notification-item-time">'+esc(displayInputDate(n.created_at))+'</div>'+
        '</button>'
      ).join('')
    : ("<div class=\"notification-empty\">"+(globalThis.YGCI18n?.html("ui.no_notifications_0b78998d",{},"No notifications.")??"No notifications.")+"</div>");
  updateUnreadHeaderAction('notificationCount',notificationData.unread_count);
}
async function loadNotifications(){
  if(!activeUser||!activeUser.user){
    notificationData={unread_count:0,notifications:[]};
    renderNotificationPanel();
    return;
  }
  try{
    notificationData=await jfetch('/api/users/'+activeUser.user.id+'/notifications');
  }catch(e){
    notificationData={unread_count:0,notifications:[]};
  }
  renderNotificationPanel();
}
async function toggleNotifications(){
  const panel=document.getElementById('notificationPanel');
  if(!panel)return;
  if(panel.classList.contains('open')){YGCOverlays.close(panel);return}
  await loadNotifications();
  YGCOverlays.open(panel);
}
async function openNotification(notificationId,individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/notifications/'+notificationId+'/read',{method:'POST'});
  }catch(e){}
  const item=(notificationData.notifications||[]).find(n=>Number(n.id)===Number(notificationId));
  if(item)item.is_read=1;
  notificationData.unread_count=Math.max(0,Number(notificationData.unread_count||0)-(item&&Number(item.is_read)===0?1:0));
  await loadNotifications();
  if(typeof YGCImportantInformation!=='undefined')YGCImportantInformation.refresh();
  const panel=document.getElementById('notificationPanel');
  if(panel)YGCOverlays.close(panel);
  if(item&&item.notification_type?.startsWith('transfer_')&&item.claim_id){if(individualId)await showIndividual(Number(individualId),true);await openTransferReview(Number(item.claim_id));return}
  if(individualId!==null&&individualId!==undefined)await showIndividual(Number(individualId),true);
}
async function markAllNotificationsRead(){
  if(!activeUser||!activeUser.user)return;
  try{
    await jfetch('/api/users/'+activeUser.user.id+'/notifications/read-all',{method:'POST'});
    await loadNotifications();
    if(typeof YGCImportantInformation!=='undefined')YGCImportantInformation.refresh();
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.could_not_mark_the_notification_as_read_2d629646",{},"Could not mark the notification as read.")??"Could not mark the notification as read.")+"\n"+e.message);
  }
}

let unansweredSequence=0,unansweredBusy=false;
async function loadUnansweredRequests(){
  const section=document.getElementById('unansweredRequests');if(!section)return;
  const userId=activeUser?.user?.id,sequence=++unansweredSequence;
  if(!userId){section.hidden=true;section.innerHTML='';return}
  try{
    const rows=await jfetch('/api/ownership-requests/unanswered?viewer_id='+Number(userId));
    if(sequence!==unansweredSequence||activeUser?.user?.id!==userId)return;
    section.hidden=!rows.length;
    section.innerHTML=rows.map(r=>
      '<div class="unanswered-request"><p>'+(r.kind==='transfer'?(globalThis.YGCI18n?.t("ui.transfer_9e0d719a",{},"Transfer ·")??"Transfer ·")+" ":(globalThis.YGCI18n?.t("ui.acquire_735f47ae",{},"Acquire ·")??"Acquire ·")+" ")+YGCProductDetail.userLink(r.sender_id,r.sender_name,esc)+
      (r.kind==='transfer'?' has offered to transfer ':' is claiming ownership of ')+
      '<a href="/users/'+Number(userId)+'?individual_id='+Number(r.individual_id)+'">'+esc(r.guitar||((globalThis.YGCI18n?.t("ui.guitar_ef54df12",{},"Guitar #")??"Guitar #")+r.individual_id))+'</a>'+(r.kind==='transfer'?" "+(globalThis.YGCI18n?.t("ui.to_you_40d474b0",{},"to you.")??"to you."):'.')+
      '</p><div><button data-ui-action="primary" onclick="answerOwnershipRequest('+Number(r.claim_id)+',&quot;'+r.kind+'&quot;,true,'+Number(r.individual_id)+')">Accept</button> '+
      '<button class="secondary" onclick="answerOwnershipRequest('+Number(r.claim_id)+',&quot;'+r.kind+'&quot;,false,'+Number(r.individual_id)+(")\">"+(globalThis.YGCI18n?.html("ui.decline_a2d285b3",{},"Decline")??"Decline")+"</button></div></div>")).join('');
  }catch(error){if(sequence!==unansweredSequence||activeUser?.user?.id!==userId)return;section.hidden=false;section.textContent=(globalThis.YGCI18n?.t("ui.unable_to_load_unanswered_requests_please_refresh_f110efc3",{},"Unable to load unanswered requests. Please refresh.")??"Unable to load unanswered requests. Please refresh.")}
}
async function answerOwnershipRequest(claimId,kind,accept,individualId){
  if(unansweredBusy||!activeUser?.user)return;
  const userId=activeUser.user.id;
  const reason=kind==='acquire'&&!accept?prompt((globalThis.YGCI18n?.t("ui.why_are_you_declining_this_acquire_your_reason_will_be_sha_0a154dc0",{},"Why are you declining this Acquire? Your reason will be shared with the applicant.")??"Why are you declining this Acquire? Your reason will be shared with the applicant.")):null;
  if(kind==='acquire'&&!accept&&!reason?.trim())return;
  if(!await confirmOwnershipAction(accept?'Accept':(globalThis.YGCI18n?.t("ui.decline_a2d285b3",{},"Decline")??"Decline"),accept?(globalThis.YGCI18n?.t("ui.accept_this_ownership_request_04be7008",{},"Accept this ownership request?")??"Accept this ownership request?"):(globalThis.YGCI18n?.t("ui.decline_this_ownership_request_a1a0b51a",{},"Decline this ownership request?")??"Decline this ownership request?")))return;
  if(activeUser?.user?.id!==userId)return;
  unansweredBusy=true;
  try{
    const url=kind==='transfer'?'/api/transfers/'+claimId+'/resolve?viewer_id='+Number(userId):'/api/claims/'+claimId+'/response';
    const body=kind==='transfer'?{action:accept?'accept':'decline'}:{responder_user_id:userId,stance:accept?'positive':'negative',reason};
    await jfetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    await refreshClaimViews(individualId);
  }catch(error){alert(error.message)}finally{unansweredBusy=false;await loadUnansweredRequests();if(typeof YGCImportantInformation!=='undefined')YGCImportantInformation.refresh()}
}
if(typeof setInterval==='function')setInterval(()=>{if(!document.hidden&&!unansweredBusy)loadUnansweredRequests()},30000);

async function loadActiveUser(){
  const id=sessionStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    await loadUnansweredRequests();
    if(!PROFILE_USER_ID)applyTheme('sunburst_3ply');
    favoriteIds=new Set();
    notificationData={unread_count:0,notifications:[]};
    ownershipAttention={attention_count:0};++ownershipAttentionSequence;
    renderAccountHub();
    renderNotificationPanel();
    return;
  }
  try{
    activeUser=await jfetch('/api/users/'+id);
    if(!PROFILE_USER_ID)applyTheme(activeUser.user.theme);
    favoriteIds=new Set(await jfetch('/api/users/'+id+'/favorites'));
  }catch(e){
    if(globalThis.YGCI18n?.changingLanguage)return;
    activeUser=null;
    await loadUnansweredRequests();
    if(!PROFILE_USER_ID)applyTheme('sunburst_3ply');
    favoriteIds=new Set();
    sessionStorage.removeItem(ACTIVE_USER_KEY);
  }
  await loadNotifications();
  await loadDirectMessageInbox();
  await loadOwnershipAttention();
  if(typeof YGCDisputes!=='undefined')await YGCDisputes.refresh();
  await loadUnansweredRequests();
  renderAccountHub();
  renderNotificationPanel();
}

async function loadNewDiscoveries(){
  try{
    const viewer=activeUser?.user?.id;
    newDiscoveries=await jfetch('/api/new-discoveries'+(viewer?'?viewer_id='+Number(viewer):''));
  }catch(e){
    newDiscoveries=[];
  }
  renderNewDiscoveries();
}
function discoveryMessage(item){
  const type=String(item.claim_type||'').toLowerCase();
  if(item.activity_type!=='claim')return (globalThis.YGCI18n?.t("ui.has_been_newly_added_to_the_list_941264a3",{},"has been newly added to the list!")??"has been newly added to the list!");
  if(type==='listing')return (globalThis.YGCI18n?.t("ui.has_been_newly_added_to_the_list_941264a3",{},"has been newly added to the list!")??"has been newly added to the list!");
  if(type==='specification')return (globalThis.YGCI18n?.t("ui.has_new_specifications_on_record_8382859d",{},"has new specifications on record!")??"has new specifications on record!");
  if(type==='incident')return (globalThis.YGCI18n?.t("ui.has_a_new_incident_report_05503b69",{},"has a new incident report!")??"has a new incident report!");
  if(type==='event')return (globalThis.YGCI18n?.t("ui.has_a_new_event_in_its_history_793392cb",{},"has a new event in its history!")??"has a new event in its history!");
  if(type==='media')return (globalThis.YGCI18n?.t("ui.has_new_media_added_19e67ff9",{},"has new media added!")??"has new media added!");
  if(type==='ownership')return (globalThis.YGCI18n?.t("ui.has_a_new_ownership_update_5aa474f2",{},"has a new ownership update!")??"has a new ownership update!");
  if(type==='identity_correction')return (globalThis.YGCI18n?.t("ui.has_received_an_identity_correction_584dbf57",{},"has received an identity correction!")??"has received an identity correction!");
  return (globalThis.YGCI18n?.t("ui.has_secured_a_new_claim_4798d884",{},"has secured a new claim!")??"has secured a new claim!");
}
function discoveryProductName(item){
  const base=[item.manufacturer,item.model].filter(Boolean).join(' ').trim()||((globalThis.YGCI18n?.t("ui.product_1d8887e5",{},"Product #")??"Product #")+item.id);
  const year=item.year?' ('+item.year+')':'';
  const finish=item.finish?' '+item.finish:'';
  return base+year+finish;
}
function discoveryActorHtml(item){
  if(item.activity_type!=='following'||!item.actor_user_id)return '';
  return '<a class="discovery-actor" href="/users/'+Number(item.actor_user_id)+'" onclick="event.stopPropagation()">'+esc(item.actor_name)+("</a> <span class=\"discovery-following\">"+(globalThis.YGCI18n?.html("ui.following_344b4271",{},"Following")??"Following")+"</span>");
}
function followingDiscoveryMessage(item){
  if(item.action_kind==='vote')return 'gave a '+String(item.action_value||'')+' vote to a Claim on';
  const kind=item.claim_type==='ownership'?(item.ownership_kind||(globalThis.YGCI18n?.t("ui.acquire_910e23d5",{},"Acquire")??"Acquire")):
    item.claim_type==='specification'&&item.specification_kind==='repair'?(globalThis.YGCI18n?.t("ui.repair_1196b6c5",{},"Repair")??"Repair"):item.claim_type;
  const label=String(kind||(globalThis.YGCI18n?.t("ui.claim_4ca41db0",{},"Claim")??"Claim")).replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  return 'added '+(/^[AEIOU]/.test(label)?'an ':'a ')+label+" "+(globalThis.YGCI18n?.t("ui.claim_to_5eb6a71e",{},"Claim to")??"Claim to");
}
function renderNewDiscoveries(){
  const root=document.getElementById('newDiscoveryList');
  if(!root)return;
  if(!newDiscoveries.length){
    root.innerHTML=("<div class=\"sub\" style=\"padding:10px\">"+(globalThis.YGCI18n?.html("ui.no_recent_activity_44b67bb3",{},"No recent activity.")??"No recent activity.")+"</div>");
    return;
  }
  root.innerHTML=newDiscoveries.map(item=>{
    const when=displayDiscoveryDateTime(item.activity_at||'');
    const product=discoveryProductName(item);
    const message=item.activity_type==='following'?String(item.actor_name||'')+' '+followingDiscoveryMessage(item):discoveryMessage(item);
    return '<div class="discovery-item" onclick="showIndividual('+Number(item.id)+',true)" title="'+esc(when+' '+product+' '+message)+'">'+
      '<span class="discovery-time">'+esc(when)+'</span>'+
      '<span class="discovery-story">'+(item.activity_type==='following'?discoveryActorHtml(item)+' '+esc(followingDiscoveryMessage(item))+' <strong>'+esc(product)+'</strong>':'<strong>'+esc(product)+'</strong> '+esc(message))+'</span>'+
    '</div>';
  }).join('');
}

async function loadIndividuals(){
  individuals=await jfetch('/api/individuals');
  renderIndividuals();
}
function normalizeSortValue(value,key){
  if(key==='id'||key==='claim_count')return Number(value||0);
  return String(value??'').toLowerCase();
}
function setIndividualSort(key){
  if(individualSortKey===key)individualSortDirection*=-1;
  else{individualSortKey=key;individualSortDirection=1}
  renderIndividuals();
  document.getElementById('individualBody').closest('.table-wrap').scrollTop=0;
}
function updateSortIndicators(){
  for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){
    const el=document.getElementById('sort-'+key);
    if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):'';
  }
}
// Use unfiltered counts; filtering never changes the outer list height.
function sizeGuitarList(panel,count){
  if(!panel)return;
  panel.dataset.totalItems=String(count);
  if(!panel._sizeObserver&&typeof ResizeObserver==='function'){
    panel._sizeObserver=new ResizeObserver(()=>measureGuitarList(panel));
    panel._sizeObserver.observe(panel);
    for(const child of panel.children)if(!child.classList.contains('table-wrap'))panel._sizeObserver.observe(child);
  }
  measureGuitarList(panel);
}
function measureGuitarList(panel){
  const wrap=panel.querySelector('.table-wrap'),table=wrap?.querySelector('table');
  if(!table)return;
  const probe=table.cloneNode(false);
  probe.removeAttribute('id');
  probe.style.cssText='position:absolute;visibility:hidden;pointer-events:none;width:'+table.getBoundingClientRect().width+'px';
  probe.innerHTML=("<tbody><tr><td>0</td><td class=\"favorite-cell\"><button class=\"favorite-button\">♡</button></td><td>"+(globalThis.YGCI18n?.html("ui.maker_287f4955",{},"Maker")??"Maker")+"</td><td>"+(globalThis.YGCI18n?.html("ui.model_5e2c614c",{},"Model")??"Model")+"</td><td>"+(globalThis.YGCI18n?.html("ui.finish_a6c7a84b",{},"Finish")??"Finish")+"</td><td>"+(globalThis.YGCI18n?.html("ui.year_89f68325",{},"Year")??"Year")+"</td><td>"+(globalThis.YGCI18n?.html("ui.serial_8ea09493",{},"Serial")??"Serial")+"</td><td>0</td></tr></tbody>");
  wrap.append(probe);
  const rowHeight=probe.rows[0].getBoundingClientRect().height;
  probe.remove();
  const css=getComputedStyle(panel),wc=getComputedStyle(wrap);
  const px=v=>parseFloat(v)||0;
  let height=px(css.paddingTop)+px(css.paddingBottom)+px(css.borderTopWidth)+px(css.borderBottomWidth);
  for(const child of panel.children){
    if(child===wrap||getComputedStyle(child).display==='none')continue;
    const style=getComputedStyle(child);
    height+=child.getBoundingClientRect().height+px(style.marginTop)+px(style.marginBottom);
  }
  height+=(table.tHead?.getBoundingClientRect().height||0)+rowHeight*Math.max(1,Number(panel.dataset.totalItems)||0)+px(wc.borderTopWidth)+px(wc.borderBottomWidth)+2;
  panel.style.setProperty('--list-content-height',Math.ceil(height)+'px');
}
window.addEventListener('resize',()=>document.querySelectorAll('[data-total-items]').forEach(measureGuitarList));
document.fonts?.ready.then(()=>document.querySelectorAll('[data-total-items]').forEach(measureGuitarList));

function renderIndividuals(){
  if(PROFILE_USER_ID)return;
  const q=document.getElementById('individualFilter').value.toLowerCase();
  const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{
    const av=normalizeSortValue(a[individualSortKey],individualSortKey);
    const bv=normalizeSortValue(b[individualSortKey],individualSortKey);
    if(av<bv)return-1*individualSortDirection;
    if(av>bv)return 1*individualSortDirection;
    return Number(a.id)-Number(b.id);
  });
  updateSortIndicators();
  document.getElementById('individualBody').innerHTML=rows.map(x=>
    '<tr class="clickable'+(Number(x.id)===Number(selectedIndividualId)?' selected':'')+'" onclick="showIndividual('+x.id+',true)"><td>'+x.id+'</td><td class="favorite-cell">'+favoriteButton(x.id)+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td></tr>'
  ).join('');
  sizeGuitarList(document.getElementById('products'),individuals.length);
}

function currentSnapshotOwnerHtml(i){
  if(!i)return '—';
  const name=String(i.current_owner_name||'').trim();
  if(!name)return '—';
  const type=String(i.current_owner_type||'').trim();
  const listingUrl=String(i.current_owner_source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(i.current_owner_user_id&&activeUser&&activeUser.user){
    const you=Number(i.current_owner_user_id)===Number(activeUser.user.id)?'':'';
    return '<a href="/users/'+Number(i.current_owner_user_id)+'">'+esc(label)+'</a>'+you;
  }
  if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';
  return esc(label);
}
function currentLocationHtml(o){
  if(!o)return '—';
  const country=String(o.location_country||'').trim();
  const region=String(o.location_region||'').trim();
  const value=[country,region].filter(Boolean).join(' / ');
  return value?esc(value):'—';
}
function activeUserOwns(individualId){
  return !!(activeUser&&(activeUser.guitars||[]).some(g=>Number(g.individual_id)===Number(individualId)&&g.ownership_status==='current_owner'));
}
function requireAccount(){
  const modal=document.getElementById('accountRequiredModal');
  if(modal)YGCOverlays.open(modal);
}
function closeAccountRequired(event){
  if(event&&event.target&&event.target.id!=='accountRequiredModal')return;
  const modal=document.getElementById('accountRequiredModal');
  if(modal)YGCOverlays.close(modal);
}
function ownershipControlsHtml(individual){
  const individualId=Number(individual.id);
  const actorNote=PROFILE_USER_ID&&activeUser&&activeUser.user
    && PROFILE_USER_ID!==Number(activeUser.user.id)
    ? ("<div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.signed_in_as_abc50e33",{},"Signed in as")??"Signed in as")+" ")+esc(activeUser.user.display_name||((globalThis.YGCI18n?.t("ui.user_f0478c1a",{},"User #")??"User #")+activeUser.user.id))+'</div>'
    : '';
  if(individual.ownership_dispute_id)return actorNote+'<button type="button" class="owner-claim-card" onclick="YGCDisputes.open('+Number(individual.ownership_dispute_id)+(")\">"+(globalThis.YGCI18n?.html("ui.under_dispute_005fd7a2",{},"Under dispute")??"Under dispute")+"</button>");
  if(activeUser&&activeUser.user&&individual.current_owner_user_id!==null
     && Number(individual.current_owner_user_id)===Number(activeUser.user.id)){
    return actorNote;
  }
  if(individual.acquire_application)return actorNote+'<button onclick="viewAcquireApplication(\''+esc(individual.acquire_application.revision)+'\')">'+esc(acquireStatusLabel(individual.acquire_application))+'</button>';
  if(individual.current_owner_user_id)return actorNote;
  const action=activeUser&&activeUser.user?'openOwnerClaim('+individualId+')':'requireAccount()';
  return actorNote+'<button type="button" class="owner-claim-card" onclick="'+action+("\">"+(globalThis.YGCI18n?.html("ui.if_you_are_the_rightful_owner_of_this_you_can_claim_it_by__b007f520",{},"If you are the rightful owner of this, you can claim it by providing some evidence!")??"If you are the rightful owner of this, you can claim it by providing some evidence!")+"</button>");
}

function ownershipClaimMenuHtml(individual){
  if(individual.ownership_dispute_id)return ("<button disabled title=\"Ownership changes are paused while this guitar is under dispute\" data-i18n-title=\"ui.ownership_changes_are_paused_while_this_guitar_is_under_di_ae3cb9c1\">"+(globalThis.YGCI18n?.html("ui.ownership_paused_62f4e1e6",{},"Ownership — paused")??"Ownership — paused")+"</button>")+(activeUserOwns(individual.id)?'':("<button disabled title=\"Ownership changes are paused while this guitar is under dispute\" data-i18n-title=\"ui.ownership_changes_are_paused_while_this_guitar_is_under_di_ae3cb9c1\">"+(globalThis.YGCI18n?.html("ui.former_owner_paused_51105546",{},"Former Owner — paused")??"Former Owner — paused")+"</button>"));
  if(activeUserOwns(individual.id))return ("<button onclick=\"chooseClaimType('ownership')\">"+(globalThis.YGCI18n?.html("ui.ownership_c7d3acc8",{},"Ownership")??"Ownership")+"</button>");
  const acquire=individual.current_owner_user_id
    ? ("<button onclick=\"chooseClaimType('acquire')\">"+(globalThis.YGCI18n?.html("ui.ownership_c7d3acc8",{},"Ownership")??"Ownership")+"</button>") : '';
  return acquire+("<button onclick=\"chooseClaimType('former_owner')\">"+(globalThis.YGCI18n?.html("ui.former_owner_68bdd82b",{},"Former Owner")??"Former Owner")+"</button>");
}

function productGalleryHtml(images,model){return YGCProductGallery.render(images,model,esc)}
function stepProductGallery(delta){YGCProductGallery.step(delta)}
function openProductAlbum(){YGCProductGallery.open()}
function specificationFieldLabel(value){
  const labels={
    nut:(globalThis.YGCI18n?.t("ui.nut_67c45877",{},"Nut")??"Nut"),
    frets:(globalThis.YGCI18n?.t("ui.frets_08aa1381",{},"Frets")??"Frets"),
    pickguard:(globalThis.YGCI18n?.t("ui.pickguard_280dde37",{},"Pickguard")??"Pickguard"),
    potentiometers:(globalThis.YGCI18n?.t("ui.potentiometers_5beb07c1",{},"Potentiometers")??"Potentiometers"),
    wiring:(globalThis.YGCI18n?.t("ui.wiring_72529059",{},"Wiring")??"Wiring"),
    neck:(globalThis.YGCI18n?.t("ui.neck_6b27a971",{},"Neck")??"Neck"),
    pickups:(globalThis.YGCI18n?.t("ui.pickups_088cf7e8",{},"Pickups")??"Pickups"),
    bridge:(globalThis.YGCI18n?.t("ui.bridge_3892e103",{},"Bridge")??"Bridge"),
    tuners:(globalThis.YGCI18n?.t("ui.tuners_1de22981",{},"Tuners")??"Tuners"),
    body:(globalThis.YGCI18n?.t("ui.body_6ccaa641",{},"Body")??"Body"),
    fingerboard:(globalThis.YGCI18n?.t("ui.fingerboard_92d85445",{},"Fingerboard")??"Fingerboard"),
    finish:(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish"),
    weight:(globalThis.YGCI18n?.t("ui.weight_81d27ef6",{},"Weight")??"Weight")
  };
  const key=String(value||'').trim();
  return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase());
}
function identityFieldLabel(value){
  const labels={
    manufacturer:(globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker"),
    model:(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model"),
    year:(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year"),
    serial_number:(globalThis.YGCI18n?.t("ui.serial_8ea09493",{},"Serial")??"Serial")
  };
  return labels[String(value||'')]||String(value||'').replace(/_/g,' ');
}
function claimTypeLabel(value){
  const fallback=String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ');return globalThis.YGCI18n?.t('values.claim_type.'+String(value||'claim'),{},fallback)??fallback;
}
function incidentClaimLabel(c){return c.value_text==='lost'?(globalThis.YGCI18n?.t("ui.incident_lost_650d5700",{},"Incident Lost")??"Incident Lost"):claimTypeLabel(c.value_text||'incident')}
function displayEventDate(value){
  if(!value)return (globalThis.YGCI18n?.t("ui.date_unknown_bc11be8c",{},"Date unknown")??"Date unknown");
  const text=String(value).trim();
  const direct=text.match(/^(\d{4}-\d{2}-\d{2})$/);
  if(direct)return direct[1];
  const d=new Date(text);
  if(Number.isNaN(d.getTime()))return text;
  const year=d.getFullYear();
  const month=String(d.getMonth()+1).padStart(2,'0');
  const day=String(d.getDate()).padStart(2,'0');
  return year+'-'+month+'-'+day;
}
function displayInputDate(value){
  if(!value)return (globalThis.YGCI18n?.t("ui.input_date_unknown_49db8d5c",{},"Input date unknown")??"Input date unknown");
  const d=new Date(String(value));
  return Number.isNaN(d.getTime())?String(value):d.toLocaleString(globalThis.YGCI18n?.locale||'en-US');
}
function displayDiscoveryDateTime(value){
  const raw=String(value||'').trim();
  if(!raw)return '';
  const d=new Date(raw);
  if(Number.isNaN(d.getTime()))return raw;
  return d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate()+' '+
    String(d.getHours()).padStart(2,'0')+':'+
    String(d.getMinutes()).padStart(2,'0')+':'+
    String(d.getSeconds()).padStart(2,'0');
}
function claimHeaderHtml(c,type,eventDate){
  let response='';
  if(c.can_verify){
    const current=String(c.verification_status||'unverified').toLowerCase();
    response='<select class="claim-response-select" onchange="setClaimResponse('+c.id+',this.value)">'+
      '<option value="positive"'+(current==='positive'?' selected':'')+(">"+(globalThis.YGCI18n?.html("ui.positive_14e9f4e3",{},"Positive")??"Positive")+"</option>")+
      '<option value="negative"'+(current==='negative'?' selected':'')+(">"+(globalThis.YGCI18n?.html("ui.negative_9f7bdabb",{},"Negative")??"Negative")+"</option>")+
      '<option value="unverified"'+(current==='unverified'?' selected':'')+(">"+(globalThis.YGCI18n?.html("ui.unverified_33c8e8de",{},"Unverified")??"Unverified")+"</option>")+
      '</select>';
  }
  return '<span class="claim-badge">'+esc(type)+'</span>'+response+'<span class="claim-event-date">'+esc(eventDate)+'</span>';
}
function claimVisualTypeClass(c){
  if(c.claim_type==='ownership')return ' claim-type-ownership';
  if(c.claim_type==='specification')return ' claim-type-specification';
  if(c.claim_type==='incident')return ' claim-type-incident';
  if(c.claim_type==='event')return ' claim-type-event';
  if(c.claim_type==='media')return ' claim-type-media';
  return '';
}
function claimCardFull(c){
  const type=c.claim_type==='specification'
    ? (c.specification_kind==='repair'?(globalThis.YGCI18n?.t("ui.repair_1196b6c5",{},"Repair")??"Repair"):(globalThis.YGCI18n?.t("ui.specification_39732416",{},"Specification")??"Specification"))
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?incidentClaimLabel(c):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):claimTypeLabel(c.claim_type))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(['automation','merged_listing'].includes(c.ownership_source)?(c.value_text||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown")):(c.author_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))).trim()||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User");
    const ownerHtml=['automation','merged_listing'].includes(c.ownership_source)?esc(owner):YGCProductDetail.userLink(c.author_user_id,owner,esc);
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))
      : (globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown");
    if(kind==='lost'){
      body=("<div><strong>"+(globalThis.YGCI18n?.html("ui.reverb_listing_unavailable_current_owner_and_location_are__9c03f334",{},"Reverb listing unavailable. Current owner and location are unknown.")??"Reverb listing unavailable. Current owner and location are unknown.")+"</strong></div>");
    }else if(kind==='release'){
      body=c.ownership_source==='automation'
        ? ("<div><strong>"+(globalThis.YGCI18n?.html("ui.reverb_listing_unavailable_current_owner_and_location_are__9c03f334",{},"Reverb listing unavailable. Current owner and location are unknown.")??"Reverb listing unavailable. Current owner and location are unknown.")+"</strong></div>")
        : '<div><strong>'+ownerHtml+' released this product.</strong></div>';
    }else if(kind==='transfer'&&c.transfer){
      const t=c.transfer;
      body='<div><strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+("</strong></div><div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.transfer_fc5cb474",{},"Transfer:")??"Transfer:")+" ")+esc(t.state)+'</div>';
      if(t.accepted_at)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.info_transfer_accepted_on_ba2319c7",{},"Info: Transfer accepted on")??"Info: Transfer accepted on")+" ")+esc(displayInputDate(t.accepted_at))+'</div>';
      if(t.state==='pending'&&activeUser?.user&&[t.from_user_id,t.to_user_id].includes(Number(activeUser.user.id)))body+='<button type="button" onclick="openTransferReview('+Number(c.id)+(")\">"+(globalThis.YGCI18n?.html("ui.review_transfer_df6be7c7",{},"Review Transfer")??"Review Transfer")+"</button>");
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+ownerHtml+'.</strong></div>';
    }else if(kind!=='acquire'){
      body=("<div><strong>"+(globalThis.YGCI18n?.html("ui.legacy_ownership_claim_335a10da",{},"Legacy Ownership Claim:")??"Legacy Ownership Claim:")+" ")+esc(kind)+'</strong></div>';
    }else{
      body='<div><strong>'+ownerHtml+' became the owner of this product.</strong></div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='incident'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='event'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='specification'){
    const items=(c.spec_items&&c.spec_items.length)
      ? c.spec_items
      : (c.field_name?[{field_name:c.field_name,value_text:c.value_text}]:[]);
    body=items.map(item=>'<div><strong>'+esc(specificationFieldLabel(item.field_name))+': '+esc(item.value_text||'')+'</strong></div>').join('');
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='identity_correction'){
    const items=c.identity_items||[];
    body=items.map(item=>
      '<div><strong>'+esc(identityFieldLabel(item.field_name))+':</strong> '+
      esc(item.old_value||'—')+' → '+esc(item.new_value||'—')+'</div>'
    ).join('');
    if(c.body)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.reason_3425d108",{},"Reason:")??"Reason:")+" ")+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||(globalThis.YGCI18n?.t("ui.listing_observed_cef64518",{},"Listing observed")??"Listing observed");
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.owner_9a638cfe",{},"Owner:")??"Owner:")+" ")+YGCProductDetail.userLink(c.observed_owner_user_id,listingOwner,esc)+'</div>';
    if(seller)details.push((globalThis.YGCI18n?.t("ui.seller_16662988",{},"Seller:")??"Seller:")+" "+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push((globalThis.YGCI18n?.t("ui.location_bbdffe25",{},"Location:")??"Location:")+" "+location);
    const specs=[
      c.observed_model&&((globalThis.YGCI18n?.t("ui.model_11a93106",{},"Model:")??"Model:")+" "+c.observed_model),
      c.observed_finish&&((globalThis.YGCI18n?.t("ui.finish_38c77297",{},"Finish:")??"Finish:")+" "+c.observed_finish),
      c.observed_year&&((globalThis.YGCI18n?.t("ui.year_60a37971",{},"Year:")??"Year:")+" "+c.observed_year),
      c.observed_serial_number&&((globalThis.YGCI18n?.t("ui.serial_8fe19cfa",{},"Serial:")??"Serial:")+" "+c.observed_serial_number)
    ].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.source_url&&(c.claim_type==='listing'||c.source_site==='reverb')){
    body+=("<div class=\"claim-info\"><strong>"+(globalThis.YGCI18n?.html("ui.info_170322a3",{},"Info")??"Info")+"</strong>: <a href=\"")+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">'+(c.source_site==='reverb'?(globalThis.YGCI18n?.t("ui.view_reverb_listing_96e64b0d",{},"View Reverb listing")??"View Reverb listing"):(globalThis.YGCI18n?.t("ui.view_listing_9d24337a",{},"View listing")??"View listing"))+'</a></div>';
  }
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const votes='<div class="claim-votes">'+
    '<button class="claim-vote'+(c.viewer_vote==='good'?' active':'')+'" onclick="voteClaim('+c.id+',\'good\')">👍 '+good+'</button>'+
    '<button class="claim-vote'+(c.viewer_vote==='bad'?' active':'')+'" onclick="voteClaim('+c.id+',\'bad\')">👎 '+bad+'</button>'+
    '</div>';
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'">'+
    '<div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div>'+
    '<div class="claim-body">'+body+'</div>'+
    '<div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+YGCProductDetail.userLink(c.author_user_id,c.author_name,esc)+'</div></div>'+
    '</div>';
}
function compactClaimType(c){
  return c.claim_type==='specification'
    ? (c.specification_kind==='repair'?(globalThis.YGCI18n?.t("ui.repair_1196b6c5",{},"Repair")??"Repair"):(globalThis.YGCI18n?.t("ui.specification_39732416",{},"Specification")??"Specification"))
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire')
      :(c.claim_type==='incident'?incidentClaimLabel(c)
      :(c.claim_type==='event'?claimTypeLabel(c.value_text||'event')
      :claimTypeLabel(c.claim_type))));
}
function claimCard(c){
  const verification=String(c.verification_status||'positive').toLowerCase();
  if(verification==='positive')return claimCardFull(c);
  if(verification==='unverified'){
    return '<div class="claim-compact-row"><button type="button" class="claim-compact-tag'+claimVisualTypeClass(c)+'" onclick="openClaimPopup('+c.id+',this)">'+esc(compactClaimType(c))+'</button></div>';
  }
  if(verification==='negative'){
    return '<div class="claim-compact-row"><button type="button" class="claim-negative-dot" title="Negative Claim" onclick="openClaimPopup('+c.id+',this)">◉</button></div>';
  }
  return claimCardFull(c);
}
function positionClaimPopup(trigger){
  const backdrop=document.getElementById('claimPopupModal');
  const popup=backdrop?backdrop.querySelector('.claim-popup-modal'):null;
  const chronicle=document.getElementById('chronicleEntries');
  if(!backdrop||!popup||!chronicle||!trigger)return;

  const triggerRect=trigger.getBoundingClientRect();
  const chronicleRect=chronicle.getBoundingClientRect();
  const marginLeft=22;
  const edge=10;
  const width=Math.max(220,chronicleRect.width-marginLeft);
  const preferredLeft=chronicleRect.left+marginLeft-(width*0.5);
  const left=Math.min(
    Math.max(edge,preferredLeft),
    Math.max(edge,window.innerWidth-width-edge)
  );

  popup.style.width=width+'px';
  popup.style.left=left+'px';
  popup.style.top=Math.min(
    window.innerHeight-edge,
    triggerRect.bottom+6
  )+'px';

  requestAnimationFrame(()=>{
    const popupRect=popup.getBoundingClientRect();
    let top=triggerRect.bottom+6;
    if(top+popupRect.height>window.innerHeight-edge){
      top=triggerRect.top-popupRect.height-6;
    }
    if(top<edge)top=edge;
    popup.style.top=top+'px';
  });
}
function openClaimPopup(claimId,trigger){
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  const claim=currentClaims.find(c=>Number(c.id)===Number(claimId));
  if(!claim)return;
  const content=document.getElementById('claimPopupContent');
  if(content)content.innerHTML=claimCardFull(claim);
  const modal=document.getElementById('claimPopupModal');
  if(modal){
    YGCOverlays.open(modal);
    positionClaimPopup(trigger);
  }
}
function closeClaimPopup(event){
  if(event&&event.target&&event.target.id!=='claimPopupModal')return;
  const modal=document.getElementById('claimPopupModal');
  if(modal)YGCOverlays.close(modal);
}

function toggleDetailAccordion(id){
  YGCProductDetail.toggleAccordion(id);
}

function renderChronicle(){
  const claims=YGCProductDetail.orderedClaims(currentClaims);
  const el=document.getElementById('chronicleEntries');
  if(el)el.innerHTML=claims.length?claims.map(claimCard).join(''):("<div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_claims_yet_bcafe434",{},"No Claims yet.")??"No Claims yet.")+"</div>");
}

async function refreshClaimViews(individualId){
  if(PROFILE_USER_ID){
    await loadActiveUser();
    await loadProfilePage(individualId);
  }else if(individualId!==null){
    await showIndividual(individualId);
  }
}

async function setClaimResponse(claimId,stance){
  if(!activeUser||!activeUser.user)return;
  const claim=typeof currentClaims!=='undefined'?currentClaims.find(c=>Number(c.id)===Number(claimId)):null;
  const reason=stance==='negative'&&claim?.claim_type==='ownership'&&claim.ownership_kind==='acquire'?prompt((globalThis.YGCI18n?.t("ui.why_are_you_declining_this_acquire_your_reason_will_be_sha_0a154dc0",{},"Why are you declining this Acquire? Your reason will be shared with the applicant.")??"Why are you declining this Acquire? Your reason will be shared with the applicant.")):null;
  if(stance==='negative'&&claim?.claim_type==='ownership'&&claim.ownership_kind==='acquire'&&!reason?.trim())return;
  try{
    await jfetch('/api/claims/'+claimId+'/response',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        responder_user_id:Number(activeUser.user.id),
        stance,reason
      })
    });
    closeClaimPopup();
    await refreshClaimViews(selectedIndividualId);
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.owner_verification_could_not_be_updated_d52e78f8",{},"Owner Verification could not be updated.")??"Owner Verification could not be updated.")+"\n"+e.message);
    if(selectedIndividualId!==null)await showIndividual(selectedIndividualId);
  }
}

async function voteClaim(claimId,vote){
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  try{
    await jfetch('/api/claims/'+claimId+'/vote',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:Number(activeUser.user.id),vote})
    });
    await refreshClaimViews(selectedIndividualId);
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.vote_could_not_be_updated_f6b7b6d7",{},"Vote could not be updated.")??"Vote could not be updated.")+"\n"+e.message);
  }
}

let acquireRevision=null;
let acquireBusy=false;
let acquireDisplayState=null;
let acquireForm=null;
let ownershipConfirmResolve=null;
function confirmOwnershipAction(title,message,confirmLabel=(globalThis.YGCI18n?.t("ui.confirm_eebdd24a",{},"Confirm")??"Confirm")){
  if(ownershipConfirmResolve)return Promise.resolve(false);
  document.getElementById('ownershipConfirmTitle').textContent=title;
  document.getElementById('ownershipConfirmMessage').textContent=message;
  const submit=document.getElementById('ownershipConfirmSubmit');
  submit.textContent=confirmLabel;
  submit.dataset.uiAction=/^(Cansel Request|Cancel Request|Delete|Release|Transfer)$/.test(title)?'danger':/^(Cancel|Close|Back)$/.test(title)?'close':/^(Accept|Submit|Keep Request|Save)$/.test(title)?'primary':'neutral';
  return new Promise(resolve=>{
    ownershipConfirmResolve=resolve;
    YGCOverlays.open('ownershipConfirmModal',{onClose:()=>{if(ownershipConfirmResolve){const done=ownershipConfirmResolve;ownershipConfirmResolve=null;done(false)}}});
  });
}
function resolveOwnershipConfirmation(accepted){
  const done=ownershipConfirmResolve;ownershipConfirmResolve=null;
  YGCOverlays.close('ownershipConfirmModal');if(done)done(accepted);
}
function requestFooter(row=null){
  if(row&&row.request_kind!=='listing'&&row.status!=='draft'){
    document.getElementById('acquireReviewActions').innerHTML='<button data-ui-action="close" onclick="cancelRequestWindow()">OK</button>';
    return;
  }
  const saved=row&&!row.unsaved;
  const terminal=row&&['accepted','rejected','cancelled','closed','expired'].includes(row.status);
  let buttons='';
  if(!row)buttons+=("<button id=\"guitarSubmit\" onclick=\"submitNewGuitar()\">"+(globalThis.YGCI18n?.html("ui.generate_challenge_321afa1e",{},"Generate Challenge")??"Generate Challenge")+"</button>");
  if(!row||row.status==='draft')buttons+='<button data-ui-action="primary" id="acquireSubmit" onclick="submitAcquireApplication()" '+(!row?'disabled':'')+(">"+(globalThis.YGCI18n?.html("ui.submit_155f816c",{},"Submit")??"Submit")+"</button>");
  if(row?.dispute_case_id)buttons+='<button onclick="YGCDisputes.open('+Number(row.dispute_case_id)+(")\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button>");
  else if(row?.can_request_dispute)buttons+=("<button onclick=\"YGCDisputes.list()\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button>");
  if(!row||row.request_kind==='listing')buttons+=("<button onclick=\"requestRefresh()\">"+(globalThis.YGCI18n?.html("ui.reflesh_7228c81b",{},"Reflesh")??"Reflesh")+"</button>");
  if(row?.status==='error')buttons+=("<button onclick=\"actAcquireApplication('retry')\">"+(globalThis.YGCI18n?.html("ui.retry_review_a82c8698",{},"Retry Review")??"Retry Review")+"</button>");
  buttons+=("<button data-ui-action=\"primary\" onclick=\"keepAcquireRequest()\">"+(globalThis.YGCI18n?.html("ui.keep_request_95011d14",{},"Keep Request")??"Keep Request")+"</button><button data-ui-action=\"close\" class=\"secondary\" onclick=\"cancelRequestWindow()\">"+(globalThis.YGCI18n?.html("action.cancel",{},"Cancel")??"Cancel")+"</button>");
  if(saved&&!terminal)buttons+=("<button data-ui-action=\"danger\" class=\"secondary\" onclick=\"actAcquireApplication('cancel')\">"+(globalThis.YGCI18n?.html("ui.cansel_request_dfc8109a",{},"Cansel Request")??"Cansel Request")+"</button>");
  document.getElementById('acquireReviewActions').innerHTML=buttons;
}
async function cancelRequestWindow(){
  if(acquireBusy)return;
  closeAcquireReview();
}
async function requestRefresh(){
  if(acquireBusy)return;
  const saved=acquireForm&&!acquireForm.unsaved;
  const message=saved?(globalThis.YGCI18n?.t("ui.reload_the_saved_request_unsaved_input_and_selected_photos_5e13d43a",{},"Reload the saved request? Unsaved input and selected photos will be discarded.")??"Reload the saved request? Unsaved input and selected photos will be discarded."):(globalThis.YGCI18n?.t("ui.refresh_this_form_entered_text_and_the_current_challenge_w_7f53526d",{},"Refresh this form? Entered text and the current Challenge will be kept. Selected photos will be cleared. The request will not be saved.")??"Refresh this form? Entered text and the current Challenge will be kept. Selected photos will be cleared. The request will not be saved.");
  if(!await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.reflesh_7228c81b",{},"Reflesh")??"Reflesh"),message))return;
  if(saved){await viewAcquireApplication(acquireRevision);return}
  const values={};
  for(const id of ['guitarMaker','guitarModel','guitarYear','guitarFinish','guitarSerial','acquireDate','acquireBody']){
    const field=document.getElementById(id);if(field)values[id]=field.value;
  }
  if(acquireForm)renderAcquireApplication(acquireForm);else openNewGuitar();
  for(const [id,value] of Object.entries(values)){
    const field=document.getElementById(id);if(field)field.value=value;
  }
}
async function requestExistingGuitar(id){
  if(await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.view_guitar_2c1748c3",{},"View Guitar")??"View Guitar"),(globalThis.YGCI18n?.t("ui.close_this_window_and_view_the_existing_guitar_6178395b",{},"Close this window and view the existing guitar?")??"Close this window and view the existing guitar?"))){closeAcquireReview();await showIndividual(id,true)}
}
async function requestHistoryItem(revision){
  if(await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.open_request_7e2bc570",{},"Open Request")??"Open Request"),(globalThis.YGCI18n?.t("ui.open_this_request_and_view_its_current_status_3d6bd90e",{},"Open this request and view its current status?")??"Open this request and view its current status?")))await viewAcquireApplication(revision);
}
async function keepAcquireRequest(){
  if(acquireBusy)return;
  if(!await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.keep_request_95011d14",{},"Keep Request")??"Keep Request"),(globalThis.YGCI18n?.t("ui.save_the_request_details_and_close_this_window_selected_ph_39330ea1",{},"Save the request details and close this window? Selected photos will not be saved.")??"Save the request details and close this window? Selected photos will not be saved.")))return;
  acquireBusy=true;
  try{
    if(!acquireForm)await prepareListingDraft();
    if(acquireForm?.status==='draft'){
      const row=await jfetch('/api/ownership-drafts/keep'+acquireQuery(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        ...(acquireForm.unsaved?{draft_token:acquireForm.draft_token}:{revision:acquireForm.revision}),
        acquisition_date:document.getElementById('acquireDate').value,body:document.getElementById('acquireBody').value})});
      acquireForm=row;
    }
    if(acquireForm){closeAcquireReview();await loadOwnershipAttention()}
  }catch(error){alert(error.message)}finally{acquireBusy=false}
}
function listingMetadataFields(payload={},readOnly=false){
  return '<div class="modal-grid">'+[['manufacturer','guitarMaker',(globalThis.YGCI18n?.t("ui.maker_0a9590e6",{},"Maker *")??"Maker *"),120],['model','guitarModel',(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model"),160],['year','guitarYear',(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year"),40],['finish','guitarFinish',(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish"),160],['serial_number','guitarSerial',(globalThis.YGCI18n?.t("ui.serial_fbb8fcca",{},"Serial *")??"Serial *"),160]].map(([key,id,label,max])=>'<label>'+label+'<input id="'+id+'" maxlength="'+max+'" value="'+esc(payload[key]||'')+'" '+(readOnly?'readonly':'')+'></label>').join('')+'</div>';
}
function ownershipEvidenceFields({listing=false,issued=true,date='',body=''}={}){
  return '<div class="modal-grid"><label>'+ (listing?(globalThis.YGCI18n?.t("ui.listing_date_211da3c0",{},"Listing date")??"Listing date"):(globalThis.YGCI18n?.t("ui.acquisition_date_0b048907",{},"Acquisition date")??"Acquisition date"))+' *<input id="acquireDate" type="date" required value="'+esc(date)+'" '+(listing&&issued?'readonly':'')+("></label><label class=\"full\">"+(globalThis.YGCI18n?.html("ui.description_526e0087",{},"Description")??"Description")+"<textarea id=\"acquireBody\" maxlength=\"4000\" ")+(listing&&issued?'readonly':'')+'>'+esc(body)+'</textarea></label>'+
    ("<label class=\"full\">"+(globalThis.YGCI18n?.html("ui.close_up_of_serial_and_challenge_ef2213e0",{},"Close-up of serial and challenge *")??"Close-up of serial and challenge *")+"<input id=\"acquireCloseup\" type=\"file\" accept=\"image/jpeg,image/png,image/webp\" ")+(!issued?'disabled':'')+("></label><label class=\"full\">"+(globalThis.YGCI18n?.html("ui.overview_of_guitar_and_challenge_fbed4b65",{},"Overview of guitar and challenge *")??"Overview of guitar and challenge *")+"<input id=\"acquireOverview\" type=\"file\" accept=\"image/jpeg,image/png,image/webp\" ")+(!issued?'disabled':'')+'></label></div>'+
    (listing?("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.after_approval_the_overview_photo_becomes_the_public_repre_5674d645",{},"After approval, the overview photo becomes the public representative image. The close-up and report are accessible only to the applicant, administrators and current owner.")??"After approval, the overview photo becomes the public representative image. The close-up and report are accessible only to the applicant, administrators and current owner.")+"</p>"):'');
}
function ownershipChallengeBox(row){
  if(!row)return ("<div class=\"challenge-box\">"+(globalThis.YGCI18n?.html("ui.challenge_not_generated_ae88ac5c",{},"Challenge: Not generated")??"Challenge: Not generated")+"<p>"+(globalThis.YGCI18n?.html("ui.enter_the_guitar_details_and_date_then_select_generate_cha_624c9833",{},"Enter the guitar details and date, then select Generate Challenge. Write the code on paper before taking and selecting both photos.")??"Enter the guitar details and date, then select Generate Challenge. Write the code on paper before taking and selecting both photos.")+"</p></div>");
  return ("<div class=\"challenge-box\">"+(globalThis.YGCI18n?.html("ui.serial_8fe19cfa",{},"Serial:")??"Serial:")+" ")+esc(row.serial)+("<br>"+(globalThis.YGCI18n?.html("ui.challenge_0766f570",{},"Challenge:")??"Challenge:")+" "+"<strong>")+esc(row.challenge)+("</strong><br>"+(globalThis.YGCI18n?.html("ui.submit_by_ae167e52",{},"Submit by:")??"Submit by:")+" ")+esc(new Date(row.expires_at*1000).toLocaleString(globalThis.YGCI18n?.locale||'en-US'))+("</div><p>"+(globalThis.YGCI18n?.html("ui.include_the_handwritten_challenge_in_both_photos_images_wi_601bec67",{},"Include the handwritten challenge in both photos. Images will be sent to GPT for review. Submitted requests do not expire while awaiting review.")??"Include the handwritten challenge in both photos. Images will be sent to GPT for review. Submitted requests do not expire while awaiting review.")+"</p>");
}
function acquireQuery(){return '?viewer_id='+encodeURIComponent(activeUser.user.id)}
const acquireLabels={draft:(globalThis.YGCI18n?.t("ui.awaiting_photos_338fa4ef",{},"Awaiting photos")??"Awaiting photos"),pending:(globalThis.YGCI18n?.t("ui.awaiting_review_4848885e",{},"Awaiting review")??"Awaiting review"),processing:(globalThis.YGCI18n?.t("ui.under_review_9e8a3b64",{},"Under review")??"Under review"),error:(globalThis.YGCI18n?.t("ui.review_error_retry_available_d267715c",{},"Review error — retry available")??"Review error — retry available"),rejected:(globalThis.YGCI18n?.t("ui.evidence_rejected_ac7b37b2",{},"Evidence rejected")??"Evidence rejected"),accepted:(globalThis.YGCI18n?.t("ui.acquire_added_64ff8a72",{},"Acquire added")??"Acquire added"),cancelled:(globalThis.YGCI18n?.t("ui.cancelled_d353a99e",{},"Cancelled")??"Cancelled"),closed:(globalThis.YGCI18n?.t("ui.closed_c21ead06",{},"Closed")??"Closed"),expired:(globalThis.YGCI18n?.t("ui.submission_expired_261232c8",{},"Submission expired")??"Submission expired")};
function acquireStatusLabel(row){if(row.request_kind==='listing')return row.status==='accepted'?(globalThis.YGCI18n?.t("ui.listing_registered_9f349e09",{},"Listing registered")??"Listing registered"):(acquireLabels[row.status]||row.status);return row.status==='accepted'&&row.verification_status==='unverified'?(globalThis.YGCI18n?.t("ui.awaiting_owner_approval_bb8f3921",{},"Awaiting owner approval")??"Awaiting owner approval"):(acquireLabels[row.status]||row.status)}
function setRequestTitle(title,status){
  document.getElementById('acquireReviewTitle').innerHTML=esc(title)+' <small class="ownership-request-status">- '+esc(status)+'</small>';
}
async function openAcquireApplication(individualId){
  if(!activeUser||!activeUser.user){requireAccount();return}
  if(acquireBusy)return;
  acquireBusy=true;
  try{
    const row=await jfetch('/api/ownership-drafts/acquire/'+individualId+acquireQuery(),{method:'POST'});
    acquireRevision=row.revision;renderAcquireApplication(row);
    YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});
  }catch(e){alert(e.message)}finally{acquireBusy=false}
}
async function loadOwnershipAttention(){
  const userId=activeUser?.user?.id,sequence=++ownershipAttentionSequence;
  if(!userId){ownershipAttention={attention_count:0};if(typeof YGCImportantInformation!=='undefined')YGCImportantInformation.refresh();return}
  try{
    const data=await jfetch('/api/acquire-applications/attention?viewer_id='+encodeURIComponent(userId));
    if(sequence!==ownershipAttentionSequence||activeUser?.user?.id!==userId)return;
    ownershipAttention=data;
    if(typeof YGCImportantInformation!=='undefined')YGCImportantInformation.refresh();
  }catch(error){/* Preserve the last known state during a connection failure. */}
}
async function acknowledgeOwnershipResult(row){
  if(!row.unread_result||Number(row.applicant_id)!==Number(activeUser?.user?.id))return;
  await jfetch('/api/acquire-applications/'+encodeURIComponent(row.revision)+'/seen'+acquireQuery(),{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_id:row.review_event_id})});
  await loadOwnershipAttention();
}
function closeAcquireReview(){YGCOverlays.close('acquireReviewModal');acquireRevision=null;acquireForm=null}
async function showAcquireApplications(){
  if(!activeUser||!activeUser.user){requireAccount();return}
  acquireRevision=null;acquireForm=null;
  document.getElementById('acquireReviewTitle').textContent=(globalThis.YGCI18n?.t("ui.ownership_requests_e00bbd39",{},"Ownership Requests")??"Ownership Requests");
  document.getElementById('acquireReviewActions').innerHTML=("<button data-ui-action=\"close\" onclick=\"cancelRequestWindow()\">"+(globalThis.YGCI18n?.html("action.cancel",{},"Cancel")??"Cancel")+"</button>");
  try{
    const rows=(await jfetch('/api/acquire-applications'+acquireQuery())).filter(r=>['draft','pending','processing','error'].includes(r.status)||(r.status==='accepted'&&r.verification_status==='unverified'));
    document.getElementById('acquireReviewContent').innerHTML=(rows.length?rows.map(r=>'<p><button onclick="requestHistoryItem(\''+esc(r.revision)+'\')">'+esc(r.request_kind==='listing'?(globalThis.YGCI18n?.t("ui.listing_fc7f1aa2",{},"Listing")??"Listing")+" "+(r.product_name||''):(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+r.original_individual_id)+' — '+esc(acquireStatusLabel(r))+(r.unread_result?' — New result':'')+'</button><br><small>'+esc(r.created_at)+'</small></p>').join(''):(globalThis.YGCI18n?.t("ui.no_incomplete_requests_a299ce51",{},"No incomplete requests.")??"No incomplete requests."));
    YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});
  }catch(e){alert(e.message)}
}
async function viewAcquireApplication(revision){
  try{const row=await jfetch('/api/acquire-applications/'+encodeURIComponent(revision)+acquireQuery());acquireRevision=row.revision;renderAcquireApplication(row);YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});await acknowledgeOwnershipResult(row);if(['accepted','closed'].includes(row.status)&&selectedIndividualId)await refreshClaimViews(selectedIndividualId)}catch(e){alert(e.message)}
}
function renderAcquireApplication(row){
  acquireDisplayState=row.status;acquireForm=row;
  setRequestTitle(row.request_kind==='listing'?(globalThis.YGCI18n?.t("ui.listing_request_32432123",{},"Listing Request")??"Listing Request"):(globalThis.YGCI18n?.t("ui.acquire_request_c11c1e49",{},"Acquire Request")??"Acquire Request"),acquireStatusLabel(row));
  const terminal=['accepted','rejected','cancelled','closed','expired'].includes(row.status);
  const listing=row.request_kind==='listing';
  let html='<p>'+esc(listing?row.product_name:(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+row.original_individual_id)+' / '+esc(row.unsaved?(globalThis.YGCI18n?.t("ui.not_saved_22b3467c",{},"Not saved")??"Not saved"):row.revision)+'</p>';
  if(row.existing_individual_ids?.length)html+=("<p>"+(globalThis.YGCI18n?.html("ui.this_maker_and_serial_are_already_registered_view_the_exis_50d9eddc",{},"This maker and serial are already registered. View the existing guitar and use Acquire to request ownership.")??"This maker and serial are already registered. View the existing guitar and use Acquire to request ownership.")+"</p>")+row.existing_individual_ids.map(id=>'<button onclick="requestExistingGuitar('+Number(id)+')">Existing guitar #'+Number(id)+' — View</button>').join('');
  if(listing&&row.status==='accepted'&&row.individual_id)html+='<p><a href="/users/'+Number(activeUser.user.id)+'?individual_id='+Number(row.individual_id)+("\">"+(globalThis.YGCI18n?.html("ui.view_registered_guitar_620dcf5d",{},"View Registered Guitar")??"View Registered Guitar")+"</a></p>");
  if(row.error)html+='<p>'+esc(row.error)+'</p>';
  if(row.status==='draft'){
    if(listing)html+=listingMetadataFields(row.listing_payload,true);
    html+=ownershipChallengeBox(row)+ownershipEvidenceFields({listing,date:listing?row.listing_payload.occurred_at:(row.acquisition_date||''),body:listing?row.listing_payload.body:(row.body||'')});
  }else if(!terminal){html+='<p>'+ (listing?(globalThis.YGCI18n?.t("ui.the_guitar_and_listing_will_be_registered_only_after_appro_e5f30f0f",{},"The guitar and Listing will be registered only after approval.")??"The guitar and Listing will be registered only after approval."):(globalThis.YGCI18n?.t("ui.the_acquire_claim_will_be_added_only_after_approval_c6972335",{},"The Acquire Claim will be added only after approval.")??"The Acquire Claim will be added only after approval."))+'</p>'}
  if(row.admin_review)html+=("<p>"+(globalThis.YGCI18n?.html("ui.administrator_review_018f86a1",{},"Administrator review:")??"Administrator review:")+" ")+(row.admin_review.accepted?(globalThis.YGCI18n?.t("ui.approved_87b42e40",{},"Approved")??"Approved"):(globalThis.YGCI18n?.t("ui.rejected_aea4a04a",{},"Rejected")??"Rejected"))+' — '+esc(row.admin_review.reason)+'</p>';
  const reasons=row.result?.adjudication?.reasons||[];
  if(row.status==='rejected'&&reasons.length)html+=("<section class=\"request-info\"><h3>"+(globalThis.YGCI18n?.html("ui.info_170322a3",{},"Info")??"Info")+"</h3><ul>")+reasons.map(reason=>'<li>'+esc(reason)+'</li>').join('')+'</ul></section>';
  document.getElementById('acquireReviewContent').innerHTML=html;requestFooter(row);
}
async function submitAcquireApplication(){
  if(acquireBusy||!acquireRevision)return;
  const form=new FormData();const acquired=document.getElementById('acquireDate').value;
  const closeup=document.getElementById('acquireCloseup').files[0],overview=document.getElementById('acquireOverview').files[0];
  if(!acquired||!closeup||!overview){alert((globalThis.YGCI18n?.t("ui.enter_the_date_and_select_both_photos_2dbbecc8",{},"Enter the date and select both photos.")??"Enter the date and select both photos."));return}
  if(!await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.submit_155f816c",{},"Submit")??"Submit"),(globalThis.YGCI18n?.t("ui.save_this_request_and_submit_both_photos_for_review_489d42bd",{},"Save this request and submit both photos for review?")??"Save this request and submit both photos for review?")))return;
  form.append('acquisition_date',acquired);form.append('body',document.getElementById('acquireBody').value);form.append('closeup',closeup);form.append('overview',overview);
  let url='/api/acquire-applications/'+acquireRevision+'/submit';
  if(acquireForm?.unsaved){url='/api/ownership-drafts/submit';form.append('draft_token',acquireForm.draft_token)}
  acquireBusy=true;document.getElementById('acquireSubmit').disabled=true;
  try{const row=await jfetch(url+acquireQuery(),{method:'POST',body:form});renderAcquireApplication(row);await loadOwnershipAttention();if(selectedIndividualId)await showIndividual(selectedIndividualId)}catch(e){alert(e.message)}finally{acquireBusy=false;const button=document.getElementById('acquireSubmit');if(button)button.disabled=false}
}
async function actAcquireApplication(action){
  if(acquireBusy||!acquireRevision)return;
  if(!await confirmOwnershipAction(action==='cancel'?(globalThis.YGCI18n?.t("ui.cansel_request_dfc8109a",{},"Cansel Request")??"Cansel Request"):(globalThis.YGCI18n?.t("ui.retry_review_a82c8698",{},"Retry Review")??"Retry Review"),action==='cancel'?(globalThis.YGCI18n?.t("ui.withdraw_this_saved_request_any_in_progress_review_will_be_2fca27e6",{},"Withdraw this saved request? Any in-progress review will be stopped.")??"Withdraw this saved request? Any in-progress review will be stopped."):(globalThis.YGCI18n?.t("ui.queue_this_request_for_another_review_5a82950a",{},"Queue this request for another review?")??"Queue this request for another review?")))return;
  acquireBusy=true;
  try{renderAcquireApplication(await jfetch('/api/acquire-applications/'+acquireRevision+'/'+action+acquireQuery(),{method:'POST'}));await loadOwnershipAttention();if(selectedIndividualId)await showIndividual(selectedIndividualId)}catch(e){alert(e.message)}finally{acquireBusy=false}
}

if(typeof setInterval==='function')setInterval(()=>{
  if(!document.hidden&&!acquireBusy&&acquireRevision&&['pending','processing'].includes(acquireDisplayState)&&document.getElementById('acquireReviewModal').classList.contains('open'))viewAcquireApplication(acquireRevision);
},15000);
let individualLoadSequence=0;
function closeCompactDetail(){
  document.getElementById('productDetailShell').classList.remove('compact-open');
}
function openCompactDetail(){
  if(window.matchMedia('(max-width: 900px)').matches){
    document.getElementById('productDetailShell').classList.add('compact-open');
  }
}
document.addEventListener('pointerdown',event=>{
  const shell=document.getElementById('productDetailShell');
  if(!shell.classList.contains('compact-open')||shell.contains(event.target))return;
  if(event.target instanceof Element&&event.target.closest('.modal-backdrop.open, dialog[open]'))return;
  closeCompactDetail();
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!document.querySelector('.modal-backdrop.open, dialog[open]'))closeCompactDetail();
});
window.addEventListener('resize',()=>{
  if(!window.matchMedia('(max-width: 900px)').matches)closeCompactDetail();
});
async function showIndividual(id,fromList=false){
  if(fromList){
    openCompactDetail();
    if(Number(selectedIndividualId)!==Number(id))document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.loading_47d2a515",{},"Loading...")??"Loading...");
  }
  const sequence=++individualLoadSequence;
  await loadActiveUser();
  if(sequence!==individualLoadSequence)return;
  const nextIndividualId=Number(id);
  const changedIndividual=Number(selectedIndividualId)!==nextIndividualId;
  selectedIndividualId=nextIndividualId;
  if(changedIndividual){
    const detail=document.getElementById('detail');
    if(detail)detail.scrollTop=0;
  }
  if(typeof renderIndividuals==='function')renderIndividuals();
  if(PROFILE_USER_ID){for(const section of ['owned','former','favorites'])renderProfileGuitars(section)}
  const [d,claims,currentSpecifications]=await Promise.all([
    jfetch('/api/individuals/'+id+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/current-specifications')
  ]);
  if(sequence!==individualLoadSequence)return;
  const i=d.individual;
  currentClaims=claims||[];
  const imageListing=d.current_source||null;
  const galleryImages=d.gallery_images||[];
  let out='';
  if(galleryImages.length){
    out+=productGalleryHtml(galleryImages,i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"));
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"))+("\" role=\"button\" tabindex=\"0\" aria-label=\"Open photo album\" loading=\"lazy\" onerror=\"this.onerror=null;this.src='/assets/no-picture.svg'\"><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.representative_image_c23db047",{},"Representative Image")??"Representative Image")+"</span>");
  }else if(imageListing){
    const imageUrl=String(imageListing.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageListing.image_url)+'" alt="'+esc(imageListing.listing_title||i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"))+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+("</a><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.source_c707ee4e",{},"Source:")??"Source:")+" "+"<a href=\"")+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(imageListing.source_site||(globalThis.YGCI18n?.t("ui.source_0e570ca6",{},"Source")??"Source")))+'</a></span>';
    else out+=image+("<span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.listing_claim_9837a144",{},"Listing Claim")??"Listing Claim")+"</span>");
  }else{
    out+=("<img class=\"detail-image\" src=\"/assets/no-picture.svg\" alt=\"No picture\" data-i18n-alt=\"ui.no_picture_6e9a17ba\"><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.no_picture_b2e8e688",{},"No Picture")??"No Picture")+"</span>");
  }
  const chronicleAction='<div class="chronicle-toolbar"><div class="claim-menu-wrap"><button class="add-claim-action" onclick="toggleAddClaimMenu(event,'+i.id+(")\">"+(globalThis.YGCI18n?.html("claim.add",{},"Let's add your Claim !!")??"Let's add your Claim !!")+"</button><div class=\"claim-menu\" id=\"addClaimMenu\"><button onclick=\"chooseClaimType('specification_repair')\">"+(globalThis.YGCI18n?.html("ui.specification_repair_66e4d9a7",{},"Specification/Repair")??"Specification/Repair")+"</button><button onclick=\"chooseClaimType('incident')\">"+(globalThis.YGCI18n?.html("ui.incident_36a606d4",{},"Incident")??"Incident")+"</button><button onclick=\"chooseClaimType('event')\">"+(globalThis.YGCI18n?.html("ui.event_4e1f49a9",{},"Event")??"Event")+"</button><button onclick=\"chooseClaimType('media')\">"+(globalThis.YGCI18n?.html("ui.media_d357175c",{},"Media")??"Media")+"</button>")+ownershipClaimMenuHtml(i)+'</div></div></div>';
  out+=YGCProductDetail.render({individual:i,specifications:currentSpecifications||[],image:'',
    owner:currentSnapshotOwnerHtml(i),location:currentLocationHtml(i),ownership:ownershipControlsHtml(i),
    titleAction:favoriteButton(i.id),chronicleAction,fieldLabel:specificationFieldLabel,escape:esc});
  document.getElementById('detail').innerHTML=out;
  renderChronicle();

  if(changedIndividual){
    const detail=document.getElementById('detail');
    if(detail)detail.scrollTop=0;
  }
}


const SPEC_FIELDS=[
  ['nut',(globalThis.YGCI18n?.t("ui.nut_67c45877",{},"Nut")??"Nut")],['frets',(globalThis.YGCI18n?.t("ui.frets_08aa1381",{},"Frets")??"Frets")],['pickguard',(globalThis.YGCI18n?.t("ui.pickguard_280dde37",{},"Pickguard")??"Pickguard")],
  ['potentiometers',(globalThis.YGCI18n?.t("ui.potentiometers_5beb07c1",{},"Potentiometers")??"Potentiometers")],['wiring',(globalThis.YGCI18n?.t("ui.wiring_72529059",{},"Wiring")??"Wiring")],['neck',(globalThis.YGCI18n?.t("ui.neck_6b27a971",{},"Neck")??"Neck")],
  ['pickups',(globalThis.YGCI18n?.t("ui.pickups_088cf7e8",{},"Pickups")??"Pickups")],['bridge',(globalThis.YGCI18n?.t("ui.bridge_3892e103",{},"Bridge")??"Bridge")],['tuners',(globalThis.YGCI18n?.t("ui.tuners_1de22981",{},"Tuners")??"Tuners")],
  ['body',(globalThis.YGCI18n?.t("ui.body_6ccaa641",{},"Body")??"Body")],['fingerboard',(globalThis.YGCI18n?.t("ui.fingerboard_92d85445",{},"Fingerboard")??"Fingerboard")],['finish',(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish")],['weight',(globalThis.YGCI18n?.t("ui.weight_81d27ef6",{},"Weight")??"Weight")]
];
let specificationKind='specification';
let specificationItems=[];
let editingSpecificationClaimId=null;

function toggleAddClaimMenu(event,individualId){
  event.stopPropagation();
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  selectedIndividualId=Number(individualId);
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.toggle('open');
}
async function chooseClaimType(type){
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.remove('open');
  if(type==='specification_repair')openSpecificationClaim(selectedIndividualId);
  else if(type==='incident')openIncidentClaim(selectedIndividualId);
  else if(type==='event')openEventClaim(selectedIndividualId);
  else if(type==='media')openMediaClaim(selectedIndividualId);
  else if(type==='former_owner')openFormerOwnerClaim(selectedIndividualId);
  else if(type==='acquire'){
    const individualId=selectedIndividualId;
    if(await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.ownership_claim_warning_186144e7",{},"Ownership Claim Warning")??"Ownership Claim Warning"),
      (globalThis.YGCI18n?.t("ui.this_guitar_already_has_an_owner_are_you_sure_it_belongs_t_bdb41c29",{},"This guitar already has an owner. Are you sure it belongs to you? This claim may lead to a dispute between users.")??"This guitar already has an owner. Are you sure it belongs to you? This claim may lead to a dispute between users."),
      (globalThis.YGCI18n?.t("ui.acknowledge_f9236d9e",{},"Acknowledge")??"Acknowledge")))openOwnerClaim(individualId);
  }
  else if(type==='ownership')openOwnershipClaim(selectedIndividualId,'add_claim');
}

function mediaImageInputs(){
  return Array.from(document.querySelectorAll('#mediaClaimImages .media-image-input'));
}
function resetMediaImageInputs(){
  mediaImageInputs().forEach((input,index)=>{
    input.value='';
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle('visible',index===0);
  });
}
function updateMediaImageSlots(){
  const inputs=mediaImageInputs();
  let lastSelected=-1;
  inputs.forEach((input,index)=>{if(input.files&&input.files.length)lastSelected=index;});
  const next=Math.min(lastSelected+1,inputs.length-1);
  inputs.forEach((input,index)=>{
    const slot=document.getElementById('mediaImageSlot'+index);
    if(slot)slot.classList.toggle('visible',index===0||index<=next||(input.files&&input.files.length>0));
  });
}
function openMediaClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('mediaClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  resetMediaImageInputs();
  document.getElementById('mediaClaimDate').value=new Date().toLocaleDateString('sv-SE');
  document.getElementById('mediaClaimCaption').value='';
  YGCOverlays.open('mediaClaimModal');
}
function closeMediaClaim(event){
  if(event&&event.target&&event.target.id!=='mediaClaimModal')return;
  YGCOverlays.close('mediaClaimModal');
}
async function submitMediaClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const images=mediaImageInputs().map(input=>input.files&&input.files[0]).filter(Boolean);
  if(!images.length){alert((globalThis.YGCI18n?.t("ui.select_at_least_one_image_67b7212c",{},"Select at least one image.")??"Select at least one image."));return;}
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){alert((globalThis.YGCI18n?.t("ui.choose_a_jpeg_png_webp_or_gif_image_2d2c2f31",{},"Choose a JPEG, PNG, WebP, or GIF image.")??"Choose a JPEG, PNG, WebP, or GIF image."));return;}
    if(image.size>12*1024*1024){alert((globalThis.YGCI18n?.t("ui.each_image_must_be_12_mb_or_less_1412d53f",{},"Each image must be 12 MB or less.")??"Each image must be 12 MB or less."));return;}
  }
  const form=new FormData();
  form.append('user_id',String(activeUser.user.id));
  images.forEach(image=>form.append('images',image));
  form.append('occurred_at',document.getElementById('mediaClaimDate').value||'');
  form.append('caption',document.getElementById('mediaClaimCaption').value.trim());
  const button=document.getElementById('mediaClaimSubmit');
  button.disabled=true;
  try{
    const response=await fetch('/api/individuals/'+selectedIndividualId+'/media-claim',{method:'POST',body:form});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(globalThis.YGCI18n?.errorMessage(data,response.statusText)??(data.detail||response.statusText));
    closeMediaClaim();
    await refreshClaimViews(selectedIndividualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.media_claim_could_not_be_added_43f640bd",{},"Media Claim could not be added.")??"Media Claim could not be added.")+"\n"+e.message);}
  finally{button.disabled=false;}
}

function openEventClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('eventClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  document.getElementById('eventClaimKind').value='exhibition';
  document.getElementById('eventClaimDate').value=new Date().toLocaleDateString('sv-SE');
  document.getElementById('eventClaimDetail').value='';
  document.getElementById('eventClaimImages').value='';
  YGCOverlays.open('eventClaimModal');
}
function closeEventClaim(event){
  if(event&&event.target&&event.target.id!=='eventClaimModal')return;
  YGCOverlays.close('eventClaimModal');
}
async function submitEventClaim(){
  const detail=document.getElementById('eventClaimDetail').value.trim();
  if(!detail){alert((globalThis.YGCI18n?.t("ui.enter_a_detail_8886d1e3",{},"Enter a detail.")??"Enter a detail."));return;}
  const images=Array.from(document.getElementById('eventClaimImages').files||[]);
  if(images.length>10){alert((globalThis.YGCI18n?.t("ui.choose_up_to_10_images_6981075c",{},"Choose up to 10 images.")??"Choose up to 10 images."));return;}
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){alert((globalThis.YGCI18n?.t("ui.choose_a_jpeg_png_webp_or_gif_image_2d2c2f31",{},"Choose a JPEG, PNG, WebP, or GIF image.")??"Choose a JPEG, PNG, WebP, or GIF image."));return;}
    if(image.size>12*1024*1024){alert((globalThis.YGCI18n?.t("ui.each_image_must_be_12_mb_or_less_1412d53f",{},"Each image must be 12 MB or less.")??"Each image must be 12 MB or less."));return;}
  }
  const button=document.getElementById('eventClaimSubmit');button.disabled=true;
  try{
    if(images.length){
      const form=new FormData();
      form.append('user_id',String(activeUser.user.id));
      form.append('event_kind',document.getElementById('eventClaimKind').value);
      form.append('occurred_at',document.getElementById('eventClaimDate').value||'');
      form.append('detail',detail);
      images.forEach(image=>form.append('images',image));
      await jfetch('/api/individuals/'+selectedIndividualId+'/event-claim-with-media',{method:'POST',body:form});
    }else{
      await jfetch('/api/individuals/'+selectedIndividualId+'/event-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),event_kind:document.getElementById('eventClaimKind').value,occurred_at:document.getElementById('eventClaimDate').value||null,detail})});
    }
    closeEventClaim();await refreshClaimViews(selectedIndividualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.event_claim_could_not_be_added_7c173fd7",{},"Event Claim could not be added.")??"Event Claim could not be added.")+"\n"+e.message);}
  finally{button.disabled=false;}
}

function openIncidentClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('incidentClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  document.getElementById('incidentClaimKind').value='damage';
  document.getElementById('incidentClaimDate').value=new Date().toLocaleDateString('sv-SE');
  document.getElementById('incidentClaimDetail').value='';
  YGCOverlays.open('incidentClaimModal');
}
function closeIncidentClaim(event){
  if(event&&event.target&&event.target.id!=='incidentClaimModal')return;
  YGCOverlays.close('incidentClaimModal');
}
async function submitIncidentClaim(){
  const detail=document.getElementById('incidentClaimDetail').value.trim();
  if(!detail){alert((globalThis.YGCI18n?.t("ui.enter_a_detail_8886d1e3",{},"Enter a detail.")??"Enter a detail."));return;}
  const button=document.getElementById('incidentClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/incident-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),incident_kind:document.getElementById('incidentClaimKind').value,occurred_at:document.getElementById('incidentClaimDate').value||null,detail})});
    closeIncidentClaim();await refreshClaimViews(selectedIndividualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.incident_claim_could_not_be_added_3288c834",{},"Incident Claim could not be added.")??"Incident Claim could not be added.")+"\n"+e.message);}
  finally{button.disabled=false;}
}

function setSpecificationKind(kind){
  specificationKind=kind==='repair'?'repair':'specification';
  document.getElementById('specKindSpecification').classList.toggle('active',specificationKind==='specification');
  document.getElementById('specKindRepair').classList.toggle('active',specificationKind==='repair');
}
function openSpecificationClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('specClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):(globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  editingSpecificationClaimId=null;specificationItems=[];setSpecificationKind('specification');
  document.getElementById('specClaimTitle').textContent=(globalThis.YGCI18n?.t("ui.specification_repair_claim_022acab6",{},"Specification/Repair Claim")??"Specification/Repair Claim");
  document.getElementById('specClaimSubmit').textContent=(globalThis.YGCI18n?.t("ui.add_claim_62b52157",{},"Add Claim")??"Add Claim");
  document.getElementById('specClaimDate').value=new Date().toLocaleDateString('sv-SE');
  document.getElementById('specClaimBody').value='';
  renderSpecificationItems();renderSpecItemMenu();
  YGCOverlays.open('specClaimModal', {onClose: () => document.getElementById('specItemMenu')?.classList.remove('open')});
}
function closeSpecificationClaim(event){
  if(event&&event.target&&event.target.id!=='specClaimModal')return;
  YGCOverlays.close('specClaimModal');
  const menu=document.getElementById('specItemMenu');if(menu)menu.classList.remove('open');
}
function toggleSpecItemMenu(event){
  event.stopPropagation();renderSpecItemMenu();document.getElementById('specItemMenu').classList.toggle('open');
}
function renderSpecItemMenu(){
  const menu=document.getElementById('specItemMenu');if(!menu)return;
  const used=new Set(specificationItems.map(x=>x.field_name));
  menu.innerHTML=SPEC_FIELDS.filter(([key])=>!used.has(key)).map(([key,label])=>'<button type="button" onclick="addSpecificationItem(\''+key+'\')">'+esc(label)+'</button>').join('')+("<button type=\"button\" onclick=\"addCustomSpecificationItem()\">"+(globalThis.YGCI18n?.html("ui.custom_c4e69d54",{},"Custom…")??"Custom…")+"</button>");
}
function addSpecificationItem(fieldName,label){
  if(specificationItems.some(x=>x.field_name===fieldName))return;
  const found=SPEC_FIELDS.find(([key])=>key===fieldName);
  specificationItems.push({field_name:fieldName,label:label||(found?found[1]:specificationFieldLabel(fieldName)),value_text:''});
  document.getElementById('specItemMenu').classList.remove('open');renderSpecificationItems();
}
function addCustomSpecificationItem(){
  const raw=prompt((globalThis.YGCI18n?.t("ui.enter_a_specification_field_name_a6cb1fe1",{},"Enter a Specification field name.")??"Enter a Specification field name."));if(!raw)return;
  const fieldName=raw.trim().toLowerCase().replace(/\s+/g,'_');if(!fieldName)return;
  if(specificationItems.some(x=>x.field_name===fieldName)){alert((globalThis.YGCI18n?.t("ui.that_field_has_already_been_added_9e05c0d8",{},"That field has already been added.")??"That field has already been added."));return;}
  addSpecificationItem(fieldName,raw.trim());
}
function removeSpecificationItem(index){specificationItems.splice(index,1);renderSpecificationItems();renderSpecItemMenu();}
function updateSpecificationItem(index,value){if(specificationItems[index])specificationItems[index].value_text=value;}
function renderSpecificationItems(){
  const el=document.getElementById('specClaimItems');if(!el)return;
  el.innerHTML=specificationItems.length?specificationItems.map((item,index)=>'<div class="spec-item-row"><div class="spec-item-label">'+esc(item.label)+'</div><input maxlength="500" value="'+esc(item.value_text)+'" oninput="updateSpecificationItem('+index+',this.value)" placeholder="Value"><button data-ui-action="close" type="button" class="spec-item-remove" onclick="removeSpecificationItem('+index+')">×</button></div>').join(''):("<div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.use_to_add_a_field_b047f788",{},"Use + to add a field.")??"Use + to add a field.")+"</div>");
}
async function submitSpecificationClaim(){
  const items=specificationItems.map(item=>({field_name:item.field_name,value_text:String(item.value_text||'').trim()})).filter(item=>item.value_text);
  if(!items.length){alert((globalThis.YGCI18n?.t("ui.add_at_least_one_field_and_value_2d1b7ddd",{},"Add at least one field and value.")??"Add at least one field and value."));return;}
  if(items.length!==specificationItems.length){alert((globalThis.YGCI18n?.t("ui.enter_a_value_for_every_added_field_c71607b7",{},"Enter a value for every added field.")??"Enter a value for every added field."));return;}
  const button=document.getElementById('specClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/specification-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),specification_kind:specificationKind,items,occurred_at:document.getElementById('specClaimDate').value||null,body:document.getElementById('specClaimBody').value.trim()||null})});
    closeSpecificationClaim();await refreshClaimViews(selectedIndividualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.specification_repair_claim_could_not_be_added_6090744c",{},"Specification/Repair Claim could not be added.")??"Specification/Repair Claim could not be added.")+"\n"+e.message);}
  finally{button.disabled=false;}
}

document.addEventListener('click',()=>{
  const claimMenu=document.getElementById('addClaimMenu');if(claimMenu)claimMenu.classList.remove('open');
  const specMenu=document.getElementById('specItemMenu');if(specMenu)specMenu.classList.remove('open');
});

function openFormerOwnerClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert((globalThis.YGCI18n?.t("ui.select_a_user_first_6a84fdaa",{},"Select a user first.")??"Select a user first."));
    return;
  }
  if(activeUserOwns(individualId)){
    alert((globalThis.YGCI18n?.t("ui.the_current_owner_cannot_add_a_former_owner_claim_dd2bba9c",{},"The current owner cannot add a Former Owner Claim.")??"The current owner cannot add a Former Owner Claim."));
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('formerOwnerClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : (globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  document.getElementById('formerOwnerAcquisitionDate').value='';
  document.getElementById('formerOwnerReleaseDate').value='';
  document.getElementById('formerOwnerDetail').value='';
  YGCOverlays.open('formerOwnerClaimModal');
  setTimeout(()=>document.getElementById('formerOwnerAcquisitionDate').focus(),0);
}
function closeFormerOwnerClaim(event){
  if(event&&event.target&&event.target.id!=='formerOwnerClaimModal')return;
  const modal=document.getElementById('formerOwnerClaimModal');
  if(modal)YGCOverlays.close(modal);
}
async function submitFormerOwnerClaim(){
  if(!activeUser||!activeUser.user||selectedIndividualId===null)return;
  const acquisitionDate=document.getElementById('formerOwnerAcquisitionDate').value;
  const releaseDate=document.getElementById('formerOwnerReleaseDate').value;
  if(!acquisitionDate||!releaseDate){
    alert((globalThis.YGCI18n?.t("ui.acquisition_date_and_release_date_are_required_b2d18b24",{},"Acquisition Date and Release Date are required.")??"Acquisition Date and Release Date are required."));
    return;
  }
  if(acquisitionDate>=releaseDate){
    alert((globalThis.YGCI18n?.t("ui.acquisition_date_must_be_earlier_than_release_date_0176f8df",{},"Acquisition Date must be earlier than Release Date.")??"Acquisition Date must be earlier than Release Date."));
    return;
  }
  const button=document.getElementById('formerOwnerClaimSubmit');
  button.disabled=true;
  try{
    const individualId=selectedIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/former-owner-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        user_id:Number(activeUser.user.id),
        acquisition_date:acquisitionDate,
        release_date:releaseDate,
        detail:document.getElementById('formerOwnerDetail').value.trim()||null
      })
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeFormerOwnerClaim();
    if(typeof renderAccount==='function')renderAccount();
    await refreshClaimViews(individualId);
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.former_owner_claim_could_not_be_added_46254487",{},"Former Owner Claim could not be added.")??"Former Owner Claim could not be added.")+"\n"+e.message);
  }finally{
    button.disabled=false;
  }
}

function configureOwnershipClaim(mode){
  ownershipClaimMode=mode==='add_claim'?'add_claim':'acquire';
  const kind=document.getElementById('ownershipClaimKind');
  const fixed=document.getElementById('ownershipClaimFixedTag');
  const previousRow=document.getElementById('ownershipClaimPreviousRow');
  if(ownershipClaimMode==='acquire'){
    kind.innerHTML=("<option value=\"acquire\">"+(globalThis.YGCI18n?.html("ui.acquire_910e23d5",{},"Acquire")??"Acquire")+"</option>");
    kind.value='acquire';
    kind.style.display='none';
    fixed.style.display='block';
    fixed.innerHTML=("<strong>"+(globalThis.YGCI18n?.html("ui.acquire_910e23d5",{},"Acquire")??"Acquire")+"</strong>");
    previousRow.style.display='';
  }else{
    kind.innerHTML=("<option value=\"transfer\">"+(globalThis.YGCI18n?.html("ui.transfer_dde8bef7",{},"Transfer")??"Transfer")+"</option><option value=\"release\">"+(globalThis.YGCI18n?.html("ui.release_e020e3c6",{},"Release")??"Release")+"</option>");
    kind.value='transfer';
    kind.style.display='block';
    fixed.style.display='none';
    previousRow.style.display='';
  }
}
function openOwnershipClaim(individualId,mode='acquire'){
  if(mode==='acquire'){openAcquireApplication(individualId);return}
  if(!activeUser||!activeUser.user){
    requireAccount();
    return;
  }
  if(mode==='add_claim'&&!activeUserOwns(individualId)){
    alert((globalThis.YGCI18n?.t("ui.only_the_current_owner_can_add_this_ownership_claim_7c390bdf",{},"Only the current owner can add this Ownership Claim.")??"Only the current owner can add this Ownership Claim."));
    return;
  }
  pendingOwnershipClaimIndividualId=Number(individualId);
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('ownershipClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : (globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId;
  transferSelectedUser=null;transferSearchGeneration++;document.getElementById('transferRecipientSearch').value='';document.getElementById('transferSearchResults').innerHTML='';document.getElementById('transferSelectedRecipient').textContent='';
  configureOwnershipClaim(mode);updateTransferFields();
  document.getElementById('ownershipClaimDate').value='';
  document.getElementById('ownershipClaimPrevious').value='';
  document.getElementById('ownershipClaimBody').value='';
  document.getElementById('ownershipClaimSubmit').textContent=mode==='acquire'?(globalThis.YGCI18n?.t("ui.submit_ownership_claim_0323b5a1",{},"Submit Ownership Claim")??"Submit Ownership Claim"):(globalThis.YGCI18n?.t("ui.add_claim_62b52157",{},"Add Claim")??"Add Claim");
  YGCOverlays.open('ownershipClaimModal');
}
function openOwnerClaim(individualId){
  openAcquireApplication(individualId);
}
function closeOwnershipClaim(event){
  if(event&&event.target&&event.target.id!=='ownershipClaimModal')return;
  YGCOverlays.close('ownershipClaimModal');
  pendingOwnershipClaimIndividualId=null;
}
async function submitOwnershipClaim(){
  if(!activeUser||!activeUser.user||pendingOwnershipClaimIndividualId===null)return;
  const button=document.getElementById('ownershipClaimSubmit');
  const kind=document.getElementById('ownershipClaimKind').value;
  if(kind==='transfer'){await submitTransferProposal();return}
  if(kind==='acquire'&&!document.getElementById('ownershipClaimDate').value){
    alert((globalThis.YGCI18n?.t("ui.acquire_requires_an_acquisition_date_a22575cf",{},"Acquire requires an acquisition date.")??"Acquire requires an acquisition date."));
    document.getElementById('ownershipClaimDate').focus();
    return;
  }
  if(kind==='release'){
    const guitar=individuals.find(x=>Number(x.id)===Number(pendingOwnershipClaimIndividualId));
    const label=guitar?guitar.manufacturer+' '+(guitar.model||''):'this guitar';
    if(!await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.release_e020e3c6",{},"Release")??"Release"),label+" "+(globalThis.YGCI18n?.t("ui.will_be_released_and_current_owner_will_become_unknown_con_850ccc36",{},"will be released and Current Owner will become Unknown. Continue?")??"will be released and Current Owner will become Unknown. Continue?")))return;
  }
  button.disabled=true;
  try{
    const body={
      user_id:Number(activeUser.user.id),
      ownership_kind:kind,
      occurred_at:document.getElementById('ownershipClaimDate').value||null,
      previous_owner_text:document.getElementById('ownershipClaimPrevious').value.trim()||null,
      body:document.getElementById('ownershipClaimBody').value.trim()||null
    };
    const individualId=pendingOwnershipClaimIndividualId;
    const d=await jfetch('/api/individuals/'+individualId+'/ownership-claim',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    activeUser={user:d.user,guitars:d.guitars};
    closeOwnershipClaim();
    if(typeof renderAccount==='function')renderAccount();
    await refreshClaimViews(individualId);
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.could_not_add_the_ownership_claim_8d07714d",{},"Could not add the Ownership Claim.")??"Could not add the Ownership Claim.")+"\n"+e.message);
  }finally{
    button.disabled=false;
  }
}

const WORLD_GEOJSON_URL='https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson';

function normalizeCountryName(value){
  const v=String(value||'').trim().toLowerCase()
    .replace(/\./g,'')
    .replace(/&/g,'and')
    .replace(/\s+/g,' ');
  const aliases={
    'us':'united states of america','usa':'united states of america','united states':'united states of america',
    'gb':'united kingdom','gbr':'united kingdom','uk':'united kingdom','great britain':'united kingdom',
    'jp':'japan','jpn':'japan',
    'ch':'switzerland','che':'switzerland',
    'de':'germany','deu':'germany',
    'fr':'france','fra':'france',
    'it':'italy','ita':'italy',
    'es':'spain','esp':'spain',
    'pt':'portugal','prt':'portugal',
    'nl':'netherlands','nld':'netherlands',
    'be':'belgium','bel':'belgium',
    'at':'austria','aut':'austria',
    'se':'sweden','swe':'sweden',
    'no':'norway','nor':'norway',
    'dk':'denmark','dnk':'denmark',
    'fi':'finland','fin':'finland',
    'ie':'ireland','irl':'ireland',
    'pl':'poland','pol':'poland',
    'cz':'czechia','cze':'czechia','czech republic':'czechia',
    'sk':'slovakia','svk':'slovakia',
    'hu':'hungary','hun':'hungary',
    'ro':'romania','rou':'romania',
    'gr':'greece','grc':'greece',
    'ca':'canada','can':'canada',
    'mx':'mexico','mex':'mexico',
    'br':'brazil','bra':'brazil',
    'ar':'argentina','arg':'argentina',
    'cl':'chile','chl':'chile',
    'au':'australia','aus':'australia',
    'nz':'new zealand','nzl':'new zealand',
    'cn':'china','chn':'china',
    'kr':'republic of korea','kor':'republic of korea','south korea':'republic of korea','korea, south':'republic of korea',
    'kp':'democratic peoples republic of korea','prk':'democratic peoples republic of korea','north korea':'democratic peoples republic of korea',
    'tw':'taiwan','twn':'taiwan',
    'hk':"hong kong s.a.r.",'hkg':"hong kong s.a.r.",'hong kong':"hong kong s.a.r.",
    'mo':'macao s.a.r','mac':'macao s.a.r','macau':'macao s.a.r',
    'sg':'singapore','sgp':'singapore',
    'my':'malaysia','mys':'malaysia',
    'th':'thailand','tha':'thailand',
    'vn':'vietnam','vnm':'vietnam','viet nam':'vietnam',
    'ph':'philippines','phl':'philippines',
    'id':'indonesia','idn':'indonesia',
    'in':'india','ind':'india',
    'ru':'russian federation','rus':'russian federation','russia':'russian federation',
    'tr':'turkey','tur':'turkey',
    'il':'israel','isr':'israel',
    'ae':'united arab emirates','are':'united arab emirates',
    'za':'south africa','zaf':'south africa'
  };
  return aliases[v]||v;
}
function geoCountryName(feature){
  const p=feature&&feature.properties||{};
  return p.ADMIN||p.NAME||p.NAME_EN||p.SOVEREIGNT||'';
}
function mapProjection(coord){
  const lon=Number(coord[0]||0);
  const lat=Math.max(-85,Math.min(85,Number(coord[1]||0)));
  return [
    (lon+180)/360*1000,
    (90-lat)/180*500
  ];
}
function ringPath(ring){
  if(!Array.isArray(ring)||!ring.length)return '';
  return ring.map((coord,index)=>{
    const p=mapProjection(coord);
    return (index?'L':'M')+p[0].toFixed(2)+' '+p[1].toFixed(2);
  }).join(' ')+' Z';
}
function geometryPath(geometry){
  if(!geometry)return '';
  if(geometry.type==='Polygon'){
    return (geometry.coordinates||[]).map(ringPath).join(' ');
  }
  if(geometry.type==='MultiPolygon'){
    return (geometry.coordinates||[]).flatMap(poly=>poly.map(ringPath)).join(' ');
  }
  return '';
}
function mapFill(count,maxCount){
  if(!count)return '#20262a';
  const t=maxCount>1?Math.log(count+1)/Math.log(maxCount+1):1;
  const a=[65,55,39];
  const b=[208,164,93];
  const rgb=a.map((v,i)=>Math.round(v+(b[i]-v)*t));
  return 'rgb('+rgb.join(',')+')';
}
async function loadWorldMap(){
  const svg=document.getElementById('worldMapSvg');
  const wrap=document.getElementById('worldMapWrap');
  const tooltip=document.getElementById('worldMapTooltip');
  if(!svg||!wrap||!tooltip)return;

  let geo,data;
  try{
    [geo,data]=await Promise.all([
      fetch(WORLD_GEOJSON_URL).then(r=>{if(!r.ok)throw new Error(r.statusText);return r.json()}),
      jfetch('/api/world-map')
    ]);
  }catch(e){
    svg.innerHTML=("<text x=\"500\" y=\"250\" text-anchor=\"middle\" fill=\"#9ba6b0\" font-size=\"14\">"+(globalThis.YGCI18n?.html("ui.world_map_could_not_be_loaded_e0f704fa",{},"World map could not be loaded.")??"World map could not be loaded.")+"</text>");
    return;
  }

  const counts=new Map();
  for(const item of (data.countries||[])){
    counts.set(normalizeCountryName(item.country),Number(item.count||0));
  }
  const maxCount=Math.max(0,...Array.from(counts.values()));
  const ns='http://www.w3.org/2000/svg';
  svg.innerHTML='';

  for(const feature of (geo.features||[])){
    const name=geoCountryName(feature);
    const key=normalizeCountryName(name);
    const count=counts.get(key)||0;
    const d=geometryPath(feature.geometry);
    if(!d)continue;
    const path=document.createElementNS(ns,'path');
    path.setAttribute('d',d);
    path.setAttribute('class','world-country');
    path.setAttribute('fill',mapFill(count,maxCount));
    path.dataset.country=name;
    path.dataset.count=String(count);
    path.addEventListener('mouseenter',event=>{
      tooltip.textContent=name+' — '+count+" "+(globalThis.YGCI18n?.t("ui.product_fb9ef894",{},"Product")??"Product")+(count===1?'':'s');
      tooltip.style.display='block';
    });
    path.addEventListener('mousemove',event=>{
      const rect=wrap.getBoundingClientRect();
      tooltip.style.left=Math.min(rect.width-150,event.clientX-rect.left+12)+'px';
      tooltip.style.top=Math.max(6,event.clientY-rect.top-26)+'px';
    });
    path.addEventListener('mouseleave',()=>{tooltip.style.display='none'});
    svg.appendChild(path);
  }
}

let topPageCharts=[];

function destroyTopPageCharts(){
  topPageCharts.forEach(chart=>{try{chart.destroy()}catch(e){}});
  topPageCharts=[];
}
function chartTextColor(){
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim()||'#edf0f3';
}
function chartMutedColor(){
  return getComputedStyle(document.documentElement).getPropertyValue('--muted').trim()||'#9ba6b0';
}
function chartLineColor(){
  return getComputedStyle(document.documentElement).getPropertyValue('--line').trim()||'#2a2f35';
}
function chartPalette(count){
  const base=[
    '#d0a45d','#66c58a','#6fa8dc','#c27ba0','#e07171',
    '#8e7cc3','#76a5af','#f6b26b','#93c47d','#a4c2f4','#999999'
  ];
  return Array.from({length:count},(_,i)=>base[i%base.length]);
}
function chartFallback(canvasId,message){
  const canvas=document.getElementById(canvasId);
  if(!canvas)return;
  const wrap=canvas.parentElement;
  if(wrap)wrap.innerHTML='<div class="chart-error">'+esc(message)+'</div>';
}
async function loadTopPageCharts(){
  let data;
  try{
    data=await jfetch('/api/top-page-charts');
  }catch(e){
    ['modelChart','yearChart','listingChart'].forEach(id=>chartFallback(id,(globalThis.YGCI18n?.t("ui.statistics_could_not_be_loaded_8a2bedab",{},"Statistics could not be loaded.")??"Statistics could not be loaded.")));
    return;
  }
  if(typeof Chart==='undefined'){
    ['modelChart','yearChart','listingChart'].forEach(id=>chartFallback(id,(globalThis.YGCI18n?.t("ui.chart_library_could_not_be_loaded_78341284",{},"Chart library could not be loaded.")??"Chart library could not be loaded.")));
    return;
  }

  destroyTopPageCharts();
  const text=chartTextColor();
  const muted=chartMutedColor();
  const line=chartLineColor();
  Chart.defaults.color=muted;
  Chart.defaults.borderColor=line;
  Chart.defaults.font.family='"Noto Sans JP", sans-serif';

  const models=data.models||[];
  const modelCanvas=document.getElementById('modelChart');
  if(modelCanvas&&models.length){
    topPageCharts.push(new Chart(modelCanvas,{
      type:'pie',
      data:{
        labels:models.map(x=>x.label),
        datasets:[{
          data:models.map(x=>Number(x.count||0)),
          backgroundColor:chartPalette(models.length),
          borderColor:'#181b1f',
          borderWidth:2
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{
          legend:{position:'right',labels:{boxWidth:10,boxHeight:10,color:text,font:{size:10}}},
          tooltip:{callbacks:{label:ctx=>' '+ctx.label+': '+ctx.parsed}}
        }
      }
    }));
  }else{
    chartFallback('modelChart',(globalThis.YGCI18n?.t("ui.no_model_data_d9d50d05",{},"No model data.")??"No model data."));
  }

  const years=data.years||[];
  const yearCanvas=document.getElementById('yearChart');
  if(yearCanvas&&years.length){
    topPageCharts.push(new Chart(yearCanvas,{
      type:'bar',
      data:{
        labels:years.map(x=>x.label),
        datasets:[{
          label:(globalThis.YGCI18n?.t("ui.products_4edc8bfa",{},"Products")??"Products"),
          data:years.map(x=>Number(x.count||0)),
          backgroundColor:'#6fa8dc',
          borderWidth:0
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{
          x:{
            grid:{display:false},
            ticks:{color:muted,maxRotation:60,minRotation:0,font:{size:9},autoSkip:true,maxTicksLimit:16}
          },
          y:{
            beginAtZero:true,
            ticks:{precision:0,color:muted,font:{size:9}},
            grid:{color:line}
          }
        }
      }
    }));
  }else{
    chartFallback('yearChart',(globalThis.YGCI18n?.t("ui.no_year_data_182e6336",{},"No year data.")??"No year data."));
  }

  const listings=data.listings_30d||[];
  const listingCanvas=document.getElementById('listingChart');
  if(listingCanvas&&listings.length){
    topPageCharts.push(new Chart(listingCanvas,{
      type:'bar',
      data:{
        labels:listings.map(x=>{
          const parts=String(x.date||'').split('-');
          return parts.length===3?Number(parts[1])+'/'+Number(parts[2]):x.date;
        }),
        datasets:[{
          label:(globalThis.YGCI18n?.t("ui.listings_5009238d",{},"Listings")??"Listings"),
          data:listings.map(x=>Number(x.count||0)),
          backgroundColor:'#d0a45d',
          borderWidth:0
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{legend:{display:false}},
        scales:{
          x:{
            grid:{display:false},
            ticks:{color:muted,maxRotation:0,minRotation:0,font:{size:9},autoSkip:true,maxTicksLimit:15}
          },
          y:{
            beginAtZero:true,
            ticks:{precision:0,color:muted,font:{size:9}},
            grid:{color:line}
          }
        }
      }
    }));
  }else{
    chartFallback('listingChart',(globalThis.YGCI18n?.t("ui.no_listing_data_5143450a",{},"No listing data.")??"No listing data."));
  }
}

function profileGuitarTable(section,title){
  const columns=[['id','ID'],['favorite','♡'],['manufacturer',(globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker")],['model',(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model")],['finish',(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish")],['year',(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year")],['serial_number',(globalThis.YGCI18n?.t("ui.serial_8ea09493",{},"Serial")??"Serial")],['claim_count',(globalThis.YGCI18n?.t("ui.claims_1c85c122",{},"Claims")??"Claims")]];
  return '<section class="panel profile-panel profile-list-panel page-section" data-profile-section="'+section+'" id="profile-'+section+'">'+
    '<div class="toolbar"><h2 data-count-items="#profileRows-'+section+' > tr.clickable">'+title+'</h2><input id="profileFilter-'+section+'" placeholder="maker / model / finish / year / serial" data-i18n-placeholder="ui.maker_model_finish_year_serial_c99806fd" oninput="renderProfileGuitars(\''+section+'\')"></div>'+
    '<div class="table-wrap"><table><thead><tr>'+columns.map(([key,label])=>key==='favorite'?"<th class=\"favorite-cell\" aria-label=\"Favorite\" data-i18n-aria-label=\"ui.favorite_ea713ecd\">"+label+'</th>':'<th class="sortable" onclick="setProfileSort(\''+section+'\',\''+key+'\')">'+label+'<span class="sort-indicator" id="profileSort-'+section+'-'+key+'"></span></th>').join('')+'</tr></thead>'+
    '<tbody id="profileRows-'+section+'"></tbody></table></div>'+
    (section==='owned'?("<button id=\"newGuitarAction\" class=\"new-guitar-action\" type=\"button\" onclick=\"openNewGuitar()\" hidden>"+(globalThis.YGCI18n?.html("ui.let_s_add_your_undiscovered_new_guitar_a2e1bb34",{},"Let's add your undiscovered new guitar!")??"Let's add your undiscovered new guitar!")+"</button>"):'')+'</section>';
}
function openNewGuitar(){
  if(!activeUser?.user||Number(activeUser.user.id)!==PROFILE_USER_ID)return;
  if(acquireBusy)return;
  acquireRevision=null;acquireDisplayState=null;acquireForm=null;
  setRequestTitle((globalThis.YGCI18n?.t("ui.listing_request_32432123",{},"Listing Request")??"Listing Request"),(globalThis.YGCI18n?.t("ui.awaiting_details_041b5dbf",{},"Awaiting details")??"Awaiting details"));
  document.getElementById('acquireReviewContent').innerHTML=("<p>"+(globalThis.YGCI18n?.html("ui.1_enter_details_and_generate_a_challenge_2_photograph_the__5c8a6d06",{},"1. Enter details and generate a challenge → 2. Photograph the guitar with the code → 3. Submit both photos")??"1. Enter details and generate a challenge → 2. Photograph the guitar with the code → 3. Submit both photos")+"</p>")+listingMetadataFields()+ownershipChallengeBox(null)+ownershipEvidenceFields({listing:true,issued:false,date:new Date().toLocaleDateString('sv-SE')})+'<p id="guitarStatus" class="sub" role="status"></p>';
  requestFooter();
  YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});
  document.getElementById('guitarMaker').focus();
}
function closeNewGuitar(){closeAcquireReview()}
async function submitNewGuitar(){
  if(acquireBusy)return;
  if(!await confirmOwnershipAction((globalThis.YGCI18n?.t("ui.generate_challenge_321afa1e",{},"Generate Challenge")??"Generate Challenge"),(globalThis.YGCI18n?.t("ui.generate_a_challenge_for_these_guitar_details_the_request__87d1375f",{},"Generate a challenge for these guitar details? The request will not be saved yet.")??"Generate a challenge for these guitar details? The request will not be saved yet.")))return;
  acquireBusy=true;
  try{await prepareListingDraft()}catch(error){alert(error.message)}finally{acquireBusy=false}
}
async function prepareListingDraft(){
  if(!activeUser?.user||Number(activeUser.user.id)!==PROFILE_USER_ID)return;
  const field=id=>document.getElementById(id);
  const payload={};for(const [key,id] of Object.entries({manufacturer:'guitarMaker',serial_number:'guitarSerial',model:'guitarModel',finish:'guitarFinish',year:'guitarYear',occurred_at:'acquireDate',body:'acquireBody'}))payload[key]=field(id).value.trim();
  if(!payload.manufacturer||!payload.serial_number||!payload.occurred_at)throw new Error((globalThis.YGCI18n?.t("ui.enter_the_maker_serial_and_date_b8c8e326",{},"Enter the maker, serial and date.")??"Enter the maker, serial and date."));
  const row=await jfetch('/api/ownership-drafts/listing'+acquireQuery(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(row.status==='duplicate'){
    field('guitarStatus').innerHTML=(globalThis.YGCI18n?.t("ui.this_maker_and_serial_are_already_registered_use_acquire_o_aa7513e8",{},"This maker and serial are already registered. Use Acquire on the existing guitar.")??"This maker and serial are already registered. Use Acquire on the existing guitar.")+row.existing_individual_ids.map(id=>'<a href="/users/'+Number(activeUser.user.id)+'?individual_id='+Number(id)+'">Guitar #'+Number(id)+' — View</a>').join('');return;
  }
  acquireRevision=row.revision;renderAcquireApplication(row);document.getElementById('acquireReviewContent').parentElement.scrollTop=0;
}
function setProfileSort(section,key){
  const state=profileSort[section];
  if(state.key===key)state.direction*=-1;
  else{state.key=key;state.direction=1}
  renderProfileGuitars(section);
  document.getElementById('profileRows-'+section).closest('.table-wrap').scrollTop=0;
}
function renderProfileGuitars(section){
  const root=document.getElementById('profileRows-'+section);
  if(!root)return;
  const filter=document.getElementById('profileFilter-'+section).value.trim().toLowerCase();
  const status=section==='owned'?'current_owner':'former_owner';
  const state=profileSort[section];
  const unfiltered=section==='favorites'?profileFavorites:profileGuitars.filter(g=>g.ownership_status===status);
  const rows=unfiltered.filter(g=>
    [g.manufacturer,g.model,g.finish,g.year,g.serial_number].join(' ').toLowerCase().includes(filter)).sort((a,b)=>{
      const av=normalizeSortValue(state.key==='id'?a.individual_id:a[state.key],state.key);
      const bv=normalizeSortValue(state.key==='id'?b.individual_id:b[state.key],state.key);
      if(av<bv)return -state.direction;
      if(av>bv)return state.direction;
      return Number(a.individual_id)-Number(b.individual_id);
    });
  for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){
    const el=document.getElementById('profileSort-'+section+'-'+key);
    if(el)el.textContent=state.key===key?(state.direction===1?'▲':'▼'):'';
  }
  root.innerHTML=rows.length?rows.map(g=>
    '<tr class="clickable'+(Number(g.individual_id)===Number(selectedIndividualId)?' selected':'')+'" onclick="showIndividual('+Number(g.individual_id)+',true)">'+
      '<td>'+Number(g.individual_id)+'</td><td class="favorite-cell">'+favoriteButton(g.individual_id)+'</td><td>'+esc(g.manufacturer)+'</td><td>'+esc(g.model||'')+'</td><td>'+esc(g.finish||'')+'</td><td>'+esc(g.year||'')+'</td><td class="mono">'+esc(g.serial_number||'')+'</td><td>'+Number(g.claim_count||0)+'</td></tr>'
  ).join(''):'<tr><td colspan="8" class="sub">'+(filter?(globalThis.YGCI18n?.t("ui.no_matching_guitars_eb9458e7",{},"No matching guitars.")??"No matching guitars."):(globalThis.YGCI18n?.t("ui.no_guitars_yet_9cac0d7d",{},"No guitars yet.")??"No guitars yet."))+'</td></tr>';
  sizeGuitarList(root.closest('.profile-list-panel'),unfiltered.length);
}
function renderUserChronicle(items){
  const root=document.getElementById('userChronicleList');
  if(!root)return;
  root.innerHTML=items.length?items.map(item=>{
    const category=['User','Social','Product','Claim','Other'].includes(item.category)?item.category:'Other';
    const categoryKeys={User:'ui.user_b512d97e',Social:'ui.social_f1b7505a',Product:'ui.product_fb9ef894',Claim:'ui.claim_4ca41db0',Other:'ui.other_f97e9da0'};
    const categoryLabel=globalThis.YGCI18n?.t(categoryKeys[category],{},category)??category;
    const id=Number(item.individual_id||0);
    const clickable=id>0;
    const interaction=clickable?' onclick="showIndividual('+id+',true)" role="button" tabindex="0" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();showIndividual('+id+',true)}"':'';
    const story=String(item.subject||'')+' '+String(item.message||'');
    return '<div class="profile-chronicle-row'+(clickable?' clickable':'')+'"'+interaction+' title="'+esc(story)+'">'+
      '<span class="profile-chronicle-tag '+category.toLowerCase()+'">'+esc(categoryLabel)+'</span>'+
      '<span class="profile-chronicle-line" aria-hidden="true"></span>'+
      '<span class="profile-chronicle-time">'+esc(displayDiscoveryDateTime(item.event_at))+'</span>'+
      '<span class="profile-chronicle-story"><strong>'+esc(item.subject||'')+'</strong> '+esc(item.message||'')+'</span></div>';
  }).join(''):("<div class=\"profile-placeholder\">"+(globalThis.YGCI18n?.html("ui.no_chronicle_entries_yet_f608f326",{},"No Chronicle entries yet.")??"No Chronicle entries yet.")+"</div>");
}
function setupProfileShell(){
  document.body.classList.add('profile-mode');
  document.querySelector('header .sub').textContent=(globalThis.YGCI18n?.t("ui.user_profile_ee7672e2",{},"User Profile")??"User Profile");
  const nav=document.querySelector('.page-nav');
  nav.innerHTML=("<a href=\"/user-view\">"+(globalThis.YGCI18n?.html("ui.top_page_272373b6",{},"Top Page")??"Top Page")+"</a><a href=\"#profile-user\">"+(globalThis.YGCI18n?.html("ui.user_profile_ee7672e2",{},"User Profile")??"User Profile")+"</a><a href=\"#profile-owned\">"+(globalThis.YGCI18n?.html("ui.owned_guitars_bb07d3cd",{},"Owned Guitars")??"Owned Guitars")+"</a><a href=\"#profile-former\">"+(globalThis.YGCI18n?.html("ui.formerly_owned_guitars_0769f4fa",{},"Formerly Owned Guitars")??"Formerly Owned Guitars")+"</a><a href=\"#profile-favorites\">"+(globalThis.YGCI18n?.html("ui.favorite_guitars_e1514ac1",{},"Favorite Guitars")??"Favorite Guitars")+"</a><a href=\"#profile-chronicle\">"+(globalThis.YGCI18n?.html("ui.user_chronicle_78bcd753",{},"User Chronicle")??"User Chronicle")+"</a>");
  document.querySelector('.left-column').innerHTML=
    ("<section class=\"panel profile-panel page-section\" data-profile-section=\"user\" id=\"profile-user\"><h2>"+(globalThis.YGCI18n?.html("ui.user_profile_ee7672e2",{},"User Profile")??"User Profile")+"</h2><div id=\"profileHero\" class=\"sub\">"+(globalThis.YGCI18n?.html("ui.loading_47d2a515",{},"Loading...")??"Loading...")+"</div></section>")+
    profileGuitarTable('owned',(globalThis.YGCI18n?.t("ui.owned_guitars_bb07d3cd",{},"Owned Guitars")??"Owned Guitars"))+
    profileGuitarTable('former',(globalThis.YGCI18n?.t("ui.formerly_owned_guitars_0769f4fa",{},"Formerly Owned Guitars")??"Formerly Owned Guitars"))+
    profileGuitarTable('favorites',(globalThis.YGCI18n?.t("ui.favorite_guitars_e1514ac1",{},"Favorite Guitars")??"Favorite Guitars"))+
    ("<section class=\"panel profile-panel page-section\" data-profile-section=\"chronicle\" id=\"profile-chronicle\"><h2 data-count-items=\"#userChronicleList > .profile-chronicle-row\">"+(globalThis.YGCI18n?.html("ui.user_chronicle_78bcd753",{},"User Chronicle")??"User Chronicle")+"</h2><div class=\"profile-activity-list\" id=\"userChronicleList\"><div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.loading_47d2a515",{},"Loading...")??"Loading...")+"</div></div></section>");
  for(const selector of ['#statistics','#world-map','.page-bottom-space']){
    const el=document.querySelector(selector);
    if(el)el.remove();
  }
  document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.select_a_guitar_from_this_profile_to_view_its_product_deta_1821cb44",{},"Select a guitar from this profile to view its Product Detail.")??"Select a guitar from this profile to view its Product Detail.");
}
let transferSelectedUser=null,transferCandidates=[],transferSearchOffset=0,transferSearchGeneration=0,transferReviewRecord=null;
function updateTransferFields(){
  const transfer=document.getElementById('ownershipClaimKind').value==='transfer';
  document.getElementById('transferRecipientRow').hidden=!transfer;
  document.getElementById('transferSearchMore').hidden=true;
  document.getElementById('ownershipClaimDate').closest('.form-row').hidden=transfer;
  document.getElementById('ownershipClaimPreviousRow').hidden=transfer;
  document.getElementById('ownershipClaimPreviousRow').style.display=transfer?'none':'';
  document.getElementById('ownershipClaimBody').closest('.form-row').hidden=transfer;
}
async function searchTransferRecipients(more=false){
  const query=document.getElementById('transferRecipientSearch').value.trim();if(!query)return;
  const generation=++transferSearchGeneration,offset=more?transferSearchOffset:0;
  if(!more){transferCandidates=[];transferSelectedUser=null;document.getElementById('transferSelectedRecipient').textContent=''}
  try{
    const users=await jfetch('/api/transfer-users?viewer_id='+Number(activeUser.user.id)+'&q='+encodeURIComponent(query)+'&offset='+offset);
    if(generation!==transferSearchGeneration)return;
    transferCandidates=[...transferCandidates,...users];transferSearchOffset=offset+users.length;
    document.getElementById('transferSearchResults').innerHTML=transferCandidates.map((u,index)=>'<button type="button" style="display:block;width:100%;text-align:left;margin-top:4px" onclick="selectTransferRecipient('+index+')">'+esc(u.display_name)+' · #'+Number(u.id)+' · '+esc(u.account_type)+'</button>').join('')||("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_matching_users_579f8c39",{},"No matching users.")??"No matching users.")+"</p>");
    document.getElementById('transferSearchMore').hidden=users.length<20;
  }catch(e){if(generation===transferSearchGeneration)document.getElementById('transferSearchResults').textContent=e.message}
}
function selectTransferRecipient(index){transferSelectedUser=transferCandidates[index];document.getElementById('transferSelectedRecipient').textContent=(globalThis.YGCI18n?.t("ui.to_2b5fc5c9",{},"To:")??"To:")+" "+transferSelectedUser.display_name+' (#'+transferSelectedUser.id+')'}
async function submitTransferProposal(){
  if(!transferSelectedUser){alert((globalThis.YGCI18n?.t("ui.select_a_recipient_from_the_search_results_9c499f68",{},"Select a recipient from the search results.")??"Select a recipient from the search results."));return}
  const button=document.getElementById('ownershipClaimSubmit'),individualId=pendingOwnershipClaimIndividualId;button.disabled=true;
  try{
    await jfetch('/api/individuals/'+individualId+'/transfers?viewer_id='+Number(activeUser.user.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_user_id:Number(transferSelectedUser.id)})});
    closeOwnershipClaim();await refreshClaimViews(individualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.transfer_could_not_be_proposed_fd3fc69f",{},"Transfer could not be proposed.")??"Transfer could not be proposed.")+"\n"+e.message)}finally{button.disabled=false}
}
async function openTransferReview(claimId){
  const dialog=document.getElementById('transferReviewDialog');YGCOverlays.open(dialog);
  transferReviewRecord=null;document.getElementById('transferReviewBody').textContent=(globalThis.YGCI18n?.t("ui.loading_47d2a515",{},"Loading...")??"Loading...");document.getElementById('transferReviewActions').innerHTML='';document.getElementById('transferReviewStatus').textContent='';
  try{
    const t=await jfetch('/api/transfers/'+claimId+'?viewer_id='+Number(activeUser.user.id));transferReviewRecord=t;
    document.getElementById('transferReviewBody').innerHTML='<strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+'</strong><p>'+esc([t.guitar?.manufacturer,t.guitar?.model,t.guitar?.serial_number].filter(Boolean).join(' / '))+' · #'+Number(t.individual_id)+' · '+esc(t.state)+'</p>'+(t.accepted_at?("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.info_transfer_accepted_on_ba2319c7",{},"Info: Transfer accepted on")??"Info: Transfer accepted on")+" ")+esc(displayInputDate(t.accepted_at))+'</p>':("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.accept_confirms_this_ownership_transfer_verification_remai_886c7b21",{},"Accept confirms this ownership transfer. Verification remains a separate Claim judgement.")??"Accept confirms this ownership transfer. Verification remains a separate Claim judgement.")+"</p>"));
    if(t.state==='pending'&&t.claim_active){
      const choices=Number(activeUser.user.id)===t.to_user_id?['accept','decline']:['cancel'];
      document.getElementById('transferReviewActions').innerHTML=choices.map(action=>'<button data-ui-action="'+(action==='accept'?'primary':action==='cancel'?'danger':'neutral')+'" type="button" onclick="resolveTransfer(\''+action+'\')">'+action[0].toUpperCase()+action.slice(1)+'</button>').join('');
    }
  }catch(e){document.getElementById('transferReviewBody').textContent=e.message}
}
async function resolveTransfer(action){
  const t=transferReviewRecord;if(!t)return;
  const buttons=[...document.getElementById('transferReviewActions').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  try{
    await jfetch('/api/transfers/'+t.claim_id+'/resolve?viewer_id='+Number(activeUser.user.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    YGCOverlays.close('transferReviewDialog');closeClaimPopup();await refreshClaimViews(t.individual_id);
  }catch(e){document.getElementById('transferReviewStatus').textContent=e.message;buttons.forEach(b=>b.disabled=false)}
}

let dmInbox={unread_count:0,conversations:[],next_before_id:null},dmPeer=null,dmBefore=null,dmGeneration=0,dmSending=false,dmHistoryLoading=false,dmInboxLoading=false;
function dmActor(){return Number(activeUser?.user?.id||0)}
function dmStatus(text){document.getElementById('dmStatus').textContent=text}
function renderDirectMessageInbox(){
  document.getElementById('dmConversationList').innerHTML=dmInbox.conversations.map(c=>'<button type="button" class="dm-conversation'+(Number(c.peer_id)===dmPeer?' selected':'')+'" onclick="selectDirectMessagePeer('+Number(c.peer_id)+')"><strong>'+esc(c.peer_name)+'</strong> '+(c.unread_count?'<span class="account-hub-count">'+Number(c.unread_count)+'</span>':'')+'<div class="dm-preview">'+esc(c.preview)+'</div></button>').join('')||("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_conversations_yet_52a87373",{},"No conversations yet.")??"No conversations yet.")+"</p>");
  document.getElementById('dmMoreConversations').hidden=!dmInbox.next_before_id;
  updateUnreadHeaderAction('directMessageCount',dmInbox.unread_count);
}
async function loadDirectMessageInbox(append=false){
  if(!dmActor()){dmInbox={unread_count:0,conversations:[],next_before_id:null};return}
  if(dmInboxLoading)return;
  dmInboxLoading=true;document.getElementById('dmMoreConversations').disabled=true;
  try{
    const cursor=append?dmInbox.next_before_id:null;if(append&&!cursor)return;
    const result=await jfetch('/api/dm?viewer_id='+dmActor()+(cursor?'&before_id='+cursor:''));
    const previous=append?dmInbox.conversations:[];
    dmInbox={...result,conversations:[...previous,...result.conversations.filter(c=>!previous.some(p=>p.peer_id===c.peer_id))]};
    renderDirectMessageInbox();
  }catch(e){if(document.getElementById('directMessageDialog').open)dmStatus(e.message)}
  finally{dmInboxLoading=false;document.getElementById('dmMoreConversations').disabled=false}
}
async function openDirectMessages(peer=null){
  if(!dmActor())return;
  const dialog=document.getElementById('directMessageDialog');
  dmStatus('');
  YGCOverlays.open(dialog);
  await loadDirectMessageInbox();
  if(peer)await selectDirectMessagePeer(Number(peer));
  else if(dmPeer)await loadDirectMessageHistory();
}
async function selectDirectMessagePeer(peer){
  if(dmSending)return;
  dmPeer=Number(peer);dmBefore=null;dmGeneration++;dmHistoryLoading=false;
  document.getElementById('dmBody').value='';document.getElementById('dmComposeForm').hidden=true;
  document.getElementById('dmThread').innerHTML='';document.getElementById('dmPeerTitle').textContent=(globalThis.YGCI18n?.t("ui.loading_conversation_05ddf541",{},"Loading conversation...")??"Loading conversation...");
  renderDirectMessageInbox();await loadDirectMessageHistory();
}
async function loadDirectMessageHistory(older=false){
  if(!dmPeer||dmHistoryLoading)return;
  const peer=dmPeer,generation=dmGeneration,cursor=older?dmBefore:null;
  if(older&&!cursor)return;
  dmHistoryLoading=true;document.getElementById('dmOlder').disabled=true;dmStatus((globalThis.YGCI18n?.t("ui.loading_47d2a515",{},"Loading...")??"Loading..."));
  try{
    const data=await jfetch('/api/dm/users/'+peer+'/messages?viewer_id='+dmActor()+(cursor?'&before_id='+cursor:''));
    if(generation!==dmGeneration)return;
    document.getElementById('dmPeerTitle').innerHTML='<a href="/users/'+Number(data.peer.id)+'" style="color:var(--text)">'+esc(data.peer.display_name)+'</a>';
    const thread=document.getElementById('dmThread'),height=thread.scrollHeight,top=thread.scrollTop;
    const content=data.messages.map(m=>'<div class="dm-message'+(m.sender_user_id===dmActor()?' mine':'')+'">'+esc(m.body)+'<div class="dm-time">'+esc(displayDiscoveryDateTime(m.created_at))+'</div></div>').join('');
    if(older){thread.insertAdjacentHTML('afterbegin',content);thread.scrollTop=top+thread.scrollHeight-height}
    else{thread.innerHTML=content||("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.start_a_conversation_59eb2538",{},"Start a conversation.")??"Start a conversation.")+"</p>");thread.scrollTop=thread.scrollHeight}
    dmBefore=data.next_before_id;document.getElementById('dmOlder').hidden=!dmBefore;
    document.getElementById('dmComposeForm').hidden=false;dmStatus('');
    if(data.messages.length&&document.getElementById('directMessageDialog').open){
      await jfetch('/api/dm/users/'+peer+'/read?viewer_id='+dmActor(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({through_id:data.messages[data.messages.length-1].id})});
      await loadDirectMessageInbox();
    }
  }catch(e){if(generation===dmGeneration)dmStatus(e.message)}
  finally{if(generation===dmGeneration){dmHistoryLoading=false;document.getElementById('dmOlder').disabled=false}}
}
async function sendDirectMessage(){
  const peer=dmPeer,input=document.getElementById('dmBody'),body=input.value.trim();
  if(!peer||dmSending)return;
  if(dmHistoryLoading){dmStatus((globalThis.YGCI18n?.t("ui.wait_for_the_conversation_to_finish_loading_79d6b09a",{},"Wait for the conversation to finish loading.")??"Wait for the conversation to finish loading."));return}
  if(!body){dmStatus((globalThis.YGCI18n?.t("ui.enter_a_message_e10b2270",{},"Enter a message.")??"Enter a message."));return}
  dmSending=true;document.getElementById('dmSend').disabled=true;input.disabled=true;dmStatus((globalThis.YGCI18n?.t("ui.sending_286a3af7",{},"Sending...")??"Sending..."));
  try{
    await jfetch('/api/dm/users/'+peer+'/messages?viewer_id='+dmActor(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body})});
    input.value='';await loadDirectMessageHistory();await loadDirectMessageInbox();dmStatus((globalThis.YGCI18n?.t("ui.message_sent_a3d34439",{},"Message sent.")??"Message sent."));
  }catch(e){dmStatus(e.message)}
  finally{dmSending=false;document.getElementById('dmSend').disabled=false;input.disabled=false}
}
async function refreshDirectMessages(){if(dmSending)return;await loadDirectMessageInbox();if(dmPeer)await loadDirectMessageHistory()}

async function toggleUserFollow(wasFollowing){
  if(!activeUser?.user)return;
  const button=document.getElementById('followUserButton'),status=document.getElementById('followUserStatus');
  button.disabled=true;
  try{
    const actor=Number(activeUser.user.id);
    await jfetch('/api/users/'+actor+'/following/'+PROFILE_USER_ID+'?viewer_id='+actor,{method:wasFollowing?'DELETE':'PUT'});
    await loadProfilePage(selectedIndividualId||null);
  }catch(e){status.textContent=e.message;button.disabled=false}
}
let connectionDirection='followers',connectionOffset=0,connectionLoading=false,connectionGeneration=0;
async function openUserConnections(direction){
  connectionDirection=direction;connectionOffset=0;connectionGeneration++;connectionLoading=false;
  const dialog=document.getElementById('userConnectionsDialog');
  document.getElementById('userConnectionsTitle').textContent=direction==='followers'?(globalThis.YGCI18n?.t("ui.followers_a145ab34",{},"Followers")??"Followers"):(globalThis.YGCI18n?.t("ui.following_344b4271",{},"Following")??"Following");
  document.getElementById('userConnectionsList').innerHTML='';
  document.getElementById('userConnectionsMore').hidden=true;
  YGCOverlays.open(dialog);
  await loadUserConnections();
}
async function loadUserConnections(){
  if(connectionLoading)return;
  connectionLoading=true;
  const generation=connectionGeneration,status=document.getElementById('userConnectionsStatus'),more=document.getElementById('userConnectionsMore');
  more.disabled=true;status.textContent=(globalThis.YGCI18n?.t("ui.loading_47d2a515",{},"Loading...")??"Loading...");
  try{
    const users=await jfetch('/api/users/'+PROFILE_USER_ID+'/connections/'+connectionDirection+'?limit=50&offset='+connectionOffset);
    if(generation!==connectionGeneration)return;
    const list=document.getElementById('userConnectionsList');
    list.insertAdjacentHTML('beforeend',users.map(u=>'<a style="display:block;padding:8px 0;border-bottom:1px solid var(--line);color:var(--text)" href="/users/'+Number(u.id)+'">'+esc(u.display_name)+' <span class="sub">'+esc(u.account_type)+'</span></a>').join(''));
    connectionOffset+=users.length;more.hidden=users.length<50;
    status.textContent=connectionOffset?'':(globalThis.YGCI18n?.t("ui.no_users_yet_44e4e2d9",{},"No users yet.")??"No users yet.");
  }catch(e){if(generation===connectionGeneration)status.textContent=e.message}
  finally{if(generation===connectionGeneration){connectionLoading=false;more.disabled=false}}
}

async function loadProfilePage(preferredIndividualId=null){
  const hero=document.getElementById('profileHero');
  if(!activeUser||!activeUser.user){
    applyTheme('sunburst_3ply');
    hero.innerHTML=("<div class=\"profile-name\">"+(globalThis.YGCI18n?.html("ui.members_only_857e2a29",{},"Members only")??"Members only")+"</div><div class=\"profile-meta\">"+(globalThis.YGCI18n?.html("ui.sign_in_to_view_member_profiles_2068c4f6",{},"Sign in to view member profiles.")??"Sign in to view member profiles.")+"</div><div class=\"profile-actions\"><button onclick=\"location.href='/user-view/edit'\">"+(globalThis.YGCI18n?.html("ui.sign_in_create_account_64d954f2",{},"Sign In / Create Account")??"Sign In / Create Account")+"</button></div>");
    for(const section of ['owned','former','favorites','chronicle'])document.getElementById('profile-'+section).hidden=true;
    document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.user_profile_is_available_to_members_c84fe73d",{},"User Profile is available to members.")??"User Profile is available to members.");
    return;
  }
  try{
    const [data,chronicle]=await Promise.all([
      jfetch('/api/users/'+PROFILE_USER_ID+'/profile?viewer_id='+Number(activeUser.user.id)),
      jfetch('/api/users/'+PROFILE_USER_ID+'/chronicle?viewer_id='+Number(activeUser.user.id))
    ]);
    const u=data.user, summary=data.summary||{};
    applyTheme(u.theme);
    profileGuitars=data.guitars||[];
    profileFavorites=data.favorites||[];
    const own=Number(activeUser.user.id)===Number(u.id);
    document.getElementById('newGuitarAction').hidden=!own;
    const locationText=[u.location_country,u.location_region].filter(Boolean).join(' / ');
    const profileMeta=[
      [(globalThis.YGCI18n?.t("ui.account_type_dce81c5b",{},"Account Type")??"Account Type"),u.account_type||'user'],
      [(globalThis.YGCI18n?.t("ui.member_since_9321bcc0",{},"Member since")??"Member since"),String(u.created_at||'').slice(0,10)],
      ...(locationText?[[(globalThis.YGCI18n?.t("ui.location_15b61974",{},"Location")??"Location"),locationText]]:[]),
      ...(u.date_of_birth?[[(globalThis.YGCI18n?.t("ui.date_of_birth_fdc739f5",{},"Date of Birth")??"Date of Birth"),u.date_of_birth]]:[])
    ].map(([label,value])=>'<div class="profile-meta-item"><span class="profile-meta-label">'+esc(label)+'</span><span class="profile-meta-value">'+esc(value)+'</span></div>').join('');
    const stats=[[(globalThis.YGCI18n?.t("ui.owned_17b760c4",{},"Owned")??"Owned"),summary.owned_count],[(globalThis.YGCI18n?.t("ui.formerly_owned_65b08593",{},"Formerly Owned")??"Formerly Owned"),summary.former_count],[(globalThis.YGCI18n?.t("ui.claims_1c85c122",{},"Claims")??"Claims"),summary.claim_count],[(globalThis.YGCI18n?.t("ui.followers_a145ab34",{},"Followers")??"Followers"),data.social.followers_count,'followers'],[(globalThis.YGCI18n?.t("ui.following_344b4271",{},"Following")??"Following"),data.social.following_count,'following']];
    hero.innerHTML='<div class="profile-hero">'+
      '<img class="profile-avatar" src="'+(u.avatar_visible?'/api/users/'+Number(u.id)+'/avatar?viewer_id='+Number(activeUser.user.id)+'&v='+encodeURIComponent(u.updated_at||''):'/assets/no-icon.svg')+'" alt="'+esc(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="profile-identity"><div class="profile-name">'+esc(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+(own?' ':'')+'</div>'+
      '<div class="profile-meta">'+profileMeta+'</div>'+
      '<div class="profile-bio'+(u.bio?'':' sub')+'">'+esc(u.bio||(globalThis.YGCI18n?.t("ui.bio_has_not_been_added_yet_228545e8",{},"Bio has not been added yet.")??"Bio has not been added yet."))+'</div>'+
      '<div class="profile-stats">'+stats.map(x=>x[2]?'<button type="button" class="profile-stat" onclick="openUserConnections(\''+x[2]+'\')"><strong>'+Number(x[1]||0)+'</strong> '+esc(x[0])+'</button>':'<span class="profile-stat"><strong>'+Number(x[1]||0)+'</strong> '+esc(x[0])+'</span>').join('')+'</div></div>'+
      '<div class="profile-actions">'+(own?("<button onclick=\"location.href='/user-view/edit'\">"+(globalThis.YGCI18n?.html("ui.user_settings_818ed0c8",{},"User Settings")??"User Settings")+"</button>"):'<button id="followUserButton" type="button" aria-pressed="'+Boolean(data.social.is_following)+'" onclick="toggleUserFollow('+Boolean(data.social.is_following)+')">'+(data.social.is_following?(globalThis.YGCI18n?.t("ui.following_344b4271",{},"Following")??"Following"):(globalThis.YGCI18n?.t("ui.follow_641d1ef6",{},"Follow")??"Follow"))+'</button><button type="button" onclick="openDirectMessages('+Number(u.id)+(")\">"+(globalThis.YGCI18n?.html("ui.message_2f77668a",{},"Message")??"Message")+"</button>"))+'<span id="followUserStatus" class="sub" role="status"></span></div></div>';
    document.title=(u.display_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))+' — Your Guitar Chronicle';
    renderProfileGuitars('owned');
    renderProfileGuitars('former');
    renderProfileGuitars('favorites');
    renderUserChronicle(chronicle);
    const requested=Number(new URLSearchParams(location.search).get('individual_id')||0);
    const signature=profileGuitars.find(g=>g.ownership_status==='current_owner'&&Number(g.individual_id)===Number(u.signature_individual_id));
    const selected=[...profileGuitars,...profileFavorites].find(g=>Number(g.individual_id)===requested)||signature||profileGuitars[0]||profileFavorites[0];
    if(preferredIndividualId!==null)await showIndividual(Number(preferredIndividualId));
    else if(selected)await showIndividual(Number(selected.individual_id));
  }catch(e){
    applyTheme('dark_default');
    hero.innerHTML=("<div class=\"profile-placeholder\">"+(globalThis.YGCI18n?.html("ui.user_profile_could_not_be_loaded_4041cfc2",{},"User Profile could not be loaded.")??"User Profile could not be loaded.")+" ")+esc(e.message)+'</div>';
  }
}

window.YGCPageReady=(async()=>{
  await loadActiveUser();
  if(!activeUser&&new URLSearchParams(location.search).get('register')==='1'){history.replaceState(null,'','/user-view');openAccountRegistration()}
  if(PROFILE_USER_ID){
    setupProfileShell();
    await loadProfilePage();
    return;
  }
  await loadNewDiscoveries();
  await loadIndividuals();
  await Promise.all([loadTopPageCharts(),loadWorldMap()]);

  const requested=Number(new URLSearchParams(window.location.search).get('individual_id')||0);
  const requestedExists=requested&&individuals.some(x=>Number(x.id)===requested);
  if(requestedExists){
    selectedIndividualId=requested;
  }else if(newDiscoveries.length){
    const candidates=newDiscoveries
      .map(item=>Number(item.id))
      .filter(id=>individuals.some(x=>Number(x.id)===id));
    if(candidates.length){
      selectedIndividualId=candidates[Math.floor(Math.random()*candidates.length)];
    }
  }else if(individuals.length){
    selectedIndividualId=Number(individuals[0].id);
  }else{
    selectedIndividualId=null;
  }

  renderIndividuals();
  if(selectedIndividualId!==null){
    await showIndividual(selectedIndividualId);
  }else{
    document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.no_individual_to_display_bed702a6",{},"No Individual to display.")??"No Individual to display.");
  }
})()

if(typeof setInterval==='function')setInterval(()=>{if(!document.hidden&&activeUser?.user)loadOwnershipAttention()},30000);
