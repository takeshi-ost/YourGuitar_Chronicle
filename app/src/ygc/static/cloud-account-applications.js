export function createApplications({auth,state,busy,work}){
  const root=document.getElementById('selfApplications'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n};
  const button=(key,id)=>{const n=node('button',t(key));n.type='button';if(id)n.id=id;return n};
  const heading=node('h2',t('applications.heading')),notice=node('p',t('applications.staging')),status=node('p'),list=node('ul');status.setAttribute('role','status');
  const add=button('applications.listing','applicationListing'),acquire=button('applications.acquire','applicationAcquire'),refreshButton=button('action.refresh');
  root.append(heading,notice,add,acquire,refreshButton,status,list);
  const dialog=node('dialog'),title=node('h2'),detail=node('p'),form=node('form'),fields=node('fieldset'),photos=node('fieldset'),message=node('p');
  dialog.id='applicationDialog';title.id='applicationTitle';dialog.setAttribute('aria-labelledby',title.id);message.setAttribute('role','status');
  const inputs={},files={},previews={},urls=new Set();let selected=null,kind=null,epoch=0,accountEpoch=0,refreshEpoch=0;
  const keys=['manufacturer','serial_number','model','finish','year','individual_id','occurred_at','body'];
  for(const key of keys){
    const label=node('label',t('applications.'+key)),input=node(key==='body'?'textarea':'input');input.id='application_'+key;label.htmlFor=input.id;
    if(key!=='body')input.type=key==='occurred_at'?'date':'text';input.maxLength=key==='body'?4000:key==='individual_id'?19:key==='manufacturer'?120:key==='year'?40:160;
    fields.append(label,input);inputs[key]={label,input};
  }
  for(const role of ['closeup','overview']){
    const label=node('label',t('applications.'+role)),input=node('input'),image=node('img'),view=button('applications.view_'+role);
    input.type='file';input.accept='image/jpeg,image/png,image/webp';input.id='application_'+role;label.htmlFor=input.id;
    image.hidden=true;image.alt=t('applications.'+role);image.style.maxWidth='100%';files[role]=input;previews[role]={image,view};photos.append(label,input,view,image);
    view.onclick=()=>action(async()=>{
      const version=epoch,revision=selected.revision,response=await request('/'+revision+'/photos/'+role,{},false),blob=await response.blob();
      if(version!==epoch||revision!==selected?.revision)return;
      const url=URL.createObjectURL(blob);urls.add(url);image.src=url;image.hidden=false;
    });
  }
  const limits=node('p',t('avatar.limits')),save=node('button',t('applications.create')),submit=button('applications.submit','applicationSubmit'),cancel=button('applications.cancel','applicationCancel'),close=button('action.close');
  const retry=button('applications.retry','applicationRetry');let retryReady=false;
  save.type='submit';save.id='applicationCreate';photos.append(limits);form.append(fields,save);dialog.append(title,detail,form,photos,submit,cancel,retry,message,close);document.body.append(dialog);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true);
  const account=()=>state()?.user?.app_user_id;
  const sameAccount=(version,id)=>version===accountEpoch&&eligible()&&id===account();
  function clearImages(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();for(const role of ['closeup','overview']){files[role].value='';previews[role].image.removeAttribute('src');previews[role].image.hidden=true}}
  function closeDialog(){epoch++;selected=null;clearImages();form.reset();message.textContent='';retryReady=false}
  dialog.addEventListener('ygc:closed',closeDialog);close.onclick=()=>globalThis.YGCOverlays.close(dialog);
  function clear(){accountEpoch++;refreshEpoch++;epoch++;list.replaceChildren();status.textContent='';globalThis.YGCOverlays.close(dialog);closeDialog()}
  function render(){
    root.hidden=!eligible();add.disabled=acquire.disabled=refreshButton.disabled=busy()||!eligible();
    const draft=selected?.status==='draft';fields.disabled=photos.disabled=busy();save.disabled=busy()||Boolean(selected);save.hidden=Boolean(selected);submit.disabled=busy()||!draft;
    form.hidden=Boolean(selected)&&!(kind==='acquire'&&draft);photos.hidden=!selected;submit.hidden=!draft;cancel.hidden=!selected||!['draft','pending','processing','error'].includes(selected.status);cancel.disabled=busy();
    for(const role of ['closeup','overview']){files[role].disabled=busy()||!draft;previews[role].view.disabled=busy()||!selected?.photos.includes(role)}
    retry.hidden=selected?.status!=='error';retry.disabled=busy();
    if(!eligible())clear();
  }
  function error(error){return t(error.status===403||error.status===401?'self_profile.restricted':error.code&&['image_format','image_pixel_limit','image_size_limit','invalid_image'].includes(error.code)?'content_media.'+error.code:error.status===400?'applications.invalid':error.status===409?'applications.conflict':'applications.failed')}
  async function request(path='',options={},json=true){
    const response=await auth().authorizedFetch('/api/auth/applications'+path,{...options,headers:{'X-YGC-Timezone':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',...options.headers}},true);
    if(!response.ok){const detail=await response.json().catch(()=>({}));throw Object.assign(Error('Application unavailable'),{status:response.status,code:detail.detail?.code})}
    return json?response.json():response;
  }
  function post(path,body){return request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}
  async function refresh(){
    // Dismissing details does not invalidate the account's application list.
    const version=accountEpoch,id=account(),latest=++refreshEpoch,data=await request();
    if(!sameAccount(version,id)||latest!==refreshEpoch)return;
    list.replaceChildren();
    for(const row of data.items){
      const item=node('li'),label=node('span',t('applications.'+row.kind)+' · '+row.serial+' · '+t('applications.status_'+row.status)),view=button('applications.detail');
      view.onclick=()=>{if(!busy()){selected=row;kind=row.kind;show()}};item.append(label,view);list.append(item);
    }
    status.textContent=data.items.length?'':t('applications.empty');render();
  }
  async function action(fn){
    if(busy()||!eligible())return;const version=epoch;
    await work(async()=>{try{await fn()}catch(err){if(version!==epoch||!eligible())return;message.textContent=status.textContent=error(err);if([401,403].includes(err.status)){globalThis.YGCOverlays.close(dialog);list.replaceChildren()}}finally{render()}});
  }
  function show(){
    clearImages();title.textContent=t('applications.'+kind);message.textContent='';retryReady=false;retry.textContent=t('applications.retry');
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
        (selected.reasons?.length?'\n'+selected.reasons.join('\n'):'');
    }else{form.reset();inputs.occurred_at.input.value=today();detail.textContent=t('applications.instructions')}
    inputs.occurred_at.input.max=today();render();globalThis.YGCOverlays.open(dialog);
  }
  function today(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
  add.onclick=()=>{if(!busy()){selected=null;kind='listing';show()}};acquire.onclick=()=>{if(!busy()){selected=null;kind='acquire';show()}};refreshButton.onclick=()=>action(refresh);
  form.onsubmit=event=>{
    event.preventDefault();if(selected)return;action(async()=>{
      const body=kind==='listing'?{kind,payload:Object.fromEntries(keys.filter(k=>k!=='individual_id').map(k=>[k,inputs[k].input.value]))}:{kind,individual_id:inputs.individual_id.input.value.trim()};
      const version=epoch,row=await post('',body);if(version!==epoch||!eligible())return;
      if(row.status==='duplicate'){message.textContent=t('applications.duplicate',{ids:row.existing_individual_ids.join(', ')});return}
      selected=row;show();await refresh();
    });
  };
  submit.onclick=()=>action(async()=>{
    const version=epoch,revision=selected.revision;
    for(const role of ['closeup','overview']){
      const file=files[role].files[0];if(!file&&!selected.photos.includes(role))throw {status:400};
      if(file){if(file.size>8*1024*1024)throw {code:'image_size_limit'};if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw {code:'image_format'};
        const row=await request('/'+revision+'/photos/'+role,{method:'POST',headers:{'Content-Type':file.type},body:file});if(version!==epoch||!eligible())return;selected=row;
      }
    }
    const row=await post('/'+revision+'/submit',{acquisition_date:selected.kind==='listing'?selected.payload.occurred_at:inputs.occurred_at.input.value,body:selected.kind==='listing'?selected.payload.body:inputs.body.input.value});
    if(version!==epoch||!eligible())return;selected=row;clearImages();show();await refresh();
  });
  cancel.onclick=()=>action(async()=>{const version=epoch,row=await post('/'+selected.revision+'/cancel',{});if(version!==epoch||!eligible())return;selected=row;show();await refresh()});
  retry.onclick=()=>{
    if(busy()||selected?.status!=='error')return;
    if(!retryReady){retryReady=true;retry.textContent=t('applications.retry_confirm');message.textContent=t('applications.retry_notice');return}
    action(async()=>{
      const version=epoch,accountVersion=accountEpoch,id=account(),revision=selected.revision,row=await post('/'+revision+'/retry',{});
      if(!sameAccount(accountVersion,id))return;
      if(version===epoch&&revision===selected?.revision){selected=row;show()}
      await refresh();
    });
  };
  return {render,refresh,clear,failed:err=>{clear();status.textContent=error(err)}};
}
