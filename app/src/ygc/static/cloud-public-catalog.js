import {loadCloudAuth} from './cloud-auth-loader.js';

// This public projection deliberately does not load the local Product Detail's
// owner, profile, image or mutation extensions. It shares its layout concepts.
const messages={
  en:{
    title:'All Discovered Guitars',eyebrow:'The stories behind the instruments',description:'Explore guitar specifications and their public Chronicle.',
    list:'Guitar catalog',detail:'Product Detail',account:'Sign in / Create account',language:'Language',search:'Search guitars',
    placeholder:'Maker, model or serial',sort:'Sort',submit:'Search',refresh:'Refresh',newest:'Newest first',oldest:'Oldest first',
    maker:'Maker',manufacturer:'Maker',model:'Model',finish:'Finish',year:'Year',serial_number:'Serial',previous:'Previous',next:'Next',
    back:'Back to catalog',view:'View details',loading:'Loading guitars…',loading_detail:'Loading guitar details…',choose:'Choose a guitar to explore its story.',
    count:'{count} guitars',page:'Page {page} of {pages}',empty:'No guitars found. Try a different search.',photo:'Photo unavailable',
    specification:'Specification',chronicle:'Chronicle',acquire:'Acquire',acquire_help:'Continue to your account to make an ownership application.',
    identifier:'Guitar #{id}',source:'Source',more:'Load more',loading_more:'Loading…',chronicle_empty:'No public Chronicle entries yet.',
    chronicle_order:'Latest recorded first',chronicle_count:'{count} public entries shown',unavailable:'The catalog is temporarily unavailable. Please try Refresh.',
    missing:'This guitar was not found or is no longer public.',invalid:'This search could not be loaded. Please change the search and try again.',
    restricted:'Catalog access is temporarily restricted.',forbidden:'This account cannot access the catalog right now.',
    session:'Your session could not be verified. Open your account to sign in again, then refresh.',
    auth_unavailable:'Account sign-in is temporarily unavailable. You can still browse the public catalog.',
    read_only:'Read-only mode: browsing is available; changes are temporarily paused.',offline:'The catalog is temporarily offline.',
    admin_only:'The catalog is temporarily limited to administrators.',service_unknown:'Service status is unavailable. Catalog access is checked separately.',
    footer:'Your Guitar Chronicle · Public catalog',positive:'Positive',negative:'Negative',unverified:'Unverified',
    ownership:'Ownership',specification_claim:'Specification',repair:'Repair',incident:'Incident',event:'Event',media:'Media',listing:'Listing',
    identity_correction:'Identity correction',acquire_kind:'Acquire',release:'Release',transfer:'Transfer',lost:'Lost',found:'Found',inherit:'Inheritance',
    body:'Body',bridge:'Bridge',fingerboard:'Fingerboard',frets:'Frets',neck:'Neck',nut:'Nut',pickups:'Pickups',pickguard:'Pickguard',
    potentiometers:'Potentiometers',tuners:'Tuners',wiring:'Wiring',weight:'Weight',pages_label:'Catalog pages',nav_label:'Account and language',
  },
  ja:{
    title:'発見されたすべてのギター',eyebrow:'楽器の背景にある物語',description:'ギターの仕様と公開クロニクルを閲覧できます。',
    list:'ギターカタログ',detail:'個体詳細',account:'サインイン / アカウント作成',language:'言語',search:'ギターを検索',
    placeholder:'メーカー、モデル、シリアル',sort:'並び順',submit:'検索',refresh:'更新',newest:'新しい順',oldest:'古い順',
    maker:'メーカー',manufacturer:'メーカー',model:'モデル',finish:'仕上げ',year:'年式',serial_number:'シリアル',previous:'前へ',next:'次へ',
    back:'カタログに戻る',view:'詳細を見る',loading:'ギターを読み込み中…',loading_detail:'個体詳細を読み込み中…',choose:'ギターを選ぶと詳細を表示します。',
    count:'{count}本のギター',page:'{pages}ページ中 {page}ページ',empty:'ギターが見つかりません。検索条件を変えてお試しください。',photo:'写真は公開されていません',
    specification:'仕様',chronicle:'クロニクル',acquire:'所有申請',acquire_help:'所有申請を行うにはアカウント画面へ進んでください。',
    identifier:'ギター #{id}',source:'出典',more:'さらに読み込む',loading_more:'読み込み中…',chronicle_empty:'公開クロニクルはまだありません。',
    chronicle_order:'記録が新しい順',chronicle_count:'公開記録を{count}件表示',unavailable:'現在カタログを利用できません。「更新」で再度お試しください。',
    missing:'このギターは見つからないか、公開されていません。',invalid:'検索結果を読み込めません。検索条件を変えてお試しください。',
    restricted:'カタログの閲覧は一時的に制限されています。',forbidden:'このアカウントでは現在カタログを閲覧できません。',
    session:'セッションを確認できませんでした。アカウント画面でサインインし直してから更新してください。',
    auth_unavailable:'現在アカウントの認証を利用できません。公開カタログは引き続き閲覧できます。',
    read_only:'閲覧専用モード：閲覧できますが、変更は一時停止中です。',offline:'カタログは一時停止中です。',
    admin_only:'現在カタログを閲覧できるのは管理者のみです。',service_unknown:'サービス状態を取得できません。カタログの閲覧可否は個別に確認されます。',
    footer:'Your Guitar Chronicle · 公開カタログ',positive:'承認済み',negative:'否認',unverified:'未確認',
    ownership:'所有権',specification_claim:'仕様',repair:'修理',incident:'事故・被害',event:'イベント',media:'メディア',listing:'出品',
    identity_correction:'個体情報の訂正',acquire_kind:'取得',release:'手放し',transfer:'譲渡',lost:'紛失',found:'発見',inherit:'相続',
    body:'ボディ',bridge:'ブリッジ',fingerboard:'指板',frets:'フレット',neck:'ネック',nut:'ナット',pickups:'ピックアップ',pickguard:'ピックガード',
    potentiometers:'ポット',tuners:'ペグ',wiring:'配線',weight:'重量',pages_label:'カタログのページ',nav_label:'アカウントと言語',
  },
};
const sorts=['newest','oldest','maker','model'],fixedFields=['manufacturer','model','finish','year','serial_number'];
const preferredFields=['body','bridge','fingerboard','frets','neck','nut','pickups','pickguard','potentiometers','tuners','wiring','weight'];
const validId=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&!/[\r\n]/.test(value);
const valueText=value=>typeof value==='string'&&value.length?value:'—';
const safeSource=value=>typeof value==='string'&&value===value.trim()&&/^https:\/\/reverb\.com\/item\/[1-9][0-9]{0,19}$/.test(value)?value:null;

export function createPublicCatalog({document=globalThis.document,window=globalThis.window,request=globalThis.fetch.bind(globalThis),loadAuth=loadCloudAuth}={}){
  const $=id=>document.getElementById(id);
  let locale='en';
  try{if(window.localStorage.getItem('ygc_ui_language')==='ja')locale='ja'}catch{/* Storage is optional. */}
  const t=(key,params={})=>(messages[locale][key]??key).replace(/\{(\w+)\}/g,(match,name)=>Object.hasOwn(params,name)?String(params[name]):match);
  const node=(tag,text,className)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(className)item.className=className;return item};
  let route=null,list=null,detail=null,claims=[],nextAfter=null,service=null,serviceFailed=false;
  let listMessage='loading',detailMessage='choose',authNotice='',auth=null,authReady=null,authBlocked=null;
  let epoch=0,controller=null,moreController=null,loading=false,moreLoading=false,pending=null,stopped=false;

  function readRoute(url=new URL(window.location.href)){
    const q=[...String(url.searchParams.get('q')||'').trim()].slice(0,120).join('');
    const sort=sorts.includes(url.searchParams.get('sort'))?url.searchParams.get('sort'):'newest';
    const raw=url.searchParams.get('page')||'1',page=/^[1-9][0-9]*$/.test(raw)&&Number(raw)<=1000000?Number(raw):1;
    const match=/^\/guitars\/([1-9][0-9]{0,18})\/?$/.exec(url.pathname);
    return {q,sort,page,id:match?.[1]||null,invalid:url.pathname!=='/'&&!match};
  }
  function routeURL(value){
    const query=new URLSearchParams();
    if(value.q)query.set('q',value.q);if(value.sort!=='newest')query.set('sort',value.sort);if(value.page!==1)query.set('page',String(value.page));
    return (value.id?'/guitars/'+value.id:'/')+(query.size?'?'+query:'');
  }
  function intercept(link,target){
    link.href=target;
    link.onclick=event=>{
      if(event&&(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey))return;
      event?.preventDefault();return navigate(target,true);
    };
  }
  function errorKey(error){
    if(error.code==='service_restricted')return 'restricted';
    if(error.status===401||error.code==='sign_in_required'||String(error.code||'').startsWith('auth/'))return 'session';
    return error.status===403?'forbidden':error.status===404?'missing':error.status===400?'invalid':'unavailable';
  }
  async function initializeAuth(retry=false){
    if(authReady&&!retry)return authReady;
    authReady=(async()=>{
      authBlocked=null;authNotice='';
      try{auth=auth||await loadAuth();await auth.restore()}
      catch(error){
        // A known identity or rejected token must never become an anonymous retry.
        if(auth?.signedIn||[401,403].includes(error.status)||['auth/invalid-user-token','auth/user-token-expired','auth/id-token-expired','auth/id-token-revoked','auth/user-disabled','auth/user-not-found'].includes(error.code)){
          authBlocked=error;authNotice=errorKey(error);
        }else{auth=null;authNotice='auth_unavailable'}
      }
    })();
    return authReady;
  }
  async function json(response){
    if(!response.ok){
      let code;try{const body=await response.json();code=body.code||body.detail?.code}catch{/* Preserve HTTP status. */}
      throw Object.assign(Error('Public catalog request failed.'),{status:response.status,code});
    }
    return response.json();
  }
  async function publicRequest(path,signal){
    if(authBlocked)throw authBlocked;
    const options={method:'GET',cache:'no-store',credentials:'omit',redirect:'error',signal};
    const response=auth?.signedIn?await auth.authorizedFetch(path,options):await request(path,options);
    // Do not downgrade a failed authorized request to the anonymous route.
    return json(response);
  }
  function validateGuitar(row){
    if(!row||!validId(row.id)||fixedFields.some(field=>row[field]!==null&&typeof row[field]!=='string'))throw Error('Invalid public guitar.');
    return row;
  }
  function validateItems(items){
    if(!Array.isArray(items)||items.some(item=>!item||typeof item.field_name!=='string'||typeof item.value_text!=='string'))throw Error('Invalid public specifications.');
    return items;
  }
  function validatePage(page){
    if(!page||!Array.isArray(page.items)||page.items.length>24||typeof page.total!=='string'||!/^(0|[1-9][0-9]*)$/.test(page.total)||!Number.isSafeInteger(page.page)||page.page<1||page.page>1000000||page.page_size!==24||!Number.isSafeInteger(page.total_pages)||page.total_pages<0)throw Error('Invalid public catalog page.');
    page.items.forEach(validateGuitar);return page;
  }
  function validateChronicle(page){
    if(!page||!Array.isArray(page.items)||page.items.length>25||!(page.next_after===null||validId(page.next_after)))throw Error('Invalid public Chronicle.');
    for(const row of page.items){
      if(!row||!validId(row.id)||typeof row.claim_type!=='string'||!['positive','negative','unverified'].includes(row.verification_status))throw Error('Invalid public Claim.');
      validateItems(row.items);
    }
    return page;
  }
  function clearDetail(){
    detail=null;claims=[];nextAfter=null;moreLoading=false;
    $('detailContent').hidden=true;$('detailTitle').textContent='';$('detailIdentifier').textContent='';
    $('detailSpecifications').replaceChildren();$('chronicleEntries').replaceChildren();$('chronicleStatus').textContent='';
    $('acquireLink').href='/account';$('chronicleMore').hidden=true;
  }
  function renderStatic(){
    const labels={catalogTitle:'title',catalogEyebrow:'eyebrow',catalogDescription:'description',listHeading:'list',detailHeading:'detail',accountLink:'account',languageLabel:'language',searchLabel:'search',sortLabel:'sort',catalogSearchSubmit:'submit',catalogRefresh:'refresh',catalogPrevious:'previous',catalogNext:'next',catalogBack:'back',photoPlaceholder:'photo',specificationHeading:'specification',chronicleHeading:'chronicle',chronicleOrder:'chronicle_order',acquireLink:'acquire',acquireDescription:'acquire_help',catalogFooter:'footer'};
    for(const [id,key] of Object.entries(labels))$(id).textContent=t(key);
    document.documentElement.lang=locale;document.title='Your Guitar Chronicle — '+t('list');
    $('catalogSearch').placeholder=t('placeholder');$('catalogLanguage').value=locale;$('catalogLanguage').setAttribute('aria-label',t('language'));
    $('detailPhoto').setAttribute('aria-label',t('photo'));$('catalogPagination').setAttribute('aria-label',t('pages_label'));
    document.querySelector('.page-nav').setAttribute('aria-label',t('nav_label'));
    $('catalogSort').replaceChildren();for(const value of sorts){const option=node('option',t(value));option.value=value;$('catalogSort').append(option)}
    if(route)$('catalogSort').value=route.sort;
  }
  function controls(){
    $('catalogLayout').dataset.detailOpen=String(Boolean(route?.id||route?.invalid));
    $('catalogRows').setAttribute('aria-busy',String(loading));$('catalogDetail').setAttribute('aria-busy',String(loading||moreLoading));
    $('catalogRefresh').disabled=loading;$('catalogPrevious').disabled=loading||!list||route.page<=1;
    $('catalogNext').disabled=loading||!list||route.page>=list.total_pages||route.page>=1000000;
    $('catalogPage').textContent=list?t('page',{page:list.page,pages:Math.max(list.total_pages,1)}):'';
    $('catalogStatus').textContent=listMessage?t(listMessage):list?t(list.items.length?'count':'empty',{count:list.total}):'';
    $('detailStatus').textContent=detailMessage?t(detailMessage):'';$('detailStatus').hidden=!detailMessage;
    $('catalogBack').hidden=!route?.id&&!route?.invalid;
    if(route)intercept($('catalogBack'),routeURL({...route,id:null,invalid:false}));
    $('chronicleMore').hidden=!detail||nextAfter===null;$('chronicleMore').disabled=loading||moreLoading;
    $('chronicleMore').textContent=t(moreLoading?'loading_more':'more');
    $('authNotice').hidden=!authNotice;$('authNotice').textContent=authNotice?t(authNotice):'';
    const serviceText=serviceFailed?t('service_unknown'):service&&service.mode!=='normal'?t(service.mode)+(service.message?'\n'+service.message:''):'';
    $('serviceNotice').hidden=!serviceText;$('serviceNotice').textContent=serviceText;
  }
  function renderList(){
    $('catalogRows').replaceChildren();if(!list)return;
    for(const row of list.items){
      const card=node('li',undefined,'guitar-card'+(row.id===route.id?' is-selected':''));
      card.append(node('h3',[row.manufacturer,row.model].filter(Boolean).join(' ')||t('identifier',{id:row.id})));
      const facts=node('p',undefined,'guitar-facts');
      for(const field of ['finish','year','serial_number'])facts.append(node('span',t(field)+': '+valueText(row[field])));
      const link=node('a',t('view'),'guitar-detail-link');link.setAttribute('aria-label',t('view')+' · '+t('identifier',{id:row.id}));
      intercept(link,routeURL({...route,id:row.id}));card.append(facts,link);$('catalogRows').append(card);
    }
  }
  function fieldLabel(field){return messages[locale][field]??field}
  function renderChronicle(){
    $('chronicleEntries').replaceChildren();
    for(const row of claims){
      const type=fieldLabel(row.claim_type==='specification'?'specification_claim':row.claim_type);
      const name=type+(row.ownership_kind?' / '+fieldLabel(row.ownership_kind==='acquire'?'acquire_kind':row.ownership_kind):'');
      const meta='#'+row.id+' · '+valueText(row.occurred_at||row.created_at)+' · '+t(row.verification_status);
      if(row.verification_status!=='positive'){
        // Non-positive Claims are public tags/points only, even if an API adds fields.
        const card=node('div',undefined,'chronicle-record '+row.verification_status),tag=node('span',row.verification_status==='negative'?'●':name);
        tag.title=name+' · '+meta;tag.setAttribute('aria-label',name+' · '+meta);card.append(tag);$('chronicleEntries').append(card);continue;
      }
      const card=node('details',undefined,'chronicle-record positive');card.open=true;card.append(node('summary',name),node('p',meta));
      const values=node('dl');for(const item of row.items)values.append(node('dt',fieldLabel(item.field_name)),node('dd',item.value_text));card.append(values);
      const source=safeSource(row.source_url);if(source){const link=node('a',t('source'));link.href=source;link.target='_blank';link.rel='noopener noreferrer';card.append(link)}
      $('chronicleEntries').append(card);
    }
    $('chronicleStatus').textContent=t(claims.length?'chronicle_count':'chronicle_empty',{count:claims.length});
  }
  function renderDetail(){
    if(!detail)return;
    $('detailContent').hidden=false;$('detailTitle').textContent=[detail.manufacturer,detail.model].filter(Boolean).join(' ')||t('identifier',{id:detail.id});
    $('detailIdentifier').textContent=t('identifier',{id:detail.id});$('acquireLink').href='/account?acquire='+encodeURIComponent(detail.id);
    $('detailSpecifications').replaceChildren();
    const add=(field,value)=>{const row=node('div',undefined,'catalog-spec-row');row.append(node('dt',fieldLabel(field),'catalog-spec-label'),node('dd',valueText(value),'catalog-spec-value'));$('detailSpecifications').append(row)};
    const finish=detail.specifications.find(item=>item.field_name.toLowerCase()==='finish');
    for(const field of fixedFields)add(field,field==='finish'&&finish?finish.value_text:detail[field]);
    const hidden=new Set([...fixedFields,'maker','serial']);
    const dynamic=detail.specifications.filter(item=>!hidden.has(item.field_name.toLowerCase())).slice().sort((a,b)=>{
      const ai=preferredFields.indexOf(a.field_name.toLowerCase()),bi=preferredFields.indexOf(b.field_name.toLowerCase());
      return (ai<0?preferredFields.length:ai)-(bi<0?preferredFields.length:bi)||a.field_name.localeCompare(b.field_name);
    });
    for(const item of dynamic)add(item.field_name,item.value_text);
    renderChronicle();
  }
  async function checkService(current,signal){
    try{
      const data=await json(await request('/api/service/status',{method:'GET',cache:'no-store',credentials:'omit',redirect:'error',signal}));
      if(!data||!['normal','read_only','offline','admin_only'].includes(data.mode)||typeof data.message!=='string')throw Error('Invalid service state.');
      if(current!==epoch||stopped)return;service=data;serviceFailed=false;
    }catch{if(current!==epoch||stopped)return;service=null;serviceFailed=true}
    controls();
  }
  function loadRoute(next,{retryAuth=false,focus=false}={}){
    if(stopped)return Promise.resolve();
    const current=++epoch;controller?.abort();moreController?.abort();controller=new AbortController();const signal=controller.signal;
    const sameList=route&&route.q===next.q&&route.sort===next.sort&&route.page===next.page;
    route=next;if(!sameList)list=null;clearDetail();loading=true;listMessage='loading';detailMessage=next.id?'loading_detail':next.invalid?'missing':'choose';
    $('catalogSearch').value=route.q;$('catalogSort').value=route.sort;renderList();controls();
    pending=(async()=>{
      const serviceCheck=checkService(current,signal);
      await initializeAuth(retryAuth);
      if(current!==epoch||stopped)return;
      const query=new URLSearchParams({q:route.q,sort:route.sort,page:String(route.page),limit:'24'});
      const listWork=publicRequest('/api/public/guitars?'+query,signal).then(page=>{validatePage(page);if(page.page!==next.page)throw Error('Unexpected catalog page.');return page});
      const detailWork=route.id?Promise.all([
        publicRequest('/api/public/guitars/'+route.id,signal).then(row=>{validateGuitar(row);validateItems(row.specifications);if(row.id!==next.id)throw Error('Unexpected guitar.');return row}),
        publicRequest('/api/public/guitars/'+route.id+'/chronicle?limit=25',signal).then(validateChronicle),
      ]):Promise.resolve(null);
      const results=await Promise.allSettled([listWork,detailWork]);
      if(current!==epoch||stopped)return;
      const fatal=results.find(result=>result.status==='rejected'&&([401,403,503].includes(result.reason.status)||result.reason===authBlocked));
      if(fatal){list=null;clearDetail();listMessage=errorKey(fatal.reason);detailMessage=route.id?listMessage:route.invalid?'missing':'choose'}
      else{
        if(results[0].status==='fulfilled'){list=results[0].value;listMessage=''}else{list=null;listMessage=errorKey(results[0].reason)}
        if(route.id){
          if(results[1].status==='fulfilled'){
            [detail,{items:claims,next_after:nextAfter}]=results[1].value;detailMessage='';renderDetail();
          }else{clearDetail();detailMessage=errorKey(results[1].reason)}
        }
      }
      renderList();loading=false;controls();
      if(focus&&route.id)$('detailHeading').focus();
      await serviceCheck;
    })().catch(error=>{
      if(current!==epoch||stopped)return;
      list=null;clearDetail();loading=false;listMessage=errorKey(error);detailMessage=route.id?listMessage:'choose';renderList();controls();
    });
    return pending;
  }
  function navigate(target,focus=false){
    const url=new URL(target,window.location.href);if(url.origin!==window.location.origin)return Promise.resolve();
    const next=readRoute(url);if(next.invalid)return Promise.resolve();const canonical=routeURL(next);
    if(canonical===window.location.pathname+window.location.search)return loading?pending:loadRoute(next,{focus});
    window.history.pushState({ygcPublicCatalog:true},'',canonical);return loadRoute(next,{focus});
  }
  function refresh(){if(loading)return pending;return loadRoute(readRoute(),{retryAuth:true})}
  async function more(){
    if(loading||moreLoading||!detail||nextAfter===null)return;
    moreLoading=true;const current=epoch,id=detail.id,cursor=nextAfter;moreController=new AbortController();controls();
    try{
      const query=new URLSearchParams({after:cursor,limit:'25'}),page=validateChronicle(await publicRequest('/api/public/guitars/'+id+'/chronicle?'+query,moreController.signal));
      if(current!==epoch||stopped)return;
      if(page.next_after===cursor)throw Error('Chronicle cursor did not advance.');
      const seen=new Set(claims.map(row=>row.id));claims.push(...page.items.filter(row=>!seen.has(row.id)));nextAfter=page.next_after;renderChronicle();
    }catch(error){
      if(current!==epoch||stopped)return;
      clearDetail();detailMessage=errorKey(error);
      if([401,403,503].includes(error.status)){list=null;listMessage=detailMessage;renderList()}
    }finally{if(current===epoch&&!stopped){moreLoading=false;controls()}}
  }
  function onPopstate(){return loadRoute(readRoute())}
  function setLanguage(){
    locale=$('catalogLanguage').value==='ja'?'ja':'en';try{window.localStorage.setItem('ygc_ui_language',locale)}catch{/* Keep the change for this page. */}
    renderStatic();renderList();renderDetail();controls();
  }
  function start(){
    renderStatic();
    $('catalogSearchForm').onsubmit=event=>{event.preventDefault();return navigate(routeURL({q:[...$('catalogSearch').value.trim()].slice(0,120).join(''),sort:$('catalogSort').value,page:1,id:null}))};
    $('catalogSort').onchange=()=>navigate(routeURL({q:$('catalogSearch').value.trim(),sort:$('catalogSort').value,page:1,id:null}));
    $('catalogRefresh').onclick=refresh;
    $('catalogPrevious').onclick=()=>{if(!loading&&list&&route.page>1)return navigate(routeURL({...route,page:route.page-1,id:null}))};
    $('catalogNext').onclick=()=>{if(!loading&&list&&route.page<list.total_pages&&route.page<1000000)return navigate(routeURL({...route,page:route.page+1,id:null}))};
    $('chronicleMore').onclick=more;$('catalogLanguage').onchange=setLanguage;window.addEventListener('popstate',onPopstate);
    return loadRoute(readRoute());
  }
  function destroy(){stopped=true;++epoch;controller?.abort();moreController?.abort();window.removeEventListener('popstate',onPopstate)}
  return {start,refresh,navigate,destroy};
}

// Readiness is for the disposable browser checks; it does not expose identity.
const catalog=createPublicCatalog();
await catalog.start();
globalThis.YGCCloudPublicCatalogReady=true;
