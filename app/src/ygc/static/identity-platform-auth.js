// Google credentials go only to the official SDK. API calls carry an ID token.
(() => {
  function create({sdk, auth, fetch: request=globalThis.fetch.bind(globalThis), origin=location.origin}){
    let initialization, account=null, accountUser=null, pending=Promise.resolve();
    let observedUser=auth.currentUser;
    const identityListeners=new Set();
    function identityChanged(){
      if(observedUser===auth.currentUser)return;
      observedUser=auth.currentUser;account=null;accountUser=null;
      for(const listener of identityListeners){try{listener()}catch{/* One view cannot retain another view's private data. */}}
    }
    const changedIdentity=()=>Object.assign(Error('The signed-in account changed.'),{code:'sign_in_required'});
    function ready(){
      return initialization??=(async()=>{
        await sdk.setPersistence(auth,sdk.browserSessionPersistence);
        await auth.authStateReady();
        identityChanged();
        // The canonical server account cannot survive an SDK principal change.
        if(typeof sdk.onAuthStateChanged==='function')sdk.onAuthStateChanged(auth,identityChanged);
      })();
    }
    function serial(action){
      const result=pending.catch(()=>{}).then(async()=>{await ready();return action()});
      pending=result;return result;
    }
    async function api(path,options={},forceRefresh=false){
      const url=new URL(path,origin);
      if(url.origin!==origin||!url.pathname.startsWith('/api/'))throw Error('Only same-origin API requests are allowed.');
      // Preserve the principal at the synchronous call boundary, before SDK
      // readiness can yield. A delayed A action must never use B's token.
      const user=auth.currentUser;
      await ready();
      identityChanged();
      if(auth.currentUser!==user)throw changedIdentity();
      if(!user)throw Object.assign(Error('Sign in to continue.'),{code:'sign_in_required'});
      const headers=new Headers(options.headers||{});
      const token=await user.getIdToken(forceRefresh);
      if(auth.currentUser!==user){identityChanged();throw changedIdentity()}
      headers.set('Authorization','Bearer '+token);
      return request(url.href,{...options,headers,credentials:'omit',redirect:'error',cache:'no-store'});
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
      if(!user)return null;
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
      accountUser=user;return account=data;
    }
    async function documents(){
      const response=await request(new URL('/api/auth/registration',origin).href,{cache:'no-store',credentials:'omit',redirect:'error'});
      return (await result(response)).documents;
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
        account=null;
        await sdk.signInWithEmailAndPassword(auth,credentials.email,credentials.password);
        return me();
      })},
      register(profile,credentials){return serial(async()=>{
        const policies=await documents();validate(profile,policies);
        account=null;
        if(!auth.currentUser){
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
        accountUser=user;return account=registered;
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
      logout(){return serial(async()=>{await sdk.signOut(auth);account=null})},
      authorizedFetch:api,
      onIdentityChanged(listener){identityListeners.add(listener);return ()=>identityListeners.delete(listener)},
      get account(){return accountUser===auth.currentUser?account:null},
      get signedIn(){return Boolean(auth.currentUser)},
    };
  }
  globalThis.YGCIdentityPlatformAuth={create};
})();
