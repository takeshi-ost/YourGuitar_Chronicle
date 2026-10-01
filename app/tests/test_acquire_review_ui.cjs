const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=require('./page_source.cjs')('app/src/ygc/static/user_view_html.html');
const source=html.slice(html.indexOf('let acquireRevision='),html.indexOf('let individualLoadSequence='));
function setup(){
  const elements={acquireReviewTitle:{textContent:''},acquireReviewActions:{innerHTML:''},acquireReviewContent:{innerHTML:''},acquireReviewModal:{classList:{add(){},remove(){},contains(){return true}}}};
  const calls=[];
  const context=vm.createContext({document:{getElementById:id=>elements[id]},activeUser:{user:{id:2}},selectedIndividualId:null,
    esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'),
    requireAccount(){calls.push('account')},alert:v=>calls.push(v),jfetch:async(url,options)=>{calls.push([url,options]);return {revision:'a'.repeat(32),status:'draft',serial:'SERIAL',challenge:'CHALLENGE',expires_at:1800000000,original_individual_id:1}},
    YGCOverlays:{open:id=>elements[id].classList.add('open'),close:id=>elements[id].classList.remove('open')},
    Date,encodeURIComponent,FormData,confirm:()=>true});
  vm.runInContext(source,context);vm.runInContext('confirmOwnershipAction=async()=>true',context);return {context,elements,calls};
}
test('Acquire entry previews an unsaved application and displays server-issued challenge',async()=>{
  const {context,elements,calls}=setup();await vm.runInContext('openAcquireApplication(1)',context);
  assert.equal(calls[0][0],'/api/ownership-drafts/acquire/1?viewer_id=2');
  assert.equal(calls[0][1].method,'POST');assert.match(elements.acquireReviewContent.innerHTML,/CHALLENGE/);
  assert.match(elements.acquireReviewContent.innerHTML,/acquireCloseup/);assert.match(elements.acquireReviewContent.innerHTML,/acquireOverview/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/reference.*type="file"/);
});
test('Request shows status and rejection Info without raw reports or evidence images',()=>{
  const {context,elements}=setup();context.row={revision:'a'.repeat(32),status:'pending',images:{},report:'<img src=x onerror=alert(1)>'};
  vm.runInContext('renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewTitle.innerHTML,/Acquire Request <small class="ownership-request-status">- Awaiting review<\/small>/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/<h3>/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/Review Report|&lt;img/);
  context.row={...context.row,status:'rejected',images:{closeup:{}},result:{adjudication:{reasons:['<Reason>']}}};
  vm.runInContext('renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewContent.innerHTML,/&lt;Reason>/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/<img|Review Report/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/<img src=x/);
  context.row={...context.row,status:'accepted',verification_status:'unverified'};vm.runInContext('renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewTitle.innerHTML,/Awaiting owner approval/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/Cancel Request/);
});
test('Current-owner entry remains hidden and old Acquire form delegates to new application',()=>{
  assert.match(html,/function openOwnerClaim\(individualId\)\{\s+openAcquireApplication\(individualId\)/);
  assert.match(html,/if\(mode==='acquire'\)\{openAcquireApplication\(individualId\);return\}/);
  assert.match(html,/Number\(individual.current_owner_user_id\)===Number\(activeUser.user.id\)\)\{\s+return actorNote/);
});

test('Add Guitar exposes Challenge and both photo fields in the shared modal immediately',()=>{
  const {context,elements}=setup();context.PROFILE_USER_ID=2;
  elements.guitarMaker={focus(){}};
  vm.runInContext(html.slice(html.indexOf('function openNewGuitar(){'),html.indexOf('function setProfileSort(')),context);
  vm.runInContext('openNewGuitar()',context);
  const content=elements.acquireReviewContent.innerHTML;
  assert.match(content,/Challenge: Not generated/);
  assert.match(content,/id="acquireCloseup"[^>]*disabled/);
  assert.match(content,/id="acquireOverview"[^>]*disabled/);
  assert.match(content,/Photograph the guitar with the code/);
  assert.match(elements.acquireReviewActions.innerHTML,/id="guitarSubmit"/);
  assert.match(elements.acquireReviewActions.innerHTML,/>Reflesh<\/button>/);
  assert.doesNotMatch(html,/id="newGuitarModal"/);
});

test('Reflesh keeps an unsaved Challenge and input without creating a request',async()=>{
  const {context,elements,calls}=setup();
  context.row={revision:'a'.repeat(32),status:'draft',unsaved:true,draft_token:'signed-preview',serial:'SERIAL',challenge:'KEEP1234',expires_at:1800000000,images:{}};
  elements.acquireDate={value:'2026-10-01'};elements.acquireBody={value:'Unsaved description'};
  vm.runInContext('acquireRevision=row.revision;renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewActions.innerHTML,/>Reflesh<\/button>/);
  await vm.runInContext('requestRefresh()',context);
  assert.equal(calls.length,0);
  assert.equal(vm.runInContext('acquireForm.draft_token',context),'signed-preview');
  assert.match(elements.acquireReviewContent.innerHTML,/KEEP1234/);
  assert.equal(elements.acquireBody.value,'Unsaved description');
  assert.equal(elements.acquireDate.value,'2026-10-01');
  vm.runInContext('confirmOwnershipAction=async()=>false',context);
  elements.acquireReviewContent.innerHTML='unchanged';
  await vm.runInContext('requestRefresh()',context);
  assert.equal(elements.acquireReviewContent.innerHTML,'unchanged');
});

test('Listing challenge issuance enables the shared photo fields without switching modals',async()=>{
  const {context,elements}=setup();context.PROFILE_USER_ID=2;
  for(const [id,value] of Object.entries({guitarMaker:'Fender',guitarModel:'Tele',guitarFinish:'Black',guitarYear:'2020',guitarSerial:'SERIAL',acquireDate:'2026-10-01',acquireBody:'note'}))elements[id]={value,focus(){}};
  elements.guitarSubmit={disabled:false};elements.guitarStatus={textContent:''};elements.acquireReviewContent.parentElement={scrollTop:55};
  context.jfetch=async()=>({request_kind:'listing',revision:'a'.repeat(32),status:'draft',serial:'SERIAL',challenge:'CODE1234',expires_at:1800000000,images:{},listing_payload:{manufacturer:'Fender',serial_number:'SERIAL',model:'Tele',finish:'Black',year:'2020',occurred_at:'2026-10-01',body:'note'}});
  vm.runInContext(html.slice(html.indexOf('function openNewGuitar(){'),html.indexOf('function setProfileSort(')),context);
  await vm.runInContext('submitNewGuitar()',context);
  assert.match(elements.acquireReviewContent.innerHTML,/CODE1234/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/id="acquireCloseup"[^>]*disabled/);
  assert.match(elements.acquireReviewActions.innerHTML,/id="acquireSubmit"/);
  assert.match(elements.acquireReviewContent.innerHTML,/id="acquireDate"[^>]*value="2026-10-01"/);
  assert.equal(elements.acquireReviewContent.parentElement.scrollTop,0);
});

 test('Public Claim extracts listing Info and hides evidence attachments; console retains them',()=>{
  const {context}=setup();
  Object.assign(context,{claimTypeLabel:v=>v,displayEventDate:v=>v,displayInputDate:v=>v,claimVisualTypeClass:()=>'',claimHeaderHtml:()=>'',YGCProductDetail:{userLink:()=> 'User'}});
  vm.runInContext(html.slice(html.indexOf('function claimCardFull(c){'),html.indexOf('function compactClaimType(c){')),context);
  context.claim={id:1,claim_type:'listing',source_site:'reverb',source_listing_id:'INTERNAL-ID',source_url:'https://reverb.com/item/example',evidence_media_id:999};
  const rendered=vm.runInContext('claimCardFull(claim)',context);
  assert.match(rendered,/Info.*View Reverb listing/);
  assert.doesNotMatch(rendered,/Evidence:|INTERNAL-ID|api\/media\/999/);
  context.claim={id:2,claim_type:'media',media_images:[{url:'/api/media/123'}]};
  assert.match(vm.runInContext('claimCardFull(claim)',context),/api\/media\/123/);
  assert.doesNotMatch(html,/Acquire Evidence|Report and Photos/);
  const consoleSource=fs.readFileSync('app/src/ygc/static/pages/console.js','utf8');
  assert.match(consoleSource,/Evidence: Accepted by User/);
  assert.match(consoleSource,/alt="Claim evidence"/);
});

test('Unanswered requests show addressed actions independently of notifications',async()=>{
  const {context,elements}=setup();elements.unansweredRequests={hidden:true,innerHTML:''};
  context.YGCProductDetail={userLink:(id,name)=>name};
  context.jfetch=async()=>[{claim_id:12,individual_id:3,kind:'transfer',sender_id:1,sender_name:'From',guitar:'Tele'},
    {claim_id:13,individual_id:4,kind:'acquire',sender_id:5,sender_name:'Buyer',guitar:'Strat'}];
  vm.runInContext(html.slice(html.indexOf('let unansweredSequence='),html.indexOf('async function loadActiveUser()')),context);
  await vm.runInContext('loadUnansweredRequests()',context);
  assert.equal(elements.unansweredRequests.hidden,false);
  assert.match(elements.unansweredRequests.innerHTML,/Unanswered Requests/);
  assert.match(elements.unansweredRequests.innerHTML,/has offered to transfer/);
  assert.match(elements.unansweredRequests.innerHTML,/is claiming ownership of/);
  assert.match(elements.unansweredRequests.innerHTML,/>Accept<\/button>/);
  assert.match(elements.unansweredRequests.innerHTML,/>Decline<\/button>/);
  context.jfetch=async()=>[];await vm.runInContext('loadUnansweredRequests()',context);
  assert.equal(elements.unansweredRequests.hidden,true);
});

test('Request Cancel closes immediately without confirmation or server writes',async()=>{
  const {context,calls}=setup();
  let closed=false;
  context.confirmOwnershipAction=()=>{throw Error('Cancel must not ask for confirmation')};
  context.YGCOverlays.close=id=>{assert.equal(id,'acquireReviewModal');closed=true};
  await vm.runInContext('cancelRequestWindow()',context);
  assert.equal(closed,true);assert.equal(calls.length,0);
});
