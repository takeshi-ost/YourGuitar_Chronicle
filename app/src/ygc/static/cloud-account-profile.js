export function createProfile({auth,state,busy,work,updated}){
  const $=id=>document.getElementById(id),t=key=>globalThis.YGCI18n.t(key);
  const fields=['display_name','location_country','location_region','bio'];
  let profile=null,pending=null,epoch=0;
  const dialog=document.createElement('dialog'),form=document.createElement('form'),title=document.createElement('h2'),notice=document.createElement('p');
  dialog.id='selfProfileDialog';title.textContent=t('users.edit_profile');notice.textContent=t('self_profile.notice');form.append(title,notice);
  const inputs={};
  for(const key of fields){
    const label=document.createElement('label'),input=document.createElement(key==='bio'?'textarea':'input');
    input.id='selfProfile_'+key;input.maxLength=key==='bio'?2000:120;input.required=key==='display_name';
    label.htmlFor=input.id;label.textContent=t('users.field_'+key);inputs[key]=input;form.append(label,input);
  }
  const save=document.createElement('button'),cancel=document.createElement('button');
  save.id='selfProfileSave';save.type='submit';save.textContent=t('users.save_profile');cancel.id='selfProfileCancel';cancel.type='button';cancel.textContent=t('chronicle.cancel_decision');
  form.append(save,cancel);dialog.append(form);document.body.append(dialog);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true);
  function clear(){epoch++;profile=pending=null;globalThis.YGCOverlays.close(dialog);for(const input of Object.values(inputs))input.value='';$('selfProfileValues').replaceChildren();$('selfProfileStatus').textContent=''}
  function render(){
    $('selfProfile').hidden=!eligible();$('selfProfileEdit').disabled=busy()||!profile;$('selfProfileRefresh').disabled=busy()||!eligible();
    if(!eligible())clear();
  }
  async function refresh(){
    const current=++epoch;profile=null;$('selfProfileEdit').disabled=true;
    try{
    const response=await auth().authorizedFetch('/api/auth/profile',{},true);
    if(!response.ok)throw Object.assign(Error('Profile unavailable'),{status:response.status});
    const data=await response.json();if(current!==epoch||!eligible())return;
    profile=data;$('selfProfileValues').replaceChildren();
    for(const key of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t('users.field_'+key);dd.textContent=data.fields[key]||'—';$('selfProfileValues').append(dt,dd)}
    $('selfProfileStatus').textContent='';render();
    }catch(error){if(current!==epoch||!eligible())return;throw error}
  }
  function failed(error){
    profile=null;globalThis.YGCOverlays.close(dialog);$('selfProfileValues').replaceChildren();
    $('selfProfileStatus').textContent=t(error.status===403?'self_profile.restricted':'self_profile.failed');render();
  }
  $('selfProfileRefresh').onclick=()=>work(async()=>{try{await refresh()}catch(error){failed(error)}});
  $('selfProfileEdit').onclick=()=>{
    if(busy()||!profile)return;pending={revision:profile.profile_revision};
    for(const key of fields)inputs[key].value=profile.fields[key];
    globalThis.YGCOverlays.open(dialog,{initialFocus:'#selfProfile_display_name'});
  };
  cancel.onclick=()=>globalThis.YGCOverlays.close(dialog);
  dialog.addEventListener('ygc:closed',()=>{pending=null;for(const input of Object.values(inputs))input.value=''});
  form.onsubmit=event=>{
    event.preventDefault();if(busy()||!pending)return;
    const body={revision:pending.revision,fields:Object.fromEntries(fields.map(key=>[key,inputs[key].value]))};
    const owner=state()?.user?.app_user_id,current=epoch;globalThis.YGCOverlays.close(dialog);
    work(async()=>{
      try{
        const response=await auth().authorizedFetch('/api/auth/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},true);
        if(!response.ok)throw Object.assign(Error('Save failed'),{status:response.status});
        if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;
        await updated();if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;await refresh();if(owner===state()?.user?.app_user_id&&eligible())$('selfProfileStatus').textContent=t('users.profile_saved');
      }catch(error){
        if(owner!==state()?.user?.app_user_id||!eligible())return;
        profile=null;render();$('selfProfileStatus').textContent=t(error.status===403?'self_profile.restricted':error.status===409?'users.profile_conflict':error.status===400?'users.profile_invalid':'users.profile_unavailable');
      }
    });
  };
  return {render,refresh,failed,clear};
}
