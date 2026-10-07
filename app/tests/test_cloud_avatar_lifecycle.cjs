const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const assets=path.join(__dirname,'../src/ygc/static');
const account=(id='A',extra={})=>({user:{app_user_id:id,role:'member',status:'active',...extra},identity:{email_verified:true}});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}};
const jpeg=(owner='A')=>({owner,type:'image/jpeg',size:10});
const response=(blob=jpeg(),status=200)=>({ok:status>=200&&status<300,status,headers:{get:()=>blob?.type},blob:async()=>blob});
const upload={type:'image/png',size:10};
function environment(initial=account()){
 const ids=new Map(),listeners={},calls=[],replies=[],created=[],revoked=[];let state=initial,canonical=initial,client,onCreate;
 for(const id of ['accountAvatar','avatarPreview','avatarStatus','avatarFile','avatarUpload','avatarRefresh','avatarRemove'])ids.set(id,{hidden:false,disabled:false,textContent:'',value:'',removeAttribute(key){delete this[key]}});
 ids.get('avatarPreview').hidden=true;
 class MediaURL extends URL{
  static createObjectURL(blob){const url='blob:'+blob.owner+'-'+created.length;created.push(url);onCreate?.();return url}
  static revokeObjectURL(url){revoked.push(url)}
 }
 const context=vm.createContext({URL:MediaURL,Headers,Error,document:{getElementById:id=>ids.get(id)},YGCI18n:{t:key=>key},location:{origin:'https://ygc.example'},addEventListener:(key,fn)=>(listeners[key]??=[]).push(fn)});
 client={get account(){return canonical},async authorizedFetch(url,options={},verified){calls.push({url,options,verified,owner:canonical?.user?.app_user_id});assert.ok(replies.length,'Every request requires an explicit fixture');const value=await replies.shift();if(value instanceof Error)throw value;return value}};
 vm.runInContext(fs.readFileSync(path.join(assets,'cloud-account-avatar.js'),'utf8').replace('export function','function'),context);
 const avatar=context.createAvatar({auth:()=>client,state:()=>state,busy:()=>false});avatar.render();
 return {avatar,context,calls,created,revoked,control:id=>ids.get(id),queue:(...values)=>replies.push(...values),
  changeAccount(value,{render=true}={}){state=canonical=value;if(render)avatar.render()},changeCanonical(value){canonical=value},setClient(value){client=value},onCreate(fn){onCreate=fn},
  event(key){for(const fn of listeners[key]||[])fn({})},async flush(){for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve))}};
}
const empty=e=>{assert.equal(e.control('avatarPreview').src,undefined);assert.equal(e.control('avatarPreview').hidden,true);assert.equal(e.control('avatarStatus').textContent,'')};

for(const role of ['member','admin'])test('Avatar happy path preserves the private Bearer adapter and '+role+' endpoint',async()=>{
 const e=environment(account('A',{role}));e.queue(response());await e.avatar.refresh();e.avatar.render();
 assert.equal(e.calls[0].url,role==='admin'?'/api/admin/accounts/me/avatar':'/api/auth/avatar');assert.equal(e.calls[0].verified,true);
 assert.equal(e.control('avatarPreview').src,e.created[0]);assert.equal(e.control('avatarPreview').hidden,false);assert.equal(e.control('avatarRemove').disabled,false);
 e.control('avatarFile').value='private selection';e.avatar.clear();empty(e);assert.equal(e.control('avatarFile').value,'');assert.deepEqual(e.revoked,e.created);
});

for(const phase of ['response','blob'])for(const boundary of ['account','pagehide','clear'])test('A deferred avatar '+phase+' cannot cross '+boundary,async()=>{
 const e=environment(),held=deferred();let blobReads=0;
 e.queue(phase==='response'?held.promise:{...response(),blob:()=>{blobReads++;return held.promise}});const pending=e.avatar.refresh();await e.flush();
 if(boundary==='account')e.changeAccount(account('B'));else if(boundary==='clear')e.avatar.clear();else e.event('pagehide');
 if(boundary==='account'){e.queue(response(jpeg('B')));await e.avatar.refresh()}
 const newest=e.control('avatarPreview').src;
 held.resolve(phase==='response'?{...response(),blob:async()=>{blobReads++;return jpeg()}}:jpeg());await pending;
 if(boundary==='account'){assert.equal(e.control('avatarPreview').src,newest);assert.match(newest,/blob:B/);assert.equal(e.revoked.includes(newest),false)}else empty(e);
 assert.equal(e.created.filter(url=>url.startsWith('blob:A')).length,0);assert.equal(blobReads,phase==='response'?0:1);
});

for(const initial of [null,{...account(),identity:{email_verified:false}},account('A',{status:'disabled'}),account('A',{status:'banned'})])test('Ineligible accounts do not read or write avatar data',async()=>{
 const e=environment(initial);await e.avatar.refresh();await e.avatar.save(upload);await e.avatar.remove();assert.equal(e.calls.length,0);assert.equal(e.control('accountAvatar').hidden,true);empty(e);
});
test('Account replacement clears a displayed object URL even without an explicit shell clear',async()=>{
 const e=environment();e.queue(response());await e.avatar.refresh();e.changeAccount(account('B'));empty(e);assert.deepEqual(e.revoked,e.created);
});
test('Initiating-account checks reject a response even before the next render',async()=>{
 const e=environment(),held=deferred();e.queue(held.promise);const pending=e.avatar.refresh();e.changeAccount(account('B'),{render:false});held.resolve(response());await pending;assert.equal(e.created.length,0);
});
test('Pagehide keeps avatar operations suspended until pageshow',async()=>{
 const e=environment();e.queue(response());await e.avatar.refresh();e.event('pagehide');e.avatar.render();await e.avatar.refresh();await e.avatar.save(upload);await e.avatar.remove();empty(e);assert.equal(e.calls.length,1);assert.deepEqual(e.revoked,e.created);
 e.event('pageshow');e.queue(response());await e.avatar.refresh();assert.equal(e.calls.length,2);assert.equal(e.control('avatarPreview').hidden,false);
});
test('A new avatar read wins over an older read or missing-image response',async()=>{
 for(const result of [response(),response(null,404)]){const e=environment(),held=deferred();e.queue(held.promise);const pending=e.avatar.refresh();e.queue(response(jpeg('new')));await e.avatar.refresh();const newest=e.control('avatarPreview').src;held.resolve(result);await pending;assert.equal(e.control('avatarPreview').src,newest);assert.equal(e.control('avatarStatus').textContent,'');assert.equal(e.revoked.includes(newest),false)}
});
test('A URL created during invalidation is revoked without attaching the stale image',async()=>{
 const e=environment();e.onCreate(()=>e.event('pagehide'));e.queue(response());await e.avatar.refresh();empty(e);assert.deepEqual(e.revoked,e.created);
});

for(const method of ['save','remove'])for(const boundary of ['account','pagehide'])for(const result of ['success','failure'])test('Late avatar '+method+' '+result+' cannot affect '+boundary,async()=>{
 const e=environment(),held=deferred();e.queue(response());await e.avatar.refresh();e.queue(held.promise);const pending=e.avatar[method](upload).catch(e.avatar.failed);await e.flush();
 if(boundary==='account'){e.changeAccount(account('B'));e.queue(response(jpeg('B')));await e.avatar.refresh()}else e.event('pagehide');
 const newest=e.control('avatarPreview').src,callCount=e.calls.length;held.resolve(response(null,result==='success'?200:403));await pending;
 assert.equal(e.calls.length,callCount,'Stale writes must not start a new-account refresh');assert.equal(e.control('avatarStatus').textContent,'');
 if(boundary==='account'){assert.equal(e.control('avatarPreview').src,newest);assert.equal(e.revoked.includes(newest),false)}else empty(e);
});
test('A save refresh already reading its blob cannot restore the old image or saved notice',async()=>{
 const e=environment(),held=deferred();e.queue(response(null),{...response(),blob:()=>held.promise});const pending=e.avatar.save(upload);await e.flush();assert.equal(e.calls.length,2);
 e.changeAccount(account('B'));e.queue(response(jpeg('B')));await e.avatar.refresh();const newest=e.control('avatarPreview').src;held.resolve(jpeg());await pending;
 assert.equal(e.control('avatarPreview').src,newest);assert.equal(e.control('avatarStatus').textContent,'');assert.equal(e.created.length,1);
});
test('An old read cannot restore an image after a newer successful Remove',async()=>{
 const e=environment(),held=deferred();e.queue(held.promise);const pending=e.avatar.refresh();e.queue(response(null));await e.avatar.remove();held.resolve(response());await pending;
 assert.equal(e.control('avatarPreview').src,undefined);assert.equal(e.control('avatarStatus').textContent,'avatar.removed');assert.equal(e.created.length,0);
});
test('An already-rejected avatar operation cannot clear a newer account through failed()',async()=>{
 const e=environment();e.queue(response(null,403));const error=await e.avatar.refresh().catch(error=>error);e.changeAccount(account('B'));e.queue(response(jpeg('B')));await e.avatar.refresh();const newest=e.control('avatarPreview').src;e.avatar.failed(error);assert.equal(e.control('avatarPreview').src,newest);assert.equal(e.control('avatarStatus').textContent,'');
});
test('Current save, remove, missing image, and validation retain existing API behavior',async()=>{
 const e=environment();e.queue(response(null),response());await e.avatar.save(upload);assert.equal(e.calls[0].options.method,'PUT');assert.equal(e.calls[0].options.body,upload);assert.equal(e.calls[0].options.headers['Content-Type'],'image/png');assert.equal(e.control('avatarStatus').textContent,'avatar.saved');
 e.queue(response(null));await e.avatar.remove();assert.equal(e.calls.at(-1).options.method,'DELETE');assert.equal(e.control('avatarPreview').src,undefined);assert.equal(e.control('avatarStatus').textContent,'avatar.removed');assert.deepEqual(e.revoked,e.created);
 e.queue(response(null,404));await e.avatar.refresh();assert.equal(e.control('avatarStatus').textContent,'avatar.empty');const count=e.calls.length;await assert.rejects(e.avatar.save({type:'image/svg+xml',size:10}),error=>error.status===400);assert.equal(e.calls.length,count);
 e.queue(response({type:'text/html',size:10}));await assert.rejects(e.avatar.refresh(),/Unexpected image type/);e.queue(response({type:'image/jpeg',size:25*1024*1024+1}));await assert.rejects(e.avatar.refresh(),/Image exceeds limit/);
});

for(const canonical of [null,undefined,account('B')])test('Stale shell A cannot read or write with a missing or different canonical account',async()=>{
 const e=environment();e.queue(response());await e.avatar.refresh();e.changeCanonical(canonical);await e.avatar.save(upload);await e.avatar.remove();await e.avatar.refresh();assert.equal(e.calls.length,1);empty(e);assert.deepEqual(e.revoked,e.created);
});
test('A canonical-account change fences a response even before the shell observes it',async()=>{
 const e=environment(),held=deferred();e.queue(held.promise);const pending=e.avatar.refresh();e.changeCanonical(null);held.resolve(response());await pending;assert.equal(e.created.length,0);
});
for(const method of ['save','remove'])for(const phase of ['before-dispatch','token'])test('The real auth adapter never sends A '+method+' as B after an SDK switch '+phase,async()=>{
 const e=environment(),held=deferred(),network=[],tokens=[];let gateToken=false;
 const userA={getIdToken:async()=>{tokens.push('A');return gateToken?held.promise:'token-A'}},userB={getIdToken:async()=>{tokens.push('B');return 'token-B'}};
 const auth={currentUser:userA,authStateReady:async()=>{}};
 const sdk={browserSessionPersistence:'session',setPersistence:async()=>{},onAuthStateChanged(){}};
 vm.runInContext(fs.readFileSync(path.join(assets,'identity-platform-auth.js'),'utf8'),e.context);
 const adapter=e.context.YGCIdentityPlatformAuth.create({sdk,auth,fetch:async(url,options)=>{network.push({url,options});return {...response(null),json:async()=>account()}}});e.setClient(adapter);await adapter.restore();network.length=tokens.length=0;
 if(phase==='before-dispatch')auth.currentUser=userB;else gateToken=true;
 const pending=e.avatar[method](upload).catch(e.avatar.failed);await e.flush();
 if(phase==='token'){assert.deepEqual(tokens,['A']);auth.currentUser=userB;e.changeAccount(account('B'));held.resolve('token-A')}
 await pending;assert.equal(network.length,0);assert.equal(tokens.includes('B'),false);empty(e);
});
