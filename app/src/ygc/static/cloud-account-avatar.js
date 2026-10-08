// Binary images use the same-origin Bearer adapter; no tokens in image URLs.
export function createAvatar({auth,state,busy}){
  const $=id=>document.getElementById(id),t=key=>globalThis.YGCI18n.t(key);
  const fingerprint=value=>JSON.stringify([value?.user?.app_user_id??null,value?.identity?.email_verified===true,value?.user?.role??null,value?.user?.status??null]);
  const identity=()=>fingerprint(state());
  // The adapter drops its canonical account synchronously when the SDK actor
  // changes, before the shell's identity-change listener necessarily runs.
  const canonical=client=>Boolean(client&&client.signedIn!==false&&(!('account' in client)||fingerprint(client.account)===identity()));
  const eligible=()=>Boolean(!suspended&&state()?.user?.app_user_id&&state()?.identity?.email_verified===true&&(!state()?.user?.status||state().user.status==='active')&&canonical(auth()));
  let url=null,hasImage=false,epoch=0,suspended=false,renderedIdentity=identity();
  const failures=new WeakMap();
  const path=()=>state()?.user?.role==='admin'?'/api/admin/accounts/me/avatar':'/api/auth/avatar';
  function resetImage(){if(url)URL.revokeObjectURL(url);url=null;hasImage=false;$('avatarPreview').removeAttribute('src');$('avatarPreview').hidden=true;$('avatarStatus').textContent='';$('avatarFile').value=''}
  function clear(){epoch++;renderedIdentity=identity();resetImage()}
  function begin(){
    if(renderedIdentity!==identity())clear();
    if(!eligible()){clear();return null}
    return {epoch:++epoch,identity:identity(),client:auth(),path:path()};
  }
  const current=c=>Boolean(c&&c.epoch===epoch&&c.identity===identity()&&c.client===auth()&&eligible());
  function fail(error,c){
    if(!current(c))return;
    // The caller may report this rejection after another account has rendered.
    if(error&&typeof error==='object')failures.set(error,c);
    throw error;
  }
  function render(){
    if(renderedIdentity!==identity()||!eligible())clear();
    $('accountAvatar').hidden=!eligible();
    for(const id of ['avatarFile','avatarUpload','avatarRefresh'])$(id).disabled=busy()||!eligible();
    $('avatarRemove').disabled=busy()||!eligible()||!hasImage;
  }
  async function read(c){
    if(!current(c))return;
    const response=await c.client.authorizedFetch(c.path,{},true);
    if(!current(c))return;
    if(response.status===404){resetImage();$('avatarStatus').textContent=t('avatar.empty');return}
    if(!response.ok)throw Object.assign(Error('Image unavailable'),{status:response.status});
    if(!response.headers.get('Content-Type')?.startsWith('image/jpeg'))throw Error('Unexpected image type');
    const blob=await response.blob();if(!current(c))return;
    if(blob.size>25*1024*1024)throw Error('Image exceeds limit');
    const nextURL=URL.createObjectURL(blob);
    if(!current(c)){URL.revokeObjectURL(nextURL);return}
    resetImage();url=nextURL;hasImage=true;$('avatarPreview').src=url;$('avatarPreview').hidden=false;
  }
  async function refresh(){
    const c=begin();if(!c)return;
    try{await read(c)}catch(error){fail(error,c)}
  }
  async function save(file){
    const c=begin();if(!c)return;
    try{
      if(!file||!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024)throw Object.assign(Error('Invalid image'),{status:400});
      const response=await c.client.authorizedFetch(c.path,{method:'PUT',headers:{'Content-Type':file.type},body:file},true);
      if(!current(c))return;
      if(!response.ok)throw Object.assign(Error('Save failed'),{status:response.status});
      await read(c);if(current(c))$('avatarStatus').textContent=t('avatar.saved');
    }catch(error){fail(error,c)}finally{try{const c=new globalThis.BroadcastChannel('ygc-member-avatar');c.postMessage('invalidate');c.close()}catch{}}
  }
  async function remove(){
    const c=begin();if(!c)return;
    try{
      const response=await c.client.authorizedFetch(c.path,{method:'DELETE'},true);
      if(!current(c))return;
      if(!response.ok)throw Object.assign(Error('Remove failed'),{status:response.status});
      resetImage();$('avatarStatus').textContent=t('avatar.removed');
    }catch(error){fail(error,c)}finally{try{const c=new globalThis.BroadcastChannel('ygc-member-avatar');c.postMessage('invalidate');c.close()}catch{}}
  }
  function failed(error){
    if(!eligible()||failures.has(error)&&!current(failures.get(error)))return;
    if([401,403].includes(error.status))clear();
    $('avatarStatus').textContent=t([400,413].includes(error.status)?'avatar.invalid':error.status===403?'avatar.restricted':'avatar.failed');
  }
  globalThis.addEventListener('pagehide',()=>{suspended=true;clear()});
  globalThis.addEventListener('pageshow',()=>{suspended=false});
  return {render,refresh,save,remove,failed,clear};
}
