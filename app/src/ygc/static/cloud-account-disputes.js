import {catalogIndividualId} from './cloud-account-applications.js';

const disputeObject=value=>Boolean(value&&typeof value==='object'&&!Array.isArray(value));
const disputeExact=(value,keys)=>disputeObject(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const disputeText=(value,max,multiline=false)=>typeof value==='string'&&[...value].length<=max&&!/[\uD800-\uDFFF]/u.test(value)&&!(multiline?/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/:/[\x00-\x1f\x7f]/).test(value);
const disputeNullable=(value,max,multiline=false)=>value===null||disputeText(value,max,multiline);
const disputeDate=value=>disputeText(value,50)&&value.length>0&&Number.isFinite(Date.parse(value));
const disputeId=value=>Boolean(catalogIndividualId(value));
const disputeRevision=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const disputeCaseKeys=['id','individual_id','owner_id','locked_owner_id','winner_id','status','version','created_at','updated_at','decision','reason','individual','owner','current_owner','applicants','round_number','round_phase'];

// Shared private participant/Admin presentation. Every destination is freshly
// authorized, and only the server decides eligibility, parties and redaction.
export function createDisputes({auth,state,busy,work,admin=false,updated=async()=>{},onUnauthorized=()=>{}}){
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params),node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n};
  const button=(key,id='')=>{const n=node('button',t(key),id);n.type='button';return n},label=(key,input)=>{const n=node('label',t(key));n.htmlFor=input.id;return n};
  const root=document.getElementById(admin?'disputeBrowser':'selfDisputes'),heading=node('h2',t('cloud_disputes.heading')),status=node('p','','disputeStatus'),list=node('ul','','disputeList'),options=node('ul','','disputeOptions');
  const refreshButton=button('action.refresh','disputeRefresh'),filter=node('select','','disputeFilter'),previous=button('users.previous','disputePrevious'),next=button('users.next','disputeNext'),optionPrevious=button('users.previous','disputeOptionPrevious'),optionNext=button('users.next','disputeOptionNext');
  for(const value of ['open','resolved','all']){const n=node('option',t('cloud_disputes.'+value));n.value=value;filter.append(n)}filter.value='open';filter.hidden=!admin;filter.setAttribute('aria-label',t('cloud_disputes.filter'));status.setAttribute('role','status');
  root.append(heading,node('p',t('cloud_disputes.scope')),refreshButton,filter,status,list,previous,next,options,optionPrevious,optionNext);
  const dialog=node('dialog','','disputeDialog'),title=node('h2',t('cloud_disputes.details'),'disputeTitle'),meta=node('div','','disputeMeta'),message=node('p','','disputeMessage'),rounds=node('div','','disputeRounds');
  const reload=button('action.refresh','disputeReload'),close=button('action.close','disputeClose'),accept=button('cloud_disputes.accept','disputeAccept');
  const form=node('form','','disputeForm'),fields=node('fieldset','','disputeFields'),claim=node('select','','disputeClaim'),claimLabel=label('cloud_disputes.claim',claim),explanation=node('textarea','','disputeExplanation'),summary=node('textarea','','disputeSummary'),attachment=node('input','','disputeAttachment'),review=node('button',t('cloud_disputes.review_submit'),'disputeReview');
  explanation.required=summary.required=true;explanation.maxLength=16000;summary.maxLength=8000;attachment.type='file';attachment.accept='image/jpeg,image/png,image/webp,image/gif,application/pdf';review.type='submit';
  fields.append(claimLabel,claim,label('cloud_disputes.explanation',explanation),explanation,label('cloud_disputes.summary',summary),summary,label('cloud_disputes.attachment',attachment),attachment,node('p',t('cloud_disputes.privacy')));form.append(fields,review);
  const adminPanel=node('section','','disputeAdmin'),operation=node('select','','disputeOperation'),reason=node('textarea','','disputeReason'),winner=node('select','','disputeWinner'),winnerLabel=label('cloud_disputes.winner',winner),reviewDecision=button('cloud_disputes.review_decision','disputeReviewDecision');reason.maxLength=8000;reason.required=true;
  adminPanel.append(node('h3',t('cloud_disputes.adjudicate')),node('p',t('cloud_disputes.incomplete_allowed')),label('cloud_disputes.operation',operation),operation,winnerLabel,winner,label('cloud_disputes.reason',reason),reason,reviewDecision);
  const preview=node('section','','disputePreview'),confirm=button('cloud_disputes.confirm','disputeConfirm'),check=button('cloud_disputes.check','disputeCheck'),acknowledge=button('cloud_disputes.retry_ack','disputeAcknowledge');
  dialog.setAttribute('aria-labelledby',title.id);message.setAttribute('role','status');dialog.append(title,meta,rounds,accept,form,adminPanel,preview,confirm,message,check,acknowledge,reload,close);document.body.append(dialog);
  const base='/api/auth/'+(admin?'admin/':'')+'ownership-disputes',storageKey='ygc.disputes.uncertain.v1.'+(admin?'admin':'participant');
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null,state()?.user?.role??null]);
  const eligible=()=>Boolean(state()?.user?.app_user_id&&state()?.identity?.email_verified===true&&(!state()?.user?.status||state().user.status==='active')&&(!admin||state().user.role==='admin'));
  let renderedIdentity=identity(),activeAccount=null,accountEpoch=0,navigationEpoch=0,dialogEpoch=0,detailEpoch=0,inputEpoch=0,listEpoch=0,optionEpoch=0;
  let rows=[],candidates=[],caseAfter=null,optionAfter=null,caseHistory=[null],optionHistory=[null],notice='',selected=null,detail=null,option=null,pending=null,stale=false,checked=false;
  const uncertain=new Set(),urls=new Set();
  const context=()=>({account:accountEpoch,identity:identity(),navigation:navigationEpoch,dialog:dialogEpoch,key:selected});
  const current=c=>eligible()&&c.account===accountEpoch&&c.identity===identity()&&c.navigation===navigationEpoch;
  const same=c=>current(c)&&c.dialog===dialogEpoch&&c.key===selected&&dialog.open;
  const unknown=()=>selected!==null&&uncertain.has(selected);
  const writable=()=>eligible()&&!stale&&!unknown()&&(detail||option)?.can_write===true;
  const displayDate=value=>value?new Date(value).toLocaleString(globalThis.YGCI18n.locale):'—';
  const guitarText=value=>['#'+value.id,value.manufacturer,value.model,value.finish,value.year,value.serial_number].filter(v=>v!==null&&v!=='').join(' · ');
  function persist(){try{if(uncertain.size)sessionStorage.setItem(storageKey,JSON.stringify({account:activeAccount,ids:[...uncertain]}));else sessionStorage.removeItem(storageKey);return true}catch{return false}}
  function restore(){if(!eligible()||activeAccount===state().user.app_user_id)return;activeAccount=state().user.app_user_id;uncertain.clear();try{const saved=JSON.parse(sessionStorage.getItem(storageKey)||'null');if(saved===null)return;if(!disputeExact(saved,['account','ids'])||saved.account!==activeAccount||!Array.isArray(saved.ids)||saved.ids.length>100||saved.ids.some(id=>typeof id!=='string'||!/^([co]):[1-9][0-9]*$/.test(id)||!disputeId(id.slice(2))))throw Error('Invalid marker');saved.ids.forEach(id=>uncertain.add(id))}catch{try{sessionStorage.removeItem(storageKey)}catch{}}}
  function person(value){if(!disputeExact(value,['id','display_name','account_type'])||!disputeId(value.id)||!disputeNullable(value.display_name,200)||!disputeNullable(value.account_type,40))throw Error('Invalid participant');return value}
  function guitar(value){if(!disputeExact(value,['id','manufacturer','model','finish','year','serial_number'])||!disputeId(value.id)||['manufacturer','model','finish','year','serial_number'].some(key=>!disputeNullable(value[key],1000)))throw Error('Invalid guitar');return value}
  function candidate(value,id=null){
    const keys=['claim_id','individual','applicant','owner','requested_at','verification_status','decline','eligible','can_acknowledge','can_appeal','wait_until','wait_days','revision','can_write','case_id'];
    if(!disputeExact(value,keys)||!disputeId(value.claim_id)||id!==null&&value.claim_id!==id||!disputeDate(value.requested_at)||!['unverified','negative','positive'].includes(value.verification_status)||!disputeDate(value.wait_until)||!Number.isInteger(value.wait_days)||value.wait_days<0||value.wait_days>36500||!disputeRevision(value.revision)||['eligible','can_acknowledge','can_appeal','can_write'].some(key=>typeof value[key]!=='boolean')||!(value.case_id===null||disputeId(value.case_id)))throw Error('Invalid option');
    guitar(value.individual);person(value.applicant);if(value.owner!==null)person(value.owner);
    if(value.decline!==null&&(!disputeExact(value.decline,['reason','created_at','acknowledged_at'])||!disputeText(value.decline.reason,4000,true)||!disputeDate(value.decline.created_at)||!(value.decline.acknowledged_at===null||disputeDate(value.decline.acknowledged_at))))throw Error('Invalid decline');
    if(value.can_acknowledge&&(!value.decline||value.decline.acknowledged_at!==null)||value.can_appeal&&!value.eligible)throw Error('Invalid eligibility');return value;
  }
  function caseRow(value,keys=disputeCaseKeys){
    if(!disputeExact(value,keys)||['id','individual_id','owner_id','locked_owner_id','version','round_number'].some(key=>!disputeId(value[key]))||!(value.winner_id===null||disputeId(value.winner_id))||!['open','resolved'].includes(value.status)||!['collecting','reviewing'].includes(value.round_phase)||!disputeDate(value.created_at)||!disputeDate(value.updated_at)||![null,'owner','applicant'].includes(value.decision)||!disputeNullable(value.reason,4000,true)||!Array.isArray(value.applicants)||value.applicants.length>100)throw Error('Invalid case');
    guitar(value.individual);person(value.owner);if(value.current_owner!==null)person(value.current_owner);value.applicants.forEach(person);if(value.individual.id!==value.individual_id||value.owner.id!==value.owner_id)throw Error('Mismatched case');return value;
  }
  function caseDetail(value,id=null){
    caseRow(value,[...disputeCaseKeys,'viewer_user_id','can_write','is_admin','can_reopen','claims','round','rounds','evidence','events']);
    if(id!==null&&value.id!==id||!disputeId(value.viewer_user_id)||typeof value.can_write!=='boolean'||value.is_admin!==admin||typeof value.can_reopen!=='boolean'||!Array.isArray(value.claims)||!value.claims.length||value.claims.length>100||!Array.isArray(value.rounds)||!value.rounds.length||value.rounds.length>1000||!Array.isArray(value.evidence)||value.evidence.length>100||!Array.isArray(value.events)||value.events.length>2000)throw Error('Invalid detail');
    for(const row of value.claims)if(!disputeExact(row,['claim_id','applicant_id','applicant_name','decline_reason','requested_at'])||!disputeId(row.claim_id)||!disputeId(row.applicant_id)||!disputeNullable(row.applicant_name,200)||!disputeNullable(row.decline_reason,4000,true)||!disputeDate(row.requested_at))throw Error('Invalid Claim');
    const claims=new Map(value.claims.map(row=>[row.claim_id,row]));if(claims.size!==value.claims.length)throw Error('Duplicate Claim');
    for(const r of value.rounds){
      if(!disputeExact(r,['id','number','phase','request_reason','created_at','parties'])||!disputeId(r.id)||!disputeId(r.number)||!['collecting','reviewing'].includes(r.phase)||!disputeNullable(r.request_reason,4000,true)||!disputeDate(r.created_at)||!Array.isArray(r.parties)||r.parties.length>200)throw Error('Invalid round');
      const seen=new Set();for(const p of r.parties){const key=p.claim_id+':'+p.user_id;if(!disputeExact(p,['claim_id','user_id','display_name','submitted_at','can_submit'])||!claims.has(p.claim_id)||!disputeId(p.user_id)||!disputeNullable(p.display_name,200)||!(p.submitted_at===null||disputeDate(p.submitted_at))||typeof p.can_submit!=='boolean'||seen.has(key)||![value.owner_id,claims.get(p.claim_id).applicant_id].includes(p.user_id)||p.can_submit&&(p.user_id!==value.viewer_user_id||p.submitted_at!==null||r.phase!=='collecting'||value.status!=='open'||r.number!==value.round_number||admin))throw Error('Invalid round party');seen.add(key)}
    }
    if(new Set(value.rounds.map(r=>r.number)).size!==value.rounds.length||value.rounds.some((r,i)=>i>0&&BigInt(value.rounds[i-1].number)>=BigInt(r.number))||JSON.stringify(value.round)!==JSON.stringify(value.rounds.at(-1))||value.round.number!==value.round_number||value.round.phase!==value.round_phase)throw Error('Invalid latest round');
    for(const e of value.evidence){
      const privateKeys=['explanation','summary','filename','content_type','has_attachment'],privateRecord=Object.hasOwn(e,'explanation'),keys=['id','claim_id','author_id','author_name','created_at','published_summary','published_at','round_number','can_publish'];
      if(!disputeExact(e,privateRecord?[...keys,...privateKeys]:keys)||!disputeId(e.id)||!claims.has(e.claim_id)||!disputeId(e.author_id)||!disputeNullable(e.author_name,200)||!disputeDate(e.created_at)||!disputeNullable(e.published_summary,4000,true)||!(e.published_at===null||disputeDate(e.published_at))||!value.rounds.some(r=>r.number===e.round_number)||typeof e.can_publish!=='boolean'||e.can_publish&&(!admin||e.published_at!==null||value.status!=='open'))throw Error('Invalid evidence');
      if(privateRecord){if(!admin&&e.author_id!==value.viewer_user_id||!disputeText(e.explanation,8000,true)||!disputeText(e.summary,4000,true)||!disputeNullable(e.filename,255)||!disputeNullable(e.content_type,100)||typeof e.has_attachment!=='boolean'||e.has_attachment&&!['image/jpeg','application/pdf'].includes(e.content_type))throw Error('Private evidence mismatch')}
      else if(admin||e.author_id===value.viewer_user_id||e.published_summary===null||e.published_at===null)throw Error('Missing private evidence');
      if(!admin&&value.viewer_user_id!==value.owner_id&&claims.get(e.claim_id).applicant_id!==value.viewer_user_id)throw Error('Other applicant evidence');
    }
    if(new Set(value.evidence.map(e=>e.id)).size!==value.evidence.length)throw Error('Duplicate evidence');
    for(const event of value.events)if(!disputeExact(event,['id','kind','note','created_at','round_number'])||!disputeId(event.id)||!['opened','evidence_submitted','under_review','summary_published','request_evidence','resolved','reopened'].includes(event.kind)||!disputeNullable(event.note,4500,true)||!disputeDate(event.created_at)||!value.rounds.some(r=>r.number===event.round_number))throw Error('Invalid event');
    return value;
  }
  function page(value,isOption,after){
    if(!disputeExact(value,['items','next_after','can_write','viewer_user_id'])||!Array.isArray(value.items)||value.items.length>25||typeof value.can_write!=='boolean'||!disputeId(value.viewer_user_id)||!(value.next_after===null||disputeId(value.next_after)))throw Error('Invalid dispute page');
    value.items.forEach(row=>isOption?candidate(row):caseRow(row));const key=isOption?'claim_id':'id';
    if(new Set(value.items.map(row=>row[key])).size!==value.items.length||value.items.some((row,i)=>after!==null&&BigInt(row[key])>=BigInt(after)||i>0&&BigInt(value.items[i-1][key])<=BigInt(row[key]))||value.next_after!==null&&(isOption?(after!==null&&BigInt(value.next_after)>=BigInt(after)||value.items.some(row=>BigInt(row[key])<BigInt(value.next_after))):value.items.at(-1)?.[key]!==value.next_after)||isOption&&value.items.some(row=>row.applicant.id!==value.viewer_user_id))throw Error('Invalid dispute cursor');return value;
  }
  async function request(path='',options={},binary=false){
    const response=await auth().authorizedFetch(base+path,{cache:'no-store',credentials:'omit',redirect:'error',...options},true);
    if(!response.ok){const data=await response.json().catch(()=>({}));throw Object.assign(Error('Dispute request failed'),{status:response.status,code:['service_restricted','dispute_storage_preflight_required'].includes(data?.detail?.code||data?.code)?(data?.detail?.code||data?.code):null})}
    if(binary){const type=response.headers.get('Content-Type')?.split(';')[0];if(!['image/jpeg','application/pdf'].includes(type))throw Error('Invalid attachment');const blob=await response.blob();if(!blob.size||blob.size>12*1024*1024||blob.type!==type)throw Error('Invalid attachment');return {blob,type}}
    return response.json();
  }
  const readKey=key=>key.startsWith('c:')?request('/'+key.slice(2)).then(v=>caseDetail(v,key.slice(2))):request('/options/'+key.slice(2)).then(v=>candidate(v,key.slice(2)));
  const errorText=error=>t(error.code==='dispute_storage_preflight_required'?'cloud_disputes.storage_preflight':error.code==='service_restricted'?'applications.service_restricted':[401,403].includes(error.status)?'self_profile.restricted':error.status===404?'cloud_disputes.unavailable':error.status===409?'cloud_disputes.conflict':[400,422].includes(error.status)?'cloud_disputes.invalid':'cloud_disputes.failed');
  function invalidate(){inputEpoch++;pending=null;preview.replaceChildren();render()}
  function revoke(){for(const url of urls)URL.revokeObjectURL(url);urls.clear()}
  function resetDialog(){dialogEpoch++;detailEpoch++;inputEpoch++;selected=null;detail=option=pending=null;stale=checked=false;revoke();for(const n of [explanation,summary,attachment,reason])n.value='';claim.replaceChildren();winner.replaceChildren();operation.replaceChildren();meta.replaceChildren();rounds.replaceChildren();preview.replaceChildren();message.textContent=''}
  function purge(){listEpoch++;optionEpoch++;rows=[];candidates=[];caseAfter=optionAfter=null;caseHistory=[null];optionHistory=[null];list.replaceChildren();options.replaceChildren();globalThis.YGCOverlays.close(dialog);resetDialog()}
  function clear(){accountEpoch++;uncertain.clear();activeAccount=null;purge();notice='';renderedIdentity=identity();root.hidden=true}
  dialog.addEventListener('ygc:closed',()=>{resetDialog();render()});close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function renderLists(){
    list.replaceChildren();options.replaceChildren();const c=context(),caseRead=listEpoch,optionRead=optionEpoch;
    for(const row of rows){const item=node('li'),open=button('action.detail');item.dataset.disputeCase=row.id;item.append(node('p',guitarText(row.individual)+'\n'+t('cloud_disputes.'+row.status)+' · '+t('cloud_disputes.owner')+': '+row.owner.display_name+'\n'+row.applicants.map(p=>p.display_name).join(', ')+'\n'+t('cloud_disputes.created')+': '+displayDate(row.created_at)+' · '+t('cloud_disputes.updated')+': '+displayDate(row.updated_at)));open.onclick=()=>{if(current(c)&&caseRead===listEpoch)return openDispute(row.id)};item.append(open);list.append(item)}
    for(const row of candidates){const item=node('li'),open=button('action.detail');item.dataset.disputeOption=row.claim_id;item.append(node('p',guitarText(row.individual)+'\n'+t('cloud_disputes.acquire',{id:row.claim_id})+' · '+row.applicant.display_name+'\n'+(row.decline?.reason||t('cloud_disputes.wait_until',{date:displayDate(row.wait_until)}))));open.onclick=()=>{if(current(c)&&optionRead===optionEpoch)return openDisputeOption(row.claim_id)};item.append(open);options.append(item)}
  }
  function render(){
    if(renderedIdentity!==identity())clear();restore();root.hidden=!eligible()||!admin&&!rows.length&&!candidates.length&&optionAfter===null&&optionHistory.length<2&&!notice;
    status.textContent=notice;refreshButton.disabled=busy()||!eligible();filter.disabled=busy()||!eligible();previous.disabled=busy()||!eligible()||caseHistory.length<2;next.disabled=busy()||!eligible()||caseAfter===null;optionPrevious.hidden=optionNext.hidden=admin;optionPrevious.disabled=busy()||!eligible()||optionHistory.length<2;optionNext.disabled=busy()||!eligible()||optionAfter===null;
    for(const b of [...list.querySelectorAll('button'),...options.querySelectorAll('button')])b.disabled=busy()||!eligible();
    const canSubmit=!admin&&(option?.can_appeal===true||detail?.round.parties.some(p=>p.can_submit));form.hidden=!canSubmit;fields.disabled=busy()||!writable();review.disabled=busy()||!writable()||!canSubmit;
    accept.hidden=admin||option?.can_acknowledge!==true;accept.disabled=busy()||!writable();adminPanel.hidden=!admin||!detail;for(const n of [operation,winner,reason,reviewDecision])n.disabled=busy()||!writable()||!operation.children.length;winner.hidden=winnerLabel.hidden=operation.value!=='applicant';
    preview.hidden=!pending;confirm.hidden=!pending;confirm.disabled=busy()||!writable()||!pending;reload.disabled=busy()||!eligible()||!selected;check.hidden=!unknown();check.disabled=busy()||!eligible();acknowledge.hidden=!unknown()||!checked;acknowledge.disabled=busy()||!eligible();
    for(const b of rounds.querySelectorAll('button'))b.disabled=busy()||!eligible()||(b.dataset.disputePublish?!writable():false);
    for(const n of rounds.querySelectorAll('textarea'))n.disabled=busy()||!writable();
  }
  function renderEvidence(e,c,version){
    const section=node('div');section.className='dispute-evidence';if(Object.hasOwn(e,'summary'))section.append(node('p',t('cloud_disputes.submitted_summary')+'\n'+e.summary));if(e.published_summary!==null)section.append(node('p',t('cloud_disputes.published_summary')+'\n'+e.published_summary));
    if(Object.hasOwn(e,'explanation')){const privateView=node('details');privateView.append(node('summary',t('cloud_disputes.private_details')),node('p',e.explanation));if(e.has_attachment){const download=button('cloud_disputes.download');download.dataset.disputeAttachment=e.id;download.onclick=()=>{if(same(c)&&detail?.version===version)return downloadAttachment(e.id)};privateView.append(download)}section.append(privateView)}
    if(admin&&e.can_publish){const pane=node('details'),input=node('textarea','','disputePublishSummary_'+e.id),publish=button('cloud_disputes.review_publish');input.value=e.summary;input.maxLength=8000;publish.dataset.disputePublish=e.id;input.oninput=invalidate;publish.onclick=()=>{if(same(c)&&detail?.version===version)return prepare('publish',{evidence_id:e.id,summary:input.value.trim()})};pane.append(node('summary',t('cloud_disputes.review_publish')),label('cloud_disputes.published_summary',input),input,publish);section.append(pane)}return section;
  }
  function apply(value){
    revoke();pending=null;checked=false;preview.replaceChildren();meta.replaceChildren();rounds.replaceChildren();claim.replaceChildren();winner.replaceChildren();operation.replaceChildren();
    if(selected.startsWith('o:')){option=value;detail=null;meta.append(node('p',guitarText(value.individual)),node('p',t('cloud_disputes.acquire',{id:value.claim_id})+' · '+value.applicant.display_name+'\n'+t('cloud_disputes.owner')+': '+(value.owner?.display_name||'—')+'\n'+t('cloud_disputes.requested')+': '+displayDate(value.requested_at)),node('p',value.decline?.reason||t('cloud_disputes.wait_until',{date:displayDate(value.wait_until)})));if(value.decline?.acknowledged_at)meta.append(node('p',t('cloud_disputes.accepted')+' · '+displayDate(value.decline.acknowledged_at)));const n=node('option',t('cloud_disputes.acquire',{id:value.claim_id}));n.value=value.claim_id;claim.append(n);claim.value=value.claim_id;attachment.required=true}
    else{
      detail=value;option=null;meta.append(node('p',guitarText(value.individual)),node('p',value.claims.map(r=>t('cloud_disputes.acquire',{id:r.claim_id})+' · '+r.applicant_name+' · '+displayDate(r.requested_at)).join('\n')),node('p',t('cloud_disputes.owner')+': '+(value.current_owner?.display_name||'—')+'\n'+t('cloud_disputes.'+(value.status==='resolved'?'resolved':value.round.phase))));
      const c=context();for(const [index,r] of value.rounds.entries()){
        const section=node('section'),timeline=node('ol');section.className='dispute-round';section.append(node('h3',t('cloud_disputes.round',{number:r.number})));
        const entries=value.events.filter(e=>e.round_number===r.number&&!['opened','request_evidence','evidence_submitted','resolved'].includes(e.kind)).map(e=>({at:e.created_at,id:e.id,content:node('p',t('cloud_disputes.event_'+e.kind)+(e.note?'\n'+e.note:''))}));
        for(const p of r.parties){if(p.submitted_at){const content=node('div');content.append(node('p',p.display_name+' · '+t('cloud_disputes.submitted')));for(const e of value.evidence.filter(e=>e.round_number===r.number&&e.claim_id===p.claim_id&&e.author_id===p.user_id))content.append(renderEvidence(e,c,value.version));entries.push({at:p.submitted_at,id:'0',content})}}
        entries.sort((a,b)=>a.at.localeCompare(b.at)||(BigInt(a.id)<BigInt(b.id)?-1:BigInt(a.id)>BigInt(b.id)?1:0));for(const entry of entries){const li=node('li');li.append(node('time',displayDate(entry.at)),entry.content);timeline.append(li)}section.append(timeline);
        const nextRound=value.rounds[index+1],decision=value.events.filter(e=>e.round_number===r.number&&e.kind==='resolved').at(-1);
        if(decision||nextRound||r.phase==='reviewing'||value.status==='resolved'&&index===value.rounds.length-1)section.append(node('p',t('cloud_disputes.review_result')+'\n'+(decision?.note||nextRound?.request_reason||value.status==='resolved'&&value.reason||t('cloud_disputes.pending_decision'))));
        if(index===value.rounds.length-1&&value.status==='open')for(const p of r.parties.filter(p=>!p.submitted_at))section.append(node('p',p.display_name+' · '+t('cloud_disputes.awaiting_submission')));rounds.append(section);
      }
      for(const p of value.round.parties.filter(p=>p.can_submit)){const n=node('option',t('cloud_disputes.acquire',{id:p.claim_id})+' · '+value.claims.find(c=>c.claim_id===p.claim_id).applicant_name);n.value=p.claim_id;claim.append(n)}claim.value=claim.children[0]?.value||'';attachment.required=false;
      for(const c of value.claims){const n=node('option',t('cloud_disputes.acquire',{id:c.claim_id})+' · '+c.applicant_name);n.value=c.claim_id;winner.append(n)}winner.value=winner.children[0]?.value||'';
      const actions=value.status==='open'?['owner','applicant',...(value.round.phase==='reviewing'?['request_evidence']:[])]:value.can_reopen?['reopen']:[];
      for(const action of actions){const n=node('option',t('cloud_disputes.action_'+action));n.value=action;operation.append(n)}operation.value=operation.children[0]?.value||'';
    }
    claimLabel.hidden=claim.hidden=claim.children.length<2;render();
  }
  function action(fn){if(busy()||!eligible())return;return work(async()=>{try{return await fn()}finally{render()}})}
  async function loadList(isOption=false,after=null,path=[null]){
    if(!eligible()||isOption&&admin)return;const c=context(),generation=isOption?++optionEpoch:++listEpoch;
    try{const params=new URLSearchParams({...after?{after}:{},limit:'25',...isOption?{}:{status:admin?filter.value:'open'}}),value=page(await request((isOption?'/options':'')+'?'+params),isOption,after);if(!current(c)||generation!==(isOption?optionEpoch:listEpoch))return;
      if(isOption){candidates=value.items;optionAfter=value.next_after;optionHistory=[...path]}else{rows=value.items;caseAfter=value.next_after;caseHistory=[...path]}
      notice=t('cloud_disputes.count',{count:String(rows.length)})+(value.can_write?'':' '+t('applications.read_only'));if(!admin&&!rows.length&&!candidates.length)notice='';renderLists();
    }catch(error){if(!current(c)||generation!==(isOption?optionEpoch:listEpoch))return;if(isOption){candidates=[];optionAfter=null}else{rows=[];caseAfter=null}if([401,403,404].includes(error.status)&&c.dialog===dialogEpoch){purge();if(admin&&[401,403].includes(error.status)&&error.code!=='service_restricted')onUnauthorized(error)}notice=errorText(error);renderLists()}render();
  }
  async function refresh(){await Promise.all([loadList(),admin?Promise.resolve():loadList(true)])}
  async function failure(error,c){
    if(!same(c))return;pending=null;stale=true;preview.replaceChildren();message.textContent=errorText(error);
    if(error.code==='service_restricted'){try{const value=await readKey(c.key);if(same(c)){apply(value);stale=true;message.textContent=errorText(error)}}catch{if(same(c)){purge();notice=errorText(error)}}}
    else if([401,403,404].includes(error.status)){purge();notice=errorText(error);if(admin&&[401,403].includes(error.status))onUnauthorized(error)}render();
  }
  function open(key){
    if(busy()||!eligible()||!disputeId(key.slice(2))||admin&&key.startsWith('o:'))return;globalThis.YGCOverlays.close(dialog);resetDialog();selected=key;globalThis.YGCOverlays.open(dialog);message.textContent=t('cloud.working');render();const c=context(),read=++detailEpoch;
    return action(async()=>{try{const value=await readKey(key);if(!same(c)||read!==detailEpoch)return;apply(value);message.textContent=unknown()?t('cloud_disputes.uncertain'):value.can_write?'':t('applications.read_only')}catch(error){if(read===detailEpoch)await failure(error,c)}});
  }
  const openDispute=id=>disputeId(id)?open('c:'+id):undefined,openDisputeOption=id=>disputeId(id)?open('o:'+id):undefined;
  async function reloadCurrent(recover=false){
    if(!selected||!dialog.open)return;const c=context(),read=++detailEpoch;pending=null;checked=false;preview.replaceChildren();stale=true;render();
    try{const value=await readKey(c.key);if(!same(c)||read!==detailEpoch)return;apply(value);stale=false;checked=recover;message.textContent=unknown()?t(recover?'cloud_disputes.checked':'cloud_disputes.uncertain'):t('cloud_disputes.review_again')}catch(error){if(read===detailEpoch)await failure(error,c)}render();
  }
  function draft(){const value={claim_id:claim.value,explanation:explanation.value.trim(),summary:summary.value.trim(),file:attachment.files?.[0]||null};if(!disputeId(value.claim_id)||!disputeText(value.explanation,8000,true)||!value.explanation||!disputeText(value.summary,4000,true)||!value.summary||option&&!value.file||attachment.files?.length>1)throw {status:400};if(value.file&&(!['image/jpeg','image/png','image/webp','image/gif','application/pdf'].includes(value.file.type)||value.file.size<=0||value.file.size>12*1024*1024))throw {status:400};return value}
  const token=value=>value?.revision||value?.version;
  function permitted(kind,value,data){if(!value.can_write)return false;if(kind==='accept')return !admin&&value.can_acknowledge===true;if(kind==='submit')return !admin&&(Object.hasOwn(value,'revision')?value.can_appeal===true&&value.claim_id===data.claim_id:value.round.parties.some(p=>p.can_submit&&p.claim_id===data.claim_id&&p.user_id===value.viewer_user_id));if(kind==='publish')return admin&&value.evidence.some(e=>e.id===data.evidence_id&&e.can_publish);return admin&&(value.status==='open'&&['owner','applicant'].includes(data.action)||value.status==='open'&&value.round.phase==='reviewing'&&data.action==='request_evidence'||value.status==='resolved'&&value.can_reopen&&data.action==='reopen')}
  function fingerprint(kind,data){if(kind==='submit'){const current=draft();return current.claim_id===data.claim_id&&current.explanation===data.explanation&&current.summary===data.summary&&current.file===data.file}if(kind==='decision')return operation.value===data.action&&reason.value.trim()===data.reason&&(data.action!=='applicant'||winner.value===data.winner_claim_id);if(kind==='publish')return document.getElementById('disputePublishSummary_'+data.evidence_id)?.value.trim()===data.summary;return true}
  function prepare(kind,data={}){
    if(busy()||!dialog.open||!writable())return;pending=null;preview.replaceChildren();const c=context(),before=token(detail||option),draftEpoch=inputEpoch;
    return action(async()=>{let reading=false;try{
      if(kind==='submit')data=draft();if(kind==='publish'&&(!disputeText(data.summary,4000,true)||!data.summary))throw {status:400};if(kind==='decision'&&(!disputeText(data.reason,4000,true)||!data.reason||data.action==='applicant'&&!disputeId(data.winner_claim_id)))throw {status:400};
      reading=true;const fresh=await readKey(c.key);if(!same(c)||draftEpoch!==inputEpoch)return;if(token(fresh)!==before){apply(fresh);message.textContent=t('cloud_disputes.conflict');return}if(!permitted(kind,fresh,data)){apply(fresh);message.textContent=t('cloud_disputes.unavailable');return}
      // Keep the typed publication field, but replace the authoritative model.
      if(c.key.startsWith('c:'))detail=fresh;else option=fresh;
      pending={kind,data,token:before,round:fresh.round_number||null,key:c.key};preview.replaceChildren(node('h3',t('cloud_disputes.confirm_'+kind)),node('p',kind==='accept'?fresh.decline.reason:kind==='submit'?data.explanation+'\n\n'+data.summary+(data.file?'\n'+data.file.name:''):kind==='publish'?data.summary:t('cloud_disputes.action_'+data.action)+'\n'+data.reason+(data.winner_claim_id?'\n'+t('cloud_disputes.acquire',{id:data.winner_claim_id}):'')));message.textContent=t('cloud_disputes.confirm_help');
    }catch(error){if(!reading&&same(c)){message.textContent=errorText(error)}else await failure(error,c)}});
  }
  form.onsubmit=event=>{event.preventDefault();return prepare('submit')};accept.onclick=()=>prepare('accept');reviewDecision.onclick=()=>prepare('decision',{action:operation.value,reason:reason.value.trim(),winner_claim_id:operation.value==='applicant'?winner.value:null});
  for(const input of [explanation,summary,reason])input.oninput=invalidate;for(const input of [claim,attachment,winner,operation])input.onchange=invalidate;
  confirm.onclick=()=>{
    if(busy()||!dialog.open||!writable()||!pending)return;const saved=pending,c=context(),draftEpoch=inputEpoch,caseRead=listEpoch,optionRead=optionEpoch;pending=null;preview.replaceChildren();
    return action(async()=>{let attempted=false;
      try{
        if(!fingerprint(saved.kind,saved.data)){message.textContent=t('cloud_disputes.review_again');return}const fresh=await readKey(c.key);if(!same(c)||draftEpoch!==inputEpoch)return;if(token(fresh)!==saved.token||fresh.round_number!==undefined&&fresh.round_number!==saved.round||!permitted(saved.kind,fresh,saved.data)){apply(fresh);message.textContent=t('cloud_disputes.conflict');return}
        if(!fingerprint(saved.kind,saved.data)){message.textContent=t('cloud_disputes.review_again');return}
        if(uncertain.size>=100){message.textContent=t('cloud_disputes.storage');return}uncertain.add(c.key);if(!persist()){uncertain.delete(c.key);message.textContent=t('cloud_disputes.storage');return}
        let path,payload,body,headers={'Content-Type':'application/json'};const data=saved.data;
        if(saved.kind==='accept'){path='/options/'+fresh.claim_id+'/acknowledge';payload={revision:fresh.revision}}
        else if(saved.kind==='submit'){path='/options/'+data.claim_id+'/evidence';payload={revision:option?fresh.revision:null,case_id:option?null:fresh.id,version:option?null:fresh.version,round_number:option?null:fresh.round_number,explanation:data.explanation,summary:data.summary};body=new FormData();body.append('data',JSON.stringify(payload));if(data.file)body.append('attachment',data.file);headers={}}
        else if(saved.kind==='publish'){path='/evidence/'+data.evidence_id+'/publish';payload={version:fresh.version,round_number:fresh.round_number,summary:data.summary}}
        else{path='/'+fresh.id+'/decision';payload={version:fresh.version,round_number:fresh.round_number,action:data.action,reason:data.reason,winner_claim_id:data.winner_claim_id}}
        attempted=true;const value=await request(path,{method:'POST',headers,body:body||JSON.stringify(payload)});
        const result=saved.kind==='accept'?(disputeExact(value,['option'])?candidate(value.option,fresh.claim_id):null):(disputeExact(value,['detail'])?caseDetail(value.detail,option?null:fresh.id):null);
        if(!result||saved.kind==='accept'&&(!result.decline?.acknowledged_at||result.can_acknowledge||result.can_appeal)||saved.kind!=='accept'&&token(result)===saved.token||saved.kind==='submit'&&!result.evidence.some(e=>e.claim_id===data.claim_id&&e.author_id===result.viewer_user_id&&e.round_number===result.round_number&&e.summary===data.summary&&e.explanation===data.explanation)||saved.kind==='publish'&&!result.evidence.some(e=>e.id===data.evidence_id&&e.published_summary===data.summary&&e.published_at)||saved.kind==='decision'&&(['owner','applicant'].includes(data.action)?result.status!=='resolved'||result.decision!==data.action:result.status!=='open'||BigInt(result.round_number)<=BigInt(fresh.round_number)))throw Error('Unexpected dispute result');
        if(!current(c))return;uncertain.delete(c.key);persist();if(same(c)){if(saved.kind==='submit'&&option)selected='c:'+result.id;stale=false;apply(result);for(const n of [explanation,summary,attachment,reason])n.value='';message.textContent=t('cloud_disputes.saved')}
        if(caseRead===listEpoch&&optionRead===optionEpoch)await refresh();if(current(c))await updated();
      }catch(error){if(!current(c))return;const definite=[400,401,403,404,409,422].includes(error.status)||error.code==='service_restricted';if(attempted&&!definite){if(same(c)){stale=true;checked=false;message.textContent=t('cloud_disputes.uncertain')}}else{if(attempted){uncertain.delete(c.key);persist()}await failure(error,c)}}
    });
  };
  async function downloadAttachment(id){
    if(busy()||!eligible()||!detail||!detail.evidence.some(e=>e.id===id&&e.has_attachment))return;const c=context(),version=detail.version;
    return action(async()=>{try{const value=await request('/evidence/'+id+'/attachment',{},true);if(!same(c)||detail?.version!==version)return;const url=URL.createObjectURL(value.blob);urls.add(url);const link=node('a',t('cloud_disputes.download'));link.href=url;link.download='evidence-'+id+(value.type==='application/pdf'?'.pdf':'.jpg');document.body.append(link);link.click();link.remove()}catch(error){await failure(error,c)}});
  }
  reload.onclick=()=>action(()=>reloadCurrent());check.onclick=()=>unknown()?action(()=>reloadCurrent(true)):undefined;
  acknowledge.onclick=()=>{if(busy()||!dialog.open||!eligible()||!checked||!unknown()||!(detail||option))return;uncertain.delete(selected);persist();checked=false;stale=false;pending=null;for(const n of [explanation,summary,attachment,reason])n.value='';message.textContent=t('cloud_disputes.review_again');render()};
  refreshButton.onclick=()=>action(refresh);filter.onchange=()=>action(()=>loadList());previous.onclick=()=>{if(caseHistory.length<2)return;const path=caseHistory.slice(0,-1);return action(()=>loadList(false,path.at(-1),path))};next.onclick=()=>caseAfter?action(()=>loadList(false,caseAfter,[...caseHistory,caseAfter])):undefined;
  optionPrevious.onclick=()=>{if(optionHistory.length<2)return;const path=optionHistory.slice(0,-1);return action(()=>loadList(true,path.at(-1),path))};optionNext.onclick=()=>optionAfter?action(()=>loadList(true,optionAfter,[...optionHistory,optionAfter])):undefined;
  globalThis.addEventListener('popstate',()=>{navigationEpoch++;purge();notice='';render()});globalThis.addEventListener('pagehide',()=>{navigationEpoch++;purge();notice=''});
  render();return {render,clear,refresh,openDispute,openDisputeOption};
}
