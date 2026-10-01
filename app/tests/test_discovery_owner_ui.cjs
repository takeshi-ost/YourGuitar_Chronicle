const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=require('./page_source.cjs')('app/src/ygc/static/user_view_html.html');
const context=vm.createContext({esc:s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;')});
for(const name of ['discoveryActorHtml','followingDiscoveryMessage']){
const start=html.indexOf('function '+name+'(');
vm.runInContext(html.slice(start,html.indexOf('\n}',start)+2),context);
}
const render=item=>context.discoveryActorHtml(item);
assert.equal(render({activity_type:'claim',current_owner_user_id:17}), '');
const followed=render({activity_type:'following',actor_user_id:18,actor_name:'<Actor>'});
assert.ok(followed.includes('href="/users/18"'));
assert.ok(followed.includes('event.stopPropagation()'));
assert.ok(followed.includes('&lt;Actor&gt;'));
assert.ok(followed.includes('>Following</span>'));
assert.equal(context.followingDiscoveryMessage({action_kind:'claim',claim_type:'ownership',ownership_kind:'acquire'}),'added an Acquire Claim to');
assert.equal(context.followingDiscoveryMessage({action_kind:'vote',action_value:'good'}),'gave a good vote to a Claim on');
console.log('New Discovery followed actor links and action wording: passed');
