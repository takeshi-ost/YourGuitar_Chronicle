export function createBackupBrowser({request,authorized,onUnauthorized,maintenanceMode=()=>false}){
  const $=id=>document.getElementById(id),t=k=>YGCI18n.t(k);
  let busy=false,epoch=0,timer=null,available=false,pending=false,maintenanceAvailable=false,maintenancePending=false,selection=null;
  function render(){
    $('backupBrowser').hidden=!authorized();
    $('backupTarget').disabled=$('backupRefresh').disabled=busy||maintenancePending||!authorized();
    $('backupSave').disabled=busy||pending||maintenancePending||!available||!authorized();
    $('backupReset').disabled=busy||pending||maintenancePending||!maintenanceAvailable||!authorized()||!maintenanceMode();
    for(const button of $('backupRows').querySelectorAll('button'))button.disabled=$('backupReset').disabled;
    $('backupConfirm').disabled=!selection||$('backupConfirmation').value!==selection.target;
    for(const id of ['backupScheduled','backupInterval','backupKeep','backupPolicySave'])$(id).disabled=busy||pending||maintenancePending||!available||!authorized();
  }
  function clear(){epoch++;clearTimeout(timer);timer=null;available=false;pending=false;maintenanceAvailable=false;maintenancePending=false;selection=null;$('backupDialog').close();$('backupMaintenanceStatus').textContent='';$('backupRows').replaceChildren();$('backupStatus').textContent='';$('backupSaveStatus').textContent='';$('backupPolicyStatus').textContent='';render()}
  function display(state){
    pending=['starting','running','unknown'].includes(state.state)&&!state.retry_allowed;
    $('backupSaveStatus').textContent=state.state==='idle'?'':t('backups.'+state.state);
    if(pending&&authorized())timer=setTimeout(()=>refresh(),5000);
  }
  async function refresh(){
    if(busy||!authorized())return;
    clearTimeout(timer);timer=null;busy=true;const current=++epoch;render();
    try{
      const target=$('backupTarget').value;
      const result=await request('/api/admin/backups?'+new URLSearchParams({target}));
      if(current!==epoch)return;
      available=result.save_available===true;maintenanceAvailable=result.maintenance_available===true;
      if(available){const policy=await request('/api/admin/backups/policy?'+new URLSearchParams({target}));if(current!==epoch)return;$('backupScheduled').checked=policy.enabled;$('backupInterval').value=policy.interval_hours;$('backupKeep').value=policy.generations;}
      $('backupRows').replaceChildren();
      for(const row of result.items){const tr=document.createElement('tr');for(const value of [row.created_at,row.schema_version,row.tables,row.rows]){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}const td=document.createElement('td'),button=document.createElement('button');button.textContent=t('backups.restore');button.onclick=()=>open('restore',row.backup_id);td.append(button);tr.append(td);$('backupRows').append(tr)}
      $('backupStatus').textContent=t(result.items.length?'backups.loaded':'backups.empty');
      if(available){const state=await request('/api/admin/backups/save-status?'+new URLSearchParams({target}));if(current===epoch)display(state)}
      if(maintenanceAvailable){const state=await request('/api/admin/databases/status?'+new URLSearchParams({target}));if(current===epoch)maintenanceDisplay(state)}
    }catch(error){
      if(current!==epoch)return;
      clear();if([401,403].includes(error.status))onUnauthorized(error);
      $('backupStatus').textContent=t('backups.failed');
    }finally{busy=false;render()}
  }
  async function save(){
    if(busy||pending||maintenancePending||!available||!authorized())return;
    clearTimeout(timer);timer=null;busy=true;const current=++epoch;render();
    try{
      const result=await request('/api/admin/backups/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:$('backupTarget').value,request_id:crypto.randomUUID()})});
      if(current===epoch)display(result);
    }catch(error){
      if(current!==epoch)return;
      if([401,403].includes(error.status)){clear();onUnauthorized(error)}
      else {$('backupSaveStatus').textContent=t(error.status===409?'backups.busy':'backups.unknown');pending=true;timer=setTimeout(()=>refresh(),5000)}
    }finally{busy=false;render()}
  }
  $('backupPolicy').onsubmit=async event=>{
    event.preventDefault();if(busy||pending||maintenancePending||!available||!authorized())return;
    busy=true;const current=++epoch;render();
    try{await request('/api/admin/backups/policy',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:$('backupTarget').value,generations:Number($('backupKeep').value),enabled:$('backupScheduled').checked,interval_hours:Number($('backupInterval').value)})});if(current===epoch)$('backupPolicyStatus').textContent=t('backups.policy_saved')}
    catch(error){if(current===epoch){if([401,403].includes(error.status)){clear();onUnauthorized(error)}else $('backupPolicyStatus').textContent=t('backups.failed')}}
    finally{busy=false;render()}
  };
  function open(action,backup_id=null){
    if($('backupReset').disabled)return;
    selection={target:$('backupTarget').value,action,backup_id};
    $('backupDialogTitle').textContent=t('backups.'+action)+' — '+selection.target;
    $('backupConfirmation').value='';render();$('backupDialog').showModal();$('backupConfirmation').focus();
  }
  function maintenanceDisplay(state){
    maintenancePending=['starting','running','unknown'].includes(state.state)&&!state.retry_allowed;
    $('backupMaintenanceStatus').textContent=state.state==='idle'?'':t('backups.maintenance_'+state.state);
    if(maintenancePending){clearTimeout(timer);timer=null;if(authorized())timer=setTimeout(()=>pollMaintenance(),5000);}
    render();
  }
  async function pollMaintenance(){
    if(!authorized())return;const current=epoch,target=$('backupTarget').value;
    try{const state=await request('/api/admin/databases/status?'+new URLSearchParams({target}));if(current!==epoch)return;maintenanceDisplay(state);if(!maintenancePending)refresh()}
    catch(error){if(current!==epoch)return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else timer=setTimeout(()=>pollMaintenance(),5000)}
  }
  $('backupReset').onclick=()=>open('reset');
  $('backupCancel').onclick=()=>$('backupDialog').close();
  $('backupDialog').addEventListener('click',event=>{const r=$('backupDialog').getBoundingClientRect();if(event.target===$('backupDialog')&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom))$('backupDialog').close()});
  $('backupConfirmation').oninput=render;
  $('backupConfirm').onclick=async()=>{
    if(!selection||$('backupConfirm').disabled||!maintenanceMode()||busy)return;
    const payload={...selection,request_id:crypto.randomUUID(),confirmation:$('backupConfirmation').value};
    $('backupDialog').close();selection=null;clearTimeout(timer);busy=true;const current=++epoch;render();
    try{const state=await request('/api/admin/databases/maintain',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(current===epoch)maintenanceDisplay(state)}
    catch(error){if(current!==epoch)return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else{$('backupMaintenanceStatus').textContent=t(error.status===409?'backups.busy':'backups.unknown');maintenancePending=true;timer=setTimeout(()=>pollMaintenance(),5000)}}
    finally{busy=false;render()}
  };
  $('backupSave').onclick=()=>save();$('backupRefresh').onclick=()=>refresh();$('backupTarget').onchange=()=>{clear();refresh()};
  return {render,clear,refresh};
}
