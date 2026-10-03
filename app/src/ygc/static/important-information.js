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
    target.hidden=!issue;target.innerHTML=issue?'<div class="unanswered-request"><p>'+safe(issue)+("</p><div><button onclick=\"openAccountSignIn()\">"+(globalThis.YGCI18n?.html("ui.sign_in_bfd402b2",{},"Sign in")??"Sign in")+"</button></div></div>"):'';
    if(issue){mine.hidden=true;mine.innerHTML='';for(const id of ['ownershipDisputeNotice','unansweredRequests'])document.getElementById(id).hidden=true}
    sync();
  }
  window.addEventListener('ygc-account-access',accessNotice);
  accessNotice();
  function requestRow(row){
    const draft=row.status==='draft';
    const text=(key,params,fallback)=>globalThis.YGCI18n?.t(key,params,fallback)??fallback;
    const due=row.expires_at?new Date(row.expires_at*1000).toLocaleString(globalThis.YGCI18n?.locale||'en-US'):'';
    const urgency=row.expires_at*1000-Date.now()<3600000?text('requests.photos_due_soon',{},' (less than 1 hour remaining)'):'';
    const deadline=draft&&row.expires_at?text('requests.photos_due',{date:due,urgency},' — Photos due '+due+urgency):'';
    const kind=row.request_kind==='listing'?text('ui.listing_fc7f1aa2',{},'Listing'):text('ui.acquire_910e23d5',{},'Acquire');
    const product=row.product_name||text('guitar.reference',{id:row.original_individual_id},'Guitar #'+row.original_individual_id);
    const status=draft?text('ui.photos_required_b9b1cf55',{},'Photos required'):acquireStatusLabel(row);
    const title=text('requests.summary',{kind,product,status,deadline},kind+' · '+product+' — '+status+deadline);
    return '<div class="unanswered-request"><p>'+safe(title)+'</p><div><button data-revision="'+safe(row.revision)+("\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button></div></div>");
  }
  async function refresh(){
    const current=++generation,userId=actor();accessNotice();
    if(!userId){mine.hidden=true;mine.innerHTML='';sync()}
    // Public service information remains available during maintenance and to Guests.
    const tasks=[jfetch('/api/service-notice').then(data=>{
      if(current!==generation)return;
      service.hidden=data.mode==='normal';
      root.classList.toggle('maintenance-only',data.mode!=='normal');
      const title=data.mode==='read_only'?(globalThis.YGCI18n?.t("ui.maintenance_read_only_b7aaa925",{},"Maintenance — Read only")??"Maintenance — Read only"):(globalThis.YGCI18n?.t("ui.maintenance_offline_88473f7e",{},"Maintenance — Offline")??"Maintenance — Offline");
      service.innerHTML='<div class="unanswered-request"><p>'+safe(title)+'\n'+safe(data.message||(data.mode==='read_only'?(globalThis.YGCI18n?.t("ui.you_can_browse_but_changes_and_submissions_are_temporarily_7e71ffc4",{},"You can browse, but changes and submissions are temporarily unavailable.")??"You can browse, but changes and submissions are temporarily unavailable."):(globalThis.YGCI18n?.t("ui.the_service_is_undergoing_maintenance_please_try_again_lat_4969a82a",{},"The service is undergoing maintenance. Please try again later.")??"The service is undergoing maintenance. Please try again later.")))+'</p></div>';sync();
    }).catch(()=>{/* Keep last known service state on a connection failure. */})];
    if(userId&&!sessionStorage.getItem('ygc_account_access_issue'))tasks.push(jfetch('/api/important-information?viewer_id='+Number(userId)).then(data=>{
      if(current!==generation||actor()!==userId||sessionStorage.getItem('ygc_account_access_issue'))return;
      const applications=data.applications.map(requestRow).join('');
      const transfers=data.outgoing_transfers.map(row=>("<div class=\"unanswered-request\"><p>"+(globalThis.YGCI18n?.html("ui.transfer_9e0d719a",{},"Transfer ·")??"Transfer ·")+" ")+safe([row.manufacturer,row.model,row.serial_number].filter(Boolean).join(' ')||(globalThis.YGCI18n?.t("ui.guitar_ef54df12",{},"Guitar #")??"Guitar #")+row.individual_id)+' — Awaiting acceptance by '+safe(row.recipient_name)+'</p><div><button data-transfer="'+Number(row.claim_id)+("\">"+(globalThis.YGCI18n?.html("ui.view_transfer_fac0c039",{},"View transfer")??"View transfer")+"</button></div></div>")).join('');
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
