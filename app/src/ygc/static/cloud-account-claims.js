import {catalogIndividualId} from './cloud-account-applications.js';
import {createPrivateMedia,validateMediaItems,validMediaFiles} from './cloud-account-media.js';

export function readClaimIntent(search){
  const values=new URLSearchParams(search).getAll('claim');
  return values.length===0?null:values.length===1?(catalogIndividualId(values[0])||''):'';
}

// This surface contains only the authenticated author's own submissions. Public
// Chronicle rendering stays in the public projection and never reads this data.
export function createClaims({auth,state,busy,work}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params),$=id=>document.getElementById(id);
  const node=(tag,text,id)=>{const n=document.createElement(tag);if(text)n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id)=>{const n=node('button',t(key),id);n.type='button';return n};
  const root=$('selfClaims'),intentRoot=$('catalogClaimIntent');
  const heading=node('h2',t('claims.heading')),notice=node('p',t('claims.help')),status=node('p','','claimsStatus'),list=node('ul','','claimsList');
  status.setAttribute('role','status');
  const browse=node('a',t('catalog.select_guitar'));browse.href='/';
  const refreshButton=button('action.refresh','claimsRefresh'),more=button('claims.older','claimsMore');
  root.append(heading,notice,browse,refreshButton,status,list,more);
  const intentHeading=node('h2',t('claims.intent_title'),'catalogClaimTitle'),intentDetail=node('p','','catalogClaimDetail'),intentStatus=node('p','','catalogClaimStatus'),intentLink=node('a',t('catalog.view_guitar'),'catalogClaimLink'),start=button('claims.add','catalogClaimStart');
  intentStatus.setAttribute('role','status');intentRoot.setAttribute('aria-labelledby',intentHeading.id);intentRoot.append(intentHeading,intentDetail,intentStatus,intentLink,start);

  const dialog=node('dialog','','claimDialog'),title=node('h2','','claimTitle'),guitarDetail=node('p','','claimGuitar'),savedState=node('p','','claimSavedState'),form=node('form','','claimForm'),fields=node('fieldset'),message=node('p','','claimMessage');
  dialog.setAttribute('aria-labelledby',title.id);message.setAttribute('role','status');
  const kind=node('select','','claimKind'),date=node('input','','claimDate'),body=node('textarea','','claimBody'),items=node('div','','claimItems');
  date.type='date';body.maxLength=2000;
  const mediaInput=node('input','','claimMediaInput'),mediaHelp=node('p',t('claims.media_help'),'claimMediaHelp'),mediaPhotos=node('div','','claimMediaPhotos'),mediaMessage=node('p','','claimMediaMessage'),mediaReload=button('claims.media_reload','claimMediaReload');
  mediaInput.type='file';mediaInput.multiple=true;mediaInput.accept='image/jpeg,image/png,image/webp';mediaInput.setAttribute('aria-describedby','claimMediaHelp');mediaPhotos.className='claim-media-photos';mediaMessage.setAttribute('role','status');
  const mediaLabel=labelMedia();function labelMedia(){const n=node('label',t('claims.media_files'));n.htmlFor=mediaInput.id;return n}
  const addItem=button('claims.add_field','claimAddField'),save=node('button',t('claims.save'),'claimSave'),deactivate=button('claims.deactivate','claimDeactivate'),close=button('action.close','claimClose');save.type='submit';
  const uncertainResults=node('p','','claimUncertainResults'),checkSubmission=button('claims.check_submission','claimCheckSubmission'),retryCreate=button('claims.retry_create','claimRetryCreate');
  const latest=node('p','','claimLatest'),rebase=button('claims.keep_edits','claimKeepEdits'),checkLatest=button('claims.check_latest','claimCheckLatest');
  const label=(input,key)=>{const n=node('label',t(key));n.htmlFor=input.id;return n};
  fields.append(label(kind,'claims.kind'),kind,label(date,'claims.date'),date,items,addItem,label(body,'claims.body'),body,mediaLabel,mediaInput);form.append(fields,save);
  const mediaSection=node('section','','claimMediaSection');mediaSection.append(mediaHelp,mediaMessage,mediaPhotos,mediaReload);
  dialog.append(title,guitarDetail,savedState,node('p',t('claims.editor_help')),form,mediaSection,deactivate,message,latest,rebase,checkLatest,uncertainResults,checkSubmission,retryCreate,close);document.body.append(dialog);

  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true&&(!state().user.status||state().user.status==='active'));
  let renderedIdentity=identity(),accountEpoch=0,intentEpoch=0,readEpoch=0,dialogEpoch=0;
  let guitarId=null,guitar=null,lookupState='',canWrite=null,rows=[],nextAfter=null,currentAfter=null,selected=null,draftGuitar=null;
  let mediaFiles=[],mediaReady=false,mediaFailed=false,photoContext=null;
  const media=createPrivateMedia({auth,container:mediaPhotos,isCurrent:()=>Boolean(photoContext&&photoContext()&&dialog.open),onState:ready=>{mediaReady=ready;render()},onError:photoError});
  let itemInputs=[],fieldSequence=0,editing=false,dateChanged=false,draftDate=null,conflict=false,latestClaim=null,confirmDeactivate=false,uncertainCreate=false,submissionChecked=false;
  const writable=()=>eligible()&&canWrite===true&&Boolean(guitar)&&guitar.id===guitarId;
  const current=(accountVersion,actor,intentVersion,id)=>accountVersion===accountEpoch&&identity()===actor&&intentVersion===intentEpoch&&id===guitarId;
  const publicFields=['id','manufacturer','model','finish','year','serial_number'];
  const summary=value=>value?[value.manufacturer,value.model,value.finish,value.year,value.serial_number,'#'+value.id].filter(v=>v!==null&&v!=='').join(' · '):'';
  const today=()=>{const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')};
  function dateValue(value){if(!value)return '';if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;const d=new Date(value);return Number.isNaN(d.valueOf())?'':d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
  function validateGuitar(value,id){
    if(!value||Array.isArray(value)||value.id!==id||!catalogIndividualId(value.id)||publicFields.slice(1).some(key=>value[key]!==null&&typeof value[key]!=='string'))throw Error('Invalid selected guitar');
    return Object.freeze(Object.fromEntries(publicFields.map(key=>[key,value[key]])));
  }
  function validateClaim(row,id){
    if(!row||!catalogIndividualId(row.id)||row.individual_id!==id||!['specification','incident','media'].includes(row.claim_type)||!['active','inactive'].includes(row.status)||!['positive','negative','unverified'].includes(row.verification_status)||typeof row.revision!=='string'||!/^[a-f0-9]{64}$/.test(row.revision)||!(row.body===null||typeof row.body==='string')||!(row.occurred_at===null||typeof row.occurred_at==='string'))throw Error('Invalid own Claim');
    if(row.claim_type==='specification'&&(!['specification','repair'].includes(row.specification_kind)||!Array.isArray(row.spec_items)||row.spec_items.length>50||row.spec_items.some(item=>!item||typeof item.field_name!=='string'||typeof item.value_text!=='string')))throw Error('Invalid own specification');
    if(row.claim_type==='incident'&&!['damage','lost','theft'].includes(row.incident_kind))throw Error('Invalid own incident');
    const media_items=row.claim_type==='media'?validateMediaItems(row.media_items):[];
    if(row.claim_type==='media'&&(row.incident_kind!==null||!Array.isArray(row.spec_items)||row.spec_items.length))throw Error('Invalid Media fields');
    return Object.freeze({id:row.id,individual_id:id,claim_type:row.claim_type,specification_kind:row.specification_kind,incident_kind:row.incident_kind,status:row.status,verification_status:row.verification_status,revision:row.revision,body:row.body,occurred_at:row.occurred_at,created_at:typeof row.created_at==='string'?row.created_at:null,updated_at:typeof row.updated_at==='string'?row.updated_at:null,media_items,spec_items:row.claim_type==='specification'?row.spec_items.map(item=>({field_name:item.field_name,value_text:item.value_text})):[]});
  }
  function validatePage(data,id){
    const individual=validateGuitar(data?.individual,id);
    if(!Array.isArray(data.items)||data.items.length>50||!(data.next_after===null||catalogIndividualId(data.next_after)))throw Error('Invalid own Claim list');
    const items=data.items.map(row=>validateClaim(row,id));
    if(new Set(items.map(row=>row.id)).size!==items.length||data.next_after!==null&&(!items.length||data.next_after!==items.at(-1).id))throw Error('Invalid own Claim cursor');
    return {individual,items,next_after:data.next_after,can_write:typeof data.can_write==='boolean'?data.can_write:null};
  }
  function resetDialog(){
    dialogEpoch++;photoContext=null;media.clear();mediaFiles=[];mediaInput.value='';mediaMessage.textContent='';mediaFailed=false;selected=null;draftGuitar=null;editing=false;dateChanged=false;draftDate=null;fieldSequence=0;conflict=false;latestClaim=null;confirmDeactivate=false;uncertainCreate=false;submissionChecked=false;uncertainResults.textContent='';
    itemInputs=[];items.replaceChildren();body.value=date.value='';kind.replaceChildren();guitarDetail.textContent=savedState.textContent=message.textContent=latest.textContent='';
  }
  dialog.addEventListener('ygc:closed',resetDialog);close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function purgePrivate(){readEpoch++;canWrite=null;rows=[];nextAfter=null;currentAfter=null;list.replaceChildren();status.textContent='';globalThis.YGCOverlays.close(dialog);resetDialog()}
  function clear(){renderedIdentity=identity();accountEpoch++;intentEpoch++;guitar=null;lookupState='';purgePrivate();renderedIdentity=identity()}
  function rowName(row){return t('claims.'+(row.claim_type==='specification'?row.specification_kind:row.claim_type==='media'?'media':row.incident_kind))}
  function rowSummary(row){return '#'+row.id+' · '+rowName(row)+' · '+(row.occurred_at||'')+' · '+t('claims.'+row.status)+' · '+t('chronicle.'+row.verification_status)}
  function contentSummary(row){return rowSummary(row)+(row.created_at?'\n'+t('claims.created')+': '+row.created_at:'')+(row.updated_at?'\n'+t('claims.updated')+': '+row.updated_at:'')+(row.spec_items.length?'\n'+row.spec_items.map(item=>item.field_name+': '+item.value_text).join('\n'):'')+(row.body?'\n'+row.body:'')}
  function renderList(){
    list.replaceChildren();const version=accountEpoch,actor=identity(),selection=intentEpoch,id=guitarId;
    for(const row of rows){const li=node('li'),description=node('p',rowSummary(row)),view=button('claims.view');
      view.onclick=()=>{if(!busy()&&eligible()&&current(version,actor,selection,id)&&!dialog.open)show(row)};li.append(description,view);list.append(li)}
  }
  function render(){
    if(renderedIdentity!==identity()){clear();renderedIdentity=identity()}
    root.hidden=!eligible();intentRoot.hidden=guitarId===null;intentDetail.textContent=summary(guitar);
    intentLink.href=catalogIndividualId(guitarId)?'/guitars/'+guitarId:'/';intentLink.textContent=t(catalogIndividualId(guitarId)?'catalog.view_guitar':'catalog.browse');
    const hint=lookupState==='loading'?'catalog.acquire_loading':guitarId===''?'catalog.acquire_invalid':!guitar?'catalog.acquire_unavailable':!state()?.user?'catalog.acquire_sign_in':!eligible()?'catalog.acquire_verify':canWrite===true?'claims.ready':canWrite===false?'applications.read_only':'applications.access_unavailable';
    intentStatus.textContent=t(hint);start.disabled=busy()||!writable();refreshButton.disabled=busy()||!catalogIndividualId(guitarId);more.hidden=nextAfter===null;more.disabled=busy()||!eligible();
    const active=!selected||selected.status==='active',spec=['specification','repair'].includes(kind.value),isMedia=kind.value==='media';
    fields.disabled=busy()||!writable()||!active;kind.disabled=Boolean(selected&&selected.claim_type!=='specification');
    mediaSection.hidden=!isMedia;mediaInput.hidden=mediaLabel.hidden=!isMedia||Boolean(selected);mediaInput.required=isMedia&&!selected;mediaReload.hidden=!selected||!isMedia||!mediaFailed;mediaReload.disabled=busy()||!eligible();
    items.hidden=addItem.hidden=!spec;addItem.disabled=itemInputs.length>=50;
    body.required=!spec&&!isMedia;save.textContent=t(selected?'claims.save':'claims.add');save.disabled=busy()||!writable()||!active||conflict||uncertainCreate||!editing||(isMedia&&!selected&&!mediaReady);
    deactivate.hidden=!selected||!active;deactivate.disabled=busy()||!writable()||conflict;deactivate.textContent=t(confirmDeactivate?'claims.deactivate_confirm':'claims.deactivate');
    latest.hidden=!conflict;rebase.hidden=!conflict||!latestClaim||latestClaim.status!=='active';rebase.disabled=busy()||!writable();checkLatest.hidden=!conflict;checkLatest.disabled=busy()||!eligible();
    checkSubmission.hidden=uncertainResults.hidden=!uncertainCreate;checkSubmission.disabled=busy()||!eligible();retryCreate.hidden=!uncertainCreate||!submissionChecked;retryCreate.disabled=busy()||!writable();
  }
  function errorText(error){return t(error.code==='service_restricted'?'applications.service_restricted':[401,403].includes(error.status)?'self_profile.restricted':error.status===409?'claims.conflict':[400,413,415,422].includes(error.status)?'claims.invalid':'claims.failed')}
  async function json(response){
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Object.assign(Error('Claim request failed'),{status:response.status,code:data.detail?.code||data.code})}
    return response.json();
  }
  async function ownRequest(id,suffix='',options={}){
    return json(await auth().authorizedFetch('/api/auth/guitars/'+id+'/claims'+suffix,{cache:'no-store',credentials:'omit',redirect:'error',...options,headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',...options.headers}},true));
  }
  async function publicGuitar(id){
    const options={cache:'no-store',credentials:'omit',redirect:'error'};
    const response=auth()?.signedIn?await auth().authorizedFetch('/api/public/guitars/'+id,options):await globalThis.fetch('/api/public/guitars/'+id,options);
    return validateGuitar(await json(response),id);
  }
  function failed(err){
    if([401,403].includes(err.status)){guitar=null;lookupState='unavailable';purgePrivate()}else if(err.status===404){guitar=null;lookupState='unavailable';purgePrivate()}else canWrite=null;
    status.textContent=errorText(err);render();
  }
  async function refresh(after=null){
    if(!catalogIndividualId(guitarId))return false;
    const id=guitarId,version=accountEpoch,actor=identity(),selection=intentEpoch,read=++readEpoch;
    const isCurrent=()=>current(version,actor,selection,id)&&read===readEpoch;
    canWrite=null;lookupState='loading';render();
    try{
      if(eligible()){
        const page=validatePage(await ownRequest(id,after?'?after='+after:''),id);if(!isCurrent())return;
        guitar=page.individual;rows=page.items;currentAfter=after;nextAfter=page.next_after;canWrite=page.can_write;renderList();
        status.textContent=rows.length?'':t('claims.empty');
        if(dialog.open&&selected?.claim_type==='media'){const fresh=rows.find(row=>row.id===selected.id);if(!fresh||fresh.revision!==selected.revision)showConflict(fresh)}
      }else{const checked=await publicGuitar(id);if(!isCurrent())return;guitar=checked}
      lookupState='ready';render();return true;
    }catch(err){
      if(!isCurrent())return;
      // Only a fresh successful read may retain private data after access denial.
      if([401,403,404].includes(err.status)){guitar=null;lookupState='unavailable';purgePrivate()}
      else{canWrite=null;lookupState=guitar?'ready':'unavailable'}
      status.textContent=errorText(err);render();return false;
    }
  }
  function setCatalogIntent(id){
    intentEpoch++;guitarId=id===null?null:(catalogIndividualId(id)||'');guitar=null;lookupState='';purgePrivate();render();return refresh();
  }
  function addField(field='',value=''){
    if(itemInputs.length>=50)return;
    const row=node('div',undefined),fieldInput=node('input'),valueInput=node('input'),remove=button('claims.remove_field');row.className='claim-spec-row';
    fieldInput.type=valueInput.type='text';fieldInput.maxLength=120;valueInput.maxLength=500;fieldInput.value=field;valueInput.value=value;fieldInput.required=valueInput.required=true;
    fieldInput.setAttribute('aria-label',t('claims.field'));valueInput.setAttribute('aria-label',t('claims.value'));fieldInput.placeholder=t('claims.field_example');valueInput.placeholder=t('claims.value');
    const index=fieldSequence++;fieldInput.id='claimField_'+index;valueInput.id='claimValue_'+index;
    row.append(label(fieldInput,'claims.field'),fieldInput,label(valueInput,'claims.value'),valueInput,remove);items.append(row);
    const entry={row,field:fieldInput,value:valueInput};itemInputs.push(entry);
    remove.onclick=()=>{if(busy()||!writable()||selected?.status==='inactive')return;itemInputs=itemInputs.filter(item=>item!==entry);items.replaceChildren(...itemInputs.map(item=>item.row));confirmDeactivate=false;render()};
    fieldInput.oninput=valueInput.oninput=()=>{confirmDeactivate=false;render()};
  }
  function show(row=null){
    resetDialog();editing=true;selected=row;draftGuitar=guitar;title.textContent=t(row?'claims.edit':'claims.add');guitarDetail.textContent=summary(draftGuitar);savedState.textContent=row?contentSummary(row):'';draftDate=row?.occurred_at??null;
    const choices=row?.claim_type==='media'?['media']:row?.claim_type==='incident'?[row.incident_kind]:row?['specification','repair']:['specification','repair','damage','lost','theft','media'];
    for(const value of choices){const option=node('option',t('claims.'+value));option.value=value;kind.append(option)}
    kind.value=row?(row.claim_type==='specification'?row.specification_kind:row.claim_type==='media'?'media':row.incident_kind):'specification';
    date.value=row?dateValue(row.occurred_at):today();date.max=today();body.value=row?.body||'';
    if(row?.claim_type==='specification')for(const item of row.spec_items)addField(item.field_name,item.value_text);
    if(!row)addField();
    render();globalThis.YGCOverlays.open(dialog);if(row?.claim_type==='media')loadPhotos(row);
  }
  function showConflict(row){
    conflict=true;if(selected?.claim_type==='media'){media.clear();mediaFailed=true;mediaMessage.textContent=t('claims.media_stale')}latestClaim=row||null;confirmDeactivate=false;message.textContent=t('claims.conflict');latest.textContent=row?t('claims.latest')+'\n'+contentSummary(row):t('claims.missing');render();
  }
  rebase.onclick=()=>{if(busy()||!writable()||!latestClaim||latestClaim.status!=='active'||!dialog.open)return;selected=latestClaim;latestClaim=null;conflict=false;message.textContent=t('claims.review_edits');savedState.textContent=contentSummary(selected);render();if(selected.claim_type==='media')loadPhotos(selected)};
  kind.onchange=()=>{confirmDeactivate=false;media.clear();mediaFiles=[];mediaInput.value='';mediaFailed=false;mediaMessage.textContent='';for(const item of itemInputs){item.field.required=item.value.required=['specification','repair'].includes(kind.value)}render()};
  function mediaContext(){const version=accountEpoch,actor=identity(),selection=intentEpoch,id=guitarId,editor=dialogEpoch;return ()=>current(version,actor,selection,id)&&editor===dialogEpoch&&dialog.open}
  function loadPhotos(row){photoContext=mediaContext();mediaFailed=false;mediaMessage.textContent=t('claims.media_loading');media.load(guitarId,row).then(()=>{if(photoContext?.()&&mediaReady)mediaMessage.textContent=''});render()}
  async function photoError(error){
    mediaFailed=true;mediaMessage.textContent=t(!selected?'claims.media_invalid':'claims.media_failed');render();
    const valid=photoContext;if(!valid?.()||!selected)return;
    if([401,403,404].includes(error.status)){
      const version=accountEpoch,actor=identity(),selection=intentEpoch,id=guitarId,after=currentAfter;purgePrivate();await refresh(after);
      if(current(version,actor,selection,id))status.textContent=t('claims.media_failed');
    }
    else if(error.status===409){showConflict(null);await readLatest(valid)}
  }
  mediaInput.onchange=()=>{
    if(busy()||!writable()||selected||kind.value!=='media')return;
    confirmDeactivate=false;mediaFiles=Array.from(mediaInput.files||[]);photoContext=mediaContext();mediaFailed=false;mediaMessage.textContent=t('claims.media_loading');
    media.preview(mediaFiles).then(()=>{if(photoContext?.()&&mediaReady)mediaMessage.textContent=''});render();
  };
  mediaReload.onclick=()=>{if(!busy()&&eligible()&&selected?.claim_type==='media'&&dialog.open&&!conflict)loadPhotos(selected)};
  date.oninput=date.onchange=()=>{dateChanged=true;confirmDeactivate=false};body.oninput=()=>{confirmDeactivate=false;render()};
  addItem.onclick=()=>{if(!busy()&&writable()&&selected?.status!=='inactive'){addField();render()}};
  start.onclick=()=>{if(!busy()&&writable()&&!dialog.open)show()};
  async function action(fn){
    if(busy()||!eligible())return;
    const version=accountEpoch,actor=identity(),selection=intentEpoch,id=guitarId,editor=dialogEpoch;
    await work(async()=>{
      try{await fn(()=>current(version,actor,selection,id)&&editor===dialogEpoch)}
      catch(err){if(!current(version,actor,selection,id))return;
        if(err.code==='service_restricted'&&[403,503].includes(err.status)){
          // PR52: do not turn a read-only write denial into a sign-out, but
          // revalidate read access before retaining any private submissions.
          canWrite=false;if(selected?.claim_type==='media')media.clear();const restored=await refresh(currentAfter);if(!current(version,actor,selection,id))return;
          if(!restored){purgePrivate();status.textContent=errorText(err);render();return}
          if(editor===dialogEpoch&&selected?.claim_type==='media'&&!conflict)loadPhotos(selected);
        }else if([401,403,404].includes(err.status)){failed(err);return}
        if(editor===dialogEpoch){message.textContent=errorText(err);if(err.status===409){if(selected){showConflict(null);await readLatest(()=>current(version,actor,selection,id)&&editor===dialogEpoch)}else message.textContent=t('claims.retry_conflict')}}
        status.textContent=errorText(err);
      }finally{render()}
    });
  }
  async function preflight(valid){
    const id=guitarId,editor=dialogEpoch,target=selected;
    const page=validatePage(await ownRequest(id,target&&currentAfter?'?after='+currentAfter:''),id);if(!valid()||!dialog.open||editor!==dialogEpoch)return false;
    guitar=page.individual;canWrite=page.can_write;rows=page.items;nextAfter=page.next_after;renderList();render();
    if(target){const latest=page.items.find(row=>row.id===target.id);if(!latest||latest.revision!==target.revision||latest.status!=='active'){showConflict(latest);return false}}
    if(!writable()){message.textContent=t('applications.read_only');return false}
    return true;
  }
  async function readLatest(valid){
    if(!selected||!dialog.open)return;
    const id=guitarId,target=selected;
    try{
      const page=validatePage(await ownRequest(id,currentAfter?'?after='+currentAfter:''),id);if(!valid())return;
      canWrite=page.can_write;guitar=page.individual;showConflict(page.items.find(row=>row.id===target.id));
    }catch(err){if(!valid())return;if([401,403,404].includes(err.status)){failed(err);return}message.textContent=errorText(err);render()}
  }
  checkLatest.onclick=()=>action(readLatest);
  checkSubmission.onclick=()=>action(async valid=>{
    if(!uncertainCreate||!dialog.open)return;
    const page=validatePage(await ownRequest(guitarId),guitarId);if(!valid())return;
    guitar=page.individual;rows=page.items;nextAfter=page.next_after;currentAfter=null;canWrite=page.can_write;submissionChecked=true;
    uncertainResults.textContent=t('claims.recent_submissions')+'\n'+(rows.length?rows.map(contentSummary).join('\n\n'):t('claims.empty'));renderList();render();
  });
  retryCreate.onclick=()=>{
    if(busy()||!dialog.open||!uncertainCreate||!submissionChecked||!writable())return;
    uncertainCreate=false;submissionChecked=false;message.textContent=t('claims.retry_acknowledged');render();
  };
  function payload(){
    const isMedia=selected?.claim_type==='media'||kind.value==='media',spec=!isMedia&&['specification','repair'].includes(kind.value),occurred_at=selected&&!dateChanged?draftDate:date.value||null;
    const result={claim_type:isMedia?'media':spec?'specification':'incident',body:body.value.trim()||null,occurred_at};
    if(spec){result.specification_kind=kind.value;result.items=itemInputs.map(item=>({field_name:item.field.value.trim(),value_text:item.value.value.trim()}));if(!result.items.length||result.items.some(item=>!item.field_name||!item.value_text)||new Set(result.items.map(item=>item.field_name.toLowerCase())).size!==result.items.length)throw {status:400}}
    else if(!isMedia){result.incident_kind=selected?.incident_kind||kind.value;if(!result.body||!['damage','lost','theft'].includes(result.incident_kind))throw {status:400}}
    if(isMedia&&!selected&&(!mediaReady||!validMediaFiles(mediaFiles)))throw {status:400};
    if(selected)result.revision=selected.revision;
    return result;
  }
  form.onsubmit=event=>{
    event.preventDefault();if(!dialog.open||!editing||!writable()||conflict||uncertainCreate||selected?.status==='inactive')return;
    action(async valid=>{
      const id=guitarId,target=selected,body=payload(),files=[...mediaFiles];if(!await preflight(valid)||!valid())return;
      let row;
      try{
        let result;
        if(!target&&body.claim_type==='media'){
          const data=new FormData();data.append('metadata',JSON.stringify(body));for(const file of files)data.append('images',file);
          result=await json(await auth().authorizedFetch('/api/auth/guitars/'+id+'/media-claims',{method:'POST',body:data,cache:'no-store',credentials:'omit',redirect:'error',headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'}},true));
        }else result=await ownRequest(id,target?'/'+target.id:'',{method:target?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        if(!valid())return;row=validateClaim(result.claim,id);
      }catch(err){
        if(!target&&valid()&&![400,401,403,404,409,413,415,422].includes(err.status)){
          // A transport/server failure may follow a committed creation. Never
          // encourage an ordinary retry before reviewing recent submissions.
          uncertainCreate=true;submissionChecked=false;uncertainResults.textContent='';message.textContent=t('claims.uncertain');render();return;
        }
        throw err;
      }
      show(row);message.textContent=t('claims.saved');await refresh();
    });
  };
  deactivate.onclick=()=>{
    if(busy()||!dialog.open||!writable()||!selected||selected.status!=='active'||conflict)return;
    if(!confirmDeactivate){confirmDeactivate=true;message.textContent=t(selected.claim_type==='media'?'claims.media_deactivate_help':'claims.deactivate_help',{id:selected.id});render();return}
    action(async valid=>{
      const id=guitarId,target=selected;if(!await preflight(valid)||!valid())return;
      const result=await ownRequest(id,'/'+target.id+'/deactivate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:target.revision})});
      if(!valid())return;const row=validateClaim(result.claim,id);show(row);message.textContent=t('claims.deactivated');await refresh();
    });
  };
  refreshButton.onclick=()=>action(async()=>{await refresh()});more.onclick=()=>{if(nextAfter!==null)return action(async()=>{await refresh(nextAfter)})};
  globalThis.addEventListener('pagehide',()=>purgePrivate());
  globalThis.addEventListener('focus',()=>{if(!busy()&&guitarId!==null)refresh(currentAfter)});
  render();return {render,refresh,clear,failed,setCatalogIntent};
}
