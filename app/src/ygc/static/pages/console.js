let individuals=[];
let individualSortKey='id';
let individualSortDirection=-1;
let users=[];
let activeUser=null;
let selectedIndividualId=null;
const TOKEN_KEY='ygc_reverb_api_token';
const ACTIVE_USER_KEY='ygc_active_user_id';
try{
if(sessionStorage.getItem(ACTIVE_USER_KEY)===null){
  const previous=localStorage.getItem(ACTIVE_USER_KEY);
  if(previous)sessionStorage.setItem(ACTIVE_USER_KEY,previous);
}
localStorage.removeItem(ACTIVE_USER_KEY);
}catch(error){}
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
function storedToken(){try{return (localStorage.getItem(TOKEN_KEY)||'').trim()}catch(error){return ''}}
async function jfetch(url,opt={}){const headers=new Headers(opt.headers||{});headers.set('X-YGC-Timezone',Intl.DateTimeFormat().resolvedOptions().timeZone);const token=storedToken();if(token)headers.set('X-Reverb-Token',token);if(CONSOLE_ADMIN_TOKEN)headers.set('X-YGC-Console-Admin',CONSOLE_ADMIN_TOKEN);const r=await fetch(url,{...opt,headers});const d=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(globalThis.YGCI18n?.errorMessage(d,r.statusText)??(Array.isArray(d.detail)?d.detail.map(e=>e.msg).join(' / '):(d.detail||r.statusText)));throw e}return d}
// Remove only credentials saved by the retired inference API UI.
try{for(const provider of ['openai','gemini'])localStorage.removeItem('ygc_authentication_api_key_'+provider)}catch(error){}
let directBusy=false;
let directSelectedRevision=null;
let directSelectedResult=null;
function hideDirectToken(){
  document.getElementById('directToken').type='password';
  const button=document.getElementById('directTokenToggle');
  button.textContent=(globalThis.YGCI18n?.t("ui.message_cba7fb66",{},"接続キーを表示")??"接続キーを表示");
  button.setAttribute('aria-pressed','false');
  document.getElementById('directTokenStatus').textContent='';
}
function toggleDirectToken(){
  const input=document.getElementById('directToken');
  const button=document.getElementById('directTokenToggle');
  const visible=input.type==='password';
  input.type=visible?'text':'password';
  button.textContent=visible?(globalThis.YGCI18n?.t("ui.message_82745ec2",{},"接続キーを隠す")??"接続キーを隠す"):(globalThis.YGCI18n?.t("ui.message_cba7fb66",{},"接続キーを表示")??"接続キーを表示");
  button.setAttribute('aria-pressed',String(visible));
}
async function copyDirectToken(){
  const input=document.getElementById('directToken');
  const status=document.getElementById('directTokenStatus');
  const token=input.value;
  if(!token){status.textContent=(globalThis.YGCI18n?.t("ui.message_fce656dd",{},"先に「① 画像とテスト申請を準備」を実行してください。")??"先に「① 画像とテスト申請を準備」を実行してください。");return}
  try{
    await navigator.clipboard.writeText(token);
    if(input.value===token)status.textContent=(globalThis.YGCI18n?.t("ui.paste_token_1b523d3d",{},"接続キーをコピーしました。設定のPASTE_TOKENを置き換えてください。")??"接続キーをコピーしました。設定のPASTE_TOKENを置き換えてください。");
  }catch(error){
    if(input.value!==token)return;
    if(input.type==='password')toggleDirectToken();
    input.focus();input.select();input.setSelectionRange(0,input.value.length);
    status.textContent=(globalThis.YGCI18n?.t("ui.c_windows_ctrl_c_4bf36a4f",{},"自動コピーを利用できません。キーを表示・選択しました。⌘C（WindowsはCtrl+C）でコピーしてください。")??"自動コピーを利用できません。キーを表示・選択しました。⌘C（WindowsはCtrl+C）でコピーしてください。");
  }
}

async function prepareDirectExperiment(){
  if(directBusy)return;
  directBusy=true;
  const status=document.getElementById('directStatus');
  try{
    const body=new FormData();
    for(const [key,id] of [['application_id','directApplication'],['serial','directSerial'],['challenge','directChallenge']])body.append(key,document.getElementById(id).value.trim());
    for(const [key,id] of [['closeup','directCloseup'],['overview','directOverview'],['reference','directReference']]){
      const file=document.getElementById(id).files[0];
      if(!file||file.size>12*1024*1024)throw new Error('3画像をそれぞれ12MB以下で選択してください。');
      body.append(key,file);
    }
    status.textContent=(globalThis.YGCI18n?.t("ui.message_3a58ca4a",{},"画像を準備しています…")??"画像を準備しています…");
    const result=await jfetch('/api/admin/direct-experiment/prepare',{method:'POST',body});
    showDirectConnection(result);
    directSelectedRevision=result.revision;
    directSelectedResult=null;
    const {token,prompt,python,project,...safe}=result;
    document.getElementById('directResult').value=JSON.stringify(safe,null,2);
    status.textContent=(globalThis.YGCI18n?.t("ui.message_d165050c",{},"申請を追加しました。定期実行で審議されます。")??"申請を追加しました。定期実行で審議されます。");
    await loadDirectQueue();
  }catch(error){status.textContent=(globalThis.YGCI18n?.t("ui.message_78ac9c88",{},"準備できませんでした: ")??"準備できませんでした: ")+error.message}
  finally{directBusy=false}
}
async function inspectDirectExperiment(){
  if(directBusy)return;
  directBusy=true;
  const status=document.getElementById('directStatus');
  try{
    const token=document.getElementById('directToken').value;
    if(!token)throw new Error('先にテスト申請を準備してください。');
    const call=async(method,params={})=>{
      const response=await jfetch('/api/experiments/direct/mcp',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+token},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});
      if(response.error||response.result?.isError)throw new Error('MCP応答を確認できませんでした。');
      return response.result;
    };
    const initialized=await call('initialize',{protocolVersion:'2025-03-26',capabilities:{},clientInfo:{name:'YGC Console diagnostic',version:'1'}});
    const tools=await call('tools/list');
    await call('ping');
    /* Diagnostic is deliberately non-claiming. */
    document.getElementById('directResult').value=JSON.stringify({server:initialized.serverInfo,tools:tools.tools.map(t=>t.name)},null,2);
    status.textContent=(globalThis.YGCI18n?.t("ui.gpt_9177959d",{},"ローカル接続診断成功。申請は確保していません。画像閲覧と審議はGPT側で行います。")??"ローカル接続診断成功。申請は確保していません。画像閲覧と審議はGPT側で行います。");
  }catch(error){status.textContent=(globalThis.YGCI18n?.t("ui.message_5f0c408b",{},"接続診断失敗: ")??"接続診断失敗: ")+error.message}
  finally{directBusy=false}
}
function showDirectConnection(result){
    document.getElementById('directToken').value=result.token;
    hideDirectToken();
    document.getElementById('directPrompt').value=result.prompt;
    const url=location.origin+'/api/experiments/direct/mcp';
    document.getElementById('directConfig').value='[mcp_servers.ygc_experiment]\ncommand = '+JSON.stringify(result.python)+'\nargs = ["-m", "ygc.direct_mcp_bridge", "--url", '+JSON.stringify(url)+']\ncwd = '+JSON.stringify(result.project)+'\n\n[mcp_servers.ygc_experiment.env]\nYGC_EXPERIMENT_TOKEN = "PASTE_TOKEN"';
}
async function restoreDirectConnection(){
  if(directBusy)return;
  directBusy=true;
  try{
    showDirectConnection(await jfetch('/api/admin/direct-experiment/connection',{method:'POST'}));
    document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_821cbc7a",{},"保存済み接続設定を表示しました。申請・結果は変更していません。")??"保存済み接続設定を表示しました。申請・結果は変更していません。");
  }catch(error){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_803d3919",{},"接続設定取得失敗: ")??"接続設定取得失敗: ")+error.message}
  finally{directBusy=false}
}
function directStatusLabel(job){
  return job.status==='completed'?(job.accepted?(globalThis.YGCI18n?.t("ui.true_72be0046",{},"True（採用）")??"True（採用）"):(globalThis.YGCI18n?.t("ui.false_0aa2bb7c",{},"False（不採用）")??"False（不採用）")):
    ({pending:'未処理',processing:'審議中',error:'エラー',cancelled:'取消済み'}[job.status]||job.status);
}
async function loadDirectQueue(){
  const result=await jfetch('/api/admin/direct-experiment');
  const jobs=result.jobs||[];
  document.getElementById('directQueueRows').innerHTML=jobs.map(job=>{
    const revision=esc(job.revision);
    const action=(name,label)=>`<button class="secondary" type="button" data-direct-action="${name}" data-direct-revision="${revision}">${label}</button>`;
    return `<tr><td>${esc(job.application_id)}<br><small>${revision.slice(0,12)}</small></td><td>${esc(directStatusLabel(job))}<br>${esc(job.error||'')}</td><td>${esc(job.created_at)}<br>${esc(job.started_at||'—')}<br>${esc(job.completed_at||'—')}</td><td>${esc(job.attempts)}回 ${action('select',(globalThis.YGCI18n?.t("ui.message_9652e7b5",{},"詳細")??"詳細"))}${job.status==='error'?action('retry',(globalThis.YGCI18n?.t("ui.message_fb6cc190",{},"再試行")??"再試行")):''}${['pending','processing','error'].includes(job.status)?action('cancel',(globalThis.YGCI18n?.t("ui.message_2cd0f3be",{},"取消")??"取消")):''}${['completed','cancelled','error'].includes(job.status)?action('delete',(globalThis.YGCI18n?.t("ui.message_e9653dc3",{},"削除")??"削除")):''}</td></tr>`;
  }).join('')||("<tr><td colspan=\"4\">"+(globalThis.YGCI18n?.t("ui.message_06bd1353",{},"申請はありません。")??"申請はありません。")+"</td></tr>");
  if(directSelectedRevision&&!jobs.some(j=>j.revision===directSelectedRevision))directSelectedRevision=null;
  if(!directSelectedRevision&&jobs.length)directSelectedRevision=jobs[0].revision;
  if(directSelectedRevision){
    const detail=await jfetch('/api/admin/direct-experiment?revision='+encodeURIComponent(directSelectedRevision));
    directSelectedResult=detail;
    document.getElementById('directResult').value=JSON.stringify(detail,null,2);
    document.getElementById('directReport').value=detail.report_text||'';
    document.getElementById('directStatus').textContent=detail.status==='completed'?(globalThis.YGCI18n?.t("ui.message_144f1d1e",{},"暫定採否: ")??"暫定採否: ")+(detail.result.adjudication.accepted?(globalThis.YGCI18n?.t("ui.true_72be0046",{},"True（採用）")??"True（採用）"):(globalThis.YGCI18n?.t("ui.false_0aa2bb7c",{},"False（不採用）")??"False（不採用）"))+(globalThis.YGCI18n?.t("ui.claim_7ada6ec9",{},"。Claim・所有権の変更なし。")??"。Claim・所有権の変更なし。"):directStatusLabel(detail);
  }else{
    directSelectedResult=null;
    document.getElementById('directResult').value='';document.getElementById('directReport').value='';
    document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_06bd1353",{},"申請はありません。")??"申請はありません。");
  }
}
async function refreshDirectExperiment(){
  if(directBusy)return;
  directBusy=true;
  try{await loadDirectQueue()}
  catch(error){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_46704339",{},"一覧取得失敗: ")??"一覧取得失敗: ")+error.message}
  finally{directBusy=false}
}
async function manageDirectJob(revision,action){
  if(directBusy)return;
  if(['delete','cancel'].includes(action)&&!confirm(action==='delete'?(globalThis.YGCI18n?.t("ui.message_2aa36e6b",{},"この実験申請の画像・診断・履歴を削除しますか？")??"この実験申請の画像・診断・履歴を削除しますか？"):(globalThis.YGCI18n?.t("ui.message_2ee6cd01",{},"この実験申請の審議を取り消しますか？")??"この実験申請の審議を取り消しますか？")))return;
  directBusy=true;
  try{
    if(action==='select'){directSelectedRevision=revision;directSelectedResult=null;}
    else await jfetch('/api/admin/direct-experiment/jobs/'+encodeURIComponent(revision)+'/'+action,{method:'POST'});
    await loadDirectQueue();
  }catch(error){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_4054f3e4",{},"操作失敗: ")??"操作失敗: ")+error.message}
  finally{directBusy=false}
}
function downloadDirectResult(format){
  if(!directSelectedResult){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_9952a123",{},"一覧から申請を選択してください。")??"一覧から申請を選択してください。");return}
  if(format==='txt'&&!directSelectedResult.report_text){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_99e755bf",{},"診断文章は未提出です。")??"診断文章は未提出です。");return}
  const value=format==='json'?JSON.stringify(directSelectedResult,null,2):directSelectedResult.report_text;
  const url=URL.createObjectURL(new Blob([value],{type:format==='json'?'application/json':'text/plain;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=directSelectedResult.application_id+'-'+directSelectedResult.revision+'.'+format;
  a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
if(typeof window!=='undefined'){
  document.getElementById('directQueueRows').addEventListener('click',event=>{
    const button=event.target.closest('button[data-direct-action]');
    if(button)manageDirectJob(button.dataset.directRevision,button.dataset.directAction);
  });
  window.setInterval(()=>{if(!document.hidden&&document.getElementById('directAutoRefresh').checked)refreshDirectExperiment()},15000);
}
async function revokeDirectExperiment(){
  if(directBusy)return;
  directBusy=true;
  try{
    await jfetch('/api/admin/direct-experiment',{method:'DELETE'});
    for(const id of ['directToken','directConfig','directPrompt'])document.getElementById(id).value='';
    hideDirectToken();
    document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_bcf4dadb",{},"接続キーを失効しました。申請・画像・診断結果は保存されています。")??"接続キーを失効しました。申請・画像・診断結果は保存されています。");
  }catch(error){document.getElementById('directStatus').textContent=(globalThis.YGCI18n?.t("ui.message_ca8b4a62",{},"終了できませんでした: ")??"終了できませんでした: ")+error.message}
  finally{directBusy=false}
}

let productionAcquires=[],productionSelected=null,productionBusy=false,productionImageUrls=[],productionDetailSequence=0;
const ownershipStates={draft:(globalThis.YGCI18n?.t("ui.awaiting_photos_338fa4ef",{},"Awaiting photos")??"Awaiting photos"),pending:(globalThis.YGCI18n?.t("ui.awaiting_review_4848885e",{},"Awaiting review")??"Awaiting review"),processing:(globalThis.YGCI18n?.t("ui.under_review_9e8a3b64",{},"Under review")??"Under review"),error:(globalThis.YGCI18n?.t("ui.processing_error_a04e7c9b",{},"Processing error")??"Processing error"),accepted:(globalThis.YGCI18n?.t("ui.approved_87b42e40",{},"Approved")??"Approved"),rejected:(globalThis.YGCI18n?.t("ui.rejected_aea4a04a",{},"Rejected")??"Rejected"),cancelled:(globalThis.YGCI18n?.t("ui.cancelled_d353a99e",{},"Cancelled")??"Cancelled"),closed:(globalThis.YGCI18n?.t("ui.closed_c21ead06",{},"Closed")??"Closed"),expired:(globalThis.YGCI18n?.t("ui.submission_expired_261232c8",{},"Submission expired")??"Submission expired")};
const ownershipActions={cancel:(globalThis.YGCI18n?.t("ui.cancel_request_397b8bd8",{},"Cancel Request")??"Cancel Request"),retry:(globalThis.YGCI18n?.t("ui.queue_another_review_d3aaa6b2",{},"Queue Another Review")??"Queue Another Review"),accept:(globalThis.YGCI18n?.t("ui.override_approve_027371b2",{},"Override: Approve")??"Override: Approve"),reject:(globalThis.YGCI18n?.t("ui.override_reject_ba19e0cf",{},"Override: Reject")??"Override: Reject"),positive:(globalThis.YGCI18n?.t("ui.verification_positive_bb042dc2",{},"Verification → Positive")??"Verification → Positive"),negative:(globalThis.YGCI18n?.t("ui.verification_negative_b0411d66",{},"Verification → Negative")??"Verification → Negative"),unverified:(globalThis.YGCI18n?.t("ui.verification_unverified_f482ec3c",{},"Verification → Unverified")??"Verification → Unverified")};
async function loadProductionAcquires(){
  try{
    const data=await jfetch('/api/admin/acquire-applications');
    productionAcquires=data.applications;
    document.getElementById('productionAcquirePrompt').value=data.prompt;
    renderProductionAcquires();
    const time=new Date().toLocaleTimeString(globalThis.YGCI18n?.locale||'en-US'),count=productionAcquires.length;
    document.getElementById('productionAcquireStatus').textContent=globalThis.YGCI18n?.t('requests.updated',{time,count},'Updated: '+time+' / '+count+' requests')??('Updated: '+time+' / '+count+' requests');
    if(productionSelected){const row=productionAcquires.find(r=>r.revision===productionSelected.revision);if(row)renderProductionAcquireDetail(row)}
  }catch(e){document.getElementById('productionAcquireStatus').textContent=(globalThis.YGCI18n?.t("ui.could_not_load_d9ce633a",{},"Could not load:")??"Could not load:")+" "+e.message}
}
function ownershipDetailLink(kind,id,label){
  const number=Number(id);
  if(!Number.isSafeInteger(number)||number<=0)return esc(label);
  const action=kind==='user'?'showUserRecord':'showIndividual';
  return '<button type="button" class="detail-record-link" onclick="'+action+'('+number+')">'+esc(label)+'</button>';
}
function renderProductionAcquires(){
  const query=document.getElementById('productionAcquireSearch').value.toLowerCase().trim();
  const status=document.getElementById('productionAcquireFilter').value;
  const rows=productionAcquires.filter(r=>(!status||(status==='incomplete'?['draft','pending','processing','error'].includes(r.status)||(r.status==='accepted'&&r.verification_status==='unverified'):r.status===status))&&[r.revision,r.applicant_name,r.applicant_id,r.product_name,r.original_individual_id,r.serial].join(' ').toLowerCase().includes(query));
  document.getElementById('productionAcquireRows').innerHTML=rows.map(r=>{
    const guitarId=r.individual_id||r.original_individual_id;
    const ownerId=r.current_owner_user_id;
    const ownerName=typeof users!=='undefined'?users.find(u=>Number(u.id)===Number(ownerId))?.display_name:null;
    return '<tr><td>'+esc(r.revision.slice(0,12))+'</td><td>'+ownershipDetailLink('user',r.applicant_id,r.applicant_name+' (#'+Number(r.applicant_id)+')')+'</td><td>'+ownershipDetailLink('guitar',guitarId,(r.request_kind==='listing'?(globalThis.YGCI18n?.t("ui.listing_43196435",{},"Listing:")??"Listing:")+" ":(globalThis.YGCI18n?.t("ui.acquire_1f4b645c",{},"Acquire:")??"Acquire:")+" ")+r.product_name+(guitarId?' (#'+Number(guitarId)+')':' (Not registered)'))+'<br>'+esc(r.serial)+'</td><td>'+esc(ownershipStates[r.status]||r.status)+'</td><td>'+esc(r.verification_status||'—')+(r.status==='accepted'&&r.verification_status==='unverified'?("<br>"+(globalThis.YGCI18n?.html("ui.awaiting_owner_approval_bb8f3921",{},"Awaiting owner approval")??"Awaiting owner approval")):'')+'</td><td>'+ownershipDetailLink('user',ownerId,ownerId?(ownerName||(globalThis.YGCI18n?.t("ui.user_f0478c1a",{},"User #")??"User #")+Number(ownerId)):(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))+'</td><td>'+esc(r.submitted_at||r.created_at)+'</td><td><button class="secondary" onclick="inspectProductionAcquire(\''+esc(r.revision)+("')\">"+(globalThis.YGCI18n?.html("action.detail",{},"Detail")??"Detail")+"</button></td></tr>");
  }).join('')||("<tr><td colspan=\"8\">"+(globalThis.YGCI18n?.html("ui.no_matching_requests_c0661a58",{},"No matching requests.")??"No matching requests.")+"</td></tr>");
}
function clearProductionImages(){for(const url of productionImageUrls)URL.revokeObjectURL(url);productionImageUrls=[];document.getElementById('productionAcquireImages').innerHTML=''}
function renderProductionAcquireDetail(row){
  productionSelected=row;
  document.getElementById('productionAcquireDetail').value=JSON.stringify(row,null,2);
  const manual=row.admin_review?("<p>"+(globalThis.YGCI18n?.html("ui.administrator_review_018f86a1",{},"Administrator review:")??"Administrator review:")+" ")+(row.admin_review.accepted?(globalThis.YGCI18n?.t("ui.approved_87b42e40",{},"Approved")??"Approved"):(globalThis.YGCI18n?.t("ui.rejected_aea4a04a",{},"Rejected")??"Rejected"))+' — '+esc(row.admin_review.reason)+'</p>':'';
  document.getElementById('productionAcquireSummary').innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.request_59f03d64",{},"Request")??"Request")+" ")+esc(row.revision)+'</h3><p>'+esc(ownershipStates[row.status]||row.status)+' / Verification: '+esc(row.verification_status||(globalThis.YGCI18n?.t("ui.not_created_1d182774",{},"Not created")??"Not created"))+' / Claim: '+esc(row.claim_id||'—')+("</p><p>"+(globalThis.YGCI18n?.html("ui.applicant_5992c27d",{},"Applicant:")??"Applicant:")+" ")+esc(row.applicant_name)+' / Current Owner ID: '+esc(row.current_owner_user_id||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))+'</p>'+manual+(row.error?'<p>'+esc(row.error)+'</p>':'');
  document.getElementById('productionAcquireActions').innerHTML=(row.admin_actions||[]).map(action=>'<button data-ui-action="'+(['accept','positive'].includes(action)?'primary':action==='cancel'?'danger':'neutral')+'" '+(productionBusy?'disabled ':'')+'class="secondary" onclick="manageProductionAcquire(\''+esc(row.revision)+'\',\''+action+'\')">'+ownershipActions[action]+'</button>').join('');
}
async function inspectProductionAcquire(revision){
  productionSelected=null;
  document.getElementById('productionAcquireSummary').textContent=(globalThis.YGCI18n?.t("ui.loading_request_fefd20fe",{},"Loading request…")??"Loading request…");
  document.getElementById('productionAcquireActions').innerHTML='';
  document.getElementById('productionAcquireDetail').value='';
  document.getElementById('productionAcquireReason').value='';
  YGCOverlays.open('productionAcquireDialog',{onClose:()=>{productionDetailSequence++;productionSelected=null;clearProductionImages()}});
  const sequence=++productionDetailSequence;clearProductionImages();document.getElementById('productionAcquireActionStatus').textContent='';
  try{
    const row=await jfetch('/api/acquire-applications/'+encodeURIComponent(revision));
    if(sequence!==productionDetailSequence)return;
    renderProductionAcquireDetail(row);
    for(const role of ['closeup','overview','reference']){
      if(!row.images[role])continue;
      const response=await fetch('/api/acquire-applications/'+encodeURIComponent(revision)+'/images/'+role,{headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},cache:'no-store'});
      if(!response.ok)throw new Error((globalThis.YGCI18n?.t("ui.could_not_load_image_8f724d80",{},"Could not load image:")??"Could not load image:")+" "+role);
      const blob=await response.blob();if(sequence!==productionDetailSequence)return;
      const url=URL.createObjectURL(blob);productionImageUrls.push(url);
      const figure=document.createElement('figure'),caption=document.createElement('figcaption'),img=document.createElement('img');
      caption.textContent={closeup:(globalThis.YGCI18n?.t("ui.close_up_223f4cd0",{},"Close-up")??"Close-up"),overview:(globalThis.YGCI18n?.t("ui.overview_d4b1ea57",{},"Overview")??"Overview"),reference:(globalThis.YGCI18n?.t("ui.reference_71bf9093",{},"Reference")??"Reference")}[role];img.src=url;img.alt=caption.textContent;img.style.cssText='max-width:100%;max-height:320px;object-fit:contain';figure.append(caption,img);document.getElementById('productionAcquireImages').append(figure);
    }
  }catch(e){if(sequence===productionDetailSequence)document.getElementById('productionAcquireActionStatus').textContent=e.message}
}
function productionActionStatus(message){
  document.getElementById('productionAcquireActionStatus').textContent=message;
  document.getElementById('productionAcquireStatus').textContent=message;
}
async function manageProductionAcquire(revision,operation){
  if(productionBusy||!productionSelected||productionSelected.revision!==revision)return;
  const reason=document.getElementById('productionAcquireReason').value.trim();
  if(!reason){productionActionStatus((globalThis.YGCI18n?.t("ui.enter_a_reason_for_this_change_no_changes_have_been_made_9d08f036",{},"Enter a reason for this change. No changes have been made.")??"Enter a reason for this change. No changes have been made."));document.getElementById('productionAcquireReason').focus();return}
  const impact=operation==='accept'?(productionSelected.request_kind==='listing'?(globalThis.YGCI18n?.t("ui.create_or_restore_the_guitar_and_listing_with_the_applican_51e56ae5",{},"Create or restore the guitar and Listing, with the applicant as initial owner.")??"Create or restore the guitar and Listing, with the applicant as initial owner."):(globalThis.YGCI18n?.t("ui.create_or_restore_the_acquire_an_existing_user_owner_must__5906862f",{},"Create or restore the Acquire. An existing user owner must approve it; otherwise it becomes Positive automatically.")??"Create or restore the Acquire. An existing user owner must approve it; otherwise it becomes Positive automatically.")):operation==='reject'?(globalThis.YGCI18n?.t("ui.set_any_existing_claim_to_negative_and_recalculate_ownersh_b0fb11b3",{},"Set any existing Claim to Negative and recalculate ownership.")??"Set any existing Claim to Negative and recalculate ownership."):operation==='retry'?(globalThis.YGCI18n?.t("ui.archive_the_original_result_and_queue_another_gpt_review_16b63a50",{},"Archive the original result and queue another GPT review.")??"Archive the original result and queue another GPT review."):operation==='cancel'?(globalThis.YGCI18n?.t("ui.results_from_an_in_progress_review_will_no_longer_be_accep_2d3b3458",{},"Results from an in-progress review will no longer be accepted.")??"Results from an in-progress review will no longer be accepted."):(globalThis.YGCI18n?.t("ui.override_claim_verification_as_an_administrator_and_recalc_7c34b38b",{},"Override Claim verification as an administrator and recalculate ownership.")??"Override Claim verification as an administrator and recalculate ownership.");
  if(!confirm(ownershipActions[operation]+'\n'+impact+"\n"+(globalThis.YGCI18n?.t("ui.reason_3425d108",{},"Reason:")??"Reason:")+" "+reason))return;
  productionBusy=true;productionActionStatus((globalThis.YGCI18n?.t("ui.applying_change_290b3d07",{},"Applying change…")??"Applying change…"));renderProductionAcquireDetail(productionSelected);
  try{
    const row=await jfetch('/api/admin/acquire-applications/'+encodeURIComponent(revision)+'/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation,reason,expected_version:productionSelected.management_version})});
    renderProductionAcquireDetail(row);document.getElementById('productionAcquireReason').value='';
    productionActionStatus((globalThis.YGCI18n?.t("ui.change_applied_1fe1ccb9",{},"Change applied:")??"Change applied:")+" "+(ownershipStates[row.status]||row.status)+(row.status==='accepted'&&row.verification_status==='unverified'?" "+(globalThis.YGCI18n?.t("ui.awaiting_owner_approval_67fe1f5f",{},"— Awaiting owner approval.")??"— Awaiting owner approval."):' .'));
    await loadProductionAcquires();await loadIndividuals();await loadUsers();if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }catch(e){productionActionStatus((globalThis.YGCI18n?.t("ui.could_not_apply_change_2f62c9dc",{},"Could not apply change:")??"Could not apply change:")+" "+e.message)}
  finally{productionBusy=false;if(productionSelected)renderProductionAcquireDetail(productionSelected)}
}
async function refreshStatus(){const d=await jfetch('/api/status');const source=d.token_source==='browser'?'saved in browser':(d.token_source==='environment'?'environment':'');document.getElementById('tokenState').innerHTML=d.token_configured?("<span class=\"status good\">"+(globalThis.YGCI18n?.html("ui.reverb_token_ok_ad344564",{},"Reverb Token OK")??"Reverb Token OK"))+(source?' / '+source:'')+'</span>':("<span class=\"status bad\">"+(globalThis.YGCI18n?.html("ui.reverb_token_not_set_841fef8a",{},"Reverb Token not set")??"Reverb Token not set")+"</span>");const input=document.getElementById('tokenInput');if(document.activeElement!==input){input.value=storedToken();input.placeholder=d.token_source==='environment'?(globalThis.YGCI18n?.t("ui.set_by_environment_variable_value_hidden_773dabb5",{},"Set by environment variable (value hidden)")??"Set by environment variable (value hidden)"):(globalThis.YGCI18n?.t("ui.enter_token_2fd4eb38",{},"Enter token")??"Enter token")}}
let repeatedGroups=[];
let repeatedBusy=false;
function renderObservationMatrix(d){
  const matrix=d.matrix||{columns:[],rows:[],current:{}};
  const snapshot=matrix.columns.filter(col=>col.group==='individual');
  const specifications=matrix.columns.filter(col=>col.group==='specification');
  const fieldLabel=key=>({manufacturer:(globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker"),model:(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model"),finish:(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish"),year:(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year"),serial_number:(globalThis.YGCI18n?.t("ui.serial_8ea09493",{},"Serial")??"Serial"),location_country:(globalThis.YGCI18n?.t("ui.country_701d021d",{},"Country")??"Country"),location_region:(globalThis.YGCI18n?.t("ui.region_d3a008ef",{},"Region")??"Region"),current_owner_name:(globalThis.YGCI18n?.t("ui.current_owner_aa8c6157",{},"Current Owner")??"Current Owner"),current_owner_type:(globalThis.YGCI18n?.t("ui.owner_type_fa33215b",{},"Owner Type")??"Owner Type"),current_owner_user_id:(globalThis.YGCI18n?.t("ui.owner_user_id_bb0f7bec",{},"Owner User ID")??"Owner User ID"),current_owner_source_url:(globalThis.YGCI18n?.t("ui.owner_source_url_c49fa436",{},"Owner Source URL")??"Owner Source URL")})[key]||((globalThis.YGCI18n?.t("ui.spec_cda0a40b",{},"Spec ·")??"Spec ·")+" "+key.slice(5).replace(/_/g,' '));
  const formatValue=value=>value===null||value===undefined||value===''?(globalThis.YGCI18n?.t("ui.blank_2c3d371c",{},"Blank")??"Blank"):String(value);
  const header=("<thead><tr><th rowspan=\"2\" style=\"text-align:left\">"+(globalThis.YGCI18n?.html("ui.claim_oldest_first_07cd1b39",{},"Claim (oldest first)")??"Claim (oldest first)")+"</th><th colspan=\"")+snapshot.length+("\">"+(globalThis.YGCI18n?.html("ui.guitar_individual_a61ae7c4",{},"Guitar Individual")??"Guitar Individual")+"</th>")+(specifications.length?'<th colspan="'+specifications.length+("\">"+(globalThis.YGCI18n?.html("ui.specification_39732416",{},"Specification")??"Specification")+"</th>"):'')+'</tr><tr>'+matrix.columns.map(col=>'<th scope="col">'+esc(fieldLabel(col.key))+'</th>').join('')+'</tr></thead>';
  const rows=matrix.rows.map(row=>{
    const results=[...new Set((row.decisions||[]).map(x=>x.result+(x.reason?' · '+x.reason:'')))].join(' / ');
    const evidences=[...new Set([...(row.decisions||[]).flatMap(x=>(x.evidence||[]).map(e=>e.source_listing_id?(e.source_site+' #'+e.source_listing_id):e.evidence_type)),...(row.specification_evidence?[row.specification_evidence.source_site+' #'+row.specification_evidence.source_listing_id]:[])])];
    const claim='<th scope="row" class="matrix-claim"><strong>#'+Number(row.claim_id)+' · '+esc(row.kind||row.type)+'</strong><small>'+esc((row.occurred_at||(globalThis.YGCI18n?.t("ui.date_unknown_bc11be8c",{},"Date unknown")??"Date unknown")).slice(0,10))+' · '+esc(row.author_name||'')+'</small><small>'+esc(row.status)+' / '+esc(row.verification_status)+' · '+esc(results||'—')+'</small>'+(evidences.length?("<small>"+(globalThis.YGCI18n?.html("ui.evidence_e56d5168",{},"Evidence:")??"Evidence:")+" ")+esc(evidences.join(', '))+'</small>':'')+'</th>';
    return '<tr>'+claim+matrix.columns.map(col=>{
      const cell=row.cells[col.key];
      if(!cell)return '<td class="matrix-unrelated">—</td>';
      const value=formatValue(cell.value);
      return '<td class="'+(cell.adopted?'matrix-adopted':'matrix-rejected')+'" title="'+(cell.adopted?(globalThis.YGCI18n?.t("ui.adopted_by_observation_1220eb51",{},"Adopted by Observation")??"Adopted by Observation"):(globalThis.YGCI18n?.t("ui.not_adopted_for_current_value_cc49a85e",{},"Not adopted for current value")??"Not adopted for current value"))+' · '+esc(value)+'"><span class="matrix-cell-value">'+esc(value)+'</span></td>';
    }).join('')+'</tr>';
  }).join('');
  const footer=("<tfoot><tr><th scope=\"row\" class=\"matrix-claim\">"+(globalThis.YGCI18n?.html("ui.current_guitar_individual_b163adb8",{},"Current Guitar Individual")??"Current Guitar Individual")+"</th>")+matrix.columns.map(col=>{
    const mismatch=Object.prototype.hasOwnProperty.call(d.differences||{},col.key);
    const value=Object.prototype.hasOwnProperty.call(matrix.current,col.key)?formatValue(matrix.current[col.key]):'—';
    return '<td class="'+(mismatch?'matrix-mismatch':'')+'" title="'+(mismatch?(globalThis.YGCI18n?.t("ui.saved_value_differs_from_observation_result_c0d4819a",{},"Saved value differs from Observation result ·")??"Saved value differs from Observation result ·")+" ":'')+esc(value)+'"><span class="matrix-cell-value">'+esc(value)+'</span></td>';
  }).join('')+'</tr></tfoot>';
  const mismatches=Object.entries(d.differences||{});
  return ("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.individual_056c49a5",{},"Individual #")??"Individual #"))+Number(d.individual_id)+' · '+matrix.rows.length+" "+(globalThis.YGCI18n?.t("ui.claims_differences_from_saved_snapshot_68bf8129",{},"Claims · Differences from saved Snapshot:")??"Claims · Differences from saved Snapshot:")+" "+mismatches.length+' (read only)</p>'+
    ("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.light_gray_adopted_dark_gray_not_adopted_not_applicable_a__d1c41974",{},"Light gray = adopted, dark gray = not adopted, — = not applicable. A blank value proposes clearing a field. The final Specification row shows the current displayed value.")??"Light gray = adopted, dark gray = not adopted, — = not applicable. A blank value proposes clearing a field. The final Specification row shows the current displayed value.")+"</p>")+
    '<div class="observation-matrix-scroll"><table class="observation-matrix" style="width:'+(94+60*matrix.columns.length+matrix.columns.length+1)+'px"><colgroup><col class="matrix-claim-col">'+matrix.columns.map(()=>'<col class="matrix-value-col">').join('')+'</colgroup>'+header+'<tbody>'+rows+'</tbody>'+footer+'</table></div>'+
    (mismatches.length?("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.saved_values_differ_from_evaluated_values_8008696d",{},"Saved values differ from evaluated values:")??"Saved values differ from evaluated values:")+" ")+mismatches.map(([key,x])=>esc(fieldLabel(key))+' (saved '+esc(x.saved??'—')+' / evaluated '+esc(x.evaluated??'—')+')').join(' / ')+'</p>':'');
}
async function openObservationDiagnostic(){
  if(!selectedIndividualId){alert((globalThis.YGCI18n?.t("ui.select_a_guitar_first_e551a1ad",{},"Select a guitar first.")??"Select a guitar first."));return}
  const dialog=document.getElementById('observationDiagnosticDialog');
  YGCOverlays.open(dialog);
  const body=document.getElementById('observationDiagnosticBody');body.textContent=(globalThis.YGCI18n?.t("ui.loading_ba3bbbe1",{},"Loading…")??"Loading…");
  try{
    const d=await jfetch('/api/admin/individuals/'+selectedIndividualId+'/observation-diagnostic');
    body.innerHTML=renderObservationMatrix(d);
  }catch(e){body.textContent=e.message}
}
async function openRepeated(){
  YGCOverlays.close('databaseMaintenanceDialog');
  const dialog=document.getElementById('repeatedDialog');
  YGCOverlays.open(dialog);
  const container=document.getElementById('repeatedGroups');
  container.textContent=(globalThis.YGCI18n?.t("ui.loading_ba3bbbe1",{},"Loading…")??"Loading…");
  try{
    const d=await jfetch('/api/admin/repeated',{headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    repeatedGroups=d.items;
    container.innerHTML=d.items.length?d.items.map((g,n)=>'<section class="panel"><h3>'+esc(g.manufacturer)+' / '+esc(g.serial)+("</h3><div style=\"overflow:auto\"><table><thead><tr><th>"+(globalThis.YGCI18n?.html("ui.keep_183f00f4",{},"Keep")??"Keep")+"</th><th>ID</th><th>"+(globalThis.YGCI18n?.html("ui.maker_model_989ae4f2",{},"Maker / Model")??"Maker / Model")+"</th><th>"+(globalThis.YGCI18n?.html("ui.year_serial_24e63433",{},"Year / Serial")??"Year / Serial")+"</th><th>"+(globalThis.YGCI18n?.html("ui.owner_4b1b8aa3",{},"Owner")??"Owner")+"</th><th>"+(globalThis.YGCI18n?.html("ui.listings_claims_1ea265e3",{},"Listings / Claims")??"Listings / Claims")+"</th></tr></thead><tbody>")+g.items.map(i=>'<tr><td><input type="radio" name="repeated-'+n+'" value="'+Number(i.id)+'" aria-label="Individual '+Number(i.id)+' to keep"></td><td><button class="secondary" onclick="YGCOverlays.close(\'repeatedDialog\');showIndividual('+Number(i.id)+')">#'+Number(i.id)+'</button></td><td>'+esc(i.manufacturer)+' / '+esc(i.model)+'</td><td>'+esc(i.year)+' / '+esc(i.serial_number)+'</td><td>'+esc(i.current_owner_name||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))+'</td><td>'+Number(i.listing_count)+' / '+Number(i.claim_count)+'</td></tr>').join('')+'</tbody></table></div><div class="modal-actions"><button data-ui-action="danger" onclick="resolveRepeated('+n+(",'merge')\">"+(globalThis.YGCI18n?.html("ui.merge_8851aaa7",{},"Merge")??"Merge")+"</button><button data-ui-action=\"danger\" class=\"danger\" onclick=\"resolveRepeated(")+n+(",'delete')\">"+(globalThis.YGCI18n?.html("ui.delete_e2d0a549",{},"Delete")??"Delete")+"</button></div></section>")).join(''):(globalThis.YGCI18n?.t("ui.no_duplicate_candidates_57c185a2",{},"No duplicate candidates.")??"No duplicate candidates.");
  }catch(e){container.textContent=e.message}
}
async function resolveRepeated(index,action){
  if(repeatedBusy)return;
  const selected=document.querySelector('input[name="repeated-'+index+'"]:checked');
  if(!selected){alert((globalThis.YGCI18n?.t("ui.select_the_guitar_to_keep_67301581",{},"Select the guitar to keep.")??"Select the guitar to keep."));return}
  const keepId=Number(selected.value), ids=repeatedGroups[index].items.map(i=>Number(i.id));
  const removed=ids.filter(id=>id!==keepId);
  if(!confirm((globalThis.YGCI18n?.t("ui.keep_e7d30518",{},"Keep #")??"Keep #")+keepId+' and '+(action==='merge'?'merge the history of ':'permanently delete ')+'#'+removed.join(', #')+(action==='merge'?'. Source Claims that change owner or other state will require review.':'. This also deletes related records and cannot be undone.')+" "+(globalThis.YGCI18n?.t("ui.continue_5c21be5a",{},"Continue?")??"Continue?")))return;
  if(action==='delete'&&prompt((globalThis.YGCI18n?.t("ui.type_delete_to_confirm_1f644ad5",{},"Type DELETE to confirm.")??"Type DELETE to confirm."))!=='DELETE')return;
  repeatedBusy=true;
  document.querySelectorAll('#repeatedGroups button').forEach(b=>b.disabled=true);
  try{
    await jfetch('/api/admin/repeated/resolve',{method:'POST',headers:{'Content-Type':'application/json','X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},body:JSON.stringify({keep_id:keepId,member_ids:ids,action})});
    await loadIndividuals();await loadStatistics();
    await showIndividual(keepId);
    if(activeUser&&activeUser.user)await loadActiveUser();
  }catch(e){alert(e.message)}
  finally{repeatedBusy=false;await openRepeated()}
}
async function saveToken(){const token=document.getElementById('tokenInput').value.trim();if(!token){alert((globalThis.YGCI18n?.t("ui.enter_a_token_64bf1192",{},"Enter a token.")??"Enter a token."));return}localStorage.setItem(TOKEN_KEY,token);document.getElementById('tokenInput').blur();await refreshStatus()}
async function clearToken(){localStorage.removeItem(TOKEN_KEY);const input=document.getElementById('tokenInput');input.value='';input.blur();await refreshStatus()}
function exportDatabase(){window.location.href='/api/export-db'}
function openDatabaseImport(){const input=document.getElementById('dbImportInput');input.value='';input.click()}
async function importDatabaseFile(input){
  const file=input.files&&input.files[0];
  if(!file)return;
  const message=(globalThis.YGCI18n?.t("ui.replace_the_current_db_and_media_with_the_selected_backup_b1301912",{},"Replace the current DB and media with the selected backup.")??"Replace the current DB and media with the selected backup.")+"\n\n"+file.name+"\n\n"+(globalThis.YGCI18n?.t("ui.a_legacy_db_file_can_also_be_restored_but_it_does_not_incl_c6ecab5b",{},"A legacy .db file can also be restored, but it does not include media.\n\nBack up the current state first if needed. Continue?")??"A legacy .db file can also be restored, but it does not include media.\n\nBack up the current state first if needed. Continue?");
  if(!confirm(message)){input.value='';return}
  try{
    const d=await jfetch('/api/import-db',{
      method:'POST',
      headers:{'Content-Type':'application/octet-stream'},
      body:file
    });
    individuals=[];
    document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.select_a_row_in_product_list_to_view_its_history_9833a49b",{},"Select a row in Product List to view its history.")??"Select a row in Product List to view its history.");
    consoleCrawlJobs.clear();
    document.getElementById('crawlLogStatus').textContent=(globalThis.YGCI18n?.t("ui.backup_restored_0a4cba5f",{},"Backup restored")??"Backup restored");
    await loadCrawlRunLog();
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    const imported=d.imported_counts||{};
    const media=d.legacy_database?(globalThis.YGCI18n?.t("ui.legacy_db_format_no_media_504ff66f",{},"Legacy DB format (no media)")??"Legacy DB format (no media)"):((globalThis.YGCI18n?.t("ui.media_f69bf966",{},"Media:")??"Media:")+" "+(d.imported_media_count??0));
    const architecture=await jfetch('/api/claim-architecture-status');
    alert((globalThis.YGCI18n?.t("ui.backup_restored_observations_9824ce0a",{},"Backup restored.\nObservations:")??"Backup restored.\nObservations:")+" "+(imported.observations??'')+"\n"+(globalThis.YGCI18n?.t("ui.product_list_94d64723",{},"Product List:")??"Product List:")+" "+(imported.individuals??'')+"\n"+(globalThis.YGCI18n?.t("ui.crawl_runs_9b9b2234",{},"Crawl Runs:")??"Crawl Runs:")+" "+(imported.crawl_runs??'')+'\n'+media+"\n"+(globalThis.YGCI18n?.t("ui.claim_migration_f49d80ce",{},"Claim Migration:")??"Claim Migration:")+" "+(architecture.ready?(globalThis.YGCI18n?.t("ui.not_required_5fe2851c",{},"Not required")??"Not required"):(globalThis.YGCI18n?.t("ui.required_4850b174",{},"Required")??"Required")));
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.could_not_restore_the_backup_00b4788a",{},"Could not restore the backup.")??"Could not restore the backup.")+"\n"+e.message);
  }finally{
    input.value='';
  }
}
async function runClaimMigration(){
  try{
    const status=await jfetch('/api/claim-architecture-status');
    if(status.ready){
      alert((globalThis.YGCI18n?.t("ui.this_db_uses_the_claim_centered_structure_and_its_snapshot_0e600018",{},"This DB uses the Claim-centered structure and its Snapshot is current.")??"This DB uses the Claim-centered structure and its Snapshot is current."));
      return;
    }
    const message=(globalThis.YGCI18n?.t("ui.migrate_the_legacy_observation_centered_db_to_the_claim_ce_a0f0e9a4",{},"Migrate the legacy Observation-centered DB to the Claim-centered structure.\n\nUnmigrated Listing Observations:")??"Migrate the legacy Observation-centered DB to the Claim-centered structure.\n\nUnmigrated Listing Observations:")+" "+status.unmigrated_listing_observations+"\n"+(globalThis.YGCI18n?.t("ui.individuals_without_claims_a2adfb4b",{},"Individuals without Claims:")??"Individuals without Claims:")+" "+status.claimless_individuals+"\n\n"+(globalThis.YGCI18n?.t("ui.existing_claims_will_not_be_duplicated_continue_2f66a2d8",{},"Existing Claims will not be duplicated. Continue?")??"Existing Claims will not be duplicated. Continue?");
    if(!confirm(message))return;
    const d=await jfetch('/api/migrate-claims',{method:'POST'});
    const m=d.migration||{};
    const a=d.after||{};
    await refreshStatus();
    await loadIndividuals();
    const r=d.rebuild||{};
    alert((globalThis.YGCI18n?.t("ui.claim_migration_snapshot_rebuild_complete_claims_created_3023e50b",{},"Claim Migration / Snapshot Rebuild complete\nClaims created:")??"Claim Migration / Snapshot Rebuild complete\nClaims created:")+" "+(m.claims_created??0)+"\n"+(globalThis.YGCI18n?.t("ui.listing_items_created_13eceae0",{},"Listing items created:")??"Listing items created:")+" "+(m.listing_items_created??0)+"\n"+(globalThis.YGCI18n?.t("ui.migration_snapshots_946afc1d",{},"Migration snapshots:")??"Migration snapshots:")+" "+(m.snapshots_rebuilt??0)+"\n"+(globalThis.YGCI18n?.t("ui.all_snapshots_rebuilt_7f1418fb",{},"All snapshots rebuilt:")??"All snapshots rebuilt:")+" "+(r.snapshots_rebuilt??0)+"\n"+(globalThis.YGCI18n?.t("ui.skipped_bdba7344",{},"Skipped:")??"Skipped:")+" "+(r.snapshots_skipped??0)+"\n"+(globalThis.YGCI18n?.t("ui.ready_00fb0810",{},"Ready:")??"Ready:")+" "+(a.ready?(globalThis.YGCI18n?.t("ui.yes_85a39ab3",{},"Yes")??"Yes"):(globalThis.YGCI18n?.t("ui.no_1ea442a1",{},"No")??"No"))+(a.backfill_recommended?"\n\n"+(globalThis.YGCI18n?.t("ui.some_reverb_listing_claims_lack_location_data_next_run_bac_3eaad0e7",{},"Some Reverb Listing Claims lack Location data. Next, run \"Backfill existing DB (one time)\" .")??"Some Reverb Listing Claims lack Location data. Next, run \"Backfill existing DB (one time)\" ."):''));
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.claim_migration_failed_a539a24c",{},"Claim Migration failed.")??"Claim Migration failed.")+"\n"+e.message);
  }
}

async function backfillCachedSpecifications(){
  if(!confirm((globalThis.YGCI18n?.t("ui.clean_incorrect_automated_specifications_and_duplicate_fin_572ddcf4",{},"Clean incorrect automated Specifications and duplicate Finish values, then add safe specifications from saved details to guitars without a user owner. Continue?")??"Clean incorrect automated Specifications and duplicate Finish values, then add safe specifications from saved details to guitars without a user owner. Continue?")))return;
  const button=document.getElementById('backfillSpecificationsButton');button.disabled=true;
  try{
    const d=await jfetch('/api/admin/backfill-cached-specifications',{method:'POST'});
    await loadIndividuals();
    alert((globalThis.YGCI18n?.t("ui.specification_cleanup_and_additions_complete_incorrect_or__df6a0357",{},"Specification cleanup and additions complete.\nIncorrect or duplicate Finish fields removed:")??"Specification cleanup and additions complete.\nIncorrect or duplicate Finish fields removed:")+" "+d.corrected_items+"\n"+(globalThis.YGCI18n?.t("ui.claims_cleaned_c3d9c11b",{},"Claims cleaned:")??"Claims cleaned:")+" "+d.corrected_claims+"\n"+(globalThis.YGCI18n?.t("ui.empty_claims_3758495f",{},"Empty Claims:")??"Empty Claims:")+" "+d.removed_claims+"\n"+(globalThis.YGCI18n?.t("ui.guitars_without_a_user_owner_a228c7ff",{},"Guitars without a user owner:")??"Guitars without a user owner:")+" "+d.ownerless+"\n"+(globalThis.YGCI18n?.t("ui.with_details_4a8d9676",{},"With details:")??"With details:")+" "+d.with_detail+"\n"+(globalThis.YGCI18n?.t("ui.claims_created_e47530d7",{},"Claims created:")??"Claims created:")+" "+d.created+"\n"+(globalThis.YGCI18n?.t("ui.fields_added_e9677092",{},"Fields added:")??"Fields added:")+" "+d.items+"\n"+(globalThis.YGCI18n?.t("ui.no_fields_available_f9cff53c",{},"No fields available:")??"No fields available:")+" "+d.skipped_no_specs+"\n"+(globalThis.YGCI18n?.t("ui.already_processed_c3160d0c",{},"Already processed:")??"Already processed:")+" "+d.skipped_existing);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.could_not_add_specifications_c57d6429",{},"Could not add Specifications.")??"Could not add Specifications.")+"\n"+e.message)}
  finally{button.disabled=false}
}

async function resetDatabase(){
  const message=(globalThis.YGCI18n?.t("ui.delete_all_current_observation_individual_and_crawl_histor_b730ee9d",{},"Delete all current Observation, Individual, and crawl history and recreate an empty DB.\n\nThis action cannot be undone. Continue?")??"Delete all current Observation, Individual, and crawl history and recreate an empty DB.\n\nThis action cannot be undone. Continue?");
  if(!confirm(message))return;
  const typed=prompt((globalThis.YGCI18n?.t("ui.type_reset_to_confirm_70a8bccc",{},"Type RESET to confirm.")??"Type RESET to confirm."));
  if(typed!=='RESET'){
    if(typed!==null)alert((globalThis.YGCI18n?.t("ui.the_confirmation_did_not_match_action_canceled_fea1b136",{},"The confirmation did not match; action canceled.")??"The confirmation did not match; action canceled."));
    return;
  }
  try{
    await jfetch('/api/reset-db',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({confirm:'RESET'})
    });
    individuals=[];
    document.getElementById('individualBody').innerHTML='';
    document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.select_a_row_in_product_list_to_view_its_history_9833a49b",{},"Select a row in Product List to view its history.")??"Select a row in Product List to view its history.");
    consoleCrawlJobs.clear();
    document.getElementById('crawlLogStatus').textContent=(globalThis.YGCI18n?.t("ui.db_reset_complete_8a15c04d",{},"DB reset complete")??"DB reset complete");
    await loadCrawlRunLog();
    sessionStorage.removeItem(ACTIVE_USER_KEY);
    activeUser=null;
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    alert((globalThis.YGCI18n?.t("ui.db_reset_complete_cc81f4b0",{},"DB reset complete.")??"DB reset complete."));
  }catch(e){
    alert(e.message);
  }
}
async function loadIndividuals(){individuals=await jfetch('/api/individuals');renderIndividuals();if(document.getElementById('pendingAcquireClaimsDialog').open)await loadUnverifiedAcquires();await refreshStatus()}
let unverifiedAcquireOffset=0;
async function loadUnverifiedAcquires(offset=unverifiedAcquireOffset){
  try{
    const d=await jfetch('/api/claims/unverified-acquires?without_request=true&limit=100&offset='+Math.max(0,offset));
    if(d.total>0&&offset>=d.total)return loadUnverifiedAcquires(Math.floor((d.total-1)/100)*100);
    unverifiedAcquireOffset=d.offset;
    document.getElementById('unverifiedAcquireTotal').textContent='('+d.total+')';
    document.getElementById('unverifiedAcquireBody').innerHTML=d.items.map(x=>'<tr class="clickable" onclick="YGCOverlays.close(\'pendingAcquireClaimsDialog\');showIndividual('+Number(x.individual_id)+')"><td>#'+Number(x.claim_id)+'</td><td>'+esc(x.manufacturer)+' '+esc(x.model||'')+'</td><td>'+esc(x.serial_number||'—')+'</td><td>'+esc(x.author_name)+'</td><td>'+esc(x.current_owner_name||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))+'</td><td>'+esc(x.proposed_owner||x.author_name)+'</td><td>'+esc(x.occurred_at||x.created_at)+'</td></tr>').join('')||("<tr><td colspan=\"7\">"+(globalThis.YGCI18n?.html("ui.no_unverified_acquire_claims_49295112",{},"No Unverified Acquire Claims.")??"No Unverified Acquire Claims.")+"</td></tr>");
    document.getElementById('unverifiedAcquirePage').textContent=d.total?(d.offset+1)+'–'+(d.offset+d.items.length)+' / '+d.total:'0 / 0';
    document.getElementById('unverifiedAcquirePrev').disabled=d.offset===0||!d.total;
    document.getElementById('unverifiedAcquireNext').disabled=d.offset+d.items.length>=d.total;
  }catch(e){document.getElementById('unverifiedAcquireBody').innerHTML='<tr><td colspan="7">'+esc(e.message)+'</td></tr>'}
}
function countList(title,rows){
  return '<div class="stat-group"><strong>'+esc(title)+'</strong>'+((rows&&rows.length)?rows.map(x=>'<div class="stat-line"><span>'+esc(x.label)+'</span><span>'+esc(x.count)+'</span></div>').join(''):'<div class="sub">—</div>')+'</div>';
}
async function loadStatistics(){
  if(!document.getElementById('statisticsDialog').open)return;
  try{
    const d=await jfetch('/api/statistics');
    const s=d.summary||{};
    const summary='<div class="stats-summary">'+[
      [(globalThis.YGCI18n?.t("ui.product_list_a7042f80",{},"Product List")??"Product List"),s.individuals],
      [(globalThis.YGCI18n?.t("ui.makers_161f1071",{},"Makers")??"Makers"),s.makers],
      [(globalThis.YGCI18n?.t("ui.models_d17d2d78",{},"Models")??"Models"),s.models],
      [(globalThis.YGCI18n?.t("ui.finishes_42696288",{},"Finishes")??"Finishes"),s.finishes],
      [(globalThis.YGCI18n?.t("ui.current_location_known_fcb898c6",{},"Current Location known")??"Current Location known"),s.located_individuals]
    ].map(x=>'<span>'+esc(x[0])+' <strong>'+esc(x[1]??0)+'</strong></span>').join('')+'</div>';
    const lists='<div class="stats-columns">'+[
      countList((globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker"),d.makers),
      countList((globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model"),d.models),
      countList((globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish"),d.finishes),
      countList((globalThis.YGCI18n?.t("ui.current_country_8bf31349",{},"Current Country")??"Current Country"),d.current_countries)
    ].join('')+'</div>';
    document.getElementById('statistics').innerHTML=summary+lists;
  }catch(e){
    document.getElementById('statistics').textContent=(globalThis.YGCI18n?.t("ui.statistics_error_18f62860",{},"Statistics error:")??"Statistics error:")+" "+e.message;
  }
}
let selectedUserId=null;
let themeOptions=[];
async function loadUsers(){
  if(!themeOptions.length)themeOptions=await jfetch('/api/themes');
  users=await jfetch('/api/users');
  const saved=sessionStorage.getItem(ACTIVE_USER_KEY)||'';
  renderUserList();
  if(selectedUserId&&users.some(u=>Number(u.id)===selectedUserId))await showUserRecord(selectedUserId);
  else if(users.some(u=>String(u.id)===saved))await showUserRecord(Number(saved));
  else{selectedUserId=null;activeUser=null;sessionStorage.removeItem(ACTIVE_USER_KEY);updateOpenTopButton();document.getElementById('accountPanel').textContent=(globalThis.YGCI18n?.t("ui.select_a_user_from_the_list_on_the_left_04d69874",{},"Select a user from the list on the left.")??"Select a user from the list on the left.")}
}
function renderUserList(){
  const filter=document.getElementById('userFilter').value.trim().toLowerCase();
  const matches=users.filter(u=>[u.id,u.display_name,u.account_type,u.ban_status,u.location_country,u.location_region].some(x=>String(x??'').toLowerCase().includes(filter)));
  document.getElementById('userBody').innerHTML=matches.map(u=>'<tr class="clickable'+(selectedUserId===Number(u.id)?' selected':'')+'" onclick="showUserRecord('+Number(u.id)+')"><td class="mono">'+Number(u.id)+'</td><td>'+esc(u.display_name)+'</td><td>'+esc(u.account_type)+'</td><td>'+esc([u.location_country,u.location_region].filter(Boolean).join(' / ')||'—')+'</td><td>'+Number(u.current_guitar_count||0)+'</td></tr>').join('')||("<tr><td colspan=\"5\" class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_matching_users_579f8c39",{},"No matching users.")??"No matching users.")+"</td></tr>");
  document.getElementById('userCount').textContent=matches.length+' / '+users.length+' users';
}
async function showUserRecord(id){
  scrollConsoleLayer('user-detail-window');
  selectedUserId=Number(id);
  renderUserList();
  updateOpenTopButton();
  const panel=document.getElementById('accountPanel');
  panel.textContent=(globalThis.YGCI18n?.t("ui.loading_47d2a515",{},"Loading...")??"Loading...");
  try{
    const data=await jfetch('/api/users/'+selectedUserId);
    if(selectedUserId!==Number(id))return;
    const u=data.user,summary=data.summary||{};
    if(u.ban_status==='ban'){
      activeUser=null;
      sessionStorage.removeItem(ACTIVE_USER_KEY);
    }else{
      activeUser=data;
      sessionStorage.setItem(ACTIVE_USER_KEY,String(u.id));
    }
    updateOpenTopButton();
    const meta=[[(globalThis.YGCI18n?.t("ui.user_id_7967e089",{},"User ID")??"User ID"),u.id],[(globalThis.YGCI18n?.t("ui.joined_69318b0c",{},"Joined")??"Joined"),u.created_at],[(globalThis.YGCI18n?.t("ui.updated_3a5ecca1",{},"Updated")??"Updated"),u.updated_at],[(globalThis.YGCI18n?.t("ui.owned_17b760c4",{},"Owned")??"Owned"),summary.owned_count||0],[(globalThis.YGCI18n?.t("ui.formerly_owned_65b08593",{},"Formerly Owned")??"Formerly Owned"),summary.former_count||0],[(globalThis.YGCI18n?.t("ui.claims_1c85c122",{},"Claims")??"Claims"),summary.claim_count||0]];
    if(u.app_user_id)meta.push([(globalThis.YGCI18n?.t("ui.account_id_919bb4cb",{},"Account ID")??"Account ID"),u.app_user_id],[(globalThis.YGCI18n?.t("ui.account_status_dafb01ab",{},"Account Status")??"Account Status"),u.account_disabled?(globalThis.YGCI18n?.t("ui.disabled_75081b59",{},"Disabled")??"Disabled"):(globalThis.YGCI18n?.t("ui.active_92340695",{},"Active")??"Active")]);
    if(!CONSOLE_ADMIN_TOKEN)meta.push([(globalThis.YGCI18n?.t("ui.display_name_18d67c99",{},"Display Name")??"Display Name"),u.display_name],[(globalThis.YGCI18n?.t("ui.account_type_dce81c5b",{},"Account Type")??"Account Type"),u.account_type],['BAN Status',u.ban_status||'normal'],[(globalThis.YGCI18n?.t("ui.country_701d021d",{},"Country")??"Country"),u.location_country||'—'],[(globalThis.YGCI18n?.t("ui.city_region_8a388dda",{},"City / Region")??"City / Region"),u.location_region||'—'],[(globalThis.YGCI18n?.t("ui.bio_3933b180",{},"Bio")??"Bio"),u.bio||'—'],...['birth','residence','bio','avatar'].map(key=>[key+" "+(globalThis.YGCI18n?.t("ui.visibility_7448611d",{},"Visibility")??"Visibility"),u[key+'_visibility']||'—']),[(globalThis.YGCI18n?.t("ui.signature_guitar_id_54225d64",{},"Signature Guitar ID")??"Signature Guitar ID"),u.signature_individual_id||'—'],[(globalThis.YGCI18n?.t("ui.theme_efb52e71",{},"Theme")??"Theme"),u.theme||'dark_default']);
    const guitars=data.guitars||[];
    panel.className='';
    panel.innerHTML='<div class="user-detail-header"><img src="/api/users/'+Number(u.id)+'/avatar?viewer_id='+Number(u.id)+'&v='+encodeURIComponent(u.updated_at||'')+'" alt="" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'"><div class="user-header-text"><strong>'+esc(u.display_name)+("</strong><span>"+(globalThis.YGCI18n?.html("ui.account_type_d120f0dd",{},"Account Type:")??"Account Type:")+" ")+esc(u.account_type)+'</span><span>BAN Status: '+esc(u.ban_status||'normal')+'</span></div></div><div class="user-detail-list">'+meta.map(([label,value])=>'<div class="detail-meta-item"><span class="detail-meta-label">'+esc(label)+'</span><span class="detail-meta-value">'+esc(value)+'</span></div>').join('')+'</div>'+
      (CONSOLE_ADMIN_TOKEN?'<form id="adminUserForm" class="admin-user-form" onsubmit="saveAdminUser(event,'+Number(u.id)+')">'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.display_name_18d67c99",{},"Display Name")??"Display Name")+"<input name=\"display_name\" maxlength=\"120\" required value=\"")+esc(u.display_name)+'"></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.account_type_dce81c5b",{},"Account Type")??"Account Type")+"<select name=\"account_type\">")+['user','shop','builder','repairer','organization'].map(x=>'<option value="'+x+'"'+(u.account_type===x?' selected':'')+'>'+x+'</option>').join('')+'</select></label>'+
        '<label>BAN Status<select name="ban_status">'+['normal','silent_ban','ban'].map(x=>'<option value="'+x+'"'+((u.ban_status||'normal')===x?' selected':'')+'>'+x+'</option>').join('')+'</select></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.theme_efb52e71",{},"Theme")??"Theme")+"<select name=\"theme\">")+themeOptions.map(theme=>'<option value="'+esc(theme.id)+'"'+((u.theme||'dark_default')===theme.id?' selected':'')+'>'+esc(theme.label)+'</option>').join('')+'</select></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.country_701d021d",{},"Country")??"Country")+"<input name=\"location_country\" maxlength=\"80\" value=\"")+esc(u.location_country||'')+'"></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.city_region_8a388dda",{},"City / Region")??"City / Region")+"<input name=\"location_region\" maxlength=\"120\" value=\"")+esc(u.location_region||'')+'"></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.bio_3933b180",{},"Bio")??"Bio")+"<textarea name=\"bio\" maxlength=\"2000\">")+esc(u.bio||'')+'</textarea></label>'+
        ['birth','residence','bio','avatar'].map(key=>'<label>'+esc(key)+' Visibility<select name="'+key+'_visibility">'+['Public','Members','Followers','Private'].map(v=>'<option value="'+v+'"'+((u[key+'_visibility']||'Private')===v?' selected':'')+'>'+esc(globalThis.YGCI18n?.label('visibility',v)??v)+'</option>').join('')+'</select></label>').join('')+
        ("<label>"+(globalThis.YGCI18n?.html("ui.signature_guitar_6783dbdf",{},"Signature Guitar")??"Signature Guitar")+"<select name=\"signature_individual_id\"><option value=\"\">"+(globalThis.YGCI18n?.html("ui.none_dc937b59",{},"None")??"None")+"</option>")+guitars.filter(g=>g.ownership_status==='current_owner'||Number(g.individual_id)===Number(u.signature_individual_id)).map(g=>'<option value="'+Number(g.individual_id)+'"'+(Number(u.signature_individual_id)===Number(g.individual_id)?' selected':'')+'>'+esc(g.manufacturer+' '+(g.model||'')+' / '+(g.serial_number||''))+'</option>').join('')+'</select></label>'+
        ("<label>"+(globalThis.YGCI18n?.html("ui.avatar_image_195eb84c",{},"Avatar image")??"Avatar image")+"<input type=\"file\" name=\"avatar\" accept=\"image/png,image/jpeg,image/webp,image/gif\"></label>")+
        ("<div class=\"toolbar\"><button data-ui-action=\"primary\" type=\"submit\">"+(globalThis.YGCI18n?.html("ui.save_user_96c2bbb5",{},"Save User")??"Save User")+"</button></div></form>"):'')+
      '<div class="toolbar" style="margin-top:12px"><a href="/users/'+Number(u.id)+'?prototype_user_id='+encodeURIComponent(sessionStorage.getItem(ACTIVE_USER_KEY)||'')+("\" target=\"_blank\" rel=\"noopener\">"+(globalThis.YGCI18n?.html("ui.user_profile_ee7672e2",{},"User Profile")??"User Profile")+"</a></div>")+
      ("<div class=\"detail-section\">"+(globalThis.YGCI18n?.html("ui.guitars_c17fea4e",{},"Guitars")??"Guitars")+" "+"<small class=\"list-item-count\">")+guitars.length+' items</small></div><div class="user-guitar-list">'+(guitars.map(g=>'<div class="user-guitar-row"><a href="#guitar-db" onclick="showIndividual('+Number(g.individual_id)+')">'+esc(g.manufacturer)+' '+esc(g.model||'')+' · '+esc(g.serial_number||'—')+'</a><span class="sub">'+esc(g.ownership_status||'')+'</span></div>').join('')||("<div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_guitars_registered_8213507b",{},"No guitars registered.")??"No guitars registered.")+"</div>"))+'</div>';
    if(selectedIndividualId)showIndividual(selectedIndividualId,false).catch(e=>{
      document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.product_detail_error_41d1b37b",{},"Product Detail error:")??"Product Detail error:")+" "+e.message;
    });
  }catch(e){panel.className='sub';panel.textContent=(globalThis.YGCI18n?.t("ui.user_detail_error_7273c96a",{},"User Detail error:")??"User Detail error:")+" "+e.message}
}
async function saveAdminUser(event,id){
  event.preventDefault();const form=event.currentTarget,fields=new FormData(form);
  const status=String(fields.get('ban_status'));
  if(status!=='normal'&&!confirm((globalThis.YGCI18n?.t("ui.set_this_account_to_8edb064f",{},"Set this account to")??"Set this account to")+" "+status+(globalThis.YGCI18n?.t("ui.public_claims_and_guitar_data_will_be_recalculated_continu_70c4e0d8",{},"? Public Claims and guitar data will be recalculated. Continue?")??"? Public Claims and guitar data will be recalculated. Continue?")))return;
  const body={};for(const key of ['display_name','account_type','ban_status','theme','location_country','location_region','bio','birth_visibility','residence_visibility','bio_visibility','avatar_visibility']){
    const value=String(fields.get(key)||'').trim();body[key]=value||null;
  }
  body.signature_individual_id=fields.get('signature_individual_id')?Number(fields.get('signature_individual_id')):null;
  const file=fields.get('avatar');const btn=form.querySelector('button[type=submit]');btn.disabled=true;
  try{
    await jfetch('/api/admin/users/'+id,{method:'PATCH',headers:{'Content-Type':'application/json','X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},body:JSON.stringify(body)});
    if(file&&file.size){const avatarData=new FormData();avatarData.set('avatar',file);
      try{await jfetch('/api/users/'+id+'/avatar',{method:'POST',body:avatarData})}
      catch(e){alert((globalThis.YGCI18n?.t("ui.user_information_was_saved_but_the_avatar_could_not_be_upd_f44f15d1",{},"User information was saved, but the avatar could not be updated.")??"User information was saved, but the avatar could not be updated.")+"\n"+e.message)}
    }
    await loadUsers();await loadIndividuals();if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }catch(e){alert((globalThis.YGCI18n?.t("ui.could_not_update_the_user_1948ff3c",{},"Could not update the user.")??"Could not update the user.")+"\n"+e.message);btn.disabled=false}
}
async function createUser(){
  try{
    const data=await jfetch('/api/users',{method:'POST'});
    const id=String(data.user.id);
    selectedUserId=Number(id);
    await loadUsers();
  }catch(e){alert((globalThis.YGCI18n?.t("ui.could_not_create_the_account_0876cbc0",{},"Could not create the account.")??"Could not create the account.")+"\n"+e.message)}
}
function updateOpenTopButton(){
  const selected=users.find(u=>Number(u.id)===selectedUserId);
  document.getElementById('openUserTopBtn').disabled=!selected||selected.ban_status==='ban'||!!selected.account_disabled;
}
function openTopPageAsActiveUser(){
  const selected=users.find(user=>Number(user.id)===selectedUserId);
  if(!selected||selected.ban_status==='ban'||selected.account_disabled)return;
  window.open('/user-view?prototype_user_id='+encodeURIComponent(selected.id),'_blank','noopener');
}
function openTopPageAsGuest(){
  window.open('/user-view?prototype_user_id=','_blank','noopener');
}
async function loadActiveUser(){
  const id=sessionStorage.getItem(ACTIVE_USER_KEY);
  if(!id){activeUser=null;return}
  try{activeUser=await jfetch('/api/users/'+encodeURIComponent(id))}
  catch(e){activeUser=null;sessionStorage.removeItem(ACTIVE_USER_KEY)}
}
function renderAccount(){if(selectedUserId)showUserRecord(selectedUserId)}
function normalizeSortValue(value,key){if(key==='id'||key==='claim_count')return Number(value||0);return String(value??'').toLowerCase()}
function setIndividualSort(key){if(individualSortKey===key){individualSortDirection*=-1}else{individualSortKey=key;individualSortDirection=1}renderIndividuals();document.getElementById('individualBody').closest('.table-wrap').scrollTop=0}
function updateSortIndicators(){for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){const el=document.getElementById('sort-'+key);if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):''}}
function renderIndividuals(){const q=document.getElementById('individualFilter').value.toLowerCase();const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{const av=normalizeSortValue(a[individualSortKey],individualSortKey);const bv=normalizeSortValue(b[individualSortKey],individualSortKey);if(av<bv)return-1*individualSortDirection;if(av>bv)return 1*individualSortDirection;return Number(a.id)-Number(b.id)});updateSortIndicators();document.getElementById('individualBody').innerHTML=rows.map(x=>'<tr class="clickable" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td></tr>').join('')}
function currentSnapshotOwnerHtml(i){if(!i)return '—';const name=String(i.current_owner_name||'').trim();if(!name)return '—';const type=String(i.current_owner_type||'').trim();const listingUrl=String(i.current_owner_source_url||'').trim();const label=type==='shop'?name+' (Shop)':name;if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';return esc(label)}
function currentLocationHtml(i){const parts=[i&&i.location_country,i&&i.location_region].filter(Boolean);return parts.length?esc(parts.join(' / ')):'—'}
function productGalleryHtml(images,model){return YGCProductGallery.render(images,model,esc)}
function stepProductGallery(delta){YGCProductGallery.step(delta)}
function openProductAlbum(){YGCProductGallery.open()}
function specificationFieldLabel(value){const labels={body:(globalThis.YGCI18n?.t("ui.body_6ccaa641",{},"Body")??"Body"),bridge:(globalThis.YGCI18n?.t("ui.bridge_3892e103",{},"Bridge")??"Bridge"),fingerboard:(globalThis.YGCI18n?.t("ui.fingerboard_92d85445",{},"Fingerboard")??"Fingerboard"),frets:(globalThis.YGCI18n?.t("ui.frets_08aa1381",{},"Frets")??"Frets"),neck:(globalThis.YGCI18n?.t("ui.neck_6b27a971",{},"Neck")??"Neck"),nut:(globalThis.YGCI18n?.t("ui.nut_67c45877",{},"Nut")??"Nut"),pickups:(globalThis.YGCI18n?.t("ui.pickups_088cf7e8",{},"Pickups")??"Pickups"),pickguard:(globalThis.YGCI18n?.t("ui.pickguard_280dde37",{},"Pickguard")??"Pickguard"),potentiometers:(globalThis.YGCI18n?.t("ui.potentiometers_5beb07c1",{},"Potentiometers")??"Potentiometers"),tuners:(globalThis.YGCI18n?.t("ui.tuners_1de22981",{},"Tuners")??"Tuners"),wiring:(globalThis.YGCI18n?.t("ui.wiring_72529059",{},"Wiring")??"Wiring"),weight:(globalThis.YGCI18n?.t("ui.weight_81d27ef6",{},"Weight")??"Weight"),finish:(globalThis.YGCI18n?.t("ui.finish_a6c7a84b",{},"Finish")??"Finish")};const key=String(value||'').trim();return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase())}
function identityFieldLabel(value){const labels={manufacturer:(globalThis.YGCI18n?.t("ui.maker_287f4955",{},"Maker")??"Maker"),model:(globalThis.YGCI18n?.t("ui.model_5e2c614c",{},"Model")??"Model"),year:(globalThis.YGCI18n?.t("ui.year_89f68325",{},"Year")??"Year"),serial_number:(globalThis.YGCI18n?.t("ui.serial_8ea09493",{},"Serial")??"Serial")};return labels[String(value||'')]||String(value||'').replace(/_/g,' ')}
function claimTypeLabel(value){const fallback=String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ');return globalThis.YGCI18n?.t('values.claim_type.'+String(value||'claim'),{},fallback)??fallback}
function incidentClaimLabel(c){return c.value_text==='lost'?(globalThis.YGCI18n?.t("ui.incident_lost_650d5700",{},"Incident Lost")??"Incident Lost"):claimTypeLabel(c.value_text||'incident')}
function displayEventDate(value){if(!value)return (globalThis.YGCI18n?.t("ui.date_unknown_bc11be8c",{},"Date unknown")??"Date unknown");const text=String(value).trim();const direct=text.match(/^(\d{4}-\d{2}-\d{2})$/);if(direct)return direct[1];const d=new Date(text);if(Number.isNaN(d.getTime()))return text;return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function displayInputDate(value){if(!value)return (globalThis.YGCI18n?.t("ui.input_date_unknown_49db8d5c",{},"Input date unknown")??"Input date unknown");const d=new Date(String(value));return Number.isNaN(d.getTime())?String(value):d.toLocaleString(globalThis.YGCI18n?.locale||'en-US')}
function claimHeaderHtml(c,type,eventDate){return '<span class="claim-badge">'+esc(type)+'</span><span class="claim-event-date">'+esc(eventDate)+'</span>'}
function claimVisualTypeClass(c){
  if(c.claim_type==='ownership')return ' claim-type-ownership';
  if(c.claim_type==='specification')return ' claim-type-specification';
  if(c.claim_type==='incident')return ' claim-type-incident';
  if(c.claim_type==='event')return ' claim-type-event';
  if(c.claim_type==='media')return ' claim-type-media';
  return '';
}
function claimCard(c){
  const type=c.claim_type==='specification'?(c.specification_kind==='repair'?(globalThis.YGCI18n?.t("ui.repair_1196b6c5",{},"Repair")??"Repair"):(globalThis.YGCI18n?.t("ui.specification_39732416",{},"Specification")??"Specification")):(c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?incidentClaimLabel(c):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):claimTypeLabel(c.claim_type))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(['automation','merged_listing'].includes(c.ownership_source)?(c.value_text||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown")):(c.author_name||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User"))).trim()||(globalThis.YGCI18n?.t("ui.user_b512d97e",{},"User")??"User");
    const ownerHtml=['automation','merged_listing'].includes(c.ownership_source)?esc(owner):YGCProductDetail.userLink(c.author_user_id,owner,esc);
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||(globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown"))
      : (globalThis.YGCI18n?.t("ui.unknown_b764cdc0",{},"Unknown")??"Unknown");
    if(kind==='lost'){
      body=("<div><strong>"+(globalThis.YGCI18n?.html("ui.reverb_listing_unavailable_current_owner_and_location_are__9c03f334",{},"Reverb listing unavailable. Current owner and location are unknown.")??"Reverb listing unavailable. Current owner and location are unknown.")+"</strong></div>");
    }else if(kind==='release'){
      body=c.ownership_source==='automation'
        ? ("<div><strong>"+(globalThis.YGCI18n?.html("ui.reverb_listing_unavailable_current_owner_and_location_are__9c03f334",{},"Reverb listing unavailable. Current owner and location are unknown.")??"Reverb listing unavailable. Current owner and location are unknown.")+"</strong></div>")
        : '<div><strong>'+ownerHtml+' released this product.</strong></div>';
    }else if(kind==='transfer'&&c.transfer){
      const t=c.transfer;
      body='<div><strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+("</strong></div><div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.transfer_fc5cb474",{},"Transfer:")??"Transfer:")+" ")+esc(t.state)+'</div>';
      if(t.accepted_at)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.evidence_accepted_by_user_155e7a6a",{},"Evidence: Accepted by User #")??"Evidence: Accepted by User #"))+Number(t.accepted_by_user_id)+' · '+esc(displayInputDate(t.accepted_at))+' · Current Owner at acceptance: User #'+Number(t.current_owner_user_id)+'</div>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+ownerHtml+'.</strong></div>';
    }else if(kind!=='acquire'){
      body=("<div><strong>"+(globalThis.YGCI18n?.html("ui.legacy_ownership_claim_335a10da",{},"Legacy Ownership Claim:")??"Legacy Ownership Claim:")+" ")+esc(kind)+'</strong></div>';
    }else{
      body='<div><strong>'+ownerHtml+' became the owner of this product.</strong></div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='incident'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='event'){
    if(c.body)body+='<div><strong>'+esc(c.body)+'</strong></div>';
  }else if(c.claim_type==='specification'){
    const items=(c.spec_items&&c.spec_items.length)?c.spec_items:(c.field_name?[{field_name:c.field_name,value_text:c.value_text}]:[]);
    body=items.map(item=>'<div><strong>'+esc(specificationFieldLabel(item.field_name))+': '+esc(item.value_text||'')+'</strong></div>').join('');
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='identity_correction'){
    const items=c.identity_items||[];
    body=items.map(item=>'<div><strong>'+esc(identityFieldLabel(item.field_name))+':</strong> '+esc(item.old_value||'—')+' → '+esc(item.new_value||'—')+'</div>').join('');
    if(c.body)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.reason_3425d108",{},"Reason:")??"Reason:")+" ")+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||(globalThis.YGCI18n?.t("ui.listing_observed_cef64518",{},"Listing observed")??"Listing observed");
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.owner_9a638cfe",{},"Owner:")??"Owner:")+" ")+YGCProductDetail.userLink(c.observed_owner_user_id,listingOwner,esc)+'</div>';
    if(seller)details.push((globalThis.YGCI18n?.t("ui.seller_16662988",{},"Seller:")??"Seller:")+" "+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push((globalThis.YGCI18n?.t("ui.location_bbdffe25",{},"Location:")??"Location:")+" "+location);
    const specs=[c.observed_model&&((globalThis.YGCI18n?.t("ui.model_11a93106",{},"Model:")??"Model:")+" "+c.observed_model),c.observed_finish&&((globalThis.YGCI18n?.t("ui.finish_38c77297",{},"Finish:")??"Finish:")+" "+c.observed_finish),c.observed_year&&((globalThis.YGCI18n?.t("ui.year_60a37971",{},"Year:")??"Year:")+" "+c.observed_year),c.observed_serial_number&&((globalThis.YGCI18n?.t("ui.serial_8fe19cfa",{},"Serial:")??"Serial:")+" "+c.observed_serial_number)].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.source_site==='reverb'&&c.source_listing_id&&(c.claim_type==='listing'||c.claim_type==='ownership'||c.claim_type==='specification')){
    const id=(globalThis.YGCI18n?.t("ui.reverb_id_209287ab",{},"Reverb ID #")??"Reverb ID #")+esc(c.source_listing_id);
    body+=("<div class=\"claim-memo\">"+(globalThis.YGCI18n?.html("ui.evidence_e56d5168",{},"Evidence:")??"Evidence:")+" ")+(c.source_url?'<a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">'+id+'</a>':id)+'</div>';
  }else if(c.claim_type==='listing'&&c.source_url){
    body+='<div class="claim-memo"><a href="'+esc(c.source_url)+("\" target=\"_blank\" rel=\"noopener noreferrer\">"+(globalThis.YGCI18n?.html("ui.open_listing_5ba1797e",{},"Open listing")??"Open listing")+"</a></div>");
  }
  if(c.evidence_media_id&&c.claim_type!=='media')body+='<div class="claim-memo"><img class="claim-evidence-image" width="48" height="48" style="width:48px;height:48px;max-width:48px;max-height:48px;object-fit:cover" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"></div>';
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const verification=String(c.verification_status||'positive');
  const moderation=("<label>"+(globalThis.YGCI18n?.html("ui.verification_7140f4f1",{},"Verification")??"Verification")+" "+"<select aria-label=\"Claim Verification\" style=\"width:auto\" ")+(!CONSOLE_ADMIN_TOKEN?'disabled ':'')+'onchange="moderateClaim('+Number(c.id)+',this.value)">'+[['positive',(globalThis.YGCI18n?.t("ui.positive_approve_6071d4f4",{},"Positive / Approve")??"Positive / Approve")],['negative',(globalThis.YGCI18n?.t("ui.negative_reject_7395f04c",{},"Negative / Reject")??"Negative / Reject")],['unverified',(globalThis.YGCI18n?.t("ui.unverified_unverified_dbac257a",{},"Unverified / Unverified")??"Unverified / Unverified")]].map(x=>'<option value="'+x[0]+'" '+(verification===x[0]?'selected':'')+'>'+x[1]+'</option>').join('')+'</select></label>';
  const votes='<div class="claim-votes" style="flex-wrap:wrap"><span class="claim-vote">👍 '+good+'</span><span class="claim-vote">👎 '+bad+'</span>'+moderation+'<button data-ui-action="danger" class="claim-vote danger" '+(!CONSOLE_ADMIN_TOKEN?'disabled ':'')+'onclick="moderateClaim('+Number(c.id)+',\'delete\','+(c.claim_type==='listing')+(")\">"+(globalThis.YGCI18n?.html("ui.delete_e2d0a549",{},"Delete")??"Delete")+"</button></div>");
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'"><div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div><div class="claim-body">'+body+'</div><div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+YGCProductDetail.userLink(c.author_user_id,c.author_name,esc)+'</div></div></div>';
}
let currentAdminClaims=[];
function renderAdminChronicle(){
  const ordered=YGCProductDetail.orderedClaims(currentAdminClaims);
  const target=document.getElementById('chronicleEntries');
  if(target)target.innerHTML=ordered.length?ordered.map(adminClaimCard).join(''):("<div class=\"sub\">"+(globalThis.YGCI18n?.html("ui.no_claims_yet_bcafe434",{},"No Claims yet.")??"No Claims yet.")+"</div>");
}
function adminClaimCard(c){
  const status=String(c.verification_status||'positive').toLowerCase();
  if(status==='positive')return claimCard(c);
  const label=c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):claimTypeLabel(c.claim_type);
  return '<div class="claim-compact-row">'+(status==='negative'
    ? '<button type="button" class="claim-negative-dot" title="Negative Claim" onclick="openAdminClaim('+Number(c.id)+')">◉</button>'
    : '<button type="button" class="claim-compact-tag'+claimVisualTypeClass(c)+'" onclick="openAdminClaim('+Number(c.id)+')">'+esc(label)+'</button>')+'</div>';
}
function openAdminClaim(id){
  const claim=currentAdminClaims.find(c=>Number(c.id)===Number(id));
  const content=document.getElementById('adminClaimPopupContent');
  if(claim&&content)content.innerHTML=claimCard(claim);
  YGCOverlays.open('adminClaimPopup');
}
function closeAdminClaim(event){
  if(event&&event.target.id!=='adminClaimPopup')return;
  YGCOverlays.close('adminClaimPopup');
}
function toggleDetailAccordion(id){
  YGCProductDetail.toggleAccordion(id);
}
let individualLoadSequence=0;
async function showIndividual(id,reveal=true){
  if(reveal)scrollConsoleLayer('product-detail-window');
  const sequence=++individualLoadSequence;
  const changedIndividual=selectedIndividualId!==Number(id);
  selectedIndividualId=Number(id);
  renderIndividuals();
  if(changedIndividual)document.getElementById('detail').scrollTop=0;
  const [d,claims,currentSpecifications]=await Promise.all([
    jfetch('/api/individuals/'+id),
    jfetch('/api/individuals/'+id+'/claims'+(activeUser&&activeUser.user?'?viewer_user_id='+encodeURIComponent(activeUser.user.id):'')),
    jfetch('/api/individuals/'+id+'/current-specifications')
  ]);
  if(sequence!==individualLoadSequence)return;
  const i=d.individual;
  const listing=d.current_source||d.current_listing||null;
  const galleryImages=d.gallery_images||[];
  let out='';
  if(galleryImages.length){
    out+=productGalleryHtml(galleryImages,i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"));
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"))+("\" role=\"button\" tabindex=\"0\" aria-label=\"Open photo album\" loading=\"lazy\" onerror=\"this.onerror=null;this.src='/assets/no-picture.svg'\"><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.representative_image_c23db047",{},"Representative Image")??"Representative Image")+"</span>");
  }else if(listing&&listing.image_url){
    const listingUrl=String(listing.source_url||'');
    const image='<img class="detail-image" src="'+esc(listing.image_url)+'" alt="'+esc(listing.listing_title||i.model||(globalThis.YGCI18n?.t("ui.guitar_c5050e5b",{},"Guitar")??"Guitar"))+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(listingUrl)out+='<a class="detail-image-link" href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+image+("</a><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.source_c707ee4e",{},"Source:")??"Source:")+" "+"<a href=\"")+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(listing.source_site||(globalThis.YGCI18n?.t("ui.source_0e570ca6",{},"Source")??"Source")))+'</a></span>';
    else out+=image+("<span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.listing_claim_9837a144",{},"Listing Claim")??"Listing Claim")+"</span>");
  }else{
    out+=("<img class=\"detail-image\" src=\"/assets/no-picture.svg\" alt=\"No picture\" data-i18n-alt=\"ui.no_picture_6e9a17ba\"><span class=\"detail-source\">"+(globalThis.YGCI18n?.html("ui.no_picture_b2e8e688",{},"No Picture")??"No Picture")+"</span>");
  }

  currentAdminClaims=claims||[];
  out+=YGCProductDetail.render({individual:i,specifications:currentSpecifications||[],image:'',
    owner:currentSnapshotOwnerHtml(i),location:currentLocationHtml(i),
    chronicleAction:("<div class=\"chronicle-toolbar\"><button type=\"button\" class=\"secondary observation-decision-action\" onclick=\"openObservationDiagnostic()\">"+(globalThis.YGCI18n?.html("detail.observation_decision",{},"Observation decision")??"Observation decision")+"</button></div>"),
    headerAction:'<div class="toolbar admin-detail-actions"><button data-ui-action="danger" class="danger" onclick="deleteIndividual('+i.id+(")\">"+(globalThis.YGCI18n?.html("ui.delete_individual_54ca0297",{},"Delete Individual")??"Delete Individual")+"</button></div>"),
    fieldLabel:specificationFieldLabel,escape:esc});
  document.getElementById('detail').innerHTML=out;
  renderAdminChronicle();
}
async function moderateClaim(claimId,action,isListing=false){
  closeAdminClaim();
  const message=action==='delete'?(isListing?(globalThis.YGCI18n?.t("ui.delete_this_listing_claim_if_it_is_the_last_listing_the_gu_59e1670d",{},"Delete this Listing Claim? If it is the last Listing, the guitar and all related records will also be deleted. Continue?")??"Delete this Listing Claim? If it is the last Listing, the guitar and all related records will also be deleted. Continue?"):(globalThis.YGCI18n?.t("ui.delete_this_claim_and_any_paired_ownership_history_continu_d9606cff",{},"Delete this Claim and any paired ownership history? Continue?")??"Delete this Claim and any paired ownership history? Continue?")):(globalThis.YGCI18n?.t("ui.claim_e070520d",{},"Claim #")??"Claim #")+claimId+' will be set to '+action+" "+(globalThis.YGCI18n?.t("ui.by_the_administrator_and_guitar_data_will_be_recalculated__9d70fe01",{},"by the administrator, and guitar data will be recalculated. Continue?")??"by the administrator, and guitar data will be recalculated. Continue?");
  if(!confirm(message)){if(selectedIndividualId)await showIndividual(selectedIndividualId);return}
  try{
    const d=await jfetch('/api/admin/claims/'+claimId+'/moderate',{method:'POST',headers:{'Content-Type':'application/json','X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},body:JSON.stringify({action,confirm_individual_delete:action==='delete'&&isListing})});
    if(d.individual_deleted){selectedIndividualId=null;document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.individual_deleted_714cdccc",{},"Individual deleted.")??"Individual deleted.")}else if(selectedIndividualId===Number(d.individual_id))await showIndividual(d.individual_id);
    await loadIndividuals();
    await loadStatistics();
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.admin_action_failed_f0183a57",{},"Admin action failed.")??"Admin action failed.")+"\n"+e.message);
    if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }
}
async function deleteIndividual(individualId){
  const individual=individuals.find(x=>Number(x.id)===Number(individualId));
  const label=individual?(individual.manufacturer+' '+(individual.model||'')+' / '+(individual.serial_number||'')):((globalThis.YGCI18n?.t("ui.individual_056c49a5",{},"Individual #")??"Individual #")+individualId);
  if(!confirm(label+" "+(globalThis.YGCI18n?.t("ui.and_all_related_claims_observations_and_ownership_links_wi_2d2f0236",{},"and all related Claims, Observations, and ownership links will be permanently deleted.\n\nThis action cannot be undone. Continue?")??"and all related Claims, Observations, and ownership links will be permanently deleted.\n\nThis action cannot be undone. Continue?")))return;
  const typed=prompt((globalThis.YGCI18n?.t("ui.type_delete_to_confirm_1f644ad5",{},"Type DELETE to confirm.")??"Type DELETE to confirm."));
  if(typed!=='DELETE')return;
  try{
    await jfetch('/api/individuals/'+individualId,{method:'DELETE',headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    if(selectedIndividualId===Number(individualId))selectedIndividualId=null;
    document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.individual_deleted_714cdccc",{},"Individual deleted.")??"Individual deleted.");
    await loadIndividuals();
    await loadStatistics();
    if(activeUser&&activeUser.user)await loadActiveUser();
  }catch(e){
    alert((globalThis.YGCI18n?.t("ui.could_not_delete_the_individual_7545c85f",{},"Could not delete the Individual.")??"Could not delete the Individual.")+"\n"+e.message);
  }
}
async function startBackfill(){if(!confirm((globalThis.YGCI18n?.t("ui.fetch_existing_reverb_listings_again_to_fill_missing_listi_b002ffbd",{},"Fetch existing Reverb Listings again to fill missing Listing Claim details. Observations will not change. Continue?")??"Fetch existing Reverb Listings again to fill missing Listing Claim details. Observations will not change. Continue?")))return;try{const d=await jfetch('/api/backfill-metadata',{method:'POST'});YGCOverlays.close('manualCrawlDialog');YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollJob(d.job_id)}catch(e){alert(e.message)}}
async function startCrawl(){const queries=document.getElementById('queries').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const minValue=document.getElementById('yearMin').value;const maxValue=document.getElementById('yearMax').value;const body={queries,limit:Number(document.getElementById('limit').value),workers:Number(document.getElementById('workers').value),year_min:minValue?Number(minValue):null,year_max:maxValue?Number(maxValue):null};const btn=document.getElementById('crawlBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});YGCOverlays.close('manualCrawlDialog');YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollJob(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
function programRequest(){return {category:document.getElementById('programCategory').value,year_min:Number(document.getElementById('programYearMin').value),year_max:Number(document.getElementById('programYearMax').value)}}
function crawlStageSummary(c){
  const n=key=>Number(c[key]||0);
  return [
    [(globalThis.YGCI18n?.t("ui.listing_review_dedc6ca7",{},"Listing review")??"Listing review"),n('summaries_processed')+' / 2000',(globalThis.YGCI18n?.t("ui.brand_new_excluded_88620c14",{},"Brand New excluded")??"Brand New excluded")+" "+n('skipped_new')+' / Known IDs '+n('skipped_existing')+' / Wrong category '+n('skipped_category')+' / Outside year range '+n('skipped_year')+' / No detail URL '+n('missing_detail_url')],
    [(globalThis.YGCI18n?.t("ui.detail_fetch_53418b13",{},"Detail fetch")??"Detail fetch"),n('details_fetched'),(globalThis.YGCI18n?.t("ui.category_and_year_matched_3a2c02c6",{},"Category and year matched")??"Category and year matched")+" "+n('detail_scope_matched')+' / Detail unavailable '+n('detail_unavailable')],
    [(globalThis.YGCI18n?.t("ui.maker_and_serial_extraction_070be7e6",{},"Maker and serial extraction")??"Maker and serial extraction"),n('serial_candidates'),(globalThis.YGCI18n?.t("ui.serial_or_maker_unknown_7258e2c9",{},"Serial or maker unknown")??"Serial or maker unknown")+" "+n('missing_identity')],
    [(globalThis.YGCI18n?.t("ui.match_existing_guitars_13eb81d9",{},"Match existing guitars")??"Match existing guitars"),n('candidate_checked')+' / '+n('candidate_total'),(globalThis.YGCI18n?.t("ui.needs_review_07297fa9",{},"Needs review")??"Needs review")+" "+n('ambiguous_matches')],
    ['DB registration',n('new_individuals')+' new / '+n('existing_individuals_extended')+' history updated',(globalThis.YGCI18n?.t("ui.create_listing_claim_for_new_guitars_dd96fce4",{},"Create Listing Claim for new guitars")??"Create Listing Claim for new guitars")]
  ];
}
function renderCrawlStage(c){
  return '<table><tbody>'+crawlStageSummary(c).map(row=>'<tr><th>'+esc(row[0])+'</th><td>'+esc(row[1])+'</td><td class="sub">'+esc(row[2])+'</td></tr>').join('')+'</tbody></table>';
}
let crawlLogLoading=false;
const consoleCrawlJobs=new Map();
function renderActiveCrawlJobs(){
  const jobs=new Map((typeof operationsData!=='undefined'&&operationsData?operationsData.jobs:[]).map(j=>[j.id,j]));
  for(const [id,job] of consoleCrawlJobs)jobs.set(id,job);
  document.getElementById('crawlActiveJobs').innerHTML=[...jobs.values()].filter(j=>j.status==='running').map(j=>'<div class="panel"><strong>'+esc(j.message||(globalThis.YGCI18n?.t("ui.crawl_running_3d657b01",{},"Crawl running")??"Crawl running"))+'</strong><div class="progress"><div class="bar" style="width:'+Math.max(0,Math.min(100,Number(j.progress||0)*100))+'%"></div></div>'+(j.stage_counts?renderCrawlStage(j.stage_counts):'')+'</div>').join('');
}
function crawlRunSummary(r){
  const c=r.counts||{};
  const text=(key,params,fallback)=>globalThis.YGCI18n?.t(key,params,fallback)??fallback;
  if(c.target_claims!==undefined){
    const target=Number(c.target_claims),updated=Number(c.claims_updated||0);
    return text('crawl.summary.claims',{target,updated},'Target Claims '+target+' / updated '+updated);
  }
  const newGuitars=Number(c.new_individuals||0),history=Number(c.existing_individuals_extended||0),review=Number(c.ambiguous_matches||0);
  if(c.cached_processed!==undefined){
    const saved=Number(c.cached_processed),skipped=Number(c.skipped_scope||0);
    return text('crawl.summary.cached',{saved,newGuitars,history,review,skipped},'Saved details '+saved+' / new guitars '+newGuitars+' / history updated '+history+' / Needs review '+review+' / skipped '+skipped);
  }
  if(!Object.keys(c).length){
    const listings=Number(r.pages_discovered||0),fetched=Number(r.pages_fetched||0),registered=Number(r.observations_created||0);
    return text('crawl.summary.legacy',{listings,fetched,registered},'Listings '+listings+' / fetched '+fetched+' / registered '+registered);
  }
  const listings=Number(c.summaries_processed??c.summaries_fetched??0),details=Number(c.details_fetched||0);
  return text('crawl.summary.current',{listings,details,newGuitars,history,review},'Listings '+listings+' / details '+details+' / new guitars '+newGuitars+' / history updated '+history+' / Needs review '+review);
}
function crawlRunDetails(r,expanded){
  const counts=r.counts||{};
  const rows=Object.entries(counts).filter(([key,value])=>typeof value==='number').map(([key,value])=>'<tr><th>'+esc(key.replaceAll('_',' '))+'</th><td>'+Number(value)+'</td></tr>').join('');
  const samples=(counts.rejected_samples||[]).map(x=>'#'+x.listing_id+' '+x.reason+' / '+(x.category||x.product_type||(globalThis.YGCI18n?.t("ui.unknown_category_fec911f5",{},"Unknown category")??"Unknown category"))).join(' · ');
  if(!rows&&!samples)return '';
  return '<details data-run="'+Number(r.id)+'" '+(expanded.has(String(r.id))?'open':'')+("><summary>"+(globalThis.YGCI18n?.html("ui.details_45989de4",{},"Details")??"Details")+"</summary><table><tbody>")+rows+'</tbody></table>'+(samples?'<p>'+esc(samples)+'</p>':'')+'</details>';
}
async function loadCrawlRunLog(){
  renderActiveCrawlJobs();
  if(crawlLogLoading)return;
  crawlLogLoading=true;
  const el=document.getElementById('crawlRunLog');
  try{
    const runs=await jfetch('/api/crawl/program/runs');
    const names={electric_acoustic:(globalThis.YGCI18n?.t("ui.electric_acoustic_crawl_9e9ba55a",{},"Electric + Acoustic Crawl")??"Electric + Acoustic Crawl"),electric:(globalThis.YGCI18n?.t("ui.electric_crawl_ddfd847a",{},"Electric Crawl")??"Electric Crawl"),acoustic:(globalThis.YGCI18n?.t("ui.acoustic_crawl_31f70c11",{},"Acoustic Crawl")??"Acoustic Crawl"),manual:(globalThis.YGCI18n?.t("ui.manual_crawl_277bd334",{},"Manual Crawl")??"Manual Crawl"),cache_reprocess:(globalThis.YGCI18n?.t("ui.saved_details_reprocessing_3324269d",{},"Saved details reprocessing")??"Saved details reprocessing"),metadata_backfill:(globalThis.YGCI18n?.t("ui.listing_metadata_backfill_5e83ced7",{},"Listing metadata backfill")??"Listing metadata backfill")};
    const expanded=new Set([...el.querySelectorAll('details[open]')].map(d=>d.dataset.run));
    el.innerHTML=runs.length?runs.map(r=>'<div class="panel"><strong>#'+Number(r.id)+' '+esc(names[r.category]||(globalThis.YGCI18n?.t("ui.crawl_62de9915",{},"Crawl")??"Crawl"))+' / '+esc(r.status)+'</strong><div class="sub">'+esc(new Date(r.started_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US'))+(r.year_min!=null?' / '+Number(r.year_min)+'–'+Number(r.year_max):'')+(r.counts?.query?' / '+esc(r.counts.query):'')+' / '+esc(r.phase||'legacy')+'</div><div>'+esc(crawlRunSummary(r))+'</div>'+crawlRunDetails(r,expanded)+(r.error_message?'<div class="status bad">'+esc(r.error_message)+'</div>':'')+'</div>').join(''):(globalThis.YGCI18n?.t("ui.no_crawl_runs_yet_2e2c2b33",{},"No crawl runs yet.")??"No crawl runs yet.");
  }catch(e){el.textContent=e.message}
  finally{crawlLogLoading=false}
}
function openManualCrawl(){YGCOverlays.open('manualCrawlDialog')}
function openConsoleBackups(){YGCOverlays.open('consoleBackupsDialog');loadCrawlBackups()}
function openDatabaseMaintenance(){YGCOverlays.open('databaseMaintenanceDialog')}
function openStatistics(){YGCOverlays.open('statisticsDialog');loadStatistics()}
function openPendingAcquireClaims(){YGCOverlays.open('pendingAcquireClaimsDialog');loadUnverifiedAcquires(0)}
async function loadCrawlProgram(){const q=programRequest();if(!q.year_min||!q.year_max||q.year_min>q.year_max){document.getElementById('programState').textContent=(globalThis.YGCI18n?.t("ui.check_the_manufacture_year_range_046c667d",{},"Check the manufacture year range")??"Check the manufacture year range");return}try{const d=await jfetch('/api/crawl/program?'+new URLSearchParams(q));document.getElementById('programState').textContent=(globalThis.YGCI18n?.t("ui.listings_processed_22d752cb",{},"Listings processed")??"Listings processed")+" "+d.processed+'  / '+(d.finished?(globalThis.YGCI18n?.t("ui.end_of_pages_for_this_range_44b27acf",{},"End of pages for this range")??"End of pages for this range"):(globalThis.YGCI18n?.t("ui.can_resume_7790f772",{},"Can resume")??"Can resume"))+(d.updated_at?' / Last run '+d.updated_at:'');await loadCrawlRunLog()}catch(e){document.getElementById('programState').textContent=e.message}}
async function advanceCrawlProgram(){const q=programRequest();const btn=document.getElementById('programBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl/advance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)});pollCrawlProgram(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollConsoleCrawlJob(id,buttonId){
  try{
    const job=await jfetch('/api/jobs/'+id);
    consoleCrawlJobs.set(id,job);
    await loadCrawlRunLog();
    if(job.status==='running'){setTimeout(()=>pollConsoleCrawlJob(id,buttonId),1000);return}
    document.getElementById(buttonId).disabled=false;
    document.getElementById('crawlLogStatus').textContent=job.status==='error'?(globalThis.YGCI18n?.t("ui.failed_89e0c2f7",{},"Failed:")??"Failed:")+" "+(job.error||job.message):(job.message||(globalThis.YGCI18n?.t("ui.complete_143b270a",{},"Complete")??"Complete"));
    await loadCrawlProgram();await loadIndividuals();await loadStatistics();
  }catch(e){document.getElementById(buttonId).disabled=false;document.getElementById('crawlLogStatus').textContent=e.message}
}
async function pollCrawlProgram(id){return pollConsoleCrawlJob(id,'programBtn')}
async function pollJob(id){return pollConsoleCrawlJob(id,'crawlBtn')}
async function reprocessCachedDetails(){const btn=document.getElementById('cacheReprocessBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl/cache/reprocess',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(programRequest())});YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollCachedDetails(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollCachedDetails(id){return pollConsoleCrawlJob(id,'cacheReprocessBtn')}
async function loadReviewCandidates(){try{const rows=await jfetch('/api/crawl/candidates/review');document.getElementById('reviewCandidates').innerHTML=rows.length?rows.map(x=>'<div>'+esc(x.manufacturer)+' '+esc(x.model)+' / '+esc(x.serial_number)+' / Listing #'+esc(x.listing_id)+' / '+esc(x.reason)+'</div>').join(''):(globalThis.YGCI18n?.t("ui.no_candidates_for_review_7d1e0a11",{},"No candidates for review")??"No candidates for review")}catch(e){document.getElementById('reviewCandidates').textContent=e.message}}
function scrollConsoleLayer(id){
  const target=document.getElementById(id);
  if(!target?.closest)return;
  const layer=target.closest('.console-main-layer,.console-detail-layer');
  if(!layer)return;
  const offset=target.getBoundingClientRect().top-layer.getBoundingClientRect().top;
  layer.scrollTo({top:layer.scrollTop+offset-parseFloat(getComputedStyle(layer).paddingTop||0),behavior:'auto'});
}
const header=document.querySelector('.sticky-header');
new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',header.offsetHeight+'px')).observe(header);
window.YGCPageReady=(async()=>{try{await refreshStatus();await loadIndividuals();await loadStatistics();await loadUsers();await loadCrawlProgram();await loadProductionAcquires()}catch(e){document.getElementById('tokenState').textContent=e.message}})()

let operationsData=null;
let operationSelection='status';
let operationsLoading=false;
function selectOperation(name,button){
  operationSelection=name;
  document.querySelectorAll('.operations-menu button').forEach(b=>{b.setAttribute('aria-selected',String(b===button));b.tabIndex=b===button?0:-1});
  document.getElementById('operationsDetail').setAttribute('aria-labelledby',button.id);
  renderOperationsDetail();
}
async function loadOperations(){
  if(operationsLoading)return;
  operationsLoading=true;
  try{
    operationsData=await jfetch('/api/admin/operations');
    const interval=document.getElementById('autoCrawlIntervalHours');
    if(!interval.dataset.loaded){interval.value=operationsData.auto_crawl.interval_seconds/3600;interval.dataset.loaded='true'}
    document.getElementById('operationsStatus').textContent=({normal:(globalThis.YGCI18n?.t("ui.normal_a7248eeb",{},"Normal")??"Normal"),read_only:(globalThis.YGCI18n?.t("ui.read_only_8ac76735",{},"Read only")??"Read only"),offline:(globalThis.YGCI18n?.t("ui.offline_a1794783",{},"Offline")??"Offline")})[operationsData.settings.mode]||operationsData.settings.mode;
    document.getElementById('operationsCheckedAt').textContent=(globalThis.YGCI18n?.t("ui.last_checked_b133524e",{},"Last checked:")??"Last checked:")+" "+new Date(operationsData.checked_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US');
    // Preserve unsaved maintenance edits during automatic refresh.
    if(operationSelection!=='maintenance'||!document.getElementById('operationsMode'))renderOperationsDetail();
    await loadCrawlRunLog();
  }catch(e){document.getElementById('operationsStatus').textContent=(globalThis.YGCI18n?.t("ui.status_unavailable_e32845a4",{},"Status unavailable:")??"Status unavailable:")+" "+e.message}
  finally{operationsLoading=false}
}
function renderOperationsDetail(){
  const el=document.getElementById('operationsDetail'),d=operationsData;
  if(!d){el.textContent=(globalThis.YGCI18n?.t("ui.refresh_to_load_operations_ddf604a6",{},"Refresh to load operations.")??"Refresh to load operations.");return}
  const rows=items=>'<table><tbody>'+items.map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+esc(v)+'</td></tr>').join('')+'</tbody></table>';
  if(operationSelection==='status')el.innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.service_status_cce5eda3",{},"Service status")??"Service status")+"</h3>")+rows([[(globalThis.YGCI18n?.t("ui.web_process_1549c7be",{},"Web process")??"Web process"),(globalThis.YGCI18n?.t("ui.responding_98047c1e",{},"Responding")??"Responding")],[(globalThis.YGCI18n?.t("ui.database_fa7fe671",{},"Database")??"Database"),d.database],[(globalThis.YGCI18n?.t("ui.media_directory_cd9fff51",{},"Media directory")??"Media directory"),d.media_directory],[(globalThis.YGCI18n?.t("ui.service_mode_b4e3ac32",{},"Service mode")??"Service mode"),d.settings.mode],[(globalThis.YGCI18n?.t("ui.process_uptime_777077c2",{},"Process uptime")??"Process uptime"),d.uptime_seconds+' seconds'],[(globalThis.YGCI18n?.t("ui.last_checked_0c0c351a",{},"Last checked")??"Last checked"),new Date(d.checked_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US')]])+("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.storage_reachability_does_not_verify_upload_download_succe_17564a0f",{},"Storage reachability does not verify upload/download success. Reverb and AI connectivity are not probed.")??"Storage reachability does not verify upload/download success. Reverb and AI connectivity are not probed.")+"</p>");
  if(operationSelection==='maintenance'){
    el.innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.maintenance_17ccfa5b",{},"Maintenance")??"Maintenance")+"</h3><form class=\"operations-form\" onsubmit=\"saveOperations(event)\"><label>"+(globalThis.YGCI18n?.html("ui.service_mode_b4e3ac32",{},"Service mode")??"Service mode")+"<select id=\"operationsMode\" onchange=\"setMaintenanceMessage(this.value)\"><option value=\"normal\">"+(globalThis.YGCI18n?.html("ui.normal_a7248eeb",{},"Normal")??"Normal")+"</option><option value=\"read_only\">"+(globalThis.YGCI18n?.html("ui.read_only_block_new_writes_02fb2e6b",{},"Read only — block new writes")??"Read only — block new writes")+"</option><option value=\"offline\">"+(globalThis.YGCI18n?.html("ui.offline_block_public_access_3955845c",{},"Offline — block public access")??"Offline — block public access")+"</option></select></label><label>"+(globalThis.YGCI18n?.html("ui.message_to_users_97162fcd",{},"Message to users")??"Message to users")+"<textarea id=\"operationsMessage\" maxlength=\"1000\"></textarea></label><p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.existing_jobs_continue_settings_persist_after_restart_the__c177c7a9",{},"Existing jobs continue. Settings persist after restart. The Console and these settings remain accessible.")??"Existing jobs continue. Settings persist after restart. The Console and these settings remain accessible.")+"</p><button id=\"operationsSave\" type=\"submit\">"+(globalThis.YGCI18n?.html("ui.save_settings_7f3a3b14",{},"Save settings")??"Save settings")+"</button><p id=\"operationsSaveStatus\" role=\"status\"></p></form>");
    document.getElementById('operationsMode').value=d.settings.mode;
    document.getElementById('operationsMessage').value=d.settings.message||maintenanceMessages[d.settings.mode];
    el.dataset.version=d.settings.version;
  }
  if(operationSelection==='jobs')el.innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.background_jobs_0ec1d8fb",{},"Background jobs")??"Background jobs")+"</h3><h4>"+(globalThis.YGCI18n?.html("ui.crawl_62de9915",{},"Crawl")??"Crawl")+"</h4><label><input id=\"autoCrawlReverb\" type=\"checkbox\" ")+(d.auto_crawl.enabled?'checked ':'')+("onchange=\"toggleAutoCrawl(this)\"> Reverb</label><p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.last_run_f636f90b",{},"Last run:")??"Last run:")+" ")+(d.last_crawl_at?esc(new Date(d.last_crawl_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US')):(globalThis.YGCI18n?.t("ui.never_6300ef80",{},"Never")??"Never"))+'</p><p class="sub">'+esc(d.auto_crawl_message||'')+("</p><p id=\"autoCrawlStatus\" role=\"status\"></p><h4>"+(globalThis.YGCI18n?.html("ui.acquire_listing_review_6923b027",{},"Acquire / Listing review")??"Acquire / Listing review")+"</h4><label><input id=\"chatgptReviewEnabled\" type=\"checkbox\" ")+(d.chatgpt_review.enabled?'checked ':'')+("onchange=\"toggleChatGPTReview(this)\"> ChatGPT</label><p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.last_answer_ada3b039",{},"Last answer:")??"Last answer:")+" ")+(d.last_gpt_answer_at?esc(new Date(d.last_gpt_answer_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US')):(globalThis.YGCI18n?.t("ui.never_6300ef80",{},"Never")??"Never"))+'</p><p id="chatgptReviewStatus" role="status"></p>';
  if(operationSelection==='history')el.innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.operation_history_93bf535e",{},"Operation history")??"Operation history")+"</h3>")+(d.history.length?rows(d.history.map(h=>[new Date(h.occurred_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US')+' · '+h.mode,h.reason])):("<p>"+(globalThis.YGCI18n?.html("ui.no_settings_changes_f5af6ff9",{},"No settings changes.")??"No settings changes.")+"</p>"))+("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.latest_100_changes_by_the_local_console_administrator_b18fecac",{},"Latest 100 changes by the local Console administrator.")??"Latest 100 changes by the local Console administrator.")+"</p>");
  if(operationSelection==='version')el.innerHTML=("<h3>"+(globalThis.YGCI18n?.html("ui.version_and_deployment_4776d967",{},"Version and deployment")??"Version and deployment")+"</h3>")+rows([[(globalThis.YGCI18n?.t("ui.application_version_f0ad2341",{},"Application version")??"Application version"),d.version],[(globalThis.YGCI18n?.t("ui.deployment_870a8ffd",{},"Deployment")??"Deployment"),d.deployment]])+("<p class=\"sub\">"+(globalThis.YGCI18n?.html("ui.cloud_monitoring_backup_automation_and_rollback_controls_a_a6169445",{},"Cloud monitoring, backup automation and rollback controls are not connected.")??"Cloud monitoring, backup automation and rollback controls are not connected.")+"</p>");
}
async function saveOperations(event){
  event.preventDefault();const button=document.getElementById('operationsSave'),status=document.getElementById('operationsSaveStatus');button.disabled=true;
  try{
    await jfetch('/api/admin/operations',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:document.getElementById('operationsMode').value,message:document.getElementById('operationsMessage').value,expected_version:Number(document.getElementById('operationsDetail').dataset.version)})});
    await loadOperations();renderOperationsDetail();document.getElementById('operationsSaveStatus').textContent=(globalThis.YGCI18n?.t("ui.settings_saved_ae493e21",{},"Settings saved.")??"Settings saved.");
  }catch(e){status.textContent=e.message}finally{button.disabled=false}
}
loadOperations();
setInterval(()=>{if(!document.hidden&&document.getElementById('operationsAutoRefresh')?.checked)loadOperations()},15000);

document.querySelectorAll('.page-nav,.ownership-nav').forEach(nav=>nav.addEventListener('click',event=>{
  const link=event.target.closest('a[href^="#"]');if(!link)return;
  event.preventDefault();const id=link.hash.slice(1);scrollConsoleLayer(id);
  if(nav.classList.contains('main-position-links')){
    const detailTarget={'web-crawl':'operations','guitar-db':'product-detail-window',ownership:'product-detail-window','user-db':'user-detail-window'}[id];
    if(detailTarget)scrollConsoleLayer(detailTarget);
  }
  history.replaceState(null,'',link.hash);
}));
document.querySelector('.operations-menu').addEventListener('keydown',event=>{
  if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
  const tabs=[...document.querySelectorAll('.operations-menu [role="tab"]')];
  const index=tabs.indexOf(document.activeElement);if(index<0)return;
  event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  tabs[next].focus();tabs[next].click();
});
if(location.hash)requestAnimationFrame(()=>scrollConsoleLayer(location.hash.slice(1)));

const detailLayer=document.querySelector('.console-detail-layer');
if(detailLayer&&typeof ResizeObserver==='function'){
  const syncDetailWindowHeight=()=>{
    const style=getComputedStyle(detailLayer);
    const height=detailLayer.clientHeight-(parseFloat(style.paddingTop)||0)-(parseFloat(style.paddingBottom)||0);
    detailLayer.style.setProperty('--detail-window-height',Math.max(0,Math.floor(height))+'px');
  };
  new ResizeObserver(syncDetailWindowHeight).observe(detailLayer);
  syncDetailWindowHeight();
}

async function toggleAutoCrawl(checkbox){
  const enabled=checkbox.checked;checkbox.disabled=true;
  try{
    await jfetch('/api/admin/operations/auto-crawl',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled,...programRequest(),interval_seconds:autoCrawlIntervalSeconds()})});
    await loadOperations();
  }catch(e){checkbox.checked=!enabled;document.getElementById('autoCrawlStatus').textContent=e.message}
  finally{checkbox.disabled=false}
}

function autoCrawlIntervalSeconds(){
  const hours=Number(document.getElementById('autoCrawlIntervalHours').value);
  if(!Number.isInteger(hours)||hours<1||hours>168)throw new Error((globalThis.YGCI18n?.t("ui.enter_an_interval_from_1_to_168_hours_99194ab1",{},"Enter an interval from 1 to 168 hours.")??"Enter an interval from 1 to 168 hours."));
  return hours*3600;
}
async function saveAutoCrawlInterval(){
  const status=document.getElementById('autoCrawlIntervalStatus');
  try{
    if(!operationsData)throw new Error((globalThis.YGCI18n?.t("ui.refresh_operations_first_c3acc0dd",{},"Refresh Operations first.")??"Refresh Operations first."));
    await jfetch('/api/admin/operations/auto-crawl',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!operationsData.auto_crawl.enabled,...programRequest(),interval_seconds:autoCrawlIntervalSeconds()})});
    await loadOperations();status.textContent=(globalThis.YGCI18n?.t("ui.interval_saved_e716bcb0",{},"Interval saved.")??"Interval saved.");
  }catch(e){status.textContent=e.message}
}

async function toggleChatGPTReview(checkbox){
  const enabled=checkbox.checked;checkbox.disabled=true;
  try{
    await jfetch('/api/admin/operations/chatgpt-review',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});
    await loadOperations();
  }catch(e){checkbox.checked=!enabled;document.getElementById('chatgptReviewStatus').textContent=e.message}
  finally{checkbox.disabled=false}
}

let backupData=null;
let backupImportTarget='chronicle';
const backupTargetNames={accounts:(globalThis.YGCI18n?.t("ui.user_accounts_067b2320",{},"User Accounts")??"User Accounts"),chronicle:(globalThis.YGCI18n?.t("ui.guitar_chronicle_3405ec2a",{},"Guitar / Chronicle")??"Guitar / Chronicle"),operations:(globalThis.YGCI18n?.t("ui.operations_358cc201",{},"Operations")??"Operations"),authentication:(globalThis.YGCI18n?.t("ui.authentication_experiment_e3f4eb21",{},"Authentication experiment")??"Authentication experiment")};
async function loadCrawlBackups(){
  try{
    backupData=await jfetch('/api/admin/operations/backups');
    renderBackupTarget();
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
}
function renderBackupTarget(){
  if(!backupData)return;
  const target=document.getElementById('backupTarget').value;
  const policy=backupData.policies.find(p=>p.target===target);
  document.getElementById('crawlBackupGenerations').value=policy.generations;
  document.getElementById('backupScheduledEnabled').checked=!!policy.enabled;
  document.getElementById('backupIntervalHours').value=policy.interval_hours;
  document.getElementById('backupScheduleStatus').textContent=(globalThis.YGCI18n?.t("ui.last_save_f50ac3e1",{},"Last save:")??"Last save:")+" "+(policy.last_at?new Date(policy.last_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US')+' / '+policy.last_status:(globalThis.YGCI18n?.t("ui.never_6300ef80",{},"Never")??"Never"))+(policy.last_error?' / '+policy.last_error:'')+(policy.enabled?' · Next scheduled: '+new Date(policy.next_run*1000).toLocaleString(globalThis.YGCI18n?.locale||'en-US'):' · Periodic backup OFF');
  const reasons={crawl:(globalThis.YGCI18n?.t("ui.before_crawl_2a5f3fb2",{},"Before Crawl")??"Before Crawl"),manual:(globalThis.YGCI18n?.t("ui.manual_b0b9fe24",{},"Manual")??"Manual"),scheduled:(globalThis.YGCI18n?.t("ui.scheduled_4724f344",{},"Scheduled")??"Scheduled"),before_restore:(globalThis.YGCI18n?.t("ui.before_restore_1b93945c",{},"Before restore")??"Before restore")};
  const rows=backupData.backups.filter(b=>b.target===target);
  document.getElementById('crawlBackupRows').innerHTML=rows.map(b=>'<tr><td>'+esc(new Date(b.created_at).toLocaleString(globalThis.YGCI18n?.locale||'en-US'))+'</td><td>'+esc(reasons[b.reason]||b.reason)+'</td><td>'+esc((b.size_bytes/1048576).toFixed(1))+' MB</td><td><button class="secondary" onclick="downloadSavedBackup(\''+esc(b.name)+("')\">"+(globalThis.YGCI18n?.html("ui.download_d6eafe82",{},"Download")??"Download")+"</button> <button class=\"secondary\" data-ui-action=\"danger\" onclick=\"restoreCrawlBackup('")+esc(b.name)+("')\">"+(globalThis.YGCI18n?.html("ui.restore_a76e13b9",{},"Restore")??"Restore")+"</button></td></tr>")).join('')||("<tr><td colspan=\"4\">"+(globalThis.YGCI18n?.html("ui.no_saved_backups_for_this_target_4de98f29",{},"No saved backups for this target.")??"No saved backups for this target.")+"</td></tr>");
  document.getElementById('crawlBackupStatus').textContent='';
}
async function saveCrawlBackupRetention(){
  try{
    await jfetch('/api/admin/operations/backups',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:document.getElementById('backupTarget').value,generations:Number(document.getElementById('crawlBackupGenerations').value),enabled:document.getElementById('backupScheduledEnabled').checked,interval_hours:Number(document.getElementById('backupIntervalHours').value)})});
    await loadCrawlBackups();document.getElementById('crawlBackupStatus').textContent=(globalThis.YGCI18n?.t("ui.backup_settings_saved_9cd069dc",{},"Backup settings saved.")??"Backup settings saved.");
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
}
async function saveManualBackup(){
  const button=document.getElementById('saveBackupButton');button.disabled=true;
  try{
    await jfetch('/api/admin/operations/backups/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:document.getElementById('backupTarget').value})});
    await loadCrawlBackups();document.getElementById('crawlBackupStatus').textContent=(globalThis.YGCI18n?.t("ui.backup_saved_44312bc4",{},"Backup saved.")??"Backup saved.");
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
  finally{button.disabled=false}
}
async function downloadSavedBackup(name){
  try{
    const response=await fetch('/api/admin/operations/backups/'+encodeURIComponent(name)+'/download',{headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    if(!response.ok)throw new Error((await response.json()).detail||(globalThis.YGCI18n?.t("ui.download_failed_eae34ccb",{},"Download failed")??"Download failed"));
    const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
}
async function refreshAfterBackupRestore(target){
  if(target==='authentication'){
    directSelectedRevision=null;directSelectedResult=null;
    for(const id of ['directToken','directConfig','directPrompt','directReport','directResult'])document.getElementById(id).value='';
    hideDirectToken();
  }
  await loadCrawlBackups();await loadOperations();
  await Promise.allSettled([loadIndividuals(),loadUsers(),loadProductionAcquires()]);
  document.getElementById('detail').textContent=(globalThis.YGCI18n?.t("ui.select_a_row_in_product_list_to_view_its_history_9833a49b",{},"Select a row in Product List to view its history.")??"Select a row in Product List to view its history.");
  selectedIndividualId=null;
  document.getElementById('crawlBackupStatus').textContent=(globalThis.YGCI18n?.t("ui.backup_restored_maintenance_remains_enabled_bac58812",{},"Backup restored. Maintenance remains enabled.")??"Backup restored. Maintenance remains enabled.");
}
async function restoreCrawlBackup(name){
  const backup=backupData?.backups.find(b=>b.name===name);
  if(!confirm((globalThis.YGCI18n?.t("ui.restore_a76e13b9",{},"Restore")??"Restore")+" "+(backupTargetNames[backup?.target]||'this target')+(globalThis.YGCI18n?.t("ui.only_this_target_will_be_replaced_its_current_state_will_b_bc29f62e",{},"? Only this target will be replaced. Its current state will be backed up first.")??"? Only this target will be replaced. Its current state will be backed up first.")))return;
  try{
    await jfetch('/api/admin/operations/backups/'+encodeURIComponent(name)+'/restore',{method:'POST'});
    await refreshAfterBackupRestore(backup?.target);
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
}
function openTargetBackupImport(){
  backupImportTarget=document.getElementById('backupTarget').value;
  const input=document.getElementById('targetBackupImportInput');input.value='';input.click();
}
async function restoreTargetBackupFile(input){
  const file=input.files?.[0];if(!file)return;
  if(!confirm((globalThis.YGCI18n?.t("ui.restore_a76e13b9",{},"Restore")??"Restore")+" "+backupTargetNames[backupImportTarget]+' from '+file.name+(globalThis.YGCI18n?.t("ui.only_this_target_will_be_replaced_its_current_state_will_b_bc29f62e",{},"? Only this target will be replaced. Its current state will be backed up first.")??"? Only this target will be replaced. Its current state will be backed up first.")))return;
  try{
    await jfetch('/api/admin/operations/backups/import?target='+encodeURIComponent(backupImportTarget),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    await refreshAfterBackupRestore(backupImportTarget);
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
  finally{input.value=''}
}
const maintenanceMessages={
  normal:(globalThis.YGCI18n?.t("ui.the_service_is_operating_normally_cec584b1",{},"The service is operating normally.")??"The service is operating normally."),
  read_only:(globalThis.YGCI18n?.t("ui.the_service_is_under_maintenance_viewing_is_available_but__029d125d",{},"The service is under maintenance. Viewing is available, but changes are temporarily disabled.")??"The service is under maintenance. Viewing is available, but changes are temporarily disabled."),
  offline:(globalThis.YGCI18n?.t("ui.the_service_is_temporarily_unavailable_for_maintenance_ple_970a0d7b",{},"The service is temporarily unavailable for maintenance. Please try again later.")??"The service is temporarily unavailable for maintenance. Please try again later.")
};
function setMaintenanceMessage(mode){document.getElementById('operationsMessage').value=maintenanceMessages[mode]||''}
