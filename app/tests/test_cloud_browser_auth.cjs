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
  const calls=[],sdkCalls=[];
  let token=0, failure=null, unregistered=false;
  const user={email:'test@example.invalid',getIdToken:async()=> 'fresh-'+(++token)};
  const auth={currentUser:null,authStateReady:async()=>{sdkCalls.push('ready')}};
  const sdk={browserSessionPersistence:'session',
    setPersistence:async(...args)=>sdkCalls.push(['persistence',...args]),
    signInWithEmailAndPassword:async(...args)=>{sdkCalls.push(['signin',...args]);auth.currentUser=user},
    createUserWithEmailAndPassword:async(...args)=>{sdkCalls.push(['create',...args]);auth.currentUser=user},
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
  return {adapter:context.YGCIdentityPlatformAuth.create({sdk,auth,fetch}),auth,sdk,calls,sdkCalls,user,
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
