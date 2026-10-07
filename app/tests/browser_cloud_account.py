"""Browser account API journeys with external Google operations replaced only here."""
from contextlib import contextmanager
import os
import socket
import threading
from pathlib import Path

from fastapi import FastAPI, Request
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
    from ygc.cloud_self_profile_routes import self_profile_router
    from ygc.cloud_profile import validate,ProfileConflict
    class Profiles:
        def own_profile(self,actor):
            record=next(row for row in records.values() if row['app_user_id']==actor)
            return dict(profile_revision=str(record.get('version',1)),fields={key:record.get(key,'') for key in ('display_name','location_country','location_region','bio')})
        def edit_own_profile(self,actor,body):
            version,fields=validate(body)
            record=next(row for row in records.values() if row['app_user_id']==actor)
            if record.get('version',1)!=version:raise ProfileConflict()
            record.update(fields);record['version']=version+1
            return dict(saved=True)
    app.include_router(self_profile_router(TestVerifier(),Profiles()))
    from ygc.cloud_self_guitars_routes import self_guitars_router
    class Guitars:
        def own_guitars(self,actor,*,kind,after,limit):
            if failures.get('ownership'):raise PermissionError()
            first=records.get('fixture-new@example.invalid',{}).get('app_user_id')
            rows=[dict(id=i,manufacturer='<b>Maker</b>',model='Model '+str(i),year=1960+i,serial_number='S'+str(i)) for i in range(1,29)] if actor==first and kind=='owned' else [dict(id=50,manufacturer='Maker',model='Former',year=None,serial_number=None)] if actor==first else []
            page=[row for row in rows if row['id']>after][:limit+1];more=len(page)>limit;page=page[:limit]
            return dict(items=page,total=len(rows),next_after=page[-1]['id'] if more else None)
    app.include_router(self_guitars_router(TestVerifier(),Guitars()))
    from ygc.cloud_application_routes import application_router
    @app.get('/api/public/guitars/{individual_id}')
    def public_guitar(individual_id: str):
        assert individual_id == '12'
        return dict(id='12', manufacturer='Maker', model='Model', serial_number='S12',
                    finish=None, year='1965', photo=None)

    applications={}
    class Applications:
        def list(self,actor):return dict(items=[row.copy() for who,row in applications.values() if who==actor],can_write=True)
        def start(self,actor,data):
            revision=format(len(applications)+1,'032x');payload=data.get('payload')
            row=dict(revision=revision,kind=data['kind'],individual_id=data.get('individual_id'),serial=payload['serial_number'] if payload else 'S12',challenge='ABCD1234',expires_at=2000000000,status='draft',payload=payload,photos=[],acquisition_date=payload['occurred_at'] if payload else None,body=payload['body'] if payload else '')
            applications[revision]=(actor,row);return row.copy()
        def upload(self,actor,revision,role,data,mime):
            from ygc.cloud_avatar import normalize_image
            normalize_image(data,mime);who,row=applications[revision];assert actor==who
            if role not in row['photos']:row['photos'].append(role)
            return row.copy()
        def submit(self,actor,revision,data):
            who,row=applications[revision];assert actor==who and set(row['photos'])=={'closeup','overview'}
            row['status']='pending';return row.copy()
        def cancel(self,actor,revision):
            who,row=applications[revision];assert actor==who;row['status']='cancelled';return row.copy()
        def image(self,actor,revision,role):
            who,row=applications[revision];assert actor==who and role in row['photos']
            from ygc.cloud_avatar import normalize_image
            return normalize_image(png(),'image/png')
    Applications.storage=storage
    app.include_router(application_router(TestVerifier(),Applications()))
    install(app, public_config({'apiKey': 'fixture-key', 'authDomain': 'fixture-project.firebaseapp.com'},
                               project_id='fixture-project', tenant=''))

    @app.get('/api/auth/ownership-disputes')
    @app.get('/api/auth/ownership-disputes/options')
    def empty_disputes():
        return {'items': [], 'next_after': None, 'can_write': True, 'viewer_user_id': '1'}

    @app.get('/api/auth/notifications')
    def notifications():
        return {'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True}

    @app.get('/api/auth/identity-corrections')
    def identity_corrections():
        return {'items': [], 'next_after': None, 'can_write': True}

    @app.get('/api/auth/ownership-transfers')
    def ownership_transfers(request: Request):
        identity = TestVerifier().verify(bearer_token=request.headers['authorization'].removeprefix('Bearer '))
        user = records[identity.subject]
        return {'viewer_user_id': str(user['id']), 'items': [], 'can_write': True, 'next_after': None}

    @app.middleware('http')
    async def observe(request, call_next):
        if request.method == 'POST' and request.headers.get('content-type','').startswith('application/json'):
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
                page_errors=[]
                page.on('pageerror',lambda error:page_errors.append(str(error)))
                def ready():
                    page.goto(url)
                    try:page.wait_for_function('window.YGCCloudAccountReady')
                    except Exception:
                        raise AssertionError('Cloud account did not initialize: '+repr(page_errors)) from None
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
                owned=page.locator('#selfGuitars_owned');former=page.locator('#selfGuitars_formerly_owned')
                expect(owned.locator('li')).to_have_count(25);expect(owned).to_contain_text('Total guitars: 28')
                expect(former.locator('li')).to_have_count(1);expect(former).to_contain_text('Former')
                assert owned.locator('b,img').count()==0
                owned.get_by_role('button',name='Next',exact=True).click();expect(owned.locator('li')).to_have_count(3)
                owned.get_by_role('button',name='Previous',exact=True).click();expect(owned.locator('li')).to_have_count(25)
                failures['ownership']=True
                owned.get_by_role('button',name='Refresh',exact=True).click()
                expect(owned).to_contain_text('restricted');expect(page.locator('#selfGuitars li')).to_have_count(0)
                expect(owned.get_by_role('button',name='Next',exact=True)).to_be_disabled()
                failures['ownership']=False
                owned.get_by_role('button',name='Refresh',exact=True).click();expect(owned.locator('li')).to_have_count(25)
                former.get_by_role('button',name='Refresh',exact=True).click();expect(former.locator('li')).to_have_count(1)
                page.locator('#applicationListing').click()
                page.locator('#application_manufacturer').fill('<b>Fender</b>')
                page.locator('#application_serial_number').fill('TEST123')
                page.locator('#application_occurred_at').fill('2020-01-01')
                page.locator('#applicationCreate').click()
                expect(page.locator('#applicationDialog')).to_contain_text('ABCD1234')
                for role in ('closeup','overview'):
                    page.locator('#application_'+role).set_input_files({'name':role+'.png','mimeType':'image/png','buffer':png()})
                page.locator('#applicationSubmit').click()
                expect(page.locator('#applicationDialog')).to_contain_text('Pending review')
                expect(owned.locator('li')).to_have_count(25)
                page.locator('#applicationDialog').get_by_role('button',name='View closeup',exact=True).click()
                expect(page.locator('#applicationDialog img').first).to_be_visible()
                page.mouse.click(1,1);expect(page.locator('#applicationDialog')).not_to_be_visible()
                assert page.locator('#applicationDialog img').first.get_attribute('src') is None
                ready();expect(page.locator('#selfApplications li')).to_have_count(1)
                page.locator('#selfApplications').get_by_role('button',name='Detail',exact=True).click()
                page.locator('#applicationCancel').click();expect(page.locator('#applicationDialog')).to_contain_text('Cancelled')
                page.keyboard.press('Escape');expect(page.locator('#applicationDialog')).not_to_be_visible()
                expect(page.locator('#applicationAcquire')).to_have_attribute('href','/')
                page.goto(url+'?acquire=12');page.wait_for_function('window.YGCCloudAccountReady')
                expect(page.locator('#catalogAcquireStart')).to_be_enabled()
                assert len(applications)==1
                page.locator('#catalogAcquireStart').click()
                expect(page.locator('#application_individual_id')).to_have_value('12')
                expect(page.locator('#application_individual_id')).to_have_js_property('readOnly',True)
                assert len(applications)==1
                page.locator('#applicationCreate').click()
                expect(page.locator('#application_occurred_at')).to_be_enabled()
                page.locator('#application_occurred_at').fill('2020-01-02')
                page.locator('#applicationCancel').click();page.keyboard.press('Escape')
                expect(page.locator('#selfApplications li')).to_have_count(2)
                expect(page.locator('#selfProfile')).to_be_visible()
                expect(page.locator('#selfProfileValues')).to_contain_text('Browser Cloud User')
                for cancel in ('button','escape','outside'):
                    page.locator('#selfProfileEdit').click()
                    page.locator('#selfProfile_display_name').fill('Unsaved')
                    if cancel=='button':page.locator('#selfProfileCancel').click()
                    elif cancel=='escape':page.keyboard.press('Escape')
                    else:page.mouse.click(1,1)
                    expect(page.locator('#selfProfileDialog')).not_to_be_visible()
                    assert records['fixture-new@example.invalid']['display_name']=='Browser Cloud User'
                page.locator('#selfProfileEdit').click()
                page.locator('#selfProfile_display_name').fill('<b>Updated profile</b>')
                page.locator('#selfProfile_location_country').fill('Japan')
                page.locator('#selfProfile_location_region').fill('Tokyo')
                page.locator('#selfProfile_bio').fill('First line\nSecond line')
                page.locator('#selfProfileSave').click()
                expect(page.locator('#selfProfileStatus')).to_contain_text('Profile saved')
                expect(page.locator('#accountSummary')).to_contain_text('<b>Updated profile</b>')
                assert page.locator('#selfProfileValues b').count()==0
                ready()
                expect(page.locator('#selfProfileValues')).to_contain_text('Second line')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#selfProfileEdit').click()
                assert page.locator('#selfProfileDialog').evaluate('(el)=>el.getBoundingClientRect().width<=innerWidth')
                if os.getenv('YGC_BROWSER_ARTIFACTS'):
                    page.screenshot(path=str(artifacts / 'cloud-self-profile-mobile.png'),full_page=True)
                page.locator('#selfProfileCancel').click()
                page.set_viewport_size({'width':1280,'height':900})
                page.locator('#selfProfileEdit').click()
                records['fixture-new@example.invalid']['version']+=1
                page.locator('#selfProfileSave').click()
                expect(page.locator('#selfProfileStatus')).to_contain_text('profile changed')
                expect(page.locator('#selfProfileEdit')).to_be_disabled()
                page.locator('#selfProfileRefresh').click()
                expect(page.locator('#selfProfileEdit')).to_be_enabled()
                page.locator('#selfProfileEdit').click()
                page.locator('#selfProfile_display_name').fill('Browser Cloud User')
                page.locator('#selfProfileSave').click()
                expect(page.locator('#selfProfileStatus')).to_contain_text('Profile saved')
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
                expect(page.locator('#selfProfile')).not_to_be_visible()
                expect(page.locator('#selfGuitars')).not_to_be_visible()
                expect(page.locator('#selfGuitars li')).to_have_count(0)
                expect(page.locator('#selfApplications')).not_to_be_visible()
                expect(page.locator('#selfApplications li')).to_have_count(0)
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
                page.evaluate("sessionStorage.setItem('verified-orphan@example.invalid','true')")
                page.locator('#refreshVerification').click()
                expect(page.locator('#selfGuitars_owned')).to_contain_text('この区分のギターはありません。')
                expect(page.locator('#selfGuitars li')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                context.close()
                browser.close()
            print('Cloud account browser: self profile and ownership paging/empty/privacy/restriction/SignOut/mobile, registration retry, credential separation, Sign In/Out, reload, unregistered enrollment, policy backdrop, verification mail/refresh, Japanese and mobile passed.')
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Cloud account browser test server did not stop')
