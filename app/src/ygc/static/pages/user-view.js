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
  if(!r.ok)throw new Error(Array.isArray(d.detail)?d.detail.map(e=>e.msg).join(' / '):(d.detail||r.statusText));
  return d;
}
function favoriteButton(id){
  if(!activeUser||!activeUser.user)return '';
  const selected=favoriteIds.has(Number(id));
  return '<button type="button" class="favorite-button'+(selected?' is-favorite':'')+'" aria-label="'+(selected?'Remove from favorites':'Add to favorites')+'" aria-pressed="'+selected+'" title="'+(selected?'Remove from favorites':'Add to favorites')+'" onclick="toggleFavorite(event,'+Number(id)+')">'+(selected?'♥':'♡')+'</button>';
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
      button.setAttribute('aria-label',selected?'Remove from favorites':'Add to favorites');
      button.title=button.getAttribute('aria-label');
    });
  }catch(e){alert('Favorite could not be updated.\n'+e.message)}
}
function renderAccountHub(){
  const hub=document.getElementById('accountHub');
  if(!hub)return;
  if(!activeUser||!activeUser.user){
    hub.innerHTML=
      '<div class="account-hub-user">'+
        '<div class="account-hub-guest-mark">YGC</div>'+
        '<div class="account-hub-user-copy">'+
          '<div class="account-hub-guest-title">Explore guitar histories. Add yours when you are ready.</div>'+
          '<div class="account-hub-guest-copy">Guests can browse the Product List and Chronicle. Create an account to contribute to the history of a guitar that matters to you.</div>'+
        '</div>'+
      '</div>'+
      '<div></div>'+
      '<div class="account-hub-actions">'+
        '<button class="account-hub-action" type="button" onclick="window.location.href=\'/user-view/edit\'">Sign In</button>'+
        '<button data-ui-action="primary" class="account-hub-action primary" type="button" onclick="window.location.href=\'/user-view/edit\'">Create Account</button>'+
      '</div>';
    return;
  }
  const u=activeUser.user;
  const summary=activeUser.summary||{};
  const guitars=activeUser.guitars||[];
  const owned=summary.owned_count??guitars.filter(g=>g.ownership_status==='current_owner').length;
  const former=summary.former_count??guitars.filter(g=>g.ownership_status==='former_owner').length;
  const claims=summary.claim_count??0;
  const location=[u.location_country,u.location_region].filter(Boolean).join(' / ')||'Location not set';
  hub.innerHTML=
    '<a class="account-hub-user account-hub-user-link" href="/users/'+Number(u.id)+'" aria-label="View '+esc(u.display_name||'User')+' profile">'+
      '<img class="account-hub-avatar" src="/api/users/'+u.id+'/avatar?viewer_id='+Number(activeUser.user.id)+'&v='+encodeURIComponent(u.updated_at||'')+'" alt="'+esc(u.display_name||'User')+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="account-hub-user-copy">'+
        '<div class="account-hub-name-row"><span class="account-hub-name">'+esc(u.display_name||'User')+'</span><span class="account-hub-you">You</span></div>'+
        '<div class="account-hub-location">'+esc(location)+'</div>'+
      '</div>'+
    '</a>'+
    '<div class="account-hub-summary">'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+owned+'</span><span class="account-hub-stat-label">Owned</span></div>'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+former+'</span><span class="account-hub-stat-label">Formerly Owned</span></div>'+
      '<div class="account-hub-stat"><span class="account-hub-stat-value">'+claims+'</span><span class="account-hub-stat-label">Claims</span></div>'+
    '</div>'+
    '<div class="account-hub-actions">'+
      '<button id="ownershipRequestAttention" class="account-hub-action" type="button" onclick="showAcquireApplications()" '+(ownershipAttention.attention_count?'':'hidden')+'>Check Requests</button>'+
      '<button class="account-hub-action" type="button" onclick="toggleNotifications()">Notifications <span class="account-hub-count" id="notificationCount">'+Number(notificationData.unread_count||0)+'</span></button>'+
      '<button class="account-hub-action" type="button" onclick="openDirectMessages()">Messages <span class="account-hub-count" id="directMessageCount">'+Number(dmInbox.unread_count||0)+'</span></button>'+
    '</div>';
}

function renderNotificationPanel(){
  const list=document.getElementById('notificationList');
  if(!list)return;
  const items=notificationData.notifications||[];
  list.innerHTML=items.length
    ? items.map(n=>
        '<button type="button" class="notification-item'+(Number(n.is_read)?'':' unread')+'" onclick="openNotification('+n.id+','+(n.individual_id===null?'null':Number(n.individual_id))+')">'+
          '<div class="notification-item-title">'+esc(n.title||'Notification')+'</div>'+
          '<div class="notification-item-body">'+esc(n.body||'')+'</div>'+
          '<div class="notification-item-time">'+esc(displayInputDate(n.created_at))+'</div>'+
        '</button>'
      ).join('')
    : '<div class="notification-empty">No notifications.</div>';
  const count=document.getElementById('notificationCount');
  if(count)count.textContent=String(Number(notificationData.unread_count||0));
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
  }catch(e){
    alert('Could not mark the notification as read.\n'+e.message);
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
    section.innerHTML='<h2 id="unansweredRequestsTitle" data-count-items="#unansweredRequests > .unanswered-request">Unanswered Requests</h2>'+rows.map(r=>
      '<div class="unanswered-request"><p>'+YGCProductDetail.userLink(r.sender_id,r.sender_name,esc)+
      (r.kind==='transfer'?' has offered to transfer ':' is claiming ownership of ')+
      '<a href="/users/'+Number(userId)+'?individual_id='+Number(r.individual_id)+'">'+esc(r.guitar||('Guitar #'+r.individual_id))+'</a>'+(r.kind==='transfer'?' to you.':'.')+
      '</p><div><button data-ui-action="primary" onclick="answerOwnershipRequest('+Number(r.claim_id)+',&quot;'+r.kind+'&quot;,true,'+Number(r.individual_id)+')">Accept</button> '+
      '<button class="secondary" onclick="answerOwnershipRequest('+Number(r.claim_id)+',&quot;'+r.kind+'&quot;,false,'+Number(r.individual_id)+')">Decline</button></div></div>').join('');
  }catch(error){if(sequence!==unansweredSequence||activeUser?.user?.id!==userId)return;section.hidden=false;section.textContent='Unable to load unanswered requests. Please refresh.'}
}
async function answerOwnershipRequest(claimId,kind,accept,individualId){
  if(unansweredBusy||!activeUser?.user)return;
  const userId=activeUser.user.id;
  if(!await confirmOwnershipAction(accept?'Accept':'Decline',accept?'Accept this ownership request?':'Decline this ownership request?'))return;
  if(activeUser?.user?.id!==userId)return;
  unansweredBusy=true;
  try{
    const url=kind==='transfer'?'/api/transfers/'+claimId+'/resolve?viewer_id='+Number(userId):'/api/claims/'+claimId+'/response';
    const body=kind==='transfer'?{action:accept?'accept':'decline'}:{responder_user_id:userId,stance:accept?'positive':'negative'};
    await jfetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    await refreshClaimViews(individualId);
  }catch(error){alert(error.message)}finally{unansweredBusy=false;await loadUnansweredRequests()}
}
if(typeof setInterval==='function')setInterval(()=>{if(!document.hidden&&!unansweredBusy)loadUnansweredRequests()},30000);

async function loadActiveUser(){
  const id=sessionStorage.getItem(ACTIVE_USER_KEY);
  if(!id){
    activeUser=null;
    await loadUnansweredRequests();
    if(!PROFILE_USER_ID)applyTheme('dark_default');
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
    activeUser=null;
    await loadUnansweredRequests();
    if(!PROFILE_USER_ID)applyTheme('dark_default');
    favoriteIds=new Set();
    sessionStorage.removeItem(ACTIVE_USER_KEY);
  }
  await loadNotifications();
  await loadDirectMessageInbox();
  await loadOwnershipAttention();
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
  if(item.activity_type!=='claim')return 'has been newly added to the list!';
  if(type==='listing')return 'has been newly added to the list!';
  if(type==='specification')return 'has new specifications on record!';
  if(type==='incident')return 'has a new incident report!';
  if(type==='event')return 'has a new event in its history!';
  if(type==='media')return 'has new media added!';
  if(type==='ownership')return 'has a new ownership update!';
  if(type==='identity_correction')return 'has received an identity correction!';
  return 'has secured a new claim!';
}
function discoveryProductName(item){
  const base=[item.manufacturer,item.model].filter(Boolean).join(' ').trim()||('Product #'+item.id);
  const year=item.year?' ('+item.year+')':'';
  const finish=item.finish?' '+item.finish:'';
  return base+year+finish;
}
function discoveryActorHtml(item){
  if(item.activity_type!=='following'||!item.actor_user_id)return '';
  return '<a class="discovery-actor" href="/users/'+Number(item.actor_user_id)+'" onclick="event.stopPropagation()">'+esc(item.actor_name)+'</a> <span class="discovery-following">Following</span>';
}
function followingDiscoveryMessage(item){
  if(item.action_kind==='vote')return 'gave a '+String(item.action_value||'')+' vote to a Claim on';
  const kind=item.claim_type==='ownership'?(item.ownership_kind||'Acquire'):
    item.claim_type==='specification'&&item.specification_kind==='repair'?'Repair':item.claim_type;
  const label=String(kind||'Claim').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  return 'added '+(/^[AEIOU]/.test(label)?'an ':'a ')+label+' Claim to';
}
function renderNewDiscoveries(){
  const root=document.getElementById('newDiscoveryList');
  if(!root)return;
  if(!newDiscoveries.length){
    root.innerHTML='<div class="sub" style="padding:10px">No recent activity.</div>';
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
}

function currentSnapshotOwnerHtml(i){
  if(!i)return '—';
  const name=String(i.current_owner_name||'').trim();
  if(!name)return '—';
  const type=String(i.current_owner_type||'').trim();
  const listingUrl=String(i.current_owner_source_url||'').trim();
  const label=type==='shop'?name+' (Shop)':name;
  if(i.current_owner_user_id&&activeUser&&activeUser.user){
    const you=Number(i.current_owner_user_id)===Number(activeUser.user.id)?'<span class="account-hub-you">You</span>':'';
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
    ? '<div class="sub">Signed in as '+esc(activeUser.user.display_name||('User #'+activeUser.user.id))+'</div>'
    : '';
  if(activeUser&&activeUser.user&&individual.current_owner_user_id!==null
     && Number(individual.current_owner_user_id)===Number(activeUser.user.id)){
    return actorNote;
  }
  if(individual.acquire_application)return actorNote+'<button onclick="viewAcquireApplication(\''+esc(individual.acquire_application.revision)+'\')">'+esc(acquireStatusLabel(individual.acquire_application))+'</button>';
  const action=activeUser&&activeUser.user?'openOwnerClaim('+individualId+')':'requireAccount()';
  return actorNote+'<button type="button" class="owner-claim-card" onclick="'+action+'">If you are the rightful owner of this, you can claim it by providing some evidence!</button>';
}

function productGalleryHtml(images,model){return YGCProductGallery.render(images,model,esc)}
function stepProductGallery(delta){YGCProductGallery.step(delta)}
function openProductAlbum(){YGCProductGallery.open()}
function specificationFieldLabel(value){
  const labels={
    nut:'Nut',
    frets:'Frets',
    pickguard:'Pickguard',
    potentiometers:'Potentiometers',
    wiring:'Wiring',
    neck:'Neck',
    pickups:'Pickups',
    bridge:'Bridge',
    tuners:'Tuners',
    body:'Body',
    fingerboard:'Fingerboard',
    finish:'Finish',
    weight:'Weight'
  };
  const key=String(value||'').trim();
  return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase());
}
function identityFieldLabel(value){
  const labels={
    manufacturer:'Maker',
    model:'Model',
    year:'Year',
    serial_number:'Serial'
  };
  return labels[String(value||'')]||String(value||'').replace(/_/g,' ');
}
function claimTypeLabel(value){
  return String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ');
}
function incidentClaimLabel(c){return c.value_text==='lost'?'Incident Lost':claimTypeLabel(c.value_text||'incident')}
function displayEventDate(value){
  if(!value)return 'Date unknown';
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
  if(!value)return 'Input date unknown';
  const d=new Date(String(value));
  return Number.isNaN(d.getTime())?String(value):d.toLocaleString('en-US');
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
      '<option value="positive"'+(current==='positive'?' selected':'')+'>Positive</option>'+
      '<option value="negative"'+(current==='negative'?' selected':'')+'>Negative</option>'+
      '<option value="unverified"'+(current==='unverified'?' selected':'')+'>Unverified</option>'+
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
    ? (c.specification_kind==='repair'?'Repair':'Specification')
    : (c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?incidentClaimLabel(c):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):claimTypeLabel(c.claim_type))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(['automation','merged_listing'].includes(c.ownership_source)?(c.value_text||'Unknown'):(c.author_name||'User')).trim()||'User';
    const ownerHtml=['automation','merged_listing'].includes(c.ownership_source)?esc(owner):YGCProductDetail.userLink(c.author_user_id,owner,esc);
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||'Unknown')
      : 'Unknown';
    if(kind==='lost'){
      body='<div><strong>Reverb listing unavailable. Current owner and location are unknown.</strong></div>';
    }else if(kind==='release'){
      body=c.ownership_source==='automation'
        ? '<div><strong>Reverb listing unavailable. Current owner and location are unknown.</strong></div>'
        : '<div><strong>'+ownerHtml+' released this product.</strong></div>';
    }else if(kind==='transfer'&&c.transfer){
      const t=c.transfer;
      body='<div><strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+'</strong></div><div class="claim-memo">Transfer: '+esc(t.state)+'</div>';
      if(t.accepted_at)body+='<div class="claim-memo">Info: Transfer accepted on '+esc(displayInputDate(t.accepted_at))+'</div>';
      if(t.state==='pending'&&activeUser?.user&&[t.from_user_id,t.to_user_id].includes(Number(activeUser.user.id)))body+='<button type="button" onclick="openTransferReview('+Number(c.id)+')">Review Transfer</button>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+ownerHtml+'.</strong></div>';
    }else if(kind==='inherit'){
      body='<div><strong>'+esc(party)+' inherited this product from '+ownerHtml+'.</strong></div>';
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
    if(c.body)body+='<div class="claim-memo">Reason: '+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||'Listing observed';
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)body+='<div class="claim-memo">Owner: '+YGCProductDetail.userLink(c.observed_owner_user_id,listingOwner,esc)+'</div>';
    if(seller)details.push('Seller: '+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push('Location: '+location);
    const specs=[
      c.observed_model&&('Model: '+c.observed_model),
      c.observed_finish&&('Finish: '+c.observed_finish),
      c.observed_year&&('Year: '+c.observed_year),
      c.observed_serial_number&&('Serial: '+c.observed_serial_number)
    ].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.source_url&&(c.claim_type==='listing'||c.source_site==='reverb')){
    body+='<div class="claim-info"><strong>Info</strong>: <a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">'+(c.source_site==='reverb'?'View Reverb listing':'View listing')+'</a></div>';
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
    ? (c.specification_kind==='repair'?'Repair':'Specification')
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
  if(el)el.innerHTML=claims.length?claims.map(claimCard).join(''):'<div class="sub">No Claims yet.</div>';
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
  try{
    await jfetch('/api/claims/'+claimId+'/response',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        responder_user_id:Number(activeUser.user.id),
        stance
      })
    });
    closeClaimPopup();
    await refreshClaimViews(selectedIndividualId);
  }catch(e){
    alert('Owner Verification could not be updated.\n'+e.message);
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
    alert('Vote could not be updated.\n'+e.message);
  }
}

let acquireRevision=null;
let acquireBusy=false;
let acquireDisplayState=null;
let acquireForm=null;
let ownershipConfirmResolve=null;
function confirmOwnershipAction(title,message){
  if(ownershipConfirmResolve)return Promise.resolve(false);
  document.getElementById('ownershipConfirmTitle').textContent=title;
  document.getElementById('ownershipConfirmMessage').textContent=message;
  const submit=document.getElementById('ownershipConfirmSubmit');
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
  const saved=row&&!row.unsaved;
  const terminal=row&&['accepted','rejected','cancelled','closed','expired'].includes(row.status);
  let buttons='';
  if(!row)buttons+='<button id="guitarSubmit" onclick="submitNewGuitar()">Generate Challenge</button>';
  if(!row||row.status==='draft')buttons+='<button data-ui-action="primary" id="acquireSubmit" onclick="submitAcquireApplication()" '+(!row?'disabled':'')+'>Submit</button>';
  buttons+='<button onclick="requestRefresh()">Reflesh</button>';
  if(row?.status==='error')buttons+='<button onclick="actAcquireApplication(\'retry\')">Retry Review</button>';
  buttons+='<button data-ui-action="primary" onclick="keepAcquireRequest()">Keep Request</button><button data-ui-action="close" class="secondary" onclick="cancelRequestWindow()">Cancel</button>';
  if(saved&&!terminal)buttons+='<button data-ui-action="danger" class="secondary" onclick="actAcquireApplication(\'cancel\')">Cansel Request</button>';
  document.getElementById('acquireReviewActions').innerHTML=buttons;
}
async function cancelRequestWindow(){
  if(acquireBusy)return;
  closeAcquireReview();
}
async function requestRefresh(){
  if(acquireBusy)return;
  const saved=acquireForm&&!acquireForm.unsaved;
  const message=saved?'Reload the saved request? Unsaved input and selected photos will be discarded.':'Refresh this form? Entered text and the current Challenge will be kept. Selected photos will be cleared. The request will not be saved.';
  if(!await confirmOwnershipAction('Reflesh',message))return;
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
  if(await confirmOwnershipAction('View Guitar','Close this window and view the existing guitar?')){closeAcquireReview();await showIndividual(id,true)}
}
async function requestHistoryItem(revision){
  if(await confirmOwnershipAction('Open Request','Open this request and view its current status?'))await viewAcquireApplication(revision);
}
async function keepAcquireRequest(){
  if(acquireBusy)return;
  if(!await confirmOwnershipAction('Keep Request','Save the request details and close this window? Selected photos will not be saved.'))return;
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
  return '<div class="modal-grid">'+[['manufacturer','guitarMaker','Maker *',120],['model','guitarModel','Model',160],['year','guitarYear','Year',40],['finish','guitarFinish','Finish',160],['serial_number','guitarSerial','Serial *',160]].map(([key,id,label,max])=>'<label>'+label+'<input id="'+id+'" maxlength="'+max+'" value="'+esc(payload[key]||'')+'" '+(readOnly?'readonly':'')+'></label>').join('')+'</div>';
}
function ownershipEvidenceFields({listing=false,issued=true,date='',body=''}={}){
  return '<div class="modal-grid"><label>'+ (listing?'Listing date':'Acquisition date')+' *<input id="acquireDate" type="date" required value="'+esc(date)+'" '+(listing&&issued?'readonly':'')+'></label><label class="full">Description<textarea id="acquireBody" maxlength="4000" '+(listing&&issued?'readonly':'')+'>'+esc(body)+'</textarea></label>'+
    '<label class="full">Close-up of serial and challenge *<input id="acquireCloseup" type="file" accept="image/jpeg,image/png,image/webp" '+(!issued?'disabled':'')+'></label><label class="full">Overview of guitar and challenge *<input id="acquireOverview" type="file" accept="image/jpeg,image/png,image/webp" '+(!issued?'disabled':'')+'></label></div>'+
    (listing?'<p class="sub">After approval, the overview photo becomes the public representative image. The close-up and report are accessible only to the applicant, administrators and current owner.</p>':'');
}
function ownershipChallengeBox(row){
  if(!row)return '<div class="challenge-box">Challenge: Not generated<p>Enter the guitar details and date, then select Generate Challenge. Write the code on paper before taking and selecting both photos.</p></div>';
  return '<div class="challenge-box">Serial: '+esc(row.serial)+'<br>Challenge: <strong>'+esc(row.challenge)+'</strong><br>Submit by: '+esc(new Date(row.expires_at*1000).toLocaleString())+'</div><p>Include the handwritten challenge in both photos. Images will be sent to GPT for review. Submitted requests do not expire while awaiting review.</p>';
}
function acquireQuery(){return '?viewer_id='+encodeURIComponent(activeUser.user.id)}
const acquireLabels={draft:'Awaiting photos',pending:'Awaiting review',processing:'Under review',error:'Review error — retry available',rejected:'Evidence rejected',accepted:'Acquire added',cancelled:'Cancelled',closed:'Closed',expired:'Submission expired'};
function acquireStatusLabel(row){if(row.request_kind==='listing')return row.status==='accepted'?'Listing registered':(acquireLabels[row.status]||row.status);return row.status==='accepted'&&row.verification_status==='unverified'?'Awaiting owner approval':(acquireLabels[row.status]||row.status)}
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
  if(!userId){ownershipAttention={attention_count:0};return}
  try{
    const data=await jfetch('/api/acquire-applications/attention?viewer_id='+encodeURIComponent(userId));
    if(sequence!==ownershipAttentionSequence||activeUser?.user?.id!==userId)return;
    ownershipAttention=data;
    const button=document.getElementById('ownershipRequestAttention');
    if(button)button.hidden=!data.attention_count;
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
  document.getElementById('acquireReviewTitle').textContent='Ownership Requests';
  document.getElementById('acquireReviewActions').innerHTML='<button data-ui-action="close" onclick="cancelRequestWindow()">Cancel</button>';
  try{
    const rows=await jfetch('/api/acquire-applications'+acquireQuery());
    document.getElementById('acquireReviewContent').innerHTML=(rows.length?rows.map(r=>'<p><button onclick="requestHistoryItem(\''+esc(r.revision)+'\')">'+esc(r.request_kind==='listing'?'Listing '+(r.product_name||''):'Individual #'+r.original_individual_id)+' — '+esc(acquireStatusLabel(r))+(r.unread_result?' — New result':'')+'</button><br><small>'+esc(r.created_at)+'</small></p>').join(''):'No requests.');
    YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});
  }catch(e){alert(e.message)}
}
async function viewAcquireApplication(revision){
  try{const row=await jfetch('/api/acquire-applications/'+encodeURIComponent(revision)+acquireQuery());acquireRevision=row.revision;renderAcquireApplication(row);YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});await acknowledgeOwnershipResult(row);if(['accepted','closed'].includes(row.status)&&selectedIndividualId)await refreshClaimViews(selectedIndividualId)}catch(e){alert(e.message)}
}
function renderAcquireApplication(row){
  acquireDisplayState=row.status;acquireForm=row;
  setRequestTitle(row.request_kind==='listing'?'Listing Request':'Acquire Request',acquireStatusLabel(row));
  const terminal=['accepted','rejected','cancelled','closed','expired'].includes(row.status);
  const listing=row.request_kind==='listing';
  let html='<p>'+esc(listing?row.product_name:'Individual #'+row.original_individual_id)+' / '+esc(row.unsaved?'Not saved':row.revision)+'</p>';
  if(row.existing_individual_ids?.length)html+='<p>This maker and serial are already registered. View the existing guitar and use Acquire to request ownership.</p>'+row.existing_individual_ids.map(id=>'<button onclick="requestExistingGuitar('+Number(id)+')">Existing guitar #'+Number(id)+' — View</button>').join('');
  if(listing&&row.status==='accepted'&&row.individual_id)html+='<p><a href="/users/'+Number(activeUser.user.id)+'?individual_id='+Number(row.individual_id)+'">View Registered Guitar</a></p>';
  if(row.error)html+='<p>'+esc(row.error)+'</p>';
  if(row.status==='draft'){
    if(listing)html+=listingMetadataFields(row.listing_payload,true);
    html+=ownershipChallengeBox(row)+ownershipEvidenceFields({listing,date:listing?row.listing_payload.occurred_at:(row.acquisition_date||''),body:listing?row.listing_payload.body:(row.body||'')});
  }else if(!terminal){html+='<p>'+ (listing?'The guitar and Listing will be registered only after approval.':'The Acquire Claim will be added only after approval.')+'</p>'}
  if(row.admin_review)html+='<p>Administrator review: '+(row.admin_review.accepted?'Approved':'Rejected')+' — '+esc(row.admin_review.reason)+'</p>';
  const reasons=row.result?.adjudication?.reasons||[];
  if(row.status==='rejected'&&reasons.length)html+='<section class="request-info"><h3>Info</h3><ul>'+reasons.map(reason=>'<li>'+esc(reason)+'</li>').join('')+'</ul></section>';
  document.getElementById('acquireReviewContent').innerHTML=html;requestFooter(row);
}
async function submitAcquireApplication(){
  if(acquireBusy||!acquireRevision)return;
  const form=new FormData();const acquired=document.getElementById('acquireDate').value;
  const closeup=document.getElementById('acquireCloseup').files[0],overview=document.getElementById('acquireOverview').files[0];
  if(!acquired||!closeup||!overview){alert('Enter the date and select both photos.');return}
  if(!await confirmOwnershipAction('Submit','Save this request and submit both photos for review?'))return;
  form.append('acquisition_date',acquired);form.append('body',document.getElementById('acquireBody').value);form.append('closeup',closeup);form.append('overview',overview);
  let url='/api/acquire-applications/'+acquireRevision+'/submit';
  if(acquireForm?.unsaved){url='/api/ownership-drafts/submit';form.append('draft_token',acquireForm.draft_token)}
  acquireBusy=true;document.getElementById('acquireSubmit').disabled=true;
  try{const row=await jfetch(url+acquireQuery(),{method:'POST',body:form});renderAcquireApplication(row);await loadOwnershipAttention();if(selectedIndividualId)await showIndividual(selectedIndividualId)}catch(e){alert(e.message)}finally{acquireBusy=false;const button=document.getElementById('acquireSubmit');if(button)button.disabled=false}
}
async function actAcquireApplication(action){
  if(acquireBusy||!acquireRevision)return;
  if(!await confirmOwnershipAction(action==='cancel'?'Cansel Request':'Retry Review',action==='cancel'?'Withdraw this saved request? Any in-progress review will be stopped.':'Queue this request for another review?'))return;
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
    if(Number(selectedIndividualId)!==Number(id))document.getElementById('detail').textContent='Loading...';
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
    out+=productGalleryHtml(galleryImages,i.model||'Guitar');
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" role="button" tabindex="0" aria-label="Open photo album" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"><span class="detail-source">Representative Image</span>';
  }else if(imageListing){
    const imageUrl=String(imageListing.source_url||'');
    const image='<img class="detail-image" src="'+esc(imageListing.image_url)+'" alt="'+esc(imageListing.listing_title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(imageUrl)out+='<a class="detail-image-link" href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(imageUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(imageListing.source_site||'Source'))+'</a></span>';
    else out+=image+'<span class="detail-source">Listing Claim</span>';
  }else{
    out+='<img class="detail-image" src="/assets/no-picture.svg" alt="No picture"><span class="detail-source">No Picture</span>';
  }
  const chronicleAction='<div class="chronicle-toolbar"><div class="claim-menu-wrap"><button class="add-claim-action" onclick="toggleAddClaimMenu(event,'+i.id+')">Let\'s add your Claim !!</button><div class="claim-menu" id="addClaimMenu"><button onclick="chooseClaimType(\'specification_repair\')">Specification/Repair</button><button onclick="chooseClaimType(\'incident\')">Incident</button><button onclick="chooseClaimType(\'event\')">Event</button><button onclick="chooseClaimType(\'media\')">Media</button>'+(activeUserOwns(i.id)?'<button onclick="chooseClaimType(\'ownership\')">Ownership</button>':'<button onclick="chooseClaimType(\'former_owner\')">Former Owner</button>')+'</div></div></div>';
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
  ['nut','Nut'],['frets','Frets'],['pickguard','Pickguard'],
  ['potentiometers','Potentiometers'],['wiring','Wiring'],['neck','Neck'],
  ['pickups','Pickups'],['bridge','Bridge'],['tuners','Tuners'],
  ['body','Body'],['fingerboard','Fingerboard'],['finish','Finish'],['weight','Weight']
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
function chooseClaimType(type){
  const menu=document.getElementById('addClaimMenu');
  if(menu)menu.classList.remove('open');
  if(type==='specification_repair')openSpecificationClaim(selectedIndividualId);
  else if(type==='incident')openIncidentClaim(selectedIndividualId);
  else if(type==='event')openEventClaim(selectedIndividualId);
  else if(type==='media')openMediaClaim(selectedIndividualId);
  else if(type==='former_owner')openFormerOwnerClaim(selectedIndividualId);
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
  document.getElementById('mediaClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
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
  if(!images.length){alert('Select at least one image.');return;}
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){alert('Choose a JPEG, PNG, WebP, or GIF image.');return;}
    if(image.size>12*1024*1024){alert('Each image must be 12 MB or less.');return;}
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
    if(!response.ok)throw new Error(data.detail||response.statusText);
    closeMediaClaim();
    await refreshClaimViews(selectedIndividualId);
  }catch(e){alert('Media Claim could not be added.\n'+e.message);}
  finally{button.disabled=false;}
}

function openEventClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('eventClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
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
  if(!detail){alert('Enter a detail.');return;}
  const images=Array.from(document.getElementById('eventClaimImages').files||[]);
  if(images.length>10){alert('Choose up to 10 images.');return;}
  for(const image of images){
    if(!['image/jpeg','image/png','image/webp','image/gif'].includes(image.type)){alert('Choose a JPEG, PNG, WebP, or GIF image.');return;}
    if(image.size>12*1024*1024){alert('Each image must be 12 MB or less.');return;}
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
  }catch(e){alert('Event Claim could not be added.\n'+e.message);}
  finally{button.disabled=false;}
}

function openIncidentClaim(individualId){
  if(!activeUser||!activeUser.user)return;
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('incidentClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
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
  if(!detail){alert('Enter a detail.');return;}
  const button=document.getElementById('incidentClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/incident-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),incident_kind:document.getElementById('incidentClaimKind').value,occurred_at:document.getElementById('incidentClaimDate').value||null,detail})});
    closeIncidentClaim();await refreshClaimViews(selectedIndividualId);
  }catch(e){alert('Incident Claim could not be added.\n'+e.message);}
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
  document.getElementById('specClaimGuitar').textContent=guitar?guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:''):'Individual #'+individualId;
  editingSpecificationClaimId=null;specificationItems=[];setSpecificationKind('specification');
  document.getElementById('specClaimTitle').textContent='Specification/Repair Claim';
  document.getElementById('specClaimSubmit').textContent='Add Claim';
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
  menu.innerHTML=SPEC_FIELDS.filter(([key])=>!used.has(key)).map(([key,label])=>'<button type="button" onclick="addSpecificationItem(\''+key+'\')">'+esc(label)+'</button>').join('')+'<button type="button" onclick="addCustomSpecificationItem()">Custom…</button>';
}
function addSpecificationItem(fieldName,label){
  if(specificationItems.some(x=>x.field_name===fieldName))return;
  const found=SPEC_FIELDS.find(([key])=>key===fieldName);
  specificationItems.push({field_name:fieldName,label:label||(found?found[1]:specificationFieldLabel(fieldName)),value_text:''});
  document.getElementById('specItemMenu').classList.remove('open');renderSpecificationItems();
}
function addCustomSpecificationItem(){
  const raw=prompt('Enter a Specification field name.');if(!raw)return;
  const fieldName=raw.trim().toLowerCase().replace(/\s+/g,'_');if(!fieldName)return;
  if(specificationItems.some(x=>x.field_name===fieldName)){alert('That field has already been added.');return;}
  addSpecificationItem(fieldName,raw.trim());
}
function removeSpecificationItem(index){specificationItems.splice(index,1);renderSpecificationItems();renderSpecItemMenu();}
function updateSpecificationItem(index,value){if(specificationItems[index])specificationItems[index].value_text=value;}
function renderSpecificationItems(){
  const el=document.getElementById('specClaimItems');if(!el)return;
  el.innerHTML=specificationItems.length?specificationItems.map((item,index)=>'<div class="spec-item-row"><div class="spec-item-label">'+esc(item.label)+'</div><input maxlength="500" value="'+esc(item.value_text)+'" oninput="updateSpecificationItem('+index+',this.value)" placeholder="Value"><button data-ui-action="close" type="button" class="spec-item-remove" onclick="removeSpecificationItem('+index+')">×</button></div>').join(''):'<div class="sub">Use + to add a field.</div>';
}
async function submitSpecificationClaim(){
  const items=specificationItems.map(item=>({field_name:item.field_name,value_text:String(item.value_text||'').trim()})).filter(item=>item.value_text);
  if(!items.length){alert('Add at least one field and value.');return;}
  if(items.length!==specificationItems.length){alert('Enter a value for every added field.');return;}
  const button=document.getElementById('specClaimSubmit');button.disabled=true;
  try{
    await jfetch('/api/individuals/'+selectedIndividualId+'/specification-claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:Number(activeUser.user.id),specification_kind:specificationKind,items,occurred_at:document.getElementById('specClaimDate').value||null,body:document.getElementById('specClaimBody').value.trim()||null})});
    closeSpecificationClaim();await refreshClaimViews(selectedIndividualId);
  }catch(e){alert('Specification/Repair Claim could not be added.\n'+e.message);}
  finally{button.disabled=false;}
}

document.addEventListener('click',()=>{
  const claimMenu=document.getElementById('addClaimMenu');if(claimMenu)claimMenu.classList.remove('open');
  const specMenu=document.getElementById('specItemMenu');if(specMenu)specMenu.classList.remove('open');
});

function openFormerOwnerClaim(individualId){
  if(!activeUser||!activeUser.user){
    alert('Select a user first.');
    return;
  }
  if(activeUserOwns(individualId)){
    alert('The current owner cannot add a Former Owner Claim.');
    return;
  }
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('formerOwnerClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
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
    alert('Acquisition Date and Release Date are required.');
    return;
  }
  if(acquisitionDate>=releaseDate){
    alert('Acquisition Date must be earlier than Release Date.');
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
    alert('Former Owner Claim could not be added.\n'+e.message);
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
    kind.innerHTML='<option value="acquire">Acquire</option>';
    kind.value='acquire';
    kind.style.display='none';
    fixed.style.display='block';
    fixed.innerHTML='<strong>Acquire</strong>';
    previousRow.style.display='';
  }else{
    kind.innerHTML='<option value="transfer">Transfer</option><option value="release">Release</option><option value="inherit">Inherit</option>';
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
    alert('Only the current owner can add this Ownership Claim.');
    return;
  }
  pendingOwnershipClaimIndividualId=Number(individualId);
  selectedIndividualId=Number(individualId);
  const guitar=individuals.find(x=>Number(x.id)===Number(individualId));
  document.getElementById('ownershipClaimGuitar').textContent=guitar
    ? guitar.manufacturer+' '+(guitar.model||'')+(guitar.serial_number?' / '+guitar.serial_number:'')
    : 'Individual #'+individualId;
  transferSelectedUser=null;transferSearchGeneration++;document.getElementById('transferRecipientSearch').value='';document.getElementById('transferSearchResults').innerHTML='';document.getElementById('transferSelectedRecipient').textContent='';
  configureOwnershipClaim(mode);updateTransferFields();
  document.getElementById('ownershipClaimDate').value='';
  document.getElementById('ownershipClaimPrevious').value='';
  document.getElementById('ownershipClaimBody').value='';
  document.getElementById('ownershipClaimSubmit').textContent=mode==='acquire'?'Submit Ownership Claim':'Add Claim';
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
    alert('Acquire requires an acquisition date.');
    document.getElementById('ownershipClaimDate').focus();
    return;
  }
  if(kind==='release'){
    const guitar=individuals.find(x=>Number(x.id)===Number(pendingOwnershipClaimIndividualId));
    const label=guitar?guitar.manufacturer+' '+(guitar.model||''):'this guitar';
    if(!await confirmOwnershipAction('Release',label+' will be released and Current Owner will become Unknown. Continue?'))return;
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
    alert('Could not add the Ownership Claim.\n'+e.message);
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
    'hk':'hong kong s.a.r.','hkg':'hong kong s.a.r.','hong kong':'hong kong s.a.r.',
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
    svg.innerHTML='<text x="500" y="250" text-anchor="middle" fill="#9ba6b0" font-size="14">World map could not be loaded.</text>';
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
      tooltip.textContent=name+' — '+count+' Product'+(count===1?'':'s');
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
    ['modelChart','yearChart','listingChart'].forEach(id=>chartFallback(id,'Statistics could not be loaded.'));
    return;
  }
  if(typeof Chart==='undefined'){
    ['modelChart','yearChart','listingChart'].forEach(id=>chartFallback(id,'Chart library could not be loaded.'));
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
    chartFallback('modelChart','No model data.');
  }

  const years=data.years||[];
  const yearCanvas=document.getElementById('yearChart');
  if(yearCanvas&&years.length){
    topPageCharts.push(new Chart(yearCanvas,{
      type:'bar',
      data:{
        labels:years.map(x=>x.label),
        datasets:[{
          label:'Products',
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
    chartFallback('yearChart','No year data.');
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
          label:'Listings',
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
    chartFallback('listingChart','No listing data.');
  }
}

function profileGuitarTable(section,title){
  const columns=[['id','ID'],['favorite','♡'],['manufacturer','Maker'],['model','Model'],['finish','Finish'],['year','Year'],['serial_number','Serial'],['claim_count','Claims']];
  return '<section class="panel profile-panel profile-list-panel page-section" data-profile-section="'+section+'" id="profile-'+section+'">'+
    '<div class="toolbar"><h2 data-count-items="#profileRows-'+section+' > tr.clickable">'+title+'</h2><input id="profileFilter-'+section+'" placeholder="maker / model / finish / year / serial" oninput="renderProfileGuitars(\''+section+'\')"></div>'+
    '<div class="table-wrap"><table><thead><tr>'+columns.map(([key,label])=>key==='favorite'?'<th class="favorite-cell" aria-label="Favorite">'+label+'</th>':'<th class="sortable" onclick="setProfileSort(\''+section+'\',\''+key+'\')">'+label+'<span class="sort-indicator" id="profileSort-'+section+'-'+key+'"></span></th>').join('')+'</tr></thead>'+
    '<tbody id="profileRows-'+section+'"></tbody></table></div>'+
    (section==='owned'?'<button id="newGuitarAction" class="new-guitar-action" type="button" onclick="openNewGuitar()" hidden>Let\'s add your undiscovered new guitar!</button>':'')+'</section>';
}
function openNewGuitar(){
  if(!activeUser?.user||Number(activeUser.user.id)!==PROFILE_USER_ID)return;
  if(acquireBusy)return;
  acquireRevision=null;acquireDisplayState=null;acquireForm=null;
  setRequestTitle('Listing Request','Awaiting details');
  document.getElementById('acquireReviewContent').innerHTML='<p>1. Enter details and generate a challenge → 2. Photograph the guitar with the code → 3. Submit both photos</p>'+listingMetadataFields()+ownershipChallengeBox(null)+ownershipEvidenceFields({listing:true,issued:false,date:new Date().toLocaleDateString('sv-SE')})+'<p id="guitarStatus" class="sub" role="status"></p>';
  requestFooter();
  YGCOverlays.open('acquireReviewModal', {onClose: () => {acquireRevision=null;acquireForm=null}});
  document.getElementById('guitarMaker').focus();
}
function closeNewGuitar(){closeAcquireReview()}
async function submitNewGuitar(){
  if(acquireBusy)return;
  if(!await confirmOwnershipAction('Generate Challenge','Generate a challenge for these guitar details? The request will not be saved yet.'))return;
  acquireBusy=true;
  try{await prepareListingDraft()}catch(error){alert(error.message)}finally{acquireBusy=false}
}
async function prepareListingDraft(){
  if(!activeUser?.user||Number(activeUser.user.id)!==PROFILE_USER_ID)return;
  const field=id=>document.getElementById(id);
  const payload={};for(const [key,id] of Object.entries({manufacturer:'guitarMaker',serial_number:'guitarSerial',model:'guitarModel',finish:'guitarFinish',year:'guitarYear',occurred_at:'acquireDate',body:'acquireBody'}))payload[key]=field(id).value.trim();
  if(!payload.manufacturer||!payload.serial_number||!payload.occurred_at)throw new Error('Enter the maker, serial and date.');
  const row=await jfetch('/api/ownership-drafts/listing'+acquireQuery(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(row.status==='duplicate'){
    field('guitarStatus').innerHTML='This maker and serial are already registered. Use Acquire on the existing guitar.'+row.existing_individual_ids.map(id=>'<a href="/users/'+Number(activeUser.user.id)+'?individual_id='+Number(id)+'">Guitar #'+Number(id)+' — View</a>').join('');return;
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
  const rows=(section==='favorites'?profileFavorites:profileGuitars.filter(g=>g.ownership_status===status)).filter(g=>
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
  ).join(''):'<tr><td colspan="8" class="sub">'+(filter?'No matching guitars.':'No guitars yet.')+'</td></tr>';
}
function renderUserChronicle(items){
  const root=document.getElementById('userChronicleList');
  if(!root)return;
  root.innerHTML=items.length?items.map(item=>{
    const category=['User','Social','Product','Claim','Other'].includes(item.category)?item.category:'Other';
    const id=Number(item.individual_id||0);
    const clickable=id>0;
    const interaction=clickable?' onclick="showIndividual('+id+',true)" role="button" tabindex="0" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();showIndividual('+id+',true)}"':'';
    const story=String(item.subject||'')+' '+String(item.message||'');
    return '<div class="profile-chronicle-row'+(clickable?' clickable':'')+'"'+interaction+' title="'+esc(story)+'">'+
      '<span class="profile-chronicle-tag '+category.toLowerCase()+'">'+category+'</span>'+
      '<span class="profile-chronicle-line" aria-hidden="true"></span>'+
      '<span class="profile-chronicle-time">'+esc(displayDiscoveryDateTime(item.event_at))+'</span>'+
      '<span class="profile-chronicle-story"><strong>'+esc(item.subject||'')+'</strong> '+esc(item.message||'')+'</span></div>';
  }).join(''):'<div class="profile-placeholder">No Chronicle entries yet.</div>';
}
function setupProfileShell(){
  document.body.classList.add('profile-mode');
  document.querySelector('header .sub').textContent='User Profile';
  const nav=document.querySelector('.page-nav');
  nav.innerHTML='<a href="/user-view">Top Page</a><a href="#profile-user">User Profile</a><a href="#profile-owned">Owned Guitars</a><a href="#profile-former">Formerly Owned Guitars</a><a href="#profile-favorites">Favorite Guitars</a><a href="#profile-chronicle">User Chronicle</a>';
  document.querySelector('.left-column').innerHTML=
    '<section class="panel profile-panel page-section" data-profile-section="user" id="profile-user"><h2>User Profile</h2><div id="profileHero" class="sub">Loading...</div></section>'+
    profileGuitarTable('owned','Owned Guitars')+
    profileGuitarTable('former','Formerly Owned Guitars')+
    profileGuitarTable('favorites','Favorite Guitars')+
    '<section class="panel profile-panel page-section" data-profile-section="chronicle" id="profile-chronicle"><h2 data-count-items="#userChronicleList > .profile-chronicle-row">User Chronicle</h2><div class="profile-activity-list" id="userChronicleList"><div class="sub">Loading...</div></div></section>';
  for(const selector of ['#statistics','#world-map','.page-bottom-space']){
    const el=document.querySelector(selector);
    if(el)el.remove();
  }
  document.getElementById('detail').textContent='Select a guitar from this profile to view its Product Detail.';
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
    document.getElementById('transferSearchResults').innerHTML=transferCandidates.map((u,index)=>'<button type="button" style="display:block;width:100%;text-align:left;margin-top:4px" onclick="selectTransferRecipient('+index+')">'+esc(u.display_name)+' · #'+Number(u.id)+' · '+esc(u.account_type)+'</button>').join('')||'<p class="sub">No matching users.</p>';
    document.getElementById('transferSearchMore').hidden=users.length<20;
  }catch(e){if(generation===transferSearchGeneration)document.getElementById('transferSearchResults').textContent=e.message}
}
function selectTransferRecipient(index){transferSelectedUser=transferCandidates[index];document.getElementById('transferSelectedRecipient').textContent='To: '+transferSelectedUser.display_name+' (#'+transferSelectedUser.id+')'}
async function submitTransferProposal(){
  if(!transferSelectedUser){alert('Select a recipient from the search results.');return}
  const button=document.getElementById('ownershipClaimSubmit'),individualId=pendingOwnershipClaimIndividualId;button.disabled=true;
  try{
    await jfetch('/api/individuals/'+individualId+'/transfers?viewer_id='+Number(activeUser.user.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_user_id:Number(transferSelectedUser.id)})});
    closeOwnershipClaim();await refreshClaimViews(individualId);
  }catch(e){alert('Transfer could not be proposed.\n'+e.message)}finally{button.disabled=false}
}
async function openTransferReview(claimId){
  const dialog=document.getElementById('transferReviewDialog');YGCOverlays.open(dialog);
  transferReviewRecord=null;document.getElementById('transferReviewBody').textContent='Loading...';document.getElementById('transferReviewActions').innerHTML='';document.getElementById('transferReviewStatus').textContent='';
  try{
    const t=await jfetch('/api/transfers/'+claimId+'?viewer_id='+Number(activeUser.user.id));transferReviewRecord=t;
    document.getElementById('transferReviewBody').innerHTML='<strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+'</strong><p>'+esc([t.guitar?.manufacturer,t.guitar?.model,t.guitar?.serial_number].filter(Boolean).join(' / '))+' · #'+Number(t.individual_id)+' · '+esc(t.state)+'</p>'+(t.accepted_at?'<p class="sub">Info: Transfer accepted on '+esc(displayInputDate(t.accepted_at))+'</p>':'<p class="sub">Accept confirms this ownership transfer. Verification remains a separate Claim judgement.</p>');
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
  document.getElementById('dmConversationList').innerHTML=dmInbox.conversations.map(c=>'<button type="button" class="dm-conversation'+(Number(c.peer_id)===dmPeer?' selected':'')+'" onclick="selectDirectMessagePeer('+Number(c.peer_id)+')"><strong>'+esc(c.peer_name)+'</strong> '+(c.unread_count?'<span class="account-hub-count">'+Number(c.unread_count)+'</span>':'')+'<div class="dm-preview">'+esc(c.preview)+'</div></button>').join('')||'<p class="sub">No conversations yet.</p>';
  document.getElementById('dmMoreConversations').hidden=!dmInbox.next_before_id;
  const count=document.getElementById('directMessageCount');if(count)count.textContent=Number(dmInbox.unread_count||0);
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
  document.getElementById('dmThread').innerHTML='';document.getElementById('dmPeerTitle').textContent='Loading conversation...';
  renderDirectMessageInbox();await loadDirectMessageHistory();
}
async function loadDirectMessageHistory(older=false){
  if(!dmPeer||dmHistoryLoading)return;
  const peer=dmPeer,generation=dmGeneration,cursor=older?dmBefore:null;
  if(older&&!cursor)return;
  dmHistoryLoading=true;document.getElementById('dmOlder').disabled=true;dmStatus('Loading...');
  try{
    const data=await jfetch('/api/dm/users/'+peer+'/messages?viewer_id='+dmActor()+(cursor?'&before_id='+cursor:''));
    if(generation!==dmGeneration)return;
    document.getElementById('dmPeerTitle').innerHTML='<a href="/users/'+Number(data.peer.id)+'" style="color:var(--text)">'+esc(data.peer.display_name)+'</a>';
    const thread=document.getElementById('dmThread'),height=thread.scrollHeight,top=thread.scrollTop;
    const content=data.messages.map(m=>'<div class="dm-message'+(m.sender_user_id===dmActor()?' mine':'')+'">'+esc(m.body)+'<div class="dm-time">'+esc(displayDiscoveryDateTime(m.created_at))+'</div></div>').join('');
    if(older){thread.insertAdjacentHTML('afterbegin',content);thread.scrollTop=top+thread.scrollHeight-height}
    else{thread.innerHTML=content||'<p class="sub">Start a conversation.</p>';thread.scrollTop=thread.scrollHeight}
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
  if(dmHistoryLoading){dmStatus('Wait for the conversation to finish loading.');return}
  if(!body){dmStatus('Enter a message.');return}
  dmSending=true;document.getElementById('dmSend').disabled=true;input.disabled=true;dmStatus('Sending...');
  try{
    await jfetch('/api/dm/users/'+peer+'/messages?viewer_id='+dmActor(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body})});
    input.value='';await loadDirectMessageHistory();await loadDirectMessageInbox();dmStatus('Message sent.');
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
  document.getElementById('userConnectionsTitle').textContent=direction==='followers'?'Followers':'Following';
  document.getElementById('userConnectionsList').innerHTML='';
  document.getElementById('userConnectionsMore').hidden=true;
  YGCOverlays.open(dialog);
  await loadUserConnections();
}
async function loadUserConnections(){
  if(connectionLoading)return;
  connectionLoading=true;
  const generation=connectionGeneration,status=document.getElementById('userConnectionsStatus'),more=document.getElementById('userConnectionsMore');
  more.disabled=true;status.textContent='Loading...';
  try{
    const users=await jfetch('/api/users/'+PROFILE_USER_ID+'/connections/'+connectionDirection+'?limit=50&offset='+connectionOffset);
    if(generation!==connectionGeneration)return;
    const list=document.getElementById('userConnectionsList');
    list.insertAdjacentHTML('beforeend',users.map(u=>'<a style="display:block;padding:8px 0;border-bottom:1px solid var(--line);color:var(--text)" href="/users/'+Number(u.id)+'">'+esc(u.display_name)+' <span class="sub">'+esc(u.account_type)+'</span></a>').join(''));
    connectionOffset+=users.length;more.hidden=users.length<50;
    status.textContent=connectionOffset?'':'No users yet.';
  }catch(e){if(generation===connectionGeneration)status.textContent=e.message}
  finally{if(generation===connectionGeneration){connectionLoading=false;more.disabled=false}}
}

async function loadProfilePage(preferredIndividualId=null){
  const hero=document.getElementById('profileHero');
  if(!activeUser||!activeUser.user){
    applyTheme('dark_default');
    hero.innerHTML='<div class="profile-name">Members only</div><div class="profile-meta">Sign in to view member profiles.</div><div class="profile-actions"><button onclick="location.href=\'/user-view/edit\'">Sign In / Create Account</button></div>';
    for(const section of ['owned','former','favorites','chronicle'])document.getElementById('profile-'+section).hidden=true;
    document.getElementById('detail').textContent='User Profile is available to members.';
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
      ['Account Type',u.account_type||'user'],
      ['Member since',String(u.created_at||'').slice(0,10)],
      ...(locationText?[['Location',locationText]]:[]),
      ...(u.date_of_birth?[['Date of Birth',u.date_of_birth]]:[])
    ].map(([label,value])=>'<div class="profile-meta-item"><span class="profile-meta-label">'+esc(label)+'</span><span class="profile-meta-value">'+esc(value)+'</span></div>').join('');
    const stats=[['Owned',summary.owned_count],['Formerly Owned',summary.former_count],['Claims',summary.claim_count],['Followers',data.social.followers_count],['Following',data.social.following_count]];
    hero.innerHTML='<div class="profile-hero">'+
      '<img class="profile-avatar" src="'+(u.avatar_visible?'/api/users/'+Number(u.id)+'/avatar?viewer_id='+Number(activeUser.user.id)+'&v='+encodeURIComponent(u.updated_at||''):'/assets/no-icon.svg')+'" alt="'+esc(u.display_name||'User')+'" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'">'+
      '<div class="profile-identity"><div class="profile-name">'+esc(u.display_name||'User')+(own?' <span class="account-hub-you">You</span>':'')+'</div>'+
      '<div class="profile-meta">'+profileMeta+'</div>'+
      '<div class="profile-bio'+(u.bio?'':' sub')+'">'+esc(u.bio||'Bio has not been added yet.')+'</div>'+
      '<div class="profile-stats">'+stats.map(x=>['Followers','Following'].includes(x[0])?'<button type="button" class="profile-stat" onclick="openUserConnections(\''+x[0].toLowerCase()+'\')"><strong>'+Number(x[1]||0)+'</strong> '+esc(x[0])+'</button>':'<span class="profile-stat"><strong>'+Number(x[1]||0)+'</strong> '+esc(x[0])+'</span>').join('')+'</div></div>'+
      '<div class="profile-actions">'+(own?'<button onclick="location.href=\'/user-view/edit\'">User Settings</button><button type="button" onclick="showAcquireApplications()">Ownership Requests</button>':'<button id="followUserButton" type="button" aria-pressed="'+Boolean(data.social.is_following)+'" onclick="toggleUserFollow('+Boolean(data.social.is_following)+')">'+(data.social.is_following?'Following':'Follow')+'</button><button type="button" onclick="openDirectMessages('+Number(u.id)+')">Message</button>')+'<span id="followUserStatus" class="sub" role="status"></span></div></div>';
    document.title=(u.display_name||'User')+' — Your Guitar Chronicle';
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
    hero.innerHTML='<div class="profile-placeholder">User Profile could not be loaded. '+esc(e.message)+'</div>';
  }
}

(async()=>{
  await loadActiveUser();
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
    document.getElementById('detail').textContent='No Individual to display.';
  }
})()

if(typeof setInterval==='function')setInterval(()=>{if(!document.hidden&&activeUser?.user)loadOwnershipAttention()},30000);
