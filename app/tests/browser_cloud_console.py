"""Cloud Console UI journeys; Google and stores are replaced only in this fixture."""
import json
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
        policies={t:dict(target=t,enabled=0,interval_hours=24,generations=10,next_run=0,last_at=None,last_status=None,last_error=None) for t in ('accounts','chronicle','operations','authentication')}
        @contextmanager
        def access(self, kind, actor):
            if self.fail:raise self.fail
            if actor!='admin-uuid':raise PermissionError()
            class CatalogConnection:
                def execute(self,query,params):
                    if query.startswith('SELECT * FROM backup_schedules'):
                        return SimpleNamespace(fetchone=lambda:dict(ops.policies[params[0]]))
                    if query.startswith('UPDATE backup_schedules'):
                        generations,enabled,interval,next_run,target=params
                        ops.policies[target].update(generations=generations,enabled=enabled,interval_hours=interval,next_run=next_run)
                        return SimpleNamespace()
                    if query.startswith('INSERT INTO events'):return SimpleNamespace()
                    target=params[1]
                    records=[{'reason':json.dumps(dict(kind='db_backup_v1',backup_id='00000000-0000-4000-8000-000000000001',target=target,created_at='2026-10-05T00:00:00Z',schema_version=2,tables=42 if target=='chronicle' else 8,rows=3))}] if target in ('chronicle','accounts') else []
                    return SimpleNamespace(fetchall=lambda:records)
            yield CatalogConnection(),dict(self.row),{}
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
    from ygc.cloud_guitar_routes import guitar_router
    from ygc.cloud_guitars import FIELDS,GuitarMissing
    guitar_reads=[]
    rows=[dict.fromkeys(FIELDS) | dict(id=i,manufacturer='<img src=x onerror=alert(1)>',model='Model '+str(i),year='1960',serial_number='S'+str(i)) for i in range(1,29)]
    class Guitars:
        def list(self,actor,*,q,after,limit):
            with ops.access('admin_read',actor):
                guitar_reads.append(actor)
                matching=[r for r in rows if r['id']>after and q.lower() in r['model'].lower()]
                return dict(items=matching[:limit],next_after=matching[limit-1]['id'] if len(matching)>limit else None)
        def detail(self,actor,individual_id):
            with ops.access('admin_read',actor):
                if not 1<=individual_id<=len(rows):raise GuitarMissing()
                return rows[individual_id-1]
    app.include_router(guitar_router(verifier,Guitars()))
    from ygc.cloud_backup_routes import backup_router
    backup_calls=[]
    class BackupControl:
        states={}
        def start(self,actor,target,token):
            with ops.access('admin_write',actor):
                backup_calls.append((actor,target,token))
                self.states[target]=dict(target=target,request_id=token,state='running',created_at='now')
                return self.states[target]
        def status(self,actor,target):
            with ops.access('admin_read',actor):
                if target not in self.states:return dict(target=target,state='idle')
                self.states[target]['state']='succeeded'
                return self.states[target]
    maintenance_calls=[]
    class Maintenance:
        def start(self,actor,data):
            with ops.access('admin_write',actor):
                assert ops.row['mode']!='normal'
                assert data['confirmation']==data['target']
                maintenance_calls.append(data)
                return dict(state='running',target=data['target'],action=data['action'])
        def status(self,actor,target):
            return dict(state='succeeded' if maintenance_calls else 'idle',target=target)
    app.include_router(backup_router(verifier,ops,BackupControl(),Maintenance()))
    from ygc.cloud_crawl_routes import crawl_router
    crawl_calls=[]
    class Crawl:
        reads=0
        config=dict(summary_limit=2000,year_min=1950,year_max=1980,interval_hours=1,enabled=False,available=True,category='electric_acoustic',next_run=0,last_at=None,runs=[],request={'state':'idle'})
        def details(self,actor):
            with ops.access('admin_read',actor):
                if crawl_calls:
                    self.reads+=1;self.config['request']={'state':'running' if self.reads==1 else 'succeeded'}
                return self.config
        def configure(self,actor,data):
            with ops.access('admin_write',actor):self.config.update(data);return self.config
        def start(self,actor,data):
            with ops.access('admin_write',actor):
                crawl_calls.append(data);self.config['last_at']='2026-10-05T00:00:00Z'
                self.config['runs']=[dict(started_at=self.config['last_at'],status='ok',phase='done',pages_discovered=12,pages_fetched=4,observations_created=2)]
                return {'state':'running'}
    app.include_router(crawl_router(verifier,Crawl()))

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
                expect(page.locator('#cloudCrawl')).to_be_visible()
                expect(page.locator('#crawlLimit')).to_have_value('2000');page.locator('#crawlLimit').fill('3');page.locator('#crawlYearMin').fill('1960');page.locator('#crawlInterval').fill('2');page.locator('#crawlConfigSave').click()
                expect(page.locator('#crawlYearMin')).to_have_value('1960')
                page.locator('#crawlTab').click();page.locator('#crawlAuto').check()
                expect(page.locator('#crawlAuto')).to_be_checked()
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                expect(page.locator('#crawlYearMin')).to_have_value('1960');expect(page.locator('#crawlInterval')).to_have_value('2');expect(page.locator('#crawlLimit')).to_have_value('3')
                page.locator('#crawlNow').click();expect(page.locator('#crawlStatus')).to_have_text('Crawl is running…')
                page.locator('#crawlTab').click();expect(page.locator('#crawlAuto')).to_be_enabled();page.locator('#crawlAuto').uncheck()
                expect(page.locator('#crawlStatus')).to_have_text('Crawl completed.');expect(page.locator('#crawlAuto')).not_to_be_checked()
                assert len(crawl_calls)==1 and crawl_calls[0]['summary_limit']==3 and crawl_calls[0]['year_min']==1960
                expect(page.locator('#crawlRows tr')).to_have_count(1)
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                expect(page.locator('#crawlRows tr')).to_have_count(1);assert len(crawl_calls)==1

                expect(page.locator('#contentStorageStatus')).to_have_text('Read access confirmed')
                expect(page.locator('#accountsStorageStatus')).to_have_text('Status unavailable. Refresh to try again.')
                expect(page.locator('#consoleIdentity')).to_have_text('<b>Operator</b>');assert page.locator('#consoleIdentity b').count()==0
                expect(page.locator('#backupRows tr')).to_have_count(1)
                expect(page.locator('#backupRows')).to_contain_text('42')
                page.locator('#backupTarget').select_option('accounts');expect(page.locator('#backupRows')).to_contain_text('8')
                page.locator('#backupTarget').select_option('operations');expect(page.locator('#backupRows tr')).to_have_count(0)
                expect(page.locator('#backupStatus')).to_have_text('No saved snapshots for this database.')
                page.locator('#backupTarget').select_option('accounts')
                expect(page.locator('#backupKeep')).to_have_value('10')
                page.locator('#backupKeep').fill('12');page.locator('#backupInterval').fill('48');page.locator('#backupScheduled').check();page.locator('#backupPolicySave').click()
                expect(page.locator('#backupPolicyStatus')).to_have_text('Backup settings saved.')
                page.locator('#backupTarget').select_option('chronicle');expect(page.locator('#backupKeep')).to_have_value('10')
                page.locator('#backupTarget').select_option('accounts');expect(page.locator('#backupKeep')).to_have_value('12');expect(page.locator('#backupScheduled')).to_be_checked()
                expect(page.locator('#backupSave')).to_be_enabled()
                page.locator('#backupSave').click()
                expect(page.locator('#backupSaveStatus')).to_have_text('Saving this database…')
                expect(page.locator('#backupSave')).to_be_disabled()
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
                page.locator('#backupTarget').select_option('accounts')
                expect(page.locator('#backupSaveStatus')).to_have_text('Saved and read-back verified.')
                expect(page.locator('#backupSave')).to_be_enabled()
                assert len(backup_calls)==1 and backup_calls[0][:2]==('admin-uuid','accounts')
                page.locator('#backupRows button').first.click()
                expect(page.locator('#backupDialog')).to_be_visible()
                expect(page.locator('#backupConfirm')).to_be_disabled()
                page.mouse.click(2,2);expect(page.locator('#backupDialog')).to_be_hidden();assert not maintenance_calls
                page.locator('#backupRows button').first.click()
                page.locator('#backupConfirmation').fill('chronicle');expect(page.locator('#backupConfirm')).to_be_disabled()
                page.locator('#backupConfirmation').fill('accounts');page.locator('#backupConfirm').click()
                expect(page.locator('#backupMaintenanceStatus')).to_have_text('Applying database maintenance…')
                expect(page.locator('#backupReset')).to_be_disabled()
                expect(page.locator('#backupMaintenanceStatus')).to_have_text('Database maintenance completed.',timeout=12000)
                assert len(maintenance_calls)==1 and maintenance_calls[0]['action']=='restore'
                page.locator('#backupReset').click();page.locator('#backupConfirmation').fill('accounts');page.locator('#backupConfirm').click()
                expect(page.locator('#backupMaintenanceStatus')).to_have_text('Database maintenance completed.',timeout=12000)
                assert len(maintenance_calls)==2 and maintenance_calls[-1]['backup_id'] is None
                expect(page.locator('#guitarRows tr')).to_have_count(25)
                expect(page.locator('#guitarStatus')).to_have_text('25 guitars on this page')
                expect(page.locator('#guitarPrevious')).to_be_disabled()
                expect(page.locator('#guitarNext')).to_be_enabled()
                assert page.locator('#guitarRows img').count()==0
                page.locator('#guitarNext').click();expect(page.locator('#guitarRows tr')).to_have_count(3)
                expect(page.locator('#guitarStatus')).to_have_text('3 guitars on this page')
                expect(page.locator('#guitarPrevious')).to_be_enabled()
                expect(page.locator('#guitarNext')).to_be_disabled()
                page.locator('#guitarPrevious').click();expect(page.locator('#guitarRows tr')).to_have_count(25)
                page.locator('#guitarRows button').first.click()
                expect(page.locator('#guitarDetailFields')).to_contain_text('Model 1')
                assert page.locator('#guitarDetailFields img').count()==0
                assert page.evaluate('document.documentElement.scrollHeight<=innerHeight')
                page.locator('#guitarSearch').fill('Model 28');page.locator('#guitarSearchSubmit').click()
                expect(page.locator('#guitarRows tr')).to_have_count(1)
                expect(page.locator('#guitarStatus')).to_have_text('1 guitars on this page')
                expect(page.locator('#guitarPrevious')).to_be_disabled();expect(page.locator('#guitarNext')).to_be_disabled()
                page.locator('#guitarSearch').fill('unknown');page.locator('#guitarSearchSubmit').click()
                expect(page.locator('#guitarStatus')).to_have_text('No guitars found.')
                page.reload();page.wait_for_function('window.YGCCloudConsoleReady===true')
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
