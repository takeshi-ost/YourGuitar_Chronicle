// Pin the official modular SDK; do not use an unversioned CDN URL.
export const FIREBASE_VERSION='12.19.0';
export async function loadCloudAuth(){
  const response=await fetch('/api/auth/config',{cache:'no-store'});
  if(!response.ok)throw Error('Cloud authentication is not configured.');
  const config=await response.json();
  const [appSDK,sdk]=await Promise.all([
    import('https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js'),
    import('https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js'),
  ]);
  const app=appSDK.initializeApp(config.firebase,'ygc-cloud-account');
  const auth=sdk.getAuth(app);
  auth.tenantId=config.tenant||null;
  return globalThis.YGCIdentityPlatformAuth.create({sdk,auth});
}
