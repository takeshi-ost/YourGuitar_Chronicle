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
  modal.innerHTML=("<div class=\"modal dispute-modal\" role=\"dialog\" aria-modal=\"true\" aria-labelledby=\"disputeTitle\"><h2 id=\"disputeTitle\">"+(globalThis.YGCI18n?.html("ui.ownership_disputes_ff09a7cb",{},"Ownership Disputes")??"Ownership Disputes")+"</h2><div id=\"disputeBody\"></div><p id=\"disputeError\" role=\"status\"></p><div class=\"modal-actions\"><button data-ui-action=\"close\" onclick=\"YGCOverlays.close('disputeModal')\">"+(globalThis.YGCI18n?.html("action.close",{},"Close")??"Close")+"</button></div></div>");
  document.body.append(modal);
  modal.addEventListener('click',event=>{
    if(event.target===modal)YGCOverlays.close(modal);
  });
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
        const actionable=options.filter(r=>r.status==='unverified'&&Date.now()-Date.parse(r.requested_at)>=r.wait_days*86400000);
        target.parentElement.hidden=!visible.length&&!actionable.length;
        target.innerHTML=visible.map(r=>("<div class=\"unanswered-request\"><p>"+(globalThis.YGCI18n?.html("ui.dispute_a62b76ac",{},"Dispute ·")??"Dispute ·")+" ")+escape([r.manufacturer,r.model,r.serial_number].filter(Boolean).join(' '))+' — Under dispute</p><div><button onclick="YGCDisputes.open('+r.id+(")\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button></div></div>")).join('')+
          actionable.map(r=>("<div class=\"unanswered-request\"><p>"+(globalThis.YGCI18n?.html("ui.acquire_592de056",{},"Acquire #")??"Acquire #"))+r.claim_id+' · Guitar #'+r.individual_id+' — '+(r.status==='negative'?(globalThis.YGCI18n?.t("ui.declined_dce083a2",{},"Declined")??"Declined"):(globalThis.YGCI18n?.t("ui.awaiting_owner_response_534b9a09",{},"Awaiting owner response")??"Awaiting owner response"))+("</p><div><button onclick=\"YGCDisputes.list()\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button></div></div>")).join('');
        return;
      }
      target.parentElement.hidden=false;
      target.innerHTML=visible.length?visible.map(r=>'<tr class="dispute-row"><td>#'+Number(r.id)+'</td><td>'+(r.applicants||[]).map(a=>ownershipDetailLink('user',a.applicant_id,a.display_name+' (#'+a.applicant_id+')')).join(', ')+'</td><td>'+ownershipDetailLink('guitar',r.individual_id,[r.manufacturer,r.model].filter(Boolean).join(' ')+' (#'+Number(r.individual_id)+')')+'<br>'+escape(r.serial_number)+'</td><td>'+(r.status==='open'?(globalThis.YGCI18n?.t("ui.under_dispute_005fd7a2",{},"Under dispute")??"Under dispute"):(globalThis.YGCI18n?.t("ui.resolved_5be3c2c8",{},"Resolved")??"Resolved"))+'</td><td>'+ownershipDetailLink('user',r.owner_id,r.owner_name)+'</td><td>'+escape(r.created_at)+'<br>'+escape(r.updated_at)+'</td><td><button class="secondary" onclick="YGCDisputes.open('+Number(r.id)+(")\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button></td></tr>")).join(''):("<tr><td colspan=\"7\">"+(globalThis.YGCI18n?.html("ui.no_disputes_43fb46e8",{},"No disputes.")??"No disputes.")+"</td></tr>");
    }catch(e){if(admin){target.textContent=e.message}else{target.parentElement.hidden=false;target.textContent=(globalThis.YGCI18n?.t("ui.unable_to_load_disputes_please_refresh_9690e09b",{},"Unable to load disputes. Please refresh.")??"Unable to load disputes. Please refresh.")}}
  }
  async function list(){
    if(!admin&&!user()){requireAccount();return}
    const actor=user();
    try{
      const [rows,options]=await Promise.all([jfetch(root+query()),admin?Promise.resolve([]):jfetch(root+'/options'+query())]);
      if(!admin&&actor!==user())return;
      current=null;
      show((globalThis.YGCI18n?.t("ui.ownership_disputes_ff09a7cb",{},"Ownership Disputes")??"Ownership Disputes"),rows.map(r=>'<p><button onclick="YGCDisputes.open('+r.id+')">Dispute #'+r.id+' — '+escape(r.status)+'</button> · Guitar #'+r.individual_id+'</p>').join('')+
        options.map(r=>("<div class=\"dispute-row\"><strong>"+(globalThis.YGCI18n?.html("ui.acquire_592de056",{},"Acquire #")??"Acquire #"))+r.claim_id+' · Guitar #'+r.individual_id+'</strong><p>'+escape(r.decline_reason||(globalThis.YGCI18n?.t("ui.awaiting_owner_response_escalation_is_available_after_47c665cb",{},"Awaiting owner response. Escalation is available after")??"Awaiting owner response. Escalation is available after")+" "+r.wait_days+" "+(globalThis.YGCI18n?.t("ui.days_from_claim_creation_5f31468b",{},"days from Claim creation.")??"days from Claim creation."))+'</p><button onclick="YGCDisputes.start('+r.claim_id+')">'+(r.status==='negative'?(globalThis.YGCI18n?.t("ui.appeal_b8b66bda",{},"Appeal")??"Appeal"):(globalThis.YGCI18n?.t("ui.request_administrator_review_763920d1",{},"Request administrator review")??"Request administrator review"))+'</button> '+(r.decline_reason?'<button onclick="YGCDisputes.acknowledge('+r.claim_id+(")\">"+(globalThis.YGCI18n?.html("ui.accept_decision_95a66969",{},"Accept decision")??"Accept decision")+"</button>"):'')+'</div>').join('')||(globalThis.YGCI18n?.t("ui.no_disputes_or_eligible_acquires_d63cf7b8",{},"No disputes or eligible Acquires.")??"No disputes or eligible Acquires."));
    }catch(e){alert(e.message)}
  }
  function form(claim,caseId){
    if(Array.isArray(claim)&&claim.length===1)claim=claim[0].claim_id;
    return '<form onsubmit="event.preventDefault();YGCDisputes.submit(this)"><input type="hidden" name="case_id" value="'+(caseId||'')+'"><input type="hidden" name="round_number" value="'+(current?.round?.number||1)+'">'+
      (Array.isArray(claim)?("<label>"+(globalThis.YGCI18n?.html("ui.request_59f03d64",{},"Request")??"Request")+"<select name=\"claim_id\">")+claim.map(c=>'<option value="'+c.claim_id+'">Acquire #'+c.claim_id+' · '+escape(c.applicant_name)+'</option>').join('')+'</select></label>':'<input type="hidden" name="claim_id" value="'+claim+'">')+
      ("<label>"+(globalThis.YGCI18n?.html("ui.private_explanation_6cd21050",{},"Please explain the basis of ownership (kept confidential).")??"Please explain the basis of ownership (kept confidential).")+"<textarea name=\"explanation\" maxlength=\"8000\" required></textarea></label><label>"+(globalThis.YGCI18n?.html("ui.summary_for_the_other_party_administrator_review_required_f8ddb0c0",{},"Claim or message for the other party (administrator review required)")??"Claim or message for the other party (administrator review required)")+"<textarea name=\"summary\" maxlength=\"4000\" required></textarea></label><label>"+(globalThis.YGCI18n?.html("ui.evidence_still_image_or_pdf_up_to_12_mb_8eae359c",{},"Evidence: still image or PDF, up to 12 MB")??"Evidence: still image or PDF, up to 12 MB")+"<input name=\"attachment\" type=\"file\" accept=\"image/jpeg,image/png,image/webp,image/gif,application/pdf\" ")+(!caseId?'required':'')+("></label><p>"+(globalThis.YGCI18n?.html("ui.originals_are_visible_only_to_you_and_administrators_you_c_9fe3823e",{},"Originals are visible only to you and administrators. You can submit once per round. Further submissions require an administrator’s additional evidence request.")??"Originals are visible only to you and administrators. You can submit once per round. Further submissions require an administrator’s additional evidence request.")+"</p><button data-ui-action=\"primary\">"+(globalThis.YGCI18n?.html("ui.submit_evidence_91e287e5",{},"Submit evidence")??"Submit evidence")+"</button></form>");
  }
  function start(claim){current=null;show((globalThis.YGCI18n?.t("ui.appeal_acquire_727dc692",{},"Appeal Acquire #")??"Appeal Acquire #")+claim,form(claim,null))}
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
    const date=value=>value?escape(new Date(value).toLocaleString(globalThis.YGCI18n?.locale||'en-US')):'—';
    const state=c.status==='resolved'?(globalThis.YGCI18n?.t("ui.resolved_5be3c2c8",{},"Resolved")??"Resolved"):rnd?.phase==='reviewing'?(globalThis.YGCI18n?.t("ui.under_review_9e8a3b64",{},"Under review")??"Under review"):(globalThis.YGCI18n?.t("ui.awaiting_evidence_a139f6b6",{},"Awaiting evidence")??"Awaiting evidence");
    const evidenceHtml=e=>'<div class="dispute-evidence">'+
      (e.summary!==undefined?("<p class=\"dispute-text\">"+(globalThis.YGCI18n?.html("ui.submitted_summary_2bbf5913",{},"Submitted summary:")??"Submitted summary:")+" ")+escape(e.summary)+'</p>':'')+
      (e.published_summary?("<p class=\"dispute-text\">"+(globalThis.YGCI18n?.html("ui.shared_summary_af057026",{},"Shared summary:")??"Shared summary:")+" ")+escape(e.published_summary)+'</p>':'')+
      (e.explanation!==undefined?("<details><summary>"+(globalThis.YGCI18n?.html("ui.private_evidence_details_9b97f142",{},"Private evidence details")??"Private evidence details")+"</summary><p class=\"dispute-text\">")+escape(e.explanation)+'</p>'+(e.has_attachment?'<button onclick="YGCDisputes.download('+e.id+(")\">"+(globalThis.YGCI18n?.html("ui.download_private_attachment_34686e56",{},"Download private attachment")??"Download private attachment")+"</button>"):'')+'</details>':'')+
      (admin&&!e.published_at&&c.status==='open'?("<details><summary>"+(globalThis.YGCI18n?.html("ui.review_summary_for_sharing_9fc3958b",{},"Review summary for sharing")??"Review summary for sharing")+"</summary><label>"+(globalThis.YGCI18n?.html("ui.summary_to_share_8d98960a",{},"Summary to share")??"Summary to share")+"<textarea id=\"disputeSummary")+e.id+'" maxlength="4000">'+escape(e.summary)+'</textarea></label><button onclick="YGCDisputes.publish('+e.id+(")\">"+(globalThis.YGCI18n?.html("ui.publish_reviewed_summary_c058c305",{},"Publish reviewed summary")??"Publish reviewed summary")+"</button></details>"):'')+'</div>';
    const rounds=(c.rounds||[rnd]).filter(Boolean).map((r,index,all)=>{
      const next=all[index+1],latest=!next;
      const events=c.events.filter(e=>e.round_number===r.number);
      const entries=events.filter(e=>!['evidence_submitted','resolved','opened','request_evidence'].includes(e.kind)).map(e=>({at:e.created_at,order:e.id,html:escape(({opened:(globalThis.YGCI18n?.t("ui.dispute_opened_a33d4b87",{},"Dispute opened")??"Dispute opened"),under_review:(globalThis.YGCI18n?.t("ui.under_review_9e8a3b64",{},"Under review")??"Under review"),request_evidence:(globalThis.YGCI18n?.t("ui.additional_evidence_requested_7debf8f0",{},"Additional evidence requested")??"Additional evidence requested"),reopened:(globalThis.YGCI18n?.t("ui.reopened_for_reconsideration_60c0db26",{},"Reopened for reconsideration")??"Reopened for reconsideration"),summary_published:(globalThis.YGCI18n?.t("ui.reviewed_summary_shared_663e6354",{},"Reviewed summary shared")??"Reviewed summary shared")})[e.kind]||e.kind)+' — '+escape(e.note)}));
      for(const party of r.parties){
        if(!party.submitted_at)continue;
        const evidence=c.evidence.filter(e=>e.round_number===r.number&&e.claim_id===party.claim_id&&e.author_id===party.user_id);
        entries.push({at:party.submitted_at,order:0,html:'<strong>'+escape(party.user_id===c.owner_id?c.owner_name:c.claims.find(p=>p.claim_id===party.claim_id)?.applicant_name)+' — Submitted</strong>'+evidence.map(evidenceHtml).join('')});
      }
      entries.sort((a,b)=>String(a.at).localeCompare(String(b.at))||a.order-b.order);
      const decision=events.findLast(e=>e.kind==='resolved');
      const outcome=decision?(globalThis.YGCI18n?.t("ui.decision_recorded_4f8b085a",{},"Decision recorded —")??"Decision recorded —")+" "+escape(decision.note):next?(globalThis.YGCI18n?.t("ui.additional_evidence_requested_212a1100",{},"Additional evidence requested —")??"Additional evidence requested —")+" "+escape(next.request_reason):c.status==='resolved'?(globalThis.YGCI18n?.t("ui.resolved_d0b47522",{},"Resolved —")??"Resolved —")+" "+escape(c.reason):r.phase==='reviewing'?(globalThis.YGCI18n?.t("ui.pending_decision_d9493792",{},"Pending decision")??"Pending decision"):(globalThis.YGCI18n?.t("ui.awaiting_evidence_a139f6b6",{},"Awaiting evidence")??"Awaiting evidence");
      return ("<section class=\"dispute-round\"><h3>"+(globalThis.YGCI18n?.html("ui.round_cd9558ac",{},"Round")??"Round")+" ")+r.number+'</h3><ol class="dispute-timeline">'+entries.map(e=>'<li><time>'+date(e.at)+'</time><div>'+e.html+'</div></li>').join('')+'</ol>'+
        (latest&&c.status==='open'&&r.phase==='collecting'?r.parties.filter(p=>!p.submitted_at).map(p=>'<p>'+escape(p.user_id===c.owner_id?c.owner_name:c.claims.find(claim=>claim.claim_id===p.claim_id)?.applicant_name)+' — Awaiting submission</p>').join(''):'')+
        (outcome==='Awaiting evidence'?'':("<p class=\"dispute-result\"><strong>"+(globalThis.YGCI18n?.html("ui.review_result_a2657ecb",{},"Review result:")??"Review result:")+"</strong> ")+outcome+'</p>')+'</section>'+
        (latest&&!admin&&canSubmit?("<section class=\"dispute-submission\"><h3>"+(globalThis.YGCI18n?.html("ui.submit_evidence_round_35115d0b",{},"Submit evidence — Round")??"Submit evidence — Round")+" ")+r.number+'</h3>'+form(c.claims.filter(p=>pending.has(p.claim_id)),c.id)+'</section>':'');
    }).join('');
    show((globalThis.YGCI18n?.t("ui.dispute_details_6d0a4d71",{},"Dispute Details #")??"Dispute Details #")+c.id,'<div class="dispute-overview">'+c.claims.map(r=>("<div><strong>"+(globalThis.YGCI18n?.html("ui.acquire_592de056",{},"Acquire #")??"Acquire #"))+r.claim_id+("</strong><dl><dt>"+(globalThis.YGCI18n?.html("ui.applicant_0a1ce115",{},"Applicant")??"Applicant")+"</dt><dd>")+escape(r.applicant_name)+("</dd><dt>"+(globalThis.YGCI18n?.html("ui.current_owner_0abf1fda",{},"Current owner")??"Current owner")+"</dt><dd>")+escape(c.current_owner_name||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))+("</dd><dt>"+(globalThis.YGCI18n?.html("ui.application_date_4b3f063e",{},"Application date")??"Application date")+"</dt><dd>")+date(r.requested_at)+("</dd><dt>"+(globalThis.YGCI18n?.html("ui.dispute_status_4f785f0f",{},"Dispute status")??"Dispute status")+"</dt><dd>")+state+'</dd></dl>'+(r.decline_reason?("<p>"+(globalThis.YGCI18n?.html("ui.decline_reason_066b41f8",{},"Decline reason:")??"Decline reason:")+" ")+escape(r.decline_reason)+'</p>':'')+'</div>').join('')+'</div>'+rounds+
      (admin?("<label>"+(globalThis.YGCI18n?.html("ui.decision_request_reason_88177a68",{},"Decision / request reason")??"Decision / request reason")+"<textarea id=\"disputeReason\" maxlength=\"4000\" required></textarea></label>")+(c.status==='open'?("<label>"+(globalThis.YGCI18n?.html("ui.applicant_to_support_abeb08b0",{},"Applicant to support")??"Applicant to support")+"<select id=\"disputeWinner\">")+c.claims.map(r=>'<option value="'+r.claim_id+'">'+escape(r.applicant_name)+' · Acquire #'+r.claim_id+'</option>').join('')+'</select></label><button '+reviewDisabled+(" onclick=\"YGCDisputes.decide('request_evidence')\">"+(globalThis.YGCI18n?.html("ui.request_additional_evidence_b9e54184",{},"Request additional evidence")??"Request additional evidence")+"</button> <button onclick=\"YGCDisputes.decide('owner')\">"+(globalThis.YGCI18n?.html("ui.support_original_owner_314886e7",{},"Support original owner")??"Support original owner")+"</button> <button data-ui-action=\"primary\" onclick=\"YGCDisputes.decide('applicant')\">"+(globalThis.YGCI18n?.html("ui.support_applicant_15d2376e",{},"Support applicant")??"Support applicant")+"</button>"):("<button onclick=\"YGCDisputes.decide('reopen')\">"+(globalThis.YGCI18n?.html("ui.reopen_for_reconsideration_920784c5",{},"Reopen for reconsideration")??"Reopen for reconsideration")+"</button>")):''));
  }
  async function mutation(fn){if(busy)return;busy=true;el('disputeError').textContent='';try{await fn();await refresh();if(!admin&&typeof refreshClaimViews==='function'&&selectedIndividualId)await refreshClaimViews(selectedIndividualId)}catch(e){err(e)}finally{busy=false}}
  async function submit(formEl){
    const data=new FormData(formEl);if(!data.get('case_id'))data.delete('case_id');
    if(!confirm((globalThis.YGCI18n?.t("ui.submit_this_evidence_it_will_be_retained_as_part_of_the_di_7b29f85c",{},"Submit this evidence? It will be retained as part of the dispute history.")??"Submit this evidence? It will be retained as part of the dispute history.")))return;
    await mutation(async()=>{current=await jfetch('/api/ownership-disputes/evidence/submit'+query(),{method:'POST',body:data});render()});
  }
  async function acknowledge(id){if(!confirm((globalThis.YGCI18n?.t("ui.accept_the_owner_s_decline_and_close_your_appeal_entry_473d2d90",{},"Accept the owner’s decline and close your appeal entry?")??"Accept the owner’s decline and close your appeal entry?")))return;await mutation(async()=>{await jfetch(root+'/acknowledge/'+id+query(),{method:'POST'});await list()})}
  async function publish(id){const summary=el('disputeSummary'+id).value.trim();if(!summary){err((globalThis.YGCI18n?.t("ui.enter_a_summary_62e63762",{},"Enter a summary")??"Enter a summary"));return}if(!confirm((globalThis.YGCI18n?.t("ui.share_this_summary_with_the_other_party_it_cannot_be_overw_2cff3c0d",{},"Share this summary with the other party? It cannot be overwritten.")??"Share this summary with the other party? It cannot be overwritten.")))return;await mutation(async()=>{current=await jfetch('/api/admin/ownership-dispute-evidence/'+id+'/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:current.version,summary})});render()})}
  async function decide(action){const reason=el('disputeReason').value.trim();if(!reason){err('A reason is required');return}if(!confirm((globalThis.YGCI18n?.t("ui.record_this_administrator_action_a514530d",{},"Record this administrator action:")??"Record this administrator action:")+" "+action+(globalThis.YGCI18n?.t("ui.ownership_may_change_f7eb0348",{},"? Ownership may change.")??"? Ownership may change.")))return;await mutation(async()=>{current=await jfetch(root+'/'+current.id+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:current.version,action,reason,winner_claim:el('disputeWinner')?Number(el('disputeWinner').value):null})});render()})}
  async function download(id){
    try{const headers={};if(admin)headers['X-YGC-Console-Admin']=CONSOLE_ADMIN_TOKEN;
      const r=await fetch((admin?'/api/admin':'/api')+'/ownership-dispute-evidence/'+id+query(),{headers});if(!r.ok)throw Error((globalThis.YGCI18n?.t("ui.evidence_access_denied_1da6cb22",{},"Evidence access denied")??"Evidence access denied"));
      const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=r.headers.get('content-type')?.includes('pdf')?'evidence.pdf':'evidence.jpg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){err(e)}
  }
  refresh();setInterval(()=>{if(!document.hidden&&!busy)refresh()},30000);
  return {refresh,list,open,start,submit,acknowledge,publish,decide,download};
})();
