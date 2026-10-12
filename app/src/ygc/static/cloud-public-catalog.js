import {createAuthDialog} from './cloud-auth-dialog.js';
import {createFavoriteControl,createFavoriteSnapshotReader} from './cloud-account-favorites.js';
import {loadCloudAuth} from './cloud-auth-loader.js';

// Formal pages use the canonical Product Detail renderer with only authorized
// public DTO fields. The public catalog and private API boundaries remain separate.
const messages={
  en:{
    "favorites.heading":"Your favorite guitars",
    "favorites.private_notice":"Only you can see your favorites. Profile visibility preferences do not make them public.",
    "favorites.count":"{count} favorites visible to you",
    "favorites.empty":"No visible favorites yet. Add one from a public guitar detail.",
    "favorites.guitar":"Guitar #{id}",
    "favorites.account":"Sign in to manage your private favorites",
    "favorites.add":"♡ Add to favorites",
    "favorites.remove":"♥ Remove from favorites",
    "favorites.added":"Added to your private favorites.",
    "favorites.removed":"Removed from your favorites.",
    "favorites.uncertain":"The result could not be confirmed. Refresh to check your current favorite before making another change.",
    "favorites.failed":"Favorites could not be loaded. Try Refresh.",
    "favorites.restricted":"Changes are temporarily restricted. Refresh to check current access.",
    "favorites.session":"Your verified account could not be confirmed. Open your account and sign in again.",
    "favorites.missing":"This guitar is unavailable. Refresh the catalog before trying again.",
    'action.refresh':'Refresh','cloud.working':'Working…',
    title:'All Discovered Guitars',eyebrow:'The stories behind the instruments',description:'Explore guitar specifications and their public Chronicle.',
    list:'Guitar catalog',detail:'Product Detail',account:'Sign in / Create account',language:'Language',search:'Search guitars',
    placeholder:'Maker, model or serial',sort:'Sort',submit:'Search',refresh:'Refresh',newest:'Newest first',oldest:'Oldest first',
    maker:'Maker',manufacturer:'Maker',model:'Model',finish:'Finish',year:'Year',serial_number:'Serial',previous:'Previous',next:'Next',
    back:'Back to catalog',view:'View details',loading:'Loading guitars…',loading_detail:'Loading guitar details…',choose:'Choose a guitar to explore its story.',
    count:'{count} guitars',page:'Page {page} of {pages}',empty:'No guitars found. Try a different search.',photo:'Photo unavailable',
    ownership_action:'Transfer / Release',ownership_help:'Current owners can propose a Transfer or record a Release from their account.',add_claim:'Add Claim',add_claim_help:'Record a specification, repair or incident from your account.',
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
    "favorites.heading":"お気に入りのギター",
    "favorites.private_notice":"お気に入りを閲覧できるのは本人だけです。プロフィールの公開範囲設定で公開されることはありません。",
    "favorites.count":"本人が閲覧できるお気に入り：{count}本",
    "favorites.empty":"閲覧できるお気に入りはありません。公開ギターの詳細画面から追加できます。",
    "favorites.guitar":"ギター #{id}",
    "favorites.account":"サインインして自分のお気に入りを管理",
    "favorites.add":"♡ お気に入りに追加",
    "favorites.remove":"♥ お気に入りを解除",
    "favorites.added":"自分のお気に入りに追加しました。",
    "favorites.removed":"お気に入りを解除しました。",
    "favorites.uncertain":"更新結果を確認できませんでした。次の変更前に「更新」で現在の状態を確認してください。",
    "favorites.failed":"お気に入りを取得できませんでした。「更新」をお試しください。",
    "favorites.restricted":"現在、変更が制限されています。「更新」で現在の状態を確認してください。",
    "favorites.session":"確認済みのアカウントを確認できませんでした。アカウント画面でサインインし直してください。",
    "favorites.missing":"このギターは現在利用できません。カタログを更新してからお試しください。",
    'action.refresh':'更新','cloud.working':'処理中…',
    title:'発見されたすべてのギター',eyebrow:'楽器の背景にある物語',description:'ギターの仕様と公開クロニクルを閲覧できます。',
    list:'ギターカタログ',detail:'個体詳細',account:'サインイン / アカウント作成',language:'言語',search:'ギターを検索',
    placeholder:'メーカー、モデル、シリアル',sort:'並び順',submit:'検索',refresh:'更新',newest:'新しい順',oldest:'古い順',
    maker:'メーカー',manufacturer:'メーカー',model:'モデル',finish:'仕上げ',year:'年式',serial_number:'シリアル',previous:'前へ',next:'次へ',
    back:'カタログに戻る',view:'詳細を見る',loading:'ギターを読み込み中…',loading_detail:'個体詳細を読み込み中…',choose:'ギターを選ぶと詳細を表示します。',
    count:'{count}本のギター',page:'{pages}ページ中 {page}ページ',empty:'ギターが見つかりません。検索条件を変えてお試しください。',photo:'写真は公開されていません',
    ownership_action:'譲渡 / 手放し',ownership_help:'現在の所有者はアカウント画面から譲渡の申請や手放しの記録ができます。',add_claim:'Claimを追加',add_claim_help:'アカウント画面から仕様・修理・事故や被害を記録できます。',
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
    ownership:'所有権',specification_claim:'スペック',repair:'修理',incident:'事故・被害',event:'イベント',media:'メディア',listing:'掲載',
    identity_correction:'個体情報の訂正',acquire_kind:'取得',release:'手放し',transfer:'譲渡',lost:'紛失',found:'発見',inherit:'相続',
    body:'ボディ',bridge:'ブリッジ',fingerboard:'指板',frets:'フレット',neck:'ネック',nut:'ナット',pickups:'ピックアップ',pickguard:'ピックガード',
    potentiometers:'ポット',tuners:'ペグ',wiring:'配線',weight:'重量',pages_label:'カタログのページ',nav_label:'アカウントと言語',
  },
};
const sorts=['newest','oldest','maker','model'],fixedFields=['manufacturer','model','finish','year','serial_number'];
const formalSorts=fixedFields.flatMap(field=>[field+'_asc',field+'_desc']);
const preferredFields=['body','bridge','fingerboard','frets','neck','nut','pickups','pickguard','potentiometers','tuners','wiring','weight'];
const validId=value=>typeof value==='string'&&/^[1-9][0-9]{0,18}$/.test(value)&&!/[\r\n]/.test(value);
const valueText=value=>typeof value==='string'&&value.length?value:'—';
const safeSource=value=>typeof value==='string'&&value===value.trim()&&/^https:\/\/reverb\.com\/item\/[1-9][0-9]{0,19}$/.test(value)?value:null;

export function createPublicCatalog({document=globalThis.document,window=globalThis.window,request=globalThis.fetch.bind(globalThis),loadAuth=loadCloudAuth,restoredAccount=()=>null,basePath='',listStyle='cards',onState=()=>{},detailOnly=false,accountPath='/account',onClaim=null,onAcquire=null,onOwnership=null,onChronicle=()=>{},onClaimPopup=()=>{}}={}){
  if(!['','/ui','/ui/profile'].includes(basePath)||!['/account','/ui/profile'].includes(accountPath)||!['cards','table'].includes(listStyle))throw Error('Invalid catalog presentation.');
  const $=id=>document.getElementById(id);
  let locale='en';
  try{if(window.localStorage.getItem('ygc_ui_language')==='ja')locale='ja'}catch{/* Storage is optional. */}
  const t=(key,params={})=>(messages[locale][key]??key).replace(/\{(\w+)\}/g,(match,name)=>Object.hasOwn(params,name)?String(params[name]):match);
  const node=(tag,text,className)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(className)item.className=className;return item};
  let route=null,list=null,detail=null,claims=[],nextAfter=null,service=null,serviceFailed=false,compactDismissed=false,searchTimer=null;
  let listMessage='loading',detailMessage='choose',authNotice='',auth=null,authReady=null,authBlocked=null,authRestoring=true;
  let epoch=0,controller=null,moreController=null,loading=false,moreLoading=false,pending=null,stopped=false;
  let readRevision=0,initialDetailId=null;

  const formal=Boolean(basePath);
  let unfilteredTotal=null,photoURL=null,photoEpoch=0;
  const rowFavorites=new Map();
  const readRowFavorite=createFavoriteSnapshotReader({auth:()=>auth,state:()=>auth?.account});
  function clearRowFavorites(){for(const item of rowFavorites.values())item.control.clear();rowFavorites.clear()}

  const favorite=createFavoriteControl({auth:()=>auth,state:()=>auth?.account,root:$('detailFavorite'),compact:formal,document,t,canWrite:()=>service?.mode!=='read_only'&&service?.mode!=='offline'});
  let unsubscribeIdentity=null;
  function readRoute(url=new URL(window.location.href)){
    const q=[...String(url.searchParams.get('q')||'').trim()].slice(0,120).join('');
    const sort=[...sorts,...(formal?formalSorts:[])].includes(url.searchParams.get('sort'))?url.searchParams.get('sort'):'newest';
    const raw=url.searchParams.get('page')||'1',page=!formal&&/^[1-9][0-9]*$/.test(raw)&&Number(raw)<=1000000?Number(raw):1;
    const pathname=basePath?(url.pathname===basePath?'/':url.pathname.startsWith(basePath+'/')?url.pathname.slice(basePath.length):'invalid'):url.pathname;
    const match=/^\/guitars\/([1-9][0-9]{0,18})\/?$/.exec(pathname);
    return {q,sort,page,id:match?.[1]||(pathname==='/'?initialDetailId:null),invalid:pathname!=='/'&&!match};
  }
  function routeURL(value){
    const query=new URLSearchParams();
    if(value.q)query.set('q',value.q);if(value.sort!=='newest')query.set('sort',value.sort);if(value.page!==1)query.set('page',String(value.page));
    return (value.id?basePath+'/guitars/'+value.id:(basePath||'/'))+(query.size?'?'+query:'');
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
    const revision=++readRevision;authRestoring=true;
    authReady=(async()=>{
      authBlocked=null;authNotice='';favorite.clear();clearRowFavorites();unfilteredTotal=null;
      // The first SDK principal notification belongs to restoration, not an
      // account switch. Subscribe after it; later switches still purge all data.
      try{auth=auth||await loadAuth();if(retry||!auth?.account?.user||restoredAccount()!==auth.account)await auth.restore()}
      catch(error){
        // A known identity or rejected token must never become an anonymous retry.
        if(auth?.signedIn||[401,403].includes(error.status)||['auth/invalid-user-token','auth/user-token-expired','auth/id-token-expired','auth/id-token-revoked','auth/user-disabled','auth/user-not-found'].includes(error.code)){
          authBlocked=error;authNotice=errorKey(error);
        }else{auth=null;authNotice='auth_unavailable'}
      }finally{if(revision===readRevision)authRestoring=false;if(auth&&!unsubscribeIdentity){const identity=auth.onIdentityChanged?.(invalidateIdentity),data=auth.onUserDataInvalidated?.((reason,error)=>{if(reason==='blocked')invalidateIdentity(error)});unsubscribeIdentity=()=>{identity?.();data?.()}}}
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
    const options={method:'GET',cache:'no-cache',credentials:'omit',redirect:'error',signal};
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
  async function loadList(next,signal,current){
    const query=new URLSearchParams({q:next.q,sort:next.sort,page:String(next.page),limit:'24'});
    const first=validatePage(await publicRequest('/api/public/guitars?'+query,signal));
    if(first.page!==next.page)throw Error('Unexpected catalog page.');
    if(!formal)return first;
    const items=[...first.items],seen=new Set(items.map(row=>row.id));
    if(seen.size!==items.length)throw Error('Duplicate catalog guitar.');
    // Submit only two remaining pages at a time, preserve page order even if
    // responses finish out of order, and never publish a partial aggregate.
    for(let number=2;number<=first.total_pages;number+=2){
      if(signal.aborted||current!==epoch||stopped)throw Error('Stale catalog.');
      const numbers=[number,...number<first.total_pages?[number+1]:[]];
      const pages=await Promise.all(numbers.map(async pageNumber=>{
        const params=new URLSearchParams(query);params.set('page',String(pageNumber));
        const page=validatePage(await publicRequest('/api/public/guitars?'+params,signal));
        if(page.page!==pageNumber||page.total!==first.total||page.total_pages!==first.total_pages)throw Error('Catalog changed while loading.');
        return page;
      }));
      if(signal.aborted||current!==epoch||stopped)throw Error('Stale catalog.');
      for(const page of pages)for(const row of page.items){if(seen.has(row.id))throw Error('Duplicate catalog guitar.');seen.add(row.id);items.push(row)}
    }
    if(String(items.length)!==first.total)throw Error('Incomplete catalog.');
    let total=unfilteredTotal;
    if(!next.q)total=first.total;
    else if(total===null){
      const counts=validatePage(await publicRequest('/api/public/guitars?'+new URLSearchParams({q:'',sort:'newest',page:'1',limit:'24'}),signal));
      if(counts.page!==1)throw Error('Unexpected catalog count page.');total=counts.total;
    }
    if(current===epoch&&!stopped)unfilteredTotal=total;
    return {...first,items};
  }
  function validateChronicle(page){
    if(!page||!Array.isArray(page.items)||page.items.length>25||!(page.next_after===null||validId(page.next_after)))throw Error('Invalid public Chronicle.');
    for(const row of page.items){
      if(!row||!validId(row.id)||typeof row.claim_type!=='string'||!['positive','negative','unverified'].includes(row.verification_status))throw Error('Invalid public Claim.');
      validateItems(row.items);
    }
    return page;
  }
  async function loadChronicle(id,signal,current){
    const first=validateChronicle(await publicRequest('/api/public/guitars/'+id+'/chronicle?limit=25',signal));
    if(!formal)return first;
    const items=[],seen=new Set();let page=first,after=null;
    do{
      for(const row of page.items){
        if(seen.has(row.id)||after!==null&&BigInt(row.id)>=BigInt(after))throw Error('Invalid Chronicle cursor.');
        seen.add(row.id);items.push(row);
      }
      if(page.next_after===null)break;
      if(page.next_after!==page.items.at(-1)?.id||after!==null&&BigInt(page.next_after)>=BigInt(after))throw Error('Invalid Chronicle cursor.');
      after=page.next_after;
      if(current!==epoch||signal.aborted||stopped)throw Error('Stale Chronicle.');
      page=validateChronicle(await publicRequest('/api/public/guitars/'+id+'/chronicle?'+new URLSearchParams({after,limit:'25'}),signal));
    }while(true);
    return {items,next_after:null};
  }
  function closePhoto(){globalThis.YGCImageAlbum?.close()}
  function clearDetail(){
    closePhoto();photoEpoch++;const photo=$('detailPhoto');if(photo?.dataset){delete photo.dataset.photoPath;delete photo.dataset.photoReady;delete photo.dataset.photoLoading}if(photoURL)URL.revokeObjectURL(photoURL);photoURL=null;
    favorite.clear();
    detail=null;claims=[];nextAfter=null;moreLoading=false;
    $('detailContent').hidden=true;$('detailTitle').textContent='';$('detailIdentifier').textContent='';
    $('detailSpecifications').replaceChildren();$('chronicleEntries').replaceChildren();$('chronicleStatus').textContent='';
    $('acquireLink').href=$('addClaimLink').href=$('ownershipLink').href=accountPath;$('chronicleMore').hidden=true;
  }
  function renderStatic(){
    const labels={catalogTitle:'title',catalogEyebrow:'eyebrow',catalogDescription:'description',listHeading:'list',detailHeading:'detail',accountLink:'account',languageLabel:'language',searchLabel:'search',sortLabel:'sort',catalogSearchSubmit:'submit',catalogRefresh:'refresh',catalogPrevious:'previous',catalogNext:'next',catalogBack:'back',photoPlaceholder:'photo',specificationHeading:'specification',chronicleHeading:'chronicle',chronicleOrder:'chronicle_order',acquireLink:'acquire',acquireDescription:'acquire_help',addClaimLink:'add_claim',addClaimDescription:'add_claim_help',ownershipLink:'ownership_action',ownershipDescription:'ownership_help',catalogFooter:'footer'};
    for(const [id,key] of Object.entries(labels))if($(id))$(id).textContent=t(key);
    if(formal){
      $('listHeading').textContent=globalThis.YGCI18n?.t('ui.product_list_a7042f80')||'Product List';
      $('catalogBack').textContent='×';$('acquireLink').textContent=globalThis.YGCI18n?.t('ui.if_you_are_the_rightful_owner_of_this_you_can_claim_it_by__b007f520')||t('acquire');
    }
    document.documentElement.lang=locale;document.title='Your Guitar Chronicle — '+t('list');
    $('catalogSearch').placeholder=formal?(globalThis.YGCI18n?.t('ui.maker_model_finish_year_serial_c99806fd')||'maker / model / finish / year / serial'):t('placeholder');$('catalogLanguage').value=locale;$('catalogLanguage').setAttribute('aria-label',t('language'));
    $('detailPhoto')?.setAttribute('aria-label',t('photo')); $('catalogPagination').setAttribute('aria-label',t('pages_label'));
    document.querySelector('.page-nav').setAttribute('aria-label',t('nav_label'));
    $('catalogSort').replaceChildren();for(const value of [...sorts,...(formal?formalSorts:[])]){const option=node('option',t(value));option.value=value;$('catalogSort').append(option)}
    if(route)$('catalogSort').value=route.sort;
  }
  function controls(){
    favorite.render();
    if(formal)$('listHeading').dataset.countPending=String(!list);
    if(formal){$('acquireLink').hidden=authBlocked!==null||Boolean(detail?.presentation?.owner);$('ownershipLink').hidden=true;}
    $('catalogLayout').dataset.detailOpen=String(Boolean((route?.id||route?.invalid)&&!compactDismissed));
    $('catalogRows').setAttribute('aria-busy',String(loading));$('catalogDetail').setAttribute('aria-busy',String(loading||moreLoading));
    $('catalogRefresh').disabled=loading;$('catalogPrevious').disabled=loading||!list||route.page<=1;
    $('catalogNext').disabled=loading||!list||route.page>=list.total_pages||route.page>=1000000;
    $('catalogPage').textContent=list?t('page',{page:list.page,pages:Math.max(list.total_pages,1)}):'';
    $('catalogStatus').textContent=listMessage?t(listMessage):list?t(list.items.length?'count':'empty',{count:list.total}):'';
    if(formal){$('catalogPagination').hidden=true;$('catalogRefresh').hidden=false;$('catalogStatus').hidden=!listMessage}
    $('detailStatus').textContent=detailMessage?t(detailMessage):'';$('detailStatus').hidden=!detailMessage;
    $('catalogBack').hidden=!route?.id&&!route?.invalid;
    if(route){intercept($('catalogBack'),routeURL({...route,id:null,invalid:false}));if(formal)$('catalogBack').onclick=event=>{event.preventDefault();closeDetail()}}
    $('chronicleMore').hidden=!detail||nextAfter===null;$('chronicleMore').disabled=loading||moreLoading;
    $('chronicleMore').textContent=t(moreLoading?'loading_more':'more');
    $('authNotice').hidden=!authNotice;$('authNotice').textContent=authNotice?t(authNotice):'';
    const serviceText=serviceFailed?t('service_unknown'):service&&service.mode!=='normal'?t(service.mode)+(service.message?'\n'+service.message:''):'';
    $('serviceNotice').hidden=!serviceText;$('serviceNotice').textContent=serviceText;
    if(formal&&document.querySelectorAll)for(const th of document.querySelectorAll('#catalogList th[data-sort-field]')){
      const field=th.dataset.sortField,ascending=field==='id'?route?.sort==='oldest':route?.sort===field+'_asc',descending=field==='id'?route?.sort==='newest':route?.sort===field+'_desc';
      th.setAttribute('aria-sort',ascending?'ascending':descending?'descending':'none');
      th.querySelector('.sort-indicator').textContent=ascending?'▲':descending?'▼':'';
    }
    onState({auth,locale,serviceMode:service?.mode||null,selectedId:route?.id||null,blocked:Boolean(authBlocked),blockCode:authBlocked?.code||null,authPending:authRestoring,loading,readRevision,detailOpen:Boolean((route?.id||route?.invalid)&&!compactDismissed)});
  }
  function renderList(){
    $('catalogRows').replaceChildren();if(!list)return;
    for(const row of list.items){
      if(listStyle==='table'){
        const tr=node('tr',undefined,'clickable'+(row.id===route.id?' selected':''));
        const id=node('td'),link=node('a',row.id);
        link.setAttribute('aria-label',t('view')+' · '+t('identifier',{id:row.id}));
        intercept(link,routeURL({...route,id:row.id}));id.append(link);tr.append(id);
        if(formal){
          const cell=node('td',undefined,'favorite-cell');let item=rowFavorites.get(row.id);
          if(!item){const root=node('span'),control=createFavoriteControl({auth:()=>auth,state:()=>auth?.account,root,compact:true,idPrefix:'catalog_'+row.id+'_',document,t,canWrite:()=>service?.mode!=='read_only'&&service?.mode!=='offline'});item={root,control};rowFavorites.set(row.id,item);void control.select(row.id,readRowFavorite).catch(()=>{})}
          cell.append(item.root);tr.append(cell);
        }
        for(const field of fixedFields)tr.append(node('td',formal?(row[field]??''):valueText(row[field]),field==='serial_number'?'mono':undefined));
        if(formal)tr.append(node('td',row.claim_count??''));
        tr.onclick=event=>{if(event.target?.closest('a,button,input,select')||event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;navigate(routeURL({...route,id:row.id}),true)};
        $('catalogRows').append(tr);continue;
      }
      const card=node('li',undefined,'guitar-card'+(row.id===route.id?' is-selected':''));
      card.append(node('h3',[row.manufacturer,row.model].filter(Boolean).join(' ')||t('identifier',{id:row.id})));
      const facts=node('p',undefined,'guitar-facts');
      for(const field of ['finish','year','serial_number'])facts.append(node('span',t(field)+': '+valueText(row[field])));
      const link=node('a',t('view'),'guitar-detail-link');link.setAttribute('aria-label',t('view')+' · '+t('identifier',{id:row.id}));
      intercept(link,routeURL({...route,id:row.id}));card.append(facts,link);$('catalogRows').append(card);
    }
    if(formal)globalThis.YGCProfileList?.sizeGuitarList($('catalogList'),Number(unfilteredTotal??list.total));
  }
  function fieldLabel(field){return messages[locale][field]??field}
  function appendClaimPresentation(card,row){
    const p=row.presentation;if(!p||typeof p!=='object')return;
    if(typeof p.body==='string'&&p.body){const body=node('div',p.body,'claim-body');body.style.whiteSpace='pre-wrap';card.append(body)}
    const footer=node('div',undefined,'claim-footer'),meta=node('div',undefined,'claim-footer-meta');
    const count=value=>typeof value==='string'&&/^(0|[1-9][0-9]{0,18})$/.test(value);
    if(count(p.good_count)&&count(p.bad_count)){const votes=node('div',undefined,'claim-votes');votes.append(node('span','👍 '+p.good_count,'claim-vote'),node('span','👎 '+p.bad_count,'claim-vote'));footer.append(votes)}
    const created=new Date(row.created_at);if(Number.isFinite(created.getTime()))meta.append(node('span',created.toLocaleString(locale)+' · '));
    if(p.author&&validId(p.author.id)&&typeof p.author.display_name==='string'){const author=node('a',p.author.display_name,'claim-author');author.href='/ui/members/'+p.author.id;meta.append(author)}
    footer.append(meta);card.append(footer);
  }
  function renderChronicle(){
    $('chronicleEntries').replaceChildren();
    for(const row of formal&&globalThis.YGCProductDetail?globalThis.YGCProductDetail.orderedClaims(claims):claims){
      const type=fieldLabel(row.claim_type==='specification'?'specification_claim':row.claim_type);
      const name=formal&&row.ownership_kind?fieldLabel(row.ownership_kind==='acquire'?'acquire_kind':row.ownership_kind):type+(row.ownership_kind?' / '+fieldLabel(row.ownership_kind==='acquire'?'acquire_kind':row.ownership_kind):'');
      const meta='#'+row.id+' · '+valueText(row.occurred_at||row.created_at)+' · '+t(row.verification_status);
      if(row.verification_status!=='positive'){
        // Non-positive Claims are public tags/points only, even if an API adds fields.
        const card=node('div',undefined,formal?'claim-compact-row':'chronicle-record '+row.verification_status),tag=node(formal?'button':'span',row.verification_status==='negative'?(formal?'◉':'●'):name,formal?(row.verification_status==='negative'?'claim-negative-dot':'claim-compact-tag claim-type-'+row.claim_type):'');
        if(formal){tag.type='button';tag.onclick=()=>{
          if(!auth?.account?.user||authBlocked){$('shellSignIn')?.click();return}
          const popup=document.getElementById('formalClaimTemplates').content.querySelector('#claimPopupModal').cloneNode(true),card=node('div',undefined,'claim-card claim-type-'+row.claim_type),head=node('div',undefined,'claim-head');
          head.append(node('span',name,'claim-badge'),node('span',globalThis.YGCOwnershipPresentation.displayEventDate(row.occurred_at),'claim-event-date'));card.append(head);
          // The public tag DTO grants no body, author, votes or private photos.
          // Match the canonical popup shell without inventing those fields.
          appendClaimPresentation(card,row);popup.querySelector('#claimPopupContent').append(card);document.body.append(popup);globalThis.YGCOverlays.open(popup,{opener:tag,onClose:()=>popup.remove()});globalThis.YGCOwnershipPresentation.positionClaimPopup(tag);onClaimPopup(card,row.id,detail.id);
        }}
        if(formal)card.dataset.claimId=row.id;tag.title=name+' · '+meta;tag.setAttribute('aria-label',name+' · '+meta);card.append(tag);$('chronicleEntries').append(card);continue;
      }
      const card=node(formal?'div':'details',undefined,formal?'claim-card'+(['ownership','specification','incident','event','media'].includes(row.claim_type)?' claim-type-'+row.claim_type:''):'chronicle-record positive');card.open=true;
      if(formal){card.dataset.claimId=row.id;const head=node('div',undefined,'claim-head');head.append(node('span',name,'claim-badge'),node('span',globalThis.YGCOwnershipPresentation.displayEventDate(row.occurred_at),'claim-event-date'));card.append(head)}else card.append(node('summary',name),node('p',meta));
      const values=node(formal?'div':'dl',undefined,formal?'claim-body':'');for(const item of row.items){if(formal){const line=node('div'),strong=node('strong',fieldLabel(item.field_name)+': '+item.value_text);line.append(strong);values.append(line)}else values.append(node('dt',fieldLabel(item.field_name)),node('dd',item.value_text))}card.append(values);
      const source=safeSource(row.source_url);if(source){const link=node('a',t('source'));link.href=source;link.target='_blank';link.rel='noopener noreferrer';card.append(link)}
      appendClaimPresentation(card,row);$('chronicleEntries').append(card);
    }
    $('chronicleStatus').textContent=t(claims.length?'chronicle_count':'chronicle_empty',{count:claims.length});if(formal)onChronicle($('chronicleEntries'),detail.id);
  }
  async function loadPublicPhoto(){
    const id=detail?.id,path=detail?.public_photo,target=$('detailPhoto'),version=++photoEpoch,owner=auth?.account?.user?.app_user_id;
    if(target?.dataset.photoPath===path&&target.dataset.photoOwner===String(owner??'')&&(target.dataset.photoLoading==='true'||target.dataset.photoReady==='true')){photoEpoch--;return}
    if(photoURL)URL.revokeObjectURL(photoURL);photoURL=null;
    if(!target)return;
    const fallback=()=>{delete target.dataset.photoLoading;delete target.dataset.photoReady;target.src='/assets/no-picture.svg'};
    if(path){target.dataset.photoPath=path;target.dataset.photoOwner=String(owner??'');target.dataset.photoLoading='true';target.removeAttribute('src')}
    target.onload=()=>{if(version!==photoEpoch)return;delete target.dataset.photoLoading;target.dataset.photoReady='true'};
    if(typeof path==='string'&&path.startsWith('https://')){
      try{const url=new URL(path);if(!['images.reverb.com','photos.reverb.com','rvb-img.reverb.com'].includes(url.hostname)||url.username||url.password||url.hash||url.port&&url.port!=='443'){fallback();return}
        target.referrerPolicy='no-referrer';target.onerror=()=>{target.onerror=null;fallback()};target.src=path;
      }catch{fallback()}return;
    }
    if(path!=='/api/public/guitars/'+id+'/photo'){fallback();return;}
    const current=()=>version===photoEpoch&&!stopped&&detail?.id===id&&auth?.account?.user?.app_user_id===owner&&!authBlocked&&$('detailPhoto')===target;
    try{const options={cache:'no-cache',credentials:'omit',redirect:'error',signal:controller?.signal};const response=auth?.signedIn?await auth.authorizedFetch(path,options):await request(path,options);
      if(!current())return;if(!response.ok||response.headers.get('content-type')?.split(';')[0]!=='image/jpeg'){fallback();return}
      const blob=await response.blob();if(!current())return;if(!blob.size||blob.size>25*1024*1024){fallback();return}
      photoURL=URL.createObjectURL(blob);target.src=photoURL;
    }catch{if(current())fallback()}
  }
  function renderSharedDetail(){
    const shared=globalThis.YGCProductDetail;
    if(!formal||!shared)return;closePhoto();
    const keep=Object.fromEntries(['detailFavorite','acquireLink','addClaimLink','ownershipLink','chronicleStatus','chronicleMore'].map(id=>[id,$(id)]));
    const previousPhoto=$('detailPhoto');
    const collapsed=['specificationAccordion','chronicleAccordion'].filter(id=>$(id)?.classList.contains('collapsed'));
    const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    // Only explicit public presentation fields are rendered; Evidence is never used.
    // Do not infer them, fetch local APIs, or turn a private image into a public one.
    $('detailContent').innerHTML=shared.render({individual:detail,specifications:detail.specifications,
      image:'<img id="detailPhoto" class="detail-image" '+(detail.public_photo?'data-photo-loading="true"':'src="/assets/no-picture.svg"')+' alt="'+escape(t('photo'))+'">',
      owner:detail.presentation?.owner&&validId(detail.presentation.owner.id)?'<a href="/ui/members/'+detail.presentation.owner.id+'">'+escape(detail.presentation.owner.display_name)+'</a>':escape(detail.presentation?.source_owner_name||'—'),location:escape(detail.presentation?.location||'—'),fieldLabel,escape});
    if(previousPhoto?.tagName==='IMG'&&previousPhoto.dataset.guitarId===detail.id)$('detailPhoto').replaceWith(previousPhoto);
    const photo=$('detailPhoto');photo.dataset.guitarId=detail.id;photo.alt=[detail.manufacturer,detail.model].filter(Boolean).join(' ');photo.setAttribute('role','button');photo.tabIndex=0;// The shared image album handles click and keyboard activation.
    const caption=node('span',globalThis.YGCI18n.t(detail.public_photo?'ui.representative_image_c23db047':'ui.no_picture_b2e8e688'),'detail-source');photo.after(caption);
    const title=$('detailContent').querySelector('.detail-header-title');title.id='detailTitle';
    const identifier=node('span',undefined,'sub');identifier.id='detailIdentifier';identifier.hidden=true;title.after(identifier);
    $('detailContent').querySelector('.catalog-spec').id='detailSpecifications';
    const ownerAction=keep.acquireLink;ownerAction.className='owner-claim-card';if(onAcquire)ownerAction.onclick=event=>{if(authBlocked)return;event.preventDefault();void onAcquire(detail.id)};
    const claimAction=keep.addClaimLink;claimAction.className='add-claim-action';claimAction.textContent=globalThis.YGCI18n?.t('claim.add')||"Let's add your Claim !!";
    $('detailContent').querySelector('.detail-title-row').append(keep.detailFavorite);
    $('detailContent').querySelector('.detail-header').append(ownerAction,keep.ownershipLink);
    const toolbar=node('div',undefined,'chronicle-toolbar'),menu=node('div',undefined,'claim-menu-wrap');menu.append(claimAction);
    if(onClaim){
      const options=node('div',undefined,'claim-menu');options.id='addClaimMenu';
      for(const [type,key] of [['specification','ui.specification_repair_66e4d9a7'],['incident','ui.incident_36a606d4'],['event','ui.event_4e1f49a9'],['media','ui.media_d357175c']]){
        const option=node('button',globalThis.YGCI18n.t(key));option.type='button';option.dataset.claimType=type;option.onclick=event=>{event.preventDefault();options.classList.remove('open');void onClaim(detail.id,type)};options.append(option);
      }
      const currentOwner=detail.presentation?.owner?.id;
      if(validId(currentOwner)){
        const ownership=node('button',globalThis.YGCI18n.t('ui.ownership_c7d3acc8'));ownership.type='button';ownership.dataset.catalogOwnership='';
        ownership.onclick=event=>{event.preventDefault();if(!auth?.account?.user||authBlocked)return;options.classList.remove('open');
          if(String(auth.account.user.id)===currentOwner){if(onOwnership)void onOwnership(detail.id);else window.location.assign(accountPath+'?ownership='+encodeURIComponent(detail.id))}
          else void onAcquire?.(detail.id);
        };options.prepend(ownership);
      }
      claimAction.onclick=event=>{if(authBlocked)return;event.preventDefault();event.stopPropagation();if(!auth?.account?.user){void onClaim(detail.id,'specification');return}options.classList.toggle('open')};menu.append(options);
    }
    toolbar.append(menu);
    $('chronicleAccordion').querySelector('.accordion-body').prepend(toolbar,keep.chronicleStatus);
    $('chronicleAccordion').querySelector('.accordion-body').append(keep.chronicleMore);
    for(const id of collapsed)$(id).classList.add('collapsed');
    // Bind the shared triangle/title controls without relying on a page-owned global.
    for(const section of $('detailContent').querySelectorAll('.accordion-section')){
      for(const control of section.querySelectorAll('.accordion-title,.accordion-toggle')){
        control.removeAttribute('onclick');control.onclick=()=>shared.toggleAccordion(section.id);
      }
    }
  }
  function renderDetail({chroniclePending=false}={}){
    if(!detail)return;
    renderSharedDetail();
    $('detailContent').hidden=false;$('detailTitle').textContent=[detail.manufacturer,detail.model].filter(Boolean).join(' ')||t('identifier',{id:detail.id});
    $('detailIdentifier').textContent=t('identifier',{id:detail.id});$('acquireLink').href=accountPath+'?acquire='+encodeURIComponent(detail.id);$('addClaimLink').href=accountPath+'?claim='+encodeURIComponent(detail.id);$('ownershipLink').href=accountPath+'?ownership='+encodeURIComponent(detail.id);
    if(!formal||!globalThis.YGCProductDetail){
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
    }
    if(chroniclePending){$('chronicleEntries').replaceChildren();$('chronicleStatus').textContent=t('loading_more')}else renderChronicle();if(formal)void loadPublicPhoto();
  }
  async function checkService(current,signal){
    try{
      const data=await json(await request('/api/service/status',{method:'GET',cache:'no-store',credentials:'omit',redirect:'error',signal}));
      if(!data||!['normal','read_only','offline','admin_only'].includes(data.mode)||typeof data.message!=='string')throw Error('Invalid service state.');
      if(current!==epoch||stopped)return;service=data;serviceFailed=false;
    }catch{if(current!==epoch||stopped)return;service=null;serviceFailed=true}
    controls();
  }
  function loadRoute(next,{retryAuth=false,focus=false,preserveView=false}={}){
    if(stopped)return Promise.resolve();
    if(retryAuth||!authReady)authRestoring=true;
    const current=++epoch;controller?.abort();moreController?.abort();controller=new AbortController();const signal=controller.signal;
    const sameList=route&&route.q===next.q&&route.sort===next.sort&&route.page===next.page;
    if(route?.id!==next.id&&formal&&globalThis.YGCProductDetail)for(const id of ['specificationAccordion','chronicleAccordion'])$(id)?.classList.remove('collapsed');
    const retainedList=sameList&&!retryAuth&&!preserveView&&next.id?list:null;
    const retainedDetail=!sameList&&!retryAuth&&!preserveView&&detail?.id===next.id?[detail,{items:claims,next_after:nextAfter}]:null;
    const keepView=preserveView&&sameList&&detail?.id===next.id&&!authBlocked;
    route=next;if(!retainedDetail&&!keepView)clearDetail();loading=true;listMessage=retainedList||keepView?'':'loading';detailMessage=retainedDetail||keepView?'':next.id?'loading_detail':next.invalid?'missing':'choose';
    $('catalogSearch').value=route.q;$('catalogSort').value=route.sort;if(!keepView)renderList();controls();
    pending=(async()=>{
      const serviceCheck=checkService(current,signal);
      await initializeAuth(retryAuth);
      if(current!==epoch||stopped)return;
      controls();
      let earlyDetail=null;
      const detailWork=retainedDetail?Promise.resolve(retainedDetail):route.id?Promise.all([
        publicRequest('/api/public/guitars/'+route.id,signal).then(async row=>{
          validateGuitar(row);validateItems(row.specifications);if(row.id!==next.id)throw Error('Unexpected guitar.');
          await serviceCheck;
          if(!keepView&&current===epoch&&!stopped&&!serviceFailed&&service?.mode!=='offline'&&!(service?.mode==='admin_only'&&auth?.account?.user?.role!=='admin')){
            // Detail and its representative image do not wait for Chronicle or
            // the remaining catalog pages. Keep this DOM when Chronicle arrives.
            detail=earlyDetail=row;detailMessage='';renderDetail({chroniclePending:true});controls();
          }
          return row;
        }),
        loadChronicle(route.id,signal,current),
      ]):Promise.resolve(null);
      const listWork=detailOnly?Promise.resolve({items:[],total:'0',page:next.page,page_size:24,total_pages:0}):keepView&&list?detailWork.then(([row])=>{
        const before=list.items.find(item=>item.id===row.id);
        // A verification-only change with the same public table projection
        // cannot change this row's filter, order or count. Keep the full list.
        return before&&[...fixedFields,'claim_count'].every(field=>before[field]===row[field])?list:loadList(next,signal,current);
      }):retainedList?Promise.resolve(retainedList):loadList(next,signal,current);
      const results=await Promise.allSettled([listWork,detailWork]);
      await serviceCheck;
      if(current!==epoch||stopped)return;
      const fatal=results.find(result=>result.status==='rejected'&&([401,403,503].includes(result.reason.status)||result.reason===authBlocked));
      const restricted=service?.mode==='offline'||service?.mode==='admin_only'&&auth?.account?.user?.role!=='admin';
      const sameRows=keepView&&!fatal&&!restricted&&results[0].status==='fulfilled'&&results[0].value===list;
      if(fatal||restricted){clearRowFavorites();unfilteredTotal=null;list=null;clearDetail();listMessage=restricted?'restricted':errorKey(fatal.reason);detailMessage=route.id?listMessage:route.invalid?'missing':'choose'}
      else{
        if(results[0].status==='fulfilled'){list=results[0].value;listMessage=''}else{list=null;listMessage=errorKey(results[0].reason)}
        if(route.id){
          if(results[1].status==='fulfilled'){
            [detail,{items:claims,next_after:nextAfter}]=results[1].value;detailMessage='';if(!retainedDetail){if(detail===earlyDetail)renderChronicle();else renderDetail();void favorite.select(detail.id);}
          }else{clearDetail();detailMessage=errorKey(results[1].reason)}
        }
      }
      if(!sameRows)renderList();loading=false;if(preserveView)readRevision++;controls();
      if(focus&&route.id)$('detailHeading').focus();
      await serviceCheck;
    })().catch(error=>{
      if(current!==epoch||stopped)return;
      list=null;clearDetail();loading=false;listMessage=errorKey(error);detailMessage=route.id?listMessage:'choose';renderList();controls();
    });
    return pending;
  }
  function selectInitial(id){
    // Only hydrate the untouched Top Page. Keep /ui so a full reload draws
    // again, while explicit links and early user navigation keep their choice.
    if(basePath!=='/ui'||epoch!==1||stopped||authBlocked||serviceFailed||route?.id||route?.invalid||!list||!id||!/^[1-9][0-9]{0,18}$/.test(id))return Promise.resolve();
    initialDetailId=id;
    return loadRoute({...route,id});
  }
  function closeDetail(){compactDismissed=true;controls()}
  function navigate(target,focus=false){
    compactDismissed=false;
    const url=new URL(target,window.location.href);if(url.origin!==window.location.origin)return Promise.resolve();
    const next=readRoute(url);if(next.invalid)return Promise.resolve();const canonical=routeURL(next);
    if(canonical===window.location.pathname+window.location.search)return loading?pending:loadRoute(next,{focus});
    window.history.pushState({ygcPublicCatalog:true},'',canonical);return loadRoute(next,{focus});
  }
  function refresh({reuseUserData=false,preserveView=false}={}){if(loading)return pending;if(!reuseUserData)auth?.invalidateUserData?.();return loadRoute(readRoute(),{retryAuth:!preserveView,preserveView})}
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
  function onPopstate(){
    const next=readRoute();
    // Native section anchors also emit popstate. They only scroll the page;
    // restoring authentication and erasing the graphs here disrupts the jump.
    if(typeof window.location.hash==='string'&&route&&routeURL(next)===routeURL(route))return;
    compactDismissed=false;return loadRoute(next);
  }
  function setLanguage(){
    locale=$('catalogLanguage').value==='ja'?'ja':'en';try{window.localStorage.setItem('ygc_ui_language',locale)}catch{/* Keep the change for this page. */}
    if(formal&&window.location.reload){window.location.reload();return}
    renderStatic();renderList();renderDetail();controls();
  }
  function invalidateIdentity(error){
    ++readRevision;authRestoring=false;
    clearRowFavorites();unfilteredTotal=null;
    ++epoch;controller?.abort();moreController?.abort();authReady=null;
    authBlocked=error&&error.status?error:Object.assign(Error('Identity changed. Refresh to continue.'),{code:'sign_in_required'});
    const message=errorKey(authBlocked);
    list=null;clearDetail();loading=false;listMessage=message;authNotice=message==='session'?message:'';detailMessage='choose';renderList();controls();
    if(message!=='session')void checkService(epoch);
  }
  function onPageHide(){clearRowFavorites();unfilteredTotal=null;window.clearTimeout?.(searchTimer);++epoch;controller?.abort();moreController?.abort();list=null;clearDetail();loading=false;listMessage='loading';renderList();controls()}
  function onPageShow(event){if(event.persisted){loading=false;return refresh({reuseUserData:true})}}
  function start(){
    renderStatic();
    $('catalogSearchForm').onsubmit=event=>{event.preventDefault();window.clearTimeout?.(searchTimer);return navigate(routeURL({q:[...$('catalogSearch').value.trim()].slice(0,120).join(''),sort:$('catalogSort').value,page:1,id:formal?route?.id:null}))};
    $('catalogSort').onchange=()=>navigate(routeURL({q:$('catalogSearch').value.trim(),sort:$('catalogSort').value,page:1,id:formal?route?.id:null}));
    if(formal&&document.querySelectorAll){
      // Keep the same input control and transport, but use the local live-filter gesture.
      $('catalogSearch').oninput=()=>{window.clearTimeout(searchTimer);searchTimer=window.setTimeout(()=>{
        if(!stopped){const raw=$('catalogSearch').value;void navigate(routeURL({q:raw.trim(),sort:route.sort,page:1,id:route.id}));$('catalogSearch').value=raw;}
      },150)};
      for(const th of document.querySelectorAll('#catalogList th[data-sort-field]')){
        th.classList.add('sortable');th.tabIndex=0;
        const sort=()=>{const field=th.dataset.sortField,current=route.sort;
          const next=field==='id'?(current==='newest'?'oldest':'newest'):(current===field+'_asc'?field+'_desc':field+'_asc');
          void navigate(routeURL({...route,sort:next,page:1}));
          $('catalogList').querySelector('.table-wrap').scrollTop=0;
        };
        th.onclick=event=>{if(!event.target.closest('.column-resize-handle'))sort()};
        th.onkeydown=event=>{if(event.target!==th||!['Enter',' '].includes(event.key))return;event.preventDefault();sort()};
      }
    }
    if(formal)document.addEventListener?.('click',event=>{if(!event.target?.closest('.claim-menu-wrap'))$('addClaimMenu')?.classList.remove('open')});
    $('catalogRefresh').onclick=refresh;
    $('catalogPrevious').onclick=()=>{if(!loading&&list&&route.page>1)return navigate(routeURL({...route,page:route.page-1,id:null}))};
    $('catalogNext').onclick=()=>{if(!loading&&list&&route.page<list.total_pages&&route.page<1000000)return navigate(routeURL({...route,page:route.page+1,id:null}))};
    $('chronicleMore').onclick=more;$('catalogLanguage').onchange=setLanguage;window.addEventListener('popstate',onPopstate);window.addEventListener('pagehide',onPageHide);window.addEventListener('pageshow',onPageShow);
    const ready=loadRoute(readRoute());
    // Route hydration has populated the fields and every handler is installed.
    for(const id of ['catalogSearch','catalogSort','catalogSearchSubmit'])$(id).disabled=false;
    return ready;
  }
  function destroy(){clearRowFavorites();window.clearTimeout?.(searchTimer);stopped=true;++epoch;controller?.abort();moreController?.abort();window.removeEventListener('popstate',onPopstate);window.removeEventListener('pagehide',onPageHide);window.removeEventListener('pageshow',onPageShow);unsubscribeIdentity?.();favorite.clear()}
  return {start,refresh,navigate,selectInitial,select:id=>navigate(routeURL({...route,id}),true),closeDetail,destroy,invalidateIdentity,read:publicRequest};
}

// Readiness is for the disposable browser checks; it does not expose identity.
if(document.body.dataset.catalogAutostart!=='false'){
  let client,dialog;
  const catalog=createPublicCatalog({onState:state=>{client=state.auth},onAcquire:id=>continueMember(id,'acquire'),onClaim:id=>continueMember(id,'claim')});
  await catalog.start();
  dialog=createAuthDialog({auth:()=>client,onAuthenticated:()=>catalog.refresh()});
  function continueMember(id,kind){const target='/account?'+kind+'='+id;if(client?.account?.identity?.email_verified===true)location.assign(target);else dialog.open({verificationPath:target,onSuccess:()=>location.assign(target)})}
  document.getElementById('accountLink').onclick=event=>{if(!client?.account?.user){event.preventDefault();dialog.open({opener:event.currentTarget})}};
  globalThis.YGCCloudPublicCatalogReady=true;
}
