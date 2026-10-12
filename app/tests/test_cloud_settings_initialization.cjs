const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/ygc/static/cloud-user-settings.js'),'utf8').replace(/^import .*;\n/gm,'');
async function setup(){
 const elements=new Map(),listeners=[],calls=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:false,dataset:{},style:{},replaceChildren(){},append(){}});return elements.get(id)};
 let initial=true,resolveSettings;
 const account={user:{app_user_id:'1',status:'active'},identity:{email_verified:true}};
 const auth={account:null,signedIn:true,async restore(){if(initial){initial=false;listeners.forEach(fn=>fn())}this.account=account;return account},onIdentityChanged(fn){listeners.push(fn)},authorizedFetch(path){calls.push(path);return new Promise(r=>resolveSettings=r)}};
 const context={createAuthDialog:()=>({open(){}}),loadCloudAuth:async()=>auth,document:{getElementById:element,querySelectorAll:()=>[],documentElement:{style:{setProperty(){}},dataset:{}},createElement:()=>element('new')},YGCI18n:{t:k=>k},addEventListener(){},URL:{revokeObjectURL(){}},console};
 vm.createContext(context);const running=vm.runInContext('(async()=>{'+source+'})()',context);await new Promise(r=>setImmediate(r));
 return {calls,elements,auth,listeners,running,finish:()=>resolveSettings({ok:false,status:503})};
}
test('restored login reaches the settings request rather than invalidating its initial load',async()=>{
 const e=await setup();assert.deepEqual(e.calls,['/api/auth/settings']);e.finish();await e.running;
});
test('later identity switch clears private fields and rejects a stale request completion',async()=>{
 const e=await setup();e.elements.get('displayName').value='previous user';e.elements.get('settings').hidden=false;
 e.auth.account=null;e.listeners.forEach(fn=>fn());assert.equal(e.elements.get('settings').hidden,true);assert.equal(e.elements.get('displayName').value,'');
 e.finish();await e.running;assert.equal(e.elements.get('emptyState').textContent,'self_profile.restricted');
});
