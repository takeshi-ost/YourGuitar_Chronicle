import {catalogIndividualId} from './cloud-account-applications.js';

const identityFields=['manufacturer','model','year','serial_number'];
const storageKey='ygc.identity-correction.uncertain.v1';
const boundedText=(value,limit,multiline=false)=>value===null||typeof value==='string'&&[...value].length<=limit&&!/[\uD800-\uDFFF]/u.test(value)&&!(multiline?/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/:/[\x00-\x1f\x7f]/).test(value);
const fieldText=(value,key)=>boundedText(value,key==='year'?40:200);
const object=value=>Boolean(value&&typeof value==='object'&&!Array.isArray(value));
const revision=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);

// This author-only entrance is independent of Current Owner. It never edits a
// Listing, media, ownership, or Verification, and never reads private duplicates.
export function createIdentityCorrections({auth,state,busy,work,updated=async()=>{}}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id='')=>{const n=node('button',t(key),id);n.type='button';return n};
  const root=document.getElementById('selfIdentityCorrections'),status=node('p','','identityStatus'),list=node('ul','','identityListings'),refreshButton=button('action.refresh','identityRefresh'),more=button('claims.older','identityMore');
  status.setAttribute('role','status');root.append(node('h2',t('identity.heading')),node('p',t('identity.author_help')),refreshButton,status,list,more);
  const dialog=node('dialog','','identityDialog'),title=node('h2',t('identity.edit_listing'),'identityTitle'),guitar=node('p','','identityGuitar'),listingDate=node('p','','identityListingDate'),message=node('p','','identityMessage');
  dialog.setAttribute('aria-labelledby',title.id);message.setAttribute('role','status');
  const create=button('identity.create','identityCreate'),form=node('form','','identityForm'),fields=node('fieldset','','identityFields'),inputs={};
  const label=(input,key)=>{const n=node('label',t(key));n.htmlFor=input.id;return n};
  for(const key of identityFields){const input=node('input','','identity_'+key);input.type='text';input.maxLength=key==='year'?80:400;input.required=['manufacturer','serial_number'].includes(key);fields.append(label(input,'applications.'+key),input);inputs[key]=input}
  const reason=node('textarea','','identityReason');reason.maxLength=4000;fields.append(label(reason,'identity.reason'),reason);
  const review=node('button',t('identity.review'),'identityReview');review.type='submit';form.append(fields,review);
  const preview=node('section','','identityPreview'),confirm=button('identity.confirm','identityConfirm'),history=node('ul','','identityHistory'),historyMore=button('claims.older','identityHistoryMore'),reload=button('action.refresh','identityReload'),check=button('identity.check_submission','identityCheckSubmission'),acknowledge=button('identity.acknowledge','identityAcknowledge'),close=button('action.close','identityClose');
  dialog.append(title,guitar,listingDate,node('p',t('identity.immutable'),'identityImmutable'),node('p',t('identity.immediate'),'identityImmediate'),create,form,preview,confirm,message,check,acknowledge,node('h3',t('identity.history')),node('p',t('identity.private_history')),history,historyMore,reload,close);document.body.append(dialog);
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  const account=()=>state()?.user?.app_user_id??null;
  const eligible=()=>Boolean(account()&&state()?.identity?.email_verified===true&&(!state()?.user?.status||state().user.status==='active'));
  let renderedIdentity=identity(),activeAccount=null,accountEpoch=0,listEpoch=0,dialogEpoch=0,detailEpoch=0,navigationEpoch=0,inputEpoch=0;
  let rows=[],nextAfter=null,listWrite=null,notice='',selected=null,detail=null,historyRows=[],historyAfter=null,editing=false,pending=null,checked=false;
  // Only account and Listing IDs are persisted, before any POST. No identity,
  // reason, draft, response or revision is stored. A marker never grants access.
  const uncertain=new Set();
  function persist(){
    try{if(uncertain.size){globalThis.sessionStorage.setItem(storageKey,JSON.stringify({account:activeAccount,ids:[...uncertain]}))}else globalThis.sessionStorage.removeItem(storageKey);return true}catch{return false}
  }
  function restoreMarkers(){
    if(!eligible()||activeAccount===account())return;
    activeAccount=account();uncertain.clear();
    try{const raw=globalThis.sessionStorage.getItem(storageKey);if(!raw)return;const saved=JSON.parse(raw);if(!object(saved)||saved.account!==activeAccount||!Array.isArray(saved.ids)||saved.ids.length>100||saved.ids.some(id=>!catalogIndividualId(id)))throw Error('Invalid retry marker');for(const id of saved.ids)uncertain.add(id)}catch{try{globalThis.sessionStorage.removeItem(storageKey)}catch{}}
  }
  const context=()=>({account:accountEpoch,actor:identity(),editor:dialogEpoch,navigation:navigationEpoch,id:selected});
  const sameAccount=c=>c.account===accountEpoch&&c.actor===identity()&&eligible();
  const sameDialog=c=>sameAccount(c)&&c.editor===dialogEpoch&&c.navigation===navigationEpoch&&c.id===selected&&dialog.open;
  const allowed=()=>eligible()&&detail?.can_write===true&&listWrite!==false&&detail.listing.id===selected;
  const unknown=()=>selected!==null&&uncertain.has(selected);
  const summary=g=>g?['#'+g.id,...identityFields.map(key=>g[key])].filter(v=>v!==null&&v!=='').join(' · '):'';
  const display=value=>value===null?t('identity.empty_value'):value;
  function individual(value,id=null){
    if(!object(value)||!catalogIndividualId(value.id)||id!==null&&value.id!==id||identityFields.some(key=>!fieldText(value[key],key)))throw Error('Invalid identity');
    return Object.freeze(Object.fromEntries(['id',...identityFields].map(key=>[key,value[key]])));
  }
  function historyRow(value,id,guitarId){
    if(!object(value)||!catalogIndividualId(value.id)||value.target_claim_id!==id||value.individual_id!==guitarId||!boundedText(value.body,2000,true)||!boundedText(value.occurred_at,40)||!boundedText(value.created_at,40)||!['active','inactive'].includes(value.status)||!['positive','negative','unverified'].includes(value.verification_status)||!Array.isArray(value.changes)||!value.changes.length||value.changes.length>4)throw Error('Invalid correction');
    const changes=value.changes.map(change=>{if(!object(change)||!identityFields.includes(change.field_name)||!fieldText(change.old_value,change.field_name)||!fieldText(change.new_value,change.field_name)||change.old_value===change.new_value)throw Error('Invalid change');return Object.freeze({field_name:change.field_name,old_value:change.old_value,new_value:change.new_value})});
    if(new Set(changes.map(change=>change.field_name)).size!==changes.length)throw Error('Duplicate change');
    return Object.freeze({id:value.id,target_claim_id:id,individual_id:guitarId,body:value.body,occurred_at:value.occurred_at,created_at:value.created_at,status:value.status,verification_status:value.verification_status,changes:Object.freeze(changes)});
  }
  function cursor(data,items,after=null){
    if(!(data.next_after===null||catalogIndividualId(data.next_after))||new Set(items.map(row=>row.id)).size!==items.length||data.next_after!==null&&(!items.length||items.at(-1).id!==data.next_after)||items.some((row,index)=>after!==null&&BigInt(row.id)>=BigInt(after)||index>0&&BigInt(items[index-1].id)<=BigInt(row.id)))throw Error('Invalid correction cursor');
    return data.next_after;
  }
  function listings(data,after=null){
    if(!object(data)||!Array.isArray(data.items)||data.items.length>50||typeof data.can_write!=='boolean')throw Error('Invalid Listings');
    const items=data.items.map(row=>{if(!object(row)||!catalogIndividualId(row.id)||!boundedText(row.occurred_at,40))throw Error('Invalid Listing');return Object.freeze({id:row.id,individual:individual(row.individual),occurred_at:row.occurred_at})});
    return {items,next_after:cursor(data,items,after),can_write:data.can_write};
  }
  function details(data,id,after=null){
    if(!object(data)||!object(data.listing)||data.listing.id!==id||!catalogIndividualId(data.listing.individual_id)||!boundedText(data.listing.occurred_at,40)||!revision(data.revision)||typeof data.can_write!=='boolean'||!Array.isArray(data.items)||data.items.length>50)throw Error('Invalid correction detail');
    const guitar=individual(data.individual,data.listing.individual_id),items=data.items.map(row=>historyRow(row,id,guitar.id));
    return Object.freeze({listing:Object.freeze({id,individual_id:guitar.id,occurred_at:data.listing.occurred_at}),individual:guitar,items:Object.freeze(items),next_after:cursor(data,items,after),revision:data.revision,can_write:data.can_write});
  }
  async function request(id=null,options={},after=null){
    const url='/api/auth/identity-corrections'+(id?'/'+id:'')+(after?'?after='+after+'&limit=25':'');
    const response=await auth().authorizedFetch(url,{cache:'no-store',credentials:'omit',redirect:'error',...options,headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',...options.headers}},true);
    if(!response.ok){const value=await response.json().catch(()=>({}));throw Object.assign(Error('Identity request failed'),{status:response.status,code:(value?.detail?.code||value?.code)==='service_restricted'?'service_restricted':null})}
    return response.json();
  }
  const readDetail=(id,after=null)=>request(id,{},after).then(data=>details(data,id,after));
  function errorText(error){return t(error.code==='service_restricted'?'applications.service_restricted':[401,403].includes(error.status)?'self_profile.restricted':error.status===404?'identity.unavailable':error.status===409?'identity.conflict':[400,422].includes(error.status)?'identity.invalid':'identity.failed')}
  function resetDialog(){dialogEpoch++;detailEpoch++;inputEpoch++;selected=null;detail=null;historyRows=[];historyAfter=null;editing=false;pending=null;checked=false;for(const input of Object.values(inputs))input.value='';reason.value='';guitar.textContent=listingDate.textContent=message.textContent='';preview.replaceChildren();history.replaceChildren()}
  function purge(){listEpoch++;rows=[];nextAfter=null;listWrite=null;list.replaceChildren();globalThis.YGCOverlays.close(dialog);resetDialog()}
  function clear(){accountEpoch++;if(activeAccount!==null){uncertain.clear();persist()}activeAccount=null;purge();notice='';renderedIdentity=identity()}
  dialog.addEventListener('ygc:closed',()=>{resetDialog();render()});close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function renderList(){
    list.replaceChildren();const c=context();
    for(const row of rows){const li=node('li'),text=node('p',summary(row.individual)+'\n'+t('identity.listing_label',{id:row.id})+' · '+(row.occurred_at||t('identity.empty_value'))),link=node('a',t('catalog.view_guitar')),edit=button('identity.edit_listing');link.href='/guitars/'+row.individual.id;
      edit.onclick=()=>{if(sameAccount(c)&&c.navigation===navigationEpoch)return openListing(row.id)};li.append(text,link,edit);list.append(li)}
  }
  function renderHistory(){
    history.replaceChildren();for(const row of historyRows){const li=node('li'),text=node('p','#'+row.id+' · '+t('claims.'+row.status)+' · '+t('chronicle.'+row.verification_status)+'\n'+t('identity.listing_date')+': '+display(row.occurred_at)+'\n'+t('claims.created')+': '+display(row.created_at)+'\n'+row.changes.map(change=>t('applications.'+change.field_name)+': '+display(change.old_value)+' → '+display(change.new_value)).join('\n')+(row.body?'\n'+t('identity.reason')+': '+row.body:''));li.append(text);history.append(li)}
    if(!historyRows.length)history.append(node('li',t('identity.history_empty')));
  }
  function applyDetail(value,{append=false}={}){
    const changed=detail&&detail.revision!==value.revision;
    if(changed){pending=null;checked=false;preview.replaceChildren()}
    detail=value;guitar.textContent=summary(value.individual);listingDate.textContent=t('identity.listing_label',{id:value.listing.id})+' · '+t('identity.listing_date')+': '+display(value.listing.occurred_at);
    historyRows=append?[...historyRows,...value.items]:[...value.items];historyAfter=value.next_after;renderHistory();return changed;
  }
  function render(){
    if(renderedIdentity!==identity())clear();restoreMarkers();root.hidden=!eligible();status.textContent=[notice,eligible()&&uncertain.size?t('identity.uncertain'):'' ].filter(Boolean).join(' ');
    refreshButton.disabled=busy()||!eligible();more.hidden=nextAfter===null;more.disabled=busy()||!eligible();for(const n of list.querySelectorAll('button'))n.disabled=busy()||!eligible();
    create.hidden=editing;create.disabled=busy()||!allowed()||unknown();form.hidden=!editing;fields.disabled=busy()||!allowed()||unknown();review.disabled=busy()||!allowed()||unknown()||!editing;
    preview.hidden=!pending;confirm.hidden=!pending;confirm.disabled=busy()||!allowed()||unknown();check.hidden=!unknown();check.disabled=busy()||!eligible();acknowledge.hidden=!unknown()||!checked;acknowledge.disabled=busy()||!eligible();historyMore.hidden=historyAfter===null;historyMore.disabled=busy()||!detail||!eligible();reload.disabled=busy()||!eligible()||!selected;
  }
  function action(fn){if(busy()||!eligible())return;return work(async()=>{try{return await fn()}finally{render()}})}
  async function refresh(after=null){
    if(!eligible())return;const c=context(),read=++listEpoch;notice=t('cloud.working');render();
    try{const value=listings(await request(null,{},after),after);if(!sameAccount(c)||read!==listEpoch)return;rows=value.items;nextAfter=value.next_after;listWrite=value.can_write;notice=t(rows.length?'identity.author_help':'identity.empty')+(!listWrite?' '+t('applications.read_only'):'');renderList();if(!listWrite)pending=null}
    catch(error){if(!sameAccount(c)||read!==listEpoch)return;rows=[];nextAfter=null;listWrite=null;list.replaceChildren();if(([401,403,404].includes(error.status)||error.code==='service_restricted')&&c.editor===dialogEpoch&&c.navigation===navigationEpoch)purge();notice=errorText(error)}render();
  }
  async function handleError(error,c){
    if(!sameDialog(c))return;pending=null;checked=false;message.textContent=errorText(error);
    if(error.code==='service_restricted'){
      // A service-mode write denial is not a sign-out. Retain private content
      // only after a fresh read proves access; never carry an old confirmation.
      try{const value=await readDetail(c.id);if(!sameDialog(c))return;applyDetail(value);message.textContent=errorText(error)}catch{if(sameDialog(c)){purge();notice=errorText(error)}}
    }else if([401,403,404].includes(error.status)){purge();notice=errorText(error)}
  }
  function openListing(id){
    if(busy()||!eligible()||dialog.open||!catalogIndividualId(id))return;resetDialog();selected=id;globalThis.YGCOverlays.open(dialog);message.textContent=t('cloud.working');render();const c=context(),read=++detailEpoch;
    return action(async()=>{try{const value=await readDetail(id);if(!sameDialog(c)||read!==detailEpoch)return;applyDetail(value);message.textContent=unknown()?t('identity.uncertain'):value.can_write?'':t('identity.write_unavailable')}catch(error){await handleError(error,c)}});
  }
  create.onclick=()=>{if(busy()||!dialog.open||!allowed()||unknown())return;editing=true;pending=null;checked=false;for(const key of identityFields)inputs[key].value=detail.individual[key]??'';reason.value='';message.textContent='';render()};
  function values(){
    const value={};for(const key of identityFields){value[key]=inputs[key].value.trim()||null;if(!fieldText(value[key],key))throw {status:400}}
    value.reason=reason.value.trim()||null;if(!value.manufacturer||!value.serial_number||!boundedText(value.reason,2000,true))throw {status:400};return value;
  }
  const changedFields=(current,proposed)=>identityFields.filter(key=>current[key]!==proposed[key]);
  for(const input of [...Object.values(inputs),reason])input.oninput=()=>{inputEpoch++;pending=null;preview.replaceChildren();render()};
  form.onsubmit=event=>{
    event.preventDefault();if(busy()||!dialog.open||!editing||!allowed()||unknown())return;const c=context(),draftEpoch=inputEpoch;pending=null;checked=false;
    return action(async()=>{try{const proposed=values(),fresh=await readDetail(c.id);if(!sameDialog(c)||draftEpoch!==inputEpoch)return;const changed=applyDetail(fresh);if(!allowed()){message.textContent=t('identity.write_unavailable');return}if(changed){message.textContent=t('identity.conflict');return}if(!changedFields(fresh.individual,proposed).length)throw {status:400};pending=Object.freeze({id:c.id,revision:fresh.revision,old:fresh.individual,listingDate:fresh.listing.occurred_at,...proposed});
      preview.replaceChildren(node('h3',t('identity.preview')),node('p',t('identity.preview_help')),...identityFields.map(key=>node('p',t('applications.'+key)+': '+display(fresh.individual[key])+' → '+display(proposed[key]))),node('p',t('identity.reason')+': '+display(proposed.reason)));message.textContent=t('identity.confirm_help');
    }catch(error){await handleError(error,c)}});
  };
  function result(value,operation){
    if(!object(value))throw Error('Invalid result');const fresh=details(value.detail,operation.id),row=historyRow(value.correction,operation.id,operation.old.id),changes=changedFields(operation.old,operation);
    if(row.status!=='active'||row.verification_status!=='positive'||operation.listingDate!==null&&row.occurred_at!==operation.listingDate||row.body!==operation.reason||row.changes.length!==changes.length||changes.some(key=>!row.changes.some(change=>change.field_name===key&&change.old_value===operation.old[key]&&change.new_value===operation[key]))||fresh.revision===operation.revision||fresh.listing.occurred_at!==operation.listingDate||!fresh.items.some(item=>JSON.stringify(item)===JSON.stringify(row)))throw Error('Unexpected correction result');return fresh;
  }
  confirm.onclick=()=>{
    if(busy()||!dialog.open||!editing||!allowed()||unknown()||!pending)return;const operation=pending,c=context(),draftEpoch=inputEpoch;pending=null;preview.replaceChildren();
    return action(async()=>{let attempted=false,completed=false;
      try{const fresh=await readDetail(operation.id);if(!sameDialog(c)||draftEpoch!==inputEpoch)return;applyDetail(fresh);if(!allowed()){message.textContent=t('identity.write_unavailable');return}if(fresh.revision!==operation.revision||fresh.listing.occurred_at!==operation.listingDate||identityFields.some(key=>fresh.individual[key]!==operation.old[key])){message.textContent=t('identity.conflict');return}
        if(uncertain.size>=100){message.textContent=t('identity.storage_unavailable');return}uncertain.add(operation.id);if(!persist()){uncertain.delete(operation.id);message.textContent=t('identity.storage_unavailable');return}attempted=true;
        const payload=Object.fromEntries(['revision',...identityFields,'reason'].map(key=>[key,operation[key]]));
        const value=await request(operation.id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const freshResult=result(value,operation);if(!sameAccount(c))return;
        completed=true;uncertain.delete(operation.id);persist();if(sameDialog(c)){applyDetail(freshResult);editing=false;for(const input of Object.values(inputs))input.value='';reason.value='';message.textContent=t('identity.saved')}
        await refresh();if(sameAccount(c))await updated();
      }catch(error){if(!sameAccount(c))return;if(completed){notice=errorText(error);return}
        const definite=[400,401,403,404,409,422].includes(error.status)||error.code==='service_restricted';
        if(attempted&&!definite){if(sameDialog(c)){checked=false;message.textContent=t('identity.uncertain')}notice='';await refresh()}
        else{if(attempted){uncertain.delete(operation.id);persist()}await handleError(error,c)}
      }
    });
  };
  async function reloadCurrent({after=null,recover=false}={}){
    if(!selected||!dialog.open)return;const c=context(),read=++detailEpoch;pending=null;checked=false;preview.replaceChildren();
    try{const fresh=await readDetail(c.id,after);if(!sameDialog(c)||read!==detailEpoch)return;const changed=detail&&fresh.revision!==detail.revision;
      if(after&&changed){message.textContent=t('identity.conflict');historyAfter=null;return}
      if(after&&fresh.items.some(row=>historyRows.some(old=>old.id===row.id)))throw Error('Repeated correction page');
      applyDetail(fresh,{append:Boolean(after)});if(recover){checked=true;message.textContent=t('identity.checked')}else message.textContent=unknown()?t('identity.uncertain'):t('identity.review_again');
    }catch(error){await handleError(error,c)}
  }
  reload.onclick=()=>action(()=>reloadCurrent());historyMore.onclick=()=>action(()=>historyAfter?reloadCurrent({after:historyAfter}):undefined);
  check.onclick=()=>{if(!unknown())return;return action(()=>reloadCurrent({recover:true}))};
  acknowledge.onclick=()=>{if(busy()||!dialog.open||!eligible()||!checked||!unknown()||!detail)return;uncertain.delete(selected);persist();checked=false;pending=null;editing=false;preview.replaceChildren();for(const input of Object.values(inputs))input.value='';reason.value='';message.textContent=t('identity.review_again');render()};
  refreshButton.onclick=()=>action(()=>refresh());more.onclick=()=>action(()=>nextAfter?refresh(nextAfter):undefined);
  globalThis.addEventListener('popstate',()=>{navigationEpoch++;globalThis.YGCOverlays.close(dialog);resetDialog();renderList();render()});
  globalThis.addEventListener('pagehide',()=>{navigationEpoch++;purge()});
  globalThis.addEventListener('pageshow',()=>{if(eligible())refresh()});
  globalThis.addEventListener('focus',()=>{if(!busy()&&eligible()){refresh();if(dialog.open)reloadCurrent()}});
  render();return {render,clear,refresh,openListing};
}
