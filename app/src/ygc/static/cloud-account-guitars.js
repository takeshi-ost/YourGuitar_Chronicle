export function createGuitars({auth,state,busy,work}){
  const root=document.getElementById('selfGuitars'),t=(key,params={})=>globalThis.YGCI18n.t(key,params);
  let epoch=0;
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true);
  const panels={};
  for(const kind of ['owned','formerly_owned']){
    const section=document.createElement('section'),title=document.createElement('h2'),status=document.createElement('p'),list=document.createElement('ul');
    section.id='selfGuitars_'+kind;title.textContent=t('users.'+kind);status.className='self-guitar-status';status.setAttribute('role','status');list.className='self-guitar-list';
    const refresh=document.createElement('button'),previous=document.createElement('button'),next=document.createElement('button');
    for(const [button,key] of [[refresh,'action.refresh'],[previous,'users.previous'],[next,'users.next']]){button.type='button';button.textContent=t(key)}
    section.append(title,status,list,refresh,previous,next);root.append(section);
    panels[kind]={status,list,refresh,previous,next,history:[0],nextAfter:null};
    refresh.onclick=()=>{if(busy())return;panels[kind].history=[0];work(()=>page(kind))};
    previous.onclick=()=>{const panel=panels[kind];if(busy()||panel.history.length<2)return;panel.history.pop();work(()=>page(kind))};
    next.onclick=()=>{const panel=panels[kind];if(busy()||panel.nextAfter===null)return;panel.history.push(panel.nextAfter);work(()=>page(kind))};
  }
  function render(){
    root.hidden=!eligible();
    for(const panel of Object.values(panels)){
      panel.refresh.disabled=busy()||!eligible();panel.previous.disabled=busy()||!eligible()||panel.history.length<2;panel.next.disabled=busy()||!eligible()||panel.nextAfter===null;
    }
    if(!eligible())clear();
  }
  function clear(){epoch++;for(const panel of Object.values(panels)){panel.history=[0];panel.nextAfter=null;panel.list.replaceChildren();panel.status.textContent=''}}
  async function page(kind){
    const current=epoch,panel=panels[kind],owner=state()?.user?.app_user_id;
    panel.list.replaceChildren();panel.nextAfter=null;panel.status.textContent=t('cloud.working');
    try{
      const params=new URLSearchParams({kind,limit:'25'}),after=panel.history.at(-1);if(after)params.set('after',after);
      const response=await auth().authorizedFetch('/api/auth/guitars?'+params,{},true);
      if(!response.ok)throw Object.assign(Error('Ownership unavailable'),{status:response.status});
      const data=await response.json();if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;
      if(typeof data.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(data.total)||!Array.isArray(data.items)||data.items.length>25||!(data.next_after===null||typeof data.next_after==='string'&&/^[1-9][0-9]*$/.test(data.next_after))||data.items.some(row=>!row||typeof row.id!=='string'||!/^[1-9][0-9]*$/.test(row.id)))throw Error('Invalid ownership page');
      for(const row of data.items){const item=document.createElement('li');item.textContent='#'+row.id+' · '+[row.manufacturer,row.model,row.year,row.serial_number].map(value=>value??'—').join(' · ');panel.list.append(item)}
      panel.nextAfter=data.next_after;panel.status.textContent=t(data.total==='0'?'users.ownership_empty':'guitars.total_count',{count:data.total});
    }catch(error){
      if(current!==epoch||owner!==state()?.user?.app_user_id||!eligible())return;
      if([401,403].includes(error.status)){
        clear();for(const item of Object.values(panels))item.status.textContent=t('self_profile.restricted');
      }else{
        panel.history=[0];panel.list.replaceChildren();panel.status.textContent=t('users.ownership_unavailable');
      }
    }
    render();
  }
  async function refresh(){
    epoch++;for(const panel of Object.values(panels))panel.history=[0];
    await Promise.all(['owned','formerly_owned'].map(page));
  }
  return {render,refresh,clear};
}
