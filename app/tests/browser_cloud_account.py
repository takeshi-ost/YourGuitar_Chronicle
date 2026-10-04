"""Browser account API journeys with external Google operations replaced only here."""
from contextlib import contextmanager
import os
import socket
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright, expect
import uvicorn

from ygc.cloud_account_page import install, public_config
from ygc.cloud_account_routes import account_router
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_accounts import AccountNotRegistered
from ygc.identity_platform import VerifiedIdentity

SDK = r'''
const makeUser=email=>({email,emailVerified:false,getIdToken:async()=> 'fixture-'+(sessionStorage.getItem('verified-'+email)==='true'?'verified-':'')+email});
const saved=sessionStorage.getItem('fixture-sdk-email');
const auth={currentUser:saved?makeUser(saved):null,authStateReady:async()=>{}};
export const browserSessionPersistence='session';
export const getAuth=()=>auth;
export async function setPersistence(_auth,persistence){if(persistence!=='session')throw Error('Incorrect persistence');}
export async function signInWithEmailAndPassword(_auth,email,password){
  if(password==='bad')throw Object.assign(Error('private SDK failure'),{code:'auth/invalid-credential'});
  auth.currentUser=makeUser(email);sessionStorage.setItem('fixture-sdk-email',email);
}
export async function createUserWithEmailAndPassword(_auth,email,password){
  window.fixtureCreates=(window.fixtureCreates||0)+1;
  await signInWithEmailAndPassword(_auth,email,password);
}
export async function reload(user){window.fixtureReloads=(window.fixtureReloads||0)+1;}
export async function sendEmailVerification(user,settings){window.fixtureVerificationSends=(window.fixtureVerificationSends||0)+1;window.fixtureVerificationURL=settings.url;window.fixtureVerificationLanguage=auth.languageCode;}
export async function signOut(){auth.currentUser=null;sessionStorage.removeItem('fixture-sdk-email');}
'''


def main():
    records = {}
    captured = []
    failures = {'register': False}

    class TestAccounts:
        def ensure_identity(self, *, issuer, subject, tenant, display_name, account_type, consents):
            if subject not in records:
                records[subject] = {'id': len(records) + 1, 'app_user_id': 'fixture-uuid-' + str(len(records) + 1),
                                    'display_name': display_name, 'account_type': account_type, 'role': 'member'}
            return records[subject]

        def resolve_identity(self, *, issuer, subject, tenant):
            if subject not in records:
                raise AccountNotRegistered('Registration required')
            return records[subject]

    class TestVerifier:
        accounts = TestAccounts()

        def verify(self, *, bearer_token):
            if not bearer_token.startswith('fixture-'):
                raise PermissionError('Invalid fixture token')
            return VerifiedIdentity('fixture-issuer', bearer_token.replace('fixture-verified-', 'fixture-', 1), '', bearer_token.startswith('fixture-verified-'))

    from ygc.cloud_avatar_routes import avatar_router
    from test_cloud_avatar import Storage, png
    class AvatarOperations:
        @contextmanager
        def account_access(self,kind,actor):
            record=next(row for row in records.values() if row['app_user_id']==actor)
            record.setdefault('avatar_storage_path',None)
            class Connection:
                def execute(self,query,params):
                    if query.startswith('UPDATE account_records'):record['avatar_storage_path']=params[0]
            yield Connection(),{},record
    storage=Storage()
    app = FastAPI()
    app.include_router(avatar_router(TestVerifier(),AvatarOperations(),storage))
    app.include_router(account_router(TestVerifier(), DOCUMENTS))
    install(app, public_config({'apiKey': 'fixture-key', 'authDomain': 'fixture-project.firebaseapp.com'},
                               project_id='fixture-project', tenant=''))

    @app.middleware('http')
    async def observe(request, call_next):
        if request.method == 'POST':
            captured.append(await request.json())
            if failures['register'] and request.url.path == '/api/auth/register':
                failures['register'] = False
                return JSONResponse({'detail': 'Temporary test outage'}, status_code=503)
        return await call_next(request)

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{sock.getsockname()[1]}/account'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.getenv('YGC_BROWSER_EXECUTABLE') or None)
                context = browser.new_context()
                def intercept(route):
                    if 'firebase-app.js' in route.request.url:
                        route.fulfill(content_type='text/javascript', body='export const initializeApp=config=>config;')
                    elif 'firebase-auth.js' in route.request.url:
                        route.fulfill(content_type='text/javascript', body=SDK)
                    else:
                        route.abort()
                context.route('https://www.gstatic.com/**', intercept)
                page = context.new_page()
                def ready():
                    page.goto(url)
                    page.wait_for_function('window.YGCCloudAccountReady')
                ready()
                page.locator('#showRegistration').click()
                page.locator('#email').fill('new@example.invalid')
                page.locator('#password').fill('test-private-password')
                page.locator('#displayName').fill('Browser Cloud User')
                page.locator('#accountType').select_option('builder')
                page.locator('#terms').check()
                page.locator('#privacy').check()
                page.locator('#viewPrivacy').click()
                expect(page.locator('#policyDialog')).to_be_visible()
                expect(page.locator('#policyContent')).to_contain_text('Google Identity Platform')
                page.mouse.click(1, 1)
                expect(page.locator('#policyDialog')).not_to_be_visible()
                failures['register'] = True
                page.locator('#submit').click()
                expect(page.locator('#status')).to_contain_text('Could not complete')
                expect(page.locator('#credentialsFields')).not_to_be_visible()
                assert page.locator('#password').input_value() == ''
                assert page.evaluate('window.fixtureCreates') == 1
                page.locator('#submit').click()
                expect(page.locator('#accountSummary')).to_contain_text('Browser Cloud User')
                if os.getenv('YGC_BROWSER_ARTIFACTS'):
                    artifacts = Path(os.environ['YGC_BROWSER_ARTIFACTS'])
                    artifacts.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(artifacts / 'cloud-account-desktop.png'), full_page=True)
                assert page.evaluate('window.fixtureCreates') == 1
                assert len(records) == 1
                assert all('email' not in body and 'password' not in body for body in captured)
                ready()
                expect(page.locator('#accountSummary')).to_contain_text('Browser Cloud User')
                expect(page.locator('#verificationStatus')).to_contain_text('not verified')
                assert page.evaluate('window.fixtureVerificationSends||0') == 0
                page.locator('#sendVerification').click()
                expect(page.locator('#status')).to_contain_text('Verification email sent')
                assert page.evaluate('window.fixtureVerificationSends') == 1
                assert page.evaluate('window.fixtureVerificationURL') == url
                page.locator('#refreshVerification').click()
                expect(page.locator('#status')).to_contain_text('still unverified')
                page.evaluate("sessionStorage.setItem('verified-new@example.invalid','true')")
                page.locator('#refreshVerification').click()
                expect(page.locator('#verificationStatus')).to_have_text('Email address verified.')
                expect(page.locator('#sendVerification')).not_to_be_visible()
                ready()
                expect(page.locator('#verificationStatus')).to_have_text('Email address verified.')
                expect(page.locator('#accountAvatar')).to_be_visible()
                page.locator('#avatarFile').set_input_files({'name':'avatar.png','mimeType':'image/png','buffer':png()})
                page.locator('#avatarUpload').click()
                expect(page.locator('#avatarPreview')).to_be_visible()
                expect(page.locator('#avatarRemove')).to_be_enabled()
                assert page.locator('#avatarPreview').get_attribute('src').startswith('blob:')
                assert len(storage.objects)==1
                ready()
                expect(page.locator('#avatarPreview')).to_be_visible()
                page.locator('#avatarRemove').click()
                expect(page.locator('#avatarPreview')).not_to_be_visible()
                expect(page.locator('#avatarRemove')).to_be_disabled()
                assert len(storage.objects)==1  # Removal preserves backup references.
                ready()
                expect(page.locator('#avatarPreview')).not_to_be_visible()
                page.locator('#signOut').click()
                expect(page.locator('#signOut')).not_to_be_visible()
                expect(page.locator('#accountSummary')).not_to_be_visible()
                expect(page.locator('#accountAvatar')).not_to_be_visible()
                page.locator('#email').fill('new@example.invalid')
                page.locator('#password').fill('bad')
                page.locator('#submit').click()
                expect(page.locator('#status')).to_contain_text('incorrect')
                assert page.locator('#password').input_value() == ''
                page.locator('#password').fill('valid-test-password')
                page.locator('#submit').click()
                expect(page.locator('#accountSummary')).to_contain_text('Browser Cloud User')
                page.locator('#signOut').click()
                page.locator('#email').fill('orphan@example.invalid')
                page.locator('#password').fill('valid-test-password')
                page.locator('#submit').click()
                expect(page.locator('#status')).to_contain_text('Complete your application profile')
                expect(page.locator('#profileFields')).to_be_visible()
                assert len(records) == 1
                # Japanese survives reload and the unregistered Google session.
                page.evaluate("localStorage.setItem('ygc_ui_language','ja')")
                ready()
                expect(page.locator('#submit')).to_have_text('アプリ登録を完了')
                page.set_viewport_size({'width': 390, 'height': 844})
                ready()
                expect(page.locator('#submit')).to_have_text('アプリ登録を完了')
                assert page.locator('header').count() == 1
                page.evaluate('async () => await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if os.getenv('YGC_BROWSER_ARTIFACTS'):
                    page.screenshot(path=str(artifacts / 'cloud-account-mobile.png'), full_page=True)
                page.locator('#displayName').fill('日本語ユーザー')
                page.locator('#accountType').select_option('repairer')
                page.locator('#terms').check()
                page.locator('#privacy').check()
                page.locator('#submit').click()
                expect(page.locator('#accountSummary')).to_contain_text('日本語ユーザー')
                assert len(records) == 2
                expect(page.locator('#verificationStatus')).to_contain_text('まだ確認')
                page.locator('#sendVerification').click()
                expect(page.locator('#status')).to_contain_text('確認メールを送信しました')
                assert page.evaluate('window.fixtureVerificationLanguage') == 'ja'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                context.close()
                browser.close()
            print('Cloud account browser: registration retry, credential separation, Sign In/Out, reload, unregistered enrollment, policy backdrop, verification mail/refresh, Japanese and mobile passed.')
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Cloud account browser test server did not stop')
