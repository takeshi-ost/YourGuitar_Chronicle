// Binary images use the same-origin Bearer adapter; no tokens in image URLs.
export function createAvatar({auth,state,busy}){
  const $=id=>document.getElementById(id),t=key=>globalThis.YGCI18n.t(key);
  let url=null,hasImage=false;
  const path=()=>state()?.user?.role==='admin'?'/api/admin/accounts/me/avatar':'/api/auth/avatar';
  function clear(){if(url)URL.revokeObjectURL(url);url=null;hasImage=false;$('avatarPreview').removeAttribute('src');$('avatarPreview').hidden=true;$('avatarStatus').textContent='';$('avatarFile').value=''}
  function render(){
    const eligible=Boolean(state()?.user&&state()?.identity?.email_verified===true);
    $('accountAvatar').hidden=!eligible;
    for(const id of ['avatarFile','avatarUpload','avatarRefresh'])$(id).disabled=busy()||!eligible;
    $('avatarRemove').disabled=busy()||!eligible||!hasImage;
    if(!eligible)clear();
  }
  async function refresh(){
    const response=await auth().authorizedFetch(path(),{},true);
    if(response.status===404){clear();$('avatarStatus').textContent=t('avatar.empty');return}
    if(!response.ok)throw Object.assign(Error('Image unavailable'),{status:response.status});
    if(!response.headers.get('Content-Type')?.startsWith('image/jpeg'))throw Error('Unexpected image type');
    const blob=await response.blob();if(blob.size>25*1024*1024)throw Error('Image exceeds limit');
    clear();url=URL.createObjectURL(blob);hasImage=true;$('avatarPreview').src=url;$('avatarPreview').hidden=false;
  }
  async function save(file){
    if(!file||!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024)throw Object.assign(Error('Invalid image'),{status:400});
    const response=await auth().authorizedFetch(path(),{method:'PUT',headers:{'Content-Type':file.type},body:file},true);
    if(!response.ok)throw Object.assign(Error('Save failed'),{status:response.status});
    await refresh();$('avatarStatus').textContent=t('avatar.saved');
  }
  async function remove(){
    const response=await auth().authorizedFetch(path(),{method:'DELETE'},true);
    if(!response.ok)throw Object.assign(Error('Remove failed'),{status:response.status});
    clear();$('avatarStatus').textContent=t('avatar.removed');
  }
  function failed(error){
    if([401,403].includes(error.status))clear();
    $('avatarStatus').textContent=t([400,413].includes(error.status)?'avatar.invalid':error.status===403?'avatar.restricted':'avatar.failed');
  }
  globalThis.addEventListener('pagehide',clear);
  return {render,refresh,save,remove,failed,clear};
}
