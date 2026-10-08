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
  const response=await auth.authorizedFetch('/api/auth/favorites'+path,{method:'GET',cache:'no-store',credentials:'omit',redirect:'error',...options},true);
  if(!response.ok){const body=await response.json().catch(()=>({}));throw Object.assign(Error('Favorite request failed'),{status:response.status,code:(body?.detail?.code||body?.code)==='service_restricted'?'service_restricted':null})}
  return response.json();
}
function favoriteResult(value,id){if(!favoriteExact(value,['individual_id','favorite'])||value.individual_id!==id||typeof value.favorite!=='boolean')throw Error('Invalid favorite result');return value.favorite}
function favoriteError(error){return error.code==='service_restricted'?'favorites.restricted':[401,403].includes(error.status)?'favorites.session':error.status===404?'favorites.missing':'favorites.failed'}

export function createFavorites({auth,state,busy,work,tableLayout=false,guitarHref=id=>'/guitars/'+id,onNavigate}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params),root=document.getElementById('selfFavorites');
  const node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id)=>{const n=node('button',t(key),id);n.type='button';return n};
  const heading=node('h2',t('favorites.heading'),'favoritesHeading'),status=node('p','','favoritesStatus'),count=node('p','','favoritesCount'),list=node(tableLayout?'tbody':'ul','','favoritesList');
  const refreshButton=button('action.refresh','favoritesRefresh'),previous=button('users.previous','favoritesPrevious'),next=button('users.next','favoritesNext');
  root.setAttribute('aria-labelledby',heading.id);status.setAttribute('role','status');root.append(heading,node('p',t('favorites.private_notice')),count,refreshButton,status);if(tableLayout){const wrap=node('div'),table=node('table'),head=node('thead'),row=node('tr');wrap.className='table-wrap';for(const key of ['ui.maker_287f4955','ui.model_5e2c614c','ui.finish_a6c7a84b','ui.year_89f68325','ui.serial_8ea09493'])row.append(node('th',t(key)));head.append(row);table.append(head,list);wrap.append(table);root.append(wrap)}else root.append(list);root.append(previous,next);
  let identity=favoriteIdentity(state()),epoch=0,history=[null],nextAfter=null,total=null,notice='',loading=false;
  const eligible=()=>favoriteEligible(state())&&auth()?.signedIn!==false;
  function clear(){epoch++;history=[null];nextAfter=total=null;notice='';loading=false;list.replaceChildren();count.textContent=status.textContent='';root.hidden=true;identity=favoriteIdentity(state())}
  function render(){if(identity!==favoriteIdentity(state())||!eligible())clear();root.hidden=!eligible();status.textContent=notice;count.textContent=total===null?'':t('favorites.count',{count:total});refreshButton.disabled=busy()||loading||!eligible();previous.disabled=busy()||loading||!eligible()||history.length<2;next.disabled=busy()||loading||!eligible()||nextAfter===null}
  async function load(after=null,path=[null]){
    if(!eligible())return;const owner=favoriteIdentity(state()),current=++epoch;list.replaceChildren();nextAfter=total=null;loading=true;notice=t('cloud.working');render();
    try{
      const data=await favoriteRequest(auth(),'?'+new URLSearchParams({...after?{after}:{},limit:'25'}));
      if(current!==epoch||owner!==favoriteIdentity(state())||!eligible())return;
      if(!favoriteExact(data,['items','total','next_after'])||!Array.isArray(data.items)||data.items.length>25||!favoriteCount(data.total)||!(data.next_after===null||favoriteId(data.next_after)))throw Error('Invalid favorites page');
      for(const [index,row] of data.items.entries())if(!favoriteExact(row,['id',...favoriteFields,'photo'])||!favoriteId(row.id)||row.photo!==null||favoriteFields.some(key=>!favoriteText(row[key]))||after!==null&&BigInt(row.id)>=BigInt(after)||index>0&&BigInt(data.items[index-1].id)<=BigInt(row.id))throw Error('Invalid favorite guitar');
      if(data.next_after!==null&&(!data.items.length||data.items.at(-1).id!==data.next_after))throw Error('Invalid favorites cursor');
      history=[...path];nextAfter=data.next_after;total=data.total;
      for(const row of data.items){const item=node(tableLayout?'tr':'li'),link=node('a',[row.manufacturer,row.model].filter(Boolean).join(' ')||t('favorites.guitar',{id:row.id}));item.dataset.favoriteId=row.id;link.href=guitarHref(row.id);if(onNavigate)link.onclick=event=>{if(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(row.id)};if(tableLayout){const first=node('td');link.textContent=row.manufacturer||'—';first.append(link);item.append(first);for(const value of [row.model,row.finish,row.year,row.serial_number])item.append(node('td',value??'—'))}else item.append(link,node('p',[row.year,row.finish,row.serial_number].filter(Boolean).join(' · ')));list.append(item)}
      notice=data.items.length?'':t('favorites.empty');
    }catch(error){if(current!==epoch||owner!==favoriteIdentity(state())||!eligible())return;list.replaceChildren();total=nextAfter=null;history=[null];notice=t(favoriteError(error))}
    finally{if(current===epoch){loading=false;render()}}
  }
  const action=fn=>{if(busy()||loading||!eligible())return;return work(fn)};
  const refresh=()=>load();refreshButton.onclick=()=>action(refresh);
  previous.onclick=()=>{if(history.length<2)return;const path=history.slice(0,-1);return action(()=>load(path.at(-1),path))};
  next.onclick=()=>{if(nextAfter===null)return;const after=nextAfter;return action(()=>load(after,[...history,after]))};
  globalThis.addEventListener('popstate',()=>{clear();render()});globalThis.addEventListener('pagehide',clear);render();return {render,clear,refresh};
}

// The public catalog renders only this visitor's own state, never a public
// favorites list/count. Display and writes stay separate from public GET data.
export function createFavoriteControl({auth,state,root,document=globalThis.document,t,canWrite=()=>true}){
  const node=(tag,id)=>{const n=document.createElement(tag);n.id=id;return n};
  const toggle=node('button','favoriteToggle'),refreshButton=node('button','favoriteRefresh'),status=node('p','favoriteStatus'),account=node('a','favoriteAccount'),help=node('p','favoritePrivateNotice');
  toggle.type=refreshButton.type='button';status.setAttribute('role','status');account.href='/account#selfFavorites';root.append(toggle,refreshButton,account,help,status);
  let id=null,value=null,epoch=0,loading=false,mutating=false,uncertain=false,notice='',identity=favoriteIdentity(state());
  const eligible=()=>favoriteEligible(state())&&auth()?.signedIn===true;
  function clear(){epoch++;id=null;value=null;loading=mutating=uncertain=false;notice='';root.hidden=true;toggle.hidden=refreshButton.hidden=account.hidden=true;toggle.textContent=status.textContent='';toggle.setAttribute('aria-pressed','false');identity=favoriteIdentity(state())}
  function render(){
    if(identity!==favoriteIdentity(state())||!eligible()&&value!==null)clear();root.hidden=!id;
    toggle.hidden=refreshButton.hidden=!eligible();account.hidden=eligible();account.textContent=t('favorites.account');help.textContent=t('favorites.private_notice');
    toggle.textContent=t(value===true?'favorites.remove':'favorites.add');toggle.setAttribute('aria-pressed',String(value===true));toggle.disabled=!id||!eligible()||loading||mutating||uncertain||value===null||!canWrite();refreshButton.textContent=t('action.refresh');refreshButton.disabled=!id||!eligible()||loading||mutating;
    status.textContent=uncertain?t('favorites.uncertain'):notice?t(notice):eligible()&&!canWrite()?t('favorites.restricted'):'';
  }
  const current=(generation,owner,target)=>generation===epoch&&owner===favoriteIdentity(state())&&eligible()&&target===id;
  async function refresh(){
    if(!id||!eligible()||loading||mutating)return;const generation=++epoch,owner=favoriteIdentity(state()),target=id;value=null;loading=true;notice='cloud.working';render();
    try{const data=await favoriteRequest(auth(),'/'+target);if(!current(generation,owner,target))return;value=favoriteResult(data,target);uncertain=false;notice=''}
    catch(error){if(!current(generation,owner,target))return;value=null;notice=favoriteError(error)}
    finally{if(current(generation,owner,target)){loading=false;render()}}
  }
  async function change(){
    if(!id||!eligible()||loading||mutating||uncertain||value===null||!canWrite())return;
    const generation=++epoch,owner=favoriteIdentity(state()),target=id,desired=!value;mutating=true;notice='cloud.working';render();
    try{const data=await favoriteRequest(auth(),'/'+target,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({favorite:desired})});if(!current(generation,owner,target))return;const result=favoriteResult(data,target);if(result!==desired)throw Error('Unexpected favorite result');value=result;notice=result?'favorites.added':'favorites.removed'}
    catch(error){if(!current(generation,owner,target))return;value=null;if([400,401,403,404,409,422].includes(error.status))notice=favoriteError(error);else{uncertain=true;notice=''}}
    finally{if(current(generation,owner,target)){mutating=false;render()}}
  }
  async function select(target){clear();if(!favoriteId(target))return;id=target;render();await refresh()}
  toggle.onclick=change;refreshButton.onclick=refresh;clear();return {clear,render,select,refresh};
}
