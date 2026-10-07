"""Real mode matrix, canonical role fencing, audit rollback and initial Admin."""
import json
import uuid
import time
import psycopg
from psycopg import sql
from ygc.db.postgres import PostgresSettings, bootstrap, migrate, connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ModeConflict, MODES
from ygc.admin_bootstrap_job import grant_first_admin


def run(port):
    prefix = 'ygctest_' + uuid.uuid4().hex[:12] + '_'
    role = prefix + 'app'
    owner = PostgresSettings('127.0.0.1','postgres','ygc-tests-only',port,prefix)
    app = PostgresSettings('127.0.0.1',role,'ygc-tests-only',port,prefix)
    created = []
    def rejected(kind, operation):
        try: operation()
        except kind: return
        raise AssertionError('Expected ' + kind.__name__)
    with psycopg.connect(host='127.0.0.1',port=port,dbname='postgres',user='postgres',password='ygc-tests-only',autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal('ygc-tests-only')))
            for target in ('accounts','chronicle','operations','authentication'):
                name = owner.database(target)
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created.append(name)
                bootstrap(owner,target,role)
                migrate(owner,target,role)
            accounts, operations = PostgresAccounts(app), PostgresOperations(app)
            a = accounts.ensure_identity(issuer='issuer',subject='admin',display_name='Admin')
            b = accounts.ensure_identity(issuer='issuer',subject='member',display_name='Member')
            aid, bid = a['app_user_id'], b['app_user_id']
            assert grant_first_admin(app,aid,'test-operator')
            assert not grant_first_admin(app,aid,'test-operator')
            rejected(PermissionError,lambda: grant_first_admin(app,bid,'test-operator'))
            with connect(app,'accounts') as con:
                assert con.execute("SELECT COUNT(*) AS n FROM account_metadata WHERE key LIKE 'admin_bootstrap:%'").fetchone()['n'] == 1
            assert operations.public_status()['mode'] == 'offline'
            version = 0
            for mode in MODES:
                state = operations.set_mode(aid,mode=mode,message='Test',version=version)
                version = state['version']
                assert operations.details(aid)['mode'] == mode
                for actor in (None,bid,aid):
                    for kind in ('public_read','user_read','user_write','admin_read','admin_write'):
                        expected = ((kind.startswith('admin_') and actor==aid) or
                            (not kind.startswith('admin_') and (not kind.startswith('user_') or actor is not None) and
                             (mode=='normal' or (mode=='read_only' and kind.endswith('_read')) or (mode=='admin_only' and actor==aid))))
                        def access():
                            with operations.access(kind,actor): pass
                        if expected: access()
                        else: rejected(PermissionError,access)
            rejected(ModeConflict,lambda: operations.set_mode(aid,mode='normal',message='',version=0))
            rejected(ValueError,lambda: operations.set_mode(aid,mode='invalid',message='',version=version))
            with connect(app,'operations') as con:
                assert con.execute('SELECT COUNT(*) AS n FROM events').fetchone()['n'] == 4
                audit = json.loads(con.execute('SELECT reason FROM events ORDER BY id LIMIT 1').fetchone()['reason'])
                assert audit['actor_app_user_id'] == aid
            # Avatar writes use the locked Accounts connection and commit while
            # the Operations mode lock is still held. No user image reaches GCP.
            from test_cloud_avatar import Storage, png
            from ygc.cloud_avatar import CloudAvatar, decode_reference
            store = Storage()
            avatars = CloudAvatar(operations,store)
            for mode in MODES:
                version = operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                for user, administrative in ((bid,False),(aid,False),(aid,True)):
                    allowed = administrative or mode=='normal' or (mode=='admin_only' and user==aid)
                    action = lambda: avatars.set(user,png(),'image/png',admin=administrative)
                    if allowed:
                        action()
                        with connect(app,'accounts') as con:
                            value=con.execute('SELECT avatar_storage_path FROM account_records WHERE app_user_id=%s',(user,)).fetchone()['avatar_storage_path']
                            assert store.get(decode_reference(value))==avatars.get(user,admin=administrative)
                            assert con.execute('SELECT COUNT(*) AS n FROM account_metadata WHERE key LIKE %s',('avatar:%',)).fetchone()['n']>0
                    else: rejected(PermissionError,action)
            # Failed Accounts audit rolls back the reference and compensates the new object.
            with connect(owner,'accounts') as con:
                before=con.execute('SELECT avatar_storage_path FROM account_records WHERE app_user_id=%s',(aid,)).fetchone()['avatar_storage_path']
                con.execute(sql.SQL('REVOKE INSERT ON account_metadata FROM {}').format(sql.Identifier(role)))
            size=len(store.objects)
            rejected(psycopg.errors.InsufficientPrivilege,lambda:avatars.set(aid,png(),'image/png',admin=True))
            assert len(store.objects)==size
            with connect(owner,'accounts') as con:
                assert con.execute('SELECT avatar_storage_path FROM account_records WHERE app_user_id=%s',(aid,)).fetchone()['avatar_storage_path']==before
                con.execute(sql.SQL('GRANT INSERT ON account_metadata TO {}').format(sql.Identifier(role)))
            assert avatars.set(aid,admin=True)=={'has_avatar':False}
            assert len(store.objects)==size  # Objects remain available to earlier backups.
            # Concurrent mode changes and role changes cannot pass this write lock.
            with operations.account_access('admin_write',aid):
                def change_mode():
                    with connect(app,'operations') as con:
                        con.execute('SET statement_timeout=100')
                        con.execute("UPDATE settings SET mode='normal' WHERE id=1")
                rejected(psycopg.errors.QueryCanceled,change_mode)
                def change_role():
                    with connect(app,'accounts') as con:
                        con.execute('SET statement_timeout=100')
                        con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s",(aid,))
                rejected(psycopg.errors.QueryCanceled,change_role)
            print('PostgreSQL avatars: mode matrix, canonical self, atomic audit rollback, retained backup objects and role/mode write fencing passed.')
            from ygc.cloud_guitars import CloudGuitars,FIELDS,GuitarMissing
            guitars=CloudGuitars(app,operations)
            with connect(app,'chronicle') as con:
                for number in range(1,29):
                    con.execute('INSERT INTO individuals(manufacturer,model,normalized_manufacturer,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)',
                        ('Maker','Literal %_'+str(number),'maker','now','now'))
            first=guitars.list(aid,limit=25)
            assert first['total']==28
            assert len(first['items'])==25 and first['next_after'] is not None
            second=guitars.list(aid,after=first['next_after'],limit=25)
            assert second['total']==28
            assert guitars.list(aid,q='Model 28')['total']==28
            assert len(second['items'])==3 and second['next_after'] is None
            assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}
            assert set(guitars.detail(aid,first['items'][0]['id']))==set(FIELDS)
            assert len(guitars.list(aid,q='%_',limit=50)['items'])==28
            assert guitars.list(aid,q="' OR 1=1 --")['items']==[]
            assert guitars.list(aid,q='unknown')['items']==[]
            rejected(GuitarMissing,lambda:guitars.detail(aid,9999))
            rejected(PermissionError,lambda:guitars.list(bid))
            # Administrator read is available in every service mode.
            for mode in MODES:
                version=operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                assert len(guitars.list(aid)['items'])==25
            print('PostgreSQL guitar reads: bounded keyset pages, literal wildcard search, fixed fields, missing IDs, Admin mode matrix and member refusal passed.')
            from ygc.cloud_users import CloudUsers,FIELDS as USER_FIELDS,UserMissing
            user_browser=CloudUsers(app,operations)
            users_page=user_browser.list(aid)
            assert users_page['total']>=2 and users_page['items']
            account_id=users_page['items'][0]['id']
            user_record=user_browser.detail(aid,account_id)
            assert set(user_record)==set(USER_FIELDS)|{'profile_revision'}
            assert not {'identity_subject','identity_provider','avatar_storage_path','date_of_birth'} & set(user_record)
            assert user_browser.list(aid,q='not-present-fixture')['items']==[]
            assert user_browser.list(aid,q='not-present-fixture')['total']==users_page['total']
            assert user_browser.list(aid,after=account_id)['total']==users_page['total']
            rejected(UserMissing,lambda:user_browser.detail(aid,999999))
            rejected(PermissionError,lambda:user_browser.list(bid))
            for mode in MODES:
                version=operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                assert user_browser.detail(aid,account_id)['id']==account_id
            from ygc.cloud_profile import ProfileConflict
            def profile():return user_browser.detail(aid,b['id'])
            original=profile()
            updates=dict(display_name='Updated member',location_country='Japan',location_region='Tokyo',bio='Updated bio')
            for mode in MODES:
                version=operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                before=profile();result=user_browser.edit_profile(aid,b['id'],dict(revision=before['profile_revision'],fields=updates))
                after=profile();assert after['display_name']=='Updated member' and after['profile_revision']==result['profile_revision']
                assert all(after[k]==original[k] for k in ('id','app_user_id','account_type','role','disabled','ban_status'))
                rejected(ProfileConflict,lambda:user_browser.edit_profile(aid,b['id'],dict(revision=before['profile_revision'],fields=updates)))
            rejected(PermissionError,lambda:user_browser.edit_profile(bid,b['id'],dict(revision=profile()['profile_revision'],fields=updates)))
            with connect(app,'operations') as guard:
                guard.execute('SELECT pg_advisory_xact_lock(79432190)')
                rejected(ProfileConflict,lambda:user_browser.edit_profile(aid,b['id'],dict(revision=profile()['profile_revision'],fields=updates)))
            before=profile()
            with connect(owner,'accounts') as con:con.execute(sql.SQL('REVOKE INSERT ON account_metadata FROM {}').format(sql.Identifier(role)))
            rejected(psycopg.errors.InsufficientPrivilege,lambda:user_browser.edit_profile(aid,b['id'],dict(revision=before['profile_revision'],fields={**updates,'display_name':'Rollback'})))
            assert profile()==before
            with connect(owner,'accounts') as con:con.execute(sql.SQL('GRANT INSERT ON account_metadata TO {}').format(sql.Identifier(role)))
            with connect(app,'accounts') as con:
                audits=con.execute("SELECT value FROM account_metadata WHERE key LIKE 'admin_profile:%'").fetchall()
                assert len(audits)==4 and all(json.loads(r['value'])['actor_app_user_id']==aid for r in audits)
            print('PostgreSQL Admin profiles: all modes, canonical authority, CAS, maintenance exclusion, audit atomicity and retained identity/roles passed.')
            # Self edits use only the locked canonical actor, and never Admin mode bypass.
            for mode in MODES:
                version=operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                for actor,target in ((bid,b),(aid,a)):
                    if mode=='normal' or (mode=='admin_only' and actor==aid):
                        own=user_browser.own_profile(actor)
                        before_other=user_browser.detail(aid,a['id'] if actor==bid else b['id'])
                        result=user_browser.edit_own_profile(actor,dict(revision=own['profile_revision'],fields=updates))
                        assert result['id']==str(target['id'])
                        assert user_browser.own_profile(actor)['fields']==updates
                        assert user_browser.detail(aid,a['id'] if actor==bid else b['id'])==before_other
                        rejected(ProfileConflict,lambda:user_browser.edit_own_profile(actor,dict(revision=own['profile_revision'],fields=updates)))
                    else:
                        before=user_browser.detail(aid,target['id'])
                        rejected(PermissionError,lambda:user_browser.edit_own_profile(actor,dict(revision=before['profile_revision'],fields=updates)))
                        assert user_browser.detail(aid,target['id'])==before
                        if mode=='read_only':assert user_browser.own_profile(actor)['profile_revision']==before['profile_revision']
                        else:rejected(PermissionError,lambda:user_browser.own_profile(actor))
            version=operations.set_mode(aid,mode='normal',message='Test',version=version)['version']
            before=user_browser.own_profile(bid)
            with connect(app,'operations') as guard:
                guard.execute('SELECT pg_advisory_xact_lock(79432190)')
                rejected(ProfileConflict,lambda:user_browser.edit_own_profile(bid,dict(revision=before['profile_revision'],fields=updates)))
            with connect(owner,'accounts') as con:con.execute(sql.SQL('REVOKE INSERT ON account_metadata FROM {}').format(sql.Identifier(role)))
            rejected(psycopg.errors.InsufficientPrivilege,lambda:user_browser.edit_own_profile(bid,dict(revision=before['profile_revision'],fields=updates)))
            assert user_browser.own_profile(bid)==before
            with connect(owner,'accounts') as con:con.execute(sql.SQL('GRANT INSERT ON account_metadata TO {}').format(sql.Identifier(role)))
            with connect(app,'accounts') as con:
                audits=con.execute("SELECT value FROM account_metadata WHERE key LIKE 'self_profile:%'").fetchall()
                assert len(audits)==3 and all(json.loads(r['value'])['actor_app_user_id']==json.loads(r['value'])['target_app_user_id'] for r in audits)
            print('PostgreSQL self profiles: own canonical target, service mode matrix, CAS, exclusion, atomic audit and other accounts unchanged passed.')
            # Materialized current ownership is authoritative; unaccepted Former Owner claims are hidden.
            assert accounts.drain_projection()>0
            gids=[r['id'] for r in first['items']]
            with connect(app,'chronicle') as con:
                con.execute('UPDATE individuals SET current_owner_user_id=%s WHERE id=ANY(%s)',(account_id,gids))
            page=user_browser.guitars(aid,account_id,kind='owned',limit=1)
            assert page['total']==25 and len(page['items'])==1 and page['next_after'] is not None
            following=user_browser.guitars(aid,account_id,kind='owned',after=page['next_after'],limit=1)
            assert following['items'][0]['id']>page['items'][0]['id']
            for mode in MODES:
                version=operations.set_mode(aid,mode=mode,message='Test',version=version)['version']
                assert user_browser.guitars(aid,account_id,kind='owned')['total']==25
                for actor in (aid,bid):
                    for kind in ('owned','formerly_owned'):
                        if mode in ('normal','read_only') or (mode=='admin_only' and actor==aid):
                            target=a if actor==aid else b
                            assert user_browser.own_guitars(actor,kind=kind)==user_browser.guitars(aid,target['id'],kind=kind)
                        else:rejected(PermissionError,lambda:user_browser.own_guitars(actor,kind=kind))
            rejected(PermissionError,lambda:user_browser.guitars(bid,account_id,kind='owned'))
            rejected(UserMissing,lambda:user_browser.guitars(aid,999999,kind='owned'))
            assert user_browser.guitars(aid,account_id,kind='formerly_owned')['items']==[]
            with connect(app,'chronicle') as con:con.execute('UPDATE individuals SET current_owner_user_id=NULL WHERE id=ANY(%s)',(gids,))
            with connect(app,'chronicle') as con:
                link=con.execute("INSERT INTO user_guitars(user_id,individual_id,ownership_status,created_at,updated_at) VALUES(%s,%s,'former_owner','now','now') RETURNING id",(account_id,gids[0])).fetchone()['id']
                claim=con.execute("INSERT INTO claims(individual_id,author_user_id,claim_type,field_name,value_text,ownership_kind,ownership_source,verification_status,created_at,updated_at) VALUES(%s,%s,'ownership','owner',%s,'acquire','former_owner','unverified','now','now') RETURNING id",(gids[0],account_id,str(account_id))).fetchone()['id']
            assert user_browser.guitars(aid,account_id,kind='formerly_owned')['items']==[]
            with connect(app,'chronicle') as con:con.execute("UPDATE claims SET verification_status='positive' WHERE id=%s",(claim,))
            assert user_browser.guitars(aid,account_id,kind='formerly_owned')['items'][0]['id']==gids[0]
            with connect(app,'chronicle') as con:con.execute("UPDATE claims SET verification_status='negative' WHERE id=%s",(claim,))
            assert user_browser.guitars(aid,account_id,kind='formerly_owned')['items']==[]
            with connect(app,'chronicle') as con:
                con.execute('DELETE FROM claims WHERE id=%s',(claim,));con.execute('DELETE FROM user_guitars WHERE id=%s',(link,))
            previous_mode=operations.details(aid)
            version=operations.set_mode(aid,mode='normal',message='Test',version=version)['version']
            # Projection UUID mismatch cannot expose an unrelated numeric-ID participant.
            with connect(app,'chronicle') as con:
                con.execute('UPDATE individuals SET current_owner_user_id=%s WHERE id=%s',(a['id'],gids[0]))
            assert user_browser._guitars(a['id'],'wrong-fixture-uuid','owned',0,25)['total']==0
            assert user_browser.own_guitars(aid,kind='owned')['total']==1
            with connect(app,'chronicle') as con:con.execute('UPDATE individuals SET current_owner_user_id=NULL WHERE id=%s',(gids[0],))
            version=operations.set_mode(aid,mode=previous_mode['mode'],message=previous_mode['message'],version=version)['version']
            print('PostgreSQL self ownership: canonical ID/UUID, mode matrix, shared visibility and other-account isolation passed.')
            print('PostgreSQL user reads: canonical Accounts, total/search/cursor, fixed profile fields, all modes and member refusal passed.')
            # Populated v2 projection rows contain timezone-aware timestamps.
            from ygc.cloud_db_snapshot import snapshot,verify_snapshot
            for target in ('accounts','chronicle'):
                data,meta=snapshot(app,target)
                assert verify_snapshot(data,target,meta['sha256'])['schema_version']==(3 if target=='chronicle' else 2)
            print('PostgreSQL snapshots: current revisions and populated outbox/receipts with timestamp precision passed.')
            # Intent persists before dispatch; retries and target conflicts do not invoke twice.
            from ygc.cloud_backup_control import BackupControl,BackupBusy
            from ygc.cloud_backup_job import save
            from unittest.mock import Mock
            from test_cloud_avatar import Storage
            job_client=Mock();job_client.start.return_value='private-operation';job_client.status.return_value='running'
            controls=BackupControl(operations,job_client);token=str(uuid.uuid4())
            assert controls.start(aid,'accounts',token)['state']=='running'
            assert controls.start(aid,'accounts',token)['state']=='running'
            assert job_client.start.call_count==1
            rejected(BackupBusy,lambda:controls.start(aid,'accounts',str(uuid.uuid4())))
            rejected(PermissionError,lambda:controls.start(bid,'chronicle',str(uuid.uuid4())))
            avatar_store=store
            store=Storage();store.next_id=avatar_store.next_id
            assert save(app,store,'accounts','fixture',request_id=token)['saved']
            assert controls.status(aid,'accounts')['state']=='succeeded'
            print('PostgreSQL manual backup: persistent intent, repeated UUID, per-target conflict, member denial and committed archive success passed.')
            from ygc.cloud_backup_policy import configure,policy,prune
            before=policy(operations,aid,'chronicle')
            updated=configure(operations,aid,'accounts',1,True,48)
            assert updated['enabled'] is True and updated['generations']==1 and updated['interval_hours']==48
            assert policy(operations,aid,'chronicle')==before
            rejected(PermissionError,lambda:configure(operations,bid,'accounts',1,True,1))
            save(app,store,'accounts','fixture-2')
            assert prune(app,store,'accounts')==1
            assert len(store.objects)==1
            configure(operations,aid,'accounts',10,False,24)
            assert save(app,store,'accounts','scheduled-fixture',scheduled=True)['skipped']
            with connect(app,'operations') as con:
                con.execute("UPDATE backup_schedules SET enabled=1,next_run=0 WHERE target='accounts'")
            assert save(app,store,'accounts','scheduled-due',scheduled=True)['saved']
            assert policy(operations,aid,'accounts')['next_run']>time.time()
            assert save(app,store,'accounts','scheduled-repeat',scheduled=True)['skipped']
            configure(operations,aid,'accounts',10,False,24)
            print('PostgreSQL backup policy: independent persistent settings, strict Admin gate, exact archive pruning and disabled scheduled save passed.')
            from postgres_maintenance_checks import run as maintenance_checks
            store.objects.update(avatar_store.objects)
            from postgres_application_checks import run as application_checks
            application_checks(app,accounts,operations,store,aid,bid)
            maintenance_checks(app,accounts,operations,store,aid,bid)
            version=operations.details(aid)['version']
            from postgres_crawl_checks import run as crawl_checks
            crawl_checks(app,accounts,operations,store,aid)
            from postgres_review_checks import run as review_checks
            review_checks(app,accounts,operations,store,aid,bid)
            version=operations.details(aid)['version']
            # A failed audit must roll back the mode update too.
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('REVOKE INSERT ON events FROM {}').format(sql.Identifier(role)))
            rejected(psycopg.errors.InsufficientPrivilege,lambda: operations.set_mode(aid,mode='normal',message='',version=version))
            assert operations.details(aid)['version'] == version
            prior_policy=policy(operations,aid,'accounts')
            rejected(psycopg.errors.InsufficientPrivilege,lambda: configure(operations,aid,'accounts',1,True,1))
            assert policy(operations,aid,'accounts')==prior_policy
            with connect(owner,'operations') as con:
                con.execute(sql.SQL('GRANT INSERT ON events TO {}').format(sql.Identifier(role)))
            # Role changes cannot race an admitted administrative operation.
            with operations.access('admin_read',aid):
                def revoke():
                    with connect(app,'accounts') as con:
                        con.execute('SET statement_timeout=100')
                        con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s",(aid,))
                rejected(psycopg.errors.QueryCanceled,revoke)
            with connect(app,'accounts') as con:
                con.execute("UPDATE account_records SET role='member' WHERE app_user_id=%s",(aid,))
            rejected(PermissionError,lambda: operations.details(aid))
            with connect(app,'accounts') as con:
                con.execute("UPDATE account_records SET role='admin',disabled=1 WHERE app_user_id=%s",(aid,))
            rejected(PermissionError,lambda: operations.details(aid))
            print('PostgreSQL operations: all modes/actors, first Admin, repeat/refusal, version conflict, audit rollback and live role fencing passed.')
        finally:
            for name in reversed(created): admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
