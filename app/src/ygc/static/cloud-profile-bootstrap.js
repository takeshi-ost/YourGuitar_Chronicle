// One bounded, canonical self read supplies the existing display controllers.
// Cursor continuations and all writes retain the original transport/guards.
export function installProfileBootstrap(auth){
 const original=auth.authorizedFetch.bind(auth);let flight=null,stopped=false,fresh=false;
 function key(path){const url=new URL(path,location.origin),p=url.searchParams;
  if(url.pathname==='/api/auth/settings'&&!url.search)return 'settings';
  if(url.pathname==='/api/auth/profile/summary'&&!url.search)return 'summary';
  if(url.pathname==='/api/auth/settings/signature'&&!url.search)return 'signature';
  if(url.pathname==='/api/auth/guitars'&&!p.has('after')&&p.get('limit')==='25'&&['owned','formerly_owned'].includes(p.get('kind')))return p.get('kind');
  if(url.pathname==='/api/auth/favorites'&&!p.has('after')&&p.get('limit')==='50')return 'favorites';return null;
 }
 auth.authorizedFetch=async(path,options={},force=false)=>{
  const part=key(path);if(stopped||!part||(options.method||'GET').toUpperCase()!=='GET')return original(path,options,force);
  const account=auth.account,user=account?.user?.app_user_id;if(!user||account.identity?.email_verified!==true)return original(path,options,force);
  if(!flight){const reuse=!fresh;fresh=false;const pending=original('/api/auth/profile/bootstrap',{reuseUserData:reuse}).then(async response=>{
    if(!response.ok){if(response.status===404)return null;throw Object.assign(Error('Profile unavailable'),{status:response.status})}
    const data=await response.json();if(!data||Object.keys(data).length!==6||['settings','summary','signature','owned','formerly_owned','favorites'].some(k=>!Object.hasOwn(data,k)))throw Error('Invalid profile bundle');return data;
   });flight=pending;pending.finally(()=>{if(flight===pending)flight=null}).catch(()=>{});
  }
  const data=await flight;if(auth.account?.user?.app_user_id!==user||auth.account?.identity?.email_verified!==true)throw Error('Profile identity changed');
  if(data===null)return original(path,options,force);return Response.json(data[part],{headers:{'Cache-Control':'no-store'}});
 };
 return {async ready(){const account=auth.account;const r=await original('/api/auth/profile/bootstrap',{reuseUserData:true});if(r.status===404)return null;if(!r.ok)throw Object.assign(Error('Profile unavailable'),{status:r.status});const data=await r.json();if(auth.account!==account)throw Error('Profile identity changed');return data},invalidate(){fresh=true;flight=null;auth.invalidateUserData?.()},stop(){stopped=true;flight=null;auth.authorizedFetch=original}};
}
