const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const tick=()=>new Promise(r=>setImmediate(r));
function setup(options={}){
 class Element{
  constructor(){this.children=[];this.hidden=false;this.dataset={};this._text='';this.classList={remove(){},toggle(){}}}
  append(...children){this.children.push(...children)} prepend(...children){this.children.unshift(...children)}
  replaceChildren(...children){this.children=children;this._text=''}
  set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(c=>typeof c==='string'?c:c.textContent).join('')}
  before(...nodes){this.beforeNodes=nodes}setAttribute(){}remove(){}
  querySelector(selector){return this.children.find(c=>c.className===selector.slice(1))||null}
 }
 const ids={};for(const id of ['accountHub','shellNotifications','shellGuestSpacer','shellAccountLinks','shellProfile','accountLink'])ids[id]=new Element();
 const old=new Element(),actions=new Element();ids.accountHub.querySelector=s=>s==='.account-hub-user'?old:actions;
 const listeners={},requests=[],revoked=[];let state={identity:{email_verified:true},user:{app_user_id:'alice',display_name:'Alice'}};
 const context={Blob,document:{getElementById:id=>ids[id],createElement:()=>new Element(),createTextNode:t=>({textContent:t}),documentElement:{dataset:{}}},window:{addEventListener:(k,f)=>listeners[k]=f},URL:{revokeObjectURL:v=>revoked.push(v),createObjectURL:()=> 'blob:fixture'},YGCI18n:{t:k=>k}};
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-hub.js'),'utf8').replace('export function createAccountHub','function createAccountHub')+';globalThis.factory=createAccountHub;',context);
 const hub=context.factory({auth:()=>({authorizedFetch:url=>{const d=deferred();requests.push({url,...d});return d.promise}}),state:()=>state,...options});
 return {hub,ids,old,requests,revoked,listeners,setState:v=>state=v,user:()=>old.beforeNodes[0],summary:()=>old.beforeNodes[1]};
}
const unavailable={ok:false,status:503,headers:{get:()=>null}};
test('known identity stays visible while supplemental requests are pending or fail',async()=>{
 const e=setup();e.hub.render();assert.equal(e.user().hidden,false);assert.match(e.user().textContent,/Alice/);assert.equal(e.summary().hidden,false);assert.equal(e.requests.length,4);
 e.requests.forEach(r=>r.resolve(unavailable));await tick();assert.equal(e.user().hidden,false);assert.match(e.user().textContent,/Alice/);
});
test('a stale avatar read cannot overwrite the new identity notification count',async()=>{
 const e=setup();e.hub.render();const blob=deferred();
 for(const r of e.requests){r.resolve(r.url.includes('avatar')?{ok:true,headers:{get:()=> 'image/jpeg'},blob:()=>blob.promise}:r.url.includes('notifications')?{ok:true,json:async()=>({unread_count:'99'})}:unavailable)}
 await tick();e.setState({identity:{email_verified:true},user:{app_user_id:'bob',display_name:'Bob'}});e.hub.render();assert.match(e.user().textContent,/Bob/);assert.equal(e.user().hidden,false);
 e.requests.slice(4).forEach(r=>r.resolve(r.url.includes('notifications')?{ok:true,json:async()=>({unread_count:'2'})}:unavailable));await tick();
 blob.resolve({size:32});await tick();e.hub.render();assert.match(e.ids.shellNotifications.textContent,/2$/);assert.doesNotMatch(e.ids.shellNotifications.textContent,/99/);assert.match(e.user().textContent,/Bob/);
});
test('signout hides private identity and ignores pending responses',async()=>{
 const e=setup();e.hub.render();e.setState(null);e.hub.render();assert.equal(e.user().hidden,true);assert.equal(e.summary().hidden,true);assert.equal(e.ids.shellNotifications.hidden,true);
 e.requests.forEach(r=>r.resolve(unavailable));await tick();assert.equal(e.user().hidden,true);assert.equal(e.user().textContent,'');
});

test('Concurrent hub refresh shares its current load; ready reuses completed state and explicit refresh reads anew',async()=>{
 const e=setup();e.hub.render();const one=e.hub.refresh(),two=e.hub.refresh();assert.equal(one,two);assert.equal(e.requests.length,4);
 e.requests.forEach(r=>r.resolve(unavailable));await one;await e.hub.ready();assert.equal(e.requests.length,4);
 const next=e.hub.refresh();assert.equal(e.requests.length,8);e.requests.slice(4).forEach(r=>r.resolve(unavailable));await next;
});


test('Profile hub consumes one avatar and notification source without fetching them twice',async()=>{
 const e=setup({readAvatar:false,readNotifications:false});e.hub.render();assert.equal(e.requests.length,2);assert.ok(e.requests.every(r=>!r.url.includes('avatar')&&!r.url.includes('notifications')));
 e.requests.forEach(r=>r.resolve(unavailable));await e.hub.ready();
 e.listeners['ygc-self-avatar']({detail:{actor:'alice',blob:new Blob(['image'],{type:'image/jpeg'})}});
 assert.equal(e.user().children[0].src,'blob:fixture');
 e.listeners['ygc-notification-count']({detail:{actor:'alice',count:'17'}});assert.match(e.ids.shellNotifications.textContent,/17$/);
 e.listeners['ygc-self-avatar']({detail:{actor:'bob',blob:null}});assert.equal(e.user().children[0].src,'blob:fixture');
 e.listeners['ygc-self-avatar']({detail:{actor:'alice',blob:null}});assert.equal(e.user().children[0].src,'/assets/no-icon.svg');assert.equal(e.revoked.length,1);
 e.setState(null);e.hub.render();e.listeners['ygc-self-avatar']({detail:{actor:'alice',blob:new Blob(['old'],{type:'image/jpeg'})}});assert.equal(e.user().hidden,true);assert.equal(e.user().children[0].src,'/assets/no-icon.svg');
});
