// Console data access remains separate from Operations availability.
export function createUserBrowser({request,authorized,onUnauthorized,onGuitar}){
  const $=id=>document.getElementById(id),t=(key,params={})=>YGCI18n.t(key,params);
  let busy=false,epoch=0,next=null,history=[0],query='',selectedUser=null;
  let selectedProfile=null,pendingProfile=null;
  const edit=document.createElement('button'),detailRefresh=document.createElement('button'),profileStatus=document.createElement('p');
  edit.id='userProfileEdit';detailRefresh.id='userDetailRefresh';profileStatus.id='userProfileStatus';profileStatus.setAttribute('role','status');
  edit.textContent=t('users.edit_profile');detailRefresh.textContent=t('users.refresh_detail');$('cloudUserDetail').append(edit,detailRefresh,profileStatus);
  const dialog=document.createElement('dialog');dialog.id='userProfileDialog';
  const form=document.createElement('form'),title=document.createElement('h2'),notice=document.createElement('p'),save=document.createElement('button'),cancel=document.createElement('button');
  const inputs={};title.textContent=t('users.edit_profile');notice.textContent=t('users.profile_notice');
  form.append(title,notice);
  for(const key of ['display_name','location_country','location_region','bio']){
    const label=document.createElement('label'),input=document.createElement(key==='bio'?'textarea':'input');input.id='userProfile_'+key;input.maxLength=key==='bio'?2000:120;if(key==='display_name')input.required=true;
    label.htmlFor=input.id;label.textContent=t('users.field_'+key);inputs[key]=input;form.append(label,input);
  }
  save.id='userProfileSave';save.type='submit';save.textContent=t('users.save_profile');cancel.id='userProfileCancel';cancel.type='button';cancel.textContent=t('chronicle.cancel_decision');form.append(save,cancel);dialog.append(form);document.body.append(dialog);
  function closeProfile(){globalThis.YGCOverlays.close(dialog);pendingProfile=null}
  dialog.addEventListener('ygc:closed',()=>{pendingProfile=null;for(const input of Object.values(inputs))input.value=''});
  cancel.onclick=closeProfile;
  edit.onclick=()=>{
    if(busy||!authorized()||!selectedProfile)return;
    pendingProfile={id:selectedUser,revision:selectedProfile.profile_revision};
    for(const [key,input] of Object.entries(inputs))input.value=selectedProfile[key]??'';
    globalThis.YGCOverlays.open(dialog,{initialFocus:'#userProfile_display_name'});
  };
  detailRefresh.onclick=()=>{if(selectedUser!==null)action(current=>loadDetail(selectedUser,current,false))};
  form.onsubmit=event=>{
    event.preventDefault();if(busy||!authorized()||!pendingProfile)return;
    const saved={...pendingProfile,fields:Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.value]))};closeProfile();
    action(async current=>{
      try{
        await request('/api/admin/users/'+saved.id+'/profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:saved.revision,fields:saved.fields})});
        if(current!==epoch)return;
        await page(current);await loadDetail(saved.id,current,false);
        if(current===epoch)profileStatus.textContent=t('users.profile_saved');
      }catch(error){
        if(current!==epoch)return;
        if([401,403].includes(error.status)){clear();onUnauthorized(error)}
        profileStatus.textContent=t(error.status===409?'users.profile_conflict':error.status===400?'users.profile_invalid':'users.profile_unavailable');
      }
    });
  };
  const ownership={};
  for(const kind of ['owned','formerly_owned']){
    const panel=document.createElement('section');panel.id='userGuitars_'+kind;panel.hidden=true;
    const title=document.createElement('h3'),status=document.createElement('p'),rows=document.createElement('div'),refresh=document.createElement('button'),previous=document.createElement('button'),next=document.createElement('button');
    title.textContent=t('users.'+kind);status.setAttribute('role','status');refresh.textContent=t('users.ownership_refresh');previous.textContent=t('users.previous');next.textContent=t('users.next');
    rows.className='user-owned-guitars';panel.append(title,refresh,status,rows,previous,next);$('cloudUserDetail').append(panel);
    ownership[kind]={panel,status,rows,refresh,previous,next,history:[0],cursor:null};
    refresh.onclick=()=>{if(busy)return;ownership[kind].history=[0];action(current=>ownedPage(kind,current))};
    previous.onclick=()=>{if(busy||ownership[kind].history.length<2)return;ownership[kind].history.pop();action(current=>ownedPage(kind,current))};
    next.onclick=()=>{if(busy||ownership[kind].cursor===null)return;ownership[kind].history.push(ownership[kind].cursor);action(current=>ownedPage(kind,current))};
  }
  function clearOwned(){selectedUser=null;selectedProfile=null;for(const item of Object.values(ownership)){item.panel.hidden=true;item.rows.replaceChildren();item.status.textContent='';item.history=[0];item.cursor=null}}
  async function ownedPage(kind,current){
    const item=ownership[kind],params=new URLSearchParams({kind,limit:'25'}),after=item.history.at(-1);if(after)params.set('after',after);
    try{
      const result=await request('/api/admin/users/'+selectedUser+'/guitars?'+params);
      if(current!==epoch)return;
      if(typeof result.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(result.total)||!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||typeof result.next_after==='string'&&/^[1-9][0-9]*$/.test(result.next_after)))throw Error('Invalid ownership page');
      item.rows.replaceChildren();item.cursor=result.next_after;item.status.textContent=t(result.total==='0'?'users.ownership_empty':'users.ownership_total',{count:result.total});
      for(const row of result.items){
        if(typeof row.id!=='string'||!/^[1-9][0-9]*$/.test(row.id))throw Error('Invalid guitar identifier');
        const button=document.createElement('button');button.textContent=[row.manufacturer,row.model,row.year,row.serial_number].filter(Boolean).join(' · ')||'#'+row.id;button.onclick=()=>onGuitar(row.id);item.rows.append(button);
      }
    }catch(error){
      if(current!==epoch)return;
      item.rows.replaceChildren();item.cursor=null;item.status.textContent=t('users.ownership_unavailable');
      if([401,403].includes(error.status)){clear();onUnauthorized(error)}
    }
  }
  const fields=['id','app_user_id','display_name','account_type','role','disabled','ban_status','location_country','location_region','bio','created_at','updated_at'];
  function render(){
    edit.hidden=detailRefresh.hidden=!authorized()||selectedUser===null;edit.disabled=busy||!selectedProfile||!(/^[1-9][0-9]*$/.test(selectedProfile.profile_revision||''));detailRefresh.disabled=busy;
    $('userBrowser').hidden=$('cloudUserDetail').hidden=!authorized();
    for(const id of ['userSearch','userSearchSubmit','userRefresh'])$(id).disabled=busy||!authorized();
    $('userPrevious').disabled=busy||!authorized()||history.length<2;
    $('userNext').disabled=busy||!authorized()||next===null;
    for(const button of $('userRows').querySelectorAll('button'))button.disabled=busy;
    for(const item of Object.values(ownership)){
      item.panel.hidden=!authorized()||selectedUser===null;
      item.refresh.disabled=busy||!authorized();item.previous.disabled=busy||!authorized()||item.history.length<2;item.next.disabled=busy||!authorized()||item.cursor===null;
      for(const button of item.rows.querySelectorAll('button'))button.disabled=busy||!authorized();
    }
  }
  function clear(){closeProfile();profileStatus.textContent='';clearOwned();epoch++;next=null;history=[0];query='';$('userRows').replaceChildren();$('userDetailFields').replaceChildren();$('userStatus').textContent='';$('userSearch').value='';$('userDetailEmpty').hidden=false;render()}
  function failed(error){
    closeProfile();selectedProfile=null;
    clearOwned();
    $('userRows').replaceChildren();$('userDetailFields').replaceChildren();$('userDetailEmpty').hidden=false;next=null;
    if([401,403].includes(error.status)){clear();onUnauthorized(error)}
    $('userStatus').textContent=t(error.status===404?'users.missing':'users.unavailable');
  }
  async function action(work){
    if(busy||!authorized())return;
    busy=true;const current=++epoch;render();
    try{await work(current)}catch(error){if(current===epoch)failed(error)}finally{busy=false;render()}
  }
  async function page(current){
    const params=new URLSearchParams({q:query,limit:'25'}),after=history.at(-1);if(after)params.set('after',String(after));
    const result=await request('/api/admin/users?'+params);
    if(current!==epoch)return;
    if(typeof result.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(result.total)||!Array.isArray(result.items)||result.items.length>25||!(result.next_after===null||typeof result.next_after==='string'&&/^[1-9][0-9]*$/.test(result.next_after)))throw Error('Invalid page');
    $('userRows').replaceChildren();next=result.next_after;
    for(const row of result.items){
      const tr=document.createElement('tr');
      for(const field of ['display_name','account_type','role','disabled']){const td=document.createElement('td');td.textContent=field==='disabled'?t('users.disabled_'+row[field]):row[field]??'—';tr.append(td)}
      const td=document.createElement('td'),button=document.createElement('button');button.textContent=t('action.detail');button.onclick=()=>detail(row.id);td.append(button);tr.append(td);$('userRows').append(tr);
    }
    $('userStatus').textContent=t('users.total_count',{count:result.total});
  }
  function refresh(){return action(page)}
  async function loadDetail(id,current,jump=true){
    closeProfile();profileStatus.textContent='';
    if(typeof id!=='string'||!/^[1-9][0-9]*$/.test(id))throw Error('Invalid identifier');
    clearOwned();render();const row=await request('/api/admin/users/'+id);
    if(current!==epoch)return;
    $('userDetailFields').replaceChildren();
    for(const field of fields){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t('users.field_'+field);dd.textContent=field==='disabled'?t('users.disabled_'+row[field]):row[field]??'—';$('userDetailFields').append(dt,dd)}
    selectedUser=id;selectedProfile=row;for(const kind of ['owned','formerly_owned']){if(current!==epoch)return;await ownedPage(kind,current)}
    if(current!==epoch)return;
    $('userDetailEmpty').hidden=true;if(jump)$('cloudUserDetail').scrollIntoView({block:'start'});
  }
  function detail(id){return action(current=>loadDetail(id,current))}
  $('userSearchForm').onsubmit=event=>{event.preventDefault();if(busy)return;query=$('userSearch').value.trim();history=[0];refresh()};
  $('userRefresh').onclick=()=>refresh();
  $('userNext').onclick=()=>{if(busy||next===null)return;history.push(next);refresh()};
  $('userPrevious').onclick=()=>{if(busy||history.length<2)return;history.pop();refresh()};
  return {render,clear,refresh};
}
