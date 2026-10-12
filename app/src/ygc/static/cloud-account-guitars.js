import {createOwnerAcquireInbox} from './cloud-owner-acquire-inbox.js';
import {createProfileList} from './cloud-profile-list.js';
import {createPrivateMedia} from './cloud-account-media.js';
export function createGuitars({auth,state,busy,work,openOwnership,root:providedRoot,inboxRoot=null,tableLayout=false,onSelect,onTotal=()=>{},onOwnerSaved=async()=>{}}){
  const formal=tableLayout||Boolean(providedRoot),root=providedRoot||document.getElementById('selfGuitars'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  let epoch=0,pending=null,canWrite=null,ownerId=null,focusedClaim=null,dialogEpoch=0,rowsEpoch=0,mediaEpoch=0,navigationEpoch=0;
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  let renderedIdentity=identity();const mediaViews=new Set();
  function clearPhotos(){mediaEpoch++;for(const viewer of mediaViews)viewer.clear();mediaViews.clear()}
  const dialog=document.createElement(formal?'div':'dialog'),title=document.createElement('h2'),warning=document.createElement('p'),claims=document.createElement('div'),message=document.createElement('p'),close=document.createElement('button');
  dialog.id='ownerResponseDialog';title.id='ownerResponseTitle';dialog.setAttribute('aria-labelledby',title.id);title.textContent=t('owner.heading');warning.textContent=t('owner.warning');message.setAttribute('role','status');close.type='button';close.textContent=t('action.close');
  const reload=document.createElement('button');reload.type='button';reload.textContent=t('action.refresh');reload.hidden=true;reload.id='ownerMediaReload';
  const reviewPanel=formal?document.createElement('div'):dialog;
  if(formal){dialog.className='modal-backdrop';reviewPanel.className='claim-popup-modal';dialog.append(reviewPanel);Object.defineProperty(dialog,'open',{get:()=>dialog.classList.contains('open')});title.hidden=warning.hidden=close.hidden=true}
  reviewPanel.append(title,warning,claims,message,close,reload);document.body.append(dialog);
  reload.onclick=()=>{if(!busy()&&eligible()&&ownerId&&dialog.open)return openOwner(ownerId,focusedClaim)};
  close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  dialog.addEventListener('ygc:closed',()=>{dialogEpoch++;rowsEpoch++;clearPhotos();reload.hidden=true;pending=null;canWrite=null;ownerId=null;focusedClaim=null;claims.replaceChildren();message.textContent=''});
  async function ownerRequest(path,options={}){
    const response=await auth().authorizedFetch('/api/auth/guitars/'+path,{cache:'no-store',credentials:'omit',redirect:'error',...options},Boolean(options.method&&!['GET','HEAD'].includes(options.method.toUpperCase())));
    if(!response.ok){const detail=await response.json().catch(()=>({}));throw Object.assign(Error('Owner response unavailable'),{status:response.status,code:detail.detail?.code})}return response.json();
  }
  function ownerAction(fn){
    if(busy()||!eligible())return;const version=epoch,editor=dialogEpoch,actor=identity(),valid=()=>version===epoch&&editor===dialogEpoch&&actor===identity();
    return work(async()=>{
      try{await fn(version)}catch(error){
        if(!valid())return;
        if(error.code==='service_restricted'&&[403,503].includes(error.status)&&ownerId&&dialog.open){
          // Service mode may change after the review list was opened. Retain
          // its private contents only after a fresh successful authorized read.
          canWrite=false;pending=null;clearPhotos();
          for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true;
          try{
            const currentId=ownerId,result=await ownerRequest(currentId+'/owner-responses');
            if(!valid()||!eligible()||currentId!==ownerId||!dialog.open)return;
            renderOwnerRows(currentId,result,true);message.textContent=t('applications.service_restricted');
          }catch{if(valid()){clearPhotos();claims.replaceChildren();canWrite=null;reload.hidden=false;message.textContent=t('self_profile.restricted')}}
        }else{
          message.textContent=t(error.status===409?'chronicle.decision_conflict':error.status===403?'self_profile.restricted':'chronicle.decision_unavailable');
          // A failed read or uncertain decision must never leave an old
          // approval live. Keep an explicit refresh path even on transport errors.
          clearPhotos();canWrite=null;pending=null;reload.hidden=false;
          for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true;
          if([401,403,404].includes(error.status))claims.replaceChildren();
        }
      }finally{render()}
    });
  }
  function openOwner(id,claimId=null,stance=null,opener=null){
    if(busy()||!eligible())return;
    dialogEpoch++;rowsEpoch++;clearPhotos();pending=null;canWrite=null;ownerId=id;focusedClaim=claimId;reload.hidden=true;claims.replaceChildren();message.textContent=t('cloud.working');globalThis.YGCOverlays.open(dialog);
    const editor=dialogEpoch,actor=identity();
    return ownerAction(async version=>{
      const result=await ownerRequest(id+'/owner-responses');if(version!==epoch||editor!==dialogEpoch||actor!==identity()||ownerId!==id||!eligible()||!dialog.open)return;
      if(claimId!==null&&!result.items.some(row=>row.id===claimId)){claims.replaceChildren();canWrite=null;message.textContent=t('notifications.unavailable');return}
      renderOwnerRows(id,formal&&claimId!==null?{...result,items:result.items.filter(row=>row.id===claimId)}:result);if(formal){const trigger=opener||document.querySelector('#chronicleEntries');globalThis.YGCOwnershipPresentation.positionClaimPopup(trigger,'ownerResponseDialog')}
    }).then(()=>{if(formal&&stance&&editor===dialogEpoch&&actor===identity()&&dialog.open){const select=claims.querySelector('select');if(select){select.value=stance;select.onchange()}}});
  }
  async function photoError(id,error,valid){
    if(!valid())return;
    pending=null;canWrite=null;rowsEpoch++;clearPhotos();claims.replaceChildren();reload.hidden=false;message.textContent=t('claims.media_failed');render();
    // Do not keep private bytes or an approval from a revoked/stale image read.
    // Refresh the review list once; loading images again requires a new click.
    if(![401,403,404,409].includes(error.status))return;
    const version=epoch,editor=dialogEpoch,actor=identity(),read=rowsEpoch;
    try{
      const result=await ownerRequest(id+'/owner-responses');
      if(version!==epoch||editor!==dialogEpoch||actor!==identity()||read!==rowsEpoch||ownerId!==id||!eligible()||!dialog.open)return;
      renderOwnerRows(id,result,false,true);message.textContent=t('claims.media_stale');reload.hidden=false;render();
    }catch{if(version===epoch&&editor===dialogEpoch&&actor===identity()&&read===rowsEpoch){canWrite=null;message.textContent=t('self_profile.restricted');render()}}
  }
  function renderOwnerRows(id,result,preserve=false,photosStale=false){
    if(formal&&focusedClaim!==null)result={...result,items:result.items.filter(row=>row.id===focusedClaim)};
    rowsEpoch++;clearPhotos();pending=null;const version=epoch,editor=dialogEpoch,actor=identity(),read=rowsEpoch;
    const valid=()=>version===epoch&&editor===dialogEpoch&&actor===identity()&&read===rowsEpoch&&ownerId===id&&dialog.open&&eligible();
    canWrite=result.can_write===true;message.textContent=!canWrite?t('applications.read_only'):result.items.length?'':t('owner.empty');
    const previous=new Map(preserve?Array.from(claims.children).filter(card=>!card._media).map(card=>[card._claimId+':'+card._revision,card]):[]);
    claims.replaceChildren();
    for(const row of result.items){
      const existing=previous.get(row.id+':'+row.revision);if(existing){existing._current=valid;for(const button of existing.querySelectorAll('[data-owner-confirm]'))button.hidden=true;claims.append(existing);continue}
      const card=document.createElement('section'),description=document.createElement('p'),select=document.createElement('select'),review=document.createElement('button'),confirm=document.createElement('button'),reasonLabel=document.createElement('label'),reason=document.createElement('textarea'),reasonHelp=document.createElement('p');
      // Only an explicit empty Event attachment list is text-only. Missing
      // or malformed lists must go through the photo gate and fail closed.
      card._current=valid;const cardValid=()=>card._current();card._claimId=row.id;card._revision=row.revision;card._media=row.claim_type==='media'||row.claim_type==='event'&&(!Array.isArray(row.media_items)||row.media_items.length>0);card._mediaReady=!card._media;
      description.textContent=['#'+row.id,row.author_name,row.claim_type,row.specification_kind,row.ownership_kind,row.claim_type==='event'?t('claims.event_'+(row.event_kind||row.value_text)):null,row.occurred_at,row.created_at?t('claims.created')+': '+row.created_at:null,row.updated_at?t('claims.updated')+': '+row.updated_at:null,...(row.spec_items?.length?row.spec_items.map(item=>item.field_name+': '+item.value_text):row.claim_type==='event'?[]:[row.field_name,row.value_text]),row.body].filter(Boolean).join(' · ');
      if(formal){card.className='claim-card claim-type-'+row.claim_type;select.className='claim-response-select'}
      select.setAttribute('aria-label',t('owner.decision'));for(const stance of ['positive','negative','unverified']){const option=document.createElement('option');option.value=stance;option.textContent=t('chronicle.'+stance);select.append(option)}select.value=row.verification_status;
      review.type=confirm.type='button';review.textContent=t('owner.review');confirm.textContent=t('chronicle.apply_decision');confirm.hidden=true;
      reason.id='ownerDeclineReason_'+row.id;reason.maxLength=4000;reasonLabel.setAttribute('for',reason.id);reasonLabel.textContent=t('owner.decline_reason');reasonHelp.id=reason.id+'_help';reasonHelp.textContent=t('owner.decline_reason_help');reason.setAttribute('aria-describedby',reasonHelp.id);
      const needsReason=()=>row.decline_reason_required===true&&select.value==='negative';
      const reasonVisibility=()=>{reasonLabel.hidden=reason.hidden=reasonHelp.hidden=!needsReason();reason.required=needsReason()};reasonVisibility();
      const invalidate=()=>{pending=null;for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true;message.textContent=''};
      review.onclick=()=>{if(busy()||!eligible()||!canWrite||!cardValid()||!card._mediaReady)return;invalidate();if(needsReason()&&(!reason.value.trim()||reason.value.trim().length>4000)){message.textContent=t('owner.decline_reason_required');reason.focus();return}pending={id,claim:row.id,revision:row.revision,stance:select.value,...(needsReason()?{reason:reason.value.trim()}:{})};confirm.hidden=false;message.textContent=t('owner.confirm',{id:row.id,state:t('chronicle.'+select.value)})+(pending.reason?' '+t('owner.decline_reason_confirm',{reason:pending.reason}):'')};
      select.onchange=()=>{invalidate();reasonVisibility();if(formal&&!card._mediaReady)select.value=row.verification_status;if(formal&&card._mediaReady){if(needsReason()){review.hidden=false;reason.focus();return}review.hidden=true;review.onclick();if(pending)confirm.onclick()}};reason.oninput=invalidate;confirm.dataset.ownerConfirm='true';
      confirm.onclick=()=>{if(busy()||!canWrite||!eligible()||!cardValid()||!card._mediaReady||!pending||pending.claim!==row.id)return;const saved={...pending},actor=identity(),navigation=navigationEpoch;pending=null;ownerAction(async current=>{
        await ownerRequest(saved.id+'/owner-responses/'+saved.claim,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stance:saved.stance,revision:saved.revision,...(saved.reason?{reason:saved.reason}:{})})});
        // Dismissal invalidates the private review, not a completed ownership
        // mutation. Refresh its account lists without closing a newer dialog.
        if(current!==epoch||actor!==identity()||navigation!==navigationEpoch||!eligible())return;
        if(cardValid())globalThis.YGCOverlays.close(dialog);
        for(const panel of Object.values(panels))panel.history=[0];
        if(!providedRoot)await Promise.all(['owned','formerly_owned'].map(page));await inbox?.refresh();await onOwnerSaved(saved.id);
      })};if(formal){
        const head=document.createElement('div'),badge=document.createElement('span'),date=document.createElement('span');head.className='claim-head';badge.className='claim-badge';badge.textContent=row.ownership_kind==='acquire'?t('ui.acquire_910e23d5'):t('claims.'+(row.claim_type==='specification'?(row.specification_kind||'specification'):row.claim_type==='ownership'?(row.ownership_kind||'ownership'):row.claim_type));date.className='claim-event-date';date.textContent=globalThis.YGCOwnershipPresentation.displayEventDate(row.occurred_at);head.append(badge,select,date);description.className='claim-body';description.replaceChildren();
        for(const item of row.spec_items||[]){const line=document.createElement('div'),strong=document.createElement('strong');strong.textContent=globalThis.YGCOwnershipPresentation.specificationFieldLabel(item.field_name)+': '+item.value_text;line.append(strong);description.append(line)}
        if(row.body){const memo=document.createElement('div');memo.className='claim-memo';memo.textContent=row.body;description.append(memo)}
        const footer=document.createElement('div');footer.className='claim-footer';const author=document.createElement('div');author.className='claim-footer-meta';author.textContent=globalThis.YGCOwnershipPresentation.displayInputDate(row.created_at)+' · By '+row.author_name;footer.append(author);card.append(head,description,footer);review.hidden=true;
      }else card.append(description,select,review);if(formal)card.append(reasonLabel,reason,reasonHelp,review,confirm);else card.append(confirm,reasonLabel,reason,reasonHelp);claims.append(card);
      if(card._media){
        const privacy=document.createElement('p'),photos=document.createElement('div'),photoStatus=document.createElement('p'),viewPhotos=document.createElement('button');privacy.textContent=t('claims.media_private');photos.className='claim-media-photos';photoStatus.setAttribute('role','status');photoStatus.textContent=t(photosStale?'claims.media_stale':'claims.media_view_help');
        viewPhotos.type='button';viewPhotos.textContent=t('claims.media_view');viewPhotos.dataset.ownerMediaView='true';card.append(privacy,photoStatus,photos,viewPhotos);
        // The Owner list is not paginated. Never fetch every Claim's photos:
        // one explicit selection owns the only live viewer and its requests.
        viewPhotos.onclick=()=>{
          if(busy()||!eligible()||!cardValid()||card._mediaLoading)return;
          invalidate();clearPhotos();const selection=mediaEpoch,mediaCurrent=()=>cardValid()&&selection===mediaEpoch;
          card._mediaLoading=true;photoStatus.textContent=t('claims.media_loading');viewPhotos.disabled=true;
          const viewer=createPrivateMedia({auth,container:photos,isCurrent:mediaCurrent,onState:ready=>{
            card._mediaReady=ready;
            if(ready){card._mediaLoading=false;photoStatus.textContent=''}
            else if(!mediaCurrent()){card._mediaLoading=false;photoStatus.textContent=t('claims.media_view_help')}
            viewPhotos.disabled=busy()||!eligible()||card._mediaLoading;
            for(const control of [select,review,confirm,reason])control.disabled=busy()||!eligible()||!canWrite||!ready;
          },onError:error=>{card._mediaLoading=false;photoError(id,error,mediaCurrent)}});
          mediaViews.add(viewer);viewer.load(id,row);
        };
      }

    }
  }

  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true&&(!state().user.status||state().user.status==='active'));
  const inbox=inboxRoot?createOwnerAcquireInbox({root:inboxRoot,auth,state,busy,openOwner}):null;
  const panels={};
  for(const kind of ['owned','formerly_owned']){
    const section=document.createElement('section'),title=document.createElement('h2'),status=document.createElement('p'),list=document.createElement(tableLayout?'tbody':'ul');
    section.id='selfGuitars_'+kind;title.textContent=t(tableLayout?(kind==='owned'?'ui.owned_guitars_bb07d3cd':'ui.formerly_owned_guitars_0769f4fa'):'users.'+kind);status.className='self-guitar-status';status.setAttribute('role','status');list.className='self-guitar-list';
    const refresh=document.createElement('button'),previous=document.createElement('button'),next=document.createElement('button');
    for(const [button,key] of [[refresh,'action.refresh'],[previous,'users.previous'],[next,'users.next']]){button.type='button';button.textContent=t(key)}
    list.id='profileRows-'+kind;
    let presentation=null;
    if(tableLayout){
      presentation=createProfileList({section,title,list,onSelect,guitarHref:id=>'/ui/profile/guitars/'+id,auth,state,busy});
      section.append(status);refresh.hidden=previous.hidden=next.hidden=true;
    }else section.append(title,status,list,refresh,previous,next);root.append(section);
    panels[kind]={status,list,refresh,previous,next,history:[0],nextAfter:null,read:0,presentation,rows:[]};
    refresh.onclick=()=>{if(busy())return;panels[kind].history=[0];work(()=>page(kind))};
    previous.onclick=()=>{const panel=panels[kind];if(busy()||panel.history.length<2)return;panel.history.pop();work(()=>page(kind))};
    next.onclick=()=>{const panel=panels[kind];if(busy()||panel.nextAfter===null)return;panel.history.push(panel.nextAfter);work(()=>page(kind))};
  }
  function render(){
    if(renderedIdentity!==identity()){renderedIdentity=identity();clear()}
    inbox?.render();root.hidden=!eligible();
    for(const panel of Object.values(panels)){
      panel.presentation?.renderControls();panel.refresh.disabled=busy()||!eligible();panel.previous.disabled=busy()||!eligible()||panel.history.length<2;panel.next.disabled=busy()||!eligible()||panel.nextAfter===null;
    }
    for(const button of [...root.querySelectorAll("li button"),...(tableLayout?root.querySelectorAll("tr button"):[])] )button.disabled=busy()||!eligible();
    for(const card of claims.children)for(const control of card.querySelectorAll("button,select,textarea"))control.disabled=busy()||!eligible()||(control.dataset.ownerMediaView?card._mediaLoading===true:!canWrite||card._mediaReady===false);
    reload.disabled=busy()||!eligible();
    if(!eligible())clear();
  }
  function clear(){inbox?.clear();renderedIdentity=identity();epoch++;dialogEpoch++;rowsEpoch++;clearPhotos();globalThis.YGCOverlays.close(dialog);pending=null;canWrite=null;claims.replaceChildren();for(const panel of Object.values(panels)){panel.history=[0];panel.nextAfter=null;panel.list.replaceChildren();panel.rows=[];panel.presentation?.clear();panel.status.textContent=''}for(const kind of Object.keys(panels))onTotal(kind,null)}
  async function page(kind){
    const current=epoch,panel=panels[kind],owner=state()?.user?.app_user_id,read=++panel.read;
    onTotal(kind,null);panel.rows=[];panel.presentation?.clear();panel.list.replaceChildren();panel.nextAfter=null;panel.status.textContent=t('cloud.working');
    try{
      let after=panel.history.at(-1),data,all=[];const seen=new Set();
      do{
        const params=new URLSearchParams({kind,limit:'25'});if(after)params.set('after',after);
        const response=await auth().authorizedFetch('/api/auth/guitars?'+params,{},false);
        if(!response.ok)throw Object.assign(Error('Ownership unavailable'),{status:response.status});
        data=await response.json();if(current!==epoch||read!==panel.read||owner!==state()?.user?.app_user_id||!eligible())return;
        if(typeof data.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(data.total)||!Array.isArray(data.items)||data.items.length>25||!(data.next_after===null||typeof data.next_after==='string'&&/^[1-9][0-9]*$/.test(data.next_after))||data.items.some(row=>!row||typeof row.id!=='string'||!/^[1-9][0-9]*$/.test(row.id)))throw Error('Invalid ownership page');
        for(const row of data.items){if(BigInt(row.id)<=BigInt(after||0)||seen.has(row.id))throw Error('Invalid ownership cursor');seen.add(row.id)}
        if(data.next_after!==null&&(!data.items.length||data.next_after!==data.items.at(-1).id))throw Error('Invalid ownership cursor');
        all.push(...data.items);after=data.next_after;
      }while(tableLayout&&after!==null);
      data={...data,items:all};
      panel.rows=data.items;if(tableLayout)panel.presentation.setRows(data.items);
      if(!tableLayout)for(const row of data.items){const item=document.createElement('li');item.textContent='#'+row.id+' · '+[row.manufacturer,row.model,row.year,row.serial_number].map(value=>value??'—').join(' · ');if(kind==='owned'){const approve=document.createElement('button');approve.type='button';approve.textContent=t('owner.heading');approve.onclick=()=>openOwner(row.id);item.append(approve)}if(openOwnership){const ownership=document.createElement('button');ownership.type='button';ownership.textContent=t('ownership.manage');ownership.onclick=()=>openOwnership(row.id);item.append(ownership)}panel.list.append(item)}
      onTotal(kind,data.total);panel.nextAfter=data.next_after;panel.status.textContent=tableLayout?'':t(data.total==='0'?'users.ownership_empty':'guitars.total_count',{count:data.total});
    }catch(error){
      if(current!==epoch||read!==panel.read||owner!==state()?.user?.app_user_id||!eligible())return;
      if([401,403].includes(error.status)){
        clear();for(const item of Object.values(panels))item.status.textContent=t('self_profile.restricted');
      }else{
        panel.history=[0];panel.list.replaceChildren();panel.presentation?.clear();panel.status.textContent=t('users.ownership_unavailable');
      }
    }
    render();
  }
  async function refreshHistory(){
    for(const panel of Object.values(panels))panel.history=[0];
    await Promise.all([...['owned','formerly_owned'].map(page),inbox?.refresh()]);
  }
  async function refresh(){
    if(dialog.open)globalThis.YGCOverlays.close(dialog);epoch++;for(const panel of Object.values(panels))panel.history=[0];
    await Promise.all([...['owned','formerly_owned'].map(page),inbox?.refresh()]);
  }
  globalThis.addEventListener('pagehide',clear);globalThis.addEventListener('popstate',()=>{navigationEpoch++;if(dialog.open)globalThis.YGCOverlays.close(dialog)});
  function selectedActions(id){
    if(!eligible()||!Object.values(panels).some(panel=>panel.rows.some(row=>row.id===id)))return null;
    const root=document.createElement('div');root.id='formalOwnershipActions';
    if(!tableLayout&&panels.owned.rows.some(row=>row.id===id)){const review=document.createElement('button');review.type='button';review.textContent=t('owner.heading');review.disabled=busy();review.onclick=()=>openOwner(id);root.append(review)}
    if(openOwnership&&panels.owned.rows.some(row=>row.id===id)){const manage=document.createElement('button');manage.type='button';manage.textContent=t('ui.ownership_c7d3acc8');manage.dataset.ownershipEntry='';manage.disabled=busy();manage.onclick=()=>{document.getElementById('addClaimMenu')?.classList.remove('open');return openOwnership(id)};root.append(manage)}
    return root;
  }
  async function readActions(id){
    if(!eligible()||!providedRoot&&!panels.owned.rows.some(row=>row.id===id))return [];
    const version=epoch,actor=identity(),navigation=navigationEpoch;
    if(providedRoot){
      let ownership;
      try{ownership=await ownerRequest(id+'/ownership')}
      catch(error){if(error.status===404)return [];throw error}
      if(version!==epoch||actor!==identity()||navigation!==navigationEpoch||!eligible()||ownership.is_current_owner!==true)return [];
    }
    const result=await ownerRequest(id+'/owner-responses');
    if(version!==epoch||actor!==identity()||navigation!==navigationEpoch||!eligible())return [];
    return result.items.map(row=>({...row,can_write:result.can_write===true}));
  }
  return {render,refresh,refreshInbox:()=>inbox?.refresh(),refreshHistory,clear,openOwner,selectedActions,readActions};
}
