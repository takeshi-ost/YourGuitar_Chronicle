import {catalogIndividualId} from './cloud-account-applications.js';

const object=value=>Boolean(value&&typeof value==='object'&&!Array.isArray(value));
const exact=(value,keys)=>object(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const text=(value,limit,multiline=false)=>typeof value==='string'&&[...value].length<=limit&&!/[\uD800-\uDFFF]/u.test(value)&&!(multiline?/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/:/[\x00-\x1f\x7f]/).test(value);
const count=value=>value==='0'||Boolean(catalogIndividualId(value));
const date=value=>text(value,40)&&value.length>0;

// A notice describes a past event. Its destination is only a hint: existing
// destination components fetch their canonical API again before showing data.
// Opening a notice never marks it read or performs a workflow decision.
export function createNotifications({auth,state,busy,work,openTransfer,openOwner}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,value='',id='')=>{const n=document.createElement(tag);n.textContent=value;if(id)n.id=id;return n};
  const button=(key,id='')=>{const n=node('button',t(key),id);n.type='button';return n};
  const root=document.getElementById('selfNotifications'),heading=node('h2',t('notifications.heading'),'notificationHeading'),unread=node('p','','notificationUnread'),status=node('p','','notificationStatus'),list=node('ul','','notificationList');
  const refreshButton=button('action.refresh','notificationRefresh'),markAll=button('notifications.mark_all','notificationMarkAll'),previous=button('users.previous','notificationPrevious'),next=button('users.next','notificationNext');
  root.setAttribute('aria-labelledby',heading.id);status.setAttribute('role','status');unread.setAttribute('aria-live','polite');
  root.append(heading,node('p',t('notifications.history_help'),'notificationHistoryHelp'),unread,refreshButton,markAll,status,list,previous,next);
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  const eligible=()=>Boolean(state()?.user?.app_user_id&&state()?.identity?.email_verified===true&&(!state()?.user?.status||state().user.status==='active'));
  let renderedIdentity=identity(),accountEpoch=0,readEpoch=0,writeEpoch=0,navigationEpoch=0,rows=[],history=[null],nextAfter=null,unreadCount=null,canWrite=null,notice='',uncertain=false;
  const context=()=>({account:accountEpoch,identity:identity(),navigation:navigationEpoch});
  const current=c=>c.account===accountEpoch&&c.identity===identity()&&c.navigation===navigationEpoch&&eligible();
  const writable=()=>eligible()&&canWrite===true&&!uncertain;
  function destination(value){
    if(value===null)return null;
    if(exact(value,['kind','claim_id'])&&value.kind==='transfer'&&catalogIndividualId(value.claim_id))return Object.freeze({kind:'transfer',claim_id:value.claim_id});
    if(exact(value,['kind','individual_id','claim_id'])&&value.kind==='owner'&&catalogIndividualId(value.individual_id)&&catalogIndividualId(value.claim_id))return Object.freeze({kind:'owner',individual_id:value.individual_id,claim_id:value.claim_id});
    throw Error('Invalid notification destination');
  }
  function notification(value){
    if(!exact(value,['id','notification_type','title','body','created_at','is_read','read_at','actor','destination'])||!catalogIndividualId(value.id)||!text(value.notification_type,64)||!value.notification_type||!text(value.title,200)||!(value.body===null||text(value.body,8000,true))||!date(value.created_at)||typeof value.is_read!=='boolean'||!(value.read_at===null||date(value.read_at)))throw Error('Invalid notification');
    let actor=null;
    if(value.actor!==null){if(!exact(value.actor,['id','display_name'])||!catalogIndividualId(value.actor.id)||!text(value.actor.display_name,120))throw Error('Invalid notification actor');actor=Object.freeze({id:value.actor.id,display_name:value.actor.display_name})}
    return Object.freeze({id:value.id,notification_type:value.notification_type,title:value.title,body:value.body,created_at:value.created_at,is_read:value.is_read,read_at:value.read_at,actor,destination:destination(value.destination)});
  }
  function page(value,after){
    if(!exact(value,['items','next_after','unread_count','can_write'])||!Array.isArray(value.items)||value.items.length>25||!count(value.unread_count)||typeof value.can_write!=='boolean'||!(value.next_after===null||catalogIndividualId(value.next_after)))throw Error('Invalid notification page');
    const items=value.items.map(notification);
    if(new Set(items.map(row=>row.id)).size!==items.length||items.some((row,index)=>after!==null&&BigInt(row.id)>=BigInt(after)||index>0&&BigInt(items[index-1].id)<=BigInt(row.id))||value.next_after!==null&&(!items.length||items.at(-1).id!==value.next_after))throw Error('Invalid notification cursor');
    return {items,next_after:value.next_after,unread_count:value.unread_count,can_write:value.can_write};
  }
  async function request(path='',options={}){
    const response=await auth().authorizedFetch('/api/auth/notifications'+path,{cache:'no-store',credentials:'omit',redirect:'error',...options},true);
    if(!response.ok){const value=await response.json().catch(()=>({}));throw Object.assign(Error('Notification request failed'),{status:response.status,code:(value?.detail?.code||value?.code)==='service_restricted'?'service_restricted':null})}
    return response.json();
  }
  function errorText(error){return t(error.code==='service_restricted'?'applications.service_restricted':[401,403].includes(error.status)?'self_profile.restricted':error.status===404?'notifications.unavailable':'notifications.failed')}
  function purge(){readEpoch++;writeEpoch++;rows=[];history=[null];nextAfter=null;unreadCount=null;canWrite=null;list.replaceChildren();unread.textContent=''}
  function clear(){accountEpoch++;purge();uncertain=false;notice='';status.textContent='';root.hidden=true;renderedIdentity=identity()}
  function renderRows(){
    list.replaceChildren();const c=context(),generation=readEpoch;
    for(const row of rows){
      const item=node('li'),title=node('h3',row.title),body=node('p',row.body??''),meta=node('p',(row.actor?row.actor.display_name+' · ':'')+row.created_at),readState=node('p',t(row.is_read?'notifications.read':'notifications.unread')+(row.read_at?' · '+row.read_at:'')),mark=button('notifications.mark_one');
      item.dataset.notificationId=row.id;item.dataset.read=String(row.is_read);mark.dataset.notificationMark=row.id;mark.hidden=row.is_read;
      const valid=()=>current(c)&&generation===readEpoch;
      mark.onclick=()=>{if(valid())return markRead(row.id)};
      item.append(title,body,meta,readState,mark);
      if(row.destination){
        const target=row.destination,open=button(target.kind==='transfer'?'notifications.open_transfer':'notifications.open_owner');open.dataset.notificationOpen=row.id;
        open.onclick=()=>{if(busy()||!valid())return;return target.kind==='transfer'?openTransfer(target.claim_id):openOwner(target.individual_id,target.claim_id)};item.append(open);
      }else item.append(node('p',t('notifications.no_destination')));
      list.append(item);
    }
  }
  function render(){
    if(renderedIdentity!==identity())clear();root.hidden=!eligible();
    unread.textContent=unreadCount===null?'':t('notifications.unread_count',{count:unreadCount});
    status.textContent=[notice,uncertain?t('notifications.uncertain'):canWrite===false?t('applications.read_only'):''].filter(Boolean).join(' ');
    refreshButton.disabled=busy()||!eligible();markAll.disabled=busy()||!writable()||unreadCount===null||unreadCount==='0';
    previous.disabled=busy()||!eligible()||history.length<2;next.disabled=busy()||!eligible()||nextAfter===null;
    for(const control of list.querySelectorAll('button'))control.disabled=busy()||!eligible()||(control.dataset.notificationMark?!writable():false);
  }
  function action(fn){if(busy()||!eligible())return;return work(async()=>{try{return await fn()}finally{render()}})}
  async function load(after=null,{checked=false,path=[null]}={}){
    if(!eligible())return false;const c=context(),generation=++readEpoch;writeEpoch++;rows=[];list.replaceChildren();nextAfter=null;unreadCount=null;canWrite=null;notice=t('cloud.working');render();
    try{
      const data=page(await request('?'+new URLSearchParams({...after?{after}:{},limit:'25'})),after);
      if(!current(c)||generation!==readEpoch)return false;
      rows=data.items;nextAfter=data.next_after;unreadCount=data.unread_count;canWrite=data.can_write;history=[...path];if(checked)uncertain=false;notice=rows.length?'':t('notifications.empty');renderRows();render();return true;
    }catch(error){
      if(!current(c)||generation!==readEpoch)return false;purge();notice=errorText(error);render();return false;
    }
  }
  function refresh(){return load(null,{checked:true})}
  function result(value,id){
    if(id===null){if(!exact(value,['marked_count','unread_count'])||!count(value.marked_count)||!count(value.unread_count))throw Error('Invalid read-all result')}
    else if(!exact(value,['id','is_read','read_at','unread_count'])||value.id!==id||value.is_read!==true||!date(value.read_at)||!count(value.unread_count))throw Error('Invalid read result');
  }
  function markRead(id=null){
    if(busy()||!writable()||id!==null&&(!catalogIndividualId(id)||!rows.some(row=>row.id===id&&!row.is_read))||id===null&&(unreadCount===null||unreadCount==='0'))return;
    const c=context(),generation=++writeEpoch,after=history.at(-1),path=[...history];readEpoch++;canWrite=null;notice=t('cloud.working');renderRows();
    return action(async()=>{
      try{
        const data=await request(id===null?'/read-all':'/'+id+'/read',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});result(data,id);
        if(!current(c)||generation!==writeEpoch)return;
        // A successful write still gets a fresh recipient-only page; never
        // manufacture a read timestamp, count, or destination from old rows.
        await load(after,{path});
      }catch(error){
        if(!current(c)||generation!==writeEpoch)return;
        if(error.code==='service_restricted'){
          const checking=readEpoch+1;await load(after,{path});if(current(c)&&readEpoch===checking){canWrite=false;notice=errorText(error)}
        }else if([401,403,404].includes(error.status)){purge();notice=errorText(error)}
        else if([400,409,422].includes(error.status)){canWrite=null;notice=errorText(error)}
        else{uncertain=true;canWrite=null;notice=''}
        render();
      }
    });
  }
  refreshButton.onclick=()=>action(refresh);markAll.onclick=()=>markRead();
  previous.onclick=()=>{if(busy()||history.length<2)return;const path=history.slice(0,-1);return action(()=>load(path.at(-1),{path}))};
  next.onclick=()=>{if(busy()||nextAfter===null)return;const after=nextAfter,path=[...history,after];return action(()=>load(after,{path}))};
  globalThis.addEventListener('popstate',()=>{navigationEpoch++;purge();notice='';render()});globalThis.addEventListener('pagehide',clear);
  render();return {render,clear,refresh};
}
