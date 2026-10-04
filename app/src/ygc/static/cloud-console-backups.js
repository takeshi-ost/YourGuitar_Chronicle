export function createBackupBrowser({request,authorized,onUnauthorized}){
  const $=id=>document.getElementById(id),t=k=>YGCI18n.t(k);
  let busy=false,epoch=0,timer=null,available=false,pending=false;
  function render(){
    $('backupBrowser').hidden=!authorized();
    $('backupTarget').disabled=$('backupRefresh').disabled=busy||!authorized();
    $('backupSave').disabled=busy||pending||!available||!authorized();
    for(const id of ['backupScheduled','backupInterval','backupKeep','backupPolicySave'])$(id).disabled=busy||pending||!available||!authorized();
  }
  function clear(){epoch++;clearTimeout(timer);timer=null;available=false;pending=false;$('backupRows').replaceChildren();$('backupStatus').textContent='';$('backupSaveStatus').textContent='';$('backupPolicyStatus').textContent='';render()}
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
      available=result.save_available===true;
      if(available){const policy=await request('/api/admin/backups/policy?'+new URLSearchParams({target}));if(current!==epoch)return;$('backupScheduled').checked=policy.enabled;$('backupInterval').value=policy.interval_hours;$('backupKeep').value=policy.generations;}
      $('backupRows').replaceChildren();
      for(const row of result.items){const tr=document.createElement('tr');for(const value of [row.created_at,row.schema_version,row.tables,row.rows]){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}$('backupRows').append(tr)}
      $('backupStatus').textContent=t(result.items.length?'backups.loaded':'backups.empty');
      if(available){const state=await request('/api/admin/backups/save-status?'+new URLSearchParams({target}));if(current===epoch)display(state)}
    }catch(error){
      if(current!==epoch)return;
      clear();if([401,403].includes(error.status))onUnauthorized(error);
      $('backupStatus').textContent=t('backups.failed');
    }finally{busy=false;render()}
  }
  async function save(){
    if(busy||pending||!available||!authorized())return;
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
    event.preventDefault();if(busy||pending||!available||!authorized())return;
    busy=true;const current=++epoch;render();
    try{await request('/api/admin/backups/policy',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:$('backupTarget').value,generations:Number($('backupKeep').value),enabled:$('backupScheduled').checked,interval_hours:Number($('backupInterval').value)})});if(current===epoch)$('backupPolicyStatus').textContent=t('backups.policy_saved')}
    catch(error){if(current===epoch){if([401,403].includes(error.status)){clear();onUnauthorized(error)}else $('backupPolicyStatus').textContent=t('backups.failed')}}
    finally{busy=false;render()}
  };
  $('backupSave').onclick=()=>save();$('backupRefresh').onclick=()=>refresh();$('backupTarget').onchange=()=>{clear();refresh()};
  return {render,clear,refresh};
}
