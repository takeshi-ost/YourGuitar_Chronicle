export function createBackupBrowser({request,authorized,onUnauthorized}){
  const $=id=>document.getElementById(id),t=k=>YGCI18n.t(k);
  let busy=false,epoch=0;
  function render(){$('backupBrowser').hidden=!authorized();$('backupTarget').disabled=$('backupRefresh').disabled=busy||!authorized()}
  function clear(){epoch++;$('backupRows').replaceChildren();$('backupStatus').textContent='';render()}
  async function refresh(){
    if(busy||!authorized())return;
    busy=true;const current=++epoch;render();
    try{
      const result=await request('/api/admin/backups?'+new URLSearchParams({target:$('backupTarget').value}));
      if(current!==epoch)return;
      $('backupRows').replaceChildren();
      for(const row of result.items){const tr=document.createElement('tr');for(const value of [row.created_at,row.schema_version,row.tables,row.rows]){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}$('backupRows').append(tr)}
      $('backupStatus').textContent=t(result.items.length?'backups.loaded':'backups.empty');
    }catch(error){
      if(current!==epoch)return;
      clear();if([401,403].includes(error.status))onUnauthorized(error);
      $('backupStatus').textContent=t('backups.failed');
    }finally{busy=false;render()}
  }
  $('backupRefresh').onclick=()=>refresh();$('backupTarget').onchange=()=>{clear();refresh()};
  return {render,clear,refresh};
}
