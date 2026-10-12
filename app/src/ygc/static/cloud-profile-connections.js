import {memberId,memberPage,memberProfile} from './cloud-members.js';

// Self-profile presentation over the existing member projection only.
export function createProfileConnections({auth,state,onUpdate}){
  const t=key=>globalThis.YGCI18n.t(key),template=document.getElementById('formalClaimTemplates');
  const dialog=template.content.querySelector('#userConnectionsDialog').cloneNode(true);
  document.body.append(dialog);
  const list=dialog.querySelector('#userConnectionsList'),status=dialog.querySelector('#userConnectionsStatus'),more=dialog.querySelector('#userConnectionsMore');
  let profile=null,epoch=0,modalEpoch=0,next=null,direction=null,loading=false;
  const identity=()=>state()?.user?.app_user_id,valid=()=>Boolean(identity()&&state()?.identity?.email_verified===true);
  const current=(version,owner)=>epoch===version&&identity()===owner&&valid();
  async function request(path){const response=await auth().authorizedFetch('/api/auth/members/'+path,{cache:'no-store',credentials:'omit',redirect:'error'},false);if(!response.ok)throw Error('Member read failed');return response.json()}
  function resetModal(){modalEpoch++;list.replaceChildren();status.textContent='';more.hidden=true;next=null;loading=false}
  function clear(){epoch++;profile=null;resetModal();globalThis.YGCOverlays.close(dialog)}
  async function refresh(){const version=++epoch,owner=identity(),id=state()?.user?.id;profile=null;if(!valid()||!memberId(id))return;try{const result=memberProfile(await request(id),id);if(!current(version,owner))return;if(!result.is_self)throw Error('Expected self profile');profile=result}catch{if(!current(version,owner))return;profile=null}onUpdate()}
  async function load(){if(!profile||!valid()||loading)return;const version=epoch,owner=identity(),modal=modalEpoch,id=profile.person.id,cursor=next;loading=true;more.disabled=true;status.textContent=t('members.loading');try{let result=memberPage(await request(id+'/connections/'+direction+'?limit=25'+(cursor?'&after='+cursor:'')),cursor);if(!current(version,owner)||modal!==modalEpoch||!dialog.open)return;const rows=[...result.items];if(result.next_after!==null){const after=result.next_after;const second=memberPage(await request(id+'/connections/'+direction+'?limit=25&after='+after),after);if(!current(version,owner)||modal!==modalEpoch||!dialog.open)return;rows.push(...second.items);result=second}for(const row of rows){const link=document.createElement('a');link.href='/ui/members/'+row.id;link.textContent=row.display_name;link.style.cssText='display:block;padding:8px 0;border-bottom:1px solid var(--line);color:var(--text)';list.append(link)}next=result.next_after;more.hidden=next===null;status.textContent=list.children.length?'':t('ui.no_users_yet_44e4e2d9')}catch{if(current(version,owner)&&modal===modalEpoch){list.replaceChildren();next=null;more.hidden=true;status.textContent=t('members.failed')}}finally{if(modal===modalEpoch){loading=false;more.disabled=false}}}
  function open(value){if(!profile||!valid())return;resetModal();direction=value;dialog.querySelector('#userConnectionsTitle').textContent=t(value==='followers'?'ui.followers_a145ab34':'ui.following_344b4271');globalThis.YGCOverlays.open(dialog);return load()}
  function appendStats(target){if(!profile)return;for(const value of ['followers','following']){const button=document.createElement('button');button.type='button';button.className='profile-stat';button.dataset.connections=value;const strong=document.createElement('strong');strong.textContent=profile[value+'_count'];button.append(strong,document.createTextNode(' '+t(value==='followers'?'ui.followers_a145ab34':'ui.following_344b4271')));button.onclick=()=>open(value);target.append(button)}}
  more.onclick=load;dialog.querySelector('[data-ui-action="close"]').onclick=()=>globalThis.YGCOverlays.close(dialog);dialog.addEventListener('ygc:closed',resetModal);window.addEventListener('pagehide',clear);
  return {clear,refresh,appendStats};
}
