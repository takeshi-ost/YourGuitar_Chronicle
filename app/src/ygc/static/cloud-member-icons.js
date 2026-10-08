// Images are fetched with Bearer credentials, never assigned an authenticated
// endpoint or storage URL as img.src. Object URLs live only in this page.
export function createMemberIcons({document,window,auth,identity,eligible}) {
  const entries=new Map();
  let running=0,active=!document.hidden;
  const queue=[];
  function reset(entry) {
    entry.version++;
    entry.controller?.abort();
    entry.controller=null;
    if(entry.url)window.URL.revokeObjectURL(entry.url);
    entry.url=null;
    entry.host.replaceChildren();
    entry.host.textContent='♙';
  }
  function current(entry,version,owner) {
    return active&&!document.hidden&&eligible()&&owner===identity()&&
      entries.get(entry.host)===entry&&entry.version===version&&entry.host.isConnected;
  }
  async function read(entry,version,owner) {
    if(!current(entry,version,owner))return;
    const controller=new window.AbortController();entry.controller=controller;
    try {
      const response=await auth().authorizedFetch('/api/auth/members/'+entry.id+'/avatar',{
        method:'GET',cache:'no-store',credentials:'omit',redirect:'error',signal:controller.signal
      },true);
      if(!current(entry,version,owner)||!response.ok)return;
      if(response.headers.get('Content-Type')?.split(';')[0]!=='image/jpeg')return;
      const blob=await response.blob();
      if(!current(entry,version,owner)||blob.size===0||blob.size>25*1024*1024)return;
      const url=window.URL.createObjectURL(blob);
      if(!current(entry,version,owner)){window.URL.revokeObjectURL(url);return}
      entry.url=url;
      const image=document.createElement('img');image.alt='';image.src=url;
      image.addEventListener('error',()=>{if(entry.url===url)reset(entry)},{once:true});
      entry.host.replaceChildren(image);
    } catch {/* Denial, stale identity, abort and storage failure retain the placeholder. */}
    finally {if(entry.controller===controller)entry.controller=null}
  }
  function pump() {
    while(running<4&&queue.length){
      const job=queue.shift();running++;
      void read(...job).finally(()=>{running--;pump()});
    }
  }
  function enqueue(entry) {queue.push([entry,entry.version,identity()]);pump()}
  function mount(host,id) {
    const previous=entries.get(host);if(previous)reset(previous);
    const entry={host,id,version:0,url:null,controller:null};entries.set(host,entry);
    reset(entry);
    // List renderers attach the node synchronously before this microtask runs.
    queueMicrotask(()=>{if(entries.get(host)===entry)enqueue(entry)});
  }
  function clear(root=null) {
    for(const [host,entry] of entries)if(!root||root===host||root.contains(host)){
      reset(entry);entries.delete(host);
    }
    if(!root)queue.length=0;
  }
  function invalidate() {queue.length=0;for(const entry of entries.values())reset(entry)}
  function refresh() {
    invalidate();
    for(const [host,entry] of entries){
      if(!host.isConnected){entries.delete(host);continue}
      if(active&&!document.hidden&&eligible())enqueue(entry);
    }
  }
  // Remote changes are rechecked while visible; leaving a page immediately
  // removes bytes. Previously delivered pixels cannot be recalled remotely.
  const timer=window.setInterval(refresh,30000);
  window.addEventListener('blur',()=>{active=false;invalidate()});
  window.addEventListener('focus',()=>{active=true;refresh()});
  document.addEventListener('visibilitychange',()=>{
    active=!document.hidden;if(active)refresh();else invalidate();
  });
  window.addEventListener('pagehide',()=>{active=false;clear()});
  window.addEventListener('pageshow',()=>{active=!document.hidden;refresh()});
  let channel;
  try {channel=new window.BroadcastChannel('ygc-member-avatar');channel.onmessage=refresh} catch {}
  function announce() {try{channel?.postMessage('invalidate')}catch{}refresh()}
  return {mount,clear,refresh,announce,destroy(){clear();window.clearInterval(timer);channel?.close()}};
}
