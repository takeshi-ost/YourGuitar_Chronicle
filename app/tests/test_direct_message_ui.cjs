const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');
const html=require('./page_source.cjs')('app/src/ygc/static/user_view_html.html');
const start=html.indexOf('async function sendDirectMessage(');
const source=html.slice(start,html.indexOf('\n}',start)+2);
function scenario(fail=false){
const input={value:' Hello ',disabled:false},button={disabled:false},calls=[];
const context=vm.createContext({dmPeer:2,dmSending:false,dmHistoryLoading:false,
 document:{getElementById:id=>id==='dmBody'?input:button},dmActor:()=>1,dmStatus:text=>calls.push(['status',text]),
 jfetch:async(url,options)=>{calls.push(['send',url,JSON.parse(options.body)]);if(fail)throw Error('Offline')},
 loadDirectMessageHistory:async()=>calls.push(['history']),loadDirectMessageInbox:async()=>calls.push(['inbox'])});
vm.runInContext(source,context);
return {input,button,calls,context,run:()=>vm.runInContext('sendDirectMessage()',context)};
}
test('DM send trims text, refreshes its private conversation and clears successful draft',async()=>{
 const s=scenario();await s.run();
 assert.deepEqual(s.calls.find(x=>x[0]==='send'),['send','/api/dm/users/2/messages?viewer_id=1',{body:'Hello'}]);
 assert.equal(s.input.value,'');assert.equal(s.button.disabled,false);assert.equal(s.input.disabled,false);
 assert.ok(s.calls.some(x=>x[0]==='history'));assert.ok(s.calls.some(x=>x[0]==='inbox'));
});
test('Failed send preserves draft for retry and reenables controls',async()=>{
 const s=scenario(true);await s.run();
 assert.equal(s.input.value,' Hello ');assert.equal(s.input.disabled,false);assert.equal(s.button.disabled,false);
 assert.ok(s.calls.some(x=>x[1]==='Offline'));assert.ok(!s.calls.some(x=>x[0]==='history'));
});
test('An in flight send is not submitted twice',async()=>{
 const s=scenario();s.context.dmSending=true;await s.run();assert.equal(s.calls.length,0);
});
