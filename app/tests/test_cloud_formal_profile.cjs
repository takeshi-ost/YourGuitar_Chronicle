const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
const dto=name=>({profile_revision:'1',fields:{display_name:name,location_country:'',location_region:'',bio:'private '+name}});
function setup(){
 const ids=new Map();class Element{constructor(){this.children=[];this.value='';this.listeners={};this.open=false;this.hidden=false;this.textContent=''}set id(id){this._id=id;ids.set(id,this)}get id(){return this._id}append(...v){this.children.push(...v)}replaceChildren(...v){this.children=v}addEventListener(n,f){this.listeners[n]=f}}
 const document={createElement:()=>new Element(),body:new Element(),getElementById:id=>ids.get(id)};
 for(const id of ['selfProfile','selfProfileValues','selfProfileStatus','selfProfileEdit','selfProfileRefresh']){const n=new Element();n.id=id}
 const context=vm.createContext({document,YGCI18n:{t:k=>k},YGCOverlays:{open:d=>{d.open=true},close:d=>{d.open=false;d.listeners['ygc:closed']?.()}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-profile.js'),'utf8').replace('export function','function'),context);
 let state={user:{app_user_id:'Alice'},identity:{email_verified:true}},queue=[],updated=0,work=Promise.resolve();
 const component=context.createProfile({auth:()=>({authorizedFetch:async()=>{const next=await queue.shift();if(next instanceof Error)throw next;return {ok:true,json:async()=>next}}}),state:()=>state,busy:()=>false,work:fn=>work=fn(),updated:async()=>{updated++}});
 return {component,queue,get updated(){return updated},get work(){return work},el:id=>ids.get(id),switch(){state={user:{app_user_id:'Bob'},identity:{email_verified:true}};component.clear()},values:()=>ids.get('selfProfileValues').children.map(n=>n.textContent).join('|')};
}
test('Formal profile discards an old read failure without clearing the next principal',async()=>{
 const e=setup(),old=deferred();e.queue.push(old.promise);const pending=e.component.refresh().catch(e.component.failed);e.switch();e.queue.push(dto('Bob'));await e.component.refresh();old.resolve(Error('old private failure'));await pending;assert.match(e.values(),/Bob/);assert.doesNotMatch(e.values(),/Alice/);
});
test('A completed old-principal profile save cannot restore or overwrite the current principal',async()=>{
 const e=setup();e.queue.push(dto('Alice'));await e.component.refresh();e.el('selfProfileEdit').onclick();const old=deferred();e.queue.push(old.promise);e.el('selfProfileDialog').children[0].onsubmit({preventDefault(){}});const pending=e.work;e.switch();e.queue.push(dto('Bob'));await e.component.refresh();old.resolve({saved:true});await pending;assert.equal(e.updated,0);assert.match(e.values(),/Bob/);
});
test('Profile cancellation clears draft fields and repeat opening uses canonical values',async()=>{
 const e=setup();e.queue.push(dto('Alice'));await e.component.refresh();e.el('selfProfileEdit').onclick();e.el('selfProfile_bio').value='discard';e.el('selfProfileCancel').onclick();assert.equal(e.el('selfProfile_bio').value,'');e.el('selfProfileEdit').onclick();assert.equal(e.el('selfProfile_bio').value,'private Alice');
});
