// Private selected-guitar state. Public catalog models never carry case data.
export function createDetailDispute({auth,state,busy=()=>false,openDispute,document=globalThis.document}){
  const id=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&BigInt(value)<=9223372036854775807n;
  const identity=()=>JSON.stringify([state()?.user?.app_user_id,state()?.user?.id,state()?.user?.role,state()?.user?.status,state()?.identity?.email_verified]);
  let key=null,epoch=0,selected=null,caseId=null,pending=false,failed=false,actorKey=null,lastView=null;
  const eligible=()=>Boolean(state()?.user?.app_user_id&&state()?.identity?.email_verified===true&&(!state().user.status||state().user.status==='active'));
  const blocked=()=>eligible()&&(pending||failed||caseId!==null);
  function render(){
    if(actorKey!==identity()){epoch++;key=null;selected=caseId=null;pending=failed=false;actorKey=identity();}
    document.getElementById('detailDisputeHint')?.remove();
    for(const button of document.querySelectorAll('#addClaimMenu [data-catalog-ownership],#addClaimMenu [data-ownership-entry]')){
      button.disabled=busy()||blocked();
    }
    const acquire=document.getElementById('acquireLink');
    if(acquire){acquire.setAttribute('aria-disabled',String(blocked()));if(caseId)acquire.hidden=true;}
    if(!eligible()||!selected||(!caseId&&!pending&&!failed))return;
    const header=document.querySelector('#detailContent .detail-header');if(!header)return;
    const button=document.createElement('button');button.id='detailDisputeHint';button.type='button';button.className='owner-claim-card';
    button.textContent=globalThis.YGCI18n.t(caseId?'ui.under_dispute_005fd7a2':failed?'cloud_disputes.failed':'cloud.working');button.disabled=busy()||pending;
    const saved=key,version=epoch,target=caseId,admin=state().user.role==='admin';
    button.onclick=()=>{if(key!==saved||epoch!==version||busy()||pending||!eligible())return;if(!target){key=null;return sync(lastView)}if(admin)globalThis.location.assign('/console?dispute='+target);else return openDispute(target)};
    header.append(button);
  }
  function clear(){epoch++;key=null;selected=caseId=null;pending=failed=false;render()}
  async function sync(view){
    lastView=view;
    if(view.blocked||view.loading||!id(view.selectedId)||!eligible()){clear();return;}
    const next=JSON.stringify([identity(),view.selectedId]);
    if(next===key){render();return;}
    actorKey=identity();key=next;selected=view.selectedId;caseId=null;pending=true;failed=false;const version=++epoch,actor=identity(),individual=selected;render();
    const current=()=>version===epoch&&key===next&&identity()===actor&&eligible();
    try{
      const admin=state().user.role==='admin';
      const response=await auth().authorizedFetch('/api/auth/'+(admin?'admin/':'')+'ownership-disputes?status=open&limit=1&individual='+individual,{cache:'no-store',credentials:'omit',redirect:'error'},false);
      if(!current())return;if(!response.ok)throw Error('Private dispute state unavailable');
      const value=await response.json();if(!current())return;
      if(!value||!Array.isArray(value.items)||value.items.length>1||value.next_after!==null||value.viewer_user_id!==String(state().user.id)||typeof value.can_write!=='boolean')throw Error('Invalid private dispute state');
      const row=value.items[0];if(row&&(!id(row.id)||row.individual_id!==individual||row.status!=='open'))throw Error('Invalid private dispute target');
      caseId=row?.id||null;
    }catch{if(current())failed=true;}finally{if(current()){pending=false;render();}}
  }
  globalThis.addEventListener('pagehide',clear);
  return {sync,render,clear,blocked};
}
