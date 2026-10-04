// Google credentials go only to the official SDK. API calls carry an ID token.
(() => {
  function create({sdk, auth, fetch: request=globalThis.fetch.bind(globalThis), origin=location.origin}){
    let initialization, account=null, pending=Promise.resolve();
    function ready(){
      return initialization??=(async()=>{
        await sdk.setPersistence(auth,sdk.browserSessionPersistence);
        await auth.authStateReady();
      })();
    }
    function serial(action){
      const result=pending.catch(()=>{}).then(async()=>{await ready();return action()});
      pending=result;return result;
    }
    async function api(path,options={}){
      const url=new URL(path,origin);
      if(url.origin!==origin||!url.pathname.startsWith('/api/'))throw Error('Only same-origin API requests are allowed.');
      await ready();
      const user=auth.currentUser;
      if(!user)throw Object.assign(Error('Sign in to continue.'),{code:'sign_in_required'});
      const headers=new Headers(options.headers||{});
      headers.set('Authorization','Bearer '+await user.getIdToken());
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
    async function me(){
      account=null;
      if(!auth.currentUser)return null;
      const response=await api('/api/auth/me');
      if(response.status===409){
        const data=await response.json();
        if(data.code==='registration_required')return {registration_required:true};
        throw Error('Account request failed.');
      }
      return account=await result(response);
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
        account=await result(await api('/api/auth/register',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({...profile,display_name:profile.display_name.trim()})}));
        return account;
      })},
      logout(){return serial(async()=>{await sdk.signOut(auth);account=null})},
      authorizedFetch:api,
      get account(){return account},
      get signedIn(){return Boolean(auth.currentUser)},
    };
  }
  globalThis.YGCIdentityPlatformAuth={create};
})();
