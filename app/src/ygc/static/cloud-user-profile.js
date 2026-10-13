import {loadCloudAuth} from './cloud-auth-loader.js';
import {createAuthDialog,authLabel} from './cloud-auth-dialog.js';
import {memberId,memberProfile} from './cloud-member-data.js';
import {createProfileList,selectProfileGuitar} from './cloud-profile-list.js';
import {createPublicCatalog} from './cloud-public-catalog.js';
import {createMemberIcons} from './cloud-member-icons.js';
import {createGuitars} from './cloud-account-guitars.js';
import {createClaims} from './cloud-account-claims.js';
import {createIdentityCorrections} from './cloud-account-identity.js';
import {createDetailClaimActions} from './cloud-detail-claim-actions.js';
const $=id=>document.getElementById(id),t=(key,p)=>globalThis.YGCI18n.t(key,p),target=document.body.dataset.profileTarget;
let auth=null,epoch=0,profile=null,busy=false,active=true,catalog=null,started=false;
const state=()=>active?auth?.account:null,eligible=()=>state()?.identity?.email_verified===true&&state()?.user?.app_user_id&&auth?.signedIn;
const node=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n};
// Reuse the exact profile columns and Detail skeleton, with no self editors.
for(const id of ['catalogAcquireIntent','catalogClaimIntent','catalogOwnershipIntent','authActions','selfGuitars','selfFavorites','selfVisibility','accountAvatar','selfClaims','selfNotifications','selfProfile'])$(id)?.remove();
const column=$('profileColumn');column.replaceChildren();
const hero=node('section','','panel profile-panel'),heading=node('h2',t('ui.user_profile_ee7672e2')),content=node('div','','profile-hero'),avatar=node('span','','profile-avatar person-icon'),identity=node('div','','profile-identity'),name=node('div','','profile-name'),meta=node('div','','profile-meta'),bio=node('div','','profile-bio'),stats=node('div','','profile-stats'),actions=node('div','','profile-actions'),follow=node('button'),notice=node('p','','notice');
hero.id='viewedUserProfile';follow.type='button';follow.id='profileFollow';identity.append(name,meta,bio,stats);actions.append(follow);content.append(avatar,identity,actions);hero.append(heading,content,notice);column.append(hero);
const connections=node('dialog'),connectionTitle=node('h2'),connectionList=node('div'),connectionStatus=node('p'),more=node('button',t('members.more'));more.type='button';connections.append(connectionTitle,connectionList,connectionStatus,more);connections.id='profileConnections';document.body.append(connections);let direction=null,cursor=null,connectionEpoch=0;
const lists={};for(const [kind,key] of [['owned','ui.owned_guitars_bb07d3cd'],['formerly_owned','ui.formerly_owned_guitars_0769f4fa']]){const section=node('section','','panel profile-panel'),title=node('h2',t(key)),list=node('tbody'),refresh=node('button',t('action.refresh'));section.id='profile_'+kind;list.id='profileRows_'+kind;refresh.type='button';column.append(section);const view=createProfileList({section,title,list,refreshButton:refresh,auth:()=>auth,state,busy:()=>busy,onSelect:openGuitar,guitarHref:id=>'/ui/profiles/'+target+'/guitars/'+id});lists[kind]=view;refresh.onclick=load;}
$('shellTitle').textContent=t('ui.user_profile_ee7672e2');$('shellMembers')?.remove();$('shellProducts').href='/ui';$('shellProducts').textContent=t('ui.top_page_272373b6');$('shellSignOut').hidden=true;$('accountLink').href='/ui/profile';$('accountLink').textContent=t('self_profile.heading');$('shellNotifications').href='/ui/profile#selfNotifications';
const icons=createMemberIcons({auth:()=>auth,identity:()=>state()?.user?.app_user_id,eligible});
const work=async fn=>{if(busy)return;busy=true;try{return await fn()}finally{busy=false;detailActions.render()}};
const owners=createGuitars({root:document.createElement('section'),auth:()=>auth,state,busy:()=>busy,work});
const claims=createClaims({formal:true,root:document.createElement('section'),intentRoot:document.createElement('section'),auth:()=>auth,state,busy:()=>busy,work,onSaved:()=>catalog?.refresh({preserveView:true})});
const corrections=createIdentityCorrections({listPanel:false,auth:()=>auth,state,busy:()=>busy,work});
const detailActions=createDetailClaimActions({auth:()=>auth,state,busy:()=>busy,owners,claims,identityCorrections:corrections});
const authDialog=createAuthDialog({auth:()=>auth,onAuthenticated:load});$('shellSignIn').textContent=authLabel();$('shellSignIn').disabled=false;$('shellSignIn').onclick=()=>authDialog.open({opener:$('shellSignIn')});
async function request(path){const response=await auth.authorizedFetch(path,{cache:'no-store'},false);if(!response.ok)throw Error(t('users.profile_unavailable'));return response.json()}
function clear(){epoch++;profile=null;icons.clear();name.textContent=meta.textContent=bio.textContent='';stats.replaceChildren();for(const view of Object.values(lists))view.clear();connectionEpoch++;connectionList.replaceChildren();globalThis.YGCOverlays.close(connections);follow.hidden=true;detailActions.clear();catalog?.invalidateIdentity();}
async function openConnections(which,after=null){if(!profile||!eligible())return;direction=which;const token=++connectionEpoch;if(!after){connectionList.replaceChildren();connectionTitle.textContent=t(which==='followers'?'ui.followers_a145ab34':'ui.following_344b4271');globalThis.YGCOverlays.open(connections)}try{const data=await request('/api/auth/members/'+target+'/connections/'+which+'?limit=25'+(after?'&after='+after:''));if(token!==connectionEpoch||!profile||!connections.open)return;for(const person of data.items){const link=node('a',person.display_name);link.href='/ui/profiles/'+person.id;connectionList.append(link)}cursor=data.next_after;more.hidden=!cursor;connectionStatus.textContent=data.items.length?'':t('members.empty')}catch{if(token===connectionEpoch)connectionStatus.textContent=t('members.failed')}}
more.onclick=()=>openConnections(direction,cursor);connections.addEventListener('ygc:closed',()=>{connectionEpoch++;connectionList.replaceChildren()});
follow.onclick=()=>work(async()=>{if(!profile||!eligible())return;const token=epoch;follow.disabled=true;try{const response=await auth.authorizedFetch('/api/auth/members/'+target+'/following',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({following:!profile.member.following})},true);if(!response.ok)throw Error();if(token===epoch)await load()}catch{if(token===epoch){notice.textContent=t('members.uncertain');follow.disabled=true}}});
async function openGuitar(id){if(catalog)return catalog.navigate('/ui/profiles/'+target+'/guitars/'+id)}
async function load(){clear();const token=epoch;notice.textContent=t('cloud.working');try{
 auth=auth||await loadCloudAuth();await auth.restore();if(token!==epoch)return;if(!eligible()){notice.textContent=t('members.signin');$('shellSignIn').hidden=false;return}
 if(state().user.id===target){location.replace('/ui/profile');return}
 const data=await request('/api/auth/profiles/'+target);if(token!==epoch||!eligible())return;memberProfile(data.member,target);if(data.member.is_self){location.replace('/ui/profile');return}if(!data.fields||['account_type','bio','location_country','location_region'].some(k=>!(data.fields[k]===null||typeof data.fields[k]==='string')))throw Error();profile=data;
 name.textContent=data.member.person.display_name;document.title=name.textContent+' — Your Guitar Chronicle';meta.textContent=[data.fields.account_type,[data.fields.location_country,data.fields.location_region].filter(Boolean).join(' / ')].filter(Boolean).join(' · ');bio.textContent=data.fields.bio||t('ui.bio_has_not_been_added_yet_228545e8');
 icons.mount(avatar,target);follow.hidden=data.member.is_self;follow.disabled=!data.member.can_write;follow.textContent=t(data.member.following?'members.unfollow':'members.follow');follow.setAttribute('aria-pressed',String(data.member.following));stats.replaceChildren();for(const which of ['followers','following']){const b=node('button',t('members.'+which,{count:data.member[which+'_count']}),'profile-stat');b.type='button';b.onclick=()=>openConnections(which);stats.append(b)}
 $('shellIdentity').textContent=state().user.display_name;$('shellAccountLinks').hidden=false;$('shellSignIn').hidden=true;notice.textContent='';
 for(const kind of ['owned','formerly_owned']){const p=data[kind];if(!p||!Array.isArray(p.items)||p.items.length>50||p.items.some(r=>!memberId(r.id)))throw Error();lists[kind].setRows(p.items)}
 if(!catalog)catalog=createPublicCatalog({basePath:'/ui/profiles/'+target,accountPath:'/ui/profile',detailOnly:true,loadAuth:async()=>auth,restoredAccount:state,onState:s=>{$('productDetailShell').classList.toggle('compact-open',s.detailOpen);selectProfileGuitar(s.selectedId);detailActions.render()},onChronicle:detailActions.load,onClaimPopup:detailActions.popup,onClaim:id=>location.assign('/ui/profile?claim='+id),onAcquire:id=>location.assign('/ui/profile?acquire='+id)});
 if(!location.pathname.includes('/guitars/')){const initial=data.owned.items[0]?.id||data.formerly_owned.items[0]?.id;if(initial)history.replaceState(null,'','/ui/profiles/'+target+'/guitars/'+initial)}
 if(!started){started=true;await catalog.start()}else await catalog.refresh({preserveView:true});
 // Continue large inventories after the first Detail is visible.
 for(const kind of ['owned','formerly_owned']){let next=data[kind].next_after,rows=[...data[kind].items];const seen=new Set(rows.map(r=>r.id));while(next){const page=await request('/api/auth/profiles/'+target+'?kind='+kind+'&after='+next);if(token!==epoch||!eligible())return;const p=page[kind];if(!p||!Array.isArray(p.items)||p.items.length>50||p.items.some(r=>!memberId(r.id)||seen.has(r.id)||BigInt(r.id)<=BigInt(next)))throw Error();for(const r of p.items)seen.add(r.id);rows.push(...p.items);next=p.next_after;lists[kind].setRows(rows)}}
 }catch(error){if(token===epoch){clear();notice.textContent=error.message||t('users.profile_unavailable')}}}
window.addEventListener('pagehide',()=>{active=false;clear()});
auth=await loadCloudAuth();auth.onIdentityChanged?.(()=>{clear();void load()});auth.onUserDataInvalidated?.(reason=>{if(reason==='blocked')clear()});await load();globalThis.YGCCloudOtherProfileReady=true;
