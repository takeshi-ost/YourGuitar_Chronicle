// Self-only adapter for the canonical local account-hub layout. No member or
// public profile projection is read; private avatar bytes use short-lived blobs.
export function createAccountHub({auth,state,onUpdate=()=>{},readAvatar=true,readNotifications=true}){
 const $=id=>document.getElementById(id),hub=$('accountHub'),oldUser=hub.querySelector('.account-hub-user'),actions=hub.querySelector('.account-hub-actions:last-child');
 const user=document.createElement('a');user.href='/ui/profile';user.className='account-hub-user account-hub-user-link';user.hidden=true;
 const avatar=document.createElement('img');avatar.className='account-hub-avatar';avatar.alt='';avatar.src='/assets/no-icon.svg';
 const copy=document.createElement('div');copy.className='account-hub-user-copy';const nameRow=document.createElement('div');nameRow.className='account-hub-name-row';const name=document.createElement('span');name.className='account-hub-name';nameRow.append(name);const location=document.createElement('div');location.className='account-hub-location';copy.append(nameRow,location);user.append(avatar,copy);
 const summary=document.createElement('div');summary.className='account-hub-summary';summary.hidden=true;oldUser.before(user,summary);
 const notifications=$('shellNotifications');actions.prepend(notifications);
 let identity=null,epoch=0,settings=null,counts=null,unread=null,url=null,flight=null,subscribed=null;
 const t=key=>globalThis.YGCI18n.t(key);
 function clear(){epoch++;flight=null;identity=null;settings=counts=unread=null;if(url)URL.revokeObjectURL(url);url=null;avatar.src='/assets/no-icon.svg';user.hidden=summary.hidden=true;name.textContent=location.textContent='';summary.replaceChildren();notifications.querySelector('.account-hub-count')?.remove();notifications.classList.remove('primary')}
 function render(){
  const client=auth();if(client&&subscribed!==client){subscribed=client;client.onUserDataInvalidated?.(reason=>{if(reason==='changed'&&client===auth()&&identity){epoch++;flight=null;void refresh()}})}
  const account=state(),valid=account?.identity?.email_verified===true&&account?.user?.app_user_id;
  const changed=identity!==valid;
  if(changed){clear();identity=valid||null}
  oldUser.hidden=Boolean(valid);user.hidden=summary.hidden=!valid;$('shellGuestSpacer')&&($('shellGuestSpacer').hidden=Boolean(valid));$('shellAccountLinks').hidden=true;notifications.hidden=!valid;$('shellProfile').hidden=Boolean(valid);$('accountLink').hidden=Boolean(valid);
  if(!valid){if(identity)clear();return}
  name.textContent=account.user.display_name;avatar.alt=account.user.display_name;user.setAttribute('aria-label','View '+account.user.display_name+' profile');location.textContent=settings?[settings.location_country,settings.location_region].filter(Boolean).join(' / ')||t('ui.location_not_set_0ccd1c0b'):'';
  summary.replaceChildren();for(const [key,label] of [['owned_count','ui.owned_17b760c4'],['former_count','ui.formerly_owned_65b08593'],['claim_count','ui.claims_1c85c122']]){const row=document.createElement('div');row.className='account-hub-stat';const value=document.createElement('span');value.className='account-hub-stat-value';value.textContent=counts?.[key]??'—';const title=document.createElement('span');title.className='account-hub-stat-label';title.textContent=t(label);row.append(value,title);summary.append(row)}
  notifications.replaceChildren(document.createTextNode(t('header.notifications')));if(unread!==null){const badge=document.createElement('span');badge.className='account-hub-count';badge.textContent=unread;notifications.append(' ',badge);notifications.classList.toggle('primary',BigInt(unread)>0n)}
  if(changed)void refresh({reuse:true})
 }
 async function load({reuse=false}={}){
  const owner=identity,version=++epoch,current=()=>version===epoch&&owner===state()?.user?.app_user_id&&state()?.identity?.email_verified===true;
  if(!owner)return;
  const json=async path=>{const response=await auth().authorizedFetch(path,{cache:'no-store',reuseUserData:reuse},false);if(!response.ok)throw Error('Unavailable');return response.json()};
  const results=await Promise.allSettled([json('/api/auth/settings'),json('/api/auth/profile/summary'),readAvatar?auth().authorizedFetch('/api/auth/avatar',{cache:'no-store'},false):Promise.resolve(null),readNotifications?json('/api/auth/notifications?limit=25'):Promise.resolve(null)]);
  if(!current())return;
  if(results[0].status==='fulfilled'){const data=results[0].value;if(data?.fields&&['location_country','location_region','theme'].every(key=>typeof data.fields[key]==='string')){settings=data.fields;document.documentElement.dataset.theme=settings.theme}}
  if(results[1].status==='fulfilled'){const data=results[1].value;if(data&&Object.keys(data).length===3&&['owned_count','former_count','claim_count'].every(key=>typeof data[key]==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(data[key])))counts=data}
  if(results[2].status==='fulfilled'){const response=results[2].value;if(response?.ok&&response.headers.get('content-type')?.split(';')[0]==='image/jpeg'){const blob=await response.blob();if(current()&&blob.size&&blob.size<=25*1024*1024){if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);avatar.src=url}}}
  if(!current())return;
  if(results[3].status==='fulfilled'&&typeof results[3].value?.unread_count==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(results[3].value.unread_count))unread=results[3].value.unread_count;
  if(current()){render();onUpdate()}
 }
 function refresh(options={}){
  const owner=identity;if(!owner)return Promise.resolve();
  if(flight?.owner===owner)return flight.promise;
  const next={owner,promise:null};next.promise=load(options).finally(()=>{if(flight===next)flight=null});flight=next;return next.promise;
 }
 window.addEventListener('pagehide',clear);
 window.addEventListener('ygc-self-avatar',event=>{
  if(readAvatar||event.detail?.actor!==identity||identity!==state()?.user?.app_user_id||state()?.identity?.email_verified!==true)return;
  const blob=event.detail.blob;
  if(blob!==null&&(!(blob instanceof Blob)||blob.type!=='image/jpeg'||!blob.size||blob.size>25*1024*1024))return;
  if(url)URL.revokeObjectURL(url);url=null;avatar.src='/assets/no-icon.svg';
  if(blob){url=URL.createObjectURL(blob);avatar.src=url}
 });
 window.addEventListener('ygc-notification-count',event=>{if(event.detail?.actor===identity&&typeof event.detail.count==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(event.detail.count)){unread=event.detail.count;render()}});
 return {render,refresh,ready:()=>flight?.promise||Promise.resolve(),clear,get counts(){return counts}};
}
