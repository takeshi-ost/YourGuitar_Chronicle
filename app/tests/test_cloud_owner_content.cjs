const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function environment(){
  const ids=new Map(),listeners={},createdUrls=[],revokedUrls=[],photoCalls=[],photoReplies=[],decodes=[];
  class MediaURL extends URL{static createObjectURL(){const url='blob:owner-'+(createdUrls.length+1);createdUrls.push(url);return url}static revokeObjectURL(url){revokedUrls.push(url)}}
  class Element{
    constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.dataset={};this.value='';this.hidden=false;this.open=false;this.disabled=false;this.textContent='';this.naturalWidth=640;this.naturalHeight=480}
    async decode(){const value=await decodes.shift();if(value instanceof Error)throw value}removeAttribute(key){delete this[key]}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}
    setAttribute(key,value){this[key]=value}addEventListener(key,fn){this.listeners[key]=fn}focus(){this.focused=true}
    all(){return this.children.flatMap(n=>[n,...n.all()])}
    querySelectorAll(selector){if(selector==='li button')return this.all().filter(n=>n.tag==='li').flatMap(n=>n.all().filter(c=>c.tag==='button'));return this.all().filter(n=>selector==='[data-owner-confirm]'?n.dataset.ownerConfirm:selector.split(',').includes(n.tag))}
  }
  const document={body:new Element('body'),createElement:tag=>new Element(tag),getElementById(id){if(!ids.has(id)){const e=new Element();e.id=id}return ids.get(id)}};
  let state={user:{app_user_id:'owner'},identity:{email_verified:true}},busy=false;
  const calls=[],replies=[];
  const client={authorizedFetch:async(url,options={},verified)=>{if(url.includes('/media/')){photoCalls.push({url,options,verified});const value=await (photoReplies.length?photoReplies.shift():new Blob(['private'],{type:'image/jpeg'}));if(value instanceof Error)throw value;return value?.status?{ok:false,status:value.status}:{ok:true,blob:async()=>value}}calls.push({url,options,verified});const value=await replies.shift();if(value instanceof Error)throw value;return {ok:true,json:async()=>value}}};
  const context=vm.createContext({AbortController,addEventListener:(key,fn)=>(listeners[key]??=[]).push(fn),document,URL:MediaURL,URLSearchParams,YGCI18n:{t:(key,params={})=>key+JSON.stringify(params)},YGCOverlays:{open:d=>{d.open=true},close:d=>{d.open=false;d.listeners['ygc:closed']?.()}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-media.js'),'utf8').replaceAll('export function','function'),context);
  const args={auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;try{return await fn()}finally{busy=false;context.ui.render()}}};
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-guitars.js'),'utf8').replace(/^import .*;\n/gm,'').replace('export function','function');
  vm.runInContext(source+';globalThis.ui=createGuitars(args);',Object.assign(context,{args}));
  return {ui:context.ui,document,calls,replies,ids,photoCalls,photoReplies,decodes,createdUrls,revokedUrls,dispatch:key=>{for(const fn of listeners[key]||[])fn()},setState:value=>{state=value},setBusy:value=>{busy=value},async flush(){for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve))}};
}
const page=items=>({items,total:String(items.length),next_after:null});
async function open(e,claim){
  e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();
  e.replies.push({items:[claim],can_write:true});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
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

for(const can_write of [false,null,undefined,'true'])test(`Owner review remains readable but cannot decide when can_write=${String(can_write)}`,async()=>{
 const e=environment();e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:[acquire],can_write});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();
 const dialog=e.ids.get('ownerResponseDialog'),card=dialog.children[2].children[0];assert.equal(dialog.open,true);assert.match(card.children[0].textContent,/#23/);
 for(const index of [1,2,3,5])assert.equal(card.children[index].disabled,true);card.children[2].onclick();card.children[3].onclick();await e.flush();assert.equal(e.calls.length,3);assert.equal(card.children[3].hidden,true);
});

const media={id:'23',claim_type:'media',spec_items:[],body:'PRIVATE CAPTION',media_items:[{id:'31',mime_type:'image/jpeg'}],verification_status:'unverified',decline_reason_required:false,revision:'a'.repeat(64)};
const held=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}};

test('Owner Media review is gated until private image bytes decode, then confirms the content revision',async()=>{
 const e=environment(),waiting=held();e.photoReplies.push(waiting.promise);const {card,select,review,confirm}=await open(e,media);assert.equal(e.photoCalls.length,0);card.children[10].onclick();assert.equal(card.children[8].textContent,'claims.media_loading{}');assert.match(card.children[7].textContent,/media_private/);assert.equal(review.disabled,true);assert.equal(select.disabled,true);review.onclick();assert.equal(confirm.hidden,true);assert.equal(e.calls.length,3);
 waiting.resolve(new Blob(['PRIVATE'],{type:'image/jpeg'}));await e.flush();assert.equal(review.disabled,false);assert.equal(card.children[9].children.length,1);assert.ok(e.photoCalls[0].url.endsWith(media.revision));assert.equal(e.photoCalls[0].verified,true);
 select.value='positive';review.onclick();assert.equal(confirm.hidden,false);e.replies.push({verification_status:'positive'},page([{id:'12'}]),page([]));confirm.onclick();await e.flush();assert.deepEqual(JSON.parse(e.calls.find(c=>c.options.method==='POST').options.body),{stance:'positive',revision:media.revision});assert.deepEqual(e.revokedUrls,e.createdUrls);
});

for(const status of [401,403,404,409])test(`Owner Media failure ${status} purges photos and requires a fresh review list plus explicit image reload`,async()=>{
 const e=environment(),waiting=held(),changed={...media,revision:'b'.repeat(64),body:'NEW CAPTION'};e.photoReplies.push(waiting.promise);const old=await open(e,media);old.card.children[10].onclick();e.replies.push({items:[changed],can_write:true});waiting.resolve({status});await e.flush();const card=old.dialog.children[2].children[0];assert.equal(card.children[2].disabled,true);assert.equal(card.children[3].hidden,true);assert.match(card.children[0].textContent,/NEW CAPTION/);assert.equal(e.ids.get('ownerMediaReload').hidden,false);old.review.onclick();old.confirm.onclick();card.children[2].onclick();card.children[3].onclick();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,0);assert.equal(e.photoCalls.length,1);
 e.replies.push({items:[changed],can_write:true});await e.ids.get('ownerMediaReload').onclick();await e.flush();const fresh=old.dialog.children[2].children[0];assert.equal(fresh.children[2].disabled,true);assert.equal(e.photoCalls.length,1);fresh.children[10].onclick();await e.flush();assert.equal(fresh.children[2].disabled,false);assert.ok(e.photoCalls.at(-1).url.endsWith(changed.revision));fresh.children[2].onclick();assert.equal(fresh.children[3].hidden,false);
});

for(const interruption of ['close','signout','account','history','pagehide'])test(`Owner private image completion after ${interruption} never revives decisions or photos`,async()=>{
 const e=environment(),waiting=held();e.photoReplies.push(waiting.promise);const {dialog,card,review,confirm}=await open(e,media);card.children[10].onclick();
 if(interruption==='close')dialog.children[4].onclick();else if(interruption==='history')e.dispatch('popstate');else if(interruption==='pagehide')e.dispatch('pagehide');else{e.setState(interruption==='signout'?null:{user:{app_user_id:'other'},identity:{email_verified:true}});e.ui.render()}
 waiting.resolve(new Blob(['PRIVATE'],{type:'image/jpeg'}));await e.flush();assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);assert.equal(e.createdUrls.length,0);review.onclick();confirm.onclick();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,0);
});

test('Read-only Owner Media photos remain readable without any enabled decisions',async()=>{
 const e=environment();e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:[media],can_write:false});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();await e.flush();const card=e.ids.get('ownerResponseDialog').children[2].children[0];assert.equal(e.photoCalls.length,0);assert.equal(card.children[10].disabled,false);card.children[10].onclick();await e.flush();assert.equal(card.children[9].children.length,1);for(const i of [1,2,3,5])assert.equal(card.children[i].disabled,true);assert.equal(e.calls.length,3);
});

test('Unavailable legacy Media storage cannot be approved and offers explicit reload',async()=>{
 const e=environment(),waiting=held();e.photoReplies.push(waiting.promise);const {dialog,card,review,confirm}=await open(e,media);card.children[10].onclick();waiting.resolve({status:400});await e.flush();assert.equal(dialog.children[2].children.length,0);assert.equal(e.ids.get('ownerMediaReload').hidden,false);review.onclick();confirm.onclick();assert.equal(e.calls.length,3);
});

test('An older Owner list request cannot populate a dismissed or reopened review dialog',async()=>{
 const e=environment(),waiting=held();e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push(waiting.promise);const pending=e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const dialog=e.ids.get('ownerResponseDialog');dialog.children[4].onclick();waiting.resolve({items:[media],can_write:true});await pending;await e.flush();assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);assert.equal(e.photoCalls.length,0);
});

test('Many Owner Media rows fetch nothing automatically and only one selected Claim retains decoded photos',async()=>{
 const e=environment(),rows=Array.from({length:80},(_,i)=>({...media,id:String(100+i),media_items:Array.from({length:10},(_,j)=>({id:String(1000+i*10+j),mime_type:'image/jpeg'}))}));
 e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:rows,can_write:true});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();await e.flush();
 const dialog=e.ids.get('ownerResponseDialog'),cards=dialog.children[2].children;assert.equal(cards.length,80);assert.equal(e.photoCalls.length,0);assert.equal(e.createdUrls.length,0);
 cards[0].children[10].onclick();await e.flush();assert.equal(e.photoCalls.length,10);assert.equal(cards[0].children[9].children.length,10);cards[0].children[2].onclick();assert.equal(cards[0].children[3].hidden,false);
 cards[1].children[10].onclick();await e.flush();assert.equal(e.photoCalls.length,20);assert.equal(cards[0].children[9].children.length,0);assert.equal(cards[0].children[2].disabled,true);assert.equal(cards[0].children[3].hidden,true);assert.equal(cards[1].children[9].children.length,10);assert.equal(e.createdUrls.length-e.revokedUrls.length,10);cards[0].children[3].onclick();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,0);dialog.children[4].onclick();assert.deepEqual(e.revokedUrls.sort(),e.createdUrls.sort());
});

test('Switching the selected Owner Media Claim cancels the old image request and discards its late response',async()=>{
 const e=environment(),waiting=held(),rows=[media,{...media,id:'24',media_items:[{id:'32',mime_type:'image/jpeg'}]}];e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:rows,can_write:true});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const cards=e.ids.get('ownerResponseDialog').children[2].children;
 e.photoReplies.push(waiting.promise);cards[0].children[10].onclick();cards[0].children[10].onclick();assert.equal(e.photoCalls.length,1);assert.equal(e.photoCalls[0].options.signal.aborted,false);cards[1].children[10].onclick();await e.flush();assert.equal(e.photoCalls.length,2);assert.equal(e.photoCalls[0].options.signal.aborted,true);assert.equal(e.createdUrls.length,1);const currentUrl=e.createdUrls[0];
 waiting.resolve(new Blob(['OLD PRIVATE'],{type:'image/jpeg'}));await e.flush();assert.equal(cards[0].children[9].children.length,0);assert.equal(cards[0].children[2].disabled,true);assert.equal(cards[1].children[9].children.length,1);assert.equal(cards[1].children[2].disabled,false);assert.equal(e.createdUrls.length,1);assert.ok(!e.revokedUrls.includes(currentUrl));
});

test('Successful Owner decision after Close refreshes ownership lists without restoring its private dialog',async()=>{
 const e=environment(),waiting=held(),{dialog,review,confirm}=await open(e,acquire);review.onclick();e.replies.push(waiting.promise);confirm.onclick();dialog.children[4].onclick();assert.equal(dialog.open,false);
 e.replies.push(page([]),page([{id:'12'}]));waiting.resolve({verification_status:'positive'});await e.flush();assert.equal(e.calls.length,6);assert.equal(e.calls.filter(call=>call.options.method==='POST').length,1);assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);assert.equal(e.ids.get('selfGuitars_owned').querySelectorAll('li button').length,0);assert.equal(e.ids.get('selfGuitars_formerly_owned').children[2].children.length,1);
});

for(const interruption of ['account','signout','navigation'])test(`Successful old Owner mutation after ${interruption} cannot refresh another account or route`,async()=>{
 const e=environment(),waiting=held(),{dialog,review,confirm}=await open(e,acquire);review.onclick();e.replies.push(waiting.promise);confirm.onclick();
 if(interruption==='navigation')e.dispatch('popstate');else{e.setState(interruption==='signout'?null:{user:{app_user_id:'another'},identity:{email_verified:true}});e.ui.render()}
 waiting.resolve({verification_status:'positive'});await e.flush();assert.equal(e.calls.length,4);assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);
});

test('A completed older Owner decision refreshes lists while leaving a newer review dialog intact',async()=>{
 const e=environment(),waiting=held(),{dialog,review,confirm}=await open(e,acquire);review.onclick();e.replies.push(waiting.promise);confirm.onclick();dialog.children[4].onclick();
 // Exercise the late-result fence independently of the global busy lock.
 e.setBusy(false);e.replies.push({items:[{...acquire,id:'24',body:'NEW PRIVATE REVIEW',revision:'b'.repeat(64)}],can_write:true});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const freshCard=dialog.children[2].children[0];
 e.replies.push(page([{id:'12'}]),page([]));waiting.resolve({verification_status:'positive'});await e.flush();assert.equal(e.calls.length,7);assert.equal(dialog.open,true);assert.equal(dialog.children[2].children[0],freshCard);assert.match(freshCard.children[0].textContent,/NEW PRIVATE REVIEW/);freshCard.children[2].onclick();assert.equal(freshCard.children[3].hidden,false);
});

const eventClaim={...media,claim_type:'event',event_kind:'performance',body:'PRIVATE EVENT <img onerror=x>',occurred_at:'2026-01-01',media_items:[]};
const posts=e=>e.calls.filter(call=>call.options.method==='POST');

test('Owner can review a text-only Event without loading photos and sees subtype, complete date and body',async()=>{
 const e=environment(),{card,description,select,review,confirm}=await open(e,eventClaim);assert.match(description.textContent,/claims.event_performance/);assert.match(description.textContent,/2026-01-01/);assert.match(description.textContent,/PRIVATE EVENT <img onerror=x>/);assert.equal(description.children.length,0);assert.equal(card.children.length,7);assert.equal(e.photoCalls.length,0);assert.equal(review.disabled,false);select.value='positive';review.onclick();assert.equal(confirm.hidden,false);assert.equal(posts(e).length,0);e.replies.push({verification_status:'positive'},page([{id:'12'}]),page([]));confirm.onclick();confirm.onclick();await e.flush();assert.equal(posts(e).length,1);assert.deepEqual(JSON.parse(posts(e)[0].options.body),{stance:'positive',revision:eventClaim.revision});assert.equal(e.photoCalls.length,0);
});

test('Owner Event approval waits for every attachment to decode, then confirms exactly its content revision',async()=>{
 const e=environment(),waiting=held(),row={...eventClaim,media_items:[{id:'31',mime_type:'image/jpeg'},{id:'32',mime_type:'image/jpeg'}]};e.decodes.push(undefined,waiting.promise);const {card,select,review,confirm}=await open(e,row);assert.equal(e.photoCalls.length,0);card.children[10].onclick();card.children[10].onclick();await e.flush();assert.equal(e.photoCalls.length,2);assert.equal(card.children[9].children.length,1);assert.equal(e.createdUrls.length,2);assert.equal(review.disabled,true);review.onclick();confirm.onclick();assert.equal(confirm.hidden,true);assert.equal(posts(e).length,0);waiting.resolve();await e.flush();assert.equal(card.children[9].children.length,2);assert.equal(review.disabled,false);select.value='positive';review.onclick();e.replies.push({verification_status:'positive'},page([{id:'12'}]),page([]));confirm.onclick();await e.flush();assert.equal(posts(e).length,1);assert.deepEqual(JSON.parse(posts(e)[0].options.body),{stance:'positive',revision:row.revision});assert.deepEqual(e.revokedUrls,e.createdUrls);
});

for(const media_items of [undefined,null,{},[{id:'31',mime_type:'image/png'}],[{id:'31',mime_type:'image/jpeg'},{id:'31',mime_type:'image/jpeg'}],Array.from({length:11},(_,i)=>({id:String(31+i),mime_type:'image/jpeg'}))])test('Missing or malformed Event attachment metadata never becomes a text-only approval',async()=>{
 const e=environment(),{dialog,card,review,confirm}=await open(e,{...eventClaim,media_items});assert.equal(review.disabled,true);review.onclick();confirm.onclick();assert.equal(posts(e).length,0);card.children[10].onclick();await e.flush();assert.equal(e.photoCalls.length,0);assert.equal(dialog.children[2].children.length,0);assert.equal(e.ids.get('ownerMediaReload').hidden,false);review.onclick();confirm.onclick();assert.equal(posts(e).length,0);
});

for(const failure of [400,401,403,404,409,500,'decode','transport'])test(`Event attached-photo failure ${failure} clears partial images and all pending decisions`,async()=>{
 const e=environment(),row={...eventClaim,media_items:[{id:'31',mime_type:'image/jpeg'},{id:'32',mime_type:'image/jpeg'}]},waiting=held();e.photoReplies.push(new Blob(['first'],{type:'image/jpeg'}),waiting.promise);if(failure==='decode')e.decodes.push(undefined,Error('invalid image'));const {dialog,card,review,confirm}=await open(e,row);card.children[10].onclick();await e.flush();assert.equal(card.children[9].children.length,1);assert.equal(review.disabled,true);review.onclick();assert.equal(confirm.hidden,true);
 if([401,403,404,409].includes(failure))e.replies.push({items:[{...row,revision:'b'.repeat(64)}],can_write:true});waiting.resolve(failure==='decode'?new Blob(['invalid'],{type:'image/jpeg'}):failure==='transport'?Error('photo unavailable'):{status:failure});await e.flush();assert.deepEqual(e.revokedUrls,e.createdUrls);assert.equal(card.children[9].children.length,0);assert.equal(e.ids.get('ownerMediaReload').hidden,false);assert.equal(posts(e).length,0);review.onclick();confirm.onclick();assert.equal(posts(e).length,0);for(const next of dialog.children[2].children){assert.equal(next.children[2].disabled,true);assert.equal(next.children[3].hidden,true)}
});

for(const interruption of ['close','signout','account','history','pagehide'])test(`Event Owner photo decode after ${interruption} cannot restore a stale review`,async()=>{
 const e=environment(),waiting=held();e.decodes.push(waiting.promise);const {dialog,card,review,confirm}=await open(e,{...eventClaim,media_items:media.media_items});card.children[10].onclick();await e.flush();assert.equal(e.createdUrls.length,1);if(interruption==='close')dialog.children[4].onclick();else if(interruption==='history')e.dispatch('popstate');else if(interruption==='pagehide')e.dispatch('pagehide');else{e.setState(interruption==='signout'?null:{user:{app_user_id:'other'},identity:{email_verified:true}});e.ui.render()}waiting.resolve();await e.flush();assert.equal(dialog.open,false);assert.equal(dialog.children[2].children.length,0);assert.deepEqual(e.revokedUrls,e.createdUrls);review.onclick();confirm.onclick();assert.equal(posts(e).length,0);
});

test('Switching between Event and Media photo reviews cancels old photos and any earlier confirmation',async()=>{
 const e=environment(),waiting=held(),rows=[{...eventClaim,media_items:media.media_items},{...media,id:'24',media_items:[{id:'32',mime_type:'image/jpeg'}]}];e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:rows,can_write:true});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const cards=e.ids.get('ownerResponseDialog').children[2].children;cards[0].children[10].onclick();await e.flush();cards[0].children[2].onclick();assert.equal(cards[0].children[3].hidden,false);e.photoReplies.push(waiting.promise);cards[1].children[10].onclick();assert.equal(cards[0].children[3].hidden,true);assert.equal(cards[0].children[9].children.length,0);assert.equal(cards[0].children[2].disabled,true);cards[0].children[3].onclick();assert.equal(posts(e).length,0);cards[0].children[10].onclick();await e.flush();assert.equal(e.photoCalls[1].options.signal.aborted,true);waiting.resolve(new Blob(['OLD MEDIA'],{type:'image/jpeg'}));await e.flush();assert.equal(cards[1].children[9].children.length,0);assert.equal(cards[1].children[2].disabled,true);assert.equal(cards[0].children[9].children.length,1);assert.equal(cards[0].children[2].disabled,false);
});

for(const photos of [false,true])test(`Read-only Owner Event (${photos?'photos':'text-only'}) never enables a decision`,async()=>{
 const e=environment(),row={...eventClaim,media_items:photos?media.media_items:[]};e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push({items:[row],can_write:false});await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const card=e.ids.get('ownerResponseDialog').children[2].children[0];if(photos){assert.equal(card.children[10].disabled,false);card.children[10].onclick();await e.flush();assert.equal(card.children[9].children.length,1)}for(const index of [1,2,3,5])assert.equal(card.children[index].disabled,true);card.children[2].onclick();card.children[3].onclick();assert.equal(posts(e).length,0);
});

test('A transient first Owner refresh exposes an explicit retry that restores current Event content',async()=>{
 const e=environment();e.replies.push(page([{id:'12'}]),page([]));await e.ui.refresh();e.replies.push(Error('temporary read unavailable'));await e.ids.get('selfGuitars_owned').querySelectorAll('li button')[0].onclick();const dialog=e.ids.get('ownerResponseDialog');assert.equal(dialog.open,true);assert.equal(dialog.children[2].children.length,0);assert.equal(e.ids.get('ownerMediaReload').hidden,false);assert.equal(e.ids.get('ownerMediaReload').disabled,false);e.replies.push({items:[eventClaim],can_write:true});await e.ids.get('ownerMediaReload').onclick();const card=dialog.children[2].children[0];assert.match(card.children[0].textContent,/PRIVATE EVENT/);assert.equal(card.children[2].disabled,false);assert.equal(posts(e).length,0);assert.equal(e.photoCalls.length,0);
});

test('Unknown Event Owner decision outcome revokes photos and requires a new list and photo review',async()=>{
 const e=environment(),row={...eventClaim,media_items:media.media_items},{dialog,card,review,confirm}=await open(e,row);card.children[10].onclick();await e.flush();review.onclick();e.replies.push(Error('decision response lost'));confirm.onclick();await e.flush();assert.equal(posts(e).length,1);assert.equal(review.disabled,true);assert.equal(confirm.hidden,true);assert.deepEqual(e.revokedUrls,e.createdUrls);assert.equal(e.ids.get('ownerMediaReload').hidden,false);review.onclick();confirm.onclick();assert.equal(posts(e).length,1);
 const changed={...row,verification_status:'positive',revision:'b'.repeat(64)};e.replies.push({items:[changed],can_write:true});await e.ids.get('ownerMediaReload').onclick();const fresh=dialog.children[2].children[0];assert.equal(fresh.children[2].disabled,true);assert.equal(fresh.children[3].hidden,true);assert.equal(e.photoCalls.length,1);fresh.children[10].onclick();await e.flush();assert.equal(fresh.children[2].disabled,false);assert.equal(fresh.children[1].value,'positive');assert.ok(e.photoCalls.at(-1).url.endsWith(changed.revision));assert.equal(posts(e).length,1);
});

for(const fresh of [Error('transient read unavailable'),Object.assign(Error('offline'),{status:503,code:'service_restricted'})])test('Owner Event service restriction followed by a failed refresh revokes content and still permits explicit retry',async()=>{
 const e=environment(),row={...eventClaim,media_items:media.media_items},{dialog,card,review,confirm}=await open(e,row);card.children[10].onclick();await e.flush();review.onclick();e.replies.push(Object.assign(Error('read only'),{status:403,code:'service_restricted'}),fresh);confirm.onclick();await e.flush();assert.equal(dialog.children[2].children.length,0);assert.deepEqual(e.revokedUrls,e.createdUrls);assert.equal(e.ids.get('ownerMediaReload').hidden,false);review.onclick();confirm.onclick();assert.equal(posts(e).length,1);e.replies.push({items:[row],can_write:false});await e.ids.get('ownerMediaReload').onclick();const readable=dialog.children[2].children[0];assert.equal(readable.children[2].disabled,true);readable.children[10].onclick();await e.flush();assert.equal(readable.children[9].children.length,1);assert.equal(readable.children[2].disabled,true);assert.equal(posts(e).length,1);
});

test('Current Owner loss during Event photo read removes every private card and cannot retain approval',async()=>{
 const e=environment(),waiting=held(),{dialog,card,review,confirm}=await open(e,{...eventClaim,media_items:media.media_items});e.photoReplies.push(waiting.promise);card.children[10].onclick();e.replies.push(Object.assign(Error('not current owner'),{status:404}));waiting.resolve({status:404});await e.flush();assert.equal(dialog.children[2].children.length,0);assert.equal(e.createdUrls.length,0);assert.equal(e.ids.get('ownerMediaReload').hidden,false);review.onclick();confirm.onclick();assert.equal(posts(e).length,0);
});

test('Existing Event value_text subtype is localized once in the Owner review description',async()=>{
 const e=environment(),{description}=await open(e,{...eventClaim,event_kind:undefined,value_text:'recording'});assert.match(description.textContent,/claims.event_recording/);assert.equal(description.textContent.split('recording').length,2);
});
