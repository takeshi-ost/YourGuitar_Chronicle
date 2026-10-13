const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/src/ygc/static/identity-platform-auth.js','utf8');
function harness({store=new Map(),uid='A',clock={value:1000},denyStorage=false,profileBootstrap=false,theme=null}={}){
 const events={},calls=[],listeners=[],user={uid,getIdToken:async()=>uid+'-token'},auth={currentUser:user,tenantId:null,authStateReady:async()=>{}},account={user:{app_user_id:uid+'-app',role:'member',status:'active'},identity:{email_verified:true}};
 const sdk={browserSessionPersistence:'session',setPersistence:async()=>{},onAuthStateChanged(_,fn){listeners.push(fn)},signOut:async()=>{auth.currentUser=null}};
 const storage={getItem:k=>{if(denyStorage)throw Error('Unavailable');return store.get(k)||null},setItem:(k,v)=>{if(denyStorage)throw Error('Unavailable');store.set(k,v)},removeItem:k=>{if(denyStorage)throw Error('Unavailable');store.delete(k)}};
 let mode='normal',status=200,hold=null,body={fields:{display_name:uid}},gateHold=null,gateStatus=200;
 const request=async(url,options)=>{calls.push({url,options});if(url.endsWith('/api/auth/me'))return Response.json(account);if(url.endsWith('/api/service/status')){if(gateHold)await gateHold;return Response.json(gateStatus===200?{mode}:{code:'closed_test_participant_required'},{status:gateStatus})}if(hold)await hold;return Response.json(body,{status})};
 const context={YGCTheme:theme,URL,Headers,Response,Error,addEventListener:(name,fn)=>events[name]=fn,location:{origin:'https://ygc.example'},fetch:request};vm.runInNewContext(source,context);
 const adapter=context.YGCIdentityPlatformAuth.create({sdk,auth,fetch:request,storage,now:()=>clock.value,profileBootstrap});
 return {adapter,store,clock,calls,account,auth,user,events,mode:v=>mode=v,status:v=>status=v,gateStatus:v=>gateStatus=v,hold:v=>hold=v,gateHold:v=>gateHold=v,body:v=>body=v,switchUser(){auth.currentUser={uid:'B',getIdToken:async()=> 'B-token'};listeners.forEach(fn=>fn())},count:path=>calls.filter(c=>new URL(c.url).pathname===path).length};
}
const read=s=>s.adapter.authorizedFetch('/api/auth/settings',{reuseUserData:true});
const defer=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve}};
test('Cached display rechecks participant with bearer and rejects revoked membership without returning old data',async()=>{
 const s=harness();await s.adapter.restore();await read(s);let blocked;
 s.adapter.onUserDataInvalidated((reason,error)=>{if(reason==='blocked')blocked=error});
 s.gateStatus(403);await assert.rejects(read(s),e=>e.status===403&&e.code==='closed_test_participant_required');
 const check=s.calls.find(c=>c.url.endsWith('/api/service/status'));
 assert.equal(check.options.headers.get('Authorization'),'Bearer A-token');
 assert.equal(s.store.size,0);assert.equal(blocked.code,'closed_test_participant_required');
 assert.equal(s.count('/api/auth/settings'),1);
});
test('Completed data reused in page and next document only after fresh canonical me; tokens/identity never persisted',async()=>{
 const s=harness();await s.adapter.restore();await read(s);await read(s);assert.equal(s.count('/api/auth/settings'),1);assert.equal(s.count('/api/service/status'),1);
 const next=harness({store:s.store});await next.adapter.restore();await read(next);assert.equal(next.count('/api/auth/me'),1);assert.equal(next.count('/api/auth/settings'),0);assert.equal(next.count('/api/service/status'),1);
 const saved=[...s.store.values()].join('');assert.ok(!saved.includes('A-token'));assert.ok(!saved.includes('email_verified'));assert.ok(!saved.includes('password'));
});
test('Stored data is never consumed before canonical restore or for another user',async()=>{
 const s=harness();await s.adapter.restore();await read(s);
 const before=harness({store:s.store});await read(before);assert.equal(before.count('/api/auth/settings'),1);
 const other=harness({store:s.store,uid:'B'});await other.adapter.restore();await read(other);assert.equal(other.count('/api/auth/settings'),1);assert.equal((await read(other)).status,200);
});
test('Explicit refresh and unlisted private/permission resources always fetch; response bodies independent',async()=>{
 const s=harness();await s.adapter.restore();const r=await read(s);assert.equal((await r.json()).fields.display_name,'A');const next=await read(s);assert.equal((await next.json()).fields.display_name,'A');
 s.body({fields:{display_name:'updated'}});await s.adapter.authorizedFetch('/api/auth/settings');assert.equal(s.count('/api/auth/settings'),2);assert.equal((await (await read(s)).json()).fields.display_name,'updated');assert.equal(s.count('/api/auth/settings'),3);
 for(const path of ['/api/auth/me','/api/auth/guitars/52/ownership','/api/auth/avatar','/api/auth/favorites/52']){await s.adapter.authorizedFetch(path,{reuseUserData:true});await s.adapter.authorizedFetch(path,{reuseUserData:true});assert.equal(s.count(path),path==='/api/auth/me'?3:2)}
});
test('TTL expiry, rollback clocks and future timestamps cannot reuse data',async()=>{
 const s=harness();await s.adapter.restore();await read(s);s.clock.value=31000;await read(s);assert.equal(s.count('/api/auth/settings'),2);s.clock.value=999;await read(s);assert.equal(s.count('/api/auth/settings'),3);
});
test('Offline cached hit must check status, clear private cache and report403, never return old JSON',async()=>{
 const s=harness();await s.adapter.restore();await read(s);let invalidated=0;s.adapter.onUserDataInvalidated(()=>invalidated++);s.mode('offline');const r=await read(s);assert.equal(r.status,403);assert.equal(r.headers.get('Cache-Control'),'no-store');assert.equal((await r.json()).detail.code,'service_restricted');assert.equal(s.store.size,0);assert.equal(invalidated,1);
});
test('Admin Only avoids cache and uses ordinary canonical-authorized API',async()=>{
 const s=harness();await s.adapter.restore();await read(s);s.mode('admin_only');await read(s);assert.equal(s.count('/api/auth/settings'),2);
});
test('Mutation clears cache before and after, including failed operation',async()=>{
 const s=harness();await s.adapter.restore();await read(s);s.status(409);await s.adapter.authorizedFetch('/api/auth/profile',{method:'PUT',body:'{}'},true);assert.equal(s.store.size,0);s.status(200);await read(s);assert.equal(s.count('/api/auth/settings'),2);
});
test('Pending mutation prevents snapshot publication and cached reads',async()=>{
 const s=harness();await s.adapter.restore();await read(s);const hold=defer();s.hold(hold.promise);const write=s.adapter.authorizedFetch('/api/auth/profile',{method:'PUT'},true);const get=read(s);hold.resolve();await Promise.all([write,get]);assert.equal(s.store.size,0);await read(s);assert.equal(s.count('/api/auth/settings'),3);
});
test('Delayed data response after invalidation cannot repopulate cache',async()=>{
 const s=harness();await s.adapter.restore();const hold=defer();s.hold(hold.promise);const result=read(s);await new Promise(setImmediate);s.adapter.invalidateUserData();hold.resolve();await result;assert.equal(s.store.size,0);
});
test('Switch and sign out discard cached data; pending gate cannot return old actor snapshot',async()=>{
 const s=harness();await s.adapter.restore();await read(s);const gate=defer();s.gateHold(gate.promise);const cached=read(s);await new Promise(setImmediate);s.switchUser();gate.resolve();await assert.rejects(cached);assert.equal(s.store.size,0);
 const n=harness();await n.adapter.restore();await read(n);await n.adapter.logout();assert.equal(n.store.size,0);assert.equal(n.adapter.account,null);
});
for(const status of [401,403,503])test(`Fresh rejected response ${status} removes all stored data`,async()=>{
 const s=harness();await s.adapter.restore();await read(s);s.status(status);const r=await s.adapter.authorizedFetch('/api/auth/settings');assert.equal(r.status,status);assert.equal(s.store.size,0);
});
test('Corrupt and oversized storage falls back to canonical network, storage denial remains usable',async()=>{
 for(const raw of ['bad JSON',JSON.stringify({owner:'B',entries:{}}),'x'.repeat(512*1024+1)]){const s=harness({store:new Map([['ygc-self-display-v1',raw]])});await s.adapter.restore();await read(s);assert.equal(s.count('/api/auth/settings'),1)}
});
test('Concurrent cached reads coalesce only pending service check and next read checks again',async()=>{
 const s=harness();await s.adapter.restore();await read(s);const gate=defer();s.gateHold(gate.promise);const a=read(s),b=read(s);await new Promise(setImmediate);gate.resolve();assert.deepEqual(await (await a).json(),await (await b).json());assert.equal(s.count('/api/service/status'),1);await read(s);assert.equal(s.count('/api/service/status'),2);
});
test('Initial SDK restoration preserves saved display entries without false account-switch notification',async()=>{
 const s=harness();await s.adapter.restore();await read(s);const next=harness({store:s.store});next.auth.currentUser=null;next.auth.authStateReady=async()=>{next.auth.currentUser=next.user};let changed=0;next.adapter.onIdentityChanged(()=>changed++);await next.adapter.restore();await read(next);assert.equal(changed,0);assert.equal(next.count('/api/auth/settings'),0);
});

test('Resource-only forbidden read clears stored display data without invalidating canonical identity views',async()=>{
 const s=harness();await s.adapter.restore();await read(s);let invalidated=0;s.adapter.onUserDataInvalidated(()=>invalidated++);s.status(403);await s.adapter.authorizedFetch('/api/auth/guitars/16/ownership');assert.equal(s.store.size,0);assert.equal(invalidated,0);assert.ok(s.adapter.account);
});

test('Incomplete Favorite pages are not persisted as a complete user collection',async()=>{
 const s=harness();await s.adapter.restore();s.body({items:[{id:'52'}],total:'2',next_after:'52'});const path='/api/auth/favorites?limit=50';await s.adapter.authorizedFetch(path,{reuseUserData:true});await s.adapter.authorizedFetch(path,{reuseUserData:true});assert.equal(s.count('/api/auth/favorites'),2);s.body({items:[{id:'52'}],total:'1',next_after:null});await s.adapter.authorizedFetch(path,{reuseUserData:true});await s.adapter.authorizedFetch(path,{reuseUserData:true});assert.equal(s.count('/api/auth/favorites'),3);
});

test('Navigation keeps completed snapshots but rejects late publication from the departed document',async()=>{
 const s=harness();await s.adapter.restore();await read(s);assert.equal(s.store.size,1);s.events.pagehide();assert.equal(s.store.size,1);
 const n=harness();await n.adapter.restore();const hold=defer();n.hold(hold.promise);const pending=read(n);await new Promise(setImmediate);n.events.pagehide();hold.resolve();await pending;assert.equal(n.store.size,0);
});
test('Malformed service status fails closed and cannot return cached private display data',async()=>{
 const s=harness();await s.adapter.restore();await read(s);s.mode('unknown');await assert.rejects(read(s));assert.equal(s.store.size,0);
});

test('Denied sessionStorage keeps memory-only reuse and canonical request fallback usable',async()=>{
 const s=harness({denyStorage:true});await s.adapter.restore();await read(s);await read(s);assert.equal(s.count('/api/auth/settings'),1);assert.equal(s.store.size,0);s.adapter.invalidateUserData();await read(s);assert.equal(s.count('/api/auth/settings'),2);
});

test('Read Only never reuses an enabled notification write control from Normal',async()=>{
 const s=harness();await s.adapter.restore();s.body({items:[],next_after:null,unread_count:'17',can_write:true});const path='/api/auth/notifications?limit=25';await s.adapter.authorizedFetch(path,{reuseUserData:true});s.mode('read_only');const data=await (await s.adapter.authorizedFetch(path,{reuseUserData:true})).json();assert.equal(data.can_write,false);assert.equal(data.unread_count,'17');assert.equal(s.count('/api/auth/notifications'),1);
});

test('Blocked event retains service restriction reason separately from authentication rejection',async()=>{
 const s=harness();await s.adapter.restore();await read(s);let detail;s.adapter.onUserDataInvalidated((reason,error)=>{detail={reason,error}});s.mode('offline');await read(s);assert.equal(detail.reason,'blocked');assert.equal(detail.error.code,'service_restricted');assert.equal(detail.error.status,403);
});

test('Explicit display invalidation during pending cache gate rejects stale snapshot without blocking the same canonical actor',async()=>{
 const s=harness();await s.adapter.restore();await read(s);let blocked=0;s.adapter.onUserDataInvalidated(reason=>{if(reason==='blocked')blocked++});
 const gate=defer();s.gateHold(gate.promise);const cached=read(s);await new Promise(setImmediate);s.adapter.invalidateUserData();gate.resolve();
 await assert.rejects(cached,e=>e.code==='stale_user_data');assert.equal(blocked,0);assert.deepEqual(s.adapter.account,s.account);assert.equal(s.store.size,0);
 s.gateHold(null);await read(s);assert.equal(s.count('/api/auth/settings'),2);
});

test('A late rejected display read after logout cannot invalidate the new Guest state',async()=>{const s=harness();await s.adapter.restore();await read(s);let blocked=0;s.adapter.onUserDataInvalidated(reason=>{if(reason==='blocked')blocked++});s.status(403);const hold=defer();s.hold(hold.promise);const pending=s.adapter.authorizedFetch('/api/auth/settings');await new Promise(setImmediate);await s.adapter.logout();hold.resolve();await assert.rejects(pending);assert.equal(blocked,0);assert.equal(s.adapter.account,null)});

test('Self Profile theme restore shares the bounded bootstrap instead of a second Settings request',async()=>{
 const themes=[],s=harness({profileBootstrap:true,theme:{bind:()=>false,remember:t=>themes.push(t)}});s.body({settings:{fields:{theme:'sunburst_3ply'}}});await s.adapter.restore();await s.adapter.authorizedFetch('/api/auth/profile/bootstrap',{reuseUserData:true});await new Promise(r=>setImmediate(r));assert.equal(s.count('/api/auth/settings'),0);assert.equal(s.count('/api/auth/profile/bootstrap'),1);assert.equal(themes.at(-1),'sunburst_3ply');
});
