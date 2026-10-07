const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function environment(){
  const ids=new Map();
  class Element{
    constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.dataset={};this.style={};this.value='';this.files=[];this.hidden=false;this.open=false;this.disabled=false;this.textContent='';}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}
    setAttribute(key,value){this[key]=value}removeAttribute(key){delete this[key]}
    addEventListener(key,fn){this.listeners[key]=fn}reset(){}focus(){}scrollIntoView(){}
    all(){return this.children.flatMap(n=>[n,...(n.all?.()||[])])}
    querySelectorAll(selector){if(selector==='li button')return this.all().filter(n=>n.tag==='li').flatMap(n=>n.all().filter(c=>c.tag==='button'));const tags=selector.split(',');return this.all().filter(n=>selector==='[data-owner-confirm]'?n.dataset.ownerConfirm:tags.some(tag=>n.tag===tag.replace('li ','')))}
  }
  const document={body:new Element('body'),createElement:tag=>new Element(tag),getElementById(id){if(!ids.has(id)){const e=new Element();e.id=id}return ids.get(id)},querySelector(){return new Element()},querySelectorAll(){return []}};
  let state={user:{app_user_id:'applicant',role:'admin',display_name:'Person'},identity:{email_verified:true}},busy=false;
  const calls=[],replies=[];
  const client={signedIn:true,restore:async()=>state,logout:async()=>{state=null},authorizedFetch:async(url,options={},verified)=>{calls.push({url,options,verified});const value=replies.shift();if(value instanceof Error)throw value;return {ok:true,json:async()=>value}}};
  const context=vm.createContext({addEventListener(){},document,URL,URLSearchParams,Intl,Date,console,YGCI18n:{t:(key,params={})=>key+JSON.stringify(params)},YGCOverlays:{open:d=>{d.open=true},close:d=>{d.open=false;d.listeners['ygc:closed']?.()}},loadCloudAuth:async()=>client,fetch:async()=>({ok:true})});
  const noOp=()=>({render(){},clear(){},refresh:async()=>{},detail(){}});for(const key of ['createUserBrowser','createCrawlBrowser','createBackupBrowser','createGuitarBrowser','createApplicationBrowser'])context[key]=noOp;
  const args={auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;try{return await fn()}finally{busy=false;context.component?.render()}}};
  function load(file,name){let source=fs.readFileSync(path.join(__dirname,'../src/ygc/static',file),'utf8').replace(/^import .*;\n/gm,'').replaceAll('export function','function');vm.runInContext(source+`;globalThis.component=${name}(args);`,Object.assign(context,{args}));return context.component}
  return {context,document,calls,replies,args,load,ids,setState:value=>{state=value},async flush(){for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))}};
}
const page=items=>({items,total:String(items.length),next_after:null});
test('Owner approval requires explicit confirmation, canonical API, snapshot revision, and refreshes both lists',async()=>{
  const e=environment(),ui=e.load('cloud-account-guitars.js','createGuitars');e.replies.push(page([{id:'12',model:'Guitar'}]),page([]));await ui.refresh();
  const claim={id:'23',author_name:'<img src=x>',claim_type:'ownership',ownership_kind:'acquire',body:'Details',verification_status:'unverified',revision:'a'.repeat(64)};
  e.replies.push({items:[claim],can_write:true});const owned=e.ids.get('selfGuitars_owned');await owned.querySelectorAll('li button')[0].onclick();
  const dialog=e.ids.get('ownerResponseDialog'),section=dialog.children[2].children[0],select=section.children[1],review=section.children[2],confirm=section.children[3];
  assert.ok(section.children[0].textContent.includes('<img src=x>'));assert.equal(section.children[0].children.length,0);
  select.value='positive';review.onclick();assert.equal(e.calls.length,3);assert.equal(confirm.hidden,false);
  e.replies.push({verification_status:'positive'},page([]),page([{id:'12',model:'Former'}]));confirm.onclick();await e.flush();
  const sent=e.calls.find(c=>c.options.method==='POST');assert.equal(sent.url,'/api/auth/guitars/12/owner-responses/23');assert.deepEqual(JSON.parse(sent.options.body),{stance:'positive',revision:'a'.repeat(64)});assert.equal(sent.verified,true);assert.equal(dialog.open,false);
  assert.equal(owned.querySelectorAll('li button').length,0);assert.equal(e.ids.get('selfGuitars_formerly_owned').all().filter(n=>n.tag==='li').length,1);assert.equal(e.calls.length,6);
});
test('Owner conflict stays visible and logout clears controls without submitting',async()=>{
  const e=environment(),ui=e.load('cloud-account-guitars.js','createGuitars');e.replies.push(page([{id:'12'}]),page([]));await ui.refresh();e.replies.push({can_write:true,items:[{id:'23',revision:'b'.repeat(64),verification_status:'unverified'}]});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
  const d=e.ids.get('ownerResponseDialog'),card=d.children[2].children[0];card.children[2].onclick();e.replies.push(Object.assign(Error(),{status:409}));card.children[3].onclick();await e.flush();assert.match(d.children[3].textContent,/decision_conflict/);
  e.setState(null);ui.render();assert.equal(d.open,false);assert.equal(d.children[2].children.length,0);
});
test('Applicant result shows Claim state as text; retry requires second confirmation and error status',async()=>{
  const e=environment(),ui=e.load('cloud-account-applications.js','createApplications'),row={revision:'c'.repeat(32),kind:'acquire',serial:'S',individual_id:'12',status:'error',photos:[],expires_at:2000000000,claim_id:null,reasons:['<img src=x>']};
  e.replies.push({items:[row],can_write:true});await ui.refresh();const list=e.ids.get('selfApplications').children.at(-1);list.children[0].children[1].onclick();
  const retry=e.ids.get('applicationRetry');retry.onclick();assert.equal(e.calls.length,1);assert.equal(retry.hidden,false);
  e.replies.push({...row,status:'pending'},{can_write:true,items:[{...row,status:'pending'}]});retry.onclick();await e.flush();assert.equal(e.calls[1].url,'/api/auth/applications/'+row.revision+'/retry');assert.deepEqual(JSON.parse(e.calls[1].options.body),{});assert.equal(retry.hidden,true);
  e.replies.push({can_write:true,items:[{...row,status:'accepted',claim_id:'23',verification_status:'unverified'}]});await ui.refresh();list.children[0].children[1].onclick();const detail=e.ids.get('applicationDialog').children[1];assert.match(detail.textContent,/owner_waiting/);assert.ok(detail.textContent.includes('<img src=x>'));assert.equal(detail.children.length,0);
});
test('Review switch confirms ON/OFF and sends compare-and-set without starting a job',async()=>{
  const e=environment();e.replies.push({mode:'normal',message:'',version:1},{enabled:false},{content:'available',accounts:'available'});
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-console-page.js'),'utf8').replace(/^import .*;\n/gm,'');await vm.runInContext('(async()=>{'+source+'})()',e.context);
  e.ids.get('reviewToggle').onclick();assert.equal(e.calls.length,3);assert.equal(e.ids.get('reviewDialog').open,true);e.ids.get('reviewCancel').onclick();assert.equal(e.calls.length,3);
  e.ids.get('reviewToggle').onclick();e.replies.push({enabled:true});e.ids.get('reviewConfirm').onclick();await e.flush();assert.equal(e.calls.length,4);assert.equal(e.calls[3].url,'/api/admin/operations/review');assert.deepEqual(JSON.parse(e.calls[3].options.body),{enabled:true,expected_enabled:false});assert.equal(e.ids.get('reviewDialog').open,false);
  e.ids.get('reviewToggle').onclick();e.replies.push({enabled:false});e.ids.get('reviewConfirm').onclick();await e.flush();assert.deepEqual(JSON.parse(e.calls[4].options.body),{enabled:false,expected_enabled:true});
});


test('Owner service-mode write denial rechecks read access and retains disabled review content',async()=>{
 const e=environment(),ui=e.load('cloud-account-guitars.js','createGuitars'),claim={id:'23',revision:'b'.repeat(64),verification_status:'unverified',body:'Private Claim'};
 e.replies.push(page([{id:'12'}]),page([]));await ui.refresh();e.replies.push({can_write:true,items:[claim]});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
 const d=e.ids.get('ownerResponseDialog'),card=d.children[2].children[0];card.children[2].onclick();e.replies.push(Object.assign(Error(),{status:403,code:'service_restricted'}),{can_write:false,items:[claim]});card.children[3].onclick();await e.flush();
 assert.equal(d.open,true);assert.equal(d.children[2].children.length,1);assert.match(card.children[0].textContent,/Private Claim/);assert.equal(card.children[1].disabled,true);assert.equal(card.children[2].disabled,true);assert.equal(card.children[3].hidden,true);assert.match(d.children[3].textContent,/service_restricted/);assert.equal(e.calls.length,5);
});

for(const fresh of [[],[{id:'23',revision:'c'.repeat(64),verification_status:'unverified',body:'NEW AUTHORIZED CONTENT'}]])test('Owner restriction recovery drops old private cards and reasons absent from the fresh revision set',async()=>{
 const e=environment(),ui=e.load('cloud-account-guitars.js','createGuitars'),claim={id:'23',revision:'b'.repeat(64),verification_status:'unverified',body:'STALE PRIVATE CONTENT',decline_reason_required:true};
 e.replies.push(page([{id:'12'}]),page([]));await ui.refresh();e.replies.push({can_write:true,items:[claim]});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
 const d=e.ids.get('ownerResponseDialog'),card=d.children[2].children[0];card.children[1].value='negative';card.children[1].onchange();card.children[5].value='STALE PRIVATE REASON';card.children[2].onclick();
 e.replies.push(Object.assign(Error(),{status:403,code:'service_restricted'}),{can_write:false,items:fresh});card.children[3].onclick();await e.flush();
 assert.equal(d.children[2].children.length,fresh.length);assert.ok(!d.children[2].all().some(n=>n.textContent?.includes('STALE PRIVATE CONTENT')||n.value==='STALE PRIVATE REASON'));
});
