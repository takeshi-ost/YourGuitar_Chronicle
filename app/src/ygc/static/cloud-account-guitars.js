export function createGuitars({auth,state,busy,work}){
  const root=document.getElementById('selfGuitars'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  let epoch=0,pending=null;
  const dialog=document.createElement('dialog'),title=document.createElement('h2'),warning=document.createElement('p'),claims=document.createElement('div'),message=document.createElement('p'),close=document.createElement('button');
  dialog.id='ownerResponseDialog';title.id='ownerResponseTitle';dialog.setAttribute('aria-labelledby',title.id);title.textContent=t('owner.heading');warning.textContent=t('owner.warning');message.setAttribute('role','status');close.type='button';close.textContent=t('action.close');
  dialog.append(title,warning,claims,message,close);document.body.append(dialog);
  close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  dialog.addEventListener('ygc:closed',()=>{pending=null;claims.replaceChildren();message.textContent=''});
  async function ownerRequest(path,options={}){
    const response=await auth().authorizedFetch('/api/auth/guitars/'+path,options,true);
    if(!response.ok)throw Object.assign(Error('Owner response unavailable'),{status:response.status});return response.json();
  }
  function ownerAction(fn){if(busy()||!eligible())return;const version=epoch;return work(async()=>{try{await fn(version)}catch(error){if(version!==epoch)return;message.textContent=t(error.status===409?'chronicle.decision_conflict':error.status===403?'self_profile.restricted':'chronicle.decision_unavailable');if([401,403].includes(error.status)){claims.replaceChildren();pending=null}}finally{render()}})}
  function openOwner(id){return ownerAction(async version=>{
    pending=null;claims.replaceChildren();message.textContent=t('cloud.working');globalThis.YGCOverlays.open(dialog);
    const result=await ownerRequest(id+'/owner-responses');if(version!==epoch||!eligible()||!dialog.open)return;
    message.textContent=result.items.length?'':t('owner.empty');
    for(const row of result.items){
      const card=document.createElement('section'),description=document.createElement('p'),select=document.createElement('select'),review=document.createElement('button'),confirm=document.createElement('button'),reasonLabel=document.createElement('label'),reason=document.createElement('textarea'),reasonHelp=document.createElement('p');
      description.textContent=['#'+row.id,row.author_name,row.claim_type,row.specification_kind,row.ownership_kind,row.occurred_at,...(row.spec_items?.length?row.spec_items.map(item=>item.field_name+': '+item.value_text):[row.field_name,row.value_text]),row.body].filter(Boolean).join(' · ');
      select.setAttribute('aria-label',t('owner.decision'));for(const stance of ['positive','negative','unverified']){const option=document.createElement('option');option.value=stance;option.textContent=t('chronicle.'+stance);select.append(option)}select.value=row.verification_status;
      review.type=confirm.type='button';review.textContent=t('owner.review');confirm.textContent=t('chronicle.apply_decision');confirm.hidden=true;
      reason.id='ownerDeclineReason_'+row.id;reason.maxLength=4000;reasonLabel.setAttribute('for',reason.id);reasonLabel.textContent=t('owner.decline_reason');reasonHelp.id=reason.id+'_help';reasonHelp.textContent=t('owner.decline_reason_help');reason.setAttribute('aria-describedby',reasonHelp.id);
      const needsReason=()=>row.decline_reason_required===true&&select.value==='negative';
      const reasonVisibility=()=>{reasonLabel.hidden=reason.hidden=reasonHelp.hidden=!needsReason();reason.required=needsReason()};reasonVisibility();
      const invalidate=()=>{pending=null;for(const button of claims.querySelectorAll('[data-owner-confirm]'))button.hidden=true;message.textContent=''};
      review.onclick=()=>{if(busy()||!eligible())return;invalidate();if(needsReason()&&(!reason.value.trim()||reason.value.trim().length>4000)){message.textContent=t('owner.decline_reason_required');reason.focus();return}pending={id,claim:row.id,revision:row.revision,stance:select.value,...(needsReason()?{reason:reason.value.trim()}:{})};confirm.hidden=false;message.textContent=t('owner.confirm',{id:row.id,state:t('chronicle.'+select.value)})+(pending.reason?' '+t('owner.decline_reason_confirm',{reason:pending.reason}):'')};
      select.onchange=()=>{invalidate();reasonVisibility()};reason.oninput=invalidate;confirm.dataset.ownerConfirm='true';
      confirm.onclick=()=>{if(!pending||pending.claim!==row.id)return;const saved={...pending};pending=null;ownerAction(async current=>{
        await ownerRequest(saved.id+'/owner-responses/'+saved.claim,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stance:saved.stance,revision:saved.revision,...(saved.reason?{reason:saved.reason}:{})})});
        if(current!==epoch||!eligible())return;globalThis.YGCOverlays.close(dialog);await refresh();
      })};card.append(description,select,review,confirm,reasonLabel,reason,reasonHelp);claims.append(card);
    }
  })}

  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true);
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
    root.hidden=!eligible();
    for(const panel of Object.values(panels)){
      panel.refresh.disabled=busy()||!eligible();panel.previous.disabled=busy()||!eligible()||panel.history.length<2;panel.next.disabled=busy()||!eligible()||panel.nextAfter===null;
    }
    for(const button of root.querySelectorAll("li button"))button.disabled=busy()||!eligible();
    for(const control of claims.querySelectorAll("button,select,textarea"))control.disabled=busy()||!eligible();
    if(!eligible())clear();
  }
  function clear(){epoch++;globalThis.YGCOverlays.close(dialog);pending=null;claims.replaceChildren();for(const panel of Object.values(panels)){panel.history=[0];panel.nextAfter=null;panel.list.replaceChildren();panel.status.textContent=''}}
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
    epoch++;for(const panel of Object.values(panels))panel.history=[0];
    await Promise.all(['owned','formerly_owned'].map(page));
  }
  return {render,refresh,clear};
}
