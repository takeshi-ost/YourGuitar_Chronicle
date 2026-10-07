import {createPrivateMedia} from './cloud-account-media.js';
export function createGuitars({auth,state,busy,work}){
  const root=document.getElementById('selfGuitars'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  let epoch=0,pending=null,canWrite=null,ownerId=null,dialogEpoch=0,rowsEpoch=0,mediaEpoch=0;
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  let renderedIdentity=identity();const mediaViews=new Set();
  function clearPhotos(){mediaEpoch++;for(const viewer of mediaViews)viewer.clear();mediaViews.clear()}
  const dialog=document.createElement('dialog'),title=document.createElement('h2'),warning=document.createElement('p'),claims=document.createElement('div'),message=document.createElement('p'),close=document.createElement('button');
  dialog.id='ownerResponseDialog';title.id='ownerResponseTitle';dialog.setAttribute('aria-labelledby',title.id);title.textContent=t('owner.heading');warning.textContent=t('owner.warning');message.setAttribute('role','status');close.type='button';close.textContent=t('action.close');
  const reload=document.createElement('button');reload.type='button';reload.textContent=t('claims.media_reload');reload.hidden=true;reload.id='ownerMediaReload';
  dialog.append(title,warning,claims,message,close,reload);document.body.append(dialog);
  reload.onclick=()=>{if(!busy()&&eligible()&&ownerId&&dialog.open)return openOwner(ownerId)};
  close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  dialog.addEventListener('ygc:closed',()=>{dialogEpoch++;rowsEpoch++;clearPhotos();reload.hidden=true;pending=null;canWrite=null;ownerId=null;claims.replaceChildren();message.textContent=''});
  async function ownerRequest(path,options={}){
    const response=await auth().authorizedFetch('/api/auth/guitars/'+path,{cache:'no-store',credentials:'omit',redirect:'error',...options},true);
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
          }catch{if(valid()){clearPhotos();claims.replaceChildren();canWrite=null;message.textContent=t('self_profile.restricted')}}
        }else{
          message.textContent=t(error.status===409?'chronicle.decision_conflict':error.status===403?'self_profile.restricted':'chronicle.decision_unavailable');
          if([401,403,404].includes(error.status)){clearPhotos();claims.replaceChildren();pending=null;canWrite=null}
          else if(error.status===409){clearPhotos();canWrite=null;pending=null;reload.hidden=false;for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true}
        }
      }finally{render()}
    });
  }
  function openOwner(id){
    if(busy()||!eligible())return;
    dialogEpoch++;rowsEpoch++;clearPhotos();pending=null;canWrite=null;ownerId=id;reload.hidden=true;claims.replaceChildren();message.textContent=t('cloud.working');globalThis.YGCOverlays.open(dialog);
    const editor=dialogEpoch,actor=identity();
    return ownerAction(async version=>{
      const result=await ownerRequest(id+'/owner-responses');if(version!==epoch||editor!==dialogEpoch||actor!==identity()||ownerId!==id||!eligible()||!dialog.open)return;
      renderOwnerRows(id,result);
    });
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
    rowsEpoch++;clearPhotos();pending=null;const version=epoch,editor=dialogEpoch,actor=identity(),read=rowsEpoch;
    const valid=()=>version===epoch&&editor===dialogEpoch&&actor===identity()&&read===rowsEpoch&&ownerId===id&&dialog.open&&eligible();
    canWrite=result.can_write===true;message.textContent=!canWrite?t('applications.read_only'):result.items.length?'':t('owner.empty');
    const previous=new Map(preserve?Array.from(claims.children).filter(card=>!card._media).map(card=>[card._claimId+':'+card._revision,card]):[]);
    claims.replaceChildren();
    for(const row of result.items){
      const existing=previous.get(row.id+':'+row.revision);if(existing){existing._current=valid;for(const button of existing.querySelectorAll('[data-owner-confirm]'))button.hidden=true;claims.append(existing);continue}
      const card=document.createElement('section'),description=document.createElement('p'),select=document.createElement('select'),review=document.createElement('button'),confirm=document.createElement('button'),reasonLabel=document.createElement('label'),reason=document.createElement('textarea'),reasonHelp=document.createElement('p');
      card._current=valid;const cardValid=()=>card._current();card._claimId=row.id;card._revision=row.revision;card._media=row.claim_type==='media';card._mediaReady=!card._media;
      description.textContent=['#'+row.id,row.author_name,row.claim_type,row.specification_kind,row.ownership_kind,row.occurred_at,row.created_at?t('claims.created')+': '+row.created_at:null,row.updated_at?t('claims.updated')+': '+row.updated_at:null,...(row.spec_items?.length?row.spec_items.map(item=>item.field_name+': '+item.value_text):[row.field_name,row.value_text]),row.body].filter(Boolean).join(' · ');
      select.setAttribute('aria-label',t('owner.decision'));for(const stance of ['positive','negative','unverified']){const option=document.createElement('option');option.value=stance;option.textContent=t('chronicle.'+stance);select.append(option)}select.value=row.verification_status;
      review.type=confirm.type='button';review.textContent=t('owner.review');confirm.textContent=t('chronicle.apply_decision');confirm.hidden=true;
      reason.id='ownerDeclineReason_'+row.id;reason.maxLength=4000;reasonLabel.setAttribute('for',reason.id);reasonLabel.textContent=t('owner.decline_reason');reasonHelp.id=reason.id+'_help';reasonHelp.textContent=t('owner.decline_reason_help');reason.setAttribute('aria-describedby',reasonHelp.id);
      const needsReason=()=>row.decline_reason_required===true&&select.value==='negative';
      const reasonVisibility=()=>{reasonLabel.hidden=reason.hidden=reasonHelp.hidden=!needsReason();reason.required=needsReason()};reasonVisibility();
      const invalidate=()=>{pending=null;for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true;message.textContent=''};
      review.onclick=()=>{if(busy()||!eligible()||!canWrite||!cardValid()||!card._mediaReady)return;invalidate();if(needsReason()&&(!reason.value.trim()||reason.value.trim().length>4000)){message.textContent=t('owner.decline_reason_required');reason.focus();return}pending={id,claim:row.id,revision:row.revision,stance:select.value,...(needsReason()?{reason:reason.value.trim()}:{})};confirm.hidden=false;message.textContent=t('owner.confirm',{id:row.id,state:t('chronicle.'+select.value)})+(pending.reason?' '+t('owner.decline_reason_confirm',{reason:pending.reason}):'')};
      select.onchange=()=>{invalidate();reasonVisibility()};reason.oninput=invalidate;confirm.dataset.ownerConfirm='true';
      confirm.onclick=()=>{if(busy()||!canWrite||!eligible()||!cardValid()||!card._mediaReady||!pending||pending.claim!==row.id)return;const saved={...pending};pending=null;ownerAction(async current=>{
        await ownerRequest(saved.id+'/owner-responses/'+saved.claim,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stance:saved.stance,revision:saved.revision,...(saved.reason?{reason:saved.reason}:{})})});
        if(current!==epoch||!cardValid())return;globalThis.YGCOverlays.close(dialog);await refresh();
      })};card.append(description,select,review,confirm,reasonLabel,reason,reasonHelp);claims.append(card);
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
  const panels={};
  for(const kind of ['owned','formerly_owned']){
    const section=document.createElement('section'),title=document.createElement('h2'),status=document.createElement('p'),list=document.createElement('ul');
    section.id='selfGuitars_'+kind;title.textContent=t('users.'+kind);status.className='self-guitar-status';status.setAttribute('role','status');list.className='self-guitar-list';
    const refresh=document.createElement('button'),previous=document.createElement('button'),next=document.createElement('button');
    for(const [button,key] of [[refresh,'action.refresh'],[previous,'users.previous'],[next,'users.next']]){button.type='button';button.textContent=t(key)}
    section.append(title,status,list,refresh,previous,next);root.append(section);
    panels[kind]={status,list,refresh,previous,next,history:[0],nextAfter:null};
    refresh.onclick=()=>{if(busy())return;panels[kind].history=[0];work(()=>page(kind))};
    previous.onclick=()=>{const panel=panels[kind];if(busy()||panel.history.length<2)return;panel.history.pop();work(()=>page(kind))};
    next.onclick=()=>{const panel=panels[kind];if(busy()||panel.nextAfter===null)return;panel.history.push(panel.nextAfter);work(()=>page(kind))};
  }
  function render(){
    if(renderedIdentity!==identity()){renderedIdentity=identity();clear()}
    root.hidden=!eligible();
    for(const panel of Object.values(panels)){
      panel.refresh.disabled=busy()||!eligible();panel.previous.disabled=busy()||!eligible()||panel.history.length<2;panel.next.disabled=busy()||!eligible()||panel.nextAfter===null;
    }
    for(const button of root.querySelectorAll("li button"))button.disabled=busy()||!eligible();
    for(const card of claims.children)for(const control of card.querySelectorAll("button,select,textarea"))control.disabled=busy()||!eligible()||(control.dataset.ownerMediaView?card._mediaLoading===true:!canWrite||card._mediaReady===false);
    reload.disabled=busy()||!eligible();
    if(!eligible())clear();
  }
  function clear(){renderedIdentity=identity();epoch++;dialogEpoch++;rowsEpoch++;clearPhotos();globalThis.YGCOverlays.close(dialog);pending=null;canWrite=null;claims.replaceChildren();for(const panel of Object.values(panels)){panel.history=[0];panel.nextAfter=null;panel.list.replaceChildren();panel.status.textContent=''}}
  async function page(kind){
    const current=epoch,panel=panels[kind],owner=state()?.user?.app_user_id;
    panel.list.replaceChildren();panel.nextAfter=null;panel.status.textContent=t('cloud.working');
    try{
      const params=new URLSearchParams({kind,limit:'25'}),after=panel.history.at(-1);if(after)params.set('after',after);
      const response=await auth().authorizedFetch('/api/auth/guitars?'+params,{},true);
      if(!response.ok)throw Object.assign(Error('Ownership unavailable'),{status:response.status});
      const data=await response.json();if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;
      if(typeof data.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(data.total)||!Array.isArray(data.items)||data.items.length>25||!(data.next_after===null||typeof data.next_after==='string'&&/^[1-9][0-9]*$/.test(data.next_after))||data.items.some(row=>!row||typeof row.id!=='string'||!/^[1-9][0-9]*$/.test(row.id)))throw Error('Invalid ownership page');
      for(const row of data.items){const item=document.createElement('li');item.textContent='#'+row.id+' · '+[row.manufacturer,row.model,row.year,row.serial_number].map(value=>value??'—').join(' · ');if(kind==='owned'){const approve=document.createElement('button');approve.type='button';approve.textContent=t('owner.heading');approve.onclick=()=>openOwner(row.id);item.append(approve)}panel.list.append(item)}
      panel.nextAfter=data.next_after;panel.status.textContent=t(data.total==='0'?'users.ownership_empty':'guitars.total_count',{count:data.total});
    }catch(error){
      if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;
      if([401,403].includes(error.status)){
        clear();for(const item of Object.values(panels))item.status.textContent=t('self_profile.restricted');
      }else{
        panel.history=[0];panel.list.replaceChildren();panel.status.textContent=t('users.ownership_unavailable');
      }
    }
    render();
  }
  async function refresh(){
    if(dialog.open)globalThis.YGCOverlays.close(dialog);epoch++;for(const panel of Object.values(panels))panel.history=[0];
    await Promise.all(['owned','formerly_owned'].map(page));
  }
  globalThis.addEventListener('pagehide',clear);globalThis.addEventListener('popstate',()=>{if(dialog.open)globalThis.YGCOverlays.close(dialog)});
  return {render,refresh,clear};
}
