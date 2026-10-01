const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');
const html=require('./page_source.cjs')('app/src/ygc/static/user_view_html.html');
const start=html.indexOf('async function toggleUserFollow(');
const source=html.slice(start,html.indexOf('\n}',start)+2);
function scenario(fail=false){
  const button={disabled:false},status={textContent:''},calls=[];
  const context=vm.createContext({activeUser:{user:{id:2}},PROFILE_USER_ID:1,selectedIndividualId:17,
    document:{getElementById:id=>id==='followUserButton'?button:status},
    jfetch:async(url,options)=>{calls.push([url,options.method]);if(fail)throw Error('Network failure')},
    loadProfilePage:async id=>calls.push(['profile',id])});
  vm.runInContext(source,context);
  return {calls,button,status,run:flag=>vm.runInContext('toggleUserFollow('+flag+')',context)};
}
test('Follow and unfollow use the acting user and retain selected Product Detail',async()=>{
  for(const [following,method] of [[false,'PUT'],[true,'DELETE']]){
    const s=scenario();await s.run(following);
    assert.deepEqual(s.calls,[['/api/users/2/following/1?viewer_id=2',method],['profile',17]]);
  }
});
test('Failed Follow reports the error and permits retry without refreshing',async()=>{
  const s=scenario(true);await s.run(false);
  assert.equal(s.button.disabled,false);
  assert.equal(s.status.textContent,'Network failure');
  assert.equal(s.calls.length,1);
});
