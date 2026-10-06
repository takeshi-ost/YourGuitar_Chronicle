const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function environment(){
  const ids=new Map();
  class Element{
    constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.dataset={};this.value='';this.hidden=false;this.open=false;this.disabled=false;this.textContent='';}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}
    setAttribute(key,value){this[key]=value}addEventListener(key,fn){this.listeners[key]=fn}focus(){this.focused=true}
    all(){return this.children.flatMap(n=>[n,...n.all()])}
    querySelectorAll(selector){if(selector==='li button')return this.all().filter(n=>n.tag==='li').flatMap(n=>n.all().filter(c=>c.tag==='button'));return this.all().filter(n=>selector==='[data-owner-confirm]'?n.dataset.ownerConfirm:selector.split(',').includes(n.tag))}
  }
  const document={body:new Element('body'),createElement:tag=>new Element(tag),getElementById(id){if(!ids.has(id)){const e=new Element();e.id=id}return ids.get(id)}};
  let state={user:{app_user_id:'owner'},identity:{email_verified:true}},busy=false;
  const calls=[],replies=[];
  const client={authorizedFetch:async(url,options={},verified)=>{calls.push({url,options,verified});return {ok:true,json:async()=>replies.shift()}}};
  const context=vm.createContext({document,URLSearchParams,YGCI18n:{t:(key,params={})=>key+JSON.stringify(params)},YGCOverlays:{open:d=>{d.open=true},close:d=>{d.open=false;d.listeners['ygc:closed']?.()}}});
  const args={auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;try{return await fn()}finally{busy=false;context.ui.render()}}};
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-guitars.js'),'utf8').replace('export function','function');
  vm.runInContext(source+';globalThis.ui=createGuitars(args);',Object.assign(context,{args}));
  return {ui:context.ui,document,calls,replies,ids,setState:value=>{state=value},async flush(){for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))}};
}
const page=items=>({items,total:String(items.length),next_after:null});
async function open(e,claim){
  e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();
  e.replies.push({items:[claim]});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
  const dialog=e.ids.get('ownerResponseDialog'),card=dialog.children[2].children[0];
  return {dialog,card,description:card.children[0],select:card.children[1],review:card.children[2],confirm:card.children[3],reason:card.children[5]};
}
const acquire={id:'23',claim_type:'ownership',ownership_kind:'acquire',verification_status:'unverified',decline_reason_required:true,revision:'a'.repeat(64)};

test('Acquire decline requires a visible reason and confirms the exact text before POST',async()=>{
  const e=environment(),{dialog,card,select,review,confirm,reason}=await open(e,acquire);
  assert.equal(reason.hidden,true);select.value='negative';select.onchange();
  assert.equal(reason.hidden,false);assert.equal(reason.required,true);assert.equal(reason.maxLength,4000);
  assert.match(card.children[6].textContent,/decline_reason_help/);
  review.onclick();assert.equal(confirm.hidden,true);assert.equal(reason.focused,true);assert.equal(e.calls.length,3);
  reason.value='   ';reason.oninput();review.onclick();assert.equal(confirm.hidden,true);
  reason.value='  On loan <img src=x>  ';reason.oninput();review.onclick();
  assert.equal(confirm.hidden,false);assert.equal(e.calls.length,3);
  assert.match(dialog.children[3].textContent,/decline_reason_confirm/);assert.match(dialog.children[3].textContent,/On loan <img src=x>/);
  assert.equal(dialog.children[3].children.length,0);
  e.replies.push({verification_status:'negative'},page([{id:'12'}]),page([]));confirm.onclick();confirm.onclick();await e.flush();
  const posts=e.calls.filter(call=>call.options.method==='POST');assert.equal(posts.length,1);
  assert.deepEqual(JSON.parse(posts[0].options.body),{stance:'negative',revision:'a'.repeat(64),reason:'On loan <img src=x>'});
  assert.equal(dialog.open,false);assert.equal(e.calls.length,6);
});

test('Editing a reason or stance invalidates confirmation and dismissal clears the pending reason',async()=>{
  const e=environment(),{dialog,select,review,confirm,reason}=await open(e,acquire);
  select.value='negative';select.onchange();reason.value='On loan';reason.oninput();review.onclick();
  reason.value='New explanation';reason.oninput();confirm.onclick();assert.equal(confirm.hidden,true);assert.equal(e.calls.length,3);
  review.onclick();assert.match(dialog.children[3].textContent,/New explanation/);
  select.value='positive';select.onchange();assert.equal(reason.hidden,true);assert.equal(reason.required,false);assert.equal(confirm.hidden,true);
  confirm.onclick();assert.equal(e.calls.length,3);
  select.value='negative';select.onchange();review.onclick();dialog.children[4].onclick();confirm.onclick();
  assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);assert.equal(e.calls.length,3);
});

for(const kind of ['specification','repair'])test(`Owner sees every ${kind} field and value before confirmation with an empty body`,async()=>{
  const e=environment(),items=[{field_name:'finish',value_text:'<img src=x> White'},{field_name:'pickups',value_text:'Two single coils'}];
  const {description,review,confirm,reason}=await open(e,{id:'24',claim_type:'specification',specification_kind:kind,spec_items:items,body:null,field_name:null,value_text:null,verification_status:'unverified',decline_reason_required:false,revision:'b'.repeat(64)});
  assert.ok(description.textContent.includes(kind));for(const item of items){assert.ok(description.textContent.includes(item.field_name));assert.ok(description.textContent.includes(item.value_text))}
  assert.equal(description.children.length,0);assert.equal(reason.hidden,true);assert.equal(confirm.hidden,true);assert.equal(e.calls.length,3);
  review.onclick();assert.equal(confirm.hidden,false);assert.equal(e.calls.length,3);
});
