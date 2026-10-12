const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 class E{constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.hidden=false}append(...xs){this.children.push(...xs)}replaceChildren(...xs){this.children=xs}setAttribute(){}querySelectorAll(tag){return this.all().filter(x=>x.tag===tag)}set innerHTML(_){throw Error('Never insert HTML')}all(){return this.children.flatMap(x=>typeof x==='string'?[]:[x,...x.all()])}}
 const root=new E('section'),document={createElement:tag=>new E(tag)},context=vm.createContext({document,YGCI18n:{t:k=>k}});
 vm.runInContext(fs.readFileSync(__dirname+'/../src/ygc/static/cloud-owner-acquire-inbox.js','utf8').replace('export function','function'),context);
 let state={user:{app_user_id:'a',status:'active'},identity:{email_verified:true}},busy=false;const replies=[],calls=[],opens=[];
 const api=context.createOwnerAcquireInbox({root,state:()=>state,busy:()=>busy,auth:()=>({authorizedFetch:async(...args)=>{calls.push(args);return await replies.shift()}}),openOwner:(...args)=>opens.push(args)});
 return {root,api,replies,calls,opens,setState:s=>state=s,setBusy:b=>busy=b,buttons:()=>root.all().filter(x=>x.tag==='button')};
}
const row=(id='1',extra={})=>({id,individual_id:'52',author_name:'<img onerror=x>',product_name:'Squier Telecaster',can_write:true,...extra});
const response=(items,next_after=null)=>({ok:true,json:async()=>({items,next_after})});
test('Acquire inbox follows sparse cursors and delegates Accept/Decline without writing',async()=>{
 const e=setup();e.replies.push(response([],'50'),response([row('51')]));await e.api.refresh();assert.equal(e.root.hidden,false);assert.equal(e.calls[1][0],'/api/auth/owner-acquire-requests?after=50');
 assert.equal(e.root.all().some(x=>x.children.includes('<img onerror=x> owner.claims_ownership ')),true);
 e.buttons()[0].onclick();e.buttons()[1].onclick();assert.deepEqual(e.opens.map(x=>x.slice(0,3)),[['52','51','positive'],['52','51','negative']]);assert.equal(e.calls.length,2);
});
test('Late responses and old buttons cannot follow an account change',async()=>{
 const e=setup();e.replies.push(response([row()]));await e.api.refresh();const old=e.buttons()[0];let resolve;e.replies.push(new Promise(r=>resolve=r));const pending=e.api.refresh();e.setState(null);e.api.render();resolve(response([row()]));await pending;old.onclick();assert.equal(e.root.hidden,true);assert.equal(e.opens.length,0);
});
test('Read-only or busy responses disable actions; permission loss clears data',async()=>{
 const e=setup();e.replies.push(response([row('1',{can_write:false})]));await e.api.refresh();assert.ok(e.buttons().every(x=>x.disabled));e.buttons()[0].onclick();assert.equal(e.opens.length,0);
 e.replies.push(response([row()]));await e.api.refresh();e.setBusy(true);e.api.render();assert.ok(e.buttons().every(x=>x.disabled));
 e.replies.push({ok:false,status:403});await e.api.refresh();assert.equal(e.root.hidden,true);assert.equal(e.buttons().length,0);
});
test('Bad pagination fails closed without retaining acceptance controls',async()=>{
 const e=setup();e.replies.push(response([row()],'1'),response([row()],'1'));await e.api.refresh();assert.equal(e.buttons().length,0);assert.equal(e.root.all().some(x=>x.textContent==='owner.inbox_unavailable'),true);
});
