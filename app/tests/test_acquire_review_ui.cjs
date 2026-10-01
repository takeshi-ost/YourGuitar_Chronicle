const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=require('./page_source.cjs')('app/src/ygc/static/user_view_html.html');
const source=html.slice(html.indexOf('let acquireRevision='),html.indexOf('let individualLoadSequence='));
function setup(){
  const elements={acquireReviewContent:{innerHTML:''},acquireReviewModal:{classList:{add(){},remove(){},contains(){return true}}}};
  const calls=[];
  const context=vm.createContext({document:{getElementById:id=>elements[id]},activeUser:{user:{id:2}},selectedIndividualId:null,
    esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'),
    requireAccount(){calls.push('account')},alert:v=>calls.push(v),jfetch:async(url,options)=>{calls.push([url,options]);return {revision:'a'.repeat(32),status:'draft',serial:'SERIAL',challenge:'CHALLENGE',expires_at:1800000000,original_individual_id:1}},
    YGCOverlays:{open:id=>elements[id].classList.add('open'),close:id=>elements[id].classList.remove('open')},
    Date,encodeURIComponent,FormData,confirm:()=>true});
  vm.runInContext(source,context);return {context,elements,calls};
}
test('Acquire entry creates an application and displays server-issued challenge',async()=>{
  const {context,elements,calls}=setup();await vm.runInContext('openAcquireApplication(1)',context);
  assert.equal(calls[0][0],'/api/individuals/1/acquire-applications?viewer_id=2');
  assert.equal(calls[0][1].method,'POST');assert.match(elements.acquireReviewContent.innerHTML,/CHALLENGE/);
  assert.match(elements.acquireReviewContent.innerHTML,/acquireCloseup/);assert.match(elements.acquireReviewContent.innerHTML,/acquireOverview/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/reference.*type="file"/);
});
test('Awaiting review is not displayed as rejection and reports are escaped',()=>{
  const {context,elements}=setup();context.row={revision:'a'.repeat(32),status:'pending',images:{},report:'<img src=x onerror=alert(1)>'};
  vm.runInContext('renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewContent.innerHTML,/Acquire申請中/);
  assert.match(elements.acquireReviewContent.innerHTML,/&lt;img/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/<img src=x/);
  context.row={...context.row,status:'accepted',verification_status:'unverified'};vm.runInContext('renderAcquireApplication(row)',context);
  assert.match(elements.acquireReviewContent.innerHTML,/Owner承認待ち/);
  assert.doesNotMatch(elements.acquireReviewContent.innerHTML,/申請を取り消す/);
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
  assert.match(content,/Challenge: 未発行/);
  assert.match(content,/id="acquireCloseup"[^>]*disabled/);
  assert.match(content,/id="acquireOverview"[^>]*disabled/);
  assert.match(content,/コードとギターを撮影/);
  assert.match(content,/id="guitarSubmit"/);
  assert.doesNotMatch(html,/id="newGuitarModal"/);
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
  assert.match(elements.acquireReviewContent.innerHTML,/id="acquireSubmit"/);
  assert.match(elements.acquireReviewContent.innerHTML,/id="acquireDate"[^>]*value="2026-10-01"/);
  assert.equal(elements.acquireReviewContent.parentElement.scrollTop,0);
});
