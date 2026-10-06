const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

const account=id=>({user:{app_user_id:id},identity:{email_verified:true}});
const application=(status='error',serial='FIRST')=>({revision:'c'.repeat(32),kind:'acquire',serial,individual_id:'12',status,photos:[],expires_at:2000000000,claim_id:null,reasons:[]});
const page=(...items)=>({items});
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
    return {ok:true,json:async()=>reply};
  }};
  const context=vm.createContext({document,URL,Intl,Date,console,CustomEvent:class{constructor(type){this.type=type}},YGCI18n:{t:key=>key}});context.window=context;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/overlays.js'),'utf8'),context);
  const args={auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;component.render();try{return await fn()}finally{busy=false;component.render()}}};
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-applications.js'),'utf8').replace('export function','function');
  vm.runInContext(source+';globalThis.create=createApplications;',context);component=context.create(args);
  const dialog=ids.get('applicationDialog'),list=root.children.at(-1),retry=ids.get('applicationRetry');
  return {component,calls,replies,root,dialog,list,retry,
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
