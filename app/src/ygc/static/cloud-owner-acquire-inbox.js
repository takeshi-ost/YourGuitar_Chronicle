// An advisory list only: openOwner re-reads authority and revision before writing.
export function createOwnerAcquireInbox({root,auth,state,busy,openOwner}){
  const t=(key)=>globalThis.YGCI18n.t(key),identity=()=>JSON.stringify([state()?.user?.app_user_id,state()?.identity?.email_verified,state()?.user?.status]);
  const eligible=()=>Boolean(state()?.user&&state()?.identity?.email_verified===true&&(!state().user.status||state().user.status==='active'));
  let actor=identity(),epoch=0,rows=[],notice='',painted=null;
  root.className='important-information-group';root.hidden=true;
  function clear(){actor=identity();epoch++;rows=[];notice='';painted=null;root.replaceChildren();root.hidden=true}
  function render(){
    if(actor!==identity()||!eligible()){clear();return}
    const signature=JSON.stringify([epoch,rows,notice]);
    if(signature===painted){for(const button of root.querySelectorAll('button'))button.disabled=busy()||button.dataset.canWrite!=='true';return}
    painted=signature;root.replaceChildren();root.hidden=!rows.length&&!notice;
    if(notice){const status=document.createElement('p');status.setAttribute('role','status');status.textContent=notice;root.append(status)}
    if(!rows.length)return;
    const title=document.createElement('h2');title.textContent=t('owner.acquire_inbox');root.append(title);
    const version=epoch,account=identity();
    for(const row of rows){
      const item=document.createElement('div'),text=document.createElement('p'),actions=document.createElement('div');item.className='unanswered-request';
      const guitar=document.createElement('a');guitar.textContent=row.product_name||'#'+row.individual_id;guitar.href='/ui/profile/guitars/'+encodeURIComponent(row.individual_id);
      text.append(row.author_name+' '+t('owner.claims_ownership')+' ',guitar);
      for(const [key,stance] of [['accept','positive'],['decline','negative']]){
        const button=document.createElement('button');button.type='button';button.textContent=t('owner.'+key);button.disabled=busy()||row.can_write!==true;button.dataset.canWrite=String(row.can_write);
        if(key==='accept')button.dataset.uiAction='primary';else button.className='secondary';
        button.onclick=()=>{if(version!==epoch||account!==identity()||!eligible()||busy()||row.can_write!==true)return;return openOwner(row.individual_id,row.id,stance,button)};
        actions.append(button);
      }
      item.append(text,actions);root.append(item);
    }
  }
  async function refresh(){
    if(actor!==identity())clear();if(!eligible()){clear();return}
    const version=++epoch,account=identity(),valid=()=>version===epoch&&account===identity()&&eligible();rows=[];notice='';render();
    try{
      let after=null;const all=[],seen=new Set();
      do{
        const response=await auth().authorizedFetch('/api/auth/owner-acquire-requests'+(after?'?after='+after:''),{cache:'no-store',credentials:'omit',redirect:'error'},false);
        if(!valid())return;if(!response.ok)throw Object.assign(Error('Owner inbox unavailable'),{status:response.status});
        const data=await response.json();if(!valid())return;
        const id=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value);
        if(!Array.isArray(data.items)||data.items.length>50||!(data.next_after===null||id(data.next_after))||data.items.some(row=>!row||!id(row.id)||!id(row.individual_id)||typeof row.author_name!=='string'||typeof row.product_name!=='string'||typeof row.can_write!=='boolean'))throw Error('Invalid inbox');
        for(const row of data.items){if(BigInt(row.id)<=BigInt(after||0)||seen.has(row.id))throw Error('Invalid inbox cursor');seen.add(row.id);all.push(row)}
        if(data.next_after!==null&&(BigInt(data.next_after)<=BigInt(after||0)||data.items.some(row=>BigInt(row.id)>BigInt(data.next_after))))throw Error('Invalid inbox cursor');
        after=data.next_after;
      }while(after!==null);
      rows=all;
    }catch(error){if(!valid())return;rows=[];notice=[401,403,404].includes(error.status)?'':t('owner.inbox_unavailable')}
    render();
  }
  return {clear,render,refresh};
}
