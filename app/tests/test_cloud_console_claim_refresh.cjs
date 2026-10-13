const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/src/ygc/static/cloud-console-guitars.js','utf8').replace(/^import .*;\n/gm,'').replace(/^import .*;\n/gm,'').replace('export function','function');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r))};
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve}};
function environment(){
 const ids=new Map(),calls=[],media={clears:0,reads:0},errors=[];let row={id:'1',manufacturer:'Squier',model:'Telecaster',year:null,serial_number:'serial',current_owner_name:'Owner'},stance='positive',detailHold=null,deny=false;
 class Element{constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;this.disabled=false;}set id(v){this._id=v;ids.set(v,this)}get id(){return this._id}append(...items){this.children.push(...items)}replaceChildren(...items){this.children=items;this.textContent=''}setAttribute(){}addEventListener(){}scrollIntoView(){}}
 const el=id=>{if(!ids.has(id)){const item=new Element();item.id=id}return ids.get(id)};
 const document={getElementById:el,createElement:tag=>new Element(tag),querySelectorAll:()=>[],body:new Element()};
 const request=async(path,options={})=>{calls.push({path,options});if(options.method==='POST'){stance=JSON.parse(options.body).action;return {saved:true}}if(path==='/api/admin/guitars/1'){if(detailHold)await detailHold;if(deny)throw Object.assign(Error('Denied'),{status:401});return {...row}}if(path.includes('/chronicle'))return {items:[{id:'12',claim_type:'specification',verification_status:stance,effective_status:'active',revision:'a'.repeat(64),items:[]}],total:'1',next_after:null};if(path.startsWith('/api/admin/guitars?'))return {items:[{...row}],total:'1',next_after:null};throw Error(path)};
 const context=vm.createContext({document,URLSearchParams,YGCI18n:{t:k=>k},YGCOverlays:{open(){},close(){}},createMediaBrowser:()=>({clear(){media.clears++},render(){},async refresh(){media.reads++}})});require('./console_list_stub.cjs').install(context);
vm.runInContext(source+';this.create=createGuitarBrowser;',context);
 const ui=context.create({request,authorized:()=>true,onUnauthorized:e=>errors.push(e)});
 return {ui,ids,el,calls,media,errors,row,hold:v=>detailHold=v,deny:()=>deny=true,change:()=>row.manufacturer='Changed',decide(){const card=el('chronicleRows').children[0];card.children.at(-1).onclick();el('claimDecisionValue').value='negative';el('claimDecisionConfirm').onclick()}};
}
test('Console verification-only update retains list/detail while waiting and skips unrelated list/media reads',async()=>{
 const e=environment();await e.ui.refresh();await e.ui.detail('1');const rows=e.el('guitarRows').children.slice(),fields=e.el('guitarDetailFields').children.slice(),claims=e.el('chronicleRows').children.slice(),reads=e.calls.filter(c=>c.path.startsWith('/api/admin/guitars?')).length,media=e.media.reads,hold=deferred();e.hold(hold.promise);e.decide();await tick();assert.equal(e.el('guitarRows').children[0],rows[0]);assert.equal(e.el('guitarDetailFields').children[0],fields[0]);assert.equal(e.el('chronicleRows').children[0],claims[0]);hold.resolve();await tick();assert.equal(e.el('guitarRows').children[0],rows[0]);assert.equal(e.calls.filter(c=>c.path.startsWith('/api/admin/guitars?')).length,reads);assert.equal(e.media.reads,media);assert.match(e.el('chronicleRows').children[0].className,/negative/);
});
test('Snapshot changes still refresh Console filter/list projection after verification',async()=>{
 const e=environment();await e.ui.refresh();await e.ui.detail('1');const reads=e.calls.filter(c=>c.path.startsWith('/api/admin/guitars?')).length;e.change();e.decide();await tick();assert.equal(e.calls.filter(c=>c.path.startsWith('/api/admin/guitars?')).length,reads+1);assert.equal(e.el('guitarRows').children[0].children[2].textContent,'Changed');
});
test('Authorization denial purges retained Console display after a successful write',async()=>{
 const e=environment();await e.ui.refresh();await e.ui.detail('1');e.deny();e.decide();await tick();assert.equal(e.el('guitarRows').children.length,0);assert.equal(e.el('guitarDetailFields').children.length,0);assert.equal(e.el('chronicleRows').children.length,0);assert.equal(e.errors.length,1);
});
