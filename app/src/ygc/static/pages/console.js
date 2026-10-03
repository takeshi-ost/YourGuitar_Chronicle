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
async function jfetch(url,opt={}){const headers=new Headers(opt.headers||{});headers.set('X-YGC-Timezone',Intl.DateTimeFormat().resolvedOptions().timeZone);const token=storedToken();if(token)headers.set('X-Reverb-Token',token);if(CONSOLE_ADMIN_TOKEN)headers.set('X-YGC-Console-Admin',CONSOLE_ADMIN_TOKEN);const r=await fetch(url,{...opt,headers});const d=await r.json().catch(()=>({}));if(!r.ok){const e=new Error(Array.isArray(d.detail)?d.detail.map(e=>e.msg).join(' / '):(d.detail||r.statusText));throw e}return d}
// Remove only credentials saved by the retired inference API UI.
try{for(const provider of ['openai','gemini'])localStorage.removeItem('ygc_authentication_api_key_'+provider)}catch(error){}
let directBusy=false;
let directSelectedRevision=null;
let directSelectedResult=null;
function hideDirectToken(){
  document.getElementById('directToken').type='password';
  const button=document.getElementById('directTokenToggle');
  button.textContent='接続キーを表示';
  button.setAttribute('aria-pressed','false');
  document.getElementById('directTokenStatus').textContent='';
}
function toggleDirectToken(){
  const input=document.getElementById('directToken');
  const button=document.getElementById('directTokenToggle');
  const visible=input.type==='password';
  input.type=visible?'text':'password';
  button.textContent=visible?'接続キーを隠す':'接続キーを表示';
  button.setAttribute('aria-pressed',String(visible));
}
async function copyDirectToken(){
  const input=document.getElementById('directToken');
  const status=document.getElementById('directTokenStatus');
  const token=input.value;
  if(!token){status.textContent='先に「① 画像とテスト申請を準備」を実行してください。';return}
  try{
    await navigator.clipboard.writeText(token);
    if(input.value===token)status.textContent='接続キーをコピーしました。設定のPASTE_TOKENを置き換えてください。';
  }catch(error){
    if(input.value!==token)return;
    if(input.type==='password')toggleDirectToken();
    input.focus();input.select();input.setSelectionRange(0,input.value.length);
    status.textContent='自動コピーを利用できません。キーを表示・選択しました。⌘C（WindowsはCtrl+C）でコピーしてください。';
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
    status.textContent='画像を準備しています…';
    const result=await jfetch('/api/admin/direct-experiment/prepare',{method:'POST',body});
    showDirectConnection(result);
    directSelectedRevision=result.revision;
    directSelectedResult=null;
    const {token,prompt,python,project,...safe}=result;
    document.getElementById('directResult').value=JSON.stringify(safe,null,2);
    status.textContent='申請を追加しました。定期実行で審議されます。';
    await loadDirectQueue();
  }catch(error){status.textContent='準備できませんでした: '+error.message}
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
    status.textContent='ローカル接続診断成功。申請は確保していません。画像閲覧と審議はGPT側で行います。';
  }catch(error){status.textContent='接続診断失敗: '+error.message}
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
    document.getElementById('directStatus').textContent='保存済み接続設定を表示しました。申請・結果は変更していません。';
  }catch(error){document.getElementById('directStatus').textContent='接続設定取得失敗: '+error.message}
  finally{directBusy=false}
}
function directStatusLabel(job){
  return job.status==='completed'?(job.accepted?'True（採用）':'False（不採用）'):
    ({pending:'未処理',processing:'審議中',error:'エラー',cancelled:'取消済み'}[job.status]||job.status);
}
async function loadDirectQueue(){
  const result=await jfetch('/api/admin/direct-experiment');
  const jobs=result.jobs||[];
  document.getElementById('directQueueRows').innerHTML=jobs.map(job=>{
    const revision=esc(job.revision);
    const action=(name,label)=>`<button class="secondary" type="button" data-direct-action="${name}" data-direct-revision="${revision}">${label}</button>`;
    return `<tr><td>${esc(job.application_id)}<br><small>${revision.slice(0,12)}</small></td><td>${esc(directStatusLabel(job))}<br>${esc(job.error||'')}</td><td>${esc(job.created_at)}<br>${esc(job.started_at||'—')}<br>${esc(job.completed_at||'—')}</td><td>${esc(job.attempts)}回 ${action('select','詳細')}${job.status==='error'?action('retry','再試行'):''}${['pending','processing','error'].includes(job.status)?action('cancel','取消'):''}${['completed','cancelled','error'].includes(job.status)?action('delete','削除'):''}</td></tr>`;
  }).join('')||'<tr><td colspan="4">申請はありません。</td></tr>';
  if(directSelectedRevision&&!jobs.some(j=>j.revision===directSelectedRevision))directSelectedRevision=null;
  if(!directSelectedRevision&&jobs.length)directSelectedRevision=jobs[0].revision;
  if(directSelectedRevision){
    const detail=await jfetch('/api/admin/direct-experiment?revision='+encodeURIComponent(directSelectedRevision));
    directSelectedResult=detail;
    document.getElementById('directResult').value=JSON.stringify(detail,null,2);
    document.getElementById('directReport').value=detail.report_text||'';
    document.getElementById('directStatus').textContent=detail.status==='completed'?'暫定採否: '+(detail.result.adjudication.accepted?'True（採用）':'False（不採用）')+'。Claim・所有権の変更なし。':directStatusLabel(detail);
  }else{
    directSelectedResult=null;
    document.getElementById('directResult').value='';document.getElementById('directReport').value='';
    document.getElementById('directStatus').textContent='申請はありません。';
  }
}
async function refreshDirectExperiment(){
  if(directBusy)return;
  directBusy=true;
  try{await loadDirectQueue()}
  catch(error){document.getElementById('directStatus').textContent='一覧取得失敗: '+error.message}
  finally{directBusy=false}
}
async function manageDirectJob(revision,action){
  if(directBusy)return;
  if(['delete','cancel'].includes(action)&&!confirm(action==='delete'?'この実験申請の画像・診断・履歴を削除しますか？':'この実験申請の審議を取り消しますか？'))return;
  directBusy=true;
  try{
    if(action==='select'){directSelectedRevision=revision;directSelectedResult=null;}
    else await jfetch('/api/admin/direct-experiment/jobs/'+encodeURIComponent(revision)+'/'+action,{method:'POST'});
    await loadDirectQueue();
  }catch(error){document.getElementById('directStatus').textContent='操作失敗: '+error.message}
  finally{directBusy=false}
}
function downloadDirectResult(format){
  if(!directSelectedResult){document.getElementById('directStatus').textContent='一覧から申請を選択してください。';return}
  if(format==='txt'&&!directSelectedResult.report_text){document.getElementById('directStatus').textContent='診断文章は未提出です。';return}
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
    document.getElementById('directStatus').textContent='接続キーを失効しました。申請・画像・診断結果は保存されています。';
  }catch(error){document.getElementById('directStatus').textContent='終了できませんでした: '+error.message}
  finally{directBusy=false}
}

let productionAcquires=[],productionSelected=null,productionBusy=false,productionImageUrls=[],productionDetailSequence=0;
const ownershipStates={draft:'Awaiting photos',pending:'Awaiting review',processing:'Under review',error:'Processing error',accepted:'Approved',rejected:'Rejected',cancelled:'Cancelled',closed:'Closed',expired:'Submission expired'};
const ownershipActions={cancel:'Cancel Request',retry:'Queue Another Review',accept:'Override: Approve',reject:'Override: Reject',positive:'Verification → Positive',negative:'Verification → Negative',unverified:'Verification → Unverified'};
async function loadProductionAcquires(){
  try{
    const data=await jfetch('/api/admin/acquire-applications');
    productionAcquires=data.applications;
    document.getElementById('productionAcquirePrompt').value=data.prompt;
    renderProductionAcquires();
    document.getElementById('productionAcquireStatus').textContent='Updated: '+new Date().toLocaleTimeString()+' / '+productionAcquires.length+' requests';
    if(productionSelected){const row=productionAcquires.find(r=>r.revision===productionSelected.revision);if(row)renderProductionAcquireDetail(row)}
  }catch(e){document.getElementById('productionAcquireStatus').textContent='Could not load: '+e.message}
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
    return '<tr><td>'+esc(r.revision.slice(0,12))+'</td><td>'+ownershipDetailLink('user',r.applicant_id,r.applicant_name+' (#'+Number(r.applicant_id)+')')+'</td><td>'+ownershipDetailLink('guitar',guitarId,(r.request_kind==='listing'?'Listing: ':'Acquire: ')+r.product_name+(guitarId?' (#'+Number(guitarId)+')':' (Not registered)'))+'<br>'+esc(r.serial)+'</td><td>'+esc(ownershipStates[r.status]||r.status)+'</td><td>'+esc(r.verification_status||'—')+(r.status==='accepted'&&r.verification_status==='unverified'?'<br>Awaiting owner approval':'')+'</td><td>'+ownershipDetailLink('user',ownerId,ownerId?(ownerName||'User #'+Number(ownerId)):'Unknown')+'</td><td>'+esc(r.submitted_at||r.created_at)+'</td><td><button class="secondary" onclick="inspectProductionAcquire(\''+esc(r.revision)+'\')">Detail</button></td></tr>';
  }).join('')||'<tr><td colspan="8">No matching requests.</td></tr>';
}
function clearProductionImages(){for(const url of productionImageUrls)URL.revokeObjectURL(url);productionImageUrls=[];document.getElementById('productionAcquireImages').innerHTML=''}
function renderProductionAcquireDetail(row){
  productionSelected=row;
  document.getElementById('productionAcquireDetail').value=JSON.stringify(row,null,2);
  const manual=row.admin_review?'<p>Administrator review: '+(row.admin_review.accepted?'Approved':'Rejected')+' — '+esc(row.admin_review.reason)+'</p>':'';
  document.getElementById('productionAcquireSummary').innerHTML='<h3>Request '+esc(row.revision)+'</h3><p>'+esc(ownershipStates[row.status]||row.status)+' / Verification: '+esc(row.verification_status||'Not created')+' / Claim: '+esc(row.claim_id||'—')+'</p><p>Applicant: '+esc(row.applicant_name)+' / Current Owner ID: '+esc(row.current_owner_user_id||'Unknown')+'</p>'+manual+(row.error?'<p>'+esc(row.error)+'</p>':'');
  document.getElementById('productionAcquireActions').innerHTML=(row.admin_actions||[]).map(action=>'<button data-ui-action="'+(['accept','positive'].includes(action)?'primary':action==='cancel'?'danger':'neutral')+'" '+(productionBusy?'disabled ':'')+'class="secondary" onclick="manageProductionAcquire(\''+esc(row.revision)+'\',\''+action+'\')">'+ownershipActions[action]+'</button>').join('');
}
async function inspectProductionAcquire(revision){
  productionSelected=null;
  document.getElementById('productionAcquireSummary').textContent='Loading request…';
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
      if(!response.ok)throw new Error('Could not load image: '+role);
      const blob=await response.blob();if(sequence!==productionDetailSequence)return;
      const url=URL.createObjectURL(blob);productionImageUrls.push(url);
      const figure=document.createElement('figure'),caption=document.createElement('figcaption'),img=document.createElement('img');
      caption.textContent={closeup:'Close-up',overview:'Overview',reference:'Reference'}[role];img.src=url;img.alt=caption.textContent;img.style.cssText='max-width:100%;max-height:320px;object-fit:contain';figure.append(caption,img);document.getElementById('productionAcquireImages').append(figure);
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
  if(!reason){productionActionStatus('Enter a reason for this change. No changes have been made.');document.getElementById('productionAcquireReason').focus();return}
  const impact=operation==='accept'?(productionSelected.request_kind==='listing'?'Create or restore the guitar and Listing, with the applicant as initial owner.':'Create or restore the Acquire. An existing user owner must approve it; otherwise it becomes Positive automatically.'):operation==='reject'?'Set any existing Claim to Negative and recalculate ownership.':operation==='retry'?'Archive the original result and queue another GPT review.':operation==='cancel'?'Results from an in-progress review will no longer be accepted.':'Override Claim verification as an administrator and recalculate ownership.';
  if(!confirm(ownershipActions[operation]+'\n'+impact+'\nReason: '+reason))return;
  productionBusy=true;productionActionStatus('Applying change…');renderProductionAcquireDetail(productionSelected);
  try{
    const row=await jfetch('/api/admin/acquire-applications/'+encodeURIComponent(revision)+'/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation,reason,expected_version:productionSelected.management_version})});
    renderProductionAcquireDetail(row);document.getElementById('productionAcquireReason').value='';
    productionActionStatus('Change applied: '+(ownershipStates[row.status]||row.status)+(row.status==='accepted'&&row.verification_status==='unverified'?' — Awaiting owner approval.':' .'));
    await loadProductionAcquires();await loadIndividuals();await loadUsers();if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }catch(e){productionActionStatus('Could not apply change: '+e.message)}
  finally{productionBusy=false;if(productionSelected)renderProductionAcquireDetail(productionSelected)}
}
async function refreshStatus(){const d=await jfetch('/api/status');const source=d.token_source==='browser'?'saved in browser':(d.token_source==='environment'?'environment':'');document.getElementById('tokenState').innerHTML=d.token_configured?'<span class="status good">Reverb Token OK'+(source?' / '+source:'')+'</span>':'<span class="status bad">Reverb Token not set</span>';const input=document.getElementById('tokenInput');if(document.activeElement!==input){input.value=storedToken();input.placeholder=d.token_source==='environment'?'Set by environment variable (value hidden)':'Enter token'}}
let repeatedGroups=[];
let repeatedBusy=false;
function renderObservationMatrix(d){
  const matrix=d.matrix||{columns:[],rows:[],current:{}};
  const snapshot=matrix.columns.filter(col=>col.group==='individual');
  const specifications=matrix.columns.filter(col=>col.group==='specification');
  const fieldLabel=key=>({manufacturer:'Maker',model:'Model',finish:'Finish',year:'Year',serial_number:'Serial',location_country:'Country',location_region:'Region',current_owner_name:'Current Owner',current_owner_type:'Owner Type',current_owner_user_id:'Owner User ID',current_owner_source_url:'Owner Source URL'})[key]||('Spec · '+key.slice(5).replace(/_/g,' '));
  const formatValue=value=>value===null||value===undefined||value===''?'Blank':String(value);
  const header='<thead><tr><th rowspan="2" style="text-align:left">Claim (oldest first)</th><th colspan="'+snapshot.length+'">Guitar Individual</th>'+(specifications.length?'<th colspan="'+specifications.length+'">Specification</th>':'')+'</tr><tr>'+matrix.columns.map(col=>'<th scope="col">'+esc(fieldLabel(col.key))+'</th>').join('')+'</tr></thead>';
  const rows=matrix.rows.map(row=>{
    const results=[...new Set((row.decisions||[]).map(x=>x.result+(x.reason?' · '+x.reason:'')))].join(' / ');
    const evidences=[...new Set([...(row.decisions||[]).flatMap(x=>(x.evidence||[]).map(e=>e.source_listing_id?(e.source_site+' #'+e.source_listing_id):e.evidence_type)),...(row.specification_evidence?[row.specification_evidence.source_site+' #'+row.specification_evidence.source_listing_id]:[])])];
    const claim='<th scope="row" class="matrix-claim"><strong>#'+Number(row.claim_id)+' · '+esc(row.kind||row.type)+'</strong><small>'+esc((row.occurred_at||'Date unknown').slice(0,10))+' · '+esc(row.author_name||'')+'</small><small>'+esc(row.status)+' / '+esc(row.verification_status)+' · '+esc(results||'—')+'</small>'+(evidences.length?'<small>Evidence: '+esc(evidences.join(', '))+'</small>':'')+'</th>';
    return '<tr>'+claim+matrix.columns.map(col=>{
      const cell=row.cells[col.key];
      if(!cell)return '<td class="matrix-unrelated">—</td>';
      const value=formatValue(cell.value);
      return '<td class="'+(cell.adopted?'matrix-adopted':'matrix-rejected')+'" title="'+(cell.adopted?'Adopted by Observation':'Not adopted for current value')+' · '+esc(value)+'"><span class="matrix-cell-value">'+esc(value)+'</span></td>';
    }).join('')+'</tr>';
  }).join('');
  const footer='<tfoot><tr><th scope="row" class="matrix-claim">Current Guitar Individual</th>'+matrix.columns.map(col=>{
    const mismatch=Object.prototype.hasOwnProperty.call(d.differences||{},col.key);
    const value=Object.prototype.hasOwnProperty.call(matrix.current,col.key)?formatValue(matrix.current[col.key]):'—';
    return '<td class="'+(mismatch?'matrix-mismatch':'')+'" title="'+(mismatch?'Saved value differs from Observation result · ':'')+esc(value)+'"><span class="matrix-cell-value">'+esc(value)+'</span></td>';
  }).join('')+'</tr></tfoot>';
  const mismatches=Object.entries(d.differences||{});
  return '<p class="sub">Individual #'+Number(d.individual_id)+' · '+matrix.rows.length+' Claims · Differences from saved Snapshot: '+mismatches.length+' (read only)</p>'+
    '<p class="sub">Light gray = adopted, dark gray = not adopted, — = not applicable. A blank value proposes clearing a field. The final Specification row shows the current displayed value.</p>'+
    '<div class="observation-matrix-scroll"><table class="observation-matrix" style="width:'+(94+60*matrix.columns.length+matrix.columns.length+1)+'px"><colgroup><col class="matrix-claim-col">'+matrix.columns.map(()=>'<col class="matrix-value-col">').join('')+'</colgroup>'+header+'<tbody>'+rows+'</tbody>'+footer+'</table></div>'+
    (mismatches.length?'<p class="sub">Saved values differ from evaluated values: '+mismatches.map(([key,x])=>esc(fieldLabel(key))+' (saved '+esc(x.saved??'—')+' / evaluated '+esc(x.evaluated??'—')+')').join(' / ')+'</p>':'');
}
async function openObservationDiagnostic(){
  if(!selectedIndividualId){alert('Select a guitar first.');return}
  const dialog=document.getElementById('observationDiagnosticDialog');
  YGCOverlays.open(dialog);
  const body=document.getElementById('observationDiagnosticBody');body.textContent='Loading…';
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
  container.textContent='Loading…';
  try{
    const d=await jfetch('/api/admin/repeated',{headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    repeatedGroups=d.items;
    container.innerHTML=d.items.length?d.items.map((g,n)=>'<section class="panel"><h3>'+esc(g.manufacturer)+' / '+esc(g.serial)+'</h3><div style="overflow:auto"><table><thead><tr><th>Keep</th><th>ID</th><th>Maker / Model</th><th>Year / Serial</th><th>Owner</th><th>Listings / Claims</th></tr></thead><tbody>'+g.items.map(i=>'<tr><td><input type="radio" name="repeated-'+n+'" value="'+Number(i.id)+'" aria-label="Individual '+Number(i.id)+' to keep"></td><td><button class="secondary" onclick="YGCOverlays.close(\'repeatedDialog\');showIndividual('+Number(i.id)+')">#'+Number(i.id)+'</button></td><td>'+esc(i.manufacturer)+' / '+esc(i.model)+'</td><td>'+esc(i.year)+' / '+esc(i.serial_number)+'</td><td>'+esc(i.current_owner_name||'Unknown')+'</td><td>'+Number(i.listing_count)+' / '+Number(i.claim_count)+'</td></tr>').join('')+'</tbody></table></div><div class="modal-actions"><button data-ui-action="danger" onclick="resolveRepeated('+n+',\'merge\')">Merge</button><button data-ui-action="danger" class="danger" onclick="resolveRepeated('+n+',\'delete\')">Delete</button></div></section>').join(''):'No duplicate candidates.';
  }catch(e){container.textContent=e.message}
}
async function resolveRepeated(index,action){
  if(repeatedBusy)return;
  const selected=document.querySelector('input[name="repeated-'+index+'"]:checked');
  if(!selected){alert('Select the guitar to keep.');return}
  const keepId=Number(selected.value), ids=repeatedGroups[index].items.map(i=>Number(i.id));
  const removed=ids.filter(id=>id!==keepId);
  if(!confirm('Keep #'+keepId+' and '+(action==='merge'?'merge the history of ':'permanently delete ')+'#'+removed.join(', #')+(action==='merge'?'. Source Claims that change owner or other state will require review.':'. This also deletes related records and cannot be undone.')+' Continue?'))return;
  if(action==='delete'&&prompt('Type DELETE to confirm.')!=='DELETE')return;
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
async function saveToken(){const token=document.getElementById('tokenInput').value.trim();if(!token){alert('Enter a token.');return}localStorage.setItem(TOKEN_KEY,token);document.getElementById('tokenInput').blur();await refreshStatus()}
async function clearToken(){localStorage.removeItem(TOKEN_KEY);const input=document.getElementById('tokenInput');input.value='';input.blur();await refreshStatus()}
function exportDatabase(){window.location.href='/api/export-db'}
function openDatabaseImport(){const input=document.getElementById('dbImportInput');input.value='';input.click()}
async function importDatabaseFile(input){
  const file=input.files&&input.files[0];
  if(!file)return;
  const message='Replace the current DB and media with the selected backup.\n\n'+file.name+'\n\nA legacy .db file can also be restored, but it does not include media.\n\nBack up the current state first if needed. Continue?';
  if(!confirm(message)){input.value='';return}
  try{
    const d=await jfetch('/api/import-db',{
      method:'POST',
      headers:{'Content-Type':'application/octet-stream'},
      body:file
    });
    individuals=[];
    document.getElementById('detail').textContent='Select a row in Product List to view its history.';
    consoleCrawlJobs.clear();
    document.getElementById('crawlLogStatus').textContent='Backup restored';
    await loadCrawlRunLog();
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    const imported=d.imported_counts||{};
    const media=d.legacy_database?'Legacy DB format (no media)':('Media: '+(d.imported_media_count??0));
    const architecture=await jfetch('/api/claim-architecture-status');
    alert('Backup restored.\nObservations: '+(imported.observations??'')+'\nProduct List: '+(imported.individuals??'')+'\nCrawl Runs: '+(imported.crawl_runs??'')+'\n'+media+'\nClaim Migration: '+(architecture.ready?'Not required':'Required'));
  }catch(e){
    alert('Could not restore the backup.\n'+e.message);
  }finally{
    input.value='';
  }
}
async function runClaimMigration(){
  try{
    const status=await jfetch('/api/claim-architecture-status');
    if(status.ready){
      alert('This DB uses the Claim-centered structure and its Snapshot is current.');
      return;
    }
    const message='Migrate the legacy Observation-centered DB to the Claim-centered structure.\n\nUnmigrated Listing Observations: '+status.unmigrated_listing_observations+'\nIndividuals without Claims: '+status.claimless_individuals+'\n\nExisting Claims will not be duplicated. Continue?';
    if(!confirm(message))return;
    const d=await jfetch('/api/migrate-claims',{method:'POST'});
    const m=d.migration||{};
    const a=d.after||{};
    await refreshStatus();
    await loadIndividuals();
    const r=d.rebuild||{};
    alert('Claim Migration / Snapshot Rebuild complete\nClaims created: '+(m.claims_created??0)+'\nListing items created: '+(m.listing_items_created??0)+'\nMigration snapshots: '+(m.snapshots_rebuilt??0)+'\nAll snapshots rebuilt: '+(r.snapshots_rebuilt??0)+'\nSkipped: '+(r.snapshots_skipped??0)+'\nReady: '+(a.ready?'Yes':'No')+(a.backfill_recommended?'\n\nSome Reverb Listing Claims lack Location data. Next, run "Backfill existing DB (one time)" .':''));
  }catch(e){
    alert('Claim Migration failed.\n'+e.message);
  }
}

async function backfillCachedSpecifications(){
  if(!confirm('Clean incorrect automated Specifications and duplicate Finish values, then add safe specifications from saved details to guitars without a user owner. Continue?'))return;
  const button=document.getElementById('backfillSpecificationsButton');button.disabled=true;
  try{
    const d=await jfetch('/api/admin/backfill-cached-specifications',{method:'POST'});
    await loadIndividuals();
    alert('Specification cleanup and additions complete.\nIncorrect or duplicate Finish fields removed: '+d.corrected_items+'\nClaims cleaned: '+d.corrected_claims+'\nEmpty Claims: '+d.removed_claims+'\nGuitars without a user owner: '+d.ownerless+'\nWith details: '+d.with_detail+'\nClaims created: '+d.created+'\nFields added: '+d.items+'\nNo fields available: '+d.skipped_no_specs+'\nAlready processed: '+d.skipped_existing);
  }catch(e){alert('Could not add Specifications.\n'+e.message)}
  finally{button.disabled=false}
}

async function resetDatabase(){
  const message='Delete all current Observation, Individual, and crawl history and recreate an empty DB.\n\nThis action cannot be undone. Continue?';
  if(!confirm(message))return;
  const typed=prompt('Type RESET to confirm.');
  if(typed!=='RESET'){
    if(typed!==null)alert('The confirmation did not match; action canceled.');
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
    document.getElementById('detail').textContent='Select a row in Product List to view its history.';
    consoleCrawlJobs.clear();
    document.getElementById('crawlLogStatus').textContent='DB reset complete';
    await loadCrawlRunLog();
    sessionStorage.removeItem(ACTIVE_USER_KEY);
    activeUser=null;
    await refreshStatus();
    await loadIndividuals();
    await loadUsers();
    alert('DB reset complete.');
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
    document.getElementById('unverifiedAcquireBody').innerHTML=d.items.map(x=>'<tr class="clickable" onclick="YGCOverlays.close(\'pendingAcquireClaimsDialog\');showIndividual('+Number(x.individual_id)+')"><td>#'+Number(x.claim_id)+'</td><td>'+esc(x.manufacturer)+' '+esc(x.model||'')+'</td><td>'+esc(x.serial_number||'—')+'</td><td>'+esc(x.author_name)+'</td><td>'+esc(x.current_owner_name||'Unknown')+'</td><td>'+esc(x.proposed_owner||x.author_name)+'</td><td>'+esc(x.occurred_at||x.created_at)+'</td></tr>').join('')||'<tr><td colspan="7">No Unverified Acquire Claims.</td></tr>';
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
      ['Product List',s.individuals],
      ['Makers',s.makers],
      ['Models',s.models],
      ['Finishes',s.finishes],
      ['Current Location known',s.located_individuals]
    ].map(x=>'<span>'+esc(x[0])+' <strong>'+esc(x[1]??0)+'</strong></span>').join('')+'</div>';
    const lists='<div class="stats-columns">'+[
      countList('Maker',d.makers),
      countList('Model',d.models),
      countList('Finish',d.finishes),
      countList('Current Country',d.current_countries)
    ].join('')+'</div>';
    document.getElementById('statistics').innerHTML=summary+lists;
  }catch(e){
    document.getElementById('statistics').textContent='Statistics error: '+e.message;
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
  else{selectedUserId=null;activeUser=null;sessionStorage.removeItem(ACTIVE_USER_KEY);updateOpenTopButton();document.getElementById('accountPanel').textContent='Select a user from the list on the left.'}
}
function renderUserList(){
  const filter=document.getElementById('userFilter').value.trim().toLowerCase();
  const matches=users.filter(u=>[u.id,u.display_name,u.account_type,u.ban_status,u.location_country,u.location_region].some(x=>String(x??'').toLowerCase().includes(filter)));
  document.getElementById('userBody').innerHTML=matches.map(u=>'<tr class="clickable'+(selectedUserId===Number(u.id)?' selected':'')+'" onclick="showUserRecord('+Number(u.id)+')"><td class="mono">'+Number(u.id)+'</td><td>'+esc(u.display_name)+'</td><td>'+esc(u.account_type)+'</td><td>'+esc([u.location_country,u.location_region].filter(Boolean).join(' / ')||'—')+'</td><td>'+Number(u.current_guitar_count||0)+'</td></tr>').join('')||'<tr><td colspan="5" class="sub">No matching users.</td></tr>';
  document.getElementById('userCount').textContent=matches.length+' / '+users.length+' users';
}
async function showUserRecord(id){
  scrollConsoleLayer('user-detail-window');
  selectedUserId=Number(id);
  renderUserList();
  updateOpenTopButton();
  const panel=document.getElementById('accountPanel');
  panel.textContent='Loading...';
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
    const meta=[['User ID',u.id],['Joined',u.created_at],['Updated',u.updated_at],['Owned',summary.owned_count||0],['Formerly Owned',summary.former_count||0],['Claims',summary.claim_count||0]];
    if(u.app_user_id)meta.push(['Account ID',u.app_user_id],['Account Status',u.account_disabled?'Disabled':'Active']);
    if(!CONSOLE_ADMIN_TOKEN)meta.push(['Display Name',u.display_name],['Account Type',u.account_type],['BAN Status',u.ban_status||'normal'],['Country',u.location_country||'—'],['City / Region',u.location_region||'—'],['Bio',u.bio||'—'],...['birth','residence','bio','avatar'].map(key=>[key+' Visibility',u[key+'_visibility']||'—']),['Signature Guitar ID',u.signature_individual_id||'—'],['Theme',u.theme||'dark_default']);
    const guitars=data.guitars||[];
    panel.className='';
    panel.innerHTML='<div class="user-detail-header"><img src="/api/users/'+Number(u.id)+'/avatar?viewer_id='+Number(u.id)+'&v='+encodeURIComponent(u.updated_at||'')+'" alt="" onerror="this.onerror=null;this.src=\'/assets/no-icon.svg\'"><div class="user-header-text"><strong>'+esc(u.display_name)+'</strong><span>Account Type: '+esc(u.account_type)+'</span><span>BAN Status: '+esc(u.ban_status||'normal')+'</span></div></div><div class="user-detail-list">'+meta.map(([label,value])=>'<div class="detail-meta-item"><span class="detail-meta-label">'+esc(label)+'</span><span class="detail-meta-value">'+esc(value)+'</span></div>').join('')+'</div>'+
      (CONSOLE_ADMIN_TOKEN?'<form id="adminUserForm" class="admin-user-form" onsubmit="saveAdminUser(event,'+Number(u.id)+')">'+
        '<label>Display Name<input name="display_name" maxlength="120" required value="'+esc(u.display_name)+'"></label>'+
        '<label>Account Type<select name="account_type">'+['user','shop','builder','repairer','organization'].map(x=>'<option value="'+x+'"'+(u.account_type===x?' selected':'')+'>'+x+'</option>').join('')+'</select></label>'+
        '<label>BAN Status<select name="ban_status">'+['normal','silent_ban','ban'].map(x=>'<option value="'+x+'"'+((u.ban_status||'normal')===x?' selected':'')+'>'+x+'</option>').join('')+'</select></label>'+
        '<label>Theme<select name="theme">'+themeOptions.map(theme=>'<option value="'+esc(theme.id)+'"'+((u.theme||'dark_default')===theme.id?' selected':'')+'>'+esc(theme.label)+'</option>').join('')+'</select></label>'+
        '<label>Country<input name="location_country" maxlength="80" value="'+esc(u.location_country||'')+'"></label>'+
        '<label>City / Region<input name="location_region" maxlength="120" value="'+esc(u.location_region||'')+'"></label>'+
        '<label>Bio<textarea name="bio" maxlength="2000">'+esc(u.bio||'')+'</textarea></label>'+
        ['birth','residence','bio','avatar'].map(key=>'<label>'+esc(key)+' Visibility<select name="'+key+'_visibility">'+['Public','Members','Followers','Private'].map(v=>'<option value="'+v+'"'+((u[key+'_visibility']||'Private')===v?' selected':'')+'>'+v+'</option>').join('')+'</select></label>').join('')+
        '<label>Signature Guitar<select name="signature_individual_id"><option value="">None</option>'+guitars.filter(g=>g.ownership_status==='current_owner'||Number(g.individual_id)===Number(u.signature_individual_id)).map(g=>'<option value="'+Number(g.individual_id)+'"'+(Number(u.signature_individual_id)===Number(g.individual_id)?' selected':'')+'>'+esc(g.manufacturer+' '+(g.model||'')+' / '+(g.serial_number||''))+'</option>').join('')+'</select></label>'+
        '<label>Avatar image<input type="file" name="avatar" accept="image/png,image/jpeg,image/webp,image/gif"></label>'+
        '<div class="toolbar"><button data-ui-action="primary" type="submit">Save User</button></div></form>':'')+
      '<div class="toolbar" style="margin-top:12px"><a href="/users/'+Number(u.id)+'?prototype_user_id='+encodeURIComponent(sessionStorage.getItem(ACTIVE_USER_KEY)||'')+'" target="_blank" rel="noopener">User Profile</a></div>'+
      '<div class="detail-section">Guitars <small class="list-item-count">'+guitars.length+' items</small></div><div class="user-guitar-list">'+(guitars.map(g=>'<div class="user-guitar-row"><a href="#guitar-db" onclick="showIndividual('+Number(g.individual_id)+')">'+esc(g.manufacturer)+' '+esc(g.model||'')+' · '+esc(g.serial_number||'—')+'</a><span class="sub">'+esc(g.ownership_status||'')+'</span></div>').join('')||'<div class="sub">No guitars registered.</div>')+'</div>';
    if(selectedIndividualId)showIndividual(selectedIndividualId,false).catch(e=>{
      document.getElementById('detail').textContent='Product Detail error: '+e.message;
    });
  }catch(e){panel.className='sub';panel.textContent='User Detail error: '+e.message}
}
async function saveAdminUser(event,id){
  event.preventDefault();const form=event.currentTarget,fields=new FormData(form);
  const status=String(fields.get('ban_status'));
  if(status!=='normal'&&!confirm('Set this account to '+status+'? Public Claims and guitar data will be recalculated. Continue?'))return;
  const body={};for(const key of ['display_name','account_type','ban_status','theme','location_country','location_region','bio','birth_visibility','residence_visibility','bio_visibility','avatar_visibility']){
    const value=String(fields.get(key)||'').trim();body[key]=value||null;
  }
  body.signature_individual_id=fields.get('signature_individual_id')?Number(fields.get('signature_individual_id')):null;
  const file=fields.get('avatar');const btn=form.querySelector('button[type=submit]');btn.disabled=true;
  try{
    await jfetch('/api/admin/users/'+id,{method:'PATCH',headers:{'Content-Type':'application/json','X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},body:JSON.stringify(body)});
    if(file&&file.size){const avatarData=new FormData();avatarData.set('avatar',file);
      try{await jfetch('/api/users/'+id+'/avatar',{method:'POST',body:avatarData})}
      catch(e){alert('User information was saved, but the avatar could not be updated.\n'+e.message)}
    }
    await loadUsers();await loadIndividuals();if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }catch(e){alert('Could not update the user.\n'+e.message);btn.disabled=false}
}
async function createUser(){
  try{
    const data=await jfetch('/api/users',{method:'POST'});
    const id=String(data.user.id);
    selectedUserId=Number(id);
    await loadUsers();
  }catch(e){alert('Could not create the account.\n'+e.message)}
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
function activeUserOwns(individualId){
  return !!(activeUser&&(activeUser.guitars||[]).some(g=>Number(g.individual_id)===Number(individualId)&&g.ownership_status==='current_owner'));
}
function ownershipControlsHtml(individualId){
  if(!activeUser||!activeUser.user)return '<div class="sub" style="margin-top:10px">Select a user to link an owned guitar.</div>';
  if(activeUserOwns(individualId))return '';
  return '<div class="toolbar" style="margin-top:10px"><button data-ui-action="primary" onclick="linkOwnedGuitar('+individualId+')">Add to owned guitars</button></div>';
}
async function linkOwnedGuitar(individualId){
  if(!activeUser||!activeUser.user)return;
  try{
    activeUser=await jfetch('/api/users/'+activeUser.user.id+'/guitars/'+individualId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ownership_status:'current_owner'})});
    await loadUsers();
    await showIndividual(individualId);
  }catch(e){
    alert('Could not link the owned guitar.\n'+e.message);
  }
}
function normalizeSortValue(value,key){if(key==='id'||key==='claim_count')return Number(value||0);return String(value??'').toLowerCase()}
function setIndividualSort(key){if(individualSortKey===key){individualSortDirection*=-1}else{individualSortKey=key;individualSortDirection=1}renderIndividuals();document.getElementById('individualBody').closest('.table-wrap').scrollTop=0}
function updateSortIndicators(){for(const key of ['id','manufacturer','model','finish','year','serial_number','claim_count']){const el=document.getElementById('sort-'+key);if(el)el.textContent=individualSortKey===key?(individualSortDirection===1?'▲':'▼'):''}}
function renderIndividuals(){const q=document.getElementById('individualFilter').value.toLowerCase();const rows=individuals.filter(x=>[x.manufacturer,x.model,x.finish,x.year,x.serial_number].join(' ').toLowerCase().includes(q)).slice().sort((a,b)=>{const av=normalizeSortValue(a[individualSortKey],individualSortKey);const bv=normalizeSortValue(b[individualSortKey],individualSortKey);if(av<bv)return-1*individualSortDirection;if(av>bv)return 1*individualSortDirection;return Number(a.id)-Number(b.id)});updateSortIndicators();document.getElementById('individualBody').innerHTML=rows.map(x=>'<tr class="clickable" onclick="showIndividual('+x.id+')"><td>'+x.id+'</td><td>'+esc(x.manufacturer)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.finish||'')+'</td><td>'+esc(x.year||'')+'</td><td class="mono">'+esc(x.serial_number)+'</td><td>'+x.claim_count+'</td></tr>').join('')}
function currentSnapshotOwnerHtml(i){if(!i)return '—';const name=String(i.current_owner_name||'').trim();if(!name)return '—';const type=String(i.current_owner_type||'').trim();const listingUrl=String(i.current_owner_source_url||'').trim();const label=type==='shop'?name+' (Shop)':name;if(type==='shop'&&listingUrl)return '<a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>';return esc(label)}
function currentLocationHtml(i){const parts=[i&&i.location_country,i&&i.location_region].filter(Boolean);return parts.length?esc(parts.join(' / ')):'—'}
function productGalleryHtml(images,model){return YGCProductGallery.render(images,model,esc)}
function stepProductGallery(delta){YGCProductGallery.step(delta)}
function openProductAlbum(){YGCProductGallery.open()}
function specificationFieldLabel(value){const labels={body:'Body',bridge:'Bridge',fingerboard:'Fingerboard',frets:'Frets',neck:'Neck',nut:'Nut',pickups:'Pickups',pickguard:'Pickguard',potentiometers:'Potentiometers',tuners:'Tuners',wiring:'Wiring',weight:'Weight',finish:'Finish'};const key=String(value||'').trim();return labels[key]||key.replace(/_/g,' ').replace(/\b\w/g,m=>m.toUpperCase())}
function identityFieldLabel(value){const labels={manufacturer:'Maker',model:'Model',year:'Year',serial_number:'Serial'};return labels[String(value||'')]||String(value||'').replace(/_/g,' ')}
function claimTypeLabel(value){return String(value||'claim').split('_').map(x=>x?x[0].toUpperCase()+x.slice(1):'').join(' ')}
function incidentClaimLabel(c){return c.value_text==='lost'?'Incident Lost':claimTypeLabel(c.value_text||'incident')}
function displayEventDate(value){if(!value)return 'Date unknown';const text=String(value).trim();const direct=text.match(/^(\d{4}-\d{2}-\d{2})$/);if(direct)return direct[1];const d=new Date(text);if(Number.isNaN(d.getTime()))return text;return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function displayInputDate(value){if(!value)return 'Input date unknown';const d=new Date(String(value));return Number.isNaN(d.getTime())?String(value):d.toLocaleString('en-US')}
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
  const type=c.claim_type==='specification'?(c.specification_kind==='repair'?'Repair':'Specification'):(c.claim_type==='ownership'?claimTypeLabel(c.ownership_kind||'acquire'):(c.claim_type==='incident'?incidentClaimLabel(c):(c.claim_type==='event'?claimTypeLabel(c.value_text||'event'):claimTypeLabel(c.claim_type))));
  const eventDate=displayEventDate(c.occurred_at);
  let body='';
  if(c.claim_type==='ownership'){
    const kind=String(c.ownership_kind||'acquire');
    const owner=String(['automation','merged_listing'].includes(c.ownership_source)?(c.value_text||'Unknown'):(c.author_name||'User')).trim()||'User';
    const ownerHtml=['automation','merged_listing'].includes(c.ownership_source)?esc(owner):YGCProductDetail.userLink(c.author_user_id,owner,esc);
    const raw=String(c.observation_raw_text||'');
    const firstLine=(raw.split(/\r?\n/)[0]||'').trim();
    const party=firstLine.startsWith('Previous owner:')
      ? (firstLine.slice('Previous owner:'.length).trim()||'Unknown')
      : 'Unknown';
    if(kind==='lost'){
      body='<div><strong>Reverb listing unavailable. Current owner and location are unknown.</strong></div>';
    }else if(kind==='release'){
      body=c.ownership_source==='automation'
        ? '<div><strong>Reverb listing unavailable. Current owner and location are unknown.</strong></div>'
        : '<div><strong>'+ownerHtml+' released this product.</strong></div>';
    }else if(kind==='transfer'&&c.transfer){
      const t=c.transfer;
      body='<div><strong>'+YGCProductDetail.userLink(t.from_user_id,t.from_name,esc)+' → '+YGCProductDetail.userLink(t.to_user_id,t.to_name,esc)+'</strong></div><div class="claim-memo">Transfer: '+esc(t.state)+'</div>';
      if(t.accepted_at)body+='<div class="claim-memo">Evidence: Accepted by User #'+Number(t.accepted_by_user_id)+' · '+esc(displayInputDate(t.accepted_at))+' · Current Owner at acceptance: User #'+Number(t.current_owner_user_id)+'</div>';
    }else if(kind==='transfer'){
      body='<div><strong>'+esc(party)+' acquired this product from '+ownerHtml+'.</strong></div>';
    }else if(kind!=='acquire'){
      body='<div><strong>Legacy Ownership Claim: '+esc(kind)+'</strong></div>';
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
    if(c.body)body+='<div class="claim-memo">Reason: '+esc(c.body)+'</div>';
  }else if(c.claim_type==='media'){
    const mediaImages=(c.media_images&&c.media_images.length)
      ? c.media_images
      : (c.evidence_media_id?[{id:c.evidence_media_id,url:'/api/media/'+encodeURIComponent(c.evidence_media_id)}]:[]);
    if(mediaImages.length){
      body+='<div class="claim-media-thumbs">'+mediaImages.map(m=>'<img class="claim-evidence-image" width="48" height="48" style="width:48px!important;height:48px!important;max-width:48px!important;max-height:48px!important;object-fit:cover" src="'+esc(m.url)+'" alt="Media Claim image" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">').join('')+'</div>';
    }
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else if(c.claim_type==='listing'){
    const title=c.listing_title||c.body||'Listing observed';
    body='<div><strong>'+esc(title)+'</strong></div>';
    const details=[];
    const listingOwner=String(c.observed_owner_name||'').trim();
    const seller=String(c.seller||'').trim();
    if(listingOwner&&listingOwner!==seller)body+='<div class="claim-memo">Owner: '+YGCProductDetail.userLink(c.observed_owner_user_id,listingOwner,esc)+'</div>';
    if(seller)details.push('Seller: '+seller);
    const location=[c.location_country,c.location_region].filter(Boolean).join(' / ');
    if(location)details.push('Location: '+location);
    const specs=[c.observed_model&&('Model: '+c.observed_model),c.observed_finish&&('Finish: '+c.observed_finish),c.observed_year&&('Year: '+c.observed_year),c.observed_serial_number&&('Serial: '+c.observed_serial_number)].filter(Boolean).join(' / ');
    if(specs)details.push(specs);
    if(details.length)body+='<div class="claim-memo">'+details.map(esc).join('<br>')+'</div>';
    if(c.body&&c.body!==title)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }else{
    if(c.value_text)body+='<div><strong>'+esc(c.value_text)+'</strong></div>';
    if(c.body)body+='<div class="claim-memo">'+esc(c.body)+'</div>';
  }
  if(c.source_site==='reverb'&&c.source_listing_id&&(c.claim_type==='listing'||c.claim_type==='ownership'||c.claim_type==='specification')){
    const id='Reverb ID #'+esc(c.source_listing_id);
    body+='<div class="claim-memo">Evidence: '+(c.source_url?'<a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">'+id+'</a>':id)+'</div>';
  }else if(c.claim_type==='listing'&&c.source_url){
    body+='<div class="claim-memo"><a href="'+esc(c.source_url)+'" target="_blank" rel="noopener noreferrer">Open listing</a></div>';
  }
  if(c.evidence_media_id&&c.claim_type!=='media')body+='<div class="claim-memo"><img class="claim-evidence-image" width="48" height="48" style="width:48px;height:48px;max-width:48px;max-height:48px;object-fit:cover" src="/api/media/'+encodeURIComponent(c.evidence_media_id)+'" alt="Claim evidence" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"></div>';
  const good=String(Number(c.good_count||0)).padStart(2,'0');
  const bad=String(Number(c.bad_count||0)).padStart(2,'0');
  const verification=String(c.verification_status||'positive');
  const moderation='<label>Verification <select aria-label="Claim Verification" style="width:auto" '+(!CONSOLE_ADMIN_TOKEN?'disabled ':'')+'onchange="moderateClaim('+Number(c.id)+',this.value)">'+[['positive','Positive / Approve'],['negative','Negative / Reject'],['unverified','Unverified / Unverified']].map(x=>'<option value="'+x[0]+'" '+(verification===x[0]?'selected':'')+'>'+x[1]+'</option>').join('')+'</select></label>';
  const votes='<div class="claim-votes" style="flex-wrap:wrap"><span class="claim-vote">👍 '+good+'</span><span class="claim-vote">👎 '+bad+'</span>'+moderation+'<button data-ui-action="danger" class="claim-vote danger" '+(!CONSOLE_ADMIN_TOKEN?'disabled ':'')+'onclick="moderateClaim('+Number(c.id)+',\'delete\','+(c.claim_type==='listing')+')">Delete</button></div>';
  return '<div class="claim-card'+claimVisualTypeClass(c)+(c.claim_type==='identity_correction'?' identity-correction-card':'')+'"><div class="claim-head">'+claimHeaderHtml(c,type,eventDate)+'</div><div class="claim-body">'+body+'</div><div class="claim-footer">'+votes+'<div class="claim-footer-meta">'+esc(displayInputDate(c.created_at))+' · By '+YGCProductDetail.userLink(c.author_user_id,c.author_name,esc)+'</div></div></div>';
}
let currentAdminClaims=[];
function renderAdminChronicle(){
  const ordered=YGCProductDetail.orderedClaims(currentAdminClaims);
  const target=document.getElementById('chronicleEntries');
  if(target)target.innerHTML=ordered.length?ordered.map(adminClaimCard).join(''):'<div class="sub">No Claims yet.</div>';
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
    out+=productGalleryHtml(galleryImages,i.model||'Guitar');
  }else if(i.representative_image_url){
    out+='<img class="detail-image" src="'+esc(i.representative_image_url)+'" alt="'+esc(i.model||'Guitar')+'" role="button" tabindex="0" aria-label="Open photo album" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'"><span class="detail-source">Representative Image</span>';
  }else if(listing&&listing.image_url){
    const listingUrl=String(listing.source_url||'');
    const image='<img class="detail-image" src="'+esc(listing.image_url)+'" alt="'+esc(listing.listing_title||i.model||'Guitar')+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src=\'/assets/no-picture.svg\'">';
    if(listingUrl)out+='<a class="detail-image-link" href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+image+'</a><span class="detail-source">Source: <a href="'+esc(listingUrl)+'" target="_blank" rel="noopener noreferrer">'+esc(String(listing.source_site||'Source'))+'</a></span>';
    else out+=image+'<span class="detail-source">Listing Claim</span>';
  }else{
    out+='<img class="detail-image" src="/assets/no-picture.svg" alt="No picture"><span class="detail-source">No Picture</span>';
  }

  currentAdminClaims=claims||[];
  out+=YGCProductDetail.render({individual:i,specifications:currentSpecifications||[],image:'',
    owner:currentSnapshotOwnerHtml(i),location:currentLocationHtml(i),ownership:ownershipControlsHtml(i.id),
    headerAction:'<div class="toolbar admin-detail-actions"><button data-ui-action="danger" class="danger" onclick="deleteIndividual('+i.id+')">Delete Individual</button></div>',
    fieldLabel:specificationFieldLabel,escape:esc});
  document.getElementById('detail').innerHTML=out;
  renderAdminChronicle();
}
async function moderateClaim(claimId,action,isListing=false){
  closeAdminClaim();
  const message=action==='delete'?(isListing?'Delete this Listing Claim? If it is the last Listing, the guitar and all related records will also be deleted. Continue?':'Delete this Claim and any paired ownership history? Continue?'):'Claim #'+claimId+' will be set to '+action+' by the administrator, and guitar data will be recalculated. Continue?';
  if(!confirm(message)){if(selectedIndividualId)await showIndividual(selectedIndividualId);return}
  try{
    const d=await jfetch('/api/admin/claims/'+claimId+'/moderate',{method:'POST',headers:{'Content-Type':'application/json','X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN},body:JSON.stringify({action,confirm_individual_delete:action==='delete'&&isListing})});
    if(d.individual_deleted){selectedIndividualId=null;document.getElementById('detail').textContent='Individual deleted.'}else if(selectedIndividualId===Number(d.individual_id))await showIndividual(d.individual_id);
    await loadIndividuals();
    await loadStatistics();
  }catch(e){
    alert('Admin action failed.\n'+e.message);
    if(selectedIndividualId)await showIndividual(selectedIndividualId);
  }
}
async function deleteIndividual(individualId){
  const individual=individuals.find(x=>Number(x.id)===Number(individualId));
  const label=individual?(individual.manufacturer+' '+(individual.model||'')+' / '+(individual.serial_number||'')):('Individual #'+individualId);
  if(!confirm(label+' and all related Claims, Observations, and ownership links will be permanently deleted.\n\nThis action cannot be undone. Continue?'))return;
  const typed=prompt('Type DELETE to confirm.');
  if(typed!=='DELETE')return;
  try{
    await jfetch('/api/individuals/'+individualId,{method:'DELETE',headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    if(selectedIndividualId===Number(individualId))selectedIndividualId=null;
    document.getElementById('detail').textContent='Individual deleted.';
    await loadIndividuals();
    await loadStatistics();
    if(activeUser&&activeUser.user)await loadActiveUser();
  }catch(e){
    alert('Could not delete the Individual.\n'+e.message);
  }
}
async function startBackfill(){if(!confirm('Fetch existing Reverb Listings again to fill missing Listing Claim details. Observations will not change. Continue?'))return;try{const d=await jfetch('/api/backfill-metadata',{method:'POST'});YGCOverlays.close('manualCrawlDialog');YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollJob(d.job_id)}catch(e){alert(e.message)}}
async function startCrawl(){const queries=document.getElementById('queries').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const minValue=document.getElementById('yearMin').value;const maxValue=document.getElementById('yearMax').value;const body={queries,limit:Number(document.getElementById('limit').value),workers:Number(document.getElementById('workers').value),year_min:minValue?Number(minValue):null,year_max:maxValue?Number(maxValue):null};const btn=document.getElementById('crawlBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});YGCOverlays.close('manualCrawlDialog');YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollJob(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
function programRequest(){return {category:document.getElementById('programCategory').value,year_min:Number(document.getElementById('programYearMin').value),year_max:Number(document.getElementById('programYearMax').value)}}
function crawlStageSummary(c){
  const n=key=>Number(c[key]||0);
  return [
    ['Listing review',n('summaries_processed')+' / 2000','Brand New excluded '+n('skipped_new')+' / Known IDs '+n('skipped_existing')+' / Wrong category '+n('skipped_category')+' / Outside year range '+n('skipped_year')+' / No detail URL '+n('missing_detail_url')],
    ['Detail fetch',n('details_fetched'),'Category and year matched '+n('detail_scope_matched')+' / Detail unavailable '+n('detail_unavailable')],
    ['Maker and serial extraction',n('serial_candidates'),'Serial or maker unknown '+n('missing_identity')],
    ['Match existing guitars',n('candidate_checked')+' / '+n('candidate_total'),'Needs review '+n('ambiguous_matches')],
    ['DB registration',n('new_individuals')+' new / '+n('existing_individuals_extended')+' history updated','Create Listing Claim for new guitars']
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
  document.getElementById('crawlActiveJobs').innerHTML=[...jobs.values()].filter(j=>j.status==='running').map(j=>'<div class="panel"><strong>'+esc(j.message||'Crawl running')+'</strong><div class="progress"><div class="bar" style="width:'+Math.max(0,Math.min(100,Number(j.progress||0)*100))+'%"></div></div>'+(j.stage_counts?renderCrawlStage(j.stage_counts):'')+'</div>').join('');
}
function crawlRunSummary(r){
  const c=r.counts||{};
  if(c.target_claims!==undefined)return 'Target Claims '+Number(c.target_claims)+' / updated '+Number(c.claims_updated||0);
  if(c.cached_processed!==undefined)return 'Saved details '+Number(c.cached_processed)+' / new guitars '+Number(c.new_individuals||0)+' / history updated '+Number(c.existing_individuals_extended||0)+' / Needs review '+Number(c.ambiguous_matches||0)+' / skipped '+Number(c.skipped_scope||0);
  if(!Object.keys(c).length)return 'Listings '+Number(r.pages_discovered||0)+' / fetched '+Number(r.pages_fetched||0)+' / registered '+Number(r.observations_created||0);
  return 'Listings '+Number(c.summaries_processed??c.summaries_fetched??0)+' / details '+Number(c.details_fetched||0)+' / new guitars '+Number(c.new_individuals||0)+' / history updated '+Number(c.existing_individuals_extended||0)+' / Needs review '+Number(c.ambiguous_matches||0);
}
function crawlRunDetails(r,expanded){
  const counts=r.counts||{};
  const rows=Object.entries(counts).filter(([key,value])=>typeof value==='number').map(([key,value])=>'<tr><th>'+esc(key.replaceAll('_',' '))+'</th><td>'+Number(value)+'</td></tr>').join('');
  const samples=(counts.rejected_samples||[]).map(x=>'#'+x.listing_id+' '+x.reason+' / '+(x.category||x.product_type||'Unknown category')).join(' · ');
  if(!rows&&!samples)return '';
  return '<details data-run="'+Number(r.id)+'" '+(expanded.has(String(r.id))?'open':'')+'><summary>Details</summary><table><tbody>'+rows+'</tbody></table>'+(samples?'<p>'+esc(samples)+'</p>':'')+'</details>';
}
async function loadCrawlRunLog(){
  renderActiveCrawlJobs();
  if(crawlLogLoading)return;
  crawlLogLoading=true;
  const el=document.getElementById('crawlRunLog');
  try{
    const runs=await jfetch('/api/crawl/program/runs');
    const names={electric_acoustic:'Electric + Acoustic Crawl',electric:'Electric Crawl',acoustic:'Acoustic Crawl',manual:'Manual Crawl',cache_reprocess:'Saved details reprocessing',metadata_backfill:'Listing metadata backfill'};
    const expanded=new Set([...el.querySelectorAll('details[open]')].map(d=>d.dataset.run));
    el.innerHTML=runs.length?runs.map(r=>'<div class="panel"><strong>#'+Number(r.id)+' '+esc(names[r.category]||'Crawl')+' / '+esc(r.status)+'</strong><div class="sub">'+esc(new Date(r.started_at).toLocaleString())+(r.year_min!=null?' / '+Number(r.year_min)+'–'+Number(r.year_max):'')+(r.counts?.query?' / '+esc(r.counts.query):'')+' / '+esc(r.phase||'legacy')+'</div><div>'+esc(crawlRunSummary(r))+'</div>'+crawlRunDetails(r,expanded)+(r.error_message?'<div class="status bad">'+esc(r.error_message)+'</div>':'')+'</div>').join(''):'No crawl runs yet.';
  }catch(e){el.textContent=e.message}
  finally{crawlLogLoading=false}
}
function openManualCrawl(){YGCOverlays.open('manualCrawlDialog')}
function openConsoleBackups(){YGCOverlays.open('consoleBackupsDialog');loadCrawlBackups()}
function openDatabaseMaintenance(){YGCOverlays.open('databaseMaintenanceDialog')}
function openStatistics(){YGCOverlays.open('statisticsDialog');loadStatistics()}
function openPendingAcquireClaims(){YGCOverlays.open('pendingAcquireClaimsDialog');loadUnverifiedAcquires(0)}
async function loadCrawlProgram(){const q=programRequest();if(!q.year_min||!q.year_max||q.year_min>q.year_max){document.getElementById('programState').textContent='Check the manufacture year range';return}try{const d=await jfetch('/api/crawl/program?'+new URLSearchParams(q));document.getElementById('programState').textContent='Listings processed '+d.processed+'  / '+(d.finished?'End of pages for this range':'Can resume')+(d.updated_at?' / Last run '+d.updated_at:'');await loadCrawlRunLog()}catch(e){document.getElementById('programState').textContent=e.message}}
async function advanceCrawlProgram(){const q=programRequest();const btn=document.getElementById('programBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl/advance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(q)});pollCrawlProgram(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollConsoleCrawlJob(id,buttonId){
  try{
    const job=await jfetch('/api/jobs/'+id);
    consoleCrawlJobs.set(id,job);
    await loadCrawlRunLog();
    if(job.status==='running'){setTimeout(()=>pollConsoleCrawlJob(id,buttonId),1000);return}
    document.getElementById(buttonId).disabled=false;
    document.getElementById('crawlLogStatus').textContent=job.status==='error'?'Failed: '+(job.error||job.message):(job.message||'Complete');
    await loadCrawlProgram();await loadIndividuals();await loadStatistics();
  }catch(e){document.getElementById(buttonId).disabled=false;document.getElementById('crawlLogStatus').textContent=e.message}
}
async function pollCrawlProgram(id){return pollConsoleCrawlJob(id,'programBtn')}
async function pollJob(id){return pollConsoleCrawlJob(id,'crawlBtn')}
async function reprocessCachedDetails(){const btn=document.getElementById('cacheReprocessBtn');btn.disabled=true;try{const d=await jfetch('/api/crawl/cache/reprocess',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(programRequest())});YGCOverlays.close('databaseMaintenanceDialog');scrollConsoleLayer('web-crawl');pollCachedDetails(d.job_id)}catch(e){alert(e.message);btn.disabled=false}}
async function pollCachedDetails(id){return pollConsoleCrawlJob(id,'cacheReprocessBtn')}
async function loadReviewCandidates(){try{const rows=await jfetch('/api/crawl/candidates/review');document.getElementById('reviewCandidates').innerHTML=rows.length?rows.map(x=>'<div>'+esc(x.manufacturer)+' '+esc(x.model)+' / '+esc(x.serial_number)+' / Listing #'+esc(x.listing_id)+' / '+esc(x.reason)+'</div>').join(''):'No candidates for review'}catch(e){document.getElementById('reviewCandidates').textContent=e.message}}
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
(async()=>{try{await refreshStatus();await loadIndividuals();await loadStatistics();await loadUsers();await loadCrawlProgram();await loadProductionAcquires()}catch(e){document.getElementById('tokenState').textContent=e.message}})()

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
    document.getElementById('operationsStatus').textContent=({normal:'Normal',read_only:'Read only',offline:'Offline'})[operationsData.settings.mode]||operationsData.settings.mode;
    document.getElementById('operationsCheckedAt').textContent='Last checked: '+new Date(operationsData.checked_at).toLocaleString();
    // Preserve unsaved maintenance edits during automatic refresh.
    if(operationSelection!=='maintenance'||!document.getElementById('operationsMode'))renderOperationsDetail();
    await loadCrawlRunLog();
  }catch(e){document.getElementById('operationsStatus').textContent='Status unavailable: '+e.message}
  finally{operationsLoading=false}
}
function renderOperationsDetail(){
  const el=document.getElementById('operationsDetail'),d=operationsData;
  if(!d){el.textContent='Refresh to load operations.';return}
  const rows=items=>'<table><tbody>'+items.map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+esc(v)+'</td></tr>').join('')+'</tbody></table>';
  if(operationSelection==='status')el.innerHTML='<h3>Service status</h3>'+rows([['Web process','Responding'],['Database',d.database],['Media directory',d.media_directory],['Service mode',d.settings.mode],['Process uptime',d.uptime_seconds+' seconds'],['Last checked',new Date(d.checked_at).toLocaleString()]])+'<p class="sub">Storage reachability does not verify upload/download success. Reverb and AI connectivity are not probed.</p>';
  if(operationSelection==='maintenance'){
    el.innerHTML='<h3>Maintenance</h3><form class="operations-form" onsubmit="saveOperations(event)"><label>Service mode<select id="operationsMode" onchange="setMaintenanceMessage(this.value)"><option value="normal">Normal</option><option value="read_only">Read only — block new writes</option><option value="offline">Offline — block public access</option></select></label><label>Message to users<textarea id="operationsMessage" maxlength="1000"></textarea></label><p class="sub">Existing jobs continue. Settings persist after restart. The Console and these settings remain accessible.</p><button id="operationsSave" type="submit">Save settings</button><p id="operationsSaveStatus" role="status"></p></form>';
    document.getElementById('operationsMode').value=d.settings.mode;
    document.getElementById('operationsMessage').value=d.settings.message||maintenanceMessages[d.settings.mode];
    el.dataset.version=d.settings.version;
  }
  if(operationSelection==='jobs')el.innerHTML='<h3>Background jobs</h3><h4>Crawl</h4><label><input id="autoCrawlReverb" type="checkbox" '+(d.auto_crawl.enabled?'checked ':'')+'onchange="toggleAutoCrawl(this)"> Reverb</label><p class="sub">Last run: '+(d.last_crawl_at?esc(new Date(d.last_crawl_at).toLocaleString()):'Never')+'</p><p class="sub">'+esc(d.auto_crawl_message||'')+'</p><p id="autoCrawlStatus" role="status"></p><h4>Acquire / Listing review</h4><label><input id="chatgptReviewEnabled" type="checkbox" '+(d.chatgpt_review.enabled?'checked ':'')+'onchange="toggleChatGPTReview(this)"> ChatGPT</label><p class="sub">Last answer: '+(d.last_gpt_answer_at?esc(new Date(d.last_gpt_answer_at).toLocaleString()):'Never')+'</p><p id="chatgptReviewStatus" role="status"></p>';
  if(operationSelection==='history')el.innerHTML='<h3>Operation history</h3>'+(d.history.length?rows(d.history.map(h=>[new Date(h.occurred_at).toLocaleString()+' · '+h.mode,h.reason])):'<p>No settings changes.</p>')+'<p class="sub">Latest 100 changes by the local Console administrator.</p>';
  if(operationSelection==='version')el.innerHTML='<h3>Version and deployment</h3>'+rows([['Application version',d.version],['Deployment',d.deployment]])+'<p class="sub">Cloud monitoring, backup automation and rollback controls are not connected.</p>';
}
async function saveOperations(event){
  event.preventDefault();const button=document.getElementById('operationsSave'),status=document.getElementById('operationsSaveStatus');button.disabled=true;
  try{
    await jfetch('/api/admin/operations',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:document.getElementById('operationsMode').value,message:document.getElementById('operationsMessage').value,expected_version:Number(document.getElementById('operationsDetail').dataset.version)})});
    await loadOperations();renderOperationsDetail();document.getElementById('operationsSaveStatus').textContent='Settings saved.';
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
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
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
  if(!Number.isInteger(hours)||hours<1||hours>168)throw new Error('Enter an interval from 1 to 168 hours.');
  return hours*3600;
}
async function saveAutoCrawlInterval(){
  const status=document.getElementById('autoCrawlIntervalStatus');
  try{
    if(!operationsData)throw new Error('Refresh Operations first.');
    await jfetch('/api/admin/operations/auto-crawl',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!operationsData.auto_crawl.enabled,...programRequest(),interval_seconds:autoCrawlIntervalSeconds()})});
    await loadOperations();status.textContent='Interval saved.';
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
const backupTargetNames={accounts:'User Accounts',chronicle:'Guitar / Chronicle',operations:'Operations',authentication:'Authentication experiment'};
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
  document.getElementById('backupScheduleStatus').textContent='Last save: '+(policy.last_at?new Date(policy.last_at).toLocaleString()+' / '+policy.last_status:'Never')+(policy.last_error?' / '+policy.last_error:'')+(policy.enabled?' · Next scheduled: '+new Date(policy.next_run*1000).toLocaleString():' · Periodic backup OFF');
  const reasons={crawl:'Before Crawl',manual:'Manual',scheduled:'Scheduled',before_restore:'Before restore'};
  const rows=backupData.backups.filter(b=>b.target===target);
  document.getElementById('crawlBackupRows').innerHTML=rows.map(b=>'<tr><td>'+esc(new Date(b.created_at).toLocaleString())+'</td><td>'+esc(reasons[b.reason]||b.reason)+'</td><td>'+esc((b.size_bytes/1048576).toFixed(1))+' MB</td><td><button class="secondary" onclick="downloadSavedBackup(\''+esc(b.name)+'\')">Download</button> <button class="secondary" data-ui-action="danger" onclick="restoreCrawlBackup(\''+esc(b.name)+'\')">Restore</button></td></tr>').join('')||'<tr><td colspan="4">No saved backups for this target.</td></tr>';
  document.getElementById('crawlBackupStatus').textContent='';
}
async function saveCrawlBackupRetention(){
  try{
    await jfetch('/api/admin/operations/backups',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:document.getElementById('backupTarget').value,generations:Number(document.getElementById('crawlBackupGenerations').value),enabled:document.getElementById('backupScheduledEnabled').checked,interval_hours:Number(document.getElementById('backupIntervalHours').value)})});
    await loadCrawlBackups();document.getElementById('crawlBackupStatus').textContent='Backup settings saved.';
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
}
async function saveManualBackup(){
  const button=document.getElementById('saveBackupButton');button.disabled=true;
  try{
    await jfetch('/api/admin/operations/backups/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:document.getElementById('backupTarget').value})});
    await loadCrawlBackups();document.getElementById('crawlBackupStatus').textContent='Backup saved.';
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
  finally{button.disabled=false}
}
async function downloadSavedBackup(name){
  try{
    const response=await fetch('/api/admin/operations/backups/'+encodeURIComponent(name)+'/download',{headers:{'X-YGC-Console-Admin':CONSOLE_ADMIN_TOKEN}});
    if(!response.ok)throw new Error((await response.json()).detail||'Download failed');
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
  document.getElementById('detail').textContent='Select a row in Product List to view its history.';
  selectedIndividualId=null;
  document.getElementById('crawlBackupStatus').textContent='Backup restored. Maintenance remains enabled.';
}
async function restoreCrawlBackup(name){
  const backup=backupData?.backups.find(b=>b.name===name);
  if(!confirm('Restore '+(backupTargetNames[backup?.target]||'this target')+'? Only this target will be replaced. Its current state will be backed up first.'))return;
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
  if(!confirm('Restore '+backupTargetNames[backupImportTarget]+' from '+file.name+'? Only this target will be replaced. Its current state will be backed up first.'))return;
  try{
    await jfetch('/api/admin/operations/backups/import?target='+encodeURIComponent(backupImportTarget),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    await refreshAfterBackupRestore(backupImportTarget);
  }catch(e){document.getElementById('crawlBackupStatus').textContent=e.message}
  finally{input.value=''}
}
const maintenanceMessages={
  normal:'The service is operating normally.',
  read_only:'The service is under maintenance. Viewing is available, but changes are temporarily disabled.',
  offline:'The service is temporarily unavailable for maintenance. Please try again later.'
};
function setMaintenanceMessage(mode){document.getElementById('operationsMessage').value=maintenanceMessages[mode]||''}
