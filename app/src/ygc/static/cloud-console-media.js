export function createMediaBrowser({request,authorized,selected,busy,work,onUnauthorized,updated}){
  const t=(key,params={})=>YGCI18n.t(key,params),panel=document.createElement('section');panel.id='contentMediaPanel';
  const title=document.createElement('h3'),form=document.createElement('form'),file=document.createElement('input'),save=document.createElement('button'),refreshButton=document.createElement('button'),previous=document.createElement('button'),next=document.createElement('button'),status=document.createElement('p'),rows=document.createElement('ul');
  title.textContent=t('content_media.heading');file.type='file';file.accept='image/jpeg,image/png,image/webp';file.required=true;file.id='contentMediaFile';file.setAttribute('aria-label',t('avatar.choose'));
  save.type='submit';save.id='contentMediaSave';save.textContent=t('content_media.save');
  for(const [button,key] of [[refreshButton,'action.refresh'],[previous,'users.previous'],[next,'users.next']]){button.type='button';button.textContent=t(key)}
  status.id='contentMediaStatus';status.setAttribute('role','status');rows.id='contentMediaRows';const limits=document.createElement('p');limits.textContent=t('content_media.limits');form.append(file,save,limits);panel.append(title,form,refreshButton,status,rows,previous,next);document.getElementById('cloudProductDetail').insertBefore(panel,document.getElementById('chroniclePanel'));
  const dialog=document.createElement('dialog'),image=document.createElement('img'),close=document.createElement('button');dialog.id='contentMediaDialog';image.id='mediaPreview';image.alt=t('content_media.heading');close.textContent=t('action.close');close.type='button';dialog.append(image,close);document.body.append(dialog);
  let epoch=0,history=[0],cursor=null,url=null;
  const revoke=()=>{if(url)URL.revokeObjectURL(url);url=null;image.removeAttribute('src')};
  close.onclick=()=>YGCOverlays.close(dialog);dialog.addEventListener('ygc:closed',revoke);
  function clear(){epoch++;history=[0];cursor=null;rows.replaceChildren();status.textContent='';file.value='';YGCOverlays.close(dialog);revoke()}
  function render(){panel.hidden=!authorized()||selected()===null;file.disabled=save.disabled=refreshButton.disabled=busy()||!authorized();previous.disabled=busy()||history.length<2;next.disabled=busy()||cursor===null;for(const b of rows.querySelectorAll('button'))b.disabled=busy()}
  async function refresh(){
    const current=++epoch,id=selected();rows.replaceChildren();cursor=null;status.textContent=t('cloud.working');
    try{
      const after=history.at(-1),data=await request('/api/admin/guitars/'+id+'/media'+(after?'?after='+after:''));
      if(current!==epoch||id!==selected()||!authorized())return;
      if(!Array.isArray(data.items)||data.items.length>25||typeof data.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(data.total)||!(data.next_after===null||typeof data.next_after==='string'&&/^[1-9][0-9]*$/.test(data.next_after)))throw Error('Invalid media page');
      cursor=data.next_after;status.textContent=t('content_media.total',{count:data.total});
      for(const row of data.items){
        if(typeof row.id!=='string'||!/^[1-9][0-9]*$/.test(row.id))throw Error('Invalid media identifier');
        const item=document.createElement('li'),button=document.createElement('button');item.textContent='#'+row.id+' · '+(row.captured_at||'—')+' ';button.type='button';button.textContent=t('action.detail');
        button.onclick=()=>work(async()=>{try{const blob=await request('/api/admin/guitars/'+id+'/media/'+row.id,{},true);if(current!==epoch||id!==selected()||!authorized())return;revoke();url=URL.createObjectURL(blob);image.src=url;YGCOverlays.open(dialog)}catch(error){if(current!==epoch||id!==selected()||!authorized())return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else status.textContent=t('content_media.failed')}});
        item.append(button);rows.append(item);
      }
    }catch(error){if(current!==epoch||id!==selected()||!authorized())return;rows.replaceChildren();cursor=null;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else status.textContent=t('content_media.failed')}
    render();
  }
  refreshButton.onclick=()=>{history=[0];work(refresh)};
  previous.onclick=()=>{if(busy()||history.length<2)return;history.pop();work(refresh)};
  next.onclick=()=>{if(busy()||cursor===null)return;history.push(cursor);work(refresh)};
  form.onsubmit=event=>{
    event.preventDefault();if(busy()||!authorized()||selected()===null)return;
    const upload=file.files[0],id=selected(),savedEpoch=epoch;if(!upload||upload.size>8*1024*1024||!['image/jpeg','image/png','image/webp'].includes(upload.type)){status.textContent=t('avatar.invalid');return}
    work(async current=>{try{await request('/api/admin/guitars/'+id+'/media',{method:'POST',headers:{'Content-Type':upload.type},body:upload});if(savedEpoch!==epoch||id!==selected()||!authorized())return;file.value='';await updated(current);if(id!==selected()||!authorized())return;status.textContent=t('content_media.saved')}catch(error){if(savedEpoch!==epoch||id!==selected()||!authorized())return;if([401,403].includes(error.status)){clear();onUnauthorized(error)}else status.textContent=t(['image_pixel_limit','image_size_limit','image_format','invalid_image'].includes(error.code)?'content_media.'+error.code:'content_media.save_failed')}});
  };
  return {render,clear,refresh};
}
