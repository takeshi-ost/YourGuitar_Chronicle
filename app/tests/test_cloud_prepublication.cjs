const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const assets=path.join(__dirname,'../src/ygc/static');
const source=name=>fs.readFileSync(path.join(assets,name),'utf8');
test('Known notification templates use requested Japanese terms and preserve names and user content',()=>{
 const c=vm.createContext({});vm.runInContext(source('cloud-notification-text.js').replace('export function','function'),c);
 let row={notification_type:'claim_added',title:'New Specification Claim',body:'Alice added a Specification Claim to Fender Stratocaster.'};
 assert.deepEqual(JSON.parse(JSON.stringify(c.notificationText(row,'ja'))),{title:'新しいスペックClaim',body:'AliceがFender StratocasterにスペックClaimを追加しました。'});
 assert.equal(c.notificationText(row,'en').body,row.body);
 row={notification_type:'ownership_dispute',title:'Ownership dispute updated',body:'I wrote this English statement.'};assert.equal(c.notificationText(row,'ja').body,row.body);assert.match(c.notificationText(row,'ja').title,/異議申立て/);
 row={notification_type:'transfer_result',title:'Transfer accepted',body:'The Transfer proposal was accepted.'};assert.match(c.notificationText(row,'ja').body,/承諾/);
 row={notification_type:'claim_verified',title:'Claim Verification: Negative',body:'Bob set your Claim on Gibson to Negative.'};assert.equal(c.notificationText(row,'ja').body,'BobがGibsonのあなたのClaimを「否定」に判定しました。');
});
test('Theme presentation is applied synchronously, restricted to curated values and cleared on account switches',()=>{
 const store=new Map(),root={dataset:{theme:'sunburst_3ply'}},storage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)};
 const context=()=>vm.createContext({document:{documentElement:root},sessionStorage:storage});
 let c=context();vm.runInContext(source('cloud-theme.js'),c);c.YGCTheme.bind('owner-A');c.YGCTheme.remember('butterscotch_black');
 root.dataset.theme='sunburst_3ply';c=context();vm.runInContext(source('cloud-theme.js'),c);assert.equal(root.dataset.theme,'butterscotch_black');
 c.YGCTheme.bind('owner-A');assert.equal(root.dataset.theme,'butterscotch_black');c.YGCTheme.bind('owner-B');assert.equal(root.dataset.theme,'sunburst_3ply');
 c.YGCTheme.remember('javascript:bad');assert.equal(root.dataset.theme,'sunburst_3ply');c.YGCTheme.remember('black_pearl');c.YGCTheme.clear();assert.equal(store.size,0);assert.equal(root.dataset.theme,'sunburst_3ply');
});
