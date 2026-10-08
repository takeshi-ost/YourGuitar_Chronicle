// Avatar visibility controls authenticated member images. Other profile
// preferences do not publish fields or favorites.
const visibilityKeys=['birth_visibility','residence_visibility','bio_visibility','avatar_visibility'];
const visibilityEnums=['Public','Members','Followers','Private'];
const visibilityExact=(value,keys)=>Boolean(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key)));
function visibilityProfile(value){
  if(!visibilityExact(value,['profile_revision','fields'])||typeof value.profile_revision!=='string'||!(/^[1-9][0-9]{0,18}$/).test(value.profile_revision)||/[\r\n]/.test(value.profile_revision)||value.profile_revision.length===19&&value.profile_revision>'9223372036854775807'||!visibilityExact(value.fields,visibilityKeys)||visibilityKeys.some(key=>value.fields[key]!==null&&!visibilityEnums.includes(value.fields[key])))throw Error('Invalid visibility preferences');
  return {profile_revision:value.profile_revision,fields:{...value.fields}};
}
export function createVisibility({auth,state,busy,work}){
  const t=key=>globalThis.YGCI18n.t(key),node=(tag,text='',id='')=>{const n=document.createElement(tag);n.textContent=text;if(id)n.id=id;return n},button=(key,id)=>{const n=node('button',t(key),id);n.type='button';return n};
  const root=document.getElementById('selfVisibility'),heading=node('h2',t('visibility.heading'),'visibilityHeading'),values=node('dl','','visibilityValues'),status=node('p','','visibilityStatus'),refreshButton=button('action.refresh','visibilityRefresh'),edit=button('visibility.edit','visibilityEdit');
  root.setAttribute('aria-labelledby',heading.id);status.setAttribute('role','status');root.append(heading,node('p',t('visibility.notice')),values,edit,refreshButton,status);
  const dialog=node('dialog','','visibilityDialog'),form=node('form','','visibilityForm'),title=node('h2',t('visibility.edit'),'visibilityTitle'),inputs={};dialog.setAttribute('aria-labelledby',title.id);form.append(title,node('p',t('visibility.notice')),node('p',t('visibility.unknown_help')));
  for(const key of visibilityKeys){const input=node('select','','visibility_'+key),label=node('label',t('visibility.'+key));label.htmlFor=input.id;input.required=true;const unknown=node('option',t('visibility.choose'));unknown.value='';input.append(unknown);for(const value of visibilityEnums){const option=node('option',t('visibility.option_'+value));option.value=value;input.append(option)}inputs[key]=input;input.onchange=()=>render();form.append(label,input)}
  const save=button('visibility.save','visibilitySave'),cancel=button('chronicle.cancel_decision','visibilityCancel');save.type='submit';form.append(save,cancel);dialog.append(form);document.body.append(dialog);
  const identity=()=>JSON.stringify([state()?.user?.app_user_id??null,state()?.identity?.email_verified===true,state()?.user?.status??null]);
  const eligible=()=>Boolean(state()?.user?.app_user_id&&state()?.identity?.email_verified===true&&(!state()?.user?.status||state().user.status==='active')&&auth()?.signedIn!==false);
  let owner=identity(),epoch=0,profile=null,pending=null,loading=false,notice='',uncertain=false;
  function dismiss(){pending=null;for(const input of Object.values(inputs))input.value='';globalThis.YGCOverlays.close(dialog)}
  function clear(){epoch++;profile=null;loading=uncertain=false;notice='';dismiss();values.replaceChildren();status.textContent='';root.hidden=true;owner=identity()}
  function render(){if(owner!==identity()||!eligible())clear();root.hidden=!eligible();edit.disabled=busy()||loading||!profile||uncertain;refreshButton.disabled=busy()||loading||!eligible();save.disabled=busy()||loading||!pending||visibilityKeys.some(key=>!visibilityEnums.includes(inputs[key].value))||visibilityKeys.every(key=>inputs[key].value===pending.fields[key]);for(const input of Object.values(inputs))input.disabled=busy()||loading;status.textContent=uncertain?t('visibility.uncertain'):notice}
  function display(){values.replaceChildren();if(profile)for(const key of visibilityKeys)values.append(node('dt',t('visibility.'+key)),node('dd',t(profile.fields[key]===null?'visibility.unknown':'visibility.option_'+profile.fields[key])))}
  async function request(options={}){const response=await auth().authorizedFetch('/api/auth/profile/visibility',{method:'GET',cache:'no-store',credentials:'omit',redirect:'error',...options},true);if(!response.ok){const data=await response.json().catch(()=>({}));throw Object.assign(Error('Visibility request failed'),{status:response.status,code:(data?.detail?.code||data?.code)==='service_restricted'?'service_restricted':null})}return visibilityProfile(await response.json())}
  const current=(generation,actor)=>generation===epoch&&actor===identity()&&eligible();
  function errorText(error){return t(error.code==='service_restricted'?'visibility.restricted':[401,403].includes(error.status)?'self_profile.restricted':error.status===409?'visibility.conflict':error.status===400?'visibility.invalid':'visibility.failed')}
  async function refresh(){if(!eligible())return;const generation=++epoch,actor=identity();profile=null;dismiss();display();loading=true;notice=t('cloud.working');render();try{const data=await request();if(!current(generation,actor))return;profile=data;uncertain=false;notice='';display()}catch(error){if(!current(generation,actor))return;notice=errorText(error)}finally{if(current(generation,actor)){loading=false;render()}}}
  refreshButton.onclick=()=>{if(busy()||loading||!eligible())return;return work(refresh)};
  edit.onclick=()=>{if(busy()||loading||!profile||uncertain||!eligible())return;pending={revision:profile.profile_revision,fields:{...profile.fields},epoch,owner:identity()};for(const key of visibilityKeys)inputs[key].value=profile.fields[key]??'';render();globalThis.YGCOverlays.open(dialog,{initialFocus:'#visibility_birth_visibility'})};
  cancel.onclick=dismiss;dialog.addEventListener('ygc:closed',()=>{pending=null;for(const input of Object.values(inputs))input.value=''});
  form.onsubmit=event=>{
    event.preventDefault();if(busy()||loading||!pending||!current(pending.epoch,pending.owner)||visibilityKeys.some(key=>!visibilityEnums.includes(inputs[key].value))||visibilityKeys.every(key=>inputs[key].value===pending.fields[key]))return;
    const body={revision:pending.revision,fields:Object.fromEntries(visibilityKeys.map(key=>[key,inputs[key].value]))},actor=identity(),generation=++epoch;dismiss();profile=null;display();notice=t('cloud.working');
    return work(async()=>{try{const data=await request({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!current(generation,actor))return;if(visibilityKeys.some(key=>data.fields[key]!==body.fields[key]))throw Error('Unexpected visibility result');profile=data;notice=t('visibility.saved');display()}catch(error){if(!current(generation,actor))return;profile=null;if([400,401,403,404,409,422].includes(error.status))notice=errorText(error);else{uncertain=true;notice=''}}finally{try{const c=new globalThis.BroadcastChannel('ygc-member-avatar');c.postMessage('invalidate');c.close()}catch{}if(current(generation,actor))render()}});
  };
  globalThis.addEventListener('popstate',()=>{clear();render()});globalThis.addEventListener('pagehide',clear);render();return {render,clear,refresh};
}
