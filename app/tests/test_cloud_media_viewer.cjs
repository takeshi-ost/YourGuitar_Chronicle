const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done});return {promise,resolve}};
const row=(extra={})=>({id:'23',revision:'a'.repeat(64),media_items:[{id:'31',mime_type:'image/jpeg'}],...extra});
function environment(){
 const created=[],revoked=[],calls=[],replies=[],decodes=[],errors=[],states=[],images=[];let current=true,width=640,height=480;
 class MediaURL extends URL{static createObjectURL(blob){const url='blob:private-'+(created.length+1);created.push(url);return url}static revokeObjectURL(url){revoked.push(url)}}
 class Element{constructor(tag){this.tag=tag;this.children=[];this.naturalWidth=width;this.naturalHeight=height}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes}removeAttribute(key){delete this[key]}async decode(){const result=await decodes.shift();if(result instanceof Error)throw result}}
 const document={createElement(tag){const el=new Element(tag);if(tag==='img')images.push(el);return el}},container=new Element('div');
 const context=vm.createContext({AbortController,document,URL:MediaURL,YGCI18n:{t:(key,params={})=>key+JSON.stringify(params)}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ygc/static/cloud-account-media.js'),'utf8').replaceAll('export function','function'),context);
 const auth=()=>({async authorizedFetch(url,options,verified){calls.push({url,options,verified});const response=await (replies.length?replies.shift():{blob:new Blob(['PRIVATE PIXELS'],{type:'image/jpeg'})});if(response instanceof Error)throw response;return {ok:!response.status,status:response.status,blob:async()=>response.blob}}});
 const viewer=context.createPrivateMedia({auth,container,isCurrent:()=>current,onState:value=>states.push(value),onError:error=>errors.push(error)});
 return {viewer,context,container,created,revoked,calls,replies,decodes,errors,states,images,setCurrent:v=>{current=v},dimensions:(w,h)=>{width=w;height=h},async flush(){for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve))}};
}

test('Private image viewer uses exact revision-bound authenticated GET and keeps paths out of markup',async()=>{
 const e=environment();await e.viewer.load('9007199254740993',row());assert.equal(e.calls.length,1);assert.equal(e.calls[0].options.signal.aborted,false);assert.deepEqual(JSON.parse(JSON.stringify({...e.calls[0],options:{...e.calls[0].options,signal:undefined}})),{url:'/api/auth/guitars/9007199254740993/claims/23/media/31?revision='+'a'.repeat(64),options:{cache:'no-store',credentials:'omit',redirect:'error'},verified:true});assert.equal(e.container.children.length,1);assert.match(e.images[0].src,/^blob:/);assert.equal(e.states.at(-1),true);e.viewer.clear();assert.equal(e.images[0].src,undefined);assert.deepEqual(e.revoked,e.created);
});

for(const extra of [{id:'../other'},{revision:'bad'},{media_items:[]},{media_items:[{id:'31',mime_type:'image/png'}]},{media_items:[{id:'31/../../secret',mime_type:'image/jpeg'}]},{media_items:[{id:'9223372036854775808',mime_type:'image/jpeg'}]},{media_items:[{id:'31',mime_type:'image/jpeg'},{id:'31',mime_type:'image/jpeg'}]}])test('Malformed photo metadata is rejected before any fetch',async()=>{
 const e=environment();await e.viewer.load('12',row(extra));assert.equal(e.calls.length,0);assert.equal(e.errors.length,1);assert.equal(e.states.at(-1),false);
});

test('Review readiness waits for every image to decode and a stale decode never reattaches content',async()=>{
 const e=environment(),held=deferred();e.decodes.push(held.promise);const pending=e.viewer.load('12',row());await e.flush();assert.equal(e.states.at(-1),false);assert.equal(e.created.length,1);assert.equal(e.container.children.length,0);e.viewer.clear();held.resolve();await pending;assert.equal(e.states.at(-1),false);assert.equal(e.container.children.length,0);assert.deepEqual(e.revoked,e.created);assert.equal(e.images[0].src,undefined);
});

test('Late photo response after clear is discarded without creating a blob URL',async()=>{
 const e=environment(),held=deferred();e.replies.push(held.promise);const pending=e.viewer.load('12',row());e.viewer.clear();held.resolve({blob:new Blob(['private'],{type:'image/jpeg'})});await pending;assert.equal(e.created.length,0);assert.equal(e.container.children.length,0);
});

test('Newer photo selection cannot be removed by an old decode error',async()=>{
 const e=environment(),held=deferred();e.decodes.push(held.promise);const pending=e.viewer.load('12',row());await e.flush();await e.viewer.load('12',row({revision:'b'.repeat(64)}));held.resolve(Error('old revoked decode'));await pending;assert.equal(e.errors.length,0);assert.equal(e.container.children.length,1);assert.equal(e.states.at(-1),true);assert.equal(e.revoked.length,1);assert.equal(e.images[1].src,e.created[1]);
});

for(const problem of ['html','empty','too large','pixels','decode'])test(`Unusable private image (${problem}) never enables review and revokes partial photos`,async()=>{
 const e=environment();if(problem==='html')e.replies.push({blob:new Blob(['SECRET HTML'],{type:'text/html'})});if(problem==='empty')e.replies.push({blob:new Blob([],{type:'image/jpeg'})});if(problem==='too large')e.replies.push({blob:{type:'image/jpeg',size:8*1024*1024+1}});if(problem==='pixels')e.dimensions(4000,2001);if(problem==='decode')e.decodes.push(Error('invalid JPEG'));
 await e.viewer.load('12',row());assert.equal(e.errors.length,1);assert.equal(e.states.at(-1),false);assert.equal(e.container.children.length,0);assert.deepEqual(e.revoked,e.created);
});

for(const status of [400,401,403,404,409,500])test(`Photo failure ${status} revokes an earlier successful photo in the same Claim`,async()=>{
 const e=environment();e.replies.push({blob:new Blob(['private'],{type:'image/jpeg'})},{status});await e.viewer.load('12',row({media_items:[{id:'31',mime_type:'image/jpeg'},{id:'32',mime_type:'image/jpeg'}]}));assert.equal(e.created.length,1);assert.deepEqual(e.revoked,e.created);assert.equal(e.container.children.length,0);assert.equal(e.errors[0].status,status);assert.equal(e.states.at(-1),false);
});

test('Local preview enforces dimensions and boundaries without any external request',async()=>{
 const e=environment();e.dimensions(4000,2000);await e.viewer.preview([new File(['local'], 'photo.png',{type:'image/png'})]);assert.equal(e.states.at(-1),true);assert.equal(e.calls.length,0);e.dimensions(4000,2001);await e.viewer.preview([new File(['local'], 'photo.png',{type:'image/png'})]);assert.equal(e.states.at(-1),false);assert.equal(e.errors.at(-1).status,400);assert.deepEqual(e.revoked,e.created);
});

test('Only explicitly text-only Event projections may validate an empty attachment list',()=>{
 const e=environment(),validate=e.context.validateMediaItems;assert.throws(()=>validate([]));const empty=validate([],{allowEmpty:true});assert.equal(empty.length,0);assert.equal(Object.isFrozen(empty),true);for(const invalid of [undefined,null,{},[{id:'31',mime_type:'image/png'}]])assert.throws(()=>validate(invalid,{allowEmpty:true}));
});
