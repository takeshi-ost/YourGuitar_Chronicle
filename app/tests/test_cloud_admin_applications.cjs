const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const revision='a'.repeat(32),second='b'.repeat(32),version='1'.repeat(64);
const manual={mode:'external_mcp',automatic_start:false,instructions:'Use a separately authorized MCP session.'};
const row=(overrides={})=>({revision,request_kind:'acquire',status:'pending',applicant_id:'1',applicant_name:'<img src=x>',product_name:'Test guitar',serial:'S1',individual_id:'12',claim_id:null,verification_status:null,management_version:version,admin_actions:['accept','reject','retry','cancel'],photos:['closeup','overview','reference'],review_enabled:false,manual_review:manual,paused_answers:[{kind:'review',received_at:'now'}],events:[{id:'1',at:'now',kind:'admin_review',note:'<script>private</script>'}],result:{accepted:false},received:{raw:'<b>answer</b>'},report:'<img src=x>',product_details:{model:'Fixture'},product_observations:{model:'Observed'},admin_review:null,...overrides});
const page=(items=[row()],extra={})=>({items,next_after:null,total:String(items.length),review_enabled:false,manual_review:manual,...extra});
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}}
function environment(){
  const ids=new Map(),listeners={};
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.style={};this._value='';this.hidden=false;this.open=false;this.disabled=false;this.textContent='';this.tabIndex=0;this.isConnected=true;this.classList={add(){},remove(){}}}
    set id(v){this._id=v;ids.set(v,this)}get id(){return this._id}
    get value(){return this.tagName==='SELECT'?(this._value||this.children[0]?.value||''):this._value}set value(v){this._value=v}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes;if(this.tagName==='SELECT')this._value=''}
    setAttribute(k,v){this[k]=v}removeAttribute(k){delete this[k]}hasAttribute(k){return k in this}
    addEventListener(k,fn){(this.listeners[k]??=[]).push(fn)}dispatchEvent(e){for(const fn of this.listeners[e.type]||[])fn(e)}
    focus(){document.activeElement=this}closest(){return null}all(){return this.children.flatMap(n=>[n,...n.all()])}contains(n){return this===n||this.all().includes(n)}
    querySelectorAll(s){const tags=s.split(',').filter(t=>/^[a-z]+$/.test(t)).map(t=>t.toUpperCase());return this.all().filter(n=>tags.includes(n.tagName))}
    querySelector(s){return this.querySelectorAll(s)[0]||null}getClientRects(){return this.hidden?[]:[this.getBoundingClientRect()]}
    getBoundingClientRect(){return {left:20,right:900,top:20,bottom:700}}showModal(){this.open=true;this.opens=(this.opens||0)+1}close(){this.open=false}
  }
  const document={body:new Element('body'),createElement:t=>new Element(t),getElementById:id=>ids.get(id),addEventListener(k,fn){(listeners[k]??=[]).push(fn)}};
  const root=new Element('section');root.id='applicationBrowser';document.body.append(root);
  const calls=[],replies=[],created=[],revoked=[],denied=[],guitars=[];let allowed=true;
  const URLMock={createObjectURL(blob){const url='blob:fixture-'+created.length;created.push({url,blob});return url},revokeObjectURL(url){revoked.push(url)}};
  const context=vm.createContext({document,URL:URLMock,URLSearchParams,Date,console,CustomEvent:class{constructor(type){this.type=type}},YGCI18n:{t:(key,params={})=>key+Object.values(params).join(',')}});context.window=context;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/overlays.js'),'utf8'),context);
  const request=async(url,options={},binary=false)=>{calls.push({url,options,binary});assert.ok(replies.length,'Missing response for '+url);const value=await replies.shift();if(value instanceof Error)throw value;return value};
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-console-applications.js'),'utf8').replace('export function','function')+';globalThis.create=createApplicationBrowser;',context);
  const ui=context.create({request,authorized:()=>allowed,onUnauthorized:e=>denied.push(e),onGuitar:id=>guitars.push(id)}),get=id=>ids.get('adminApplication'+id);
  return {ui,get,calls,replies,root,created,revoked,denied,guitars,
    async open(data=row()){replies.push(data);await ui.detail(data.revision)},
    prepare(op='accept',reason='Verified photos manually'){get('Operation').value=op;get('Reason').value=reason;get('Reason').oninput();get('ReviewAction').onclick()},
    dismiss(kind='close'){if(kind==='close')get('Close').onclick();else{const e={target:get('Dialog'),key:kind==='escape'?'Escape':undefined,clientX:1,clientY:1,preventDefault(){},stopImmediatePropagation(){}};for(const fn of listeners[kind==='escape'?'keydown':'click']||[])fn(e)}},
    signout(clear=true){allowed=false;if(clear)ui.clear();ui.render()},signin(){allowed=true;ui.render()},
    async flush(){for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve))},
  };
}
const http=status=>Object.assign(Error('private backend error'),{status});

test('Search, filters, cursor pagination and latest list win; requests are never cached',async()=>{
  const e=environment();e.replies.push(page([row()],{next_after:second,total:'26'}));await e.ui.refresh();
  assert.equal(e.get('Rows').children.length,1);assert.equal(e.get('Rows').querySelectorAll('img').length,0);assert.equal(e.get('Next').disabled,false);
  e.replies.push(page([row({revision:second})]));e.get('Next').onclick();await e.flush();assert.equal(new URL('https://fixture'+e.calls.at(-1).url).searchParams.get('after'),second);
  e.replies.push(page());e.get('Previous').onclick();await e.flush();assert.equal(new URL('https://fixture'+e.calls.at(-1).url).searchParams.has('after'),false);
  e.get('Search').value=' serial ';e.get('StatusFilter').value='error';e.get('KindFilter').value='listing';e.replies.push(page([]));e.get('SearchForm').onsubmit({preventDefault(){}});await e.flush();
  const params=new URL('https://fixture'+e.calls.at(-1).url).searchParams;assert.equal(params.get('q'),'serial');assert.equal(params.get('status'),'error');assert.equal(params.get('kind'),'listing');assert.equal(e.get('Previous').disabled,true);
  const old=deferred();e.replies.push(old.promise,page([row({serial:'NEW'})]));const first=e.ui.refresh();await e.ui.refresh();old.resolve(page([row({serial:'OLD'})]));await first;
  assert.equal(e.get('Rows').children[0].children[2].textContent,'NEW');for(const call of e.calls)assert.equal(call.options.cache,'no-store');
});

test('Private detail JSON/history render only text; photos use binary request and URLs are revoked',async()=>{
  const e=environment();await e.open();assert.equal(e.get('Report').textContent,'<img src=x>');assert.equal(e.get('Report').children.length,0);assert.equal(e.get('Events').querySelectorAll('script').length,0);
  assert.match(e.get('DetailReview').textContent,/review_off/);assert.match(e.get('DetailFields').all().map(n=>n.textContent).join(' '),/paused_answers/);
  e.replies.push(new Blob(['photo']));await e.get('Photo_reference').onclick();assert.equal(e.calls.at(-1).binary,true);assert.match(e.calls.at(-1).url,/\/photos\/reference$/);assert.equal(e.created.length,1);
  e.dismiss();assert.deepEqual(e.revoked,['blob:fixture-0']);assert.equal(e.get('Photos').querySelectorAll('img').every(n=>!n.src&&n.hidden),true);
});

for(const op of ['accept','reject','retry','cancel'])test(`${op} requires reasoned confirmation, exact CAS body, and one POST even with Review OFF`,async()=>{
  const e=environment();await e.open();e.prepare(op,'');assert.equal(e.get('Confirm').hidden,true);
  e.prepare(op,' Valid reason ');assert.equal(e.get('Confirm').hidden,false);assert.match(e.get('Confirmation').textContent,/confirm_off/);
  const pending=deferred();e.replies.push(pending.promise,page());const first=e.get('Confirm').onclick();e.get('Confirm').onclick();assert.equal(e.calls.filter(c=>c.options.method==='POST').length,1);
  const sent=e.calls.at(-1);assert.equal(sent.url,'/api/admin/applications/'+revision+'/decision');assert.deepEqual(JSON.parse(sent.options.body),{operation:op,reason:'Valid reason',expected_version:version});
  pending.resolve(row({management_version:'2'.repeat(64),admin_actions:[]}));await first;assert.equal(e.get('Dialog').open,true);assert.match(e.get('DetailStatus').textContent,/saved/);assert.equal(e.get('ReviewAction').disabled,true);
});

test('Editing the reason or operation invalidates confirmation, including programmatic edits',async()=>{
  const e=environment();await e.open();e.prepare();e.get('Reason').value='Different';e.get('Reason').oninput();assert.equal(e.get('Confirm').hidden,true);await e.get('Confirm').onclick();assert.equal(e.calls.length,1);
  e.prepare();e.get('Operation').value='reject';e.get('Operation').onchange();assert.equal(e.get('Confirm').hidden,true);
  e.prepare();e.get('Reason').value='Unsynced edit';await e.get('Confirm').onclick();assert.equal(e.calls.length,1);assert.equal(e.get('Confirm').hidden,true);
});

for(const dismiss of ['close','escape','backdrop'])test(`${dismiss} during a POST still refreshes list and never reopens detail`,async()=>{
  const e=environment();await e.open();e.prepare();const pending=deferred();e.replies.push(pending.promise,page([row({status:'accepted'})]));const work=e.get('Confirm').onclick();e.dismiss(dismiss);
  assert.equal(e.get('Dialog').open,false);pending.resolve(row({status:'accepted'}));await work;assert.equal(e.get('Dialog').open,false);assert.equal(e.get('Dialog').opens,1);assert.match(e.get('Rows').children[0].children[4].textContent,/accepted/);
});

for(const code of [400,409,500])test(`Decision HTTP ${code} requires fresh detail before retry; no private error text leaks`,async()=>{
  const e=environment();await e.open();e.prepare();e.replies.push(http(code));await e.get('Confirm').onclick();assert.equal(e.get('ReviewAction').disabled,true);assert.match(e.get('DetailStatus').textContent,/refresh_before_retry/);assert.doesNotMatch(e.get('DetailStatus').textContent,/private backend/);
  e.prepare();await e.get('Confirm').onclick();assert.equal(e.calls.length,2);e.replies.push(row({management_version:'3'.repeat(64)}));await e.get('DetailRefresh').onclick();e.prepare();assert.equal(e.get('Confirm').disabled,false);
});

for(const stage of ['list','detail','photo','post'])test(`Signout invalidates pending ${stage} and discards later success across re-entry`,async()=>{
  const e=environment(),pending=deferred();let work;
  if(['photo','post'].includes(stage))await e.open();
  if(stage==='post')e.prepare();e.replies.push(pending.promise);
  if(stage==='list')work=e.ui.refresh();if(stage==='detail')work=e.ui.detail(revision);if(stage==='photo')work=e.get('Photo_closeup').onclick();if(stage==='post')work=e.get('Confirm').onclick();
  e.signout();e.signin();e.replies.push(page([row({serial:'CURRENT'})]));await e.ui.refresh();const count=e.calls.length;
  pending.resolve(stage==='photo'?new Blob(['old']):stage==='list'?page([row({serial:'OLD'})]):row());await work;
  assert.equal(e.calls.length,count);assert.equal(e.get('Dialog').open,false);assert.equal(e.created.length,0);assert.equal(e.get('Rows').children[0].children[2].textContent,'CURRENT');
});

test('Authorization render boundary purges private data and object URLs without needing explicit clear',async()=>{
  const e=environment();await e.open();e.replies.push(new Blob(['photo']));await e.get('Photo_closeup').onclick();e.signout(false);assert.equal(e.get('Dialog').open,false);assert.equal(e.get('Report').textContent,'');assert.equal(e.revoked.length,1);
});

test('New detail and image requests supersede old replies; dismissal cancels pending detail display',async()=>{
  const e=environment(),pending=deferred();e.replies.push(pending.promise,row({revision:second,serial:'NEW'}));const first=e.ui.detail(revision);await e.ui.detail(second);pending.resolve(row({serial:'OLD'}));await first;assert.match(e.get('DetailFields').all().map(n=>n.textContent).join(' '),/NEW/);
  const oldPhoto=deferred();e.replies.push(oldPhoto.promise,new Blob(['new']));const image=e.get('Photo_closeup').onclick();await e.get('Photo_closeup').onclick();oldPhoto.resolve(new Blob(['old']));await image;assert.equal(e.created.length,1);
  const detail=deferred();e.replies.push(detail.promise);const last=e.ui.detail(revision);e.dismiss('escape');detail.resolve(row());await last;assert.equal(e.get('Dialog').open,false);assert.equal(e.get('DetailFields').children.length,0);
});

for(const code of [401,403])test(`HTTP ${code} clears private data and delegates access revocation`,async()=>{
  const e=environment();await e.open();e.replies.push(http(code));await e.get('Photo_closeup').onclick();assert.equal(e.denied.length,1);assert.equal(e.get('Dialog').open,false);assert.equal(e.get('DetailFields').children.length,0);
});

test('Malformed capabilities fail closed and Claim verification has only a separate guitar link',async()=>{
  const e=environment();e.replies.push(row({admin_actions:['verify']}));await e.ui.detail(revision);assert.equal(e.get('ReviewAction').disabled,true);assert.equal(e.get('Confirm').hidden,true);
  await e.open();e.get('OpenGuitar').onclick();assert.deepEqual(e.guitars,['12']);assert.equal(e.get('Dialog').open,false);
  const source=fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-console-applications.js'),'utf8');assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|\/verification|\/moderate|child_process/);
});

test('Corrupt photo references leave diagnostics and allowed decisions available, with an explicit warning',async()=>{
  const e=environment();await e.open(row({photos:[],photos_unavailable:true,status:'accepted',verification_status:'unverified',admin_actions:['reject']}));
  assert.match(e.get('PhotoWarning').textContent,/photos_unavailable/);assert.match(e.get('OwnerNotice').textContent,/owner_waiting/);assert.equal(e.get('Photos').children.every(n=>n.hidden),true);
  e.prepare('reject');assert.equal(e.get('Confirm').disabled,false);assert.equal(e.get('Report').textContent,'<img src=x>');e.dismiss();assert.equal(e.get('PhotoWarning').textContent,'');assert.equal(e.get('OwnerNotice').textContent,'');
});

test('Missing or failed private photos keep the review open with diagnostics and can be retried',async()=>{
  const e=environment();await e.open();e.replies.push(http(404));await e.get('Photo_closeup').onclick();
  const figure=e.get('Photos').children[0];assert.match(figure.children[2].textContent,/photo_failed/);assert.equal(e.get('Dialog').open,true);assert.equal(e.denied.length,0);assert.equal(e.created.length,0);
  e.replies.push(new Blob(['retry']));await e.get('Photo_closeup').onclick();assert.equal(figure.children[2].textContent,'');assert.equal(figure.children[3].hidden,false);assert.equal(e.created.length,1);
});

for(const source of ['list','detail','photo','post'])test(`A late ${source} role-revocation error cannot purge a newer authorized session`,async()=>{
  const e=environment(),pending=deferred();let work;if(['photo','post'].includes(source))await e.open();if(source==='post')e.prepare();e.replies.push(pending.promise);
  if(source==='list')work=e.ui.refresh();if(source==='detail')work=e.ui.detail(revision);if(source==='photo')work=e.get('Photo_closeup').onclick();if(source==='post')work=e.get('Confirm').onclick();
  e.signout();e.signin();e.replies.push(page([row({serial:'CURRENT'})]));await e.ui.refresh();pending.resolve(http(403));await work;
  assert.equal(e.denied.length,0);assert.equal(e.root.hidden,false);assert.equal(e.get('Rows').children[0].children[2].textContent,'CURRENT');assert.equal(e.get('Dialog').open,false);
});

for(const source of ['list','detail','photo'])test(`A late ${source} role-revocation error cannot erase a newer same-session read`,async()=>{
  const e=environment(),pending=deferred();let work;if(source==='photo')await e.open();e.replies.push(pending.promise);
  if(source==='list')work=e.ui.refresh();if(source==='detail')work=e.ui.detail(revision);if(source==='photo')work=e.get('Photo_closeup').onclick();
  if(source==='list'){e.replies.push(page([row({serial:'CURRENT'})]));await e.ui.refresh()}
  else if(source==='detail'){e.replies.push(row({revision:second,serial:'CURRENT'}));await e.ui.detail(second)}
  else{e.replies.push(new Blob(['current']));await e.get('Photo_closeup').onclick()}
  pending.resolve(http(403));await work;assert.equal(e.denied.length,0);assert.equal(e.root.hidden,false);
  if(source==='list')assert.equal(e.get('Rows').children[0].children[2].textContent,'CURRENT');
  if(source==='detail')assert.match(e.get('DetailFields').all().map(n=>n.textContent).join(' '),/CURRENT/);
  if(source==='photo')assert.equal(e.created.length,1);
});
