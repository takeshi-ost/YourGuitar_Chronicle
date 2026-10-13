// Google credentials go only to the official SDK. API calls carry an ID token.
(() => {
  function create({sdk, auth, fetch: request=globalThis.fetch.bind(globalThis), origin=location.origin,storage,now=()=>Date.now()}){
    let initialization, account=null, accountUser=null, pending=Promise.resolve();
    let observedUser=auth.currentUser;
    // Display data only: canonical identity and operation permissions never come
    // from this tab-scoped, short-lived cache. Every document restores /me first.
    const storageKey='ygc-self-display-v1';
    try{storage??=globalThis.sessionStorage}catch{/* Storage is optional. */}
    let dataOwner=null,dataEpoch=0,dataWrites=0,entries={},themeOwner=null;
    const dataListeners=new Set();
    globalThis.addEventListener?.('pagehide',()=>{dataEpoch++;dataGate=null});
    const ttl=path=>path==='/api/auth/profile/bootstrap'?15000:path==='/api/auth/settings'?30000:path==='/api/auth/profile/summary'?15000:
      /^\/api\/auth\/(notifications|favorites)(?:\?|$)/.test(path)&&!path.split('?')[0].slice('/api/auth/'.length).includes('/')?10000:0;
    function invalidateUserData(reason='refresh',error=null){
      dataEpoch++;entries={};try{storage?.removeItem(storageKey)}catch{}
      if(reason==='blocked'||reason==='changed')for(const listener of dataListeners){try{listener(reason,error)}catch{}}
    }
    function bindUserData(){
      const user=auth.currentUser,valid=account?.user?.app_user_id&&account.identity?.email_verified===true;
      const owner=valid&&typeof user?.uid==='string'?JSON.stringify([origin,user.uid,auth.tenantId||'',account.user.app_user_id,account.user.role||'',account.user.status||'']):null;
      const themeKnown=globalThis.YGCTheme?.bind(owner);
      if(owner&&globalThis.YGCTheme&&!themeKnown&&themeOwner!==owner){
        themeOwner=owner;
        // A direct Account/Console/Member entry also restores the same display
        // preference. Never authorize an operation from a saved theme.
        Promise.resolve().then(()=>displayRead('/api/auth/settings',{reuseUserData:true},false)).then(async response=>{
          if(response.ok){const data=await response.json();if(dataOwner===owner&&accountUser===auth.currentUser)globalThis.YGCTheme?.remember(data?.fields?.theme)}
        }).catch(()=>{});
      }
      if(owner===dataOwner)return;
      dataOwner=owner;entries={};dataEpoch++;
      try{
        const raw=storage?.getItem(storageKey);if(!raw)return;
        if(raw.length>512*1024)throw Error('Oversize');
        const saved=JSON.parse(raw);if(!owner||saved.owner!==owner||!saved.entries||Array.isArray(saved.entries)||Object.keys(saved.entries).length>64)throw Error('Wrong cache owner');
        for(const [path,row] of Object.entries(saved.entries))if(ttl(path)&&row&&typeof row.body==='string'&&row.body.length<=65536&&Number.isFinite(row.at)&&row.at<=now()&&now()-row.at<ttl(path)){JSON.parse(row.body);entries[path]=row}
      }catch{try{storage?.removeItem(storageKey)}catch{}}
    }
    function saveUserData(){
      if(!dataOwner)return;
      const live=Object.entries(entries).filter(([path,row])=>now()>=row.at&&now()-row.at<ttl(path)).slice(-64);entries=Object.fromEntries(live);
      try{const raw=JSON.stringify({owner:dataOwner,entries});if(raw.length<=512*1024)storage?.setItem(storageKey,raw);else invalidateUserData()}catch{/* Memory reuse still works when storage is unavailable. */}
    }
    async function userDataGate(){
      // Reuse saves expensive private reads, not the service-mode check. Concurrent
      // cache hits share only this in-flight check, never a completed decision.
      const response=await dispatchApi('/api/service/status',{},false);
      if(!response.ok){const data=await response.json().catch(()=>null);throw Object.assign(Error('Service access unavailable.'),{status:response.status,code:data?.code||data?.detail?.code})}
      const status=await response.json();
      if(!['normal','read_only','offline','admin_only'].includes(status?.mode))throw Object.assign(Error('Invalid service status.'),{status:503});
      return status.mode;
    }
    let dataGate=null;
    async function displayRead(path,options,forceRefresh){
      const url=new URL(path,origin),key=url.pathname+url.search;
      const reusable=url.origin===origin&&options.reuseUserData===true&&!forceRefresh&&!options.signal&&!options.body&&(!options.headers||[...new Headers(options.headers)].length===0)&&ttl(key)&&accountUser===auth.currentUser&&dataOwner&&!dataWrites;
      const {reuseUserData,...requestOptions}=options;
      const owner=dataOwner,version=dataEpoch,user=auth.currentUser;
      const current=()=>version===dataEpoch&&owner===dataOwner&&user===auth.currentUser&&accountUser===user&&!dataWrites;
      if(ttl(key)&&!options.reuseUserData){delete entries[key];saveUserData()}
      const row=reusable?entries[key]:null;
      if(row&&row.at<=now()&&now()-row.at<ttl(key)){
        try{
          if(!dataGate){const pending=userDataGate();dataGate=pending;pending.finally(()=>{if(dataGate===pending)dataGate=null}).catch(()=>{})}
          const mode=await dataGate;if(!current()){if(auth.currentUser===user&&owner===dataOwner)throw Object.assign(Error('Display data was refreshed.'),{code:'stale_user_data'});throw changedIdentity()}
          if(mode==='offline'){invalidateUserData('blocked',{status:403,code:'service_restricted'});return new Response(JSON.stringify({detail:{code:'service_restricted',message:'Service access is temporarily restricted.'}}),{status:403,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})}
          if(mode==='normal'||mode==='read_only'){
            // A cached notification DTO must never retain an enabled write
            // control after the service has entered Read Only.
            const data=JSON.parse(row.body);
            if(mode==='read_only'&&url.pathname==='/api/auth/notifications')data.can_write=false;
            return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
          }
          invalidateUserData(); // Admin Only requires the ordinary authorized API.
        }catch(error){if(error.code!=='stale_user_data')invalidateUserData('blocked',error);throw error}
      }
      const response=await dispatchApi(path,requestOptions,forceRefresh);
      if([401,403,503].includes(response.status)){
        const error=await response.clone().json().catch(()=>null);
        const blocked=response.status===401||error?.detail?.code==='service_restricted'||error?.code==='service_restricted'||response.status===403&&Boolean(ttl(key));
        invalidateUserData(blocked?'blocked':'failure',{status:response.status,code:error?.detail?.code||error?.code});return response;
      }
      if(reusable&&current()&&response.status===200&&response.headers.get('content-type')?.split(';')[0]==='application/json'){
        const body=await response.clone().text();
        if(current()&&body.length<=65536){try{
          const data=JSON.parse(body);
          const complete=url.pathname!=='/api/auth/favorites'||!url.searchParams.has('after')&&data.next_after===null&&Array.isArray(data.items)&&String(data.items.length)===data.total;
          if(complete){entries[key]={at:now(),body};saveUserData()}
        }catch{}}
      }
      return response;
    }
    const identityListeners=new Set();
    const sharedReads=new Map();
    function identityChanged(initial=false){
      if(observedUser===auth.currentUser)return;
      observedUser=auth.currentUser;account=null;accountUser=null;
      sharedReads.clear();dataOwner=null;themeOwner=null;
      if(!initial){invalidateUserData();globalThis.YGCTheme?.clear()}
      if(initial)return;
      for(const listener of identityListeners){try{listener()}catch{/* One view cannot retain another view's private data. */}}
    }
    const changedIdentity=()=>Object.assign(Error('The signed-in account changed.'),{code:'sign_in_required'});
    function ready(){
      return initialization??=(async()=>{
        await sdk.setPersistence(auth,sdk.browserSessionPersistence);
        await auth.authStateReady();
        identityChanged(true);
        // The canonical server account cannot survive an SDK principal change.
        if(typeof sdk.onAuthStateChanged==='function')sdk.onAuthStateChanged(auth,()=>identityChanged());
      })();
    }
    function serial(action){
      const result=pending.catch(()=>{}).then(async()=>{await ready();return action()});
      pending=result;return result;
    }
    // All authenticated page components share the database connection budget.
    // Row-only throttling misses concurrent profile/detail/settings requests.
    let activeRequests=0,backgroundRequests=0;const requestWaiters=[];
    const aborted=()=>Object.assign(Error('Request aborted.'),{name:'AbortError'});
    function drainRequests(){
      while(activeRequests<2){
        let index=requestWaiters.findIndex(waiter=>waiter.priority===2);
        if(index<0)index=requestWaiters.findIndex(waiter=>!waiter.background);
        if(index<0&&backgroundRequests<1)index=requestWaiters.findIndex(waiter=>waiter.background);
        if(index<0)return;
        const waiter=requestWaiters.splice(index,1)[0];
        waiter.signal?.removeEventListener('abort',waiter.cancel);
        activeRequests++;if(waiter.background)backgroundRequests++;
        waiter.resolve();
      }
    }
    function requestSlot(priority,signal){
      if(signal?.aborted)return Promise.reject(aborted());
      return new Promise((resolve,reject)=>{
        const waiter={priority,background:priority===0,signal,resolve,cancel:()=>{const index=requestWaiters.indexOf(waiter);if(index>=0){requestWaiters.splice(index,1);reject(aborted());drainRequests()}}};
        requestWaiters.push(waiter);signal?.addEventListener('abort',waiter.cancel,{once:true});drainRequests();
      });
    }
    function releaseRequest(background){activeRequests--;if(background)backgroundRequests--;drainRequests()}
    async function dispatchApi(path,options={},forceRefresh=false){
      const url=new URL(path,origin);
      if(url.origin!==origin||!url.pathname.startsWith('/api/'))throw Error('Only same-origin API requests are allowed.');
      // Preserve the principal at the synchronous call boundary, before SDK
      // readiness can yield. A delayed A action must never use B's token.
      const user=auth.currentUser;
      // An SDK switch can precede its observer. Never dispatch an old shell's
      // action with the new principal while a different canonical cache remains.
      if(account!==null&&accountUser!==user){identityChanged();throw changedIdentity()}
      await ready();
      identityChanged();
      if(auth.currentUser!==user)throw changedIdentity();
      if(!user)throw Object.assign(Error('Sign in to continue.'),{code:'sign_in_required'});
      // One background row read leaves a slot available for user operations.
      const background=['GET','HEAD'].includes((options.method||'GET').toUpperCase())&&/^\/api\/auth\/(?:favorites\/[1-9][0-9]*|members\/[1-9][0-9]*\/avatar)$/.test(url.pathname);
      const priority=background?0:!['GET','HEAD'].includes((options.method||'GET').toUpperCase())||url.pathname==='/api/auth/me'||/^\/api\/public\/guitars(?:\/[1-9][0-9]*(?:\/.*)?)?$/.test(url.pathname)?2:1;
      await requestSlot(priority,options.signal);
      try{
        // Waiting must not turn an old identity's request into a new user's action.
        if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
        if(options.signal?.aborted)throw Object.assign(Error('Request aborted.'),{name:'AbortError'});
        const headers=new Headers(options.headers||{});
        const token=await user.getIdToken(forceRefresh);
        if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
        if(options.signal?.aborted)throw Object.assign(Error('Request aborted.'),{name:'AbortError'});
        headers.set('Authorization','Bearer '+token);
        const publicRevalidation=(options.method||'GET').toUpperCase()==='GET'&&options.cache==='no-cache'&&/^\/api\/public\/guitars(?:\/[1-9][0-9]*(?:\/chronicle)?|\/(?:discoveries|statistics|world-map))?$/.test(url.pathname);
        return await request(url.href,{...options,headers,credentials:'omit',redirect:'error',cache:publicRevalidation?'no-cache':'no-store'});
      }finally{releaseRequest(background)}
    }
    async function api(path,options={},forceRefresh=false){
      const method=(options.method||'GET').toUpperCase(),user=auth.currentUser;
      // Share only simultaneous reads, never a stored response. Signals and
      // forced refreshes remain independent; writes invalidate pending reuse.
      if(!['GET','HEAD'].includes(method)){
        sharedReads.clear();invalidateUserData();dataWrites++;
        try{return await dispatchApi(path,options,forceRefresh)}finally{dataWrites--;invalidateUserData(dataWrites?'refresh':'changed')}
      }
      if(method!=='GET'||forceRefresh||options.signal||options.body||new URL(path,origin).pathname==='/api/auth/me')return displayRead(path,options,forceRefresh);
      const key=JSON.stringify([new URL(path,origin).href,[...new Headers(options.headers||{})],options.cache==='no-cache'?'revalidate':'fresh',options.reuseUserData===true]);
      let entry=sharedReads.get(key);
      if(!entry||entry.user!==user){
        entry={user,promise:displayRead(path,options,forceRefresh)};sharedReads.set(key,entry);
        entry.promise.finally(()=>{if(sharedReads.get(key)===entry)sharedReads.delete(key)}).catch(()=>{});
      }
      const response=await entry.promise;
      if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
      return response.clone();
    }
    async function result(response){
      const data=await response.json();
      if(!response.ok){
        account=null;
        throw Object.assign(Error(typeof data.detail==='string'?data.detail:'Account request failed.'),
                            {code:data.code||'account_request_failed',status:response.status});
      }
      return data;
    }
    async function me(forceRefresh=false){
      identityChanged();account=null;accountUser=null;
      const user=auth.currentUser;
      if(!user){globalThis.YGCTheme?.clear();return null;}
      const response=await api('/api/auth/me',{},forceRefresh);
      if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
      if(response.status===409){
        const data=await response.json();
        if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
        if(data.code==='registration_required')return {registration_required:true};
        throw Error('Account request failed.');
      }
      const data=await result(response);
      if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
      accountUser=user;account=data;bindUserData();return account;
    }
    async function documents(){
      const response=await request(new URL('/api/auth/registration',origin).href,{cache:'no-store',credentials:'omit',redirect:'error'});
      const data=await result(response);
      return data.participant_only===true?{...data.documents,participant_only:true}:data.documents;
    }
    function validate(profile,policies){
      const fields=['display_name','account_type','terms_accepted','privacy_accepted','terms_version','privacy_version'];
      if(!profile||typeof profile!=='object'||Array.isArray(profile)||Object.keys(profile).some(key=>!fields.includes(key)))throw Error('Send only profile and agreement fields.');
      if(typeof profile.display_name!=='string'||!profile.display_name.trim()||[...profile.display_name.trim()].length>120)throw Error('Display Name is required (maximum 120 characters).');
      if(!['user','shop','builder','repairer','organization'].includes(profile.account_type))throw Error('Select a valid Account Type.');
      if(profile.terms_accepted!==true||profile.privacy_accepted!==true)throw Error('Agree to the Terms and Privacy notice.');
      if(profile.terms_version!==policies.terms.version||profile.privacy_version!==policies.privacy.version)throw Object.assign(Error('The agreement version has changed. Review the current documents.'),{code:'policy_changed'});
    }
    return {
      documents,
      restore(){return serial(me)},
      signIn(credentials){return serial(async()=>{
        invalidateUserData();account=null;
        await sdk.signInWithEmailAndPassword(auth,credentials.email,credentials.password);
        return me();
      })},
      register(profile,credentials){return serial(async()=>{
        const policies=await documents();validate(profile,policies);
        account=null;
        if(!auth.currentUser){
          if(policies.participant_only===true)throw Object.assign(Error('Closed-test participant sign-in is required.'),{code:'closed_test_participant_required'});
          if(!credentials?.email||!credentials?.password)throw Error('Email and password are required.');
          await sdk.createUserWithEmailAndPassword(auth,credentials.email,credentials.password);
        }else if(credentials?.email&&credentials.email.trim().toLowerCase()!==auth.currentUser.email?.toLowerCase()){
          throw Error('SignOut before creating an account for another email address.');
        }
        // On failure keep Google's account/session so enrollment can be retried.
        const user=auth.currentUser;
        const registered=await result(await api('/api/auth/register',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({...profile,display_name:profile.display_name.trim()})}));
        if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
        accountUser=user;account=registered;bindUserData();return account;
      })},
      requestEmailVerification({language='en',acquire,claim}={}){return serial(async()=>{
        const user=auth.currentUser;
        if(!user)throw Object.assign(Error('Sign in to continue.'),{code:'sign_in_required'});
        const current=await me(true);
        if(!current?.user||auth.currentUser!==user)throw Error('Complete registration before verifying email.');
        if(current.identity.email_verified===true)return {account:current,sent:false};
        if(typeof language!=='string'||language.length>63||!/^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$/.test(language))throw Error('Invalid language.');
        const returnUrl=new URL('/account',origin);
        for(const [key,value] of [['acquire',acquire],['claim',claim]]){
          if(value===undefined)continue;
          if(typeof value!=='string'||!/^[1-9][0-9]{0,18}$/.test(value)||(value.length===19&&value>'9223372036854775807'))throw Error('Invalid guitar selection.');
          returnUrl.searchParams.set(key,value);
        }
        auth.languageCode=language;
        await sdk.sendEmailVerification(user,{url:returnUrl.href});
        return {account:current,sent:true};
      })},
      refreshVerification(){return serial(async()=>{
        account=null;
        const user=auth.currentUser;
        if(!user)throw Object.assign(Error('Sign in to continue.'),{code:'sign_in_required'});
        await sdk.reload(user);
        if(auth.currentUser!==user)throw Error('The signed-in account changed.');
        // Force a new JWT: SDK emailVerified alone cannot authorize an app action.
        return me(true);
      })},
      logout(){globalThis.YGCTheme?.clear();invalidateUserData();return serial(async()=>{try{await sdk.signOut(auth);account=null;dataOwner=null}finally{invalidateUserData()}})},
      authorizedFetch:api,
      invalidateUserData,
      onUserDataInvalidated(listener){dataListeners.add(listener);return ()=>dataListeners.delete(listener)},
      onIdentityChanged(listener){identityListeners.add(listener);return ()=>identityListeners.delete(listener)},
      get account(){return accountUser===auth.currentUser?account:null},
      get signedIn(){return Boolean(auth.currentUser)},
    };
  }
  globalThis.YGCIdentityPlatformAuth={create};
})();
