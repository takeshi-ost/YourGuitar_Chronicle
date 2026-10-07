// IDs stay decimal strings throughout the public-to-private handoff.
export function catalogIndividualId(value){
  return typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&
    (value.length<19||value<='9223372036854775807')?value:null;
}
export function readCatalogIntent(search){
  const values=new URLSearchParams(search).getAll('acquire');
  return values.length===0?null:values.length===1?(catalogIndividualId(values[0])||''):'';
}
export function createApplications({auth,state,busy,work}){
  const root=document.getElementById('selfApplications'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n};
  const button=(key,id)=>{const n=node('button',t(key));n.type='button';if(id)n.id=id;return n};
  const heading=node('h2',t('applications.heading')),notice=node('p',t('applications.staging')),status=node('p'),list=node('ul');status.setAttribute('role','status');
  const accessNotice=node('p'),accessDetail=node('p');accessNotice.setAttribute('role','status');accessDetail.setAttribute('role','status');
  const add=button('applications.listing','applicationListing'),acquire=node('a',t('catalog.select_guitar')),refreshButton=button('action.refresh');
  acquire.id='applicationAcquire';acquire.href='/';
  const intentRoot=document.getElementById('catalogAcquireIntent')||node('section'),intentHeading=node('h2',t('catalog.acquire_title')),
    intentDetail=node('p'),intentStatus=node('p'),intentLink=node('a',t('catalog.view_guitar')),intentStart=button('catalog.acquire_start','catalogAcquireStart');
  intentDetail.id='catalogAcquireDetail';intentStatus.id='catalogAcquireStatus';intentStatus.setAttribute('role','status');
  intentHeading.id='catalogAcquireTitle';intentRoot.style.overflowWrap='anywhere';intentRoot.setAttribute('aria-labelledby',intentHeading.id);
  intentLink.id='catalogAcquireLink';intentRoot.append(intentHeading,intentDetail,intentStatus,intentLink,intentStart);intentRoot.hidden=true;
  root.append(heading,notice,accessNotice,add,acquire,refreshButton,status,list);
  const dialog=node('dialog'),title=node('h2'),detail=node('p'),form=node('form'),fields=node('fieldset'),photos=node('fieldset'),message=node('p');
  const adminReview=node('p');adminReview.id='applicationAdminReview';adminReview.hidden=true;adminReview.style.whiteSpace='pre-wrap';
  dialog.id='applicationDialog';title.id='applicationTitle';dialog.setAttribute('aria-labelledby',title.id);message.setAttribute('role','status');
  const inputs={},files={},previews={},urls=new Set();let selected=null,kind=null,epoch=0,accountEpoch=0,refreshEpoch=0,canWrite=null,renderedAccount=state()?.user?.app_user_id;
  let catalogId=null,catalogGuitar=null,catalogState='',catalogEpoch=0,draftGuitar=null;
  const keys=['manufacturer','serial_number','model','finish','year','individual_id','occurred_at','body'];
  for(const key of keys){
    const label=node('label',t('applications.'+key)),input=node(key==='body'?'textarea':'input');input.id='application_'+key;label.htmlFor=input.id;
    if(key!=='body')input.type=key==='occurred_at'?'date':'text';input.maxLength=key==='body'?4000:key==='individual_id'?19:key==='manufacturer'?120:key==='year'?40:160;
    if(key==='individual_id')input.readOnly=true;
    fields.append(label,input);inputs[key]={label,input};
  }
  for(const role of ['closeup','overview']){
    const label=node('label',t('applications.'+role)),input=node('input'),image=node('img'),view=button('applications.view_'+role);
    input.type='file';input.accept='image/jpeg,image/png,image/webp';input.id='application_'+role;label.htmlFor=input.id;
    image.hidden=true;image.alt=t('applications.'+role);image.style.maxWidth='100%';files[role]=input;previews[role]={image,view};photos.append(label,input,view,image);
    view.onclick=()=>{if(!selected?.photos.includes(role))return;return action(async()=>{
      const version=epoch,accountVersion=accountEpoch,id=account(),revision=selected.revision,response=await request('/'+revision+'/photos/'+role,{},false),blob=await response.blob();
      if(!sameAccount(accountVersion,id)||version!==epoch||revision!==selected?.revision)return;
      const url=URL.createObjectURL(blob);urls.add(url);image.src=url;image.hidden=false;
    })};
  }
  const limits=node('p',t('avatar.limits')),save=node('button',t('applications.create')),submit=button('applications.submit','applicationSubmit'),cancel=button('applications.cancel','applicationCancel'),close=button('action.close');
  const retry=button('applications.retry','applicationRetry'),dialogRefresh=button('action.refresh','applicationRefresh');let retryReady=false;
  save.type='submit';save.id='applicationCreate';photos.append(limits);form.append(fields,save);dialog.append(title,detail,adminReview,accessDetail,form,photos,submit,cancel,retry,dialogRefresh,message,close);document.body.append(dialog);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true);
  const account=()=>state()?.user?.app_user_id;
  const writable=()=>eligible()&&canWrite;
  const sameAccount=(version,id)=>version===accountEpoch&&eligible()&&id===account();
  function clearImages(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();for(const role of ['closeup','overview']){files[role].value='';previews[role].image.removeAttribute('src');previews[role].image.hidden=true}}
  function closeDialog(){epoch++;selected=null;kind=null;draftGuitar=null;clearImages();form.reset();detail.textContent=message.textContent=adminReview.textContent='';adminReview.hidden=true;retryReady=false}
  dialog.addEventListener('ygc:closed',closeDialog);close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function clear(){accountEpoch++;refreshEpoch++;epoch++;canWrite=null;list.replaceChildren();status.textContent='';accessNotice.textContent=accessDetail.textContent='';globalThis.YGCOverlays.close(dialog);closeDialog()}
  function render(){
    if(renderedAccount!==account()){clear();renderedAccount=account()}
    root.hidden=!eligible();add.disabled=busy()||!writable();refreshButton.disabled=dialogRefresh.disabled=busy()||!eligible();
    const draft=selected?.status==='draft';fields.disabled=busy()||!writable();photos.disabled=busy();save.disabled=busy()||!writable()||Boolean(selected)||(kind==='acquire'&&!readySelection());save.hidden=Boolean(selected);submit.disabled=busy()||!writable()||!draft;
    form.hidden=Boolean(selected)&&!(kind==='acquire'&&draft);photos.hidden=!selected;submit.hidden=!draft;cancel.hidden=!selected||!['draft','pending','processing','error'].includes(selected.status);cancel.disabled=busy()||!writable();
    for(const role of ['closeup','overview']){files[role].disabled=busy()||!writable()||!draft;previews[role].view.disabled=busy()||!eligible()||!selected?.photos.includes(role)}
    retry.hidden=selected?.status!=='error';retry.disabled=busy()||!writable();
    accessNotice.textContent=accessDetail.textContent=eligible()&&!canWrite?t(canWrite===false?'applications.read_only':'applications.access_unavailable'):'';
    if(!writable()){retryReady=false;retry.textContent=t('applications.retry')}
    if(!eligible())clear();
    intentRoot.hidden=catalogId===null;
    intentDetail.textContent=catalogGuitar?[catalogGuitar.manufacturer,catalogGuitar.model,catalogGuitar.serial_number,catalogGuitar.finish,catalogGuitar.year,catalogGuitar.id].filter(v=>v!==null&&v!=='').join(' · '):'';
    intentLink.href=catalogIndividualId(catalogId)?'/guitars/'+catalogId:'/';
    intentLink.textContent=t(catalogIndividualId(catalogId)?'catalog.view_guitar':'catalog.browse');
    const hint=catalogState==='loading'?'catalog.acquire_loading':catalogState==='invalid'?'catalog.acquire_invalid':!catalogGuitar?'catalog.acquire_unavailable':
      !state()?.user?'catalog.acquire_sign_in':!eligible()?'catalog.acquire_verify':canWrite!==true?(canWrite===false?'applications.read_only':'applications.access_unavailable'):'catalog.acquire_ready';
    intentStatus.textContent=t(hint);intentStart.disabled=busy()||!writable()||!catalogGuitar;
  }
  function readySelection(){return Boolean(draftGuitar&&catalogGuitar&&draftGuitar.id===catalogId&&catalogGuitar.id===catalogId)}
  async function lookupCatalog(id){
    const path='/api/public/guitars/'+id,options={cache:'no-store',credentials:'omit',redirect:'error'};
    const response=auth()?.signedIn&&state()?.user?await auth().authorizedFetch(path,options,true):await globalThis.fetch(path,options);
    // A rejected bearer request is never retried anonymously.
    if(!response.ok)throw Object.assign(Error('Catalog unavailable'),{status:response.status});
    const data=await response.json();
    if(!data||typeof data!=='object'||Array.isArray(data)||data.id!==id||!catalogIndividualId(data.id)||
      !['manufacturer','model','serial_number','finish','year'].every(key=>data[key]===null||typeof data[key]==='string'))throw Error('Invalid catalog guitar');
    // Keep only public identity fields. Never retain extra response properties.
    return Object.freeze(Object.fromEntries(['id','manufacturer','model','serial_number','finish','year'].map(key=>[key,data[key]])));
  }
  async function refreshCatalog(){
    if(!catalogIndividualId(catalogId))return;
    const id=catalogId,version=++catalogEpoch,accountVersion=accountEpoch,actor=account();
    catalogGuitar=null;catalogState='loading';render();
    try{
      const guitar=await lookupCatalog(id);
      if(version!==catalogEpoch||id!==catalogId)return;
      catalogGuitar=guitar;catalogState='ready';render();return guitar;
    }catch(err){
      if(version!==catalogEpoch||id!==catalogId)return;
      catalogGuitar=null;catalogState='unavailable';
      if([401,403].includes(err.status)&&sameAccount(accountVersion,actor))clear();
      render();return null;
    }
  }
  function setCatalogIntent(id){
    catalogEpoch++;catalogId=id===null?null:(catalogIndividualId(id)||'');catalogGuitar=null;catalogState=catalogId===''?'invalid':'';
    // History navigation must invalidate pending creation, even for the same ID.
    if(kind==='acquire'){globalThis.YGCOverlays.close(dialog);closeDialog()}
    render();return refreshCatalog();
  }
  function error(error){return t(error.code==='service_restricted'?'applications.service_restricted':error.status===403||error.status===401?'self_profile.restricted':error.code&&['image_format','image_pixel_limit','image_size_limit','invalid_image'].includes(error.code)?'content_media.'+error.code:error.status===400?'applications.invalid':error.status===409?'applications.conflict':'applications.failed')}
  async function request(path='',options={},json=true){
    const response=await auth().authorizedFetch('/api/auth/applications'+path,{...options,headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',...options.headers}},true);
    if(!response.ok){const detail=await response.json().catch(()=>({}));throw Object.assign(Error('Application unavailable'),{status:response.status,code:detail.detail?.code})}
    return json?response.json():response;
  }
  function post(path,body){return request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}
  async function refresh(){
    // Dismissing details does not invalidate the account's application list.
    const version=accountEpoch,id=account(),latest=++refreshEpoch;
    let data;try{data=await request();if(!Array.isArray(data?.items))throw Error('Invalid application list')}catch(err){if(sameAccount(version,id)&&latest===refreshEpoch){failed(err);return false}return}
    if(!sameAccount(version,id)||latest!==refreshEpoch)return;
    canWrite=typeof data.can_write==='boolean'?data.can_write:null;list.replaceChildren();
    for(const row of data.items){
      const item=node('li'),label=node('span',t('applications.'+row.kind)+' · '+row.serial+' · '+t('applications.status_'+row.status)),view=button('applications.detail');
      view.onclick=()=>{if(!busy()&&sameAccount(version,id)){selected=row;kind=row.kind;show()}};item.append(label,view);list.append(item);
    }
    status.textContent=data.items.length?'':t('applications.empty');render();return true;
  }
  function failed(err){
    // Authentication/read-access revocation must still purge private data.
    if([401,403].includes(err.status))clear();
    else canWrite=null;
    status.textContent=error(err);render();
  }
  async function action(fn,write=false){
    if(busy()||!eligible()||(write&&!writable()))return;
    const version=epoch,accountVersion=accountEpoch,id=account(),current=()=>sameAccount(accountVersion,id);
    await work(async()=>{
      try{await fn(current)}catch(err){
        if(!current())return;
        if(write&&err.status===403&&err.code==='service_restricted'){
          // A mode can change after the last list read. Revalidate access before
          // retaining its private rows; a write denial is not a sign-out.
          canWrite=false;
          const restored=await refresh();
          if(!current()||restored===undefined)return;
          if(!restored){clear();status.textContent=t('applications.failed');return}
        }else if([401,403].includes(err.status)){failed(err);return}
        if(version===epoch)message.textContent=error(err);
        status.textContent=error(err);
      }finally{render()}
    });
  }
  function show(){
    clearImages();adminReview.textContent='';adminReview.hidden=true;title.textContent=t('applications.'+kind);message.textContent='';retryReady=false;retry.textContent=t('applications.retry');
    for(const key of keys){const visible=selected?kind==='acquire'&&['occurred_at','body'].includes(key):key==='occurred_at'||key==='body'||(kind==='acquire'?key==='individual_id':key!=='individual_id');inputs[key].label.hidden=inputs[key].input.hidden=!visible;inputs[key].input.disabled=!visible;inputs[key].input.required=visible&&['manufacturer','serial_number','individual_id','occurred_at'].includes(key)}
    if(selected){
      inputs.occurred_at.input.value=selected.acquisition_date||today();inputs.body.input.value=selected.body||'';
      detail.textContent=t('applications.serial_number')+': '+selected.serial+'\n'+
        (selected.individual_id?t('applications.individual_id')+': '+selected.individual_id+'\n':'')+
        t('applications.challenge',{challenge:selected.challenge,expires:new Date(selected.expires_at*1000).toLocaleString()})+'\n'+t('applications.status_'+selected.status)+
        (selected.acquisition_date?'\n'+t('applications.occurred_at')+': '+selected.acquisition_date:'')+
        (selected.body?'\n'+t('applications.body')+': '+selected.body:'')+
        (selected.claim_id?'\n'+t('applications.claim_result',{id:selected.claim_id,state:t('chronicle.'+(selected.verification_status||'unverified'))}):'')+
        (selected.status==='accepted'&&selected.verification_status==='unverified'?'\n'+t('applications.owner_waiting'):'')+
        (selected.reasons?.length?'\n'+t('applications.ai_reasons')+'\n'+selected.reasons.join('\n'):'');
      if(selected.admin_review&&typeof selected.admin_review.reason==='string'){
        const review=selected.admin_review,operation=String(review.operation||'').replace(/^admin_/,'');
        adminReview.textContent=t('applications.admin_review')+'\n'+(['accept','reject','retry'].includes(operation)?t('admin_applications.operation_'+operation)+'\n':'')+(review.at?String(review.at)+'\n':'')+review.reason;adminReview.hidden=false;
      }
    }else{form.reset();inputs.occurred_at.input.value=today();inputs.individual_id.input.value=kind==='acquire'?draftGuitar?.id||'':'';detail.textContent=t('applications.instructions')+(kind==='acquire'?'\n'+[draftGuitar?.manufacturer,draftGuitar?.model,draftGuitar?.serial_number].filter(Boolean).join(' · '):'')}
    inputs.occurred_at.input.max=today();render();globalThis.YGCOverlays.open(dialog);
  }
  function today(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
  add.onclick=()=>{if(!busy()&&writable()){selected=null;draftGuitar=null;kind='listing';show()}};
  intentStart.onclick=()=>{if(!dialog.open&&!busy()&&writable()&&catalogGuitar){selected=null;draftGuitar=catalogGuitar;kind='acquire';show()}};
  refreshButton.onclick=dialogRefresh.onclick=()=>action(refresh);
  globalThis.addEventListener('focus',()=>{if(eligible())action(refresh);if(catalogId!==null)refreshCatalog()});
  form.onsubmit=event=>{
    event.preventDefault();if(selected||!dialog.open||!['listing','acquire'].includes(kind)||(kind==='acquire'&&!readySelection()))return;
    action(async current=>{
      const version=epoch,draftKind=kind,guitar=draftGuitar;
      const body=draftKind==='listing'?{kind:draftKind,payload:Object.fromEntries(keys.filter(k=>k!=='individual_id').map(k=>[k,inputs[k].input.value]))}:{kind:draftKind,individual_id:guitar.id};
      if(draftKind==='acquire'){
        // Recheck public availability at the explicit creation boundary. A stale
        // selection must not bypass offline/admin-only mode, including for admins.
        const checked=await refreshCatalog();
        if(!checked||!current()||version!==epoch||!writable()||guitar.id!==catalogId){if(!checked&&current()&&version===epoch)message.textContent=t('catalog.acquire_unavailable');return}
      }
      const row=await post('',body);if(!current())return;
      if(row.status==='duplicate'){if(version===epoch)message.textContent=t('applications.duplicate',{ids:row.existing_individual_ids.join(', ')});return}
      if(version===epoch){selected=row;show()}
      await refresh();
    },true);
  };
  submit.onclick=()=>{if(selected?.status!=='draft')return;return action(async current=>{
    const version=epoch,revision=selected.revision;
    for(const role of ['closeup','overview']){
      if(!current()||!writable()||version!==epoch)return;
      const file=files[role].files[0];if(!file&&!selected.photos.includes(role))throw {status:400};
      if(file){if(file.size>8*1024*1024)throw {code:'image_size_limit'};if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw {code:'image_format'};
        const row=await request('/'+revision+'/photos/'+role,{method:'POST',headers:{'Content-Type':file.type},body:file});if(!current()||version!==epoch)return;selected=row;
      }
    }
    if(!current()||!writable())return;
    const row=await post('/'+revision+'/submit',{acquisition_date:selected.kind==='listing'?selected.payload.occurred_at:inputs.occurred_at.input.value,body:selected.kind==='listing'?selected.payload.body:inputs.body.input.value});
    if(!current()||version!==epoch)return;selected=row;clearImages();show();await refresh();
  },true)};
  cancel.onclick=()=>{if(!['draft','pending','processing','error'].includes(selected?.status))return;return action(async current=>{const version=epoch,row=await post('/'+selected.revision+'/cancel',{});if(!current())return;if(version===epoch){selected=row;show()}await refresh()},true)};
  retry.onclick=()=>{
    if(busy()||!writable()||selected?.status!=='error')return;
    if(!retryReady){retryReady=true;retry.textContent=t('applications.retry_confirm');message.textContent=t('applications.retry_notice');return}
    action(async()=>{
      const version=epoch,accountVersion=accountEpoch,id=account(),revision=selected.revision,row=await post('/'+revision+'/retry',{});
      if(!sameAccount(accountVersion,id))return;
      if(version===epoch&&revision===selected?.revision){selected=row;show()}
      await refresh();
    },true);
  };
  return {render,refresh,clear,failed,setCatalogIntent};
}
