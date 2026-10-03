// Tab-local dummy sessions. Only localhost with server-enabled local_dummy mode.
(() => {
  const originalFetch=window.fetch.bind(window);
  const key='ygc_local_auth';
  let backend;
  async function mode(){
    if(!backend)backend=originalFetch('/api/local-auth').then(r=>r.json());
    return (await backend).backend;
  }
  let pending=Promise.resolve();
  function accessIssue(message){sessionStorage.setItem('ygc_account_access_issue',message);window.dispatchEvent(new Event('ygc-account-access'))}
  function saveSession(result){
    sessionStorage.removeItem('ygc_account_access_issue');window.dispatchEvent(new Event('ygc-account-access'));
    const session={user_id:result.user_id,app_user_id:result.app_user_id,provider:result.provider,
      localId:result.localId||result.subject,idToken:result.idToken||result.token,
      expiresIn:String(result.expiresIn||3600),refreshToken:result.refreshToken||null,
      displayName:result.displayName||'',registered:result.registered===true,
      capabilities:result.capabilities||{refresh:false}};
    // Compatibility alias for the existing local bearer adapter.
    session.token=session.idToken;
    sessionStorage.setItem(key,JSON.stringify(session));
    sessionStorage.setItem('ygc_active_user_id',String(session.user_id));
    return session;
  }
  const adapters={local_dummy:{async signIn(_credentials,options={}){
    const hint=Number(options.testUserId||sessionStorage.getItem('ygc_last_user_id')||0);
    const response=await originalFetch('/api/local-auth/sign-in',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(hint?{user_id:hint}:{})});
    const result=await response.json();
    if(!response.ok)throw Error(globalThis.YGCI18n?.errorMessage(result,"Sign in failed.")??(result.detail||(globalThis.YGCI18n?.t("ui.sign_in_failed_26739f00",{},"Sign in failed.")??"Sign in failed.")));
    return result;
  }}};
  const auth={async register(profile){
    await pending.catch(()=>{});
    if(await mode()!=='local_dummy')throw Error((globalThis.YGCI18n?.t("ui.local_dummy_registration_is_disabled_7cce6922",{},"Local dummy registration is disabled.")??"Local dummy registration is disabled."));
    const response=await originalFetch('/api/local-auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(profile)});
    const result=await response.json();
    if(!response.ok)throw Error(globalThis.YGCI18n?.errorMessage(result,"Registration failed.")??(result.detail||(globalThis.YGCI18n?.t("ui.registration_failed_a4e72985",{},"Registration failed.")??"Registration failed.")));
    return saveSession(result);
  },async signIn(credentials,options={}){
    await pending.catch(()=>{});
    const adapter=adapters[await mode()];
    if(!adapter)throw Error('Start the server with local_dummy identity mode to use test sign-in.');
    return saveSession(await adapter.signIn(credentials,options));
  },async logout(){
    await pending.catch(()=>{});
    const session=JSON.parse(sessionStorage.getItem(key)||'null');
    if(session?.token){
      const response=await originalFetch('/api/local-auth/logout',{method:'POST',headers:{Authorization:'Bearer '+session.token}});
      if(!response.ok)throw Error((globalThis.YGCI18n?.t("ui.could_not_log_out_please_try_again_47d534f4",{},"Could not log out. Please try again.")??"Could not log out. Please try again."));
    }
    const id=sessionStorage.getItem('ygc_active_user_id');
    if(id)sessionStorage.setItem('ygc_last_user_id',id);
    sessionStorage.removeItem(key);
    sessionStorage.removeItem('ygc_account_access_issue');
    sessionStorage.removeItem('ygc_active_user_id');
    localStorage.removeItem('ygc_active_user_id');
    location.assign('/user-view?prototype_user_id=');
  }};
  window.YGCAuth=auth;
  window.YGCLocalAuth=auth;
  async function ensure(){
    if(await mode()!=='local_dummy')return;
    const id=Number(sessionStorage.getItem('ygc_active_user_id')||0);
    let session=JSON.parse(sessionStorage.getItem(key)||'null');
    if(session?.user_id===id)return;
    if(session?.token)await originalFetch('/api/local-auth/logout',{method:'POST',headers:{Authorization:'Bearer '+session.token}});
    sessionStorage.removeItem(key);
    if(!id)return;
    const response=await originalFetch('/api/local-auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:id})});
    const data=await response.json();
    if(!response.ok){if(response.status===401||response.status===403){accessIssue(data.detail||(globalThis.YGCI18n?.t("ui.account_access_is_unavailable_e2101277",{},"Account access is unavailable.")??"Account access is unavailable."));sessionStorage.removeItem('ygc_active_user_id')}throw Error(data.detail||(globalThis.YGCI18n?.t("ui.local_login_failed_2e997021",{},"Local login failed.")??"Local login failed."))}
    saveSession(data);
  }
  window.fetch=async function(input,options={}){
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/api/')||url.pathname.startsWith('/api/local-auth'))return originalFetch(input,options);
    if(url.pathname==='/api/users'||url.pathname==='/api/service-notice')return originalFetch(input,options); // Local test-user selector / registration.
    // Console requests already carry a distinct operator credential.
    const headers=new Headers(options.headers||{});
    if(!headers.has('X-YGC-Console-Admin')){
      pending=pending.catch(()=>{}).then(ensure);await pending;
      const session=JSON.parse(sessionStorage.getItem(key)||'null');
      if(session?.token)headers.set('Authorization','Bearer '+session.token);
    }
    const response=await originalFetch(input,{...options,headers});
    if(response.status===401){sessionStorage.removeItem(key);const data=await response.clone().json().catch(()=>({}));accessIssue(data.detail||(globalThis.YGCI18n?.t("ui.your_session_has_expired_please_sign_in_again_b529fce2",{},"Your session has expired. Please sign in again.")??"Your session has expired. Please sign in again."))}
    return response;
  };
  // Image tags cannot attach Authorization; load private API images via fetch.
  const images=new WeakMap();
  async function loadImage(img){
    const src=img.getAttribute('src');
    if(!src?.startsWith('/api/')||images.get(img)===src||await mode()!=='local_dummy')return;
    images.set(img,src);
    try{
      const response=await window.fetch(src);
      if(!response.ok)return;
      const object=URL.createObjectURL(await response.blob());
      if(images.get(img)!==src){URL.revokeObjectURL(object);return}
      img.onload=()=>URL.revokeObjectURL(object);img.src=object;
    }catch{}
  }
  new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='attributes')loadImage(record.target);
      for(const node of record.addedNodes||[]){if(node.nodeType!==1)continue;if(node.matches('img'))loadImage(node);node.querySelectorAll('img').forEach(loadImage)}
    }
  }).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src']});
})();
