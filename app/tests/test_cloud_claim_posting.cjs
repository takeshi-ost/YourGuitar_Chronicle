const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const staticPath=path.join(__dirname,'../src/ygc/static');
const account=(id='first',verified=true)=>({user:{app_user_id:id,display_name:'Member',role:'member',status:'active'},identity:{email_verified:verified}});
const guitar=(id='12',extra={})=>({id,manufacturer:'Maker',model:'Model',serial_number:'SERIAL-'+id,finish:null,year:'1965',...extra});
const claim=(extra={})=>({id:'23',individual_id:'12',claim_type:'specification',specification_kind:'repair',incident_kind:null,spec_items:[{field_name:'neck',value_text:'Maple'}],body:'Private note',occurred_at:'2026-01-01',status:'active',verification_status:'unverified',created_at:'2026-01-02T03:04:05Z',updated_at:'2026-01-02T03:04:05Z',revision:'a'.repeat(64),...extra});
const page=(rows=[],extra={})=>({individual:guitar(),items:rows,next_after:null,can_write:true,...extra});
const denied=(httpStatus=403,code='service_restricted')=>({httpStatus,code});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}};
function environment({initial=account(),search='',fullPage=false}={}){
 const ids=new Map(),listeners={},createdUrls=[],revokedUrls=[],photoCalls=[],photoReplies=[];
 class MediaURL extends URL{static createObjectURL(blob){const url='blob:fixture-'+(createdUrls.length+1);createdUrls.push(url);return url}static revokeObjectURL(url){revokedUrls.push(url)}}
 class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.style={};this.value='';this.files=[];this.hidden=false;this.open=false;this.disabled=false;this._text='';this.classList={add(){},remove(){}};this.isConnected=true;this.tabIndex=0;this.naturalWidth=640;this.naturalHeight=480}
  async decode(){}
  set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
  set textContent(value){this._text=String(value);this.children=[]}get textContent(){return this._text+this.children.map(n=>n.textContent).join('')}
  set innerHTML(value){throw Error('Claims must be text-only')}
  append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this._text='';this.children=nodes}
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
 for(const match of fs.readFileSync(path.join(staticPath,'cloud_account_html.html'),'utf8').matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)){const n=new Element(match[1]);n.id=match[2];document.body.append(n)}
 let state=initial,busy=false,component,args;
 const calls=[],publicCalls=[],authCalls=[],replies=[],publicReplies=[],authReplies=[];let defaultRows=[];
 async function response(value){const data=await value;if(data instanceof Error)throw data;return data?.httpStatus?{ok:false,status:data.httpStatus,json:async()=>({detail:{code:data.code}})}:{ok:true,json:async()=>data}}
 const client={signedIn:Boolean(initial),account:initial,documents:async()=>({terms:{version:'t'},privacy:{version:'p'}}),restore:async()=>initial,
  async signIn(credentials){authCalls.push({name:'signin',credentials});this.signedIn=true;return this.account=authReplies.shift()??account('first',false)},
  async register(profile,credentials){authCalls.push({name:'register',profile,credentials});this.signedIn=true;return this.account=authReplies.shift()??account('first',false)},
  async logout(){authCalls.push({name:'logout'});this.signedIn=false;this.account=null},
  async requestEmailVerification(options){authCalls.push({name:'verification',options});return {sent:true,account:this.account}},
  async refreshVerification(){authCalls.push({name:'refreshVerification'});return this.account=account()},
  async authorizedFetch(url,options={},verified){
   if(url.startsWith('/api/public/guitars/'))return catalogResponse(url,options,{authorized:true,verified});
   if(url.includes('/media/')){photoCalls.push({url,options,verified});const value=await (photoReplies.length?photoReplies.shift():new Blob(['private jpeg'],{type:'image/jpeg'}));if(value instanceof Error)throw value;return value?.httpStatus?{ok:false,status:value.httpStatus}:{ok:true,blob:async()=>value}}
   calls.push({url,options,verified,account:args.state()?.user?.app_user_id});
   assert.match(url,/^\/api\/auth\/guitars\/[1-9][0-9]*\/(?:claims(?:[/?]|$)|media-claims$)/);
   if(options.method&&options.method!=='GET')assert.ok(replies.length,'Write requires an explicit fixture');
   const id=url.split('/')[4];return response(replies.length?replies.shift():page(defaultRows,{individual:guitar(id)}));
  },
 };
 const context=vm.createContext({AbortController,document,URL:MediaURL,URLSearchParams,Blob,File,FormData,Intl,Date,console,location:{search,origin:'https://ygc.example'},CustomEvent:class{constructor(type){this.type=type}},YGCI18n:{t:(key,params={})=>key+(Object.keys(params).length?JSON.stringify(params):'')}});
 context.window=context;context.addEventListener=(key,fn)=>(listeners[key]??=[]).push(fn);
 function catalogResponse(url,options,extra={}){publicCalls.push({url,options,...extra});return response(publicReplies.length?publicReplies.shift():guitar(url.split('/').at(-1)))}context.fetch=catalogResponse;
 vm.runInContext(fs.readFileSync(path.join(staticPath,'overlays.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(staticPath,'cloud-account-applications.js'),'utf8').split('export function createApplications')[0].replaceAll('export function','function'),context);
 vm.runInContext(fs.readFileSync(path.join(staticPath,'cloud-account-media.js'),'utf8').replaceAll('export function','function'),context);
 vm.runInContext(fs.readFileSync(path.join(staticPath,'cloud-account-claims.js'),'utf8').replace(/^import .*;\n/gm,'').replaceAll('export function','function'),context);
 const create=context.createClaims;context.createClaims=value=>{args=value;component=create(value);return component};
 const noOp=()=>({render(){},clear(){},refresh:async()=>{},failed(){},save(){},remove(){},setCatalogIntent(){}});
 Object.assign(context,{loadCloudAuth:async()=>client,createOwnership:()=>({...noOp(),setCatalogIntent(){},openGuitar(){}}),readOwnershipIntent:()=>null,createAvatar:noOp,createProfile:noOp,createGuitars:noOp,createApplications:noOp});
 let ready;
 if(fullPage){ready=vm.runInContext('(async()=>{'+fs.readFileSync(path.join(staticPath,'cloud-account-page.js'),'utf8').replace(/^import .*;\n/gm,'')+'})()',context)}
 else{component=context.createClaims({auth:()=>client,state:()=>state,busy:()=>busy,work:async fn=>{busy=true;component.render();try{return await fn()}finally{busy=false;component.render()}}});ready=Promise.resolve()}
 const control=id=>ids.get(id),dialog=control('claimDialog'),form=control('claimForm');
 return {component,context,client,createdUrls,revokedUrls,photoCalls,photoReplies,control,dialog,form,calls,replies,publicCalls,publicReplies,authCalls,authReplies,ready,
  get list(){return control('claimsList')},get status(){return control('catalogClaimStatus').textContent},
  start(){control('catalogClaimStart').onclick()},submit(){form.onsubmit({preventDefault(){}})},open(index=0){return this.list.children[index].children[1].onclick()},dismiss(){control('claimClose').onclick()},
  changeAccount(next){state=next;client.signedIn=Boolean(next);component.render()},
  rows(rows){defaultRows=rows},navigate(query){context.location.search=query;for(const fn of listeners.popstate||[])fn({})},
  async flush(){for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve))},
 };
}
const writes=e=>e.calls.filter(call=>call.options.method&&call.options.method!=='GET');
const field=(e,key,value)=>{e.control(key).value=value;e.control(key).oninput?.()};
const populated=e=>{field(e,'claimField_0','neck');field(e,'claimValue_0','Maple');field(e,'claimBody','my edited note')};

test('Claim URL intent is a canonical BIGINT string and ignores unrelated return destinations',()=>{
 const e=environment(),read=e.context.readClaimIntent;
 for(const id of ['1','9007199254740993','9223372036854775807'])assert.equal(read('?claim='+id+'&next=https://evil.invalid'),id);
 assert.equal(read('?acquire=12'),null);
 for(const value of ['','0','01','-1','+1','1.0','9223372036854775808','12\n','https://evil.invalid'])assert.equal(read('?claim='+encodeURIComponent(value)),'');
 assert.equal(read('?claim=12&claim=12'),'');
});

for(const initial of [null,account('first',false)])test('Guest/unverified intent performs only a safe public read without private data or writes',async()=>{
 const e=environment({initial});await e.component.setCatalogIntent('12');e.start();e.submit();await e.flush();
 assert.equal(e.publicCalls.length,1);assert.equal(e.calls.length,0);assert.equal(e.dialog.open,false);assert.equal(e.control('selfClaims').hidden,true);
 assert.equal(e.status,initial?'catalog.acquire_verify':'catalog.acquire_sign_in');
});

test('Verified selection reads private own Claims even if public detail is no longer visible, with text-only content',async()=>{
 const e=environment(),attack='<img src=x onerror=alert(1)>';e.replies.push(page([claim({body:attack,spec_items:[{field_name:'neck',value_text:attack}]})],{individual:guitar('12',{manufacturer:attack,private:'PRIVATE-EXTRA'})}));
 await e.component.setCatalogIntent('12');e.open();assert.equal(e.publicCalls.length,0);assert.equal(writes(e).length,0);
 assert.equal(e.dialog.open,true);assert.match(e.control('claimSavedState').textContent,/<img/);assert.match(e.control('claimSavedState').textContent,/2026-01-02T03:04:05Z/);
 assert.doesNotMatch(e.control('catalogClaimDetail').textContent,/PRIVATE-EXTRA/);assert.equal(e.control('claimSavedState').children.length,0);
 assert.equal(e.calls[0].verified,true);assert.ok(e.calls[0].options.headers['X-YGC-Timezone']);
});

test('Opening/repeating/cancelling a populated Claim form performs no mutation and preserves fields',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.start();assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.dialog.opens,1);
 e.dismiss();assert.equal(e.dialog.open,false);assert.equal(e.control('claimBody').value,'');assert.equal(writes(e).length,0);
});

for(const kind of ['specification','repair','damage','lost','theft'])test(`Create ${kind} uses only typed Claim fields after a private access recheck`,async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.control('claimKind').value=kind;e.control('claimKind').onchange();
 const spec=['specification','repair'].includes(kind);e.replies.push(page(),{claim:claim(spec?{specification_kind:kind}:{claim_type:'incident',incident_kind:kind,specification_kind:null,spec_items:[]})});
 e.submit();e.submit();await e.flush();assert.equal(writes(e).length,1);const posted=writes(e)[0];assert.equal(posted.url,'/api/auth/guitars/12/claims');assert.equal(posted.options.method,'POST');
 const data=JSON.parse(posted.options.body);assert.deepEqual(Object.keys(data).sort(),(spec?['claim_type','specification_kind','items','body','occurred_at']:['claim_type','incident_kind','body','occurred_at']).sort());
 assert.equal(data.claim_type,spec?'specification':'incident');assert.equal(data.body,'my edited note');assert.equal(data[spec?'specification_kind':'incident_kind'],kind);assert.equal(e.publicCalls.length,0);
});

for(const capability of [false,null,undefined,'true'])test(`Missing/denied write capability ${String(capability)} keeps the Claim list readable and cannot create`,async()=>{
 const e=environment();e.replies.push(page([claim()],{can_write:capability}));await e.component.setCatalogIntent('12');assert.equal(e.list.children.length,1);e.start();e.submit();assert.equal(e.dialog.open,false);assert.equal(writes(e).length,0);
 e.open();assert.equal(e.dialog.open,true);assert.equal(e.control('claimSave').disabled,true);assert.equal(e.control('claimDeactivate').disabled,true);
});

test('Read-only mode discovered at Save preserves input without sending a mutation',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(page([],{can_write:false}));e.submit();await e.flush();
 assert.equal(writes(e).length,0);assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimSave').disabled,true);assert.equal(e.dialog.open,true);
});

for(const interruption of ['new intent','back','close','signout','other account','unverified'])test(`Preflight interrupted by ${interruption} does not mutate or reopen a stale dialog`,async()=>{
 const e=environment(),held=deferred();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(held.promise);e.submit();
 if(interruption==='new intent')await e.component.setCatalogIntent('13');else if(interruption==='back')await e.component.setCatalogIntent(null);else if(interruption==='close')e.dismiss();else e.changeAccount(interruption==='signout'?null:account(interruption==='other account'?'second':'first',interruption!=='unverified'));
 held.resolve(page());await e.flush();assert.equal(writes(e).length,0);assert.equal(e.dialog.open,false);
});

for(const interruption of ['new intent','close','signout','other account'])test(`Late successful mutation after ${interruption} cannot replace newer/private view`,async()=>{
 const e=environment(),held=deferred();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(page(),held.promise);e.submit();await e.flush();assert.equal(writes(e).length,1);
 if(interruption==='new intent')await e.component.setCatalogIntent('13');else if(interruption==='close')e.dismiss();else e.changeAccount(interruption==='signout'?null:account('second'));
 held.resolve({claim:claim()});await e.flush();assert.equal(e.dialog.open,false);assert.equal(e.control('claimBody').value,'');if(interruption==='new intent')assert.match(e.control('catalogClaimDetail').textContent,/SERIAL-13/);
});

test('Revision conflict compares latest state without losing typed fields or original timestamp; rebasing is explicit',async()=>{
 const e=environment(),old=claim({occurred_at:'2026-01-01T12:34:56Z'}),changed=claim({revision:'b'.repeat(64),body:'REMOTE UPDATE',occurred_at:'2026-02-01T11:00:00Z'});e.rows([old]);await e.component.setCatalogIntent('12');e.open();populated(e);
 e.replies.push(page([changed]));e.submit();await e.flush();assert.equal(writes(e).length,0);assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimValue_0').value,'Maple');assert.match(e.control('claimLatest').textContent,/REMOTE UPDATE/);assert.equal(e.control('claimSave').disabled,true);
 e.control('claimKeepEdits').onclick();assert.equal(writes(e).length,0);assert.equal(e.control('claimSave').disabled,false);
 e.replies.push(page([changed]),{claim:claim({revision:'c'.repeat(64)})});e.submit();await e.flush();const data=JSON.parse(writes(e)[0].options.body);
 assert.equal(data.revision,'b'.repeat(64));assert.equal(data.body,'my edited note');assert.equal(data.occurred_at,'2026-01-01T12:34:56Z');assert.equal(writes(e)[0].options.method,'PATCH');
});

test('A server409 after preflight refreshes latest revision and leaves typed fields recoverable',async()=>{
 const e=environment(),old=claim(),changed=claim({revision:'b'.repeat(64),body:'REMOTE'});e.rows([old]);await e.component.setCatalogIntent('12');e.open();populated(e);
 e.replies.push(page([old]),denied(409,'claim_conflict'),page([changed]));e.submit();await e.flush();assert.equal(writes(e).length,1);assert.equal(e.control('claimBody').value,'my edited note');assert.match(e.control('claimLatest').textContent,/REMOTE/);assert.equal(e.control('claimKeepEdits').hidden,false);
 e.control('claimKeepEdits').onclick();assert.equal(e.control('claimSave').disabled,false);assert.equal(writes(e).length,1);
});

test('A failed latest-conflict fetch can be retried without closing or losing input',async()=>{
 const e=environment();e.rows([claim()]);await e.component.setCatalogIntent('12');e.open();populated(e);e.replies.push(page([claim()]),denied(409,'claim_conflict'),Error('offline'));e.submit();await e.flush();
 assert.equal(e.control('claimKeepEdits').hidden,true);assert.equal(e.control('claimCheckLatest').hidden,false);e.replies.push(page([claim({revision:'b'.repeat(64)})]));await e.control('claimCheckLatest').onclick();assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimKeepEdits').hidden,false);
});

test('Editing date deliberately changes the original timestamp; blank/null dates stay null if untouched',async()=>{
 for(const original of ['2026-01-01T11:22:33Z',null]){const e=environment(),row=claim({occurred_at:original});e.rows([row]);await e.component.setCatalogIntent('12');e.open();field(e,'claimDate','2026-01-04');e.replies.push(page([row]),{claim:row});e.submit();await e.flush();assert.equal(JSON.parse(writes(e)[0].options.body).occurred_at,'2026-01-04')}
 const e=environment(),row=claim({occurred_at:null});e.rows([row]);await e.component.setCatalogIntent('12');e.open();e.replies.push(page([row]),{claim:row});e.submit();await e.flush();assert.equal(JSON.parse(writes(e)[0].options.body).occurred_at,null);
});

test('Incident subtype cannot change during editing and Lost never produces an Ownership payload',async()=>{
 const e=environment(),row=claim({claim_type:'incident',incident_kind:'lost',specification_kind:null,spec_items:[]});e.rows([row]);await e.component.setCatalogIntent('12');e.open();assert.equal(e.control('claimKind').disabled,true);
 e.control('claimKind').value='theft';e.replies.push(page([row]),{claim:row});e.submit();await e.flush();const data=JSON.parse(writes(e)[0].options.body);assert.equal(data.claim_type,'incident');assert.equal(data.incident_kind,'lost');assert.equal(data.ownership_kind,undefined);
});

test('Existing space and underscore custom field names remain distinct; genuine case-folded duplicates are rejected',async()=>{
 const e=environment(),row=claim({spec_items:[{field_name:'neck wood',value_text:'Maple'},{field_name:'neck_wood',value_text:'Rosewood'}]});e.rows([row]);await e.component.setCatalogIntent('12');e.open();e.replies.push(page([row]),{claim:row});e.submit();await e.flush();assert.equal(writes(e).length,1);
 const e2=environment();await e2.component.setCatalogIntent('12');e2.start();populated(e2);e2.control('claimAddField').onclick();field(e2,'claimField_1',' NECK ');field(e2,'claimValue_1','Rosewood');e2.submit();await e2.flush();assert.equal(writes(e2).length,0);
});

test('Deactivation requires a separate confirmation and current revision, then remains visible as inactive',async()=>{
 const e=environment(),row=claim();e.rows([row]);await e.component.setCatalogIntent('12');e.open();e.control('claimDeactivate').onclick();assert.equal(writes(e).length,0);assert.match(e.control('claimMessage').textContent,/deactivate_help/);
 e.rows([claim({status:'inactive'})]);e.replies.push(page([row]),{claim:claim({status:'inactive'})});e.control('claimDeactivate').onclick();e.control('claimDeactivate').onclick();await e.flush();assert.equal(writes(e).length,1);assert.deepEqual(JSON.parse(writes(e)[0].options.body),{revision:'a'.repeat(64)});assert.match(writes(e)[0].url,/\/23\/deactivate$/);assert.equal(e.control('claimSave').disabled,true);assert.equal(e.control('claimDeactivate').hidden,true);assert.match(e.list.textContent,/claims.inactive/);
});

for(const httpStatus of [401,403])test(`Read denial ${httpStatus} purges private content and never retries anonymously`,async()=>{
 const e=environment();e.rows([claim()]);await e.component.setCatalogIntent('12');e.open();e.replies.push(denied(httpStatus,'account_inactive'));await e.component.refresh();assert.equal(e.dialog.open,false);assert.equal(e.list.children.length,0);assert.equal(e.control('claimBody').value,'');assert.equal(e.publicCalls.length,0);
});

test('Read-only rejection at write revalidates private read access and keeps unsaved fields',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(page(),denied(403),page([],{can_write:false}));e.submit();await e.flush();assert.equal(writes(e).length,1);assert.equal(e.dialog.open,true);assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimSave').disabled,true);
});

test('A delayed read or denial cannot expose or clear a newer account selection',async()=>{
 const e=environment(),held=deferred();e.replies.push(held.promise);const pending=e.component.setCatalogIntent('12');e.changeAccount(account('second'));e.replies.push(page([claim({body:'SECOND ACCOUNT'})]));await e.component.setCatalogIntent('12');held.resolve(denied(401));await pending;e.open();assert.match(e.control('claimSavedState').textContent,/SECOND ACCOUNT/);
});

test('Private pagination uses an exact string cursor and never makes a write',async()=>{
 const e=environment();e.replies.push(page([claim()],{next_after:'23'}));await e.component.setCatalogIntent('12');e.replies.push(page([claim({id:'20'})]));await e.control('claimsMore').onclick();assert.match(e.calls.at(-1).url,/\?after=23$/);assert.equal(e.list.children.length,1);assert.match(e.list.textContent,/#20/);assert.equal(writes(e).length,0);
});

for(const bad of [page([],{individual:guitar('13')}),page([claim({individual_id:'13'})]),page([claim({revision:'old'})]),page([claim({claim_type:'ownership'})])])test('Malformed private data cannot enable submission',async()=>{
 const e=environment();e.replies.push(bad);await e.component.setCatalogIntent('12');e.start();assert.equal(e.dialog.open,false);assert.equal(e.control('catalogClaimStart').disabled,true);assert.equal(writes(e).length,0);
});

test('Login, verification and account Back/Forward retain Claim intent with no automatic mutation',async()=>{
 const id='9007199254740993',e=environment({initial:null,search:'?claim='+id,fullPage:true});await e.ready;await e.flush();assert.equal(e.status,'catalog.acquire_sign_in');
 await e.control('cloudAccountForm').onsubmit({preventDefault(){}});await e.flush();assert.equal(e.status,'catalog.acquire_verify');await e.control('sendVerification').onclick();assert.equal(e.authCalls.at(-1).options.claim,id);
 await e.control('refreshVerification').onclick();await e.flush();assert.equal(e.status,'claims.ready');assert.equal(writes(e).length,0);e.start();field(e,'claimBody','KEEP');e.navigate('');await e.flush();assert.equal(e.dialog.open,false);assert.equal(e.control('catalogClaimIntent').hidden,true);
 e.navigate('?claim=12');await e.flush();assert.match(e.control('catalogClaimDetail').textContent,/SERIAL-12/);e.navigate('?claim=12&claim=13');await e.flush();assert.equal(e.status,'catalog.acquire_invalid');assert.equal(writes(e).length,0);
});

test('Known creation409 keeps the new draft retryable instead of requiring an existing revision',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(page(),denied(409,'claim_conflict'));e.submit();await e.flush();
 assert.equal(writes(e).length,1);assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimSave').disabled,false);assert.match(e.control('claimMessage').textContent,/retry_conflict/);
 e.replies.push(page(),{claim:claim()});e.submit();await e.flush();assert.equal(writes(e).length,2);assert.equal(JSON.parse(writes(e)[1].options.body).body,'my edited note');assert.equal(e.control('claimMessage').textContent,'claims.saved');
});

for(const failure of [Error('response lost'),denied(503,'temporarily_unavailable'),{claim:{}}])test('An ambiguous create result locks ordinary Save until explicit read-and-acknowledge',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(page(),failure);e.submit();await e.flush();
 assert.equal(writes(e).length,1);assert.equal(e.control('claimBody').value,'my edited note');assert.equal(e.control('claimSave').disabled,true);assert.match(e.control('claimMessage').textContent,/claims.uncertain/);
 e.submit();e.control('claimRetryCreate').onclick();await e.flush();assert.equal(writes(e).length,1);assert.equal(e.control('claimSave').disabled,true);
 // The first POST was committed even though its response was lost.
 e.rows([claim({body:'my edited note'})]);await e.control('claimCheckSubmission').onclick();assert.match(e.control('claimUncertainResults').textContent,/my edited note/);assert.equal(writes(e).length,1);assert.equal(e.control('claimSave').disabled,true);
 e.control('claimRetryCreate').onclick();assert.equal(e.control('claimSave').disabled,false);assert.equal(writes(e).length,1);
 e.replies.push(page([claim()]),{claim:claim({id:'24'})});e.submit();await e.flush();assert.equal(writes(e).length,2);
});

test('Preflight transport failure does not mark a create as ambiguously committed because no write was attempted',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();populated(e);e.replies.push(Error('preflight failed'));e.submit();await e.flush();assert.equal(writes(e).length,0);assert.equal(e.control('claimSave').disabled,false);assert.equal(e.control('claimCheckSubmission').hidden,true);
});

const mediaClaim=(extra={})=>claim({claim_type:'media',specification_kind:null,incident_kind:null,spec_items:[],media_items:[{id:'31',mime_type:'image/jpeg'}],...extra});
const imageFile=(name='private.png',type='image/png')=>new File(['fixture private pixels'],name,{type});
async function selectMedia(e,files=[imageFile()]){e.control('claimKind').value='media';e.control('claimKind').onchange();e.control('claimMediaInput').files=files;e.control('claimMediaInput').onchange();await e.flush()}

test('Media creation uses exactly multipart metadata and original images after a fresh access check',async()=>{
 const e=environment(),files=[imageFile('private.png'),imageFile('private.webp','image/webp')];await e.component.setCatalogIntent('12');e.start();await selectMedia(e,files);
 assert.equal(e.control('claimBody').required,false);assert.equal(e.control('claimField_0').required,false);assert.equal(e.control('claimSave').disabled,false);assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,2);
 field(e,'claimBody','  Caption <img onerror=x>  ');field(e,'claimDate','');e.rows([mediaClaim()]);e.replies.push(page(),{claim:mediaClaim()});e.submit();e.submit();await e.flush();
 assert.equal(writes(e).length,1);const sent=writes(e)[0];assert.equal(sent.url,'/api/auth/guitars/12/media-claims');assert.equal(sent.options.method,'POST');assert.equal(sent.verified,true);assert.equal(sent.options.headers['Content-Type'],undefined);
 const data=sent.options.body;assert.ok(data instanceof FormData);assert.deepEqual([...data.keys()],['metadata','images','images']);assert.deepEqual(JSON.parse(data.get('metadata')),{claim_type:'media',body:'Caption <img onerror=x>',occurred_at:null});
 assert.deepEqual(data.getAll('images').map(f=>[f.name,f.type]),files.map(f=>[f.name,f.type]));assert.equal(await data.getAll('images')[0].text(),await files[0].text());
 assert.equal(e.control('claimMediaInput').hidden,true);assert.equal(e.control('claimKind').disabled,true);assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,1);assert.equal(e.publicCalls.length,0);
 assert.deepEqual(e.photoCalls.map(c=>c.url),['/api/auth/guitars/12/claims/23/media/31?revision='+'a'.repeat(64)]);assert.equal(e.photoCalls[0].verified,true);assert.equal(e.photoCalls[0].options.cache,'no-store');
 e.dismiss();assert.deepEqual(e.revokedUrls.sort(),e.createdUrls.sort());assert.equal(e.control('claimMediaPhotos').children.length,0);
});

test('Media edits change only caption/date while preserving Verification and immutable attachments',async()=>{
 const e=environment(),row=mediaClaim({verification_status:'positive',occurred_at:'2026-01-01T11:22:33Z'});e.rows([row]);await e.component.setCatalogIntent('12');e.open();await e.flush();
 assert.equal(e.control('claimKind').disabled,true);assert.equal(e.control('claimMediaInput').hidden,true);field(e,'claimBody','edited');e.control('claimKind').value='theft';e.replies.push(page([row]),{claim:row});e.submit();await e.flush();
 const sent=writes(e)[0];assert.equal(sent.options.method,'PATCH');assert.deepEqual(JSON.parse(sent.options.body),{claim_type:'media',body:'edited',occurred_at:'2026-01-01T11:22:33Z',revision:row.revision});assert.match(e.control('claimSavedState').textContent,/chronicle.positive/);
});

test('Own inactive Media photos stay viewable with edits and deactivation disabled',async()=>{
 const e=environment();e.rows([mediaClaim({status:'inactive'})]);await e.component.setCatalogIntent('12');e.open();await e.flush();assert.equal(e.control('claimSave').disabled,true);assert.equal(e.control('claimDeactivate').hidden,true);assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,1);assert.equal(writes(e).length,0);
});

for(const files of [[],Array.from({length:11},()=>imageFile()),[imageFile('animation.gif','image/gif')],[{type:'image/png',size:8*1024*1024+1}],Array.from({length:4},()=>({type:'image/png',size:8*1024*1024}))])test('Invalid Media count/type/per-image/combined size cannot write',async()=>{
 const e=environment();await e.component.setCatalogIntent('12');e.start();await selectMedia(e,files);assert.equal(e.control('claimSave').disabled,true);assert.match(e.control('claimMediaMessage').textContent,/media_invalid/);e.submit();await e.flush();assert.equal(writes(e).length,0);
});

test('A Media upload with an unknown result keeps original files and needs a fresh list plus explicit retry',async()=>{
 const e=environment(),file=imageFile();await e.component.setCatalogIntent('12');e.start();await selectMedia(e,[file]);field(e,'claimBody','UNCONFIRMED MEDIA');e.replies.push(page(),Error('upload response lost'));e.submit();await e.flush();
 assert.equal(writes(e).length,1);assert.equal(e.control('claimSave').disabled,true);assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,1);assert.equal(e.control('claimMediaInput').files[0],file);
 e.submit();e.control('claimRetryCreate').onclick();await e.flush();assert.equal(writes(e).length,1);e.rows([mediaClaim({body:'UNCONFIRMED MEDIA'})]);await e.control('claimCheckSubmission').onclick();assert.match(e.control('claimUncertainResults').textContent,/UNCONFIRMED MEDIA/);assert.equal(e.control('claimSave').disabled,true);assert.equal(writes(e).length,1);
 e.control('claimRetryCreate').onclick();assert.equal(writes(e).length,1);e.replies.push(page([mediaClaim()]),{claim:mediaClaim()});e.submit();await e.flush();assert.equal(writes(e).length,2);assert.equal(writes(e)[1].options.body.getAll('images')[0],file);
});

for(const interruption of ['close','intent','signout','account','unverified'])test(`Late private Media bytes after ${interruption} cannot create or retain blob URLs`,async()=>{
 const e=environment(),held=deferred();e.rows([mediaClaim()]);await e.component.setCatalogIntent('12');e.photoReplies.push(held.promise);e.open();await e.flush();
 if(interruption==='close')e.dismiss();else if(interruption==='intent')await e.component.setCatalogIntent('13');else e.changeAccount(interruption==='signout'?null:account(interruption==='account'?'second':'first',interruption!=='unverified'));
 held.resolve(new Blob(['private'],{type:'image/jpeg'}));await e.flush();assert.equal(e.dialog.open,false);assert.equal(e.createdUrls.length,0);assert.equal(e.control('claimMediaPhotos').children.length,0);
});

for(const status of [401,403,404])test(`Private Media denial ${status} revokes loaded photos, closes the editor, and refreshes access`,async()=>{
 const e=environment(),row=mediaClaim({media_items:[{id:'31',mime_type:'image/jpeg'},{id:'32',mime_type:'image/jpeg'}]});e.rows([row]);await e.component.setCatalogIntent('12');e.photoReplies.push(new Blob(['private'],{type:'image/jpeg'}),denied(status));e.open();await e.flush();
 assert.equal(e.dialog.open,false);assert.equal(e.control('claimMediaPhotos').children.length,0);assert.equal(e.createdUrls.length,1);assert.deepEqual(e.revokedUrls,e.createdUrls);assert.equal(e.calls.filter(c=>c.url.endsWith('/claims')).length,2);assert.equal(writes(e).length,0);
});

test('Stale Media revision clears photos and preserves caption edits until explicit rebase',async()=>{
 const e=environment(),row=mediaClaim(),changed=mediaClaim({revision:'b'.repeat(64),body:'REMOTE CAPTION'});e.rows([row]);await e.component.setCatalogIntent('12');e.photoReplies.push(denied(409));e.replies.push(page([changed]));e.open();field(e,'claimBody','MY CAPTION');await e.flush();assert.equal(e.dialog.open,true);assert.equal(e.control('claimMediaPhotos').children.length,0);assert.equal(e.control('claimSave').disabled,true);assert.match(e.control('claimLatest').textContent,/REMOTE CAPTION/);
 e.control('claimKeepEdits').onclick();await e.flush();assert.equal(e.control('claimBody').value,'MY CAPTION');assert.ok(e.photoCalls.at(-1).url.endsWith('b'.repeat(64)));assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,1);assert.equal(writes(e).length,0);
});

test('Read-only Media is readable and a legacy unavailable photo does not disable authorized caption editing',async()=>{
 const e=environment();e.replies.push(page([mediaClaim()],{can_write:false}));await e.component.setCatalogIntent('12');e.open();await e.flush();assert.equal(e.control('claimMediaPhotos').querySelectorAll('img').length,1);assert.equal(e.control('claimSave').disabled,true);e.dismiss();
 e.replies.push(page([mediaClaim()]));await e.component.refresh();e.photoReplies.push(denied(400));e.open();await e.flush();assert.equal(e.control('claimSave').disabled,false);assert.equal(e.control('claimMediaReload').hidden,false);assert.match(e.control('claimMediaMessage').textContent,/media_failed/);
});
