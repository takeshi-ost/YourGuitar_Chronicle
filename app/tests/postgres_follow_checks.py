"""Unpublished Follow contracts on disposable loopback PostgreSQL only."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid
import psycopg
from psycopg import sql, errors
from postgres_profile_visibility_checks import Workflow
from postgres_event_claim_checks import structure
from ygc.cloud_follows import CloudFollows, FollowConflict, FollowTargetMissing
from ygc.db.postgres import PostgresSettings, TARGETS, bootstrap, connect, migrate
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_operations import PostgresOperations, ServiceRestricted


def checks(w):
    service = CloudFollows(w.settings, w.operations)
    a, b = w.actor(), w.records['b']['id']
    original, content = w.snapshot(), w.snapshot('chronicle')
    assert service.state(a, b) == {'target_id': str(b), 'following': False}
    assert w.snapshot() == original
    assert service.set_following(a, b, True)['following'] is True
    first = w.snapshot()
    assert len(first['account_user_follows']) == 1
    assert service.set_following(a, b, True)['following'] is True
    assert w.snapshot() == first  # no duplicate relation or audit on replay
    assert service.state(w.actor('b'), w.records['a']['id'])['following'] is False
    for table in original:
        if table not in ('account_user_follows', 'account_metadata'):
            assert first[table] == original[table], table
    assert w.snapshot('chronicle') == content
    assert service.set_following(a, b, False)['following'] is False
    removed = w.snapshot()
    assert service.set_following(a, b, False)['following'] is False
    assert w.snapshot() == removed
    audits = [r for r in removed['account_metadata'] if r['key'].startswith('self_follow:')]
    assert len(audits) == 2
    import json
    assert [json.loads(r['value'])['following'] for r in sorted(audits, key=lambda r: json.loads(r['value'])['occurred_at'])] == [True, False]
    w.unchanged(ValueError, lambda: service.set_following(a, w.records['a']['id'], True))
    w.unchanged(FollowTargetMissing, lambda: service.set_following(a, 2**63-1, True))
    # Both endpoints are rechecked against Accounts, not Chronicle projection.
    for field, bad, good in [('disabled', 1, 0), ('ban_status', 'ban', 'normal'), ('account_type', 'source', 'user')]:
        w.seed_account('b', **{field: bad})
        for value in (True, False):
            w.unchanged(FollowTargetMissing, lambda: service.set_following(a, b, value))
        w.unchanged(FollowTargetMissing, lambda: service.state(a, b))
        w.seed_account('b', **{field: good})
        w.seed_account('a', **{field: bad})
        w.unchanged(PermissionError, lambda: service.set_following(a, b, True))
        w.seed_account('a', **{field: good})
    # Existing silent-ban semantics remain eligible; no new social restriction.
    w.seed_account('b', ban_status='silent_ban')
    assert service.set_following(a, b, True)['following']
    service.set_following(a, b, False)
    w.seed_account('b', ban_status='normal')
    for mode in ('read_only', 'offline', 'admin_only'):
        w.mode(mode)
        w.unchanged(ServiceRestricted, lambda: service.set_following(a, b, True))
        if mode == 'read_only': assert service.state(a, b)['following'] is False
        else: w.unchanged(ServiceRestricted, lambda: service.state(a, b))
    assert service.set_following(w.actor('admin'), b, True)['following']
    w.mode('offline')
    w.unchanged(ServiceRestricted, lambda: service.set_following(w.actor('admin'), b, False))
    w.mode('normal')
    # A failed audit rolls back the relation in the same Accounts transaction.
    with w.reject_inserts('account_metadata'):
        w.unchanged(errors.CheckViolation, lambda: service.set_following(a, b, True))
    with connect(w.owner, 'operations') as guard:
        guard.execute('SELECT pg_advisory_xact_lock(79432190)')
        w.unchanged(FollowConflict, lambda: service.set_following(a, b, True))
    # Concurrent identical commands either succeed idempotently or explicitly
    # conflict; neither duplicate rows/audits nor a silent automatic retry.
    before_audits = len(w.snapshot()['account_metadata'])
    barrier = Barrier(2)
    def register():
        barrier.wait(timeout=5)
        try:
            return service.set_following(a, b, True)['following']
        except FollowConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(), range(2)))
    assert True in results and all(r is True or r == 'conflict' for r in results)
    assert len(w.snapshot()['account_metadata']) == before_audits + 1
    w.seed_account('b', disabled=1)
    w.unchanged(FollowTargetMissing, lambda: service.state(a, b))
    w.seed_account('b', disabled=0)
    assert service.state(a, b)['following'] is True  # existing relation retained
    with w.reject_inserts('account_metadata'):
        w.unchanged(errors.CheckViolation, lambda: service.set_following(a, b, False))

    # Member directory is fixed-field, literal substring search and ID-keyset.
    for name in ('a', 'b'):
        w.seed_account(name, display_name='Same %_\\ name')
    rows = service.search(a, q='%_\\', limit=1)
    assert rows['total'] == '2' and len(rows['items']) == 1
    assert set(rows['items'][0]) == {'id', 'display_name', 'icon'}
    assert rows['items'][0]['icon'] is None
    second = service.search(a, q='%_\\', after=int(rows['next_after']), limit=1)
    assert second['total'] == '2' and second['next_after'] is None
    assert second['items'][0]['id'] != rows['items'][0]['id']
    assert service.search(a, q="' OR 1=1 --")['total'] == '0'
    assert service.search(a, q=w.actor('b'))['total'] == '0'  # UUID is not searchable
    third = w.actor('admin')
    # Membership alone permits third-party reads; following the subject is not required.
    service.set_following(third, b, False)
    assert not service.profile(third, b)['following']
    assert service.connections(third, b, direction='followers')['total'] == '1'
    service.set_following(third, b, True)
    page = service.connections(third, b, direction='followers')
    assert {r['id'] for r in page['items']} == {str(w.records['a']['id']), str(w.records['admin']['id'])}
    profile = service.profile(third, b)
    assert profile['followers_count'] == '2' and profile['following_count'] == '0'
    assert profile['following'] and not profile['is_self']
    assert service.profile(a, w.records['a']['id'])['is_self']
    assert service.connections(third, w.records['a']['id'], direction='following')['items'][0]['id'] == str(b)
    for field, bad, good in [('disabled', 1, 0), ('ban_status', 'ban', 'normal'), ('account_type', 'source', 'user')]:
        w.seed_account('a', **{field: bad})
        assert service.profile(third, b)['followers_count'] == '1'
        assert service.connections(third, b, direction='followers')['total'] == '1'
        assert service.search(third, q='Same')['total'] == '1'
        w.unchanged(PermissionError, lambda: service.search(a))
        w.unchanged(PermissionError, lambda: service.profile(a, b))
        w.unchanged(PermissionError, lambda: service.connections(a, b, direction='followers'))
        w.unchanged(FollowTargetMissing, lambda: service.profile(third, w.records['a']['id']))
        w.seed_account('a', **{field: good})
    for mode in ('read_only', 'offline', 'admin_only'):
        w.mode(mode)
        if mode == 'read_only':
            assert not service.profile(a, b)['can_write']
            assert service.search(a)['total'] == '3'
        else:
            w.unchanged(ServiceRestricted, lambda: service.search(a))
            w.unchanged(ServiceRestricted, lambda: service.profile(a, b))
            w.unchanged(ServiceRestricted, lambda: service.connections(a, b, direction='followers'))
    w.mode('normal')
    assert w.snapshot('chronicle') == content


def avatar_checks(w):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import Mock, patch
    from ygc.cloud_avatar import AvatarMissing
    from ygc.cloud_follow_routes import follow_router
    from ygc.identity_platform import VerifiedIdentity
    from test_cloud_avatar import png
    service = CloudFollows(w.settings, w.operations, w.storage)
    a, b = w.actor(), w.records['b']['id']
    w.avatars.set(w.actor('b'), png(), 'image/png')
    expected = w.avatars.get(w.actor('b'))
    # HTTP + real restricted PostgreSQL + actual normalized nonpersonal bytes.
    verifier = Mock(accounts=w.accounts)
    verifier.verify.return_value = VerifiedIdentity('synthetic-follow', 'a', '', True)
    app = FastAPI();app.include_router(follow_router(verifier, service))
    auth = {'Authorization':'Bearer synthetic'}
    with TestClient(app) as client:
        def read(status, headers=None):
            response = client.get(f'/api/auth/members/{b}/avatar', headers=auth if headers is None else headers)
            assert response.status_code == status, response.text if status != 200 else ''
            assert response.headers['cache-control'] == 'private, no-store'
            if status == 200: assert response.content == expected
            else: assert expected not in response.content
        service.set_following(a, b, False)
        for visibility in ('Public','Members','Followers','Private',None,'unsupported'):
            if visibility is None:
                # Current schema is non-null; unknown legacy spellings fail closed.
                continue
            w.seed_account('b', avatar_visibility=visibility)
            read(200 if visibility in ('Public','Members') else 404)
            assert service.avatar(w.actor('b'), b) == expected
        w.seed_account('b', avatar_visibility='Followers')
        service.set_following(a, b, True);read(200)
        # Read locks cover the source account, target policy and relationship
        # until the private storage read completes.
        original_get=w.storage.get
        def locked_get(reference):
            for query, params in [
                ('SELECT id FROM account_records WHERE id=%s FOR UPDATE NOWAIT', (b,)),
                ('SELECT id FROM account_records WHERE id=%s FOR UPDATE NOWAIT', (w.records['a']['id'],)),
                ('SELECT followed_user_id FROM account_user_follows WHERE follower_user_id=%s AND followed_user_id=%s FOR UPDATE NOWAIT', (w.records['a']['id'],b))]:
                try:
                    with connect(w.owner,'accounts') as con: con.execute(query,params)
                except errors.LockNotAvailable: pass
                else: raise AssertionError('Avatar authorization lock missing')
            return original_get(reference)
        with patch.object(w.storage,'get',side_effect=locked_get): read(200)
        service.set_following(a,b,False);read(404)
        # Actual visibility save changes the next read; it does not require a
        # new URL, browser cache busting or Chronicle projection to authorize.
        fields=w.service.own_visibility(w.actor('b'))['fields']
        for visibility in ('Members','Private'):
            fields={**fields,'avatar_visibility':visibility}
            w.service.edit_own_visibility(w.actor('b'),{'revision':w.service.own_visibility(w.actor('b'))['profile_revision'],'fields':fields})
            read(200 if visibility=='Members' else 404)
        w.unchanged(AvatarMissing,lambda:service.avatar(w.actor('admin'),b))
        read(401,{})
        verifier.verify.return_value=VerifiedIdentity('synthetic-follow','admin','',True)
        read(404)  # switching actor never inherits the prior viewer's rights
        verifier.verify.return_value=VerifiedIdentity('synthetic-follow','a','',True)
        w.seed_account('b',avatar_visibility='Public')
        for mode in ('read_only','offline','admin_only'):
            w.mode(mode);read(200 if mode=='read_only' else 403)
        w.mode('normal')
        for subject in ('a','b'):
            for field,bad,good in [('disabled',1,0),('ban_status','ban','normal'),('account_type','source','user')]:
                w.seed_account(subject,**{field:bad})
                with patch.object(w.storage,'get',side_effect=AssertionError('Unauthorized storage read')):
                    read(403 if subject=='a' else 404)
                w.seed_account(subject,**{field:good})
        reference=w.record('b')['avatar_storage_path']
        for invalid in ('/private/legacy.jpg','https://private.invalid/photo','gcs-avatar-v1:{}',None):
            w.seed_account('b',avatar_storage_path=invalid)
            with patch.object(w.storage,'get',side_effect=AssertionError('Unsafe reference read')):read(404)
        w.seed_account('b',avatar_storage_path=reference)
        before=w.snapshot(),w.snapshot('chronicle')
        read(200)
        assert (w.snapshot(),w.snapshot('chronicle'))==before
        w.avatars.set(w.actor('b'));read(404)
    print('PostgreSQL member avatars: normalized pinned private objects, all visibility/identity/mode gates, HTTP no-store, no guest/admin bypass, follow and policy revocation, read locks, safe legacy fallback and read-only side effects passed.')


def run(port):
    prefix = 'ygctest_follow_' + uuid.uuid4().hex[:10] + '_'
    runtime = prefix + 'app'
    owner = PostgresSettings('127.0.0.1', 'postgres', 'ygc-tests-only', port, prefix)
    settings = replace(owner, user=runtime)
    databases = []
    with psycopg.connect(host='127.0.0.1', port=port, dbname='postgres', user='postgres', password='ygc-tests-only', autocommit=True) as system:
        try:
            system.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(runtime), sql.Literal('ygc-tests-only')))
            for target in TARGETS:
                name = owner.database(target)
                system.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                databases.append(name)
                bootstrap(owner, target, runtime)
                migrate(owner, target, runtime)
            baseline = structure(owner, runtime)
            accounts, operations = PostgresAccounts(settings), PostgresOperations(settings)
            records = {name: accounts.ensure_identity(issuer='synthetic-follow', subject=name, display_name='Synthetic '+name) for name in ('admin', 'a', 'b')}
            with connect(owner, 'accounts') as con:
                con.execute("UPDATE account_records SET role='admin' WHERE app_user_id=%s", (records['admin']['app_user_id'],))
            accounts.drain_projection()
            w = Workflow(settings, owner, accounts, operations, records)
            w.mode('normal')
            checks(w)
            avatar_checks(w)
            assert structure(owner, runtime) == baseline
            print('PostgreSQL Follow foundation: direction, idempotency, canonical eligibility, modes, audit rollback, maintenance fence and unchanged schema/grants/Chronicle passed.')
        finally:
            for name in reversed(databases):
                system.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            system.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
