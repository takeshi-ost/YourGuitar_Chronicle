const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'../src/ygc/static');
const source=fs.readFileSync(path.join(root,'cloud-console-page.js'),'utf8');
function held(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function environment(){
 const elements=new Map(),calls=[],panels={},reads=new Map(),listeners={},open=[],client={signedIn:true,account:{user:{app_user_id:'admin-A',id:'1',role:'admin',display_name:'Admin'},identity:{email_verified:true}},restore:async()=>client.account,onIdentityChanged:fn=>listeners.identity=fn,logout:async()=>{client.account=null}};
 class Element{constructor(){this.disabled=false;this.hidden=false;this.value='';this.textContent='';this.tabIndex=0;this.attributes={}}setAttribute(k,v){this.attributes[k]=v}getAttribute(k){return this.attributes[k]}removeAttribute(){}addEventListener(){}querySelectorAll(){return []}scrollIntoView(){}focus(){}}
 const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
 const document={getElementById:element,querySelector:element,activeElement:null};
 const controller=name=>options=>{const deferred=held();panels[name]={deferred,options,cleared:0,loaded:false};return {render(){if(name==='disputes')element('caseAction').disabled=options.busy()||!options.state()},clear(){panels[name].cleared++;panels[name].loaded=false},async refresh(){calls.push(name);await deferred.promise;panels[name].loaded=true},openDispute:async id=>{open.push(id)}}};
 client.authorizedFetch=async url=>{calls.push(url);const deferred=held();reads.set(url,deferred);return await deferred.promise};
 const context=vm.createContext({authLabel:()=> 'Sign in / Create Account',createAuthDialog:()=>({open(){}}),document,URLSearchParams,location:{search:'?dispute=3'},YGCI18n:{t:k=>k},YGCOverlays:{close(){},open(){}},fetch:async()=>({ok:true}),loadCloudAuth:async()=>client,createDisputes:controller('disputes'),createApplicationBrowser:controller('applications'),createUserBrowser:controller('users'),createCrawlBrowser:controller('crawl'),createBackupBrowser:controller('backups'),createGuitarBrowser:controller('guitars')});
 const ready=vm.runInContext('(async()=>{'+source.replace(/^import .*;\n/gm,'')+'})()',context);
 const reply=(url,value)=>reads.get(url).resolve({ok:true,json:async()=>value});
 return {elements,element,panels,reads,calls,client,ready,open,listeners,reply,flush:()=>new Promise(r=>setImmediate(r))};
}
test('Ready console controls and dispute detail do not wait for unrelated panels or diagnostics',async()=>{
 const e=environment();await e.flush();assert.equal(e.element('caseAction').disabled,false);assert.equal(e.element('operationsSave').disabled,true);
 assert.ok(['disputes','applications','users','crawl','backups','guitars'].every(name=>e.calls.includes(name)));
 e.reply('/api/admin/operations',{mode:'offline',message:'maintenance',version:1});await e.flush();assert.equal(e.element('operationsSave').disabled,false);assert.equal(e.element('reviewToggle').disabled,true);
 e.reply('/api/admin/operations/review',{enabled:false});e.panels.disputes.deferred.resolve();await e.flush();assert.equal(e.element('reviewToggle').disabled,false);assert.deepEqual(e.open,['3']);assert.ok(e.reads.has('/api/admin/operations/storage'));assert.equal(e.panels.backups.loaded,false);
 for(const name of ['applications','users','crawl','backups','guitars'])e.panels[name].deferred.resolve();await e.ready;assert.equal(e.element('operationsSave').disabled,false);
 e.reply('/api/admin/operations/storage',{content:'available',accounts:'available'});await e.flush();assert.equal(e.element('contentStorageStatus').textContent,'console.storage_readable');
});
test('Failed Review read retains successfully loaded Maintenance controls and other panels',async()=>{
 const e=environment();await e.flush();e.reply('/api/admin/operations',{mode:'offline',message:'maintenance',version:1});e.reads.get('/api/admin/operations/review').resolve({ok:false,status:503,json:async()=>({})});for(const panel of Object.values(e.panels))panel.deferred.resolve();await e.ready;assert.equal(e.element('operationsSave').disabled,false);assert.equal(e.element('reviewToggle').disabled,true);assert.equal(e.element('consoleStatus').textContent,'console.unavailable');
});
test('Identity invalidation discards pending service settings and does not reopen a private case',async()=>{
 const e=environment();await e.flush();e.listeners.identity();e.client.account={user:{app_user_id:'other',role:'member'}};
 e.reply('/api/admin/operations',{mode:'normal',message:'OLD PRIVATE MESSAGE',version:1});e.reply('/api/admin/operations/review',{enabled:true});for(const panel of Object.values(e.panels))panel.deferred.resolve();await e.ready;
 assert.equal(e.element('operationsSave').disabled,true);assert.equal(e.element('operationsMessage').value,'');assert.deepEqual(e.open,[]);assert.equal(e.element('consoleControls').hidden,true);assert.equal(e.reads.has('/api/admin/operations/storage'),false);
});
