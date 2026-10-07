const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/src/ygc/static/identity-platform-auth.js','utf8');
const policies={terms:{version:'terms-1'},privacy:{version:'privacy-1'}};
const profile={display_name:' Test User ',account_type:'builder',terms_accepted:true,privacy_accepted:true,
  terms_version:'terms-1',privacy_version:'privacy-1'};
const account={user:{id:7,app_user_id:'uuid',display_name:'Test User'},identity:{email_verified:false}};
function setup(){
  const calls=[],sdkCalls=[],refreshes=[];
  let token=0, failure=null, unregistered=false;
  const user={email:'test@example.invalid',getIdToken:async(force=false)=>{refreshes.push(force);return 'fresh-'+(++token)}};
  const auth={currentUser:null,authStateReady:async()=>{sdkCalls.push('ready')}};
  const sdk={browserSessionPersistence:'session',
    setPersistence:async(...args)=>sdkCalls.push(['persistence',...args]),
    signInWithEmailAndPassword:async(...args)=>{sdkCalls.push(['signin',...args]);auth.currentUser=user},
    createUserWithEmailAndPassword:async(...args)=>{sdkCalls.push(['create',...args]);auth.currentUser=user},
    sendEmailVerification:async(...args)=>sdkCalls.push(['verifyEmail',...args]),
    reload:async(...args)=>sdkCalls.push(['reload',...args]),
    signOut:async()=>{sdkCalls.push('signout');auth.currentUser=null}};
  const fetch=async(url,options={})=>{
    calls.push({url,options});
    if(url.endsWith('/registration'))return new Response(JSON.stringify({documents:policies}));
    if(failure)return new Response(JSON.stringify({detail:'Try again'}),{status:failure});
    if(unregistered&&url.endsWith('/me'))return new Response(JSON.stringify({code:'registration_required'}),{status:409});
    return new Response(JSON.stringify(account));
  };
  const context={URL,Headers,Error,location:{origin:'https://ygc.example'},fetch};
  vm.runInNewContext(source,context);
  return {adapter:context.YGCIdentityPlatformAuth.create({sdk,auth,fetch}),auth,sdk,calls,sdkCalls,user,refreshes,
    fail:value=>failure=value,unregistered:value=>unregistered=value};
}
test('Sign In uses session persistence and sends only SDK credentials to Google',async()=>{
  const s=setup();assert.deepEqual(await s.adapter.signIn({email:'test@example.invalid',password:'private-password'}),account);
  assert.equal(s.sdkCalls[0][0],'persistence');assert.equal(s.sdkCalls[0][2],'session');
  assert.equal(s.sdkCalls[1],'ready');assert.equal(s.sdkCalls[2][0],'signin');
  assert.equal(s.sdkCalls[2][3],'private-password');
  assert.equal(s.calls[0].options.headers.get('Authorization'),'Bearer fresh-1');
  assert.equal(s.calls[0].options.body,undefined);
  assert.equal(JSON.stringify(s.calls).includes('private-password'),false);
});
test('Registration separates credentials from the profile and refreshes tokens for each API call',async()=>{
  const s=setup();await s.adapter.register(profile,{email:'test@example.invalid',password:'private-password'});
  const write=s.calls.find(call=>call.url.endsWith('/register'));
  assert.equal(JSON.parse(write.options.body).display_name,'Test User');
  assert.equal(write.options.body.includes('private-password'),false);
  assert.equal(write.options.body.includes('test@example.invalid'),false);
  await s.adapter.restore();
  assert.equal(s.calls.at(-1).options.headers.get('Authorization'),'Bearer fresh-2');
});
test('An app registration failure preserves Google login and retries enrollment without another Google account',async()=>{
  const s=setup();s.fail(503);
  await assert.rejects(s.adapter.register(profile,{email:'test@example.invalid',password:'private-password'}));
  assert.equal(s.adapter.signedIn,true);assert.equal(s.adapter.account,null);
  s.fail(null);await s.adapter.register(profile);
  assert.equal(s.sdkCalls.filter(call=>call[0]==='create').length,1);
  assert.deepEqual(s.adapter.account,account);
});
test('Unregistered Sign In does not create an app account automatically',async()=>{
  const s=setup();s.unregistered(true);
  assert.equal((await s.adapter.signIn({email:'test@example.invalid',password:'password'})).registration_required,true);
  assert.equal(s.adapter.account,null);assert.equal(s.calls.some(call=>call.url.endsWith('/register')),false);
});
test('Changed consent documents stop before Google account creation',async()=>{
  const s=setup();await assert.rejects(s.adapter.register({...profile,terms_version:'old'},
    {email:'test@example.invalid',password:'password'}),error=>error.code==='policy_changed');
  assert.equal(s.sdkCalls.some(call=>call[0]==='create'),false);
});
test('Invalid profile or credentials in the profile cannot create a Google account',async()=>{
  for(const patch of [{password:'private'}, {role:'admin'}, {terms_accepted:false}, {display_name:'x'.repeat(121)}, {account_type:'admin'}]){
    const s=setup();await assert.rejects(s.adapter.register({...profile,...patch},{email:'test@example.invalid',password:'password'}));
    assert.equal(s.sdkCalls.some(call=>call[0]==='create'),false);
  }
});
test('Enrollment cannot silently switch the signed-in identity',async()=>{
  const s=setup();s.auth.currentUser=s.user;
  await assert.rejects(s.adapter.register(profile,{email:'other@example.invalid',password:'password'}));
  assert.equal(s.calls.some(call=>call.url.endsWith('/register')),false);
});
test('Bearer requests reject cross-origin destinations and redirects',async()=>{
  const s=setup();s.auth.currentUser=s.user;
  await assert.rejects(s.adapter.authorizedFetch('https://other.example/api/me'));
  await assert.rejects(s.adapter.authorizedFetch('/account'));
  assert.equal(s.calls.length,0);
  await s.adapter.authorizedFetch('/api/auth/me');
  assert.equal(s.calls[0].options.redirect,'error');assert.equal(s.calls[0].options.credentials,'omit');
});
test('SignOut clears the SDK session and application identity',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  await s.adapter.logout();assert.equal(s.adapter.account,null);assert.equal(s.adapter.signedIn,false);
  await assert.rejects(s.adapter.authorizedFetch('/api/auth/me'));
});
test('Concurrent registration and SignOut finish in order',async()=>{
  const s=setup();await Promise.all([s.adapter.register(profile,{email:'test@example.invalid',password:'password'}),s.adapter.logout()]);
  assert.equal(s.adapter.signedIn,false);assert.equal(s.adapter.account,null);
});
test('Verification email is explicit, uses Google SDK and stays on the configured origin',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'private-password'});
  assert.equal(s.sdkCalls.some(call=>call[0]==='verifyEmail'),false);
  const result=await s.adapter.requestEmailVerification({language:'ja'});
  assert.equal(result.sent,true);assert.equal(result.account.identity.email_verified,false);
  const email=s.sdkCalls.find(call=>call[0]==='verifyEmail');
  assert.equal(email[1],s.user);assert.equal(email[2].url,'https://ygc.example/account');
  assert.equal(s.auth.languageCode,'ja');assert.equal(s.refreshes.at(-1),true);
  assert.equal(s.calls.every(call=>!call.options.method||call.options.method==='GET'),true);
});
test('Refreshing verification reloads Google and forces a fresh server-verified token',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  s.user.emailVerified=true;
  const result=await s.adapter.refreshVerification();
  assert.equal(result.identity.email_verified,false,'SDK flag must not replace server verification');
  assert.equal(s.sdkCalls.at(-1)[0],'reload');assert.equal(s.refreshes.at(-1),true);
  assert.equal(s.calls.at(-1).url,'https://ygc.example/api/auth/me');
});
test('Signed-out, unregistered and rejected accounts cannot request verification mail',async()=>{
  const s=setup();await assert.rejects(s.adapter.requestEmailVerification());
  s.auth.currentUser=s.user;s.unregistered(true);
  await assert.rejects(s.adapter.requestEmailVerification());
  s.unregistered(false);s.fail(403);
  await assert.rejects(s.adapter.requestEmailVerification());
  assert.equal(s.sdkCalls.some(call=>call[0]==='verifyEmail'),false);
});
test('Verification request and SignOut are serialized without a second identity',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  await Promise.all([s.adapter.requestEmailVerification(),s.adapter.logout()]);
  assert.equal(s.sdkCalls.at(-1),'signout');assert.equal(s.adapter.account,null);
  assert.equal(s.adapter.signedIn,false);
});
test('Already verified server identity never sends another verification email',async()=>{
  const s=setup();s.auth.currentUser=s.user;
  const adapterSource=source;
  const verified={...account,identity:{email_verified:true}};
  const fetch=async()=>new Response(JSON.stringify(verified));
  const context={URL,Headers,Error,location:{origin:'https://ygc.example'},fetch};
  vm.runInNewContext(adapterSource,context);
  const adapter=context.YGCIdentityPlatformAuth.create({sdk:s.sdk,auth:s.auth,fetch});
  assert.equal((await adapter.requestEmailVerification()).sent,false);
  assert.equal(s.sdkCalls.some(call=>call[0]==='verifyEmail'),false);
});
test('Google throttling during verification remains an error and cannot mark email verified',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  s.sdk.sendEmailVerification=async()=>{throw Object.assign(Error('private provider details'),{code:'auth/too-many-requests'})};
  await assert.rejects(s.adapter.requestEmailVerification(),error=>error.code==='auth/too-many-requests');
  assert.equal(s.adapter.account.identity.email_verified,false);
});

test('Verification return preserves exact canonical BIGINT Acquire intent on the fixed account path',async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  await s.adapter.requestEmailVerification({language:'en',acquire:'9223372036854775807',returnUrl:'https://evil.invalid'});
  assert.equal(s.sdkCalls.find(call=>call[0]==='verifyEmail')[2].url,'https://ygc.example/account?acquire=9223372036854775807');
  assert.equal(s.calls.some(call=>call.url.includes('/applications')),false);
});
for(const acquire of ['',null,12,'0','01','+1','-1','1e3','9223372036854775808','https://evil.invalid','12&next=https://evil.invalid'])test(`Verification rejects invalid Acquire intent ${String(acquire)}`,async()=>{
  const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
  await assert.rejects(s.adapter.requestEmailVerification({acquire}));assert.equal(s.sdkCalls.some(call=>call[0]==='verifyEmail'),false);
});

test('Verification return preserves Claim intent alongside Acquire without accepting a return URL',async()=>{
 const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});
 await s.adapter.requestEmailVerification({language:'ja',claim:'9223372036854775807',acquire:'12',returnUrl:'https://evil.invalid'});
 assert.equal(s.sdkCalls.find(call=>call[0]==='verifyEmail')[2].url,'https://ygc.example/account?acquire=12&claim=9223372036854775807');
});
for(const claim of ['',null,12,'0','01','+1','-1','1e3','9223372036854775808','https://evil.invalid','12&next=https://evil.invalid'])test(`Verification rejects invalid Claim intent ${String(claim)}`,async()=>{
 const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});await assert.rejects(s.adapter.requestEmailVerification({claim}));assert.equal(s.sdkCalls.some(call=>call[0]==='verifyEmail'),false);
});

function delayed(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
function principalHarness({readiness=Promise.resolve(),token=Promise.resolve('A-token'),fetch}={}){
 const first={email:'a@example.invalid',getIdToken:()=>token},second={email:'b@example.invalid',getIdToken:async()=> 'B-token'};
 const auth={currentUser:first,authStateReady:()=>readiness},calls=[],listeners=[];
 const sdk={browserSessionPersistence:'session',setPersistence:async()=>{},onAuthStateChanged(_auth,listener){listeners.push(listener)}};
 const request=async(url,options)=>{calls.push({url,options});return fetch?fetch(url,options):new Response(JSON.stringify(account))};
 const context={URL,Headers,Error,location:{origin:'https://ygc.example'},fetch:request};vm.runInNewContext(source,context);
 const adapter=context.YGCIdentityPlatformAuth.create({sdk,auth,fetch:request});
 return {adapter,auth,calls,first,second,switchUser(user=second){auth.currentUser=user;for(const listener of listeners)listener()}};
}
test('Pending SDK readiness cannot send an initiating A mutation using B credentials',async()=>{
 const hold=delayed(),s=principalHarness({readiness:hold.promise});
 const write=s.adapter.authorizedFetch('/api/auth/favorites/1',{method:'PUT',body:'{"favorite":true}'},true);
 s.switchUser();hold.resolve();await assert.rejects(write,error=>error.code==='sign_in_required');assert.equal(s.calls.length,0);assert.equal(s.adapter.account,null);
});
test('An SDK switch during token retrieval rejects the mutation before network dispatch',async()=>{
 const hold=delayed(),s=principalHarness({token:hold.promise});const write=s.adapter.authorizedFetch('/api/auth/profile/visibility',{method:'PUT',body:'PRIVATE'},true);
 await new Promise(resolve=>setImmediate(resolve));s.switchUser();hold.resolve('A-token');await assert.rejects(write,error=>error.code==='sign_in_required');assert.equal(s.calls.length,0);
});
for(const status of [200,409])test('Late canonical '+status+' response body cannot restore an old principal',async()=>{
 const body=delayed(),s=principalHarness({fetch:async()=>({ok:status===200,status,json:()=>body.promise})});const restoring=s.adapter.restore();await new Promise(resolve=>setImmediate(resolve));s.switchUser();body.resolve(status===200?account:{code:'registration_required'});
 await assert.rejects(restoring,error=>error.code==='sign_in_required');assert.equal(s.adapter.account,null);
});
test('SDK account change synchronously invalidates canonical cache and notifies all private views',async()=>{
 const s=principalHarness();await s.adapter.restore();assert.deepEqual(s.adapter.account,account);let cleared=0;s.adapter.onIdentityChanged(()=>{throw Error('Broken unrelated view')});const unsubscribe=s.adapter.onIdentityChanged(()=>cleared++);s.switchUser();assert.equal(s.adapter.account,null);assert.equal(cleared,1);unsubscribe();s.switchUser(null);assert.equal(cleared,1);
});
test('Without an SDK observer, the canonical account getter still refuses another current SDK principal',async()=>{
 const s=setup();await s.adapter.signIn({email:'test@example.invalid',password:'password'});assert.deepEqual(s.adapter.account,account);s.auth.currentUser={email:'other@example.invalid',getIdToken:async()=> 'new'};assert.equal(s.adapter.account,null);
});

test('A stale canonical cache rejects writes after the SDK switched before observer delivery',async()=>{
 const s=principalHarness();await s.adapter.restore();const count=s.calls.length;let cleared=0;s.adapter.onIdentityChanged(()=>cleared++);
 // Deliberately do not notify the observer: an old shell can still show A.
 s.auth.currentUser=s.second;
 await assert.rejects(s.adapter.authorizedFetch('/api/auth/profile',{method:'PUT',body:'A-private-profile'},true),error=>error.code==='sign_in_required');
 assert.equal(s.calls.length,count);assert.equal(cleared,1);assert.equal(s.adapter.account,null);
 // Canonical restore is an explicit new read and is still available for B.
 await s.adapter.restore();assert.equal(s.calls.at(-1).options.headers.get('Authorization'),'Bearer B-token');
});
