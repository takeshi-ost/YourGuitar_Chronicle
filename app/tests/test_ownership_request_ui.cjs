const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('app/src/ygc/static/index_html.html','utf8');
const source=html.slice(html.indexOf('let productionAcquires='),html.indexOf('function statCard('));
function setup(){
 const elements={};for(const id of ['productionAcquireSearch','productionAcquireFilter','productionAcquireRows','productionAcquireSummary','productionAcquireActions','productionAcquireDetail','productionAcquireReason','productionAcquireStatus','productionAcquirePrompt','productionAcquireImages'])elements[id]={value:'',innerHTML:'',textContent:''};
 const row={revision:'a'.repeat(32),status:'accepted',verification_status:'unverified',claim_id:2,applicant_id:3,applicant_name:'<script>bad</script>',product_name:'Fender',original_individual_id:1,serial:'TEST',created_at:'2026-10-01',images:{},admin_actions:['reject','positive'],management_version:'b'.repeat(64)};
 const calls=[];const context=vm.createContext({document:{getElementById:id=>elements[id]},Date,URL,encodeURIComponent,CONSOLE_ADMIN_TOKEN:'test',selectedIndividualId:null,
 esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'),
 confirm:()=>true,jfetch:async(url,options)=>{calls.push([url,options]);return options?row:{applications:[row],prompt:'prompt'}},loadIndividuals:async()=>{},loadUsers:async()=>{}});
 vm.runInContext(source,context);context.row=row;return{context,elements,row,calls};
}
test('Ownership Request is separate from experiments and safely shows owner approval wait',async()=>{
 assert.match(html,/href="#ownership-request"/);
 const {context,elements}=setup();await vm.runInContext('loadProductionAcquires()',context);
 assert.match(elements.productionAcquireRows.innerHTML,/Owner承認待ち/);
 assert.match(elements.productionAcquireRows.innerHTML,/&lt;script>/);
 assert.doesNotMatch(elements.productionAcquireRows.innerHTML,/<script>/);
 elements.productionAcquireFilter.value='rejected';vm.runInContext('renderProductionAcquires()',context);
 assert.match(elements.productionAcquireRows.innerHTML,/該当する申請はありません/);
});
test('Admin changes require a reason and send the displayed version',async()=>{
 const {context,elements,calls,row}=setup();vm.runInContext('renderProductionAcquireDetail(row)',context);
 await vm.runInContext("manageProductionAcquire(row.revision,'reject')",context);assert.equal(calls.length,0);
 elements.productionAcquireReason.value='目視で確認';await vm.runInContext("manageProductionAcquire(row.revision,'reject')",context);
 const body=JSON.parse(calls[0][1].body);assert.equal(body.expected_version,row.management_version);assert.equal(body.operation,'reject');assert.equal(body.reason,'目視で確認');
 assert.match(calls[0][0],/\/api\/admin\/acquire-applications\/[a-f0-9]+\/manage$/);
});
test('Manual decision is distinct from original AI JSON and its reason is escaped',()=>{
 const {context,elements,row}=setup();row.admin_review={accepted:false,reason:'<img src=x>'};row.result={adjudication:{accepted:true}};
 vm.runInContext('renderProductionAcquireDetail(row)',context);
 assert.match(elements.productionAcquireSummary.innerHTML,/管理者による審議: 不採用/);
 assert.match(elements.productionAcquireSummary.innerHTML,/&lt;img/);
 assert.equal(JSON.parse(elements.productionAcquireDetail.value).result.adjudication.accepted,true);
});
