const ACTIVE_USER_KEY='ygc_active_user_id';
if(sessionStorage.getItem(ACTIVE_USER_KEY)===null){
 const previous=localStorage.getItem(ACTIVE_USER_KEY);
 if(previous)sessionStorage.setItem(ACTIVE_USER_KEY,previous);
}
localStorage.removeItem(ACTIVE_USER_KEY);
const defaults={birth:'Private',residence:'Private',bio:'Public',avatar:'Public'};
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const field=id=>document.getElementById(id);
let activeUser=null;
function previewTheme(value){document.documentElement.dataset.theme=value||'dark_default'}
async function request(url,options={}){const response=await fetch(url,options);let data;try{data=await response.json()}catch{data={}}if(!response.ok)throw Error(data.detail||response.statusText);return data}
function setStatus(message,error=false){field('status').textContent=message;field('status').dataset.error=String(error)}
function syncHeader(){
 const u=activeUser?.user;
 field('profileLink').href=u?'/users/'+u.id:'/user-view';
 field('accountHub').innerHTML=u?'<a class="account-user" href="/users/'+Number(u.id)+'"><img src="/api/users/'+Number(u.id)+'/avatar?viewer_id='+Number(u.id)+'&v='+encodeURIComponent(u.updated_at||'')+'" alt=""><span>'+esc(u.display_name||'User')+'</span></a>':'<span class="sub">No user selected</span><div class="account-actions"><button data-ui-action="primary" onclick="createUser()">Create Account</button><button class="secondary" onclick="switchUser()">Select User</button></div>';
 if(u)field('accountHub').insertAdjacentHTML('beforeend','<button class="secondary" type="button" onclick="logoutUser(this)">SignOut</button>');
}
async function logoutUser(button){button.disabled=true;try{await YGCLocalAuth.logout()}catch(error){alert(error.message);button.disabled=false}}
async function switchUser(){
 const users=await request('/api/users');
 const answer=prompt('Select User ID:\n'+users.map(u=>u.id+' · '+u.display_name).join('\n'),activeUser?.user?.id||'');
 if(answer===null)return;
 const found=users.find(u=>String(u.id)===answer.trim());
 if(!found){if(answer.trim())alert('User not found.');return}
 sessionStorage.setItem(ACTIVE_USER_KEY,String(found.id));await loadUser();
}
function createUser(){location.assign('/user-view?register=1')}
async function loadUser(){
 const id=sessionStorage.getItem(ACTIVE_USER_KEY);
 if(!id){activeUser=null;previewTheme('sunburst_3ply');field('settings').hidden=true;field('emptyState').hidden=false;syncHeader();measureHeader();return}
 try{
  activeUser=await request('/api/users/'+encodeURIComponent(id));
  const u=activeUser.user;
  const themes=await request('/api/themes');
  field('theme').innerHTML=themes.map(theme=>'<option value="'+esc(theme.id)+'">'+esc(theme.label)+'</option>').join('');
  field('theme').value=u.theme||'dark_default';previewTheme(u.theme);
  field('displayName').value=u.display_name||'';field('userId').value=String(u.id);field('accountType').value=u.account_type||'user';
  field('country').value=u.location_country||'';field('city').value=u.location_region||'';field('bio').value=u.bio||'';
  field('dateOfBirth').value=u.date_of_birth||'';
  field('avatar').value='';field('avatarPreview').src='/api/users/'+u.id+'/avatar?viewer_id='+Number(u.id)+'&v='+encodeURIComponent(u.updated_at||'');
  for(const selector of document.querySelectorAll('.visibility')){
   const value=u[selector.dataset.field+'_visibility']||defaults[selector.dataset.field];
   selector.innerHTML=['Public','Members','Followers','Private'].map(option=>'<option'+(value===option?' selected':'')+'>'+option+'</option>').join('');
  }
  const owned=(activeUser.guitars||[]).filter(g=>g.ownership_status==='current_owner');
  field('signatureGuitar').innerHTML='<option value="">Select an owned guitar</option>'+owned.map(g=>'<option value="'+Number(g.individual_id)+'">'+esc([g.manufacturer,g.model,g.year].filter(Boolean).join(' · '))+'</option>').join('');
  field('signatureGuitar').value=owned.some(g=>Number(g.individual_id)===Number(u.signature_individual_id))?String(u.signature_individual_id):'';
  field('settings').hidden=false;field('emptyState').hidden=true;setStatus('');
 }catch(error){activeUser=null;previewTheme('sunburst_3ply');sessionStorage.removeItem(ACTIVE_USER_KEY);field('settings').hidden=true;field('emptyState').textContent=error.message;field('emptyState').hidden=false}
 syncHeader();measureHeader();
}
async function saveSettings(){
 if(!activeUser)return;
 const id=activeUser.user.id;
 if(!field('displayName').value.trim()){setStatus('Display Name is required.',true);field('displayName').focus();return}
 const button=field('saveButton');button.disabled=true;setStatus('Saving...');
 try{
  const visibility=Object.fromEntries([...document.querySelectorAll('.visibility')].map(select=>[select.dataset.field+'_visibility',select.value]));
  const birthInput=field('dateOfBirth');
  if(!birthInput.checkValidity()){birthInput.reportValidity();throw new Error('Enter a valid Date of Birth.')}
  const result=await request('/api/users/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:field('displayName').value.trim(),account_type:field('accountType').value,location_country:field('country').value.trim()||null,location_region:field('city').value.trim()||null,bio:field('bio').value.trim(),date_of_birth:birthInput.value||null,signature_individual_id:field('signatureGuitar').value?Number(field('signatureGuitar').value):null,theme:field('theme').value,...visibility})});
  const image=field('avatar').files[0];
  if(image){const data=new FormData();data.append('avatar',image);await request('/api/users/'+id+'/avatar',{method:'POST',body:data})}
  window.location.href='/users/'+id;
 }catch(error){setStatus(error.message,true)}finally{button.disabled=false}
}
function measureHeader(){document.documentElement.style.setProperty('--header-height',document.querySelector('.sticky-header').offsetHeight+'px')}
window.addEventListener('resize',measureHeader);
loadUser();
