// Important information uses the acting account, never the profile being viewed.
const YGCImportantInformation=(()=>{
  const root=document.getElementById('importantInformation');
  const mine=document.getElementById('myOwnershipInformation');
  const service=document.getElementById('serviceNotice');
  let generation=0;
  const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const actor=()=>activeUser?.user?.id;
  function sync(){const otherProfile=PROFILE_USER_ID&&Number(actor())!==Number(PROFILE_USER_ID);const hidden=otherProfile||(root.classList.contains('maintenance-only')?service.hidden:![...root.children].some(node=>node.tagName==='SECTION'&&!node.hidden));if(root.hidden!==hidden)root.hidden=hidden}
  new MutationObserver(sync).observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden']});
  function accessNotice(){
    const target=document.getElementById('accountAccessNotice');
    const issue=sessionStorage.getItem('ygc_account_access_issue');
    target.hidden=!issue;target.innerHTML=issue?'<div class="unanswered-request"><p>'+safe(issue)+'</p><div><button onclick="openAccountSignIn()">Sign in</button></div></div>':'';
    if(issue){mine.hidden=true;mine.innerHTML='';for(const id of ['ownershipDisputeNotice','unansweredRequests'])document.getElementById(id).hidden=true}
    sync();
  }
  window.addEventListener('ygc-account-access',accessNotice);
  accessNotice();
  function requestRow(row){
    const draft=row.status==='draft';
    const deadline=draft&&row.expires_at?' — Photos due '+new Date(row.expires_at*1000).toLocaleString()+(row.expires_at*1000-Date.now()<3600000?' (less than 1 hour remaining)':''):'';
    const title=(row.request_kind==='listing'?'Listing':'Acquire')+' · '+(row.product_name||'Guitar #'+row.original_individual_id)+' — '+(draft?'Photos required':acquireStatusLabel(row))+deadline;
    return '<div class="unanswered-request"><p>'+safe(title)+'</p><div><button data-revision="'+safe(row.revision)+'">Detail</button></div></div>';
  }
  async function refresh(){
    const current=++generation,userId=actor();accessNotice();
    if(!userId){mine.hidden=true;mine.innerHTML='';sync()}
    // Public service information remains available during maintenance and to Guests.
    const tasks=[jfetch('/api/service-notice').then(data=>{
      if(current!==generation)return;
      service.hidden=data.mode==='normal';
      root.classList.toggle('maintenance-only',data.mode!=='normal');
      const title=data.mode==='read_only'?'Maintenance — Read only':'Maintenance — Offline';
      service.innerHTML='<div class="unanswered-request"><p>'+safe(title)+'\n'+safe(data.message||(data.mode==='read_only'?'You can browse, but changes and submissions are temporarily unavailable.':'The service is undergoing maintenance. Please try again later.'))+'</p></div>';sync();
    }).catch(()=>{/* Keep last known service state on a connection failure. */})];
    if(userId&&!sessionStorage.getItem('ygc_account_access_issue'))tasks.push(jfetch('/api/important-information?viewer_id='+Number(userId)).then(data=>{
      if(current!==generation||actor()!==userId||sessionStorage.getItem('ygc_account_access_issue'))return;
      const applications=data.applications.map(requestRow).join('');
      const transfers=data.outgoing_transfers.map(row=>'<div class="unanswered-request"><p>Transfer · '+safe([row.manufacturer,row.model,row.serial_number].filter(Boolean).join(' ')||'Guitar #'+row.individual_id)+' — Awaiting acceptance by '+safe(row.recipient_name)+'</p><div><button data-transfer="'+Number(row.claim_id)+'">View transfer</button></div></div>').join('');
      mine.innerHTML=applications+transfers;mine.hidden=!mine.innerHTML;sync();
    }).catch(()=>{/* Retain ongoing information until a successful refresh. */}));
    await Promise.all(tasks);
  }
  mine.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.revision)await viewAcquireApplication(button.dataset.revision);
    else if(button.dataset.transfer)await openTransferReview(Number(button.dataset.transfer));
    await refresh();
  });
  refresh();
  setInterval(()=>{if(!document.hidden)refresh()},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
  return {refresh};
})();
