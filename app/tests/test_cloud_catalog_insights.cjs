const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const staticPath=path.join(__dirname,'../src/ygc/static');
const source=fs.readFileSync(path.join(staticPath,'cloud-catalog-insights.js'),'utf8');
const countries=[{name:'Japan',code:'JP',aliases:['Japan','JP','JPN'],path:'M0,0 L1,1 Z'},{name:'United States of America',code:'US',aliases:['United States of America','USA','United States','US'],path:'M1,1 L2,2 Z'}];
const news=(id='52',extra={})=>({id,manufacturer:'Squier',model:'Telecaster',finish:null,year:'1960',serial_number:'123',activity_type:'claim',claim_type:'listing',activity_at:'2026-10-12T00:00:00Z',...extra});
const stats=()=>({individuals:'2',models:[{label:'Telecaster',count:'2'}],years:[{label:'1960',count:'2'}],listings_30d:Array.from({length:30},(_,i)=>({date:new Date(Date.UTC(2026,8,13+i)).toISOString().slice(0,10),count:i===29?'2':'0'}))});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
function environment(){
  const ids=new Map();
  class Element{
    constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.hidden=false;this._text='';}
    set textContent(value){this._text=String(value);this.children=[]}get textContent(){return this._text+this.children.map(n=>n.textContent).join('')}
    set innerHTML(_){throw Error('Untrusted data must never enter HTML')}
    append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this._text='';this.children=nodes}
    setAttribute(key,value){this.attributes[key]=String(value)}
    all(){return this.children.flatMap(node=>[node,...node.all()])}
  }
  for(const match of fs.readFileSync(path.join(staticPath,'cloud_ui_html.html'),'utf8').matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g))ids.set(match[2],new Element(match[1]));
  const document={getElementById:id=>ids.get(id),createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
  const context=vm.createContext({document,worldCountries:countries,Intl,Date,Map,Set,BigInt,AbortController,console});
  vm.runInContext(source.replace(/^import .*;\n/gm,'').replaceAll('export function','function'),context);
  const e={context,ids,calls:[],selected:[],response:{discovery:{items:[news()]},statistics:stats(),map:{countries:[{country:'JP',count:'2'}]}},handler:null,state:{locale:'en',readRevision:1,loading:false,blocked:false,serviceMode:'normal',auth:null}};
  e.component=context.createCatalogInsights({document,countries,read:async(url,signal)=>{e.calls.push({url,signal});if(e.handler)return e.handler(url,signal);return e.response[url.endsWith('discoveries')?'discovery':url.endsWith('statistics')?'statistics':'map']},onSelect:id=>e.selected.push(id),onRefresh:async()=>{e.state.readRevision++;await e.component.sync(e.state)}});
  e.sync=()=>e.component.sync(e.state);e.text=id=>ids.get(id).textContent;return e;
}

test('New Discovery connects safe links and textual data, with exact BIGINT identity',async()=>{
  const e=environment(),id='9007199254740993';e.response.discovery.items=[news(id,{model:'<img src=x onerror=alert(1)>'})];await e.sync();
  const row=e.ids.get('newDiscoveryList').children[0];assert.equal(row.href,'/ui/guitars/'+id);assert.match(row.textContent,/<img src=x/);
  let prevented=false;row.onclick({button:0,preventDefault(){prevented=true}});assert.equal(prevented,true);assert.deepEqual(e.selected,[id]);
  row.onclick({button:0,ctrlKey:true,preventDefault(){throw Error('Modified link should navigate normally')}});assert.deepEqual(e.selected,[id]);
  assert.equal(e.calls.length,3);assert.ok(e.calls.every(call=>call.url.startsWith('/api/public/guitars/')));
  assert.ok(e.ids.get('modelChart').all().some(n=>n.tag==='circle'));assert.ok(e.ids.get('yearChart').all().some(n=>n.tag==='rect'));assert.ok(e.ids.get('listingChart').all().some(n=>n.tag==='polyline'));
});

test('Unfiltered panels remain unchanged during guitar selection/search and same-state renders',async()=>{
  const e=environment();await e.sync();const paths=e.ids.get('worldMapSvg').children;
  e.state.selectedId='12';e.state.loading=true;await e.sync();e.state.loading=false;await e.sync();
  assert.equal(e.calls.length,3);assert.equal(e.ids.get('worldMapSvg').children,paths);
});

test('Identity rejection erases every panel, never retries anonymously, and Refresh recovers',async()=>{
  const e=environment();await e.sync();e.handler=url=>{if(url.endsWith('statistics'))throw Object.assign(Error('PRIVATE'),{status:401});return e.response[url.endsWith('discoveries')?'discovery':'map']};e.state.readRevision++;await e.sync();
  assert.equal(e.ids.get('newDiscoveryList').children.length,0);assert.equal(e.ids.get('modelChart').children.length,0);assert.equal(e.ids.get('worldMapSvg').children.length,0);
  assert.match(e.text('mapStatus'),/session/);assert.equal(e.calls.length,6);
  e.handler=null;await e.ids.get('insightsRefresh').onclick();assert.equal(e.ids.get('newDiscoveryList').children.length,1);assert.equal(e.calls.length,9);
});

for(const state of [{blocked:true},{serviceMode:'offline'},{serviceMode:'admin_only'}])test('Service/session restriction clears charts before new reads: '+JSON.stringify(state),async()=>{
  const e=environment();await e.sync();Object.assign(e.state,state);await e.sync();
  assert.equal(e.calls.length,3);assert.equal(e.ids.get('newDiscoveryList').children.length,0);assert.equal(e.ids.get('worldMapSvg').children.length,0);assert.equal(e.ids.get('mapCounts').children.length,0);
});

test('Slow responses from old identity or suspended page cannot repopulate data',async()=>{
  const e=environment(),hold=deferred();e.handler=()=>hold.promise;const pending=e.sync();await new Promise(resolve=>setImmediate(resolve));
  e.component.clear({pause:true});assert.ok(e.calls.every(call=>call.signal.aborted));hold.resolve({items:[news()]});await pending;
  assert.equal(e.ids.get('newDiscoveryList').children.length,0);assert.equal(e.ids.get('worldMapSvg').children.length,0);
  e.handler=null;e.component.resume();e.state.readRevision++;await e.sync();assert.equal(e.ids.get('newDiscoveryList').children.length,1);
});

test('One network/data error keeps other valid public sections and offers retry',async()=>{
  const e=environment();e.response.statistics={...stats(),listings_30d:[]};await e.sync();
  assert.match(e.text('statisticsStatus'),/Could not load/);assert.equal(e.ids.get('newDiscoveryList').children.length,1);assert.ok(e.ids.get('worldMapSvg').children.length>0);
  e.response.statistics=stats();await e.ids.get('insightsRefresh').onclick();assert.equal(e.text('statisticsStatus'),'');assert.ok(e.ids.get('modelChart').children.length>0);
});

test('Empty data is honest and language changes do not make another request',async()=>{
  const e=environment();e.response.discovery={items:[]};e.response.statistics={...stats(),individuals:'0',models:[],years:[]};e.response.map={countries:[]};await e.sync();
  assert.match(e.text('newDiscoveryList'),/No recent/);assert.match(e.text('modelChart'),/No model/);assert.match(e.text('yearChart'),/No single-year/);assert.match(e.text('mapSelection'),/No public country/);
  e.state.locale='ja';await e.sync();assert.equal(e.calls.length,3);assert.equal(e.text('discoveryHeading'),'新着情報');assert.match(e.text('newDiscoveryList'),/新着情報/);
});

test('Country aliases combine counts and unknown small countries stay in accessible table',async()=>{
  const e=environment();e.response.map={countries:[{country:'JP',count:'2'},{country:'Japan',count:'3'},{country:'Small Island',count:'7'}]};await e.sync();
  const paths=e.ids.get('worldMapSvg').children.filter(n=>n.tag==='path');assert.equal(paths[0].attributes.tabindex,'0');paths[0].onfocus();assert.match(e.text('mapSelection'),/Japan — 5 guitars/);
  assert.match(e.text('mapCounts'),/Small Island7/);assert.match(e.text('mapCounts'),/Japan/);
  const index=e.context.countryIndex();for(const input of ['JPN','JP','日本'])assert.equal(index.get(input.toLowerCase()).name,'Japan');assert.equal(index.get('uk').code,'GB');assert.equal(index.get('singapore').code,'SG');assert.match(e.text('mapCounts'),/Japan5/);
});

test('No country rows/charts appear when a late restriction arrives while loading',async()=>{
  const e=environment(),hold=deferred();e.handler=()=>hold.promise;const pending=e.sync();await new Promise(resolve=>setImmediate(resolve));
  e.state.serviceMode='offline';await e.sync();hold.resolve({items:[news()]});await pending;assert.equal(e.ids.get('newDiscoveryList').children.length,0);assert.match(e.text('discoveryStatus'),/restricted/);
});

test('Discovery validator rejects duplicate IDs, unknown activity, malformed dates and unsafe IDs',()=>{
  const e=environment(),validate=e.context.validateDiscoveries;
  for(const items of [[news(),news()],[news('0')],[news('9223372036854775808')],[news('1',{activity_type:'following'})],[news('1',{activity_at:'bad'})],[news('1',{claim_type:'private'})],Array.from({length:201},(_,i)=>news(String(i+1)))])assert.throws(()=>validate({items}));
});

test('Statistics reject malformed counts, incomplete totals, unordered years and missing dates',()=>{
  const e=environment(),validate=e.context.validateStatistics;
  for(const data of [{...stats(),individuals:'3'},{...stats(),models:[{label:'x',count:'01'}]},{...stats(),years:[{label:'1960-1962',count:'2'}]},{...stats(),years:[{label:'1961',count:'1'},{label:'1960',count:'1'}]},{...stats(),listings_30d:stats().listings_30d.slice(1)}])assert.throws(()=>validate(data));
});

test('Map validator rejects duplicate/zero/unbounded counts and markup stays text',()=>{
  const e=environment(),validate=e.context.validateMap;
  for(const rows of [[{country:'JP',count:'0'}],[{country:'JP',count:'-1'}],[{country:'JP',count:'9223372036854775808'}],[{country:'JP',count:'1'},{country:'JP',count:'1'}]])assert.throws(()=>validate({countries:rows}));
  assert.equal(validate({countries:[{country:'<svg onload=alert(1)>',count:'1'}]}).countries[0].country,'<svg onload=alert(1)>');
});


test('Admin Only permits canonical administrator insights after restoration',async()=>{
 const e=environment();e.state.serviceMode='admin_only';e.state.auth={account:{user:{app_user_id:'admin-fixture',role:'admin'}}};await e.sync();
 assert.equal(e.calls.length,3);assert.ok(e.ids.get('modelChart').children.length);
 e.state.loading=true;e.state.readRevision++;await e.sync();e.state.auth.account=null;await e.sync();
 e.state.auth.account={user:{app_user_id:'admin-fixture',role:'admin'}};e.state.loading=false;await e.sync();
 assert.equal(e.calls.length,6);assert.ok(e.ids.get('modelChart').children.length);
});

test('Chart end labels keep a full tick interval and all counts remain in tables',async()=>{
 const e=environment();e.response.statistics.years=Array.from({length:17},(_,i)=>({label:String(1962+i),count:'1'}));e.response.statistics.individuals='17';e.response.statistics.models=[{label:'A',count:'17'}];await e.sync();
 const text=e.ids.get('yearChart').children[0].all().filter(n=>n.tag==='text').map(n=>n.textContent);
 assert.ok(text.includes('1978'));assert.ok(!text.includes('1977'));assert.match(e.text('yearChart'),/1977/);
});

test('Service invalidation clears insights with restriction text, without asking for sign-in',async()=>{
 const e=environment();await e.sync();e.state.blocked=true;e.state.blockCode='service_restricted';e.state.serviceMode='offline';await e.sync();assert.match(e.text('discoveryStatus'),/restricted/);assert.doesNotMatch(e.text('discoveryStatus'),/session|sign in/i);assert.equal(e.ids.get('newDiscoveryList').children.length,0);
});


test('Initial random detail draws only from displayed discoveries, including a single item or empty data',async()=>{
 const e=environment();assert.equal(e.component.pickDiscovery(),null);
 e.response.discovery.items=[news('2'),news('52'),news('9007199254740993')];await e.sync();
 assert.equal(e.component.pickDiscovery(()=>0),'2');assert.equal(e.component.pickDiscovery(()=>.5),'52');assert.equal(e.component.pickDiscovery(()=>.999),'9007199254740993');
 e.component.clear();assert.equal(e.component.pickDiscovery(),null);
 e.response.discovery.items=[news('52')];await e.sync();assert.equal(e.component.pickDiscovery(()=>.999),'52');
 e.response.discovery.items=[];e.state.readRevision++;await e.sync();assert.equal(e.component.pickDiscovery(),null);
});
