/* Shared private dispute UI. Business authorization remains on the server. */
const YGCDisputes=(()=>{
  const admin=typeof CONSOLE_ADMIN_TOKEN!=='undefined';
  const root=admin?'/api/admin/ownership-disputes':'/api/ownership-disputes';
  let current=null,busy=false,seq=0;
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const user=()=>typeof activeUser!=='undefined'?activeUser?.user?.id:null;
  const query=()=>admin?'':'?viewer_id='+Number(user());
  const el=id=>document.getElementById(id);
  const modal=document.createElement('div');modal.id='disputeModal';modal.className='modal-backdrop';
  modal.innerHTML='<div class="modal dispute-modal" role="dialog" aria-modal="true" aria-labelledby="disputeTitle"><h2 id="disputeTitle">Ownership Disputes</h2><div id="disputeBody"></div><p id="disputeError" role="status"></p><div class="modal-actions"><button data-ui-action="close" onclick="YGCOverlays.close(\'disputeModal\')">Close</button></div></div>';
  document.body.append(modal);
  const err=e=>{el('disputeError').textContent=e.message||String(e)};
  function show(title,html){el('disputeTitle').textContent=title;el('disputeBody').innerHTML=html;el('disputeError').textContent='';YGCOverlays.open(modal)}
  async function refresh(){
    const target=el('disputeList');if(!target)return;
    const generation=++seq,actor=user();
    if(!admin&&!actor){target.innerHTML='';target.parentElement.hidden=true;return}
    try{
      const [rows,options]=await Promise.all([jfetch(root+query()),admin?Promise.resolve([]):jfetch(root+'/options'+query())]);
      if(generation!==seq||(!admin&&actor!==user()))return;
      const status=admin?(el('disputeStatusFilter')?.value??'open'):'open';
      const visible=rows.filter(r=>!status||r.status===status);
      if(!admin){
        const actionable=options.filter(r=>r.status==='negative'||Date.now()-Date.parse(r.requested_at)>=r.wait_days*86400000);
        target.parentElement.hidden=!visible.length&&!actionable.length;
        target.innerHTML=visible.map(r=>'<div class="unanswered-request"><p>'+escape([r.manufacturer,r.model,r.serial_number].filter(Boolean).join(' '))+' — Under dispute</p><div><button onclick="YGCDisputes.open('+r.id+')">Dispute Details</button></div></div>').join('')+
          actionable.map(r=>'<div class="unanswered-request"><p>Acquire #'+r.claim_id+' · Guitar #'+r.individual_id+' — '+(r.status==='negative'?'Declined':'Awaiting owner response')+'</p><div><button onclick="YGCDisputes.list()">Review owner response / Appeal</button></div></div>').join('');
        return;
      }
      target.parentElement.hidden=false;
      target.innerHTML=visible.length?visible.map(r=>'<div class="dispute-row"><strong>'+escape([r.manufacturer,r.model,r.serial_number].filter(Boolean).join(' '))+'</strong> — '+(r.status==='open'?'Under dispute':'Resolved')+' · Owner: '+escape(r.owner_name)+' · Applicant: '+escape((r.applicants||[]).map(a=>a.display_name).join(', '))+' · Started: '+escape(r.created_at)+' · Updated: '+escape(r.updated_at)+' <button onclick="YGCDisputes.open('+r.id+')">View dispute #'+r.id+'</button></div>').join(''):'No disputes.';
    }catch(e){if(admin){target.textContent=e.message}else{target.parentElement.hidden=false;target.textContent='Unable to load disputes. Please refresh.'}}
  }
  async function list(){
    if(!admin&&!user()){requireAccount();return}
    const actor=user();
    try{
      const [rows,options]=await Promise.all([jfetch(root+query()),admin?Promise.resolve([]):jfetch(root+'/options'+query())]);
      if(!admin&&actor!==user())return;
      current=null;
      show('Ownership Disputes',rows.map(r=>'<p><button onclick="YGCDisputes.open('+r.id+')">Dispute #'+r.id+' — '+escape(r.status)+'</button> · Guitar #'+r.individual_id+'</p>').join('')+
        options.map(r=>'<div class="dispute-row"><strong>Acquire #'+r.claim_id+' · Guitar #'+r.individual_id+'</strong><p>'+escape(r.decline_reason||'Awaiting owner response. Escalation is available after '+r.wait_days+' days from Claim creation.')+'</p><button onclick="YGCDisputes.start('+r.claim_id+')">'+(r.status==='negative'?'Appeal':'Request administrator review')+'</button> '+(r.decline_reason?'<button onclick="YGCDisputes.acknowledge('+r.claim_id+')">Accept decision</button>':'')+'</div>').join('')||'No disputes or eligible Acquires.');
    }catch(e){alert(e.message)}
  }
  function form(claim,caseId){
    if(Array.isArray(claim)&&claim.length===1)claim=claim[0].claim_id;
    return '<form onsubmit="event.preventDefault();YGCDisputes.submit(this)"><input type="hidden" name="case_id" value="'+(caseId||'')+'"><input type="hidden" name="round_number" value="'+(current?.round?.number||1)+'">'+
      (Array.isArray(claim)?'<label>Request<select name="claim_id">'+claim.map(c=>'<option value="'+c.claim_id+'">Acquire #'+c.claim_id+' · '+escape(c.applicant_name)+'</option>').join('')+'</select></label>':'<input type="hidden" name="claim_id" value="'+claim+'">')+
      '<label>Private explanation<textarea name="explanation" maxlength="8000" required></textarea></label><label>Summary for the other party (administrator review required)<textarea name="summary" maxlength="4000" required></textarea></label><label>Evidence: still image or PDF, up to 12 MB<input name="attachment" type="file" accept="image/jpeg,image/png,image/webp,image/gif,application/pdf" '+(!caseId?'required':'')+'></label><p>Originals are visible only to you and administrators. You can submit once per round. Further submissions require an administrator’s additional evidence request.</p><button data-ui-action="primary">Submit evidence</button></form>';
  }
  function start(claim){current=null;show('Appeal Acquire #'+claim,form(claim,null))}
  async function open(id){
    const actor=user();
    try{const result=await jfetch(root+'/'+id+query());if(!admin&&actor!==user())return;current=result;render()}catch(e){alert(e.message)}
  }
  function render(){
    const c=current;
    const rnd=c.round;
    const pending=new Set((rnd?.parties||[]).filter(p=>p.user_id===Number(user())&&!p.submitted_at).map(p=>p.claim_id));
    const canSubmit=c.status==='open'&&rnd?.phase==='collecting'&&pending.size>0;
    const reviewDisabled=rnd?.phase==='reviewing'?'':'disabled';
    const date=value=>value?escape(new Date(value).toLocaleString()):'—';
    const state=c.status==='resolved'?'Resolved':rnd?.phase==='reviewing'?'Under review':'Awaiting evidence';
    const evidenceHtml=e=>'<div class="dispute-evidence">'+
      (e.summary!==undefined?'<p class="dispute-text">Submitted summary: '+escape(e.summary)+'</p>':'')+
      (e.published_summary?'<p class="dispute-text">Shared summary: '+escape(e.published_summary)+'</p>':'')+
      (e.explanation!==undefined?'<details><summary>Private evidence details</summary><p class="dispute-text">'+escape(e.explanation)+'</p>'+(e.has_attachment?'<button onclick="YGCDisputes.download('+e.id+')">Download private attachment</button>':'')+'</details>':'')+
      (admin&&!e.published_at&&c.status==='open'?'<details><summary>Review summary for sharing</summary><label>Summary to share<textarea id="disputeSummary'+e.id+'" maxlength="4000">'+escape(e.summary)+'</textarea></label><button onclick="YGCDisputes.publish('+e.id+')">Publish reviewed summary</button></details>':'')+'</div>';
    const rounds=(c.rounds||[rnd]).filter(Boolean).map((r,index,all)=>{
      const next=all[index+1],latest=!next;
      const events=c.events.filter(e=>e.round_number===r.number);
      const entries=events.filter(e=>!['evidence_submitted','resolved','opened','request_evidence'].includes(e.kind)).map(e=>({at:e.created_at,order:e.id,html:escape(({opened:'Dispute opened',under_review:'Under review',request_evidence:'Additional evidence requested',reopened:'Reopened for reconsideration',summary_published:'Reviewed summary shared'})[e.kind]||e.kind)+' — '+escape(e.note)}));
      for(const party of r.parties){
        if(!party.submitted_at)continue;
        const evidence=c.evidence.filter(e=>e.round_number===r.number&&e.claim_id===party.claim_id&&e.author_id===party.user_id);
        entries.push({at:party.submitted_at,order:0,html:'<strong>'+escape(party.user_id===c.owner_id?c.owner_name:c.claims.find(p=>p.claim_id===party.claim_id)?.applicant_name)+' — Submitted</strong>'+evidence.map(evidenceHtml).join('')});
      }
      entries.sort((a,b)=>String(a.at).localeCompare(String(b.at))||a.order-b.order);
      const decision=events.findLast(e=>e.kind==='resolved');
      const outcome=decision?'Decision recorded — '+escape(decision.note):next?'Additional evidence requested — '+escape(next.request_reason):c.status==='resolved'?'Resolved — '+escape(c.reason):r.phase==='reviewing'?'Pending decision':'Awaiting evidence';
      return '<section class="dispute-round"><h3>Round '+r.number+'</h3><ol class="dispute-timeline">'+entries.map(e=>'<li><time>'+date(e.at)+'</time><div>'+e.html+'</div></li>').join('')+'</ol>'+
        (latest&&c.status==='open'&&r.phase==='collecting'?r.parties.filter(p=>!p.submitted_at).map(p=>'<p>'+escape(p.user_id===c.owner_id?c.owner_name:c.claims.find(claim=>claim.claim_id===p.claim_id)?.applicant_name)+' — Awaiting submission</p>').join(''):'')+
        (outcome==='Awaiting evidence'?'':'<p class="dispute-result"><strong>Review result:</strong> '+outcome+'</p>')+'</section>'+
        (latest&&!admin&&canSubmit?'<section class="dispute-submission"><h3>Submit evidence — Round '+r.number+'</h3>'+form(c.claims.filter(p=>pending.has(p.claim_id)),c.id)+'</section>':'');
    }).join('');
    show('Dispute Details #'+c.id,'<div class="dispute-overview">'+c.claims.map(r=>'<div><strong>Acquire #'+r.claim_id+'</strong><dl><dt>Applicant</dt><dd>'+escape(r.applicant_name)+'</dd><dt>Current owner</dt><dd>'+escape(c.current_owner_name||'Unknown')+'</dd><dt>Application date</dt><dd>'+date(r.requested_at)+'</dd><dt>Dispute status</dt><dd>'+state+'</dd></dl>'+(r.decline_reason?'<p>Decline reason: '+escape(r.decline_reason)+'</p>':'')+'</div>').join('')+'</div>'+rounds+
      (admin?'<label>Decision / request reason<textarea id="disputeReason" maxlength="4000" required></textarea></label>'+(c.status==='open'?'<label>Applicant to support<select id="disputeWinner">'+c.claims.map(r=>'<option value="'+r.claim_id+'">'+escape(r.applicant_name)+' · Acquire #'+r.claim_id+'</option>').join('')+'</select></label><button '+reviewDisabled+' onclick="YGCDisputes.decide(\'request_evidence\')">Request additional evidence</button> <button onclick="YGCDisputes.decide(\'owner\')">Support original owner</button> <button data-ui-action="primary" onclick="YGCDisputes.decide(\'applicant\')">Support applicant</button>':'<button onclick="YGCDisputes.decide(\'reopen\')">Reopen for reconsideration</button>'):''));
  }
  async function mutation(fn){if(busy)return;busy=true;el('disputeError').textContent='';try{await fn();await refresh();if(!admin&&typeof refreshClaimViews==='function'&&selectedIndividualId)await refreshClaimViews(selectedIndividualId)}catch(e){err(e)}finally{busy=false}}
  async function submit(formEl){
    const data=new FormData(formEl);if(!data.get('case_id'))data.delete('case_id');
    if(!confirm('Submit this evidence? It will be retained as part of the dispute history.'))return;
    await mutation(async()=>{current=await jfetch('/api/ownership-disputes/evidence/submit'+query(),{method:'POST',body:data});render()});
  }
  async function acknowledge(id){if(!confirm('Accept the owner’s decline and close your appeal entry?'))return;await mutation(async()=>{await jfetch(root+'/acknowledge/'+id+query(),{method:'POST'});await list()})}
  async function publish(id){const summary=el('disputeSummary'+id).value.trim();if(!summary){err('Enter a summary');return}if(!confirm('Share this summary with the other party? It cannot be overwritten.'))return;await mutation(async()=>{current=await jfetch('/api/admin/ownership-dispute-evidence/'+id+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:current.version,summary})});render()})}
  async function decide(action){const reason=el('disputeReason').value.trim();if(!reason){err('A reason is required');return}if(!confirm('Record this administrator action: '+action+'? Ownership may change.'))return;await mutation(async()=>{current=await jfetch(root+'/'+current.id+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:current.version,action,reason,winner_claim:el('disputeWinner')?Number(el('disputeWinner').value):null})});render()})}
  async function download(id){
    try{const headers={};if(admin)headers['X-YGC-Console-Admin']=CONSOLE_ADMIN_TOKEN;
      const r=await fetch((admin?'/api/admin':'/api')+'/ownership-dispute-evidence/'+id+query(),{headers});if(!r.ok)throw Error('Evidence access denied');
      const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=r.headers.get('content-type')?.includes('pdf')?'evidence.pdf':'evidence.jpg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){err(e)}
  }
  refresh();setInterval(()=>{if(!document.hidden&&!busy)refresh()},30000);
  return {refresh,list,open,start,submit,acknowledge,publish,decide,download};
})();
