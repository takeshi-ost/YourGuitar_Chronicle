import {createProfileList} from './cloud-profile-list.js';
// Favorites always belong to the canonical verified session. Neither a public
// profile setting nor a caller-supplied user ID can select another collection.
const favoriteId=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&!/[\r\n]/.test(value)&&(value.length<19||value<='9223372036854775807');
const favoriteExact=(value,keys)=>Boolean(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key)));
const favoriteIdentity=state=>JSON.stringify([state?.user?.app_user_id??null,state?.identity?.email_verified===true,state?.user?.status??null]);
const favoriteEligible=state=>Boolean(state?.user?.app_user_id&&state?.identity?.email_verified===true&&(!state.user.status||state.user.status==='active'));
const favoriteCount=value=>value==='0'||favoriteId(value);
const favoriteFields=['manufacturer','model','finish','year','serial_number'];
const favoriteText=value=>value===null||typeof value==='string'&&[...value].length<=200&&![...value].some(char=>/[\x00-\x1f\x7f\uD800-\uDFFF]/u.test(char));
async function favoriteRequest(auth,path,options={}){
  const response=await auth.authorizedFetch('/api/auth/favorites'+path,{method:'GET',cache:'no-store',credentials:'omit',redirect:'error',...options},Boolean(options.method&&!['GET','HEAD'].includes(options.method.toUpperCase())));
  if(!response.ok){const body=await response.json().catch(()=>({}));throw Object.assign(Error('Favorite request failed'),{status:response.status,code:(body?.detail?.code||body?.code)==='service_restricted'?'service_restricted':null})}
  return response.json();
}
function favoriteResult(value,id){if(!favoriteExact(value,['individual_id','favorite'])||value.individual_id!==id||typeof value.favorite!=='boolean')throw Error('Invalid favorite result');return value.favorite}
function favoriteError(error){return error.code==='service_restricted'?'favorites.restricted':[401,403].includes(error.status)?'favorites.session':error.status===404?'favorites.missing':'favorites.failed'}

// Coordinate controls for the same canonical identity/guitar within this page.
// A list heart and detail heart must not race or retain contradictory state.
const favoriteObservers=new Set(),favoritePending=new Set();
let favoriteWriteRevision=0;
const favoriteSnapshotFlights=new WeakMap();
const favoriteKey=(owner,id)=>JSON.stringify([owner,id]);
function favoriteBroadcast(change){for(const observer of [...favoriteObservers])observer(change)}

// Share only one in-flight, fully validated personal collection. No completed
// snapshot survives this read; explicit control refresh still uses its detail API.
export function createFavoriteSnapshotReader({auth,state}){
  return function read(target){
    const owner=favoriteIdentity(state()),account=state(),client=auth(),revision=favoriteWriteRevision;
    if(!favoriteId(target)||!favoriteEligible(account)||client?.signedIn!==true||favoritePending.size)return Promise.reject(Error('Favorite session unavailable'));
    let flight=favoriteSnapshotFlights.get(client);
    if(!flight||flight.owner!==owner||flight.account!==account||flight.revision!==revision){
      const entry={owner,account,revision,promise:null};
      entry.promise=(async()=>{
        const ids=new Set();let after=null,total=null;
        do{
          const data=await favoriteRequest(client,'?'+new URLSearchParams({...after?{after}:{},limit:'50'}),{reuseUserData:true});
          if(account!==state()||owner!==favoriteIdentity(state())||client!==auth()||!favoriteEligible(state())||client.signedIn!==true||revision!==favoriteWriteRevision)throw Error('Stale favorites snapshot');
          if(!favoriteExact(data,['items','total','next_after'])||!Array.isArray(data.items)||data.items.length>50||!favoriteCount(data.total)||!(data.next_after===null||favoriteId(data.next_after))||total!==null&&total!==data.total)throw Error('Invalid favorites snapshot');
          total=data.total;
          for(const [index,row] of data.items.entries()){
            if(!favoriteExact(row,['id',...favoriteFields,'photo'])||!favoriteId(row.id)||row.photo!==null||favoriteFields.some(key=>!favoriteText(row[key]))||after!==null&&BigInt(row.id)>=BigInt(after)||index>0&&BigInt(data.items[index-1].id)<=BigInt(row.id)||ids.has(row.id))throw Error('Invalid favorites snapshot row');
            ids.add(row.id);
          }
          if(data.next_after!==null&&(!data.items.length||data.items.at(-1).id!==data.next_after))throw Error('Invalid favorites snapshot cursor');
          after=data.next_after;
        }while(after!==null);
        if(String(ids.size)!==total)throw Error('Incomplete favorites snapshot');
        return ids;
      })().finally(()=>{if(favoriteSnapshotFlights.get(client)===entry)favoriteSnapshotFlights.delete(client)});
      favoriteSnapshotFlights.set(client,entry);flight=entry;
    }
    return flight.promise.then(ids=>{
      if(account!==state()||owner!==favoriteIdentity(state())||client!==auth()||client.signedIn!==true||revision!==favoriteWriteRevision)throw Error('Stale favorites snapshot');
      return {individual_id:target,favorite:ids.has(target)};
    });
  };
}

export function createFavorites({auth,state,busy,work,tableLayout=false,guitarHref=id=>'/guitars/'+id,onNavigate}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params),root=document.getElementById('selfFavorites');
  const node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id)=>{const n=node('button',t(key),id);n.type='button';return n};
  const heading=node('h2',t('favorites.heading'),'favoritesHeading'),status=node('p','','favoritesStatus'),count=node('p','','favoritesCount'),list=node(tableLayout?'tbody':'ul','','favoritesList');
  const refreshButton=button('action.refresh','favoritesRefresh'),previous=button('users.previous','favoritesPrevious'),next=button('users.next','favoritesNext');
  root.setAttribute('aria-labelledby',heading.id);status.setAttribute('role','status');
  let presentation=null;
  if(tableLayout){heading.textContent=t('ui.favorite_guitars_e1514ac1');presentation=createProfileList({section:root,title:heading,list,onSelect:onNavigate,guitarHref,auth,state,busy,refreshButton});root.append(status);previous.hidden=next.hidden=count.hidden=true}
  else root.append(heading,node('p',t('favorites.private_notice')),count,refreshButton,status,list,previous,next);
  let identity=favoriteIdentity(state()),epoch=0,history=[null],nextAfter=null,total=null,notice='',loading=false;
  const eligible=()=>favoriteEligible(state())&&auth()?.signedIn!==false;
  function clear(){epoch++;history=[null];nextAfter=total=null;notice='';loading=false;list.replaceChildren();presentation?.clear();count.textContent=status.textContent='';root.hidden=true;identity=favoriteIdentity(state())}
  function render(){if(identity!==favoriteIdentity(state())||!eligible())clear();root.hidden=!eligible();presentation?.renderControls();status.textContent=notice;count.textContent=total===null?'':t('favorites.count',{count:total});refreshButton.disabled=busy()||loading||!eligible();previous.disabled=busy()||loading||!eligible()||history.length<2;next.disabled=busy()||loading||!eligible()||nextAfter===null}
  async function load(after=null,path=[null],reuse=false){
    if(!eligible())return;const owner=favoriteIdentity(state()),current=++epoch;presentation?.clear();list.replaceChildren();nextAfter=total=null;loading=true;notice=t('cloud.working');render();
    try{
      let data,all=[];const seen=new Set();
      do{
        data=await favoriteRequest(auth(),'?'+new URLSearchParams({...after?{after}:{},limit:tableLayout?'50':'25'}),{reuseUserData:reuse});
        if(current!==epoch||owner!==favoriteIdentity(state())||!eligible())return;
        if(!favoriteExact(data,['items','total','next_after'])||!Array.isArray(data.items)||data.items.length>(tableLayout?50:25)||!favoriteCount(data.total)||!(data.next_after===null||favoriteId(data.next_after)))throw Error('Invalid favorites page');
      for(const [index,row] of data.items.entries())if(!favoriteExact(row,['id',...favoriteFields,'photo'])||!favoriteId(row.id)||row.photo!==null||favoriteFields.some(key=>!favoriteText(row[key]))||after!==null&&BigInt(row.id)>=BigInt(after)||index>0&&BigInt(data.items[index-1].id)<=BigInt(row.id))throw Error('Invalid favorite guitar');
      if(data.next_after!==null&&(!data.items.length||data.items.at(-1).id!==data.next_after))throw Error('Invalid favorites cursor');
        for(const row of data.items){if(seen.has(row.id))throw Error('Repeated favorite cursor');seen.add(row.id)}
        all.push(...data.items);after=data.next_after;
      }while(tableLayout&&after!==null);
      data={...data,items:all};
      if(tableLayout)presentation.setRows(data.items);
      history=[...path];nextAfter=data.next_after;total=data.total;
      if(!tableLayout)for(const row of data.items){const item=node(tableLayout?'tr':'li'),link=node('a',[row.manufacturer,row.model].filter(Boolean).join(' ')||t('favorites.guitar',{id:row.id}));item.dataset.favoriteId=row.id;link.href=guitarHref(row.id);if(onNavigate)link.onclick=event=>{if(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(row.id)};if(tableLayout){const first=node('td');link.textContent=row.manufacturer||'—';first.append(link);item.append(first);for(const value of [row.model,row.finish,row.year,row.serial_number])item.append(node('td',value??'—'))}else item.append(link,node('p',[row.year,row.finish,row.serial_number].filter(Boolean).join(' · ')));list.append(item)}
      notice=tableLayout||data.items.length?'':t('favorites.empty');
    }catch(error){if(current!==epoch||owner!==favoriteIdentity(state())||!eligible())return;list.replaceChildren();presentation?.clear();total=nextAfter=null;history=[null];notice=t(favoriteError(error))}
    finally{if(current===epoch){loading=false;render()}}
  }
  const action=fn=>{if(busy()||loading||!eligible())return;return work(fn)};
  const refresh=({reuse=false}={})=>load(null,[null],reuse);refreshButton.onclick=()=>action(refresh);
  previous.onclick=()=>{if(history.length<2)return;const path=history.slice(0,-1);return action(()=>load(path.at(-1),path))};
  next.onclick=()=>{if(nextAfter===null)return;const after=nextAfter;return action(()=>load(after,[...history,after]))};
  favoriteObservers.add(change=>{if(change.phase==='saved'&&change.owner===favoriteIdentity(state())&&eligible())void refresh()});
  globalThis.addEventListener('popstate',()=>render());globalThis.addEventListener('pagehide',clear);render();return {render,clear,refresh};
}

// The public catalog renders only this visitor's own state, never a public
// favorites list/count. Display and writes stay separate from public GET data.
export function createFavoriteControl({auth,state,root,compact=false,idPrefix='',document=globalThis.document,t,canWrite=()=>true,busy=()=>false}){
  const node=(tag,id)=>{const n=document.createElement(tag);n.id=idPrefix+id;return n};
  const toggle=node('button','favoriteToggle'),refreshButton=node('button','favoriteRefresh'),status=node('p','favoriteStatus'),account=node('a','favoriteAccount'),help=node('p','favoritePrivateNotice');
  if(compact)root.classList.add('favorite-control-compact');
  toggle.type=refreshButton.type='button';status.setAttribute('role','status');account.href='/account#selfFavorites';root.append(toggle,refreshButton,account,help,status);
  let id=null,value=null,epoch=0,loading=false,mutating=false,uncertain=false,notice='',identity=favoriteIdentity(state());
  const eligible=()=>favoriteEligible(state())&&auth()?.signedIn===true;
  function clear(){favoriteObservers.delete(observe);epoch++;id=null;value=null;loading=mutating=uncertain=false;notice='';root.hidden=true;toggle.hidden=refreshButton.hidden=account.hidden=true;toggle.textContent=status.textContent='';toggle.setAttribute('aria-pressed','false');identity=favoriteIdentity(state())}
  function render(){
    if(identity!==favoriteIdentity(state())||!eligible()&&value!==null)clear();root.hidden=!id;
    toggle.hidden=refreshButton.hidden=!eligible();account.hidden=eligible();account.textContent=t('favorites.account');help.textContent=t('favorites.private_notice');
    toggle.textContent=t(value===true?'favorites.remove':'favorites.add');toggle.setAttribute('aria-pressed',String(value===true));toggle.disabled=!id||!eligible()||loading||mutating||uncertain||value===null||!canWrite()||busy()||favoritePending.has(favoriteKey(identity,id));refreshButton.textContent=t('action.refresh');refreshButton.disabled=!id||!eligible()||loading||mutating||busy()||favoritePending.has(favoriteKey(identity,id));
    status.textContent=uncertain?t('favorites.uncertain'):notice?t(notice):eligible()&&!canWrite()?t('favorites.restricted'):'';
    if(compact){root.hidden=!id||!eligible();help.hidden=account.hidden=true;refreshButton.hidden=!eligible()||!(uncertain||value===null&&notice&&notice!=='cloud.working'&&!loading&&!mutating&&!favoritePending.has(favoriteKey(identity,id)));toggle.className='favorite-button'+(value===true?' is-favorite':'');toggle.setAttribute('aria-label',t(value===true?'favorites.remove':'favorites.add'));toggle.title=status.textContent||t(busy()?'cloud.working':value===true?'favorites.remove':'favorites.add');toggle.setAttribute('aria-describedby',status.id);refreshButton.className='favorite-refresh-compact';refreshButton.textContent='↻';refreshButton.setAttribute('aria-label',t('action.refresh'));refreshButton.title=t('action.refresh');status.className='favorite-status-compact';toggle.textContent=value===true?'♥':'♡';status.hidden=!status.textContent;}
  }
  function observe(change){
    if(change.owner!==favoriteIdentity(state())||change.id!==id||!eligible()||change.source===observe)return;
    ++epoch;loading=false;value=typeof change.value==='boolean'?change.value:null;uncertain=change.uncertain===true;
    notice=change.phase==='start'?'cloud.working':change.notice||'';render();
  }
  const current=(generation,owner,target)=>generation===epoch&&owner===favoriteIdentity(state())&&eligible()&&target===id;
  async function refresh(read=null){
    if(!id||!eligible()||loading||mutating||favoritePending.has(favoriteKey(favoriteIdentity(state()),id)))return;const generation=++epoch,owner=favoriteIdentity(state()),target=id;value=null;loading=true;notice='cloud.working';render();
    try{const data=await (read?read(target):favoriteRequest(auth(),'/'+target));if(!current(generation,owner,target))return;value=favoriteResult(data,target);uncertain=false;notice='';favoriteBroadcast({owner,id:target,source:observe,phase:'read',value})}
    catch(error){if(!current(generation,owner,target))return;value=null;notice=favoriteError(error)}
    finally{if(current(generation,owner,target)){loading=false;render()}}
  }
  async function change(){
    if(!id||!eligible()||loading||mutating||uncertain||value===null||!canWrite()||busy()||favoritePending.has(favoriteKey(favoriteIdentity(state()),id)))return;
    const generation=++epoch,owner=favoriteIdentity(state()),target=id,desired=!value,key=favoriteKey(owner,target);mutating=true;notice='cloud.working';++favoriteWriteRevision;favoritePending.add(key);favoriteBroadcast({owner,id:target,source:observe,phase:'start'});render();
    try{const data=await favoriteRequest(auth(),'/'+target,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorite:desired})});if(!current(generation,owner,target))return;const result=favoriteResult(data,target);if(result!==desired)throw Error('Unexpected favorite result');value=result;notice=result?'favorites.added':'favorites.removed'}
    catch(error){if(!current(generation,owner,target))return;value=null;if([400,401,403,404,409,422].includes(error.status))notice=favoriteError(error);else{uncertain=true;notice=''}}
    finally{++favoriteWriteRevision;favoritePending.delete(key);if(current(generation,owner,target)){mutating=false;render();favoriteBroadcast({owner,id:target,source:observe,phase:typeof value==='boolean'?'saved':'failed',value,uncertain,notice})}else favoriteBroadcast({owner,id:target,source:observe,phase:'failed',value:null,uncertain:true,notice:''})}
  }
  async function select(target,read=null){clear();if(!favoriteId(target))return;id=target;favoriteObservers.add(observe);render();await refresh(read)}
  toggle.onclick=change;refreshButton.onclick=()=>refresh();clear();return {clear,render,select,refresh};
}
