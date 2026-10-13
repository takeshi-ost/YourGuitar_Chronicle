const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'../src/ygc/static');
const source=fs.readFileSync(path.join(root,'cloud-account-page.js'),'utf8');
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function setup(){
 const calls=[],waits={};const context={state:{user:{app_user_id:'A'},identity:{email_verified:true}},sessionEpoch:0,pageSuspended:false,formalProfile:false,profileBootstrap:null,location:{pathname:'/ui/profile',search:''},URLSearchParams,accountHydrating:0,render:()=>{}};
 for(const name of ['profile','guitars','favorites','formalView','visibility','disputes','notifications','identityCorrections','ownership','applications','avatar']){
  waits[name]=deferred();context[name]={refresh:()=>{calls.push(name);return waits[name].promise},failed:error=>{throw error}};
 }
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function loadAvatar(){'),source.indexOf('async function avatarAction(')),context);
 return {context,calls,waits,run:()=>context.loadAvatar(),flush:()=>new Promise(r=>setImmediate(r))};
}
test('visible profile and lists start together before secondary panels, independent failures do not block siblings',async()=>{
 const e=setup(),done=e.run();assert.deepEqual(e.calls,['profile','guitars','favorites']);
 e.waits.profile.resolve();e.waits.guitars.resolve();e.waits.favorites.resolve();await e.flush();
 assert.equal(e.calls.length,10);assert.equal(e.calls[3],'formalView');
 const error=new Error('notification unavailable');e.waits.notifications.reject(error);
 let completed=false;done.catch(()=>{completed=true});await e.flush();assert.equal(completed,false);
 for(const name of e.calls.slice(3))if(name!=='notifications')e.waits[name].resolve();
 await assert.rejects(done,/notification unavailable/);
});
test('identity change or page suspension cancels scheduling secondary private requests',async()=>{
 for(const change of [e=>e.context.state.user.app_user_id='B',e=>e.context.pageSuspended=true,e=>e.context.sessionEpoch++]){
  const e=setup(),done=e.run();change(e);for(const name of ['profile','guitars','favorites'])e.waits[name].resolve();await done;
  assert.deepEqual(e.calls,['profile','guitars','favorites']);
 }
});
test('background hydration leaves mutation controls unlocked and discards stale failure messages',async()=>{
 for(const invalidate of [false,true]){
  const e=setup(),status={textContent:''};e.context.busy=false;e.context.$=()=>status;e.context.errorMessage=error=>error.message;
  const done=e.context.hydrateAccount();assert.equal(e.context.busy,false);assert.equal(e.context.accountHydrating,1);
  for(const name of ['profile','guitars','favorites'])e.waits[name].resolve();await e.flush();
  assert.equal(e.context.busy,false);assert.ok(e.calls.includes('notifications'));
  if(invalidate)e.context.sessionEpoch++;
  e.waits.notifications.reject(new Error('notification unavailable'));
  for(const name of e.calls.slice(3))if(name!=='notifications')e.waits[name].resolve();
  await done;assert.equal(e.context.accountHydrating,0);assert.equal(status.textContent,invalidate?'':'notification unavailable');
 }
});
test('formal section links scroll without firing the popstate reload path',()=>{
 const source=fs.readFileSync(path.join(root,'cloud-ui-profile.js'),'utf8');
 const start=source.indexOf('a.onclick=event=>{'),end=source.indexOf('};nav.append(a)',start);
 const calls=[],a={},context={a,id:'selfGuitars_owned',location:{pathname:'/ui/profile/guitars/52',search:''},history:{state:null,replaceState:(_,__,url)=>calls.push(url)},$:()=>({scrollIntoView:()=>calls.push('scroll')})};
 vm.runInNewContext(source.slice(start,end+1),context);
 a.onclick({button:0,preventDefault:()=>calls.push('prevent')});assert.deepEqual(calls,['prevent','/ui/profile/guitars/52#selfGuitars_owned','scroll']);
 calls.length=0;a.onclick({button:0,ctrlKey:true,preventDefault:()=>calls.push('prevent')});assert.deepEqual(calls,[]);
});
test('pending list counts cannot be shown as a measured zero',()=>{
 const source=fs.readFileSync(path.join(root,'list-navigation.js'),'utf8');
 const start=source.indexOf('  function updateCounts()'),end=source.indexOf('  new MutationObserver(updateCounts)',start);
 const label={textContent:''},title={dataset:{countItems:'#rows',countPending:'true'},querySelector:()=>label};
 const context={document:{querySelectorAll:q=>q==='[data-count-items]'?[title]:[]},YGCI18n:{t:(_,p)=>p.count+' items',number:String}};
 vm.createContext(context);vm.runInContext(source.slice(start,end),context);context.updateCounts();assert.equal(label.textContent,'—');
 title.dataset.countPending='false';context.updateCounts();assert.equal(label.textContent,'0 items');
});

test('ownership mutations refresh profile header, Chronicle and detail after ownership lists',async()=>{
 const start=source.indexOf('async function refreshOwnershipViews(){'),end=source.indexOf('let acquireIntent=',start);
 for(const invalidate of [false,true]){
  const calls=[],pending=deferred(),context={state:{user:{app_user_id:'A'}},sessionEpoch:0,pageSuspended:false,guitars:{refreshHistory:()=>{calls.push('lists');return pending.promise}},formalView:{refresh:async()=>calls.push('profile')}};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  const done=context.refreshOwnershipViews();assert.deepEqual(calls,['lists']);
  if(invalidate)context.sessionEpoch++;
  pending.resolve();await done;assert.deepEqual(calls,invalidate?['lists']:['lists','profile']);
 }
});


test('Formal Profile skips the hidden visibility settings panel during hydration',async()=>{
 const e=setup();e.context.formalProfile=true;const done=e.run();for(const name of ['profile','guitars','favorites'])e.waits[name].resolve();await e.flush();
 assert.ok(!e.calls.includes('visibility'));assert.ok(e.calls.includes('avatar')&&e.calls.includes('notifications'));
 for(const name of e.calls.slice(3))e.waits[name].resolve();await done;
});
