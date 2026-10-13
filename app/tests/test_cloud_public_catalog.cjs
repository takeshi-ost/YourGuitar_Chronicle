const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const assets=path.join(__dirname,'../src/ygc/static');
const source=fs.readFileSync(path.join(assets,'cloud-public-catalog.js'),'utf8');
const html=fs.readFileSync(path.join(assets,'cloud_public_catalog_html.html'),'utf8');
const guitar=(id,extra={})=>({id:String(id),manufacturer:'Fender',model:'Model '+id,finish:'Sunburst',year:'1960',serial_number:'SERIAL-'+id,photo:null,...extra});
const claim=(id,extra={})=>({id:String(id),claim_type:'listing',ownership_kind:null,occurred_at:'2026-01-01',created_at:'2026-01-01T12:00:00Z',verification_status:'positive',items:[],source_url:null,...extra});
const response=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body});
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return {promise,resolve}};
const tick=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve))};

function environment({url='https://catalog.example/',guitars=[guitar(1),guitar(2)],signedIn=false,loadError=null,restoreError=null,locale='en',presentation={}}={}){
  const ids=new Map();
  class Element{
    constructor(tag='div'){this.classList={add:(name)=>{this.className=[this.className,name].filter(Boolean).join(' ')}};this.style={};this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.value='';this.hidden=false;this.disabled=false;this.open=false;this._text='';}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    set textContent(value){this._text=String(value);this.children=[]}get textContent(){return this._text+this.children.map(child=>child.textContent).join('')}
    set innerHTML(_){throw Error('Public data must never be inserted as HTML.')}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this._text='';this.children=nodes}
    removeAttribute(key){delete this.attributes[key];if(key==='src')delete this.src}
    setAttribute(key,value){this.attributes[key]=String(value)}getAttribute(key){return this.attributes[key]??null}
    focus(){document.activeElement=this}
    all(){return this.children.flatMap(child=>[child,...child.all()])}
  }
  const nav=new Element('nav'),document={documentElement:new Element('html'),body:new Element('body'),createElement:tag=>new Element(tag),getElementById:id=>ids.get(id),querySelector:selector=>selector==='.page-nav'?nav:null};
  for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const element=new Element(match[1]);element.id=match[2];element.hidden=/\bhidden\b/.test(match[0]);element.disabled=/\bdisabled\b/.test(match[0])}
  const listeners=new Map(),store=new Map([['ygc_ui_language',locale]]),history=[new URL(url)];let index=0;
  const window={localStorage:{getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value)},addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key)};
  window.location={get href(){return history[index].href},get pathname(){return history[index].pathname},get search(){return history[index].search},get origin(){return history[index].origin}};
  window.history={pushState(state,_,target){history.splice(index+1);history.push(new URL(target,window.location.href));index++;this.state=state},back(){if(index>0){index--;return listeners.get('popstate')?.()}},forward(){if(index<history.length-1){index++;return listeners.get('popstate')?.()}}};
  const e={ids,document,window,store,calls:[],guitars,chronicles:{},specifications:{},mode:'normal',message:'',handler:null,loadError,restoreError,loads:0,restores:0};
  async function dispatch(kind,target,options={}){
    const parsed=new URL(target,window.location.href),call={kind,url:parsed.pathname+parsed.search,path:parsed.pathname,params:parsed.searchParams,options};e.calls.push(call);
    const overridden=e.handler?.(call);if(overridden!==undefined)return await overridden;
    if(call.path==='/api/service/status')return response({mode:e.mode,message:e.message});
    if(call.path==='/api/public/guitars'){
      const q=(call.params.get('q')||'').toLowerCase(),sort=call.params.get('sort'),page=Number(call.params.get('page')||1),limit=Number(call.params.get('limit')||24);
      const filtered=e.guitars.filter(row=>[row.manufacturer,row.model,row.serial_number].some(value=>String(value||'').toLowerCase().includes(q))).slice().sort((a,b)=>{
        if(sort==='maker'||sort==='model'){const key=sort==='maker'?'manufacturer':'model';return String(a[key]).localeCompare(String(b[key]))}
        return (BigInt(a.id)<BigInt(b.id)?-1:1)*(sort==='oldest'?1:-1);
      });
      return response({items:filtered.slice((page-1)*limit,page*limit),total:String(filtered.length),page,page_size:limit,total_pages:Math.ceil(filtered.length/limit)});
    }
    if(call.path==='/api/auth/favorites')return response({items:[],total:'0',next_after:null});
    if(call.path.startsWith('/api/auth/favorites/'))return response({individual_id:call.path.split('/').at(-1),favorite:false});
    const match=/^\/api\/public\/guitars\/([1-9][0-9]*)(\/chronicle)?$/.exec(call.path);
    if(match){
      const row=e.guitars.find(row=>row.id===match[1]);if(!row)return response({detail:'Missing'},404);
      if(!match[2])return response({...row,specifications:e.specifications[row.id]||[]});
      const after=call.params.get('after'),values=(e.chronicles[row.id]||[]).filter(item=>!after||BigInt(item.id)<BigInt(after)).slice().sort((a,b)=>BigInt(a.id)>BigInt(b.id)?-1:1),items=values.slice(0,25);
      return response({items,next_after:values.length>25?items.at(-1).id:null});
    }
    throw Error('Unexpected request '+call.url);
  }
  e.auth={onIdentityChanged:listener=>{e.identityChanged=listener;return ()=>{}},signedIn,account:signedIn?{user:{app_user_id:'uuid-1',role:'user'},identity:{email_verified:true}}:null,restore:async()=>{e.restores++;if(e.restoreError)throw e.restoreError;return e.auth.account},authorizedFetch:(url,options)=>dispatch('authorized',url,options)};
  const context=vm.createContext({document,window,URL,URLSearchParams,AbortController,loadCloudAuth:async()=>{},console});
  const localSource=fs.readFileSync(path.join(assets,'pages/user-view.js'),'utf8');vm.runInContext(localSource.slice(localSource.indexOf('function displayEventDate('),localSource.indexOf('function displayInputDate('))+';globalThis.YGCOwnershipPresentation={displayEventDate};',context);
  vm.runInContext(fs.readFileSync(path.join(assets,'cloud-account-favorites.js'),'utf8').replace(/^import .*;\n/gm,'').replaceAll('export function','function'),context);
  vm.runInContext(source.replace(/^import .*;\n/gm,'').replace('export function','function').split('// Readiness is')[0]+';globalThis.createCatalog=createPublicCatalog;',context);
  e.ui=context.createCatalog({...presentation,document,window,request:(url,options)=>dispatch('anonymous',url,options),loadAuth:async()=>{e.loads++;if(e.loadError)throw e.loadError;return e.auth}});
  e.emit=(name,event={})=>listeners.get(name)?.(event);
  e.publicCalls=()=>e.calls.filter(call=>call.path.startsWith('/api/public/'));
  e.links=()=>ids.get('catalogRows').all().filter(node=>node.tag==='a'&&!node.id?.endsWith('favoriteAccount'));
  e.click=(node,extra={})=>node.onclick({button:0,preventDefault(){},...extra});
  e.text=id=>ids.get(id).textContent;
  return e;
}

test('Anonymous catalog restores optional auth, renders a bounded list, and only issues safe GET reads',async()=>{
  const e=environment();await e.ui.start();
  assert.equal(e.loads,1);assert.equal(e.restores,1);assert.equal(e.links().length,2);assert.equal(e.text('catalogStatus'),'2 guitars');
  assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'false');
  assert.equal(e.publicCalls().length,1);assert.equal(e.publicCalls()[0].kind,'anonymous');assert.equal(e.publicCalls()[0].params.get('limit'),'24');
  for(const call of e.calls){assert.equal(call.options.method,'GET');assert.equal(call.options.cache,call.path==='/api/service/status'?'no-store':'no-cache');assert.equal(call.options.credentials,'omit');assert.equal(call.options.redirect,'error')}
  assert.ok(!e.calls.some(call=>/\/api\/(admin|individuals|users|claims)/.test(call.path)));
});

test('Auth loader or anonymous initialization failure leaves public browsing available with an honest notice',async()=>{
  for(const args of [{loadError:Error('SDK unavailable')},{restoreError:Error('SDK storage unavailable')}]){
    const e=environment(args);await e.ui.start();assert.equal(e.links().length,2);assert.match(e.text('authNotice'),/still browse/);assert.ok(e.publicCalls().every(call=>call.kind==='anonymous'));
  }
});

test('Signed-in requests use the restored identity and are never retried as anonymous after token rejection',async()=>{
  const e=environment({signedIn:true});e.handler=call=>call.path.startsWith('/api/public/')?response({detail:'Invalid identity'},401):undefined;
  await e.ui.start();assert.equal(e.restores,1);assert.equal(e.publicCalls().length,1);assert.equal(e.publicCalls()[0].kind,'authorized');
  assert.equal(e.links().length,0);assert.match(e.text('catalogStatus'),/session could not be verified/);
  e.handler=null;await e.ui.refresh();assert.equal(e.restores,2);assert.equal(e.links().length,2);assert.ok(e.publicCalls().every(call=>call.kind==='authorized'));
});

test('A rejected restore, including one that clears signedIn, cannot silently downgrade to anonymous',async()=>{
  for(const signedIn of [true,false]){
    const e=environment({signedIn,restoreError:Object.assign(Error('Invalid token'),{status:401})});await e.ui.start();
    assert.equal(e.publicCalls().length,0);assert.equal(e.links().length,0);assert.match(e.text('catalogStatus'),/session could not be verified/);
  }
});

test('SDK token-invalid errors cannot downgrade even if the SDK clears the cached identity',async()=>{
  for(const code of ['auth/invalid-user-token','auth/user-token-expired','auth/id-token-revoked','auth/user-disabled']){
    const e=environment({restoreError:Object.assign(Error('Invalid identity'),{code})});await e.ui.start();
    assert.equal(e.publicCalls().length,0);assert.match(e.text('catalogStatus'),/session could not be verified/);
  }
});

test('A signed-in non-auth restore failure blocks public reads until an explicit successful refresh',async()=>{
  const e=environment({signedIn:true,restoreError:Error('Network failed')});await e.ui.start();
  assert.equal(e.publicCalls().length,0);assert.match(e.text('catalogStatus'),/temporarily unavailable/);
  e.restoreError=null;await e.ui.refresh();assert.equal(e.publicCalls().length,1);assert.equal(e.publicCalls()[0].kind,'authorized');
});

test('Deep links preserve large string identifiers, public specifications, placeholders and an inert account Acquire link',async()=>{
  const id='9007199254741009',e=environment({url:'https://catalog.example/guitars/'+id,guitars:[guitar(id)]});
  e.specifications[id]=[{field_name:'pickups',value_text:'Two single coils'},{field_name:'body',value_text:'Alder'},{field_name:'finish',value_text:'White'}];
  e.chronicles[id]=[claim('99',{items:[{field_name:'model',value_text:'Historical Model'}],source_url:'https://reverb.com/item/12345'})];await e.ui.start();
  assert.equal(e.ids.get('detailContent').hidden,false);assert.match(e.text('detailTitle'),new RegExp(id));assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'true');
  assert.equal(e.ids.get('acquireLink').href,'/ui/profile?acquire='+id);assert.equal(e.ids.get('acquireLink').onclick,undefined);assert.equal(e.ids.get('addClaimLink').href,'/ui/profile?claim='+id);assert.equal(e.ids.get('addClaimLink').onclick,undefined);
  assert.match(e.text('detailSpecifications'),/White/);assert.doesNotMatch(e.text('detailSpecifications'),/Sunburst/);
  const fields=e.ids.get('detailSpecifications').children.map(row=>row.children[0].textContent);assert.ok(fields.indexOf('Body')<fields.indexOf('Pickups'));
  assert.equal(e.text('photoPlaceholder'),'Photo unavailable');assert.equal(e.ids.get('detailContent').all().filter(node=>node.tag==='img').length,0);
  assert.equal(e.publicCalls().length,3);assert.ok(e.publicCalls().some(call=>call.path==='/api/public/guitars/'+id+'/chronicle'));
});

test('Untrusted values stay text; Chronicle omits private extra fields and allows only canonical marketplace source links',async()=>{
  const attack='<img src=x onerror=alert(1)>',e=environment({url:'https://catalog.example/guitars/1',guitars:[guitar(1,{manufacturer:attack,current_owner_name:'PRIVATE',photo:{url:'https://storage/private'}})]});
  e.specifications['1']=[{field_name:'body',value_text:attack}];
  const urls=['javascript:alert(1)','https://user:password@reverb.com/item/12','http://reverb.com/item/12','https://reverb.com/item/12?token=secret','https://reverb.com/item/12#fragment','https://other.example/item/12','https://reverb.com/item/12\n','https://reverb.com/item/12'];
  e.chronicles['1']=urls.map((source_url,i)=>claim(String(i+1),{source_url,body:'PRIVATE',author_name:'PRIVATE',evidence:[{url:'PRIVATE'}],items:[{field_name:'finish',value_text:attack}]}));
  e.chronicles['1'].push(claim('90',{verification_status:'negative',source_url:urls.at(-1),items:[{field_name:'finish',value_text:'PRIVATE'}]}),claim('91',{verification_status:'unverified',source_url:urls.at(-1),items:[{field_name:'finish',value_text:'PRIVATE'}]}));
  await e.ui.start();assert.match(e.text('detailTitle'),/<img/);assert.match(e.text('detailSpecifications'),/<img/);assert.doesNotMatch(e.text('chronicleEntries'),/PRIVATE/);
  const all=e.ids.get('chronicleEntries').all(),links=all.filter(node=>node.tag==='a'&&!node.id?.endsWith('favoriteAccount'));assert.equal(links.length,1);assert.equal(links[0].href,'https://reverb.com/item/12');assert.equal(links[0].rel,'noopener noreferrer');assert.equal(links[0].target,'_blank');assert.ok(!all.some(node=>node.tag==='img'));
  const negative=e.ids.get('chronicleEntries').children.find(node=>node.className.endsWith('negative'));assert.equal(negative.textContent,'●');
});

test('Search, sorting and pagination live in the URL and Back/Forward restore the same view',async()=>{
  const e=environment({guitars:Array.from({length:27},(_,i)=>guitar(i+1))});await e.ui.start();
  assert.equal(e.links().length,24);assert.equal(e.text('catalogPage'),'Page 1 of 2');await e.ids.get('catalogNext').onclick();
  assert.equal(e.window.location.search,'?page=2');assert.equal(e.links().length,3);assert.equal(e.ids.get('catalogNext').disabled,true);
  const detailLink=e.links()[0];await e.click(detailLink);assert.match(e.window.location.pathname,/\/guitars\//);assert.match(e.window.location.search,/page=2/);assert.equal(e.ids.get('detailContent').hidden,false);
  await e.window.history.back();assert.equal(e.window.location.pathname,'/');assert.equal(e.window.location.search,'?page=2');assert.equal(e.ids.get('detailContent').hidden,true);
  await e.window.history.forward();assert.equal(e.ids.get('detailContent').hidden,false);await e.click(e.ids.get('catalogBack'));assert.equal(e.window.location.pathname,'/');assert.equal(e.window.location.search,'?page=2');
  e.ids.get('catalogSearch').value=' SERIAL-17 ';e.ids.get('catalogSort').value='maker';await e.ids.get('catalogSearchForm').onsubmit({preventDefault(){}});
  assert.equal(e.window.location.search,'?q=SERIAL-17&sort=maker');assert.equal(e.links().length,1);assert.equal(e.ids.get('catalogSearch').value,'SERIAL-17');assert.equal(e.ids.get('catalogSort').value,'maker');
  await e.window.history.back();assert.equal(e.window.location.search,'?page=2');assert.equal(e.links().length,3);
});

test('English/Japanese controls persist language without refetching or translating user content',async()=>{
  const e=environment({url:'https://catalog.example/guitars/1'});await e.ui.start();const count=e.calls.length;
  e.ids.get('catalogLanguage').value='ja';e.ids.get('catalogLanguage').onchange();
  assert.equal(e.document.documentElement.lang,'ja');assert.equal(e.store.get('ygc_ui_language'),'ja');assert.equal(e.text('catalogRefresh'),'更新');assert.equal(e.text('acquireLink'),'所有申請');assert.equal(e.text('addClaimLink'),'Claimを追加');assert.equal(e.text('catalogBack'),'カタログに戻る');assert.equal(e.text('detailTitle'),'Fender Model 1');assert.equal(e.calls.length,count);
  const saved=environment({locale:'ja'});await saved.ui.start();assert.equal(saved.text('catalogSearchSubmit'),'検索');
});

test('Newer selections clear old detail immediately and reject late results even if fetch ignores abort',async()=>{
  const e=environment({url:'https://catalog.example/guitars/1'});await e.ui.start();assert.match(e.text('detailTitle'),/Model 1/);
  const hold=deferred();e.handler=call=>call.path==='/api/public/guitars/2'?hold.promise:undefined;
  const obsolete=e.ui.navigate('/guitars/2');await tick();assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.text('detailTitle'),'');assert.equal(e.ids.get('acquireLink').href,'/ui/profile');assert.equal(e.ids.get('addClaimLink').href,'/ui/profile');
  const oldRequest=e.publicCalls().findLast(call=>call.path==='/api/public/guitars/2');e.handler=null;await e.ui.navigate('/guitars/1?q=Fender');
  assert.equal(oldRequest.options.signal.aborted,true);assert.match(e.text('detailTitle'),/Model 1/);
  hold.resolve(response({...guitar(2),specifications:[]}));await obsolete;assert.match(e.text('detailTitle'),/Model 1/);assert.equal(e.window.location.pathname,'/guitars/1');
});

test('An obsolete search cannot overwrite a newer search or Back navigation',async()=>{
  const e=environment();await e.ui.start();const hold=deferred();e.handler=call=>call.path==='/api/public/guitars'&&call.params.get('q')==='old'?hold.promise:undefined;
  const old=e.ui.navigate('/?q=old');await tick();await e.ui.navigate('/?q=SERIAL-1');assert.equal(e.links().length,1);assert.match(e.text('catalogRows'),/Model 1/);
  const back=e.window.history.back();assert.equal(e.window.location.search,'?q=old');await tick();
  // Navigate away from both held requests; neither may repopulate the list.
  await e.ui.navigate('/?q=SERIAL-2');hold.resolve(response({items:[guitar(99)],total:'1',page:1,page_size:24,total_pages:1}));await old;await back;await tick();
  assert.match(e.text('catalogRows'),/Model 2/);assert.doesNotMatch(e.text('catalogRows'),/Model 99/);
});

test('Repeated Refresh is one request batch and failures clear the previous list and detail',async()=>{
  const e=environment({url:'https://catalog.example/guitars/1'});await e.ui.start();const hold=deferred(),before=e.calls.length;
  e.handler=call=>call.path==='/api/public/guitars'?hold.promise:undefined;
  const first=e.ui.refresh(),second=e.ui.refresh();assert.equal(first,second);await tick();assert.equal(e.calls.length-before,4);assert.equal(e.ids.get('detailContent').hidden,false);assert.match(e.text('detailTitle'),/Model 1/);
  hold.resolve(response({detail:'Unavailable'},503));await first;assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('detailStatus'),/temporarily unavailable/);assert.equal(e.ids.get('catalogRefresh').disabled,false);
});

test('Chronicle pagination guards repeated clicks, preserves IDs and discards results after navigating away',async()=>{
  const e=environment({url:'https://catalog.example/guitars/1'});e.chronicles['1']=Array.from({length:27},(_,i)=>claim(i+1));await e.ui.start();
  assert.equal(e.ids.get('chronicleEntries').children.length,25);assert.equal(e.ids.get('chronicleMore').hidden,false);
  const before=e.calls.length;const one=e.ids.get('chronicleMore').onclick(),two=e.ids.get('chronicleMore').onclick();await Promise.all([one,two]);
  assert.equal(e.calls.length-before,1);assert.equal(e.publicCalls().at(-1).params.get('after'),'3');assert.equal(e.ids.get('chronicleEntries').children.length,27);assert.equal(e.ids.get('chronicleMore').hidden,true);
  await e.ui.refresh();const held=deferred();e.handler=call=>call.path.endsWith('/chronicle')&&call.params.has('after')?held.promise:undefined;
  const old=e.ids.get('chronicleMore').onclick();await tick();const request=e.calls.at(-1);await e.ui.navigate('/');assert.equal(request.options.signal.aborted,true);
  held.resolve(response({items:[claim(1)],next_after:null}));await old;assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('chronicleEntries').children.length,0);
});

test('Restricted Chronicle pagination clears the public content and cannot retain an Acquire action',async()=>{
  const e=environment({url:'https://catalog.example/guitars/1'});e.chronicles['1']=Array.from({length:27},(_,i)=>claim(i+1));await e.ui.start();
  e.handler=call=>call.path.endsWith('/chronicle')&&call.params.has('after')?response({detail:{code:'service_restricted'}},403):undefined;
  await e.ids.get('chronicleMore').onclick();assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('acquireLink').href,'/ui/profile');assert.equal(e.ids.get('addClaimLink').href,'/ui/profile');assert.equal(e.links().length,0);assert.match(e.text('detailStatus'),/temporarily restricted/);
});

test('Offline/admin-only restriction is enforced by API responses, while canonical signed-in admin access remains possible',async()=>{
  for(const mode of ['offline','admin_only']){
    const e=environment({url:'https://catalog.example/guitars/1'});await e.ui.start();e.mode=mode;e.message='<img src=x> Maintenance';
    e.handler=call=>call.path.startsWith('/api/public/')?response({detail:{code:'service_restricted'}},403):undefined;
    await e.ui.refresh();assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('catalogStatus'),/temporarily restricted/);assert.ok(e.text('serviceNotice').includes('<img src=x> Maintenance'));assert.equal(e.ids.get('serviceNotice').children.length,0);
  }
  const admin=environment({signedIn:true});admin.mode='admin_only';admin.auth.account.user.role='admin';await admin.ui.start();assert.equal(admin.links().length,2);assert.match(admin.text('serviceNotice'),/administrators/);assert.ok(admin.publicCalls().every(call=>call.kind==='authorized'));
  const readonly=environment();readonly.mode='read_only';await readonly.ui.start();assert.equal(readonly.links().length,2);assert.match(readonly.text('serviceNotice'),/Read-only mode/);
});

test('Missing guitar and empty search have distinct states and no stale detail; service status failure does not invent a read ban',async()=>{
  const e=environment({url:'https://catalog.example/guitars/999'});e.handler=call=>call.path==='/api/service/status'?response({detail:'Unavailable'},503):undefined;
  await e.ui.start();assert.equal(e.links().length,2);assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('detailStatus'),/not found/);assert.match(e.text('serviceNotice'),/checked separately/);
  await e.ui.navigate('/?q=no-match');assert.equal(e.links().length,0);assert.match(e.text('catalogStatus'),/No guitars found/);assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'false');
});

test('Malformed API pages fail closed and invalid URL parameters normalize to bounded requests',async()=>{
  const e=environment({url:'https://catalog.example/?q='+('x'.repeat(200))+'&sort=unknown&page=9999999'});await e.ui.start();
  assert.equal(e.publicCalls()[0].params.get('q').length,120);assert.equal(e.publicCalls()[0].params.get('sort'),'newest');assert.equal(e.publicCalls()[0].params.get('page'),'1');
  e.handler=call=>call.path==='/api/public/guitars'?response({items:[guitar(1)],total:1,page:1,page_size:24,total_pages:1}):undefined;
  await e.ui.refresh();assert.equal(e.links().length,0);assert.match(e.text('catalogStatus'),/temporarily unavailable/);
});

test('Submitting the same search retries a failed list without adding a duplicate history entry',async()=>{
  const e=environment();e.handler=call=>call.path==='/api/public/guitars'?response({},503):undefined;await e.ui.start();
  assert.equal(e.links().length,0);e.handler=null;await e.ids.get('catalogSearchForm').onsubmit({preventDefault(){}});
  assert.equal(e.links().length,2);assert.equal(e.window.location.pathname,'/');assert.equal(e.window.location.search,'');
});

test('Native modified link clicks remain available and stopping the page prevents late DOM writes',async()=>{
  const e=environment();await e.ui.start();const before=e.calls.length;await e.click(e.links()[0],{ctrlKey:true});assert.equal(e.window.location.pathname,'/');assert.equal(e.calls.length,before);
  const hold=deferred();e.handler=call=>call.path==='/api/public/guitars/1'?hold.promise:undefined;const pending=e.ui.navigate('/guitars/1');await tick();e.ui.destroy();
  hold.resolve(response({...guitar(1),specifications:[]}));await pending;assert.equal(e.ids.get('detailContent').hidden,true);
});

test('Public shell owns only safe cloud assets and bilingual keys match',()=>{
  assert.match(html,/maxlength="120"/);assert.match(html,/\/assets\/cloud-public-catalog\.css/);assert.match(html,/\/assets\/cloud-public-catalog\.js/);
  assert.doesNotMatch(html,/local-auth|product-detail\.js|\/user-view|\/api\/users|\/console/);
  assert.doesNotMatch(source,/insertAdjacentHTML|localId|POST|PATCH|DELETE/);
  assert.match(source,/innerHTML=shared.render/); // Shared renderer escapes every DTO field.
  const context=vm.createContext({URL});vm.runInContext(source.slice(source.indexOf('const messages='),source.indexOf('const sorts='))+';globalThis.keys=[Object.keys(messages.en),Object.keys(messages.ja)];',context);
  assert.deepEqual(Array.from(context.keys[0]).sort(),Array.from(context.keys[1]).sort());
  const css=fs.readFileSync(path.join(assets,'cloud-public-catalog.css'),'utf8');assert.match(css,/@media\(max-width:900px\)/);assert.match(css,/data-detail-open="true"/);assert.match(css,/overflow-wrap:anywhere/);
});

test('Delayed private favorite GET cannot block catalog Refresh, navigation or Chronicle pagination',async()=>{
 const e=environment({url:'https://catalog.example/guitars/1',signedIn:true}),held=deferred();e.chronicles['1']=Array.from({length:27},(_,i)=>claim(i+1));
 e.handler=call=>call.path==='/api/auth/favorites/1'?held.promise:undefined;await e.ui.start();
 assert.equal(e.ids.get('catalogRefresh').disabled,false);assert.equal(e.ids.get('chronicleMore').disabled,false);assert.equal(e.ids.get('detailContent').hidden,false);assert.equal(e.ids.get('favoriteToggle').disabled,true);
 await e.ids.get('chronicleMore').onclick();assert.equal(e.ids.get('chronicleEntries').children.length,27);await e.ui.refresh();assert.equal(e.ids.get('catalogRefresh').disabled,false);
 await e.ui.navigate('/guitars/2');await tick();assert.match(e.text('detailTitle'),/Model 2/);assert.equal(e.ids.get('favoriteToggle')['attributes']['aria-pressed'],'false');held.resolve(response({individual_id:'1',favorite:true}));await tick();assert.equal(e.ids.get('favoriteToggle')['attributes']['aria-pressed'],'false');assert.match(e.text('detailTitle'),/Model 2/);
});

test('Public favorite action preserves authorized context and exposes no public collection/count',async()=>{
 const e=environment({url:'https://catalog.example/guitars/1',signedIn:true});await e.ui.start();await tick();const writes=[];
 e.handler=call=>{if(call.options.method==='PUT'){writes.push(call);return response({individual_id:'1',favorite:true})}};
 await e.ids.get('favoriteToggle').onclick();assert.equal(writes.length,1);assert.equal(writes[0].kind,'authorized');assert.equal(writes[0].path,'/api/auth/favorites/1');assert.equal(writes[0].options.body,'{"favorite":true}');assert.equal(e.ids.get('favoriteToggle').attributes['aria-pressed'],'true');assert.equal(e.ids.get('detailFavorite').all().filter(n=>n.id==='favoritesCount'||n.id==='favoritesList').length,0);
});


test('Formal entry preserves its route namespace, bounded public DTO and existing account intents',async()=>{
  const e=environment({url:'https://catalog.example/ui?q=Fender',presentation:{basePath:'/ui',listStyle:'table'}});
  await e.ui.start();assert.equal(e.ids.get('catalogRows').children[0].tag,'tr');
  assert.ok(e.links().every(link=>link.href.startsWith('/ui/guitars/')));
  await e.click(e.links()[0]);assert.match(e.window.location.pathname,/^\/ui\/guitars\//);
  assert.match(e.ids.get('acquireLink').href,/^\/ui\/profile\?acquire=/);
  await e.window.history.back();assert.equal(e.window.location.pathname,'/ui');
  assert.ok(e.publicCalls().every(call=>call.path.startsWith('/api/public/guitars')));
});

test('Identity switch immediately clears catalog and invalidates held responses until explicit refresh',async()=>{
  const e=environment({url:'https://catalog.example/ui/guitars/1',signedIn:true,presentation:{basePath:'/ui'}});
  await e.ui.start();const hold=deferred();e.handler=call=>call.path==='/api/public/guitars'?hold.promise:undefined;
  const pending=e.ui.refresh();await tick();e.auth.account=null;e.identityChanged();
  assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
  hold.resolve(response({items:e.guitars,total:'2',page:1,page_size:24,total_pages:1}));await pending;
  assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
  e.handler=null;await e.ui.refresh();assert.equal(e.links().length,2);
});


test('Page suspension clears rendered content before BFCache restore rechecks the session',async()=>{
  const e=environment({url:'https://catalog.example/ui/guitars/1',signedIn:true,presentation:{basePath:'/ui'}});
  await e.ui.start();assert.equal(e.ids.get('detailContent').hidden,false);
  e.emit('pagehide');assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
  e.restoreError=Object.assign(Error('Revoked'),{status:401});await e.emit('pageshow',{persisted:true});
  assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
});


test('Formal self profile detail keeps intents internal without fetching an unrelated public list',async()=>{
 const e=environment({url:'https://catalog.example/ui/profile/guitars/1',signedIn:true,presentation:{basePath:'/ui/profile',accountPath:'/ui/profile',detailOnly:true}});
 await e.ui.start();assert.equal(e.ids.get('detailContent').hidden,false);
 assert.equal(e.ids.get('acquireLink').href,'/ui/profile?acquire=1');assert.equal(e.ids.get('addClaimLink').href,'/ui/profile?claim=1');assert.equal(e.ids.get('ownershipLink').href,'/ui/profile?ownership=1');
 assert.equal(e.calls.filter(c=>c.path==='/api/public/guitars').length,0);
 await e.ui.navigate('/ui/profile/guitars/2');await e.window.history.back();assert.match(e.ids.get('detailTitle').textContent,/Model 1/);
 e.auth.account=null;e.identityChanged();assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('favoriteToggle').hidden,true);
});


test('Formal compact close preserves selected record and URL; reopening and filtered search keep identity',async()=>{
  const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',accountPath:'/ui/profile',listStyle:'table'}});
  await e.ui.start();const url=e.window.location.href;
  e.ui.closeDetail();assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'false');
  assert.equal(e.window.location.href,url);assert.equal(e.ids.get('detailContent').hidden,false);
  await e.ui.navigate('/ui/guitars/1');assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'true');
  e.ids.get('catalogSearch').value='Fender';await e.ids.get('catalogSearchForm').onsubmit({preventDefault(){}});
  assert.equal(e.window.location.pathname,'/ui/guitars/1');assert.equal(e.window.location.search,'?q=Fender');
});


test('Formal catalog aggregates API pages without pager UI and rejects changed or duplicate snapshots',async()=>{
  const guitars=Array.from({length:55},(_,i)=>guitar(i+1));
  const e=environment({url:'https://catalog.example/ui?page=2',guitars,presentation:{basePath:'/ui',listStyle:'table'}});
  await e.ui.start();assert.equal(e.links().length,55);assert.equal(e.ids.get('catalogPagination').hidden,true);assert.equal(e.ids.get('catalogRefresh').hidden,false);
  assert.deepEqual(e.publicCalls().filter(c=>c.path==='/api/public/guitars').map(c=>c.params.get('page')),['1','2','3']);
  for(const fault of ['duplicate','changed','incomplete']){
    e.handler=call=>{if(call.path==='/api/public/guitars'&&call.params.get('page')==='2')return response({items:fault==='incomplete'?[]:guitars.slice(fault==='duplicate'?31:7,fault==='duplicate'?55:31),total:fault==='changed'?'56':'55',page:2,page_size:24,total_pages:3})};
    await e.ui.refresh();assert.equal(e.links().length,0,fault);assert.match(e.text('catalogStatus'),/unavailable/);assert.equal(e.ids.get('catalogRefresh').hidden,false);
  }
});

test('Identity change during a concurrent aggregate batch discards all data and stops subsequent batches',async()=>{
  const e=environment({url:'https://catalog.example/ui',guitars:Array.from({length:110},(_,i)=>guitar(i+1)),signedIn:true,presentation:{basePath:'/ui'}}),held=deferred();
  e.handler=call=>call.path==='/api/public/guitars'&&call.params.get('page')==='2'?held.promise:undefined;
  const pending=e.ui.start();await tick();e.auth.account=null;e.identityChanged();
  held.resolve(response({items:e.guitars.slice(12,36).reverse(),total:'110',page:2,page_size:24,total_pages:5}));await pending;
  assert.equal(e.links().length,0);assert.ok(!e.calls.some(call=>call.params.get('page')==='4'));
});


test('Formal Chronicle reads every cursor page before canonical occurrence ordering',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui'}});
 const values=Array.from({length:61},(_,i)=>claim(61-i,{occurred_at:'2026-01-'+String(1+i%28).padStart(2,'0')}));
 e.handler=call=>{if(call.path==='/api/public/guitars/1/chronicle'){const after=call.params.get('after'),remaining=values.filter(row=>!after||BigInt(row.id)<BigInt(after)),items=remaining.slice(0,25);return response({items,next_after:remaining.length>25?items.at(-1).id:null})}};
 await e.ui.start();assert.equal(e.ids.get('chronicleEntries').children.length,61);assert.equal(e.ids.get('chronicleMore').hidden,true);
 const cursors=e.calls.filter(call=>call.path.endsWith('/chronicle')).map(call=>call.params.get('after'));assert.deepEqual(cursors,[null,'37','12']);
});

test('Formal Chronicle rejects repeated cursor pages instead of silently showing partial history',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui'}});
 e.handler=call=>call.path.endsWith('/chronicle')?response({items:[claim(20)],next_after:'20'}):undefined;
 await e.ui.start();assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('detailStatus'),/unavailable/);assert.equal(e.ids.get('chronicleEntries').children.length,0);
});

test('approved public prose and author render as text, not markup or Evidence',async()=>{
 const e=environment({url:'https://catalog.example/guitars/1'});
 e.chronicles['1']=[claim(1,{presentation:{author:{id:'9007199254741009',display_name:'<img onerror=evil>'},body:'<script>not executable</script>',good_count:'2',bad_count:'1',evidence:'DO NOT RENDER'}})];
 await e.ui.start();const root=e.ids.get('chronicleEntries');assert.match(root.textContent,/<script>not executable<\/script>/);assert.match(root.textContent,/👍 2/);assert.ok(!root.textContent.includes('DO NOT RENDER'));
});


test('initial SDK principal restoration is not treated as a later account switch',async()=>{
  const e=environment({signedIn:true});
  e.auth.restore=async()=>{e.restores++;e.identityChanged?.();return e.auth.account};
  await e.ui.start();
  assert.equal(e.links().length,2);
  assert.ok(e.publicCalls().every(call=>call.kind==='authorized'));
  e.auth.account=null;e.identityChanged();
  assert.equal(e.links().length,0);
  assert.match(e.text('catalogStatus'),/session could not be verified/);
});


test('table hearts share one personal snapshot and discard old-account response',async()=>{
  const e=environment({signedIn:true,guitars:Array.from({length:51},(_,i)=>guitar(i+1)),url:'https://catalog.example/ui',presentation:{basePath:'/ui',listStyle:'table'}});
  const held=deferred();e.handler=call=>call.path==='/api/auth/favorites'?held.promise:undefined;
  await e.ui.start();await tick();assert.equal(e.calls.filter(c=>c.path==='/api/auth/favorites').length,1);
  assert.equal(e.calls.filter(c=>c.path.startsWith('/api/auth/favorites/')).length,0);
  e.auth.account=null;e.identityChanged();held.resolve(response({items:[],total:'0',next_after:null}));await tick();
  assert.equal(e.links().length,0);assert.equal(e.ids.get('catalog_1_favoriteToggle').hidden,true);
});


test('Search stays disabled in raw HTML and accepts a new query while the initial API read is pending',async()=>{
 const e=environment(),held=deferred();
 for(const id of ['catalogSearch','catalogSort','catalogSearchSubmit'])assert.equal(e.ids.get(id).disabled,true);
 e.handler=call=>call.path==='/api/public/guitars'&&!call.params.get('q')?held.promise:undefined;
 const ready=e.ui.start();await tick();
 for(const id of ['catalogSearch','catalogSort','catalogSearchSubmit'])assert.equal(e.ids.get(id).disabled,false);
 e.ids.get('catalogSearch').value='SERIAL-1';await e.ids.get('catalogSearchForm').onsubmit({preventDefault(){}});
 held.resolve(response({items:[guitar(2)],total:'1',page:1,page_size:24,total_pages:1}));await ready;
 assert.match(e.window.location.search,/q=SERIAL-1/);assert.equal(e.ids.get('catalogSearch').value,'SERIAL-1');assert.equal(e.links().length,1);
});

test('Formal catalog count distinguishes pending and failed reads from a measured empty result',async()=>{
 const e=environment({url:'https://catalog.example/ui',presentation:{basePath:'/ui',listStyle:'table'}}),held=deferred();
 e.handler=call=>call.path==='/api/public/guitars'?held.promise:undefined;
 const ready=e.ui.start();await tick();assert.equal(e.ids.get('listHeading').dataset.countPending,'true');
 held.resolve(response({items:[],total:'0',page:1,page_size:24,total_pages:0}));await ready;
 assert.equal(e.ids.get('listHeading').dataset.countPending,'false');
 e.handler=call=>call.path==='/api/public/guitars'?response({},503):undefined;await e.ui.refresh();
 assert.equal(e.ids.get('listHeading').dataset.countPending,'true');
});

test('Formal section-anchor history scrolls without restoring identity or rereading catalog',async()=>{
  const e=environment({url:'https://catalog.example/ui',presentation:{basePath:'/ui',listStyle:'table'}});Object.defineProperty(e.window.location,'hash',{get:()=>new URL(e.window.location.href).hash});await e.ui.start();
  const reads=e.calls.length,restores=e.restores;e.window.history.pushState(null,'','#statistics');await e.emit('popstate');
  assert.equal(e.calls.length,reads);assert.equal(e.restores,restores);e.window.history.pushState(null,'','#world-map');await e.emit('popstate');assert.equal(e.calls.length,reads);
  await e.window.history.back();assert.equal(e.calls.length,reads);assert.equal(e.restores,restores);
});

test('Selecting another guitar reuses the complete formal list but freshly reads Detail and Chronicle',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',guitars:Array.from({length:51},(_,i)=>guitar(i+1)),presentation:{basePath:'/ui',listStyle:'table'}});
 await e.ui.start();const lists=()=>e.calls.filter(c=>c.path==='/api/public/guitars');
 assert.equal(lists().length,3);assert.equal(e.links().length,51);
 await e.ui.navigate('/ui/guitars/2');
 assert.equal(lists().length,3);assert.equal(e.publicCalls().filter(c=>c.path==='/api/public/guitars/2').length,1);assert.equal(e.publicCalls().filter(c=>c.path==='/api/public/guitars/2/chronicle').length,1);
 assert.equal(e.text('detailIdentifier'),'Guitar #2');
 await e.ui.refresh();assert.equal(lists().length,6);assert.equal(e.publicCalls().filter(c=>c.path==='/api/public/guitars/2').length,2);
});

test('Sorting preserves visible rows and the same Detail while a fresh list is pending',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();
 const detailReads=e.publicCalls().filter(c=>c.path.includes('/1')).length,held=deferred();
 e.handler=c=>c.path==='/api/public/guitars'&&c.params.get('sort')==='oldest'?held.promise:undefined;
 const job=e.ui.navigate('/ui/guitars/1?sort=oldest');await tick();
 assert.equal(e.links().length,2);assert.equal(e.ids.get('detailContent').hidden,false);assert.equal(e.text('detailIdentifier'),'Guitar #1');assert.equal(e.ids.get('listHeading').dataset.countPending,'false');
 held.resolve(response({items:e.guitars,total:'2',page:1,page_size:24,total_pages:1}));await job;
 assert.equal(e.publicCalls().filter(c=>c.path.includes('/1')).length,detailReads);assert.equal(e.links()[0].href,'/ui/guitars/1?sort=oldest');
});

for(const code of [401,403,503])test('Fresh selection denial '+code+' purges the reused list and Detail',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();
 e.handler=c=>c.path==='/api/public/guitars/2'?response({detail:{code:'service_restricted'}},code):undefined;
 await e.ui.navigate('/ui/guitars/2');assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
});

for(const mode of ['offline','admin_only'])test('A new '+mode+' status cannot leave reused catalog content visible',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();e.mode=mode;
 await e.ui.navigate('/ui/guitars/1?sort=oldest');assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('catalogStatus'),/temporarily restricted/);
});

test('An embedded Profile Detail shares the exact restored canonical account, but explicit Refresh restores again',async()=>{
 const e=environment({url:'https://catalog.example/ui/profile/guitars/1',signedIn:true,presentation:{basePath:'/ui/profile',detailOnly:true,restoredAccount:()=>e.auth.account}});
 await e.ui.start();assert.equal(e.restores,0);assert.equal(e.publicCalls().length,2);assert.equal(e.ids.get('detailContent').hidden,false);
 await e.ui.refresh();assert.equal(e.restores,1);assert.equal(e.publicCalls().length,4);
});

test('An embedded Detail cannot skip restoration with a different account object',async()=>{
 const e=environment({url:'https://catalog.example/ui/profile/guitars/1',signedIn:true,presentation:{basePath:'/ui/profile',detailOnly:true,restoredAccount:()=>({user:{app_user_id:'uuid-other'}})}});
 await e.ui.start();assert.equal(e.restores,1);
});

test('Catalog Back reuses the same list and session, freshly authorizes Detail, and purges on revocation',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',signedIn:true,presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();await e.ui.navigate('/ui/guitars/2');
 const lists=e.calls.filter(c=>c.path==='/api/public/guitars').length,restores=e.restores;
 await e.window.history.back();assert.equal(e.restores,restores);assert.equal(e.calls.filter(c=>c.path==='/api/public/guitars').length,lists);assert.equal(e.text('detailIdentifier'),'Guitar #1');
 e.handler=c=>c.path==='/api/public/guitars/2'?response({detail:'revoked'},401):undefined;await e.window.history.forward();assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
});

test('All 51 table hearts become usable from one validated empty personal collection',async()=>{
 const e=environment({signedIn:true,guitars:Array.from({length:51},(_,i)=>guitar(i+1)),url:'https://catalog.example/ui',presentation:{basePath:'/ui',listStyle:'table'}});
 await e.ui.start();await tick();assert.equal(e.calls.filter(c=>c.path==='/api/auth/favorites').length,1);
 for(let i=1;i<=51;i++){const heart=e.ids.get('catalog_'+i+'_favoriteToggle');assert.equal(heart.disabled,false);assert.equal(heart.getAttribute('aria-pressed'),'false')}
 await e.ui.navigate('/ui?sort=oldest');await tick();assert.equal(e.calls.filter(c=>c.path==='/api/auth/favorites').length,1);
});


test('formal list reads remaining pages in pairs, handles out-of-order completion without partial publication',async()=>{
 const e=environment({url:'https://catalog.example/ui',guitars:Array.from({length:120},(_,i)=>guitar(i+1)),presentation:{basePath:'/ui',listStyle:'table'}}),held=new Map();
 e.handler=c=>{if(c.path==='/api/public/guitars'&&c.params.get('page')!=='1'){const d=deferred();held.set(Number(c.params.get('page')),d);return d.promise}};
 const done=e.ui.start();await tick();assert.deepEqual([...held.keys()],[2,3]);assert.equal(e.links().length,0);
 const page=n=>response({items:e.guitars.slice().reverse().slice((n-1)*24,n*24),total:'120',page:n,page_size:24,total_pages:5});
 held.get(3).resolve(page(3));await tick();assert.equal(held.size,2);assert.equal(e.links().length,0);
 held.get(2).resolve(page(2));await tick();assert.deepEqual([...held.keys()],[2,3,4,5]);assert.equal(e.links().length,0);
 held.get(5).resolve(page(5));held.get(4).resolve(page(4));await done;
 assert.deepEqual(e.links().map(n=>n.textContent),e.guitars.slice().reverse().map(n=>n.id));
});


test('canonical restore is explicitly pending on initial load and BFCache, with failed restore ending pending',async()=>{
 const states=[],e=environment({signedIn:true,presentation:{onState:s=>states.push(s)}}),held=deferred();
 e.auth.restore=async()=>{e.restores++;await held.promise;return e.auth.account};
 const initial=e.ui.start();await tick();assert.equal(states.at(-1).authPending,true);
 held.resolve();await initial;assert.equal(states.at(-1).authPending,false);assert.equal(states.at(-1).blocked,false);
 e.emit('pagehide');const second=deferred();e.auth.restore=async()=>{await second.promise;throw Object.assign(Error('revoked'),{status:401})};
 const restored=e.emit('pageshow',{persisted:true});await tick();assert.equal(states.at(-1).authPending,true);
 second.resolve();await restored;assert.equal(states.at(-1).authPending,false);assert.equal(states.at(-1).blocked,true);assert.equal(e.links().length,0);
});


test('Representative image starts before a held Chronicle and catalog; late image cannot survive navigation',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',guitars:[guitar(1,{public_photo:'/api/public/guitars/1/photo'}),guitar(2)],presentation:{basePath:'/ui',listStyle:'table'}});
 const image=e.document.createElement('img');image.id='detailPhoto';const chronicle=deferred(),photo=deferred(),list=deferred();
 e.handler=c=>c.path==='/api/public/guitars/1/chronicle'?chronicle.promise:c.path==='/api/public/guitars/1/photo'?photo.promise:c.path==='/api/public/guitars'?list.promise:undefined;
 const start=e.ui.start();await tick();assert.match(e.text('detailTitle'),/Model 1/);assert.equal(e.ids.get('detailContent').hidden,false);assert.equal(e.publicCalls().filter(c=>c.path.endsWith('/photo')).length,1);
 e.handler=null;await e.ui.navigate('/ui/guitars/2');assert.equal(e.publicCalls().find(c=>c.path.endsWith('/photo')).options.signal.aborted,true);
 photo.resolve(new Response(new Blob(['old image'],{type:'image/jpeg'}),{headers:{'Content-Type':'image/jpeg'}}));chronicle.resolve(response({items:[],next_after:null}));list.resolve(response({items:e.guitars,total:'2',page:1,page_size:24,total_pages:1}));await start;await tick();assert.match(e.text('detailTitle'),/Model 2/);assert.equal(image.src,'/assets/no-picture.svg');
});

test('After mutation refresh keeps list/detail visible without restoring auth, then reflects fresh projection',async()=>{
 const e=environment({signedIn:true,url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();const restores=e.restores,hold=deferred();e.guitars[0]=guitar(1,{manufacturer:'Changed'});e.handler=c=>c.path==='/api/public/guitars'?hold.promise:undefined;
 const pending=e.ui.refresh({preserveView:true});await tick();assert.equal(e.restores,restores);assert.equal(e.ids.get('detailContent').hidden,false);assert.equal(e.links().length,2);assert.equal(e.ids.get('listHeading').dataset.countPending,'false');
 hold.resolve(response({items:[guitar(1,{manufacturer:'Changed'})],total:'1',page:1,page_size:24,total_pages:1}));await pending;assert.match(e.text('catalogRows'),/Changed/);assert.equal(e.links().length,1);
});

for(const code of [401,403,503])test('After mutation '+code+' failure still purges retained display',async()=>{
 const e=environment({signedIn:true,url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();e.handler=c=>c.path==='/api/public/guitars/1'?response({},code):undefined;await e.ui.refresh({preserveView:true});assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);
});


test('Verification-only update with unchanged table fields keeps exact rows and does not reread list pages',async()=>{
 const e=environment({signedIn:true,url:'https://catalog.example/ui/guitars/1',presentation:{basePath:'/ui',listStyle:'table'}});e.chronicles['1']=[claim(11)];await e.ui.start();const rows=e.ids.get('catalogRows').children.slice(),reads=e.publicCalls().filter(c=>c.path==='/api/public/guitars').length,restores=e.restores;
 e.chronicles['1']=[claim(11,{verification_status:'negative'})];await e.ui.refresh({preserveView:true});assert.equal(e.publicCalls().filter(c=>c.path==='/api/public/guitars').length,reads);assert.equal(e.restores,restores);assert.equal(e.ids.get('catalogRows').children[0],rows[0]);assert.equal(e.ids.get('catalogRows').children[1],rows[1]);assert.ok(e.ids.get('chronicleEntries').all().some(node=>node.className==='claim-negative-dot'));
});

test('Mutation affecting Claim count rereads full list rather than retaining stale counts',async()=>{
 const e=environment({url:'https://catalog.example/ui/guitars/1',guitars:[guitar(1,{claim_count:'1'}),guitar(2,{claim_count:'0'})],presentation:{basePath:'/ui',listStyle:'table'}});await e.ui.start();const reads=e.publicCalls().filter(c=>c.path==='/api/public/guitars').length;e.guitars[0]=guitar(1,{claim_count:'2'});await e.ui.refresh({preserveView:true});assert.equal(e.publicCalls().filter(c=>c.path==='/api/public/guitars').length,reads+1);assert.ok(e.ids.get('catalogRows').children.some(row=>row.children.at(-1).textContent==='2'));
});


test('Top Page hydrates a discovery without changing its URL and retains it on refresh',async()=>{
 const e=environment({url:'https://catalog.example/ui',presentation:{basePath:'/ui'}});await e.ui.start();
 const lists=e.calls.filter(c=>c.path==='/api/public/guitars').length;
 await e.ui.selectInitial('2');assert.equal(e.window.location.pathname,'/ui');assert.match(e.text('detailTitle'),/Model 2/);
 assert.equal(e.calls.filter(c=>c.path==='/api/public/guitars').length,lists);
 await e.ui.refresh();assert.match(e.text('detailTitle'),/Model 2/);
 await e.ui.selectInitial('1');assert.match(e.text('detailTitle'),/Model 2/);
});

test('Explicit guitar and navigation before discoveries arrive take precedence over random default',async()=>{
 for(const direct of [true,false]){
  const e=environment({url:'https://catalog.example/ui'+(direct?'/guitars/1':''),presentation:{basePath:'/ui'}});await e.ui.start();
  if(!direct)await e.ui.select('1');await e.ui.selectInitial('2');assert.match(e.text('detailTitle'),/Model 1/);assert.equal(e.window.location.pathname,'/ui/guitars/1');
 }
});

test('Restricted Top Page never loads an initial discovery detail',async()=>{
 const e=environment({url:'https://catalog.example/ui',presentation:{basePath:'/ui'}});e.mode='offline';await e.ui.start();const before=e.calls.length;await e.ui.selectInitial('2');assert.equal(e.calls.length,before);
});
