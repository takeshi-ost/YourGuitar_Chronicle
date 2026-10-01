const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('app/src/ygc/static/index_html.html','utf8');
const script=html.slice(html.indexOf('let directBusy='),html.indexOf('function statCard('));
function setup(){
 const elements=new Proxy({}, {get:(obj,id)=>obj[id]??=( {value:'',type:'password',textContent:'',files:[{size:10}],setAttribute(){},focus(){},select(){this.selected=true},setSelectionRange(){}} )});
 const calls=[];
 const job={application_id:'test-001',revision:'abc123',status:'pending',created_at:'now',attempts:0};
 const context=vm.createContext({location:{origin:'http://localhost:8000'},document:{getElementById:id=>elements[id]},
  esc:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  FormData:class{append(){}},jfetch:async(url,options)=>{
    calls.push({url,options});
    if(url==='/api/admin/direct-experiment'&&!options)return {status:'queue',jobs:[job]};
    if(url.includes('?revision='))return {...job,result:null,report_text:null};
    return {...job,token:'private-token',prompt:'prompt',python:'/python',project:'/project'};
  }});
 vm.runInContext(script,context);return {context,elements,calls};
}
test('Prepare exposes dedicated token only in its field, config has placeholder',async()=>{
 const {context,elements}=setup();await context.prepareDirectExperiment();
 assert.equal(elements.directToken.value,'private-token');
 assert.match(elements.directConfig.value,/PASTE_TOKEN/);
 assert.doesNotMatch(elements.directConfig.value,/private-token/);
 assert.doesNotMatch(elements.directResult.value,/private-token/);
});
test('Revoke clears credentials only after successful request',async()=>{
 const {context,elements}=setup();await context.prepareDirectExperiment();
 context.jfetch=async()=>{throw Error('offline')};await context.revokeDirectExperiment();
 assert.equal(elements.directToken.value,'private-token');
 context.jfetch=async()=>({});await context.revokeDirectExperiment();
 assert.equal(elements.directToken.value,'');assert.equal(elements.directConfig.value,'');
});
test('Pending and communication failure are not rejection',async()=>{
 const {context,elements}=setup();await context.refreshDirectExperiment();
 assert.match(elements.directStatus.textContent,/未処理/);
 context.jfetch=async()=>{throw Error('offline')};await context.refreshDirectExperiment();
 assert.match(elements.directStatus.textContent,/取得失敗/);assert.doesNotMatch(elements.directStatus.textContent,/False/);
});

test('Copy key uses clipboard without revealing the password',async()=>{
 const {context,elements}=setup();let copied;
 context.navigator={clipboard:{writeText:async value=>{copied=value}}};
 await context.prepareDirectExperiment();await context.copyDirectToken();
 assert.equal(copied,'private-token');assert.equal(elements.directToken.type,'password');
 assert.match(elements.directTokenStatus.textContent,/コピーしました/);
});
test('Clipboard unavailable reveals and selects key without claiming copy succeeded',async()=>{
 const {context,elements}=setup();await context.prepareDirectExperiment();
 await context.copyDirectToken();
 assert.equal(elements.directToken.type,'text');assert.equal(elements.directToken.selected,true);
 assert.match(elements.directTokenStatus.textContent,/⌘C/);
 assert.doesNotMatch(elements.directTokenStatus.textContent,/コピーしました/);
 context.toggleDirectToken();assert.equal(elements.directToken.type,'password');
});
test('Empty key does not copy',async()=>{
 const {context,elements}=setup();await context.copyDirectToken();
 assert.match(elements.directTokenStatus.textContent,/準備/);
});

test('Queue rendering escapes AI errors and restores detail by revision',async()=>{
 const {context,elements}=setup();
 context.jfetch=async url=>url.includes('?revision=')?{revision:'rev',status:'error',report_text:null}:
  {jobs:[{application_id:'<script>',revision:'rev',status:'error',error:'<img onerror=bad>',attempts:1}]};
 await context.refreshDirectExperiment();
 assert.doesNotMatch(elements.directQueueRows.innerHTML,/<script>|<img/);
 assert.match(elements.directQueueRows.innerHTML,/再試行/);
 assert.match(elements.directResult.value,/'rev'|"rev"/);
});
test('Connection diagnostics do not claim jobs',async()=>{
 const {context,elements,calls}=setup();elements.directToken.value='private-token';
 context.jfetch=async(url,options)=>{
   calls.push({url,options});const req=JSON.parse(options.body);
   if(req.method==='initialize')return {result:{serverInfo:{name:'YGC'}}};
   if(req.method==='tools/list')return {result:{tools:[{name:'ygc_pending_test'}]}};
   if(req.method==='ping')return {result:{}};
   throw Error('Unexpected request');
 };
 await context.inspectDirectExperiment();
 assert.deepEqual(calls.map(c=>JSON.parse(c.options.body).method),['initialize','tools/list','ping']);
 assert.match(elements.directStatus.textContent,/診断成功/);
});
test('Restoring connection does not prepare or claim a job',async()=>{
 const {context,calls,elements}=setup();await context.restoreDirectConnection();
 assert.equal(calls.length,1);assert.match(calls[0].url,/connection$/);
 assert.equal(elements.directToken.value,'private-token');
});


test('Console retires API and Sheets controls and removes only their saved API keys',()=>{
  assert.doesNotMatch(html,/id="(?:authProvider|authApiKey|authTestResults|sheetResult)"/);
  const source=html.slice(html.indexOf('// Remove only credentials'),html.indexOf('let directBusy='));
  const saved=new Map([['ygc_authentication_api_key_openai','old'],['ygc_authentication_api_key_gemini','old'],['ygc_reverb_token','keep']]);
  vm.runInNewContext(source,{localStorage:{removeItem:key=>saved.delete(key)}});
  assert.deepEqual([...saved],[['ygc_reverb_token','keep']]);
});
