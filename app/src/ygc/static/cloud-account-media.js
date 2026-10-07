// Private Media never exposes storage references or authenticated API URLs in
// markup. Each view owns its blob URLs and discards every late response.
export function validateMediaItems(items){
  if(!Array.isArray(items)||!items.length||items.length>10||items.some(item=>!item||typeof item.id!=='string'||!/^[1-9][0-9]{0,18}$/.test(item.id)||(item.id.length===19&&item.id>'9223372036854775807')||item.mime_type!=='image/jpeg')||new Set(items.map(item=>item.id)).size!==items.length)throw Error('Invalid private Media');
  return Object.freeze(items.map(item=>Object.freeze({id:item.id,mime_type:'image/jpeg'})));
}
export function validMediaFiles(files){
  return files.length>=1&&files.length<=10&&files.reduce((total,file)=>total+file.size,0)<=24*1024*1024&&files.every(file=>['image/jpeg','image/png','image/webp'].includes(file.type)&&file.size>0&&file.size<=8*1024*1024);
}
export function createPrivateMedia({auth,container,isCurrent,onState=()=>{},onError=()=>{}}){
  let epoch=0,urls=[],images=[],requestController=null;
  const t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  function clear(){
    epoch++;requestController?.abort();requestController=null;
    for(const img of images)img.removeAttribute('src');
    for(const url of urls)URL.revokeObjectURL(url);
    urls=[];images=[];container.replaceChildren();onState(false);
  }
  async function display(sources,getBlob,local){
    clear();const version=epoch,valid=()=>version===epoch&&isCurrent(),controller=new AbortController();requestController=controller;
    try{
      for(let index=0;index<sources.length;index++){
        const blob=await getBlob(sources[index],controller.signal);if(!valid())return;
        if(!blob||!blob.size||blob.size>8*1024*1024||!(local?['image/jpeg','image/png','image/webp']:['image/jpeg']).includes(blob.type))throw Error('Invalid private image');
        const url=URL.createObjectURL(blob),img=document.createElement('img');urls.push(url);images.push(img);
        img.alt=t('claims.media_photo',{number:index+1});img.src=url;
        // Loading bytes alone is insufficient for an Owner to review a photo.
        await img.decode();if(!valid())return;
        if(!img.naturalWidth||!img.naturalHeight||img.naturalWidth*img.naturalHeight>8000000)throw Object.assign(Error('Invalid image dimensions'),{status:400});
        const figure=document.createElement('figure'),caption=document.createElement('figcaption');caption.textContent=t('claims.media_photo',{number:index+1});figure.append(img,caption);container.append(figure);
      }
      if(valid())onState(true);
    }catch(error){if(valid()){clear();onError(error)}}
  }
  function load(individualId,row){
    let items;try{
      if(![individualId,row.id].every(id=>typeof id==='string'&&/^[1-9][0-9]{0,18}$/.test(id)&&(id.length<19||id<='9223372036854775807'))||typeof row.revision!=='string'||!/^[a-f0-9]{64}$/.test(row.revision))throw Error('Invalid private photo address');
      items=validateMediaItems(row.media_items)
    }catch(error){clear();onError(error);return Promise.resolve()}
    return display(items,async(item,signal)=>{
      const response=await auth().authorizedFetch('/api/auth/guitars/'+individualId+'/claims/'+row.id+'/media/'+item.id+'?revision='+encodeURIComponent(row.revision),{cache:'no-store',credentials:'omit',redirect:'error',signal},true);
      if(!response.ok)throw Object.assign(Error('Private photo unavailable'),{status:response.status});
      return response.blob();
    },false);
  }
  function preview(files){
    if(!validMediaFiles(files)){clear();onError(Object.assign(Error('Invalid image selection'),{status:400}));return Promise.resolve()}
    return display(files,async file=>file,true);
  }
  return {clear,load,preview};
}
