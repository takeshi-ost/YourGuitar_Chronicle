"""Cloud Console UI journeys; Google and stores are replaced only in this fixture."""
import os
import socket
import threading
from types import SimpleNamespace
from contextlib import contextmanager
from fastapi import FastAPI
from playwright.sync_api import sync_playwright, expect
import uvicorn
from browser_cloud_account import SDK
from ygc.cloud_account_page import install, public_config
from ygc.cloud_account_routes import account_router
from ygc.cloud_operations_routes import operations_router
from ygc.cloud_registration import DOCUMENTS
from ygc.db.postgres_operations import ModeConflict
from ygc.identity_platform import VerifiedIdentity


def main():
    calls=[]
    class Accounts:
        def resolve_identity(self, **identity):
            admin=identity['subject'].endswith('admin@example.invalid')
            return dict(id=1 if admin else 2,app_user_id='admin-uuid' if admin else 'member-uuid',
                        display_name='<b>Operator</b>' if admin else 'Member',account_type='user',role='admin' if admin else 'member')
    class Verifier:
        accounts=Accounts()
        def verify(self, *, bearer_token):
            if not bearer_token.startswith('fixture-'):raise PermissionError()
            return VerifiedIdentity('fixture-issuer',bearer_token,'',bearer_token.startswith('fixture-verified-'))
    class Operations:
        row=dict(mode='offline',message='<img src=x onerror=alert(1)>',version=1)
        fail=None
        @contextmanager
        def access(self, kind, actor):
            if self.fail:raise self.fail
            if actor!='admin-uuid':raise PermissionError()
            yield
        def details(self, actor):
            calls.append(('read',actor))
            if self.fail:raise self.fail
            return dict(self.row)
        def set_mode(self, actor, **data):
            calls.append(('write',actor,data))
            if self.fail:raise self.fail
            if data['version']!=self.row['version']:raise ModeConflict()
            self.row=dict(mode=data['mode'],message=data['message'],version=data['version']+1)
            return dict(self.row)
    ops=Operations();verifier=Verifier();app=FastAPI()
    app.include_router(account_router(verifier,DOCUMENTS));app.include_router(operations_router(verifier,ops,SimpleNamespace(status=lambda:dict(backend='gcs',content='available',accounts='unavailable',check='read_only'))))
    install(app,public_config({'apiKey':'fixture-key','authDomain':'fixture-project.firebaseapp.com'},project_id='fixture-project',tenant=''))
    @app.get('/ready')
    def ready():return {'status':'ok'}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));base=f'http://127.0.0.1:{sock.getsockname()[1]}'
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=os.getenv('YGC_BROWSER_EXECUTABLE') or None)
                context=browser.new_context(viewport={'width':1280,'height':720})
                def intercept(route):
                    route.fulfill(content_type='text/javascript',body='export const initializeApp=config=>config;' if 'firebase-app.js' in route.request.url else SDK)
                context.route('https://www.gstatic.com/firebasejs/**',intercept)
                page=context.new_page()
                def open_console(email=None,verified=True):
                    page.goto(base+'/console');page.wait_for_function('window.YGCCloudConsoleReady===true')
                    page.evaluate('([email,verified])=>{sessionStorage.clear();if(email){sessionStorage.setItem("fixture-sdk-email",email);sessionStorage.setItem("verified-"+email,String(verified))}}',[email,verified])
                    page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                open_console()
                expect(page.locator('#consoleControls')).to_be_hidden();expect(page.locator('#consoleRefresh')).to_be_disabled();assert not calls
                open_console('member@example.invalid')
                expect(page.locator('#consoleControls')).to_be_hidden();assert not calls
                open_console('admin@example.invalid',False)
                expect(page.locator('#consoleControls')).to_be_hidden();assert not calls
                open_console('admin@example.invalid')
                expect(page.locator('#operationsStatus')).to_have_text('Offline')
                expect(page.locator('#contentStorageStatus')).to_have_text('Read access confirmed')
                expect(page.locator('#accountsStorageStatus')).to_have_text('Status unavailable. Refresh to try again.')
                expect(page.locator('#consoleIdentity')).to_have_text('<b>Operator</b>');assert page.locator('#consoleIdentity b').count()==0
                page.locator('#statusTab').focus();page.keyboard.press('ArrowRight')
                expect(page.locator('#maintenanceTab')).to_be_focused();expect(page.locator('#maintenancePanel')).to_be_visible()
                expect(page.locator('#operationsMessage')).to_have_value(ops.row['message']);assert page.locator('#operations img').count()==0
                page.select_option('#operationsMode','admin_only');expect(page.locator('#operationsMessage')).not_to_have_value(ops.row['message'])
                page.fill('#operationsMessage','Custom maintenance message');page.click('#operationsSave')
                expect(page.locator('#consoleStatus')).to_have_text('Settings saved.')
                assert calls[-1]==('write','admin-uuid',dict(mode='admin_only',message='Custom maintenance message',version=1))
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true');expect(page.locator('#operationsStatus')).to_have_text('Admin Only')
                page.click('#maintenanceTab');page.fill('#operationsMessage','Unsaved message');ops.row['version']+=1
                page.click('#operationsSave');expect(page.locator('#operationsSave')).to_be_disabled();expect(page.locator('#operationsMessage')).to_have_value('Unsaved message')
                page.click('#consoleRefresh');expect(page.locator('#operationsSave')).to_be_enabled()
                # Long content must scroll within each column, without increasing the body.
                page.evaluate('()=>{document.querySelector(".console-main-layer").insertAdjacentHTML("beforeend","<p>Long main</p>".repeat(100));document.querySelector(".console-detail-layer").insertAdjacentHTML("beforeend","<p>Long detail</p>".repeat(100))}')
                assert page.evaluate('()=>{const a=document.querySelector(".console-main-layer"),b=document.querySelector(".console-detail-layer");a.scrollTop=100;return a.scrollTop>0&&b.scrollTop===0&&document.documentElement.scrollHeight<=innerHeight}')
                assert page.evaluate('()=>{const a=document.querySelector(".console-main-layer"),b=document.querySelector(".console-detail-layer");b.scrollTop=80;return a.scrollTop===100&&b.scrollTop>0}')
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                directory=os.getenv('YGC_BROWSER_ARTIFACTS')
                if directory:
                    from pathlib import Path
                    Path(directory).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(directory)/'cloud-console-desktop.png'),full_page=True)
                ops.fail=RuntimeError('private database error');page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                expect(page.locator('#operationsSave')).to_be_disabled();expect(page.locator('#consoleRefresh')).to_be_enabled()
                assert 'private database error' not in page.content()
                ops.fail=None;page.click('#consoleRefresh');expect(page.locator('#operationsSave')).to_be_enabled()
                context.set_default_timeout(10000)
                ops.fail=PermissionError();page.click('#consoleRefresh');expect(page.locator('#consoleControls')).to_be_hidden();expect(page.locator('#consoleIdentity')).to_have_text('')
                ops.fail=None;page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                page.click('#consoleSignOut');expect(page.locator('#consoleControls')).to_be_hidden()
                open_console('admin@example.invalid');page.goto(base+'/account');page.wait_for_function('window.YGCCloudAccountReady===true');expect(page.locator('#consoleLink')).to_be_visible()
                page.goto(base+'/console');page.wait_for_function('window.YGCCloudConsoleReady===true')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('[data-language-picker]').select_option('ja');page.wait_for_function('document.documentElement.lang==="ja"&&window.YGCCloudConsoleReady===true')
                expect(page.locator('#operationsStatus')).to_have_text('管理者のみ')
                directory=os.getenv('YGC_BROWSER_ARTIFACTS')
                if directory:
                    from pathlib import Path
                    Path(directory).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(directory)/'cloud-console-mobile.png'),full_page=True)
                browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=10)
            if thread.is_alive():raise RuntimeError('Cloud Console test server did not stop')
    print('Cloud Console: identity gates, mode save/reload, version conflict, role revocation, SignOut, tabs, independent scrolling, mobile and Japanese passed.')

if __name__=='__main__':main()
