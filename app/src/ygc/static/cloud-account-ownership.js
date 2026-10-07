import {catalogIndividualId} from './cloud-account-applications.js';

export function readOwnershipIntent(search){
  const values=new URLSearchParams(search).getAll('ownership');
  return values.length===0?null:values.length===1?(catalogIndividualId(values[0])||''):'';
}

// Private participant inbox and current-owner operations. No public directory,
// evidence-photo endpoint, or Verification action is used by this component.
export function createOwnership({auth,state,busy,work,updated=async()=>{}}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id='')=>{const n=node('button',t(key),id);n.type='button';return n};
  const label=(input,key)=>{const n=node('label',t(key));n.htmlFor=input.id;return n};
  const root=document.getElementById('selfOwnership'),intentRoot=document.getElementById('catalogOwnershipIntent');
  const inboxStatus=node('p','','ownershipInboxStatus'),inbox=node('ul','','ownershipInbox'),refreshButton=button('action.refresh','ownershipRefresh'),inboxMore=button('claims.older','ownershipInboxMore');
  inboxStatus.setAttribute('role','status');root.append(node('h2',t('ownership.inbox')),node('p',t('ownership.inbox_help')),refreshButton,inboxStatus,inbox,inboxMore);
  const intentDetail=node('p','','ownershipIntentDetail'),intentStatus=node('p','','ownershipIntentStatus'),start=button('ownership.manage','ownershipStart'),history=node('ul','','ownershipHistory'),historyMore=button('claims.older','ownershipHistoryMore'),intentRefresh=button('action.refresh','ownershipIntentRefresh');
  intentStatus.setAttribute('role','status');intentRoot.append(node('h2',t('ownership.heading')),intentDetail,intentStatus,start,intentRefresh,history,historyMore);
  const dialog=node('dialog','','ownershipDialog'),title=node('h2','','ownershipTitle'),detail=node('p','','ownershipDetail'),saved=node('p','','ownershipSaved'),evidence=node('p','','ownershipEvidence'),message=node('p','','ownershipMessage');
  dialog.setAttribute('aria-labelledby','ownershipTitle');message.setAttribute('role','status');
  const form=node('form','','ownershipForm'),fields=node('fieldset'),kind=node('select','','ownershipKind');
  for(const value of ['transfer','release']){const option=node('option',t('ownership.'+value));option.value=value;kind.append(option)}kind.value='transfer';
  const transferFields=node('div','','ownershipTransferFields'),query=node('input','','ownershipSearch'),search=button('ownership.search','ownershipSearchButton'),candidates=node('ul','','ownershipCandidates'),searchMore=button('users.next','ownershipSearchMore'),selectedText=node('p','','ownershipSelected');
  query.type='search';query.maxLength=120;query.autocomplete='off';transferFields.append(label(query,'ownership.search_label'),query,search,candidates,searchMore,selectedText,node('p',t('ownership.transfer_help')));
  const releaseFields=node('div','','ownershipReleaseFields'),date=node('input','','ownershipDate'),body=node('textarea','','ownershipBody');date.type='date';body.maxLength=2000;
  releaseFields.append(label(date,'ownership.release_date'),date,label(body,'claims.body'),body,node('p',t('ownership.release_help')));
  const review=button('ownership.review','ownershipReview'),confirm=button('ownership.confirm','ownershipConfirm'),accept=button('ownership.accept','ownershipAccept'),decline=button('ownership.decline','ownershipDecline'),cancel=button('ownership.cancel','ownershipCancel'),check=button('ownership.check','ownershipCheck'),acknowledge=button('ownership.acknowledge','ownershipAcknowledge'),reload=button('action.refresh','ownershipReload'),close=button('action.close','ownershipClose');
  fields.append(label(kind,'ownership.kind'),kind,transferFields,releaseFields);form.append(fields,review);dialog.append(title,detail,saved,evidence,form,accept,decline,cancel,message,confirm,check,acknowledge,reload,close);document.body.append(dialog);
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true&&(!state().user.status||state().user.status==='active'));
  const actorId=()=>canonicalViewer;
  const revision=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  const nullableText=value=>value===null||typeof value==='string';
  let canonicalViewer=null,renderedIdentity=identity(),accountEpoch=0,intentEpoch=0,inboxEpoch=0,viewEpoch=0,dialogEpoch=0,searchEpoch=0,navigationEpoch=0;
  let inboxNotice='',guitarId=null,view=null,viewState='',inboxRows=[],inboxAfter=null,historyAfter=null,selected=null,transfer=null,candidate=null,nextOffset=null,searchTerm='',pending=null,checked=false;
  // Uncertain mutations survive dialog dismissal and same-account navigation.
  // They are never persisted to browser storage or shared with another account.
  const uncertain=new Map();
  const summary=g=>g?['#'+g.id,g.manufacturer,g.model,g.finish,g.year,g.serial_number].filter(v=>v!==null&&v!==undefined&&v!=='').join(' · '):'';
  const today=()=>{const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')};
  const context=()=>({account:accountEpoch,actor:identity(),intent:intentEpoch,editor:dialogEpoch,navigation:navigationEpoch,id:selected});
  const sameAccount=c=>c.account===accountEpoch&&c.actor===identity()&&eligible();
  const sameDialog=c=>sameAccount(c)&&c.editor===dialogEpoch&&c.id===selected&&dialog.open;
  const allowed=()=>eligible()&&view?.can_write===true&&view.is_current_owner===true&&view.individual.id===selected;
  const uncertainty=()=>selected?uncertain.get(selected):null;

  function publicGuitar(value,id){
    if(!value||value.id!==id||!catalogIndividualId(value.id)||['manufacturer','model','finish','year','serial_number'].some(key=>!nullableText(value[key])))throw Error('Invalid guitar');
    return Object.freeze(Object.fromEntries(['id','manufacturer','model','finish','year','serial_number'].map(key=>[key,value[key]])));
  }
  function user(value,candidate=false){
    if(!value||!catalogIndividualId(value.id)||!(typeof value.display_name==='string'||!candidate&&value.display_name===null)||!(['user','shop','builder','repairer','organization'].includes(value.account_type)||!candidate&&[null,'source'].includes(value.account_type)))throw Error('Invalid participant');
    return Object.freeze({id:value.id,display_name:value.display_name,account_type:value.account_type});
  }
  function viewer(value){if(!catalogIndividualId(value)||canonicalViewer!==null&&canonicalViewer!==value)throw Error('Invalid viewer');return value}
  function transferRow(row){
    if(!row||!catalogIndividualId(row.id)||!catalogIndividualId(row.individual_id)||row.ownership_kind!=='transfer'||!['pending','accepted','declined','cancelled'].includes(row.state)||!['active','inactive'].includes(row.status)||!['positive','negative','unverified'].includes(row.verification_status)||!revision(row.revision)||typeof row.created_at!=='string'||!nullableText(row.resolved_at)||!nullableText(row.occurred_at))throw Error('Invalid Transfer');
    const viewerId=viewer(row.viewer_user_id),from=user(row.from_user),to=user(row.to_user);if(from.id===to.id||![from.id,to.id].includes(viewerId))throw Error('Invalid participant access');
    let acceptance=null;
    if(row.acceptance!==null){const a=row.acceptance;if(!a||!catalogIndividualId(a.accepted_by_user_id)||!catalogIndividualId(a.current_owner_user_id)||typeof a.accepted_at!=='string'||a.accepted_by_user_id!==to.id||a.current_owner_user_id!==from.id)throw Error('Invalid acceptance');acceptance=Object.freeze({accepted_by_user_id:a.accepted_by_user_id,accepted_at:a.accepted_at,current_owner_user_id:a.current_owner_user_id})}
    if((row.state==='accepted')!==Boolean(acceptance)||acceptance&&acceptance.accepted_at!==row.occurred_at)throw Error('Invalid acceptance state');
    return Object.freeze({viewer_user_id:viewerId,id:row.id,individual_id:row.individual_id,individual:publicGuitar(row.individual,row.individual_id),ownership_kind:'transfer',from_user:from,to_user:to,state:row.state,status:row.status,verification_status:row.verification_status,revision:row.revision,created_at:row.created_at,resolved_at:row.resolved_at,occurred_at:row.occurred_at,acceptance,can_write:row.can_write===true,can_accept:row.can_accept===true,can_decline:row.can_decline===true,can_cancel:row.can_cancel===true});
  }
  function releaseRow(row,id){
    if(!row||!catalogIndividualId(row.id)||row.individual_id!==id||row.ownership_kind!=='release'||!['active','inactive'].includes(row.status)||!['positive','negative','unverified'].includes(row.verification_status)||!nullableText(row.occurred_at)||!nullableText(row.body))throw Error('Invalid Release');
    return Object.freeze({id:row.id,individual_id:id,ownership_kind:'release',status:row.status,verification_status:row.verification_status,occurred_at:row.occurred_at,body:row.body});
  }
  function page(data,id=null){
    if(!data||!Array.isArray(data.items)||data.items.length>50||!(data.next_after===null||catalogIndividualId(data.next_after)))throw Error('Invalid ownership page');
    const viewerId=viewer(data.viewer_user_id),rows=data.items.map(row=>row.ownership_kind==='release'&&id?releaseRow(row,id):transferRow(row));
    if(new Set(rows.map(row=>row.id)).size!==rows.length||rows.some(row=>id&&row.individual_id!==id)||data.next_after!==null&&(!rows.length||rows.at(-1).id!==data.next_after))throw Error('Invalid ownership cursor');
    return {viewer_user_id:viewerId,items:rows,next_after:data.next_after,can_write:data.can_write===true};
  }
  function ownership(data,id){
    const rows=page(data,id);if(!revision(data.revision)||!(data.current_owner_user_id===null||catalogIndividualId(data.current_owner_user_id))||typeof data.is_current_owner!=='boolean'||data.is_current_owner!==(data.current_owner_user_id===rows.viewer_user_id))throw Error('Invalid ownership access');
    return {...rows,individual:publicGuitar(data.individual,id),current_owner_user_id:data.current_owner_user_id,is_current_owner:data.is_current_owner,revision:data.revision,can_transfer:data.can_transfer===true,can_release:data.can_release===true};
  }
  async function request(path,options={}){
    const response=await auth().authorizedFetch('/api/auth/'+path,{cache:'no-store',credentials:'omit',redirect:'error',...options,headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',...options.headers}},true);
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Object.assign(Error('Ownership request failed'),{status:response.status,code:data.detail?.code||data.code})}return response.json();
  }
  const readView=(id,after=null)=>request('guitars/'+id+'/ownership'+(after?'?after='+after:'')).then(data=>ownership(data,id));
  const readTransfer=id=>request('transfers/'+id).then(transferRow);
  function errorText(err){return t(err.code==='service_restricted'?'applications.service_restricted':[401,403].includes(err.status)?'self_profile.restricted':err.status===409?'ownership.conflict':[400,422].includes(err.status)?'ownership.invalid':'ownership.failed')}
  function resetDialog(){dialogEpoch++;searchEpoch++;selected=null;transfer=null;candidate=null;pending=null;checked=false;nextOffset=null;searchTerm='';query.value=body.value=date.value='';candidates.replaceChildren();selectedText.textContent=detail.textContent=saved.textContent=evidence.textContent=message.textContent='';kind.value='transfer'}
  function purge(){inboxEpoch++;viewEpoch++;inboxRows=[];inboxAfter=historyAfter=null;view=null;inbox.replaceChildren();history.replaceChildren();globalThis.YGCOverlays.close(dialog);resetDialog()}
  function clear(){renderedIdentity=identity();accountEpoch++;intentEpoch++;uncertain.clear();canonicalViewer=null;purge();inboxNotice='';viewState='';renderedIdentity=identity()}
  dialog.addEventListener('ygc:closed',()=>{resetDialog();render()});close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function transferSummary(row){return '#'+row.id+' · '+(row.from_user.display_name??t('ownership.unavailable_user'))+' (#'+row.from_user.id+') → '+(row.to_user.display_name??t('ownership.unavailable_user'))+' (#'+row.to_user.id+')\n'+t('ownership.agreement')+': '+t('ownership.'+row.state)+' · '+t('ownership.verification')+': '+t('chronicle.'+row.verification_status)}
  function showTransfer(row){
    canonicalViewer=row.viewer_user_id;transfer=row;selected=row.individual_id;title.textContent=t('ownership.review_transfer');detail.textContent=summary(row.individual);saved.textContent=transferSummary(row)+'\n'+t('claims.created')+': '+row.created_at+(row.resolved_at?'\n'+t('ownership.resolved')+': '+row.resolved_at:'');
    evidence.textContent=row.acceptance?t('ownership.acceptance')+'\n'+t('ownership.accepted_by')+': #'+row.acceptance.accepted_by_user_id+'\n'+t('ownership.accepted_at')+': '+row.acceptance.accepted_at+'\n'+t('ownership.owner_at_acceptance')+': #'+row.acceptance.current_owner_user_id+'\n'+t('ownership.independent'):t('ownership.no_acceptance');
  }
  function renderRows(container,rows){
    container.replaceChildren();const account=accountEpoch,actor=identity(),navigation=navigationEpoch;
    for(const row of rows){const li=node('li'),text=node('p',row.ownership_kind==='transfer'?summary(row.individual)+'\n'+transferSummary(row):'#'+row.id+' · '+t('ownership.release')+' · '+(row.occurred_at||'')+' · '+t('chronicle.'+row.verification_status)+(row.body?'\n'+row.body:''));li.append(text);
      if(row.ownership_kind==='transfer'){const open=button('ownership.review_transfer');open.onclick=()=>{if(account===accountEpoch&&actor===identity()&&navigation===navigationEpoch)return openTransfer(row.id)};li.append(open)}container.append(li)}
  }
  function render(){
    if(renderedIdentity!==identity())clear();root.hidden=!eligible();inboxStatus.textContent=[inboxNotice,eligible()&&uncertain.size?t('ownership.uncertain'):''].filter(Boolean).join(' ');intentRoot.hidden=guitarId===null;intentDetail.textContent=summary(view?.individual)+(view?'\n'+t('ownership.current_owner',{owner:view.current_owner_user_id?'#'+view.current_owner_user_id:t('ownership.unknown_owner')}):'');
    const hint=viewState==='loading'?'cloud.working':guitarId===''?'catalog.acquire_invalid':!state()?.user?'catalog.acquire_sign_in':!eligible()?'catalog.acquire_verify':!view?'ownership.unavailable':!view.is_current_owner?'ownership.participant_only':view.can_write?'ownership.ready':'applications.read_only';intentStatus.textContent=t(hint)+(guitarId&&uncertain.has(guitarId)?' '+t('ownership.uncertain'):'');
    start.disabled=busy()||!eligible()||!view||!view.is_current_owner&&!uncertain.has(guitarId);intentRefresh.disabled=busy()||!eligible()||!catalogIndividualId(guitarId);refreshButton.disabled=busy()||!eligible();inboxMore.hidden=inboxAfter===null;historyMore.hidden=historyAfter===null;inboxMore.disabled=historyMore.disabled=busy()||!eligible();
    for(const n of [...inbox.querySelectorAll('button'),...history.querySelectorAll('button')])n.disabled=busy()||!eligible();
    form.hidden=Boolean(transfer);fields.disabled=busy()||!allowed()||Boolean(uncertainty());transferFields.hidden=kind.value!=='transfer';releaseFields.hidden=kind.value!=='release';date.required=kind.value==='release';searchMore.hidden=nextOffset===null;
    review.disabled=busy()||!allowed()||Boolean(uncertainty())||!(kind.value==='transfer'?view?.can_transfer&&candidate:view?.can_release&&date.value);search.disabled=busy()||!allowed()||!view?.can_transfer||!query.value.trim()||Boolean(uncertainty());searchMore.disabled=search.disabled;
    const canRespond=Boolean(transfer&&transfer.can_write&&transfer.state==='pending'&&transfer.status==='active'&&!uncertainty());
    for(const [n,action,role] of [[accept,'accept','to'],[decline,'decline','to'],[cancel,'cancel','from']]){n.hidden=!transfer||!transfer['can_'+action]||transfer[role+'_user'].id!==actorId();n.disabled=busy()||!eligible()||!canRespond}
    confirm.hidden=!pending;confirm.disabled=busy()||!eligible()||Boolean(uncertainty());check.hidden=!uncertainty();check.disabled=busy()||!eligible();acknowledge.hidden=!uncertainty()||!checked;acknowledge.disabled=busy()||!eligible();reload.disabled=busy()||!eligible();
  }
  async function refreshInbox(after=null){
    if(!eligible())return;const c=context(),read=++inboxEpoch;inboxNotice=t('cloud.working');render();
    try{const result=page(await request('ownership-transfers'+(after?'?after='+after:'')));if(!sameAccount(c)||read!==inboxEpoch)return;canonicalViewer=result.viewer_user_id;inboxRows=result.items;inboxAfter=result.next_after;renderRows(inbox,inboxRows);inboxNotice=t(inboxRows.length?'ownership.inbox_help':'ownership.empty')+(!result.can_write?' '+t('applications.read_only'):'')}
    catch(err){if(!sameAccount(c)||read!==inboxEpoch)return;if(([401,403,404].includes(err.status)||err.code==='service_restricted')&&c.intent===intentEpoch&&c.navigation===navigationEpoch)purge();else{inboxRows=[];inboxAfter=null;inbox.replaceChildren()}inboxNotice=errorText(err)}render();
  }
  async function refreshView(after=null){
    if(!eligible()||!catalogIndividualId(guitarId))return;const c=context(),id=guitarId,intent=intentEpoch,read=++viewEpoch;viewState='loading';render();
    try{const result=await readView(id,after);if(!sameAccount(c)||intent!==intentEpoch||id!==guitarId||read!==viewEpoch)return;canonicalViewer=result.viewer_user_id;view=result;historyAfter=result.next_after;viewState='ready';renderRows(history,result.items)}
    catch(err){if(!sameAccount(c)||intent!==intentEpoch||id!==guitarId||read!==viewEpoch)return;view=null;historyAfter=null;history.replaceChildren();viewState='failed';if(([401,403,404].includes(err.status)||err.code==='service_restricted')){globalThis.YGCOverlays.close(dialog);resetDialog()}}render();
  }
  async function setCatalogIntent(id){
    intentEpoch++;viewEpoch++;guitarId=id===null?null:(catalogIndividualId(id)||'');view=null;viewState='';historyAfter=null;history.replaceChildren();globalThis.YGCOverlays.close(dialog);resetDialog();render();return refreshView();
  }
  function open(){
    if(busy()||!eligible()||!view||(!view.is_current_owner&&!uncertain.has(guitarId))||dialog.open)return;resetDialog();selected=guitarId;title.textContent=t('ownership.heading');detail.textContent=summary(view.individual);date.value=date.max=today();globalThis.YGCOverlays.open(dialog);if(uncertainty())message.textContent=t('ownership.uncertain');render();
  }
  async function openGuitar(id){if(busy()||!eligible())return;const account=accountEpoch,actor=identity(),navigation=navigationEpoch;const loading=setCatalogIntent(id),intent=intentEpoch,editor=dialogEpoch;await loading;if(account===accountEpoch&&actor===identity()&&navigation===navigationEpoch&&intent===intentEpoch&&editor===dialogEpoch&&guitarId===id)open()}
  function action(fn){if(busy()||!eligible())return;return work(async()=>{try{return await fn()}finally{render()}})}
  function openTransfer(id){
    if(busy()||!eligible()||dialog.open||!catalogIndividualId(id))return;resetDialog();globalThis.YGCOverlays.open(dialog);title.textContent=t('ownership.review_transfer');message.textContent=t('cloud.working');const c=context();
    return action(async()=>{try{const row=await readTransfer(id);if(!sameDialog(c))return;showTransfer(row);message.textContent=uncertainty()?t('ownership.uncertain'):''}catch(err){if(sameDialog(c)){message.textContent=errorText(err);if(([401,403,404].includes(err.status)||err.code==='service_restricted')){purge();inboxNotice=errorText(err)}}}});
  }
  function invalidate(){pending=null;checked=false;message.textContent=uncertainty()?t('ownership.uncertain'):'';render()}
  query.oninput=()=>{searchEpoch++;candidate=null;nextOffset=null;searchTerm='';candidates.replaceChildren();selectedText.textContent='';invalidate()};kind.onchange=()=>{candidate=null;candidates.replaceChildren();selectedText.textContent='';nextOffset=null;searchEpoch++;invalidate()};date.oninput=body.oninput=invalidate;
  function searchUsers(offset=0){
    if(busy()||!allowed()||!view.can_transfer||uncertainty()||!query.value.trim()||query.value.trim().length>120)return;const c=context(),q=query.value.trim(),read=++searchEpoch;candidate=null;selectedText.textContent='';pending=null;candidates.replaceChildren();nextOffset=null;
    return action(async()=>{try{
      const data=await request('guitars/'+c.id+'/transfer-users?'+new URLSearchParams({q,offset:String(offset),limit:'20'}));if(!sameDialog(c)||read!==searchEpoch||query.value.trim()!==q)return;
      if(!Array.isArray(data.items)||data.items.length>20||!(data.next_offset===null||Number.isInteger(data.next_offset)&&data.next_offset>offset&&data.next_offset<=200))throw Error('Invalid destination search');
      const rows=data.items.map(value=>user(value,true));if(rows.some(row=>row.id===actorId())||new Set(rows.map(row=>row.id)).size!==rows.length)throw Error('Invalid destination');searchTerm=q;nextOffset=data.next_offset;
      for(const row of rows){const li=node('li'),choose=button('ownership.select');li.append(node('p',row.display_name+' · #'+row.id+' · '+row.account_type),choose);choose.onclick=()=>{if(busy()||!sameDialog(c)||read!==searchEpoch||query.value.trim()!==q||!allowed())return;candidate=row;selectedText.textContent=t('ownership.selected',{name:row.display_name,id:row.id});invalidate()};candidates.append(li)}message.textContent=rows.length?'':t('ownership.search_empty');
    }catch(err){if(!sameDialog(c)||read!==searchEpoch)return;candidate=null;nextOffset=null;candidates.replaceChildren();message.textContent=errorText(err);if(([401,403,404].includes(err.status)||err.code==='service_restricted'))await restricted(err,c)}});
  }
  search.onclick=()=>searchUsers();searchMore.onclick=()=>{if(nextOffset!==null&&searchTerm===query.value.trim())return searchUsers(nextOffset)};
  function prepare(actionName){
    if(busy()||!eligible()||!dialog.open||uncertainty())return;
    const c=context();
    if(transfer){if(!transfer.can_write||transfer.state!=='pending'||!transfer['can_'+actionName]||transfer[actionName==='cancel'?'from_user':'to_user'].id!==actorId())return;pending={action:actionName,claim:transfer.id,revision:transfer.revision,id:selected};message.textContent=t('ownership.confirm_'+actionName)+'\n'+transferSummary(transfer)}
    else{if(!allowed()||!view['can_'+kind.value])return;if(kind.value==='transfer'&&!candidate)return;if(kind.value==='release'&&(!/^\d{4}-\d{2}-\d{2}$/.test(date.value)||date.value>today()||body.value.trim().length>2000)){message.textContent=t('ownership.invalid');return}pending={action:kind.value,id:selected,revision:view.revision,...(kind.value==='transfer'?{to_user_id:candidate.id,to_name:candidate.display_name}:{occurred_at:date.value,body:body.value.trim()||null})};message.textContent=t('ownership.confirm_'+kind.value,{name:pending.to_name,id:pending.to_user_id,date:pending.occurred_at})+'\n'+summary(view.individual)}
    pending={...pending,context:c};render();
  }
  review.onclick=()=>prepare(kind.value);form.onsubmit=event=>{event.preventDefault();prepare(kind.value)};accept.onclick=()=>prepare('accept');decline.onclick=()=>prepare('decline');cancel.onclick=()=>prepare('cancel');
  async function restricted(err,c){
    pending=null;candidate=null;candidates.replaceChildren();selectedText.textContent='';
    if(err.code==='service_restricted'){
      try{const data=transfer?await readTransfer(transfer.id):await readView(c.id);if(!sameDialog(c))return;if(transfer)showTransfer(data);else view=data;message.textContent=errorText(err)}catch{if(sameDialog(c)){purge();inboxNotice=t('self_profile.restricted')}}
    }else if(sameAccount(c)){purge();inboxNotice=errorText(err)}
  }
  async function refreshAfterMutation(c){
    if(!sameAccount(c))return;
    // Completion invalidates ownership/account lists even if Close or Back was
    // used. Refreshing must not close or replace a newer private editor.
    await Promise.all([refreshInbox(),updated(),guitarId?refreshView():Promise.resolve()]);
  }
  confirm.onclick=()=>{
    if(busy()||!eligible()||!pending||uncertainty()||!sameDialog(pending.context))return;const operation={...pending},c=operation.context;pending=null;
    return action(async()=>{let attempted=false;
      try{
        const fresh=operation.claim?await readTransfer(operation.claim):await readView(operation.id);if(!sameDialog(c))return;
        if(operation.claim)showTransfer(fresh);else view=fresh;
        if(!fresh.can_write){message.textContent=t('applications.read_only');return}
        const permission=operation.claim?fresh['can_'+operation.action]&&fresh.state==='pending'&&fresh[operation.action==='cancel'?'from_user':'to_user'].id===actorId():fresh.is_current_owner&&fresh['can_'+operation.action];
        if(!permission||fresh.revision!==operation.revision){message.textContent=t('ownership.conflict');return}
        const path=operation.claim?'transfers/'+operation.claim+'/resolve':'guitars/'+operation.id+'/'+(operation.action==='transfer'?'transfers':'release');
        const payload=operation.claim?{action:operation.action,revision:operation.revision}:operation.action==='transfer'?{to_user_id:operation.to_user_id,revision:operation.revision}:{occurred_at:operation.occurred_at,body:operation.body,revision:operation.revision};
        attempted=true;const data=await request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const result=operation.action==='release'?releaseRow(data.claim,operation.id):transferRow(data.transfer);
        if(result.individual_id!==operation.id||operation.claim&&(result.id!==operation.claim||result.state!==({accept:'accepted',decline:'declined',cancel:'cancelled'}[operation.action]))||operation.action==='transfer'&&(result.from_user.id!==fresh.viewer_user_id||result.to_user.id!==operation.to_user_id||result.state!=='pending'))throw Error('Unexpected ownership result');
        if(!sameAccount(c))return;uncertain.delete(operation.id);
        if(sameDialog(c)){if(operation.action==='release'){globalThis.YGCOverlays.close(dialog)}else{showTransfer(result);message.textContent=t('ownership.saved')}}
        await refreshAfterMutation(c);
      }catch(err){
        if(!sameAccount(c))return;
        const unknown=attempted&&(!err.status||err.status>=500&&err.code!=='service_restricted');
        if(unknown){uncertain.set(operation.id,operation);if(sameDialog(c)){checked=false;message.textContent=t('ownership.uncertain')}inboxNotice='';await refreshAfterMutation(c)}
        else if(sameDialog(c)){message.textContent=errorText(err);if(([401,403,404].includes(err.status)||err.code==='service_restricted'))await restricted(err,c);else if(err.status===409){await reloadCurrent(c);if(sameDialog(c))message.textContent=t('ownership.conflict')}}
      }
    });
  };
  async function reloadCurrent(c=context()){
    try{const data=transfer?await readTransfer(transfer.id):await readView(c.id);if(!sameDialog(c))return false;pending=null;if(transfer)showTransfer(data);else{view=data;renderRows(history,data.items);historyAfter=data.next_after}return true}
    catch(err){if(sameDialog(c)){message.textContent=errorText(err);if(([401,403,404].includes(err.status)||err.code==='service_restricted'))await restricted(err,c)}return false}
  }
  reload.onclick=()=>action(async()=>{const c=context();if(await reloadCurrent(c)&&sameDialog(c))message.textContent=uncertainty()?t('ownership.uncertain'):t('ownership.review_again')});
  check.onclick=()=>action(async()=>{const c=context(),record=uncertainty();if(!record)return;checked=false;
    try{const data=record.claim?await readTransfer(record.claim):await readView(record.id);if(!sameDialog(c))return;if(record.claim)showTransfer(data);else{view=data;renderRows(history,data.items);saved.textContent=data.items.map(row=>row.ownership_kind==='transfer'?transferSummary(row):'#'+row.id+' · '+t('ownership.release')+' · '+(row.occurred_at||'')+(row.body?'\n'+row.body:'')).join('\n\n')}
      checked=true;message.textContent=t('ownership.checked');await refreshAfterMutation(c);
    }catch(err){if(sameDialog(c)){message.textContent=errorText(err);if(([401,403,404].includes(err.status)||err.code==='service_restricted'))await restricted(err,c)}}});
  acknowledge.onclick=()=>{if(busy()||!eligible()||!checked||!uncertainty()||!dialog.open)return;uncertain.delete(selected);checked=false;pending=null;message.textContent=t('ownership.review_again');render()};
  start.onclick=open;refreshButton.onclick=()=>action(()=>refreshInbox());inboxMore.onclick=()=>action(()=>inboxAfter?refreshInbox(inboxAfter):undefined);intentRefresh.onclick=()=>action(()=>refreshView());historyMore.onclick=()=>action(()=>historyAfter?refreshView(historyAfter):undefined);
  globalThis.addEventListener('popstate',()=>{navigationEpoch++;globalThis.YGCOverlays.close(dialog);resetDialog()});globalThis.addEventListener('pagehide',clear);
  render();return {render,clear,refresh:refreshInbox,setCatalogIntent,openGuitar};
}
