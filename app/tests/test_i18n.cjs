const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const english=JSON.parse(fs.readFileSync('app/src/ygc/static/locales/en.json','utf8'));
const japanese=JSON.parse(fs.readFileSync('app/src/ygc/static/locales/ja.json','utf8'));
const source=fs.readFileSync('app/src/ygc/static/i18n.js','utf8');
function load(saved='en',storageWorks=true){
 const preferences={ygc_ui_language:saved};let reloads=0;
 const context={Intl,RangeError,Error,document:{documentElement:{},readyState:'loading',addEventListener(){}},
  localStorage:{getItem:k=>{if(!storageWorks)throw Error('blocked');return preferences[k]},setItem:(k,v)=>{if(!storageWorks)throw Error('blocked');preferences[k]=v}},
  location:{reload:()=>reloads++},
  YGCI18nResources:{manifest:{defaultLocale:'en',languages:[{code:'en',label:'English',dir:'ltr'},{code:'ja',label:'日本語',dir:'ltr'},{code:'ar',label:'Arabic',dir:'rtl'}]},
   catalogs:{en:{...english,'test.greeting':'Hello, {name}','test.count':{one:'{count} guitar',other:'{count} guitars'}},ja:japanese,ar:{'header.notifications':'تنبيهات','test.greeting':'{name}, مرحبا','test.count':{one:'واحد',other:'{count} متعدد'},'test.unsafe':'<img src=x onerror=alert(1)> {name}'}}}};
 vm.runInNewContext(source,context);return {api:context.YGCI18n,context,preferences,reloads:()=>reloads};
}
test('English remains the default and unsupported saved languages fall back',()=>{
 const {api,context}=load('zz');assert.equal(api.locale,'en');assert.equal(api.t('header.notifications'),'Notifications');assert.equal(context.document.documentElement.lang,'en');assert.equal(context.document.documentElement.dir,'ltr');
 assert.equal(api.t('missing',{},'Original'),'Original');assert.equal(load('ar',false).api.locale,'en');
});
test('Additional dictionaries use English fallback, parameters, plural rules and RTL',()=>{
 const {api,context}=load('ar');assert.equal(api.t('header.notifications'),'تنبيهات');assert.equal(api.t('account.create'),'Create Account');assert.equal(api.t('test.greeting',{name:'Alice'}),'Alice, مرحبا');assert.equal(api.t('test.count',{count:1}),'واحد');assert.equal(api.t('test.count',{count:2}),'2 متعدد');assert.equal(context.document.documentElement.dir,'rtl');
 assert.equal(api.number(1234),new Intl.NumberFormat('ar').format(1234));
 assert.equal(api.date('2026-10-03T00:00:00Z',{timeZone:'UTC',year:'numeric'}),new Intl.DateTimeFormat('ar',{timeZone:'UTC',year:'numeric'}).format(new Date('2026-10-03T00:00:00Z')));
});
test('Translations and interpolated user content cannot inject HTML',()=>{
 const {api}=load('ar');const result=api.html('test.unsafe',{name:'<script>&amp;'});assert(!result.includes('<img'));assert(!result.includes('<script>'));assert(result.includes('&lt;img'));assert(result.includes('&lt;script&gt;&amp;amp;'));
 assert.equal(api.html('missing',{},'A &amp; B'),'A &amp; B');
});
test('Language switches persist and reload renderers; unsupported choices are rejected',()=>{
 const state=load('ar');state.api.setLanguage('ar');assert.equal(state.reloads(),0);state.api.setLanguage('en');assert.equal(state.preferences.ygc_ui_language,'en');assert.equal(state.reloads(),1);assert.throws(()=>state.api.setLanguage('../../db'),RangeError);
});
test('API errors preserve detail fallback and structured validation errors',()=>{
 const {api}=load();assert.equal(api.errorMessage({detail:'Raw diagnostic',message_key:'unknown'}),'Raw diagnostic');assert.equal(api.errorMessage({detail:[{msg:'Invalid field'},{msg:'Required'}]}),'Invalid field / Required');assert.equal(api.errorMessage({},'Unavailable'),'Unavailable');
});
test('Visibility and claim identifiers stay stable while their labels can translate',()=>{
 const {api,context}=load('ar');context.YGCI18nResources.catalogs.ar['values.visibility.Private']='خاص';assert.equal(api.label('visibility','Private'),'خاص');assert.equal(api.label('claim_type','transfer'),'Transfer');
 const settings=fs.readFileSync('app/src/ygc/static/pages/user-edit.js','utf8');assert(settings.includes("value=\"'+option+'\""));assert(settings.includes("const defaults={birth:'Private'"));
});
test('Authorization scheme is never translated with the UI',async()=>{
 const calls=[];const session={user_id:7,token:'local-test-token'};
 const originalFetch=async(input,options={})=>{calls.push({input,options});return {ok:true,status:200,json:async()=>({backend:'local_dummy'})}};
 const context={window:{fetch:originalFetch},URL,Headers,location:{origin:'http://localhost',href:'http://localhost/user-view'},
  sessionStorage:{getItem:key=>key==='ygc_local_auth'?JSON.stringify(session):key==='ygc_active_user_id'?'7':null},
  document:{documentElement:{}},MutationObserver:class{observe(){}},YGCI18n:{t:()=> 'Translated scheme'}};
 vm.runInNewContext(fs.readFileSync('app/src/ygc/static/local-auth.js','utf8'),context);
 await context.window.fetch('/api/users/7');assert.equal(calls.at(-1).options.headers.get('Authorization'),'Bearer local-test-token');
});
test('Cancelled page loading during language navigation retains login; real failures still clear it',async()=>{
 const page=fs.readFileSync('app/src/ygc/static/pages/user-view.js','utf8');const start=page.indexOf('async function loadActiveUser(');const source=page.slice(start,page.indexOf('\n}',start)+2);
 for(const changingLanguage of [true,false]){
  const removed=[];const context={YGCI18n:{changingLanguage},ACTIVE_USER_KEY:'actor',PROFILE_USER_ID:0,activeUser:{user:{id:7}},ownershipAttentionSequence:0,
   sessionStorage:{getItem:()=> '7',removeItem:key=>removed.push(key)},jfetch:async()=>{throw Error('Cancelled request')},
   loadUnansweredRequests:async()=>{},applyTheme(){},loadNotifications:async()=>{},loadDirectMessageInbox:async()=>{},loadOwnershipAttention:async()=>{},renderAccountHub(){},renderNotificationPanel(){}};
  vm.runInNewContext(source,context);await context.loadActiveUser();assert.equal(removed.length,changingLanguage?0:1);assert.equal(context.activeUser?.user?.id,changingLanguage?7:undefined);
 }
});

test('Japanese draft localizes labels, parameters and counts without changing content',()=>{
 const {api,context}=load('ja');assert.equal(api.locale,'ja');assert.equal(context.document.documentElement.lang,'ja');assert.equal(context.document.documentElement.dir,'ltr');
 assert.equal(api.t('header.notifications'),'通知');assert.equal(api.t('account.create'),'アカウント作成');assert.equal(api.t('requests.updated',{time:'10:30',count:2}),'更新：10:30 / 申請 2件');assert.equal(api.t('list.item_count',{count:1,formattedCount:'1'}),'1件');assert.equal(api.label('visibility','Private'),'非公開');
 assert.equal(api.t('guitar.reference',{id:42}),'ギター #42');
 assert.equal(api.t('ui.followers_a145ab34'),'フォロワー');assert.equal(api.label('visibility','Followers'),'フォロワーのみ');
});
test('Operation tab keys remain functional regardless of the selected UI language',()=>{
 const page=fs.readFileSync('app/src/ygc/static/pages/console.js','utf8');const start=page.indexOf("document.querySelector('.operations-menu').addEventListener('keydown'");const source=page.slice(start,page.indexOf('\n});',start)+4);
 let handle;let focused=-1,clicked=-1;
 const tabs=[0,1,2].map(index=>({focus:()=>focused=index,click:()=>clicked=index}));
 const context={YGCI18n:{t:()=> '翻訳されたキー'},document:{activeElement:tabs[1],querySelector:()=>({addEventListener:(_,callback)=>handle=callback}),querySelectorAll:()=>tabs}};
 vm.runInNewContext(source,context);
 for(const [key,next] of [['ArrowRight',2],['ArrowLeft',0],['Home',0],['End',2]]){let prevented=false;handle({key,preventDefault:()=>prevented=true});assert(prevented);assert.equal(focused,next);assert.equal(clicked,next);}
});
test('Japanese Chronicle labels retain stable category classes and source text',()=>{
 const page=fs.readFileSync('app/src/ygc/static/pages/user-view.js','utf8');const start=page.indexOf('function renderUserChronicle(');const source=page.slice(start,page.indexOf('\n}',start)+2);
 const root={innerHTML:''};const {api}=load('ja');const context={YGCI18n:api,document:{getElementById:()=>root},esc:value=>String(value),displayDiscoveryDateTime:value=>value};vm.runInNewContext(source,context);
 context.renderUserChronicle([{category:'User',subject:'Alice',message:'joined',event_at:'2026-10-03'},{category:'Social',subject:'Bob',message:'followed',event_at:'2026-10-03'},{category:'unexpected',subject:'Carol',message:'original content',event_at:'2026-10-03'}]);
 assert(root.innerHTML.includes('profile-chronicle-tag user">ユーザー'));assert(root.innerHTML.includes('profile-chronicle-tag social">交流'));assert(root.innerHTML.includes('profile-chronicle-tag other">その他'));assert(root.innerHTML.includes('Alice'));assert(root.innerHTML.includes('original content'));
});
