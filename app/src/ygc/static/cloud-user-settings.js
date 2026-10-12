import {loadCloudAuth} from './cloud-auth-loader.js';
const $=id=>document.getElementById(id),t=key=>globalThis.YGCI18n.t(key);
const fieldIds={display_name:'displayName',account_type:'accountType',location_country:'country',location_region:'city',bio:'bio',date_of_birth:'dateOfBirth',theme:'theme'};
const visibility=['birth','residence','bio','avatar'],choices=['Public','Members','Followers','Private'];
const exactId=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&BigInt(value)<=9223372036854775807n;
let auth,account=null,settings=null,signature=null,epoch=0,saving=false,imageURL=null,savedTheme='sunburst_3ply',uncertain=false;
const identity=()=>JSON.stringify([auth?.account?.user?.app_user_id,auth?.account?.identity?.email_verified,auth?.account?.user?.status]);
const eligible=()=>Boolean(auth?.signedIn&&account?.user?.app_user_id&&account.identity?.email_verified===true&&(!account.user.status||account.user.status==='active')&&account.user.app_user_id===auth.account?.user?.app_user_id);
const current=(token,owner)=>token===epoch&&owner===identity()&&eligible();
function status(message,error=false){$('status').textContent=message;$('status').dataset.error=String(error)}
function clear(){epoch++;account=settings=null;signature=null;saving=false;uncertain=false;$('settings').hidden=true;$('emptyState').hidden=false;$('accountHub').replaceChildren();for(const id of [...Object.values(fieldIds),'userId','signatureGuitar','avatar'])$(id).value='';if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('avatarPreview').src='/assets/no-icon.svg';status('')}
function controls(){ $('saveButton').disabled=saving||uncertain||!settings||!eligible();for(const input of document.querySelectorAll('#settings input,#settings select,#settings textarea'))input.disabled=saving; }
async function request(path,options={}){const response=await auth.authorizedFetch(path,{cache:'no-store',credentials:'omit',redirect:'error',...options},Boolean(options.method&&!['GET','HEAD'].includes(options.method.toUpperCase())));if(!response.ok)throw Object.assign(Error(t(response.status===409?'users.profile_conflict':response.status===403?'self_profile.restricted':'users.profile_unavailable')),{status:response.status});return response.json()}
function header(){const link=document.createElement('a'),img=document.createElement('img'),name=document.createElement('span'),logout=document.createElement('button');link.className='account-user';link.href='/ui/profile';img.src=imageURL||'/assets/no-icon.svg';img.alt='';name.textContent=settings.fields.display_name;link.append(img,name);logout.className='secondary';logout.type='button';logout.textContent=t('account.sign_out');logout.onclick=()=>globalThis.logoutUser(logout);$('accountHub').replaceChildren(link,logout);$('profileLink').href='/ui/profile'}
async function load(){
  clear();const token=epoch;
  try{
    account=await auth.restore();const owner=identity();if(token!==epoch)return;
    if(!eligible()){$('emptyState').textContent=t('self_profile.restricted');const link=document.createElement('a');link.href='/ui/profile';link.textContent=t('account.sign_in');$('emptyState').append(' ',link);return}
    const data=await request('/api/auth/settings');if(!current(token,owner))return;
    const keys=[...Object.keys(fieldIds),...visibility.map(key=>key+'_visibility')];
    if(!data||!exactId(data.id)||!exactId(data.profile_revision)||!data.fields||Object.keys(data.fields).length!==keys.length||keys.some(key=>!Object.hasOwn(data.fields,key)||!(typeof data.fields[key]==='string'||key.endsWith('_visibility')&&data.fields[key]===null)))throw Error(t('users.profile_unavailable'));
    const themeResponse=await fetch('/api/themes',{credentials:'omit'});if(!themeResponse.ok)throw Error(t('users.profile_unavailable'));const themes=await themeResponse.json();if(!current(token,owner))return;
    if(!Array.isArray(themes)||themes.some(theme=>!theme||typeof theme.id!=='string'||typeof theme.label!=='string')||!themes.some(theme=>theme.id===data.fields.theme))throw Error(t('users.profile_unavailable'));
    $('theme').replaceChildren();for(const theme of themes){const option=document.createElement('option');option.value=theme.id;option.textContent=theme.label;$('theme').append(option)}
    settings=data;savedTheme=data.fields.theme;document.documentElement.dataset.theme=savedTheme;
    for(const [key,id] of Object.entries(fieldIds))$(id).value=data.fields[key];$('userId').value=data.id;
    for(const name of visibility){const select=document.querySelector('.visibility[data-field="'+name+'"]');select.replaceChildren();if(data.fields[name+'_visibility']===null){const blank=document.createElement('option');blank.value='';blank.textContent=t('visibility.choose');select.append(blank)}for(const value of choices){const option=document.createElement('option');option.value=value;option.textContent=t('visibility.option_'+value);select.append(option)}select.value=data.fields[name+'_visibility']??'';select.required=true}
    const selected=await request('/api/auth/settings/signature');if(!current(token,owner))return;if(!selected||Object.keys(selected).length!==1||!(selected.individual_id===null||exactId(selected.individual_id)))throw Error(t('users.profile_unavailable'));signature=selected.individual_id;
    $('signatureGuitar').replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent=t('ui.select_an_owned_guitar_5b81269e');$('signatureGuitar').append(blank);
    let after=null;const seen=new Set();do{const page=await request('/api/auth/guitars?'+new URLSearchParams({kind:'owned',limit:'25',...(after?{after}:{})}));if(!current(token,owner))return;if(!Array.isArray(page.items)||page.items.length>25||!(page.next_after===null||exactId(page.next_after)))throw Error(t('users.profile_unavailable'));for(const row of page.items){if(!exactId(row.id)||seen.has(row.id)||after&&BigInt(row.id)<=BigInt(after))throw Error(t('users.profile_unavailable'));seen.add(row.id);const option=document.createElement('option');option.value=row.id;option.textContent=[row.manufacturer,row.model,row.year].filter(Boolean).join(' · ');$('signatureGuitar').append(option)}if(page.next_after!==null&&page.next_after!==page.items.at(-1)?.id)throw Error(t('users.profile_unavailable'));after=page.next_after}while(after);
    $('signatureGuitar').value=seen.has(signature)?signature:'';
    const avatar=await auth.authorizedFetch('/api/auth/avatar',{cache:'no-store'},false);if(!current(token,owner))return;
    if(avatar.ok){if(!avatar.headers.get('content-type')?.startsWith('image/jpeg'))throw Error(t('avatar.failed'));const blob=await avatar.blob();if(!current(token,owner))return;if(blob.size>25*1024*1024)throw Error(t('avatar.failed'));imageURL=URL.createObjectURL(blob);$('avatarPreview').src=imageURL}else if(avatar.status!==404)throw Error(t('avatar.failed'));
    $('settings').hidden=false;$('emptyState').hidden=true;header();controls();measure();
  }catch(error){if(token!==epoch)return;clear();$('emptyState').textContent=error.message}
}
globalThis.previewTheme=value=>{document.documentElement.dataset.theme=value||savedTheme};
globalThis.logoutUser=async button=>{button.disabled=true;clear();try{await auth.logout();location.assign('/ui')}catch{$('emptyState').textContent=t('self_profile.restricted')}};
globalThis.saveSettings=async()=>{
  if(saving||uncertain||!settings||!eligible())return;
  if(!$('displayName').value.trim()){$('displayName').focus();status(t('ui.display_name_is_required_e7535edc'),true);return}
  for(const input of document.querySelectorAll('#settings input,#settings select,#settings textarea'))if(!input.checkValidity()){input.reportValidity();return}
  const fields=Object.fromEntries(Object.entries(fieldIds).map(([key,id])=>[key,$(id).value.trim()]));for(const name of visibility){fields[name+'_visibility']=document.querySelector('.visibility[data-field="'+name+'"]').value;if(!choices.includes(fields[name+'_visibility']))return}
  const target=$('signatureGuitar').value||null,file=$('avatar').files[0];
  if(file&&(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024)){status(t('avatar.invalid'),true);return}
  const token=epoch,owner=identity();saving=true;controls();status(t('ui.saving_dc85af8f'));let phase='settings';
  try{
    const result=await request('/api/auth/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:settings.profile_revision,fields})});if(!current(token,owner))return;if(!result||result.saved!==true||!exactId(result.profile_revision))throw Error(t('users.profile_unavailable'));
    settings={...settings,profile_revision:result.profile_revision,fields};savedTheme=fields.theme;
    if(target!==signature){phase='signature';const result=await request('/api/auth/settings/signature',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({previous:signature,individual_id:target})});if(!current(token,owner))return;if(result.individual_id!==target)throw Error(t('users.profile_unavailable'));signature=target}
    if(file){phase='avatar';const result=await auth.authorizedFetch('/api/auth/avatar',{method:'PUT',headers:{'Content-Type':file.type},body:file},true);if(!current(token,owner))return;if(!result.ok)throw Object.assign(Error(t('avatar.failed')),{status:result.status})}
    location.assign('/ui/profile');
  }catch(error){if(!current(token,owner))return;uncertain=![400,403,409,422].includes(error.status);status((phase==='settings'?'':t('settings.partial_saved')+' ')+error.message+(uncertain?' '+t('settings.refresh_required'):''),true)}
  finally{if(current(token,owner)){saving=false;controls()}}
};
function measure(){document.documentElement.style.setProperty('--header-height',document.querySelector('.sticky-header').offsetHeight+'px')}
globalThis.addEventListener('resize',measure);globalThis.addEventListener('pagehide',clear);
// Finish the initial SDK session restoration before observing later identity switches.
// Otherwise its initial null-to-user event invalidates load() before settings load.
try{auth=await loadCloudAuth();await auth.restore();auth.onIdentityChanged?.(()=>{clear();$('emptyState').textContent=t('self_profile.restricted')});await load()}catch(error){clear();$('emptyState').textContent=t('self_profile.failed')}
globalThis.addEventListener('pageshow',event=>{if(event.persisted)void load()});
