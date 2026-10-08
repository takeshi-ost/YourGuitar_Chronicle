const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-member-icons.js'),'utf8').replace(/export /g,'');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function environment(){
 const events={},documentEvents={},requests=[],revoked=[],made=[],pending=[];
 let owner='a',allowed=true,timer;
 const element=()=>({isConnected:true,textContent:'',children:[],replaceChildren(...nodes){this.children=nodes;this.textContent=''},addEventListener(){},contains(node){return this.children.includes(node)}});
 const document={hidden:false,createElement:element,addEventListener(name,fn){documentEvents[name]=fn}};
 const window={URL:{createObjectURL(blob){const url='blob:synthetic-'+made.length;made.push(url);return url},revokeObjectURL(url){revoked.push(url)}},AbortController,setInterval(fn){timer=fn;return 1},clearInterval(){},addEventListener(name,fn){events[name]=fn}};
 const auth={authorizedFetch(url,options,verified){requests.push({url,options,verified});return new Promise(resolve=>pending.push(resolve))}};
 const context=vm.createContext({queueMicrotask});vm.runInContext(code+';globalThis.make=createMemberIcons;',context);
 const icons=context.make({document,window,auth:()=>auth,identity:()=>owner,eligible:()=>allowed});
 const response=(status=200,type='image/jpeg')=>({ok:status===200,status,headers:{get:()=>type},blob:async()=>({size:10})});
 return {icons,element,requests,revoked,made,pending,response,events,documentEvents,document,change(id){owner=id},deny(){allowed=false},timer:()=>timer()};
}
test('member images use authenticated no-store fetch, blob only and revoke on clear',async()=>{
 const e=environment(),host=e.element();e.icons.mount(host,'2');await tick();
 const r=e.requests[0];assert.equal(r.url,'/api/auth/members/2/avatar');assert.equal(r.options.cache,'no-store');assert.equal(r.options.credentials,'omit');assert.equal(r.options.redirect,'error');assert.equal(r.verified,true);
 e.pending.shift()(e.response());await tick();assert.equal(host.children[0].src,'blob:synthetic-0');
 e.icons.clear();assert.equal(host.textContent,'♙');assert.deepEqual(e.revoked,e.made);
});
test('late image after logout or actor switch never renders or creates a URL',async()=>{
 for(const mode of ['logout','switch']){const e=environment(),host=e.element();e.icons.mount(host,'2');await tick();if(mode==='logout'){e.deny();e.icons.clear()}else e.change('b');e.pending.shift()(e.response());await tick();assert.equal(e.made.length,0);assert.equal(host.children.length,0)}
});
test('revocation refresh removes old bytes before denial, including delayed old responses',async()=>{
 const e=environment(),host=e.element();e.icons.mount(host,'2');await tick();const late=e.pending.shift();e.icons.refresh();await tick();e.pending.shift()(e.response(404));late(e.response());await tick();assert.equal(e.made.length,0);
 e.icons.refresh();await tick();e.pending.shift()(e.response());await tick();e.icons.refresh();assert.equal(host.children.length,0);assert.equal(e.revoked.length,1);await tick();e.pending.shift()(e.response(403));await tick();assert.equal(host.textContent,'♙');
});
test('hidden page clears image; focus and periodic validation refetch without cache',async()=>{
 const e=environment(),host=e.element();e.icons.mount(host,'2');await tick();e.pending.shift()(e.response());await tick();e.events.blur();assert.equal(e.revoked.length,1);e.events.focus();await tick();e.pending.shift()(e.response());await tick();e.timer();assert.equal(e.revoked.length,2);await tick();e.pending.shift()(e.response(404));await tick();assert.equal(host.children.length,0);
});
test('image queue bounds concurrent requests and rejects foreign MIME',async()=>{
 const e=environment();for(let i=1;i<=6;i++)e.icons.mount(e.element(),String(i));await tick();assert.equal(e.requests.length,4);e.pending.shift()(e.response(200,'text/html'));await tick();assert.equal(e.requests.length,5);assert.equal(e.made.length,0);e.icons.clear();for(const resolve of e.pending)resolve(e.response());await tick();assert.equal(e.made.length,0);
});
