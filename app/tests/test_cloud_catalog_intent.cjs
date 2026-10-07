const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const staticPath=path.join(__dirname,'../src/ygc/static');
const account=(id='first',verified=true)=>({user:{app_user_id:id,display_name:'Member',role:'member'},identity:{email_verified:verified}});
const guitar=(id='12',extra={})=>({id,manufacturer:'Maker',model:'Model',serial_number:'SERIAL-'+id,finish:null,year:'1965',photo:null,...extra});
const draft=(id='12')=>({revision:'a'.repeat(32),kind:'acquire',individual_id:id,serial:'SERIAL-'+id,status:'draft',photos:[],expires_at:2000000000,reasons:[]});
const denied=(httpStatus=403)=>({httpStatus});
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
function environment({initial=account(),search='',fullPage=false,catalogReplies=[]}={}){
  const ids=new Map(),listeners={};
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.style={};this.value='';this.files=[];this.hidden=false;this.open=false;this.disabled=false;this.textContent='';this.classList={add(){},remove(){}};this.isConnected=true;this.tabIndex=0}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}
    setAttribute(key,value){this[key]=value}removeAttribute(key){delete this[key]}hasAttribute(key){return key in this}
    addEventListener(key,fn){(this.listeners[key]??=[]).push(fn)}dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn(event)}
    all(){return this.children.flatMap(n=>[n,...n.all()])}contains(n){return n===this||this.all().includes(n)}
    querySelectorAll(selector){const tags=selector.split(',').filter(t=>/^[a-z]+$/.test(t)).map(t=>t.toUpperCase());return this.all().filter(n=>tags.includes(n.tagName))}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null}
    reset(){for(const input of this.all().filter(n=>['INPUT','TEXTAREA'].includes(n.tagName)))input.value=''}
    focus(){document.activeElement=this}closest(){return null}getClientRects(){return this.hidden?[]:[this.getBoundingClientRect()]}
    getBoundingClientRect(){return {left:20,right:600,top:20,bottom:600}}showModal(){this.open=true;this.opens=(this.opens||0)+1}close(){this.open=false}
  }
  const document={body:new Element('body'),documentElement:{lang:'en'},createElement:tag=>new Element(tag),getElementById:id=>ids.get(id),addEventListener(key,fn){(listeners[key]??=[]).push(fn)}};
  const html=fs.readFileSync(path.join(staticPath,'cloud_account_html.html'),'utf8');
  for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)){const n=new Element(match[1]);n.id=match[2];document.body.append(n)}
  let state=initial,busy=false,component,componentArgs;
  const calls=[],publicCalls=[],authCalls=[],replies=[],publicReplies=[...catalogReplies],authReplies=[];
  async function response(value){const data=await value;if(data instanceof Error)throw data;return data?.httpStatus?{ok:false,status:data.httpStatus,json:async()=>({detail:{code:'service_restricted'}})}:{ok:true,json:async()=>data}}
  const client={signedIn:Boolean(initial),account:initial,documents:async()=>({terms:{version:'t'},privacy:{version:'p'}}),
    restore:async()=>initial,
    async signIn(credentials){authCalls.push({name:'signin',credentials});this.signedIn=true;return this.account=authReplies.shift()??account('first',false)},
    async register(profile,credentials){authCalls.push({name:'register',profile,credentials});this.signedIn=true;return this.account=authReplies.shift()??account('first',false)},
    async logout(){authCalls.push({name:'logout'});this.signedIn=false;this.account=null},
    async requestEmailVerification(options){authCalls.push({name:'verification',options});return {sent:true,account:this.account}},
    async refreshVerification(){authCalls.push({name:'refreshVerification'});return this.account=account()},
    async authorizedFetch(url,options={},verified){if(url.startsWith('/api/public/guitars/'))return catalogResponse(url,options,{authorized:true,verified});calls.push({url,options,verified,account:componentArgs.state()?.user?.app_user_id});if(options.method==='POST')assert.ok(replies.length,'POST requires explicit fixture');return response(replies.length?replies.shift():{items:[],can_write:true})},
  };
  const context=vm.createContext({document,URL,URLSearchParams,Blob,Intl,Date,console,location:{search,origin:'https://ygc.example'},CustomEvent:class{constructor(type){this.type=type}},YGCI18n:{t:key=>key}});
  context.window=context;context.addEventListener=(key,fn)=>(listeners[key]??=[]).push(fn);
  function catalogResponse(url,options,extra={}){publicCalls.push({url,options,...extra});return response(publicReplies.length?publicReplies.shift():guitar(url.split('/').at(-1)))}
  context.fetch=catalogResponse;
  vm.runInContext(fs.readFileSync(path.join(staticPath,'overlays.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(staticPath,'cloud-account-applications.js'),'utf8').replaceAll('export function','function'),context);
  const create=context.createApplications;
  context.createApplications=args=>{componentArgs=args;component=create(args);return component};
  const noOp=()=>({render(){},clear(){},refresh:async()=>{},failed(){},save(){},remove(){}});
  Object.assign(context,{createFavorites:noOp,createVisibility:noOp,createDisputes:noOp,createNotifications:noOp,createIdentityCorrections:noOp,loadCloudAuth:async()=>client,createOwnership:()=>({...noOp(),setCatalogIntent(){},openGuitar(){}}),readOwnershipIntent:()=>null,createAvatar:noOp,createProfile:noOp,createGuitars:noOp,createClaims:()=>({...noOp(),setCatalogIntent(){}}),readClaimIntent:()=>null});
  let ready;
  if(fullPage){const source=fs.readFileSync(path.join(staticPath,'cloud-account-page.js'),'utf8').replace(/^import .*;\n/gm,'');ready=vm.runInContext('(async()=>{'+source+'})()',context)}
  else{component=context.createApplications({auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;component.render();try{return await fn()}finally{busy=false;component.render()}}});ready=Promise.resolve()}
  const control=id=>ids.get(id),dialog=control('applicationDialog'),form=dialog.querySelector('form');
  return {component,context,client,ids,control,dialog,form,calls,replies,publicCalls,publicReplies,authCalls,authReplies,ready,
    get list(){return control('selfApplications').children.at(-1)},
    get status(){return control('catalogAcquireStatus').textContent},
    start(){control('catalogAcquireStart').onclick()},submit(){form.onsubmit({preventDefault(){}})},
    dismiss(){dialog.children.at(-1).onclick()},
    changeAccount(next){state=next;client.signedIn=Boolean(next);component.render()},
    navigate(query){context.location.search=query;for(const fn of listeners.popstate||[])fn({})},
    async flush(){for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))},
  };
}
async function select(e,id='12'){await e.component.setCatalogIntent(id);await e.component.refresh()}
function posts(e){return e.calls.filter(c=>c.options.method==='POST')}

test('Positive BIGINT IDs are canonical strings and return parameters cannot redirect',()=>{
  const e=environment(),parse=e.context.readCatalogIntent;
  for(const id of ['1','9007199254740993','9223372036854775807'])assert.equal(parse('?acquire='+id),id);
  assert.equal(parse('?next=https://evil.invalid'),null);
  for(const value of ['0','01','-1','+1',' 1','1e2','1.0','9223372036854775808','9'.repeat(100),'https://evil.invalid','<script>'])assert.equal(parse('?acquire='+encodeURIComponent(value)),'',value);
  assert.equal(parse('?acquire=12&acquire=12'),'');assert.equal(parse('?acquire='),'');
  assert.equal(e.context.catalogIndividualId(12),null);
});

test('Selection is public, text-only, immutable, and does not create a draft until submitted',async()=>{
  const e=environment(),id='9007199254740993';e.publicReplies.push(guitar(id,{manufacturer:'<img src=x onerror=alert(1)>',profile:{secret:'PRIVATE'}}));await select(e,id);
  assert.equal(e.publicCalls.length,1);assert.deepEqual(JSON.parse(JSON.stringify(e.publicCalls[0].options)),{cache:'no-store',credentials:'omit',redirect:'error'});
  const text=e.control('catalogAcquireDetail');assert.match(text.textContent,/<img src=x/);assert.equal(text.children.length,0);assert.doesNotMatch(text.textContent,/PRIVATE/);
  assert.equal(e.control('applicationAcquire').tagName,'A');assert.equal(e.control('applicationAcquire').href,'/');
  e.start();assert.equal(e.dialog.open,true);assert.equal(posts(e).length,0);
  const input=e.control('application_individual_id');assert.equal(input.readOnly,true);assert.equal(input.value,id);input.value='8';
  e.replies.push(draft(id),{items:[draft(id)],can_write:true});e.submit();e.submit();await e.flush();
  assert.equal(posts(e).length,1);assert.deepEqual(JSON.parse(posts(e)[0].options.body),{kind:'acquire',individual_id:id});assert.equal(e.publicCalls.length,2);
  assert.match(e.dialog.children[1].textContent,/9007199254740993/);
});

test('Repeat Start clicks do not erase unsaved fields or create applications',async()=>{
  const e=environment();await select(e);e.start();e.control('application_body').value='Keep this note';e.start();
  assert.equal(e.control('application_body').value,'Keep this note');assert.equal(e.dialog.opens,1);assert.equal(posts(e).length,0);
});

for(const capability of [false,null,undefined,'true'])test(`Acquire fails closed with write capability ${String(capability)}`,async()=>{
  const e=environment();await e.component.setCatalogIntent('12');e.replies.push({items:[],can_write:capability});await e.component.refresh();e.start();e.submit();await e.flush();
  assert.equal(e.control('catalogAcquireStart').disabled,true);assert.equal(e.dialog.open,false);assert.equal(posts(e).length,0);
});

test('A new Acquire form cannot be submitted after read-only mode appears',async()=>{
  const e=environment();await select(e);e.start();e.replies.push({items:[],can_write:false});await e.component.refresh();e.submit();await e.flush();assert.equal(posts(e).length,0);assert.equal(e.control('applicationCreate').disabled,true);assert.equal(e.dialog.open,true);
});

for(const failure of [denied(403),denied(404),denied(503),new Error('offline')])test(`Unavailable public selection ${failure.httpStatus||failure.message} never creates an application`,async()=>{
  const e=environment();e.publicReplies.push(failure);await select(e);e.start();e.submit();await e.flush();assert.equal(posts(e).length,0);assert.equal(e.dialog.open,false);assert.equal(e.status,'catalog.acquire_unavailable');assert.equal(e.control('catalogAcquireLink').href,'/guitars/12');
});

for(const failure of [denied(403),denied(503),new Error('offline')])test(`Catalog becoming unavailable at submit (${failure.httpStatus||failure.message}) blocks creation despite prior write access`,async()=>{
  const e=environment();await select(e);e.start();e.publicReplies.push(failure);e.submit();await e.flush();assert.equal(posts(e).length,0);assert.equal(e.status,'catalog.acquire_unavailable');assert.equal(e.control('applicationCreate').disabled,true);if(failure.httpStatus!==403)assert.equal(e.dialog.children.at(-2).textContent,'catalog.acquire_unavailable');
});

for(const data of [guitar('13'),guitar(12),{id:'12'},guitar('12',{manufacturer:{html:'unsafe'}})])test('Malformed/mismatched catalog result cannot authorize Acquire',async()=>{
  const e=environment();e.publicReplies.push(data);await select(e);e.start();assert.equal(posts(e).length,0);assert.equal(e.dialog.open,false);assert.equal(e.status,'catalog.acquire_unavailable');
});

test('An older public response cannot replace a newer selection',async()=>{
  const e=environment(),old=deferred();e.publicReplies.push(old.promise);const first=e.component.setCatalogIntent('12');await e.component.setCatalogIntent('13');old.resolve(guitar('12'));await first;
  assert.match(e.control('catalogAcquireDetail').textContent,/SERIAL-13/);assert.doesNotMatch(e.control('catalogAcquireDetail').textContent,/SERIAL-12/);assert.equal(e.control('catalogAcquireLink').href,'/guitars/13');
});

for(const interruption of ['new intent','back','close','signout','other account'])test(`Draft validation interrupted by ${interruption} never POSTs or reopens the dialog`,async()=>{
  const e=environment(),check=deferred();await select(e);e.start();e.publicReplies.push(check.promise);e.submit();
  if(interruption==='new intent')await e.component.setCatalogIntent('13');else if(interruption==='back')await e.component.setCatalogIntent(null);else if(interruption==='close')e.dismiss();else e.changeAccount(interruption==='signout'?null:account('second'));
  check.resolve(guitar('12'));await e.flush();assert.equal(posts(e).length,0);assert.equal(e.dialog.open,false);
});

test('A completed creation after navigation refreshes the list without reopening or switching intent',async()=>{
  const e=environment(),created=deferred();await select(e);e.start();e.replies.push(created.promise);e.submit();await e.flush();assert.equal(posts(e).length,1);
  await e.component.setCatalogIntent('13');e.replies.push({items:[draft()],can_write:true});created.resolve(draft());await e.flush();assert.equal(e.dialog.open,false);assert.match(e.control('catalogAcquireDetail').textContent,/SERIAL-13/);assert.equal(e.list.children.length,1);
});

test('A delayed create result after sign-out never exposes private data to a later account',async()=>{
  const e=environment(),created=deferred();await select(e);e.start();e.replies.push(created.promise);e.submit();await e.flush();e.changeAccount(null);e.changeAccount(account('second'));created.resolve(draft());await e.flush();assert.equal(e.dialog.open,false);assert.equal(e.list.children.length,0);assert.equal(e.dialog.children[1].textContent,'');assert.equal(e.control('catalogAcquireStart').disabled,true);
});

test('An authorization rejection clears private application data while retaining only the public intent',async()=>{
  const e=environment();await select(e);e.replies.push({items:[draft()],can_write:true});await e.component.refresh();e.list.children[0].children[1].onclick();
  e.replies.push(denied(403));await e.component.refresh();assert.equal(e.list.children.length,0);assert.equal(e.dialog.open,false);assert.equal(e.dialog.children[1].textContent,'');assert.match(e.control('catalogAcquireDetail').textContent,/SERIAL-12/);assert.equal(e.control('catalogAcquireStart').disabled,true);
});

test('Guest sign-in, email verification and refreshed access preserve intent without automatic application writes',async()=>{
  const id='9223372036854775807',e=environment({initial:null,search:'?acquire='+id+'&next=https://evil.invalid',fullPage:true});await e.ready;await e.flush();assert.equal(e.status,'catalog.acquire_sign_in');assert.equal(e.control('catalogAcquireStart').disabled,true);
  e.control('email').value='member@example.invalid';e.control('password').value='password';await e.control('cloudAccountForm').onsubmit({preventDefault(){}});await e.flush();assert.equal(e.status,'catalog.acquire_verify');assert.equal(posts(e).length,0);
  await e.control('sendVerification').onclick();assert.deepEqual(JSON.parse(JSON.stringify(e.authCalls.at(-1).options)),{language:'en',acquire:id});
  await e.control('refreshVerification').onclick();await e.flush();assert.equal(e.status,'catalog.acquire_ready');assert.equal(e.control('catalogAcquireStart').disabled,false);assert.equal(posts(e).length,0);
  assert.equal(e.context.location.search,'?acquire='+id+'&next=https://evil.invalid');e.start();assert.equal(e.control('application_individual_id').value,id);
  await e.control('signOut').onclick();await e.flush();assert.equal(e.dialog.open,false);assert.equal(e.dialog.children[1].textContent,'');assert.equal(e.control('application_individual_id').value,'');assert.equal(e.status,'catalog.acquire_sign_in');assert.equal(posts(e).length,0);
});

test('Registration and incomplete-enrollment retry retain selection and never automatically draft',async()=>{
  const e=environment({initial:null,search:'?acquire=12',fullPage:true});await e.ready;e.authReplies.push({registration_required:true});await e.control('cloudAccountForm').onsubmit({preventDefault(){}});await e.flush();
  assert.equal(e.control('credentialsFields').hidden,true);assert.equal(e.control('profileFields').hidden,false);assert.equal(e.status,'catalog.acquire_sign_in');
  e.control('displayName').value='Member';e.control('accountType').value='user';e.control('terms').checked=e.control('privacy').checked=true;await e.control('cloudAccountForm').onsubmit({preventDefault(){}});await e.flush();
  assert.equal(e.authCalls.at(-1).name,'register');assert.equal(e.authCalls.at(-1).credentials,undefined);assert.equal(e.status,'catalog.acquire_verify');assert.equal(posts(e).length,0);assert.equal(e.context.location.search,'?acquire=12');
});

test('Create Account mode switches retain URL selection',async()=>{
  const e=environment({initial:null,search:'?acquire=12',fullPage:true});await e.ready;e.control('showRegistration').onclick();e.control('showSignIn').onclick();e.control('showRegistration').onclick();await e.control('cloudAccountForm').onsubmit({preventDefault(){}});await e.flush();
  assert.equal(e.authCalls[0].name,'register');assert.equal(e.context.location.search,'?acquire=12');assert.equal(posts(e).length,0);
});

test('Account page handles Back/Forward query changes and malformed duplicate intent without redirecting',async()=>{
  const e=environment({search:'?acquire=12',fullPage:true});await e.ready;await e.flush();e.start();e.navigate('');await e.flush();assert.equal(e.control('catalogAcquireIntent').hidden,true);assert.equal(e.dialog.open,false);
  e.navigate('?acquire=13');await e.flush();assert.equal(e.control('catalogAcquireIntent').hidden,false);assert.match(e.control('catalogAcquireDetail').textContent,/SERIAL-13/);
  const count=e.publicCalls.length;e.navigate('?acquire=13&acquire=https://evil.invalid');await e.flush();assert.equal(e.status,'catalog.acquire_invalid');assert.equal(e.publicCalls.length,count);assert.equal(e.control('catalogAcquireLink').href,'/');assert.equal(posts(e).length,0);
});


test('Verified Admin catalog validation uses a fresh authorized read before Acquire',async()=>{
  const admin={...account(),user:{...account().user,role:'admin'}},e=environment({initial:admin});await select(e);e.start();e.replies.push(draft(),{items:[draft()],can_write:true});e.submit();await e.flush();
  assert.equal(e.publicCalls.length,2);assert.equal(e.publicCalls.every(call=>call.authorized===true&&call.verified===true),true);assert.equal(posts(e).length,1);
});

test('A denied bearer catalog read clears current private data and is never retried as Guest',async()=>{
  const e=environment();e.replies.push({items:[draft()],can_write:true});await e.component.refresh();assert.equal(e.list.children.length,1);
  e.publicReplies.push(denied(401));await e.component.setCatalogIntent('12');assert.equal(e.publicCalls.length,1);assert.equal(e.publicCalls[0].authorized,true);assert.equal(e.list.children.length,0);assert.equal(e.status,'catalog.acquire_unavailable');assert.equal(posts(e).length,0);
});

test('A delayed catalog denial cannot clear a later account application list',async()=>{
  const e=environment(),old=deferred();e.publicReplies.push(old.promise);const pending=e.component.setCatalogIntent('12');e.changeAccount(account('second'));e.replies.push({items:[{...draft('13'),serial:'CURRENT PRIVATE'}],can_write:true});await e.component.refresh();old.resolve(denied(401));await pending;
  assert.equal(e.list.children.length,1);assert.match(e.list.children[0].children[0].textContent,/CURRENT PRIVATE/);assert.equal(e.publicCalls.length,1);
});


test('Restored verified Admin retries the selection with identity after anonymous admin-only denial',async()=>{
  const admin={...account(),user:{...account().user,role:'admin'}},e=environment({initial:admin,search:'?acquire=12',fullPage:true,catalogReplies:[denied(403)]});await e.ready;await e.flush();
  assert.equal(e.publicCalls.length,2);assert.equal(e.publicCalls[0].authorized,undefined);assert.equal(e.publicCalls[1].authorized,true);assert.equal(e.status,'catalog.acquire_ready');assert.equal(e.control('catalogAcquireStart').disabled,false);assert.equal(posts(e).length,0);
});


test('Explicit verification refresh rechecks a temporarily unavailable selection for the same verified account',async()=>{
  const e=environment({search:'?acquire=12',fullPage:true,catalogReplies:[denied(503),denied(503)]});await e.ready;await e.flush();assert.equal(e.status,'catalog.acquire_unavailable');const count=e.publicCalls.length;
  await e.control('refreshVerification').onclick();await e.flush();assert.equal(e.publicCalls.length,count+1);assert.equal(e.publicCalls.at(-1).authorized,true);assert.equal(e.status,'catalog.acquire_ready');assert.equal(posts(e).length,0);
});
