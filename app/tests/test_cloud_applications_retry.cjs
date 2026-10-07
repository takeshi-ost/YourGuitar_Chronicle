const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

const account=id=>({user:{app_user_id:id},identity:{email_verified:true}});
const application=(status='error',serial='FIRST')=>({revision:'c'.repeat(32),kind:'acquire',serial,individual_id:'12',status,photos:[],expires_at:2000000000,claim_id:null,reasons:[]});
const page=(...items)=>({items,can_write:true});
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
function environment(){
  const ids=new Map(),listeners={};
  class Element{
    constructor(tag='div'){
      this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.style={};this.value='';this.files=[];this.hidden=false;this.open=false;this.disabled=false;this.textContent='';this.tabIndex=0;this.isConnected=true;
      this.classList={add(){},remove(){}};
    }
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}
    setAttribute(key,value){this[key]=value}removeAttribute(key){delete this[key]}hasAttribute(key){return key in this}
    addEventListener(key,fn){(this.listeners[key]??=[]).push(fn)}dispatchEvent(event){for(const listener of this.listeners[event.type]||[])listener(event)}
    reset(){}focus(){document.activeElement=this}closest(){return null}
    all(){return this.children.flatMap(n=>[n,...n.all()])}
    contains(value){return this===value||this.all().includes(value)}
    querySelectorAll(selector){const tags=selector.split(',').filter(t=>/^[a-z]+$/.test(t)).map(t=>t.toUpperCase());return this.all().filter(n=>tags.includes(n.tagName))}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null}
    getClientRects(){return this.hidden?[]:[this.getBoundingClientRect()]}
    getBoundingClientRect(){return {left:20,right:600,top:20,bottom:600}}
    showModal(){this.open=true;this.opens=(this.opens||0)+1}close(){this.open=false}
  }
  const document={body:new Element('body'),createElement:tag=>new Element(tag),getElementById:id=>ids.get(id),addEventListener(key,fn){(listeners[key]??=[]).push(fn)}};
  const root=new Element('section');root.id='selfApplications';document.body.append(root);
  let state=account('first'),busy=false,component;
  const calls=[],replies=[];
  const client={authorizedFetch:async(url,options={},verified)=>{
    calls.push({url,options,verified,account:state?.user?.app_user_id});
    assert.ok(replies.length,'Every request must have an explicit fixture response');
    const reply=await replies.shift();if(reply instanceof Error)throw reply;
    return reply?.httpStatus?{ok:false,status:reply.httpStatus,json:async()=>({detail:{code:reply.code}})}:{ok:true,json:async()=>reply,blob:async()=>new Blob(['photo'])};
  }};
  const context=vm.createContext({document,URL,Blob,Intl,Date,console,CustomEvent:class{constructor(type){this.type=type}},YGCI18n:{t:key=>key}});context.window=context;context.addEventListener=(key,fn)=>(listeners[key]??=[]).push(fn);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/overlays.js'),'utf8'),context);
  const args={auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;component.render();try{return await fn()}finally{busy=false;component.render()}}};
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-applications.js'),'utf8').replaceAll('export function','function');
  vm.runInContext(source+';globalThis.create=createApplications;',context);component=context.create(args);
  const dialog=ids.get('applicationDialog'),list=root.children.at(-1),retry=ids.get('applicationRetry');
  return {component,calls,replies,root,dialog,list,retry,ids,
    focus(){for(const listener of listeners.focus||[])listener()},
    async start(){replies.push(page(application()));await component.refresh();list.children[0].children[1].onclick();retry.onclick();assert.equal(calls.length,1)},
    confirm(){retry.onclick()},
    dismiss(kind){
      if(kind==='close')dialog.children.at(-1).onclick();
      else{const event={target:dialog,key:kind==='escape'?'Escape':undefined,clientX:1,clientY:1,preventDefault(){},stopImmediatePropagation(){}};for(const listener of listeners[kind==='escape'?'keydown':'click']||[])listener(event)}
      assert.equal(dialog.open,false);
    },
    changeAccount(value,{clear=true}={}){if(clear)component.clear();state=value;component.render()},
    listText(){return list.children.map(item=>item.children[0].textContent).join('\n')},
    async flush(){for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))},
  };
}

for(const dismissal of ['escape','close','backdrop']){
  test(`Retry completed after ${dismissal} refreshes the list without reopening the dialog`,async()=>{
    const e=environment(),post=deferred();await e.start();
    e.replies.push(post.promise,page(application('pending')));e.confirm();e.confirm();
    assert.equal(e.calls.length,2);assert.equal(e.calls[1].url,'/api/auth/applications/'+application().revision+'/retry');
    assert.equal(e.calls[1].options.method,'POST');assert.equal(e.calls[1].verified,true);assert.deepEqual(JSON.parse(e.calls[1].options.body),{});
    e.dismiss(dismissal);post.resolve(application('pending'));await e.flush();
    assert.match(e.listText(),/status_pending/);assert.doesNotMatch(e.listText(),/status_error/);
    assert.equal(e.dialog.open,false);assert.equal(e.dialog.opens,1);assert.equal(e.calls.length,3);
    e.list.children[0].children[1].onclick();assert.equal(e.retry.hidden,true);
  });
  test(`Closing with ${dismissal} during the retry list refresh keeps the refreshed status`,async()=>{
    const e=environment(),refresh=deferred();await e.start();
    e.replies.push(application('pending'),refresh.promise);e.confirm();await e.flush();assert.equal(e.calls.length,3);
    e.dismiss(dismissal);refresh.resolve(page(application('pending')));await e.flush();
    assert.match(e.listText(),/status_pending/);assert.equal(e.dialog.open,false);assert.equal(e.dialog.opens,1);
  });
}

test('An undismissed retry updates details and cannot be posted again after success',async()=>{
  const e=environment();await e.start();e.replies.push(application('pending'),page(application('pending')));e.confirm();await e.flush();
  assert.equal(e.dialog.open,true);assert.match(e.dialog.children[1].textContent,/status_pending/);assert.equal(e.retry.hidden,true);
  e.confirm();await e.flush();assert.equal(e.calls.length,3);
});

for(const transition of ['other account','sign out','sign out and return','account round trip','other account without clear']){
  test(`A delayed retry is discarded after ${transition}`,async()=>{
    const e=environment(),post=deferred();await e.start();e.replies.push(post.promise);e.confirm();
    if(transition.startsWith('other account'))e.changeAccount(account('second'),{clear:transition!=='other account without clear'});
    else if(transition==='account round trip'){e.changeAccount(account('second'));e.changeAccount(account('first'))}
    else{e.changeAccount(null);if(transition==='sign out and return')e.changeAccount(account('first'))}
    if(transition!=='sign out'){e.replies.push(page(application('accepted','CURRENT')));await e.component.refresh()}
    const callCount=e.calls.length;post.resolve(application('pending'));await e.flush();
    assert.equal(e.calls.length,callCount,'A stale retry must not start a new-account list refresh');
    if(transition==='sign out')assert.equal(e.list.children.length,0);
    else{assert.match(e.listText(),/CURRENT.*status_accepted/);assert.doesNotMatch(e.listText(),/FIRST|status_pending/)}
    if(transition!=='other account without clear')assert.equal(e.dialog.open,false);
  });
}

for(const transition of ['other account','sign out','sign out and return']){
  test(`A delayed retry list refresh is discarded after ${transition}`,async()=>{
    const e=environment(),refresh=deferred();await e.start();e.replies.push(application('pending'),refresh.promise);e.confirm();await e.flush();
    e.changeAccount(transition==='other account'?account('second'):null);
    if(transition==='sign out and return')e.changeAccount(account('first'));
    if(transition!=='sign out'){e.replies.push(page(application('accepted','CURRENT')));await e.component.refresh()}
    refresh.resolve(page(application('pending')));await e.flush();
    if(transition==='sign out')assert.equal(e.list.children.length,0);
    else assert.match(e.listText(),/CURRENT.*status_accepted/);
    assert.equal(e.dialog.open,false);
  });
}

test('Repeated refreshes keep the newest response when an older response arrives last',async()=>{
  const e=environment(),older=deferred();e.replies.push(older.promise,page(application('processing')));
  const first=e.component.refresh();await e.component.refresh();older.resolve(page(application('error')));await first;
  assert.match(e.listText(),/status_processing/);assert.doesNotMatch(e.listText(),/status_error/);
});

const denied=(status=403,code)=>({httpStatus:status,code});
async function open(e,status='pending',can_write=true){
  const row={...application(status),photos:['closeup','overview']};
  e.replies.push({items:[row],can_write});await e.component.refresh();e.list.children[0].children[1].onclick();return row;
}
function control(e,id){return e.ids.get(id)}
function form(e){return e.dialog.querySelector('form')}
function message(e){return e.dialog.children.at(-2).textContent}

for(const status of ['draft','pending','processing','error']){
  test(`Read-only ${status} applications keep details/photos while all mutations are blocked locally`,async()=>{
    const e=environment();await open(e,status,false);
    for(const id of ['applicationListing','catalogAcquireStart','applicationCreate','applicationSubmit','applicationCancel','applicationRetry','application_closeup','application_overview'])assert.equal(control(e,id).disabled,true,id);
    assert.equal(form(e).children[0].disabled,true);
    for(const id of ['applicationListing','catalogAcquireStart','applicationSubmit','applicationCancel','applicationRetry'])control(e,id).onclick();
    form(e).onsubmit({preventDefault(){}});await e.flush();assert.equal(e.calls.length,1,'No mutation handler may start a request');
    const photos=e.dialog.querySelectorAll('fieldset')[1],view=photos.children[2];assert.equal(photos.disabled,false);assert.equal(view.disabled,false);
    e.replies.push({});view.onclick();await e.flush();assert.equal(e.calls.length,2);assert.match(e.calls[1].url,/photos\/closeup$/);assert.equal(e.calls[1].options.method,undefined);
    assert.equal(photos.children[3].hidden,false);assert.match(e.listText(),/FIRST/);assert.equal(e.dialog.open,true);
  });
}

for(const capability of [undefined,null,'true',1,false]){
  test(`Missing/invalid write capability ${String(capability)} fails closed`,async()=>{
    const e=environment();await open(e,'pending',capability===undefined?null:capability);
    if(capability===undefined){e.replies.push({items:[application('pending')]});await e.component.refresh()}
    assert.equal(control(e,'applicationCancel').disabled,true);control(e,'applicationCancel').onclick();await e.flush();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,0);
  });
}

test('Initial application creation is blocked until a successful permission-bearing read',async()=>{
  const e=environment();e.component.render();control(e,'applicationListing').onclick();form(e).onsubmit({preventDefault(){}});await e.flush();assert.equal(e.calls.length,0);assert.equal(e.dialog.open,false);
});

test('Mode refresh updates an open draft without erasing its fields and normal restores mutations',async()=>{
  const e=environment(),row=await open(e,'draft');control(e,'application_body').value='Unsaved note';
  e.replies.push({items:[row],can_write:false});await control(e,'applicationRefresh').onclick();await e.flush();
  assert.equal(e.dialog.open,true);assert.equal(control(e,'application_body').value,'Unsaved note');assert.equal(control(e,'applicationSubmit').disabled,true);assert.match(e.listText(),/FIRST/);
  e.replies.push({items:[row],can_write:true});e.focus();await e.flush();assert.equal(control(e,'applicationSubmit').disabled,false);assert.equal(e.dialog.open,true);assert.equal(control(e,'application_body').value,'Unsaved note');
});

test('A read-only transition invalidates a prepared retry confirmation',async()=>{
  const e=environment(),row=await open(e,'error');e.retry.onclick();assert.equal(e.retry.textContent,'applications.retry_confirm');
  e.replies.push({items:[row],can_write:false});await e.component.refresh();e.retry.onclick();
  e.replies.push({items:[row],can_write:true});await e.component.refresh();e.retry.onclick();await e.flush();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,0);assert.equal(e.retry.textContent,'applications.retry_confirm');
});

for(const dismissal of [null,'escape','close','backdrop']){
  test(`Service-denied cancellation revalidates and keeps the list after ${dismissal||'no dismissal'}`,async()=>{
    const e=environment(),post=deferred(),row=await open(e);e.replies.push(post.promise,{items:[row],can_write:false});control(e,'applicationCancel').onclick();
    if(dismissal)e.dismiss(dismissal);post.resolve(denied(403,'service_restricted'));await e.flush();
    assert.equal(e.calls.length,3);assert.equal(e.calls[1].options.method,'POST');assert.equal(e.calls[2].options.method,undefined);
    assert.match(e.listText(),/FIRST.*status_pending/);assert.equal(e.dialog.open,!dismissal);assert.equal(control(e,'applicationCancel').disabled,true);
    assert.equal(e.root.children.at(-2).textContent,'applications.service_restricted');
    control(e,'applicationCancel').onclick();await e.flush();assert.equal(e.calls.length,3);
  });
}

for(const status of [400,409,503]){
  test(`Cancellation HTTP ${status} retains the current application list and shows the error`,async()=>{
    const e=environment();await open(e);e.replies.push(denied(status));control(e,'applicationCancel').onclick();await e.flush();
    assert.match(e.listText(),/FIRST.*status_pending/);assert.equal(e.dialog.open,true);assert.ok(message(e));assert.equal(e.calls.length,2);
  });
}

for(const failure of [denied(401),denied(403),denied(403,'service_restricted'),denied(503)]){
  test(`Service-denied cancellation clears private rows when recovery fails ${failure.httpStatus}/${failure.code||''}`,async()=>{
    const e=environment();await open(e);e.replies.push(denied(403,'service_restricted'),failure);control(e,'applicationCancel').onclick();await e.flush();
    assert.equal(e.list.children.length,0);assert.equal(e.dialog.open,false);assert.equal(e.dialog.children[1].textContent,'');assert.equal(control(e,'applicationCancel').disabled,true);
  });
}

for(const status of [401,403]){
  test(`A generic authorization ${status} clears private content even after dialog dismissal`,async()=>{
    const e=environment(),post=deferred();await open(e);e.replies.push(post.promise);control(e,'applicationCancel').onclick();e.dismiss('close');post.resolve(denied(status));await e.flush();assert.equal(e.list.children.length,0);assert.equal(e.calls.length,2);
  });
}

for(const failure of [denied(403,'service_restricted'),denied(401),denied(503)]){
  test(`A delayed denial ${failure.httpStatus}/${failure.code||''} never affects a different account`,async()=>{
    const e=environment(),post=deferred();await open(e);e.replies.push(post.promise);control(e,'applicationCancel').onclick();e.changeAccount(account('second'),{clear:false});
    e.replies.push(page(application('accepted','CURRENT')));await e.component.refresh();const calls=e.calls.length;post.resolve(failure);await e.flush();assert.equal(e.calls.length,calls);assert.match(e.listText(),/CURRENT/);assert.doesNotMatch(e.listText(),/FIRST/);assert.equal(e.dialog.open,false);
  });
}

for(const result of [page(application('pending')),denied(403),denied(503)]){
  test(`Stale recovery response ${result.httpStatus||'success'} is discarded after sign-out and return`,async()=>{
    const e=environment(),recovery=deferred();await open(e);e.replies.push(denied(403,'service_restricted'),recovery.promise);control(e,'applicationCancel').onclick();await e.flush();
    e.changeAccount(null);e.changeAccount(account('first'));e.replies.push(page(application('accepted','CURRENT')));await e.component.refresh();recovery.resolve(result);await e.flush();assert.match(e.listText(),/CURRENT.*status_accepted/);assert.equal(e.dialog.open,false);assert.equal(control(e,'applicationListing').disabled,false);
  });
}

test('A stale failing list refresh cannot erase a newer successful list or permissions',async()=>{
  const e=environment(),old=deferred();e.replies.push(old.promise,page(application('pending','CURRENT')));const first=e.component.refresh();await e.component.refresh();old.resolve(denied(403));await first;assert.match(e.listText(),/CURRENT/);assert.equal(control(e,'applicationListing').disabled,false);
});

test('Normal-mode cancellation succeeds once after returning from read-only',async()=>{
  const e=environment(),row=await open(e,'pending',false);e.replies.push({items:[row],can_write:true});await e.component.refresh();
  e.replies.push({...row,status:'cancelled'},page({...row,status:'cancelled'}));control(e,'applicationCancel').onclick();control(e,'applicationCancel').onclick();await e.flush();
  assert.match(e.listText(),/status_cancelled/);assert.equal(control(e,'applicationCancel').hidden,true);assert.equal(e.calls.filter(c=>c.options.method==='POST').length,1);
});

test('Successful cancellation after dismissal still refreshes the list without reopening details',async()=>{
  const e=environment(),post=deferred(),row=await open(e);e.replies.push(post.promise,page({...row,status:'cancelled'}));control(e,'applicationCancel').onclick();e.dismiss('close');post.resolve({...row,status:'cancelled'});await e.flush();assert.match(e.listText(),/status_cancelled/);assert.equal(e.dialog.open,false);
});

for(const kind of ['Listing']){
  test(`An already-open new ${kind} form cannot submit after a read-only transition`,async()=>{
    const e=environment();e.replies.push(page());await e.component.refresh();control(e,'application'+kind).onclick();
    e.replies.push({items:[],can_write:false});await e.component.refresh();form(e).onsubmit({preventDefault(){}});await e.flush();
    assert.equal(e.calls.length,2);assert.equal(control(e,'applicationCreate').disabled,true);assert.equal(e.dialog.open,true);
  });
}

for(const transition of ['read-only','sign-out']){
  test(`Photo submission stops between uploads after ${transition}`,async()=>{
    const e=environment(),upload=deferred(),row=await open(e,'draft');
    for(const role of ['closeup','overview'])control(e,'application_'+role).files=[{size:10,type:'image/png'}];
    e.replies.push(upload.promise);control(e,'applicationSubmit').onclick();assert.equal(e.calls.length,2);
    if(transition==='sign-out')e.changeAccount(null);
    else{e.replies.push({items:[row],can_write:false});await e.component.refresh()}
    const calls=e.calls.length;upload.resolve(row);await e.flush();assert.equal(e.calls.length,calls);assert.equal(e.calls.filter(c=>c.options.method==='POST').length,1);
  });
}

test('Delayed private photo data is discarded and never displayed in a different account',async()=>{
  const e=environment(),photo=deferred();await open(e);const photos=e.dialog.querySelectorAll('fieldset')[1];e.replies.push(photo.promise);photos.children[2].onclick();e.changeAccount(account('second'),{clear:false});photo.resolve({});await e.flush();assert.equal(photos.children[3].hidden,true);assert.equal(photos.children[3].src,undefined);assert.equal(e.list.children.length,0);assert.equal(e.dialog.children[1].textContent,'');
});

test('Applicant sees manual Admin reason separately from retained AI reasons, with text escaping and teardown',async()=>{
  const e=environment(),data={...application('rejected'),reasons:['Original AI reason <img src=x>'],admin_review:{at:'2026-10-07',operation:'reject',reason:'Manual rejection <script>alert(1)</script>',actor:'admin'}};
  e.replies.push(page(data));await e.component.refresh();e.list.children[0].children[1].onclick();
  const review=control(e,'applicationAdminReview');assert.equal(review.hidden,false);assert.match(review.textContent,/applications.admin_review/);assert.match(review.textContent,/Manual rejection <script>/);assert.equal(review.children.length,0);
  assert.match(e.dialog.children[1].textContent,/applications.ai_reasons.*\nOriginal AI reason/);assert.doesNotMatch(e.dialog.children[1].textContent,/Manual rejection/);
  e.dismiss('escape');assert.equal(review.hidden,true);assert.equal(review.textContent,'');
});
