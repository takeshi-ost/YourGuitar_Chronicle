const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const assets=path.join(__dirname,'../src/ygc/static');
const source=fs.readFileSync(path.join(assets,'cloud-public-catalog.js'),'utf8');
const html=fs.readFileSync(path.join(assets,'cloud_public_catalog_html.html'),'utf8');
const guitar=(id,extra={})=>({id:String(id),manufacturer:'Fender',model:'Model '+id,finish:'Sunburst',year:'1960',serial_number:'SERIAL-'+id,photo:null,...extra});
const claim=(id,extra={})=>({id:String(id),claim_type:'listing',ownership_kind:null,occurred_at:'2026-01-01',created_at:'2026-01-01T12:00:00Z',verification_status:'positive',items:[],source_url:null,...extra});
const response=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body});
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return {promise,resolve}};
const tick=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve))};

function environment({url='https://catalog.example/',guitars=[guitar(1),guitar(2)],signedIn=false,loadError=null,restoreError=null,locale='en'}={}){
  const ids=new Map();
  class Element{
    constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.value='';this.hidden=false;this.disabled=false;this.open=false;this._text='';}
    set id(value){this._id=value;ids.set(value,this)}get id(){return this._id}
    set textContent(value){this._text=String(value);this.children=[]}get textContent(){return this._text+this.children.map(child=>child.textContent).join('')}
    set innerHTML(_){throw Error('Public data must never be inserted as HTML.')}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this._text='';this.children=nodes}
    setAttribute(key,value){this.attributes[key]=String(value)}getAttribute(key){return this.attributes[key]??null}
    focus(){document.activeElement=this}
    all(){return this.children.flatMap(child=>[child,...child.all()])}
  }
  const nav=new Element('nav'),document={documentElement:new Element('html'),body:new Element('body'),createElement:tag=>new Element(tag),getElementById:id=>ids.get(id),querySelector:selector=>selector==='.page-nav'?nav:null};
  for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const element=new Element(match[1]);element.id=match[2];element.hidden=/\bhidden\b/.test(match[0])}
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
    const match=/^\/api\/public\/guitars\/([1-9][0-9]*)(\/chronicle)?$/.exec(call.path);
    if(match){
      const row=e.guitars.find(row=>row.id===match[1]);if(!row)return response({detail:'Missing'},404);
      if(!match[2])return response({...row,specifications:e.specifications[row.id]||[]});
      const after=call.params.get('after'),values=(e.chronicles[row.id]||[]).filter(item=>!after||BigInt(item.id)<BigInt(after)).slice().sort((a,b)=>BigInt(a.id)>BigInt(b.id)?-1:1),items=values.slice(0,25);
      return response({items,next_after:values.length>25?items.at(-1).id:null});
    }
    throw Error('Unexpected request '+call.url);
  }
  e.auth={signedIn,restore:async()=>{e.restores++;if(e.restoreError)throw e.restoreError;return e.auth.signedIn?{user:{role:'user'}}:null},authorizedFetch:(url,options)=>dispatch('authorized',url,options)};
  const context=vm.createContext({document,window,URL,URLSearchParams,AbortController,loadCloudAuth:async()=>{},console});
  vm.runInContext(source.replace(/^import .*;\n/gm,'').replace('export function','function').split('// Readiness is')[0]+';globalThis.createCatalog=createPublicCatalog;',context);
  e.ui=context.createCatalog({document,window,request:(url,options)=>dispatch('anonymous',url,options),loadAuth:async()=>{e.loads++;if(e.loadError)throw e.loadError;return e.auth}});
  e.publicCalls=()=>e.calls.filter(call=>call.path.startsWith('/api/public/'));
  e.links=()=>ids.get('catalogRows').all().filter(node=>node.tag==='a');
  e.click=(node,extra={})=>node.onclick({button:0,preventDefault(){},...extra});
  e.text=id=>ids.get(id).textContent;
  return e;
}

test('Anonymous catalog restores optional auth, renders a bounded list, and only issues safe GET reads',async()=>{
  const e=environment();await e.ui.start();
  assert.equal(e.loads,1);assert.equal(e.restores,1);assert.equal(e.links().length,2);assert.equal(e.text('catalogStatus'),'2 guitars');
  assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('catalogLayout').dataset.detailOpen,'false');
  assert.equal(e.publicCalls().length,1);assert.equal(e.publicCalls()[0].kind,'anonymous');assert.equal(e.publicCalls()[0].params.get('limit'),'24');
  for(const call of e.calls){assert.equal(call.options.method,'GET');assert.equal(call.options.cache,'no-store');assert.equal(call.options.credentials,'omit');assert.equal(call.options.redirect,'error')}
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
  assert.equal(e.ids.get('acquireLink').href,'/account?acquire='+id);assert.equal(e.ids.get('acquireLink').onclick,undefined);assert.equal(e.ids.get('addClaimLink').href,'/account?claim='+id);assert.equal(e.ids.get('addClaimLink').onclick,undefined);
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
  const all=e.ids.get('chronicleEntries').all(),links=all.filter(node=>node.tag==='a');assert.equal(links.length,1);assert.equal(links[0].href,'https://reverb.com/item/12');assert.equal(links[0].rel,'noopener noreferrer');assert.equal(links[0].target,'_blank');assert.ok(!all.some(node=>node.tag==='img'));
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
  const obsolete=e.ui.navigate('/guitars/2');await tick();assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.text('detailTitle'),'');assert.equal(e.ids.get('acquireLink').href,'/account');assert.equal(e.ids.get('addClaimLink').href,'/account');
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
  const first=e.ui.refresh(),second=e.ui.refresh();assert.equal(first,second);await tick();assert.equal(e.calls.length-before,4);assert.equal(e.ids.get('detailContent').hidden,true);
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
  await e.ids.get('chronicleMore').onclick();assert.equal(e.ids.get('detailContent').hidden,true);assert.equal(e.ids.get('acquireLink').href,'/account');assert.equal(e.ids.get('addClaimLink').href,'/account');assert.equal(e.links().length,0);assert.match(e.text('detailStatus'),/temporarily restricted/);
});

test('Offline/admin-only restriction is enforced by API responses, while canonical signed-in admin access remains possible',async()=>{
  for(const mode of ['offline','admin_only']){
    const e=environment({url:'https://catalog.example/guitars/1'});await e.ui.start();e.mode=mode;e.message='<img src=x> Maintenance';
    e.handler=call=>call.path.startsWith('/api/public/')?response({detail:{code:'service_restricted'}},403):undefined;
    await e.ui.refresh();assert.equal(e.links().length,0);assert.equal(e.ids.get('detailContent').hidden,true);assert.match(e.text('catalogStatus'),/temporarily restricted/);assert.ok(e.text('serviceNotice').includes('<img src=x> Maintenance'));assert.equal(e.ids.get('serviceNotice').children.length,0);
  }
  const admin=environment({signedIn:true});admin.mode='admin_only';await admin.ui.start();assert.equal(admin.links().length,2);assert.match(admin.text('serviceNotice'),/administrators/);assert.ok(admin.publicCalls().every(call=>call.kind==='authorized'));
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
  assert.doesNotMatch(source,/innerHTML|insertAdjacentHTML|localId|POST|PATCH|DELETE/);
  const context=vm.createContext({URL});vm.runInContext(source.slice(source.indexOf('const messages='),source.indexOf('const sorts='))+';globalThis.keys=[Object.keys(messages.en),Object.keys(messages.ja)];',context);
  assert.deepEqual(Array.from(context.keys[0]).sort(),Array.from(context.keys[1]).sort());
  const css=fs.readFileSync(path.join(assets,'cloud-public-catalog.css'),'utf8');assert.match(css,/@media\(max-width:900px\)/);assert.match(css,/data-detail-open="true"/);assert.match(css,/overflow-wrap:anywhere/);
});
