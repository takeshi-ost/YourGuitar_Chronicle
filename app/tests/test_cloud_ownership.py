"""Cloud Transfer/Release boundaries using the canonical portable algorithms."""
from contextlib import contextmanager
import sqlite3
from unittest.mock import Mock

import pytest

from ygc.claim_revision import ClaimConflict
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_ownership import CloudOwnership, ownership_revision
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.repository import Repository


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    repo = Repository(tmp_path / 'ownership.db')
    repo.init_db()
    with repo.connect() as con:
        con.execute('ALTER TABLE users ADD COLUMN app_user_id TEXT')
    a, b, c = (repo.create_user(name) for name in ('From', 'Recipient', 'Outsider'))
    individual, *_ = repo.create_initial_listing_claim(a, manufacturer='Fixture', model='Transfer',
        serial_number='CLOUD-TRANSFER', media_storage_path='private/fixture.jpg', occurred_at='2020-01-01')
    service = CloudOwnership(None, None)

    @contextmanager
    def transaction(actor, individual=None, *, claim=None, write=False, extra_ids=(), accept=False):
        with repo.connect() as con:
            if write:
                con.execute('BEGIN IMMEDIATE')
            if claim is not None:
                from ygc.cloud_ownership import transfer_row
                individual = transfer_row(con, claim, actor)['individual_id']
            service._visible(con, individual, actor)
            repo._transfer_user(con, actor)
            if accept:
                row = con.execute('SELECT from_user_id,to_user_id FROM claim_transfers WHERE claim_id=?', (claim,)).fetchone()
                for value in row:
                    repo._transfer_user(con, value)
            for value in extra_ids:
                repo._transfer_user(con, value)
            yield BoundRepository(con), actor, True

    @contextmanager
    def inbox_transaction(actor, after, limit):
        with repo.connect() as con:
            repo._transfer_user(con, actor)
            yield BoundRepository(con), actor, True

    monkeypatch.setattr(service, 'transaction', transaction)
    monkeypatch.setattr(service, 'inbox_transaction', inbox_transaction)
    return repo, service, a, b, c, individual


def user_guitars(repo, user):
    with repo.connect() as con:
        return con.execute('SELECT * FROM user_guitars WHERE user_id=?', (user,)).fetchall()


def create(workflow, target=None):
    _, service, a, b, _, individual = workflow
    view = service.view(a, individual)
    return service.create(a, individual, {'to_user_id': str(target or b), 'revision': view['revision']})['transfer']


def resolve(service, user, transfer, action):
    return service.resolve(user, int(transfer['id']), {'action': action, 'revision': transfer['revision']})['transfer']


def test_transfer_agreement_owner_history_and_authority(workflow):
    repo, service, a, b, c, individual = workflow
    initial = service.view(a, individual)
    assert initial['is_current_owner'] and initial['can_transfer'] and initial['can_release']
    transfer = create(workflow)
    assert transfer['state'] == 'pending' and transfer['verification_status'] == 'unverified'
    assert transfer['acceptance'] is None and transfer['occurred_at'] is None
    assert transfer['can_cancel'] and not transfer['can_accept']
    assert service.view(a, individual)['revision'] != initial['revision']
    assert service.view(b, individual)['current_owner_user_id'] == str(a)
    assert not user_guitars(repo, b)
    assert service.inbox(c)['items'] == []
    for action in ('accept', 'decline'):
        with pytest.raises(PermissionError):
            resolve(service, a, transfer, action)
    with pytest.raises(PermissionError):
        resolve(service, b, transfer, 'cancel')
    for action in ('accept', 'decline', 'cancel'):
        with pytest.raises(GuitarMissing):
            resolve(service, c, transfer, action)
    recipient = service.detail(b, int(transfer['id']))
    assert recipient['can_accept'] and recipient['can_decline'] and not recipient['can_cancel']
    accepted = resolve(service, b, recipient, 'accept')
    assert accepted['state'] == 'accepted' and accepted['verification_status'] == 'positive'
    assert accepted['acceptance'] == {'accepted_by_user_id': str(b),
        'accepted_at': accepted['occurred_at'], 'current_owner_user_id': str(a)}
    assert service.view(a, individual)['current_owner_user_id'] == str(b)
    assert service.view(b, individual)['is_current_owner']
    assert not service.view(a, individual)['can_release']
    assert user_guitars(repo, a)[0]['ownership_status'] == 'former_owner'
    assert user_guitars(repo, b)[0]['ownership_status'] == 'current_owner'
    with pytest.raises(ValueError):
        repo.set_claim_response(int(transfer['id']), b, 'negative')
    with pytest.raises(ValueError):
        repo.set_claim_response(int(transfer['id']), a, 'positive')


def test_repeat_accept_preserves_evidence_notifications_and_admin_verification(workflow):
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    accepted = resolve(service, b, pending, 'accept')
    claim = int(accepted['id'])
    with repo.connect() as con:
        before = [dict(row) for row in con.execute('SELECT * FROM notifications')]
    repo.admin_moderate_claim(claim, 'negative')
    changed = service.detail(b, claim)
    assert changed['state'] == 'accepted' and changed['verification_status'] == 'negative'
    assert changed['acceptance'] == accepted['acceptance']
    repeated = resolve(service, b, pending, 'accept')
    assert repeated == changed
    assert service.view(a, individual)['current_owner_user_id'] == str(a)
    with repo.connect() as con:
        assert [dict(row) for row in con.execute('SELECT * FROM notifications')] == before
        assert con.execute('SELECT COUNT(*) FROM claim_transfer_acceptance').fetchone()[0] == 1
    with pytest.raises(ClaimConflict):
        resolve(service, b, changed, 'decline')


@pytest.mark.parametrize('action,participant,state', [('decline', 1, 'declined'), ('cancel', 0, 'cancelled')])
def test_terminal_decline_cancel_idempotency(workflow, action, participant, state):
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    actor = (a, b)[participant]
    done = resolve(service, actor, pending, action)
    assert done['state'] == state and done['acceptance'] is None
    assert resolve(service, actor, pending, action) == done
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == a
    assert not user_guitars(repo, b)
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM notifications WHERE notification_type=\'transfer_result\'').fetchone()[0] == 1


def test_release_records_shared_claim_and_formerly_owned_history(workflow):
    repo, service, a, _, c, individual = workflow
    initial = service.view(a, individual)
    data = {'occurred_at': '2021-01-01', 'body': '  Sold outside this service.  ', 'revision': initial['revision']}
    result = service.release(a, individual, data)
    assert result['claim']['ownership_kind'] == 'release' and result['claim']['verification_status'] == 'positive'
    assert result['claim']['body'] == 'Sold outside this service.'
    assert result['ownership']['current_owner_user_id'] is None
    assert not result['ownership']['is_current_owner']
    assert result['ownership']['items'] == [result['claim']]
    assert user_guitars(repo, a)[0]['ownership_status'] == 'former_owner'
    with pytest.raises(ClaimConflict):
        service.release(a, individual, data)
    with pytest.raises(GuitarMissing):
        service.view(c, individual)
    with pytest.raises(PermissionError):
        service.release(a, individual, data | {'revision': result['ownership']['revision']})


def test_backdated_release_retains_shared_chronological_outcome(workflow):
    repo, service, a, _, _, individual = workflow
    # The shared algorithm records historical releases, even when a later
    # ownership basis still supplies the current owner. Do not force a snapshot.
    result = service.release(a, individual, {'occurred_at': '2019-01-01', 'body': None,
        'revision': service.view(a, individual)['revision']})
    assert result['ownership']['current_owner_user_id'] == str(a)
    assert result['claim']['occurred_at'] == '2019-01-01'
    assert user_guitars(repo, a)[0]['ownership_status'] == 'current_owner'


def test_stale_creation_release_and_response_are_rejected(workflow):
    repo, service, a, b, c, individual = workflow
    initial = service.view(a, individual)
    pending = create(workflow)
    with pytest.raises(ClaimConflict):
        service.create(a, individual, {'to_user_id': str(c), 'revision': initial['revision']})
    with pytest.raises(ClaimConflict):
        service.release(a, individual, {'occurred_at': '2021-01-01', 'body': None, 'revision': initial['revision']})
    repo.admin_moderate_claim(int(pending['id']), 'positive')
    with pytest.raises(ClaimConflict):
        resolve(service, b, pending, 'accept')
    current = service.detail(b, int(pending['id']))
    assert current['state'] == 'pending' and current['acceptance'] is None
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == a
    assert resolve(service, b, current, 'accept')['state'] == 'accepted'


def test_competing_pending_transfers_cannot_both_accept(workflow):
    repo, service, a, b, c, individual = workflow
    first = create(workflow)
    second = create(workflow, c)
    first = service.detail(b, int(first['id']))
    resolve(service, b, first, 'accept')
    second = service.detail(c, int(second['id']))
    assert not second['can_accept'] and second['can_decline']
    with pytest.raises(ClaimConflict):
        resolve(service, c, second, 'accept')
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == b
    assert not user_guitars(repo, c)
    assert resolve(service, a, second, 'cancel')['state'] == 'cancelled'


def test_accept_then_release_prevents_stale_pending_accept(workflow):
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    service.release(a, individual, {'occurred_at': '2022-01-01', 'body': None,
        'revision': service.view(a, individual)['revision']})
    assert service.detail(b, int(pending['id']))['can_accept'] is False
    with pytest.raises(ClaimConflict):
        resolve(service, b, pending, 'accept')
    assert repo.get_individual(individual)[0]['current_owner_user_id'] is None


def test_accept_rolls_back_evidence_and_history_if_notification_fails(workflow):
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    with repo.connect() as con:
        con.execute("CREATE TRIGGER fail_result BEFORE INSERT ON notifications WHEN NEW.notification_type='transfer_result' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        resolve(service, b, pending, 'accept')
    assert service.detail(b, int(pending['id']))['state'] == 'pending'
    assert repo.get_individual(individual)[0]['current_owner_user_id'] == a
    assert not user_guitars(repo, b)
    with repo.connect() as con:
        assert con.execute('SELECT COUNT(*) FROM claim_transfer_acceptance').fetchone()[0] == 0


def test_independent_later_transfer_survives_earlier_admin_negative(workflow):
    repo, service, a, b, c, individual = workflow
    first = resolve(service, b, create(workflow), 'accept')
    next_transfer = service.create(b, individual, {'to_user_id': str(c),
        'revision': service.view(b, individual)['revision']})['transfer']
    last = resolve(service, c, next_transfer, 'accept')
    repo.admin_moderate_claim(int(first['id']), 'negative')
    assert service.view(c, individual)['current_owner_user_id'] == str(c)
    assert service.detail(c, int(last['id']))['acceptance'] == last['acceptance']
    assert user_guitars(repo, c)[0]['ownership_status'] == 'current_owner'


def test_private_bounded_history_and_inbox(workflow):
    repo, service, a, b, c, individual = workflow
    for index in range(4):
        pending = create(workflow, b if index % 2 == 0 else c)
        resolve(service, a, pending, 'cancel')
    first = service.inbox(a, limit=2)
    second = service.inbox(a, limit=2, after=int(first['next_after']))
    assert len(first['items']) == len(second['items']) == 2 and second['next_after'] is None
    assert all(int(first['items'][-1]['id']) > int(item['id']) for item in second['items'])
    assert all(item['to_user']['id'] == str(b) for item in service.inbox(b)['items'])
    view = service.view(b, individual, limit=1)
    assert len(view['items']) == 1 and view['next_after'] is not None
    assert view['viewer_user_id'] == str(b)
    with pytest.raises(GuitarMissing):
        service.detail(c, int(service.inbox(b)['items'][0]['id']))
    assert all('identity' not in key and 'email' not in key for item in first['items'] for key in item['to_user'])


def test_dispute_guards_create_accept_release_but_not_cancel(workflow):
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    with repo.connect() as con:
        con.execute("INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,created_at,updated_at) VALUES (?,?,?,'2020-01-01','2020-01-01')", (individual, a, a))
    view = service.view(a, individual)
    assert view['is_current_owner'] and not view['can_transfer'] and not view['can_release']
    pending = service.detail(b, int(pending['id']))
    assert not pending['can_accept'] and pending['can_decline']
    with pytest.raises(ValueError, match='dispute'):
        resolve(service, b, pending, 'accept')
    with pytest.raises(ValueError, match='dispute'):
        service.release(a, individual, {'occurred_at': '2021-01-01', 'body': None, 'revision': view['revision']})
    with pytest.raises(ValueError, match='dispute'):
        service.create(a, individual, {'to_user_id': str(b), 'revision': view['revision']})
    assert resolve(service, a, pending, 'cancel')['state'] == 'cancelled'


@pytest.mark.parametrize('method,kwargs', [
    ('inbox', dict(after=-1)), ('inbox', dict(after=True)), ('inbox', dict(limit=0)),
    ('view', dict(limit=51)), ('search_users', dict(offset=201)), ('search_users', dict(offset=-1)),
    ('search_users', dict(limit=21)), ('search_users', dict(q='x' * 121)), ('search_users', dict(q='x\n'))])
def test_read_bounds(workflow, method, kwargs):
    _, service, a, _, _, individual = workflow
    args = (a,) if method == 'inbox' else (a, individual)
    with pytest.raises(ValueError):
        getattr(service, method)(*args, **kwargs)


@pytest.mark.parametrize('changes', [dict(to_user_id=2), dict(to_user_id=True), dict(to_user_id='0'),
    dict(to_user_id='-1'), dict(to_user_id='9223372036854775808'), dict(from_user_id='99'),
    dict(revision='x'), dict(revision=1), dict(occurred_at='2020-01-01')])
def test_create_strict_payload(workflow, changes):
    _, service, a, b, _, individual = workflow
    data = {'to_user_id': str(b), 'revision': service.view(a, individual)['revision']}
    with pytest.raises(ValueError):
        service.create(a, individual, data | changes)


@pytest.mark.parametrize('changes', [dict(occurred_at=''), dict(occurred_at=None), dict(occurred_at='2999-01-01'),
    dict(occurred_at=True), dict(body=[]), dict(body='x' * 2001), dict(body='x\x00'),
    dict(ownership_kind='transfer'), dict(author_user_id=2), dict(revision='x')])
def test_release_strict_payload(workflow, changes):
    _, service, a, _, _, individual = workflow
    data = {'occurred_at': '2021-01-01', 'body': None, 'revision': service.view(a, individual)['revision']}
    with pytest.raises(ValueError):
        service.release(a, individual, data | changes)


@pytest.mark.parametrize('changes', [dict(action='positive'), dict(action=''), dict(revision='x'), dict(to_user_id='2')])
def test_resolve_strict_payload(workflow, changes):
    _, service, _, b, _, _ = workflow
    transfer = create(workflow)
    with pytest.raises(ValueError):
        service.resolve(b, int(transfer['id']), {'action': 'accept', 'revision': transfer['revision']} | changes)


def test_same_timestamps_do_not_hide_changed_revision(workflow, monkeypatch):
    repo, service, a, b, _, individual = workflow
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: '2020-02-01T00:00:00+00:00')
    before = service.view(a, individual)['revision']
    transfer = create(workflow)
    after = service.view(a, individual)['revision']
    assert after != before
    with repo.connect() as con:
        con.execute("UPDATE users SET location_country='Japan' WHERE id=?", (b,))
        assert ownership_revision(con, individual) != after
    with pytest.raises(ClaimConflict):
        resolve(service, b, transfer, 'accept')


def test_postgres_adapter_preserves_explicit_returning():
    from ygc.db.postgres_queries import ObservationConnection
    raw = Mock()
    raw.execute.return_value.fetchone.return_value = {'id': 9007199254740993}
    result = ObservationConnection(raw).execute('INSERT INTO claims (body) VALUES (?) RETURNING id', ('fixture',)).fetchone()
    assert result['id'] == 9007199254740993
    assert raw.execute.call_args.args == ('INSERT INTO claims (body) VALUES (%s) RETURNING id', ('fixture',))


def test_release_earlier_than_accepted_transfer_records_history_without_changing_owner(workflow):
    repo, service, a, b, _, individual = workflow
    accepted = resolve(service, b, create(workflow), 'accept')
    view = service.view(b, individual)
    data = {'occurred_at': '2021-01-01', 'body': 'Historical Release', 'revision': view['revision']}
    result = service.release(b, individual, data)
    assert result['ownership']['current_owner_user_id'] == str(b)
    assert result['ownership']['revision'] != view['revision']
    assert service.detail(b, int(accepted['id']))['acceptance'] == accepted['acceptance']
    with pytest.raises(ClaimConflict):
        service.release(b, individual, data)


@pytest.mark.parametrize('write,mode,expected_kind', [(False, 'normal', 'user_read'),
    (False, 'read_only', 'user_read'), (True, 'normal', 'user_write'), (True, 'admin_only', 'user_write')])
def test_transaction_holds_principal_mode_and_projection_fences(monkeypatch, write, mode, expected_kind):
    import ygc.cloud_ownership as module
    account = dict(id=8, app_user_id='canonical', ban_status='normal')
    raw, operations = Mock(), Mock()
    raw.execute.return_value.fetchone.return_value = {'locked': True}
    events = []

    @contextmanager
    def connection(settings, target):
        events.append(('open', target))
        yield raw
        events.append(('close', target))

    @contextmanager
    def access(kind, actor):
        assert (kind, actor) == (expected_kind, 'canonical')
        events.append('authority-start')
        yield None, {'mode': mode}, account
        events.append('authority-end')

    @contextmanager
    def fenced(self, principal, individual, extra_ids, *, active_ids):
        assert principal.user_id == 8 and principal.app_user_id == 'canonical' and principal.verified
        assert individual == 12 and extra_ids == (29,) and active_ids == (29,)
        events.append('content-start')
        yield BoundRepository(module.ObservationConnection(raw)), account
        events.append('content-end')

    operations.access = access
    monkeypatch.setattr(module, 'connect', connection)
    monkeypatch.setattr(module.PostgresOwnership, '_transaction', fenced)
    monkeypatch.setattr(module.PostgresOwnership, '_participants', Mock(return_value={8}))
    service = CloudOwnership(None, operations)
    service._account_status = Mock()
    service._visible = Mock(side_effect=lambda *args: events.append('visible'))
    with service.transaction('canonical', 12, write=write, extra_ids=(29,)) as (repo, user, can_write):
        assert user == 8 and can_write is (mode != 'read_only')
        events.append('action')
    assert events.index('authority-start') < events.index('content-start') < events.index('action')
    assert events.index('action') < events.index('content-end') < events.index('authority-end')
    assert events.count('visible') == 2 and events.index('visible') < events.index('content-start')
    service._account_status.assert_called_once_with(repo.connection, {8, 29})
    assert any('pg_try_advisory_xact_lock' in call.args[0] for call in raw.execute.call_args_list) is write


def test_hidden_ownership_rejected_before_participant_discovery(monkeypatch):
    import ygc.cloud_ownership as module
    raw, operations = Mock(), Mock()
    raw.execute.return_value.fetchone.return_value = None

    @contextmanager
    def connection(*args):
        yield raw

    @contextmanager
    def access(*args):
        yield None, {'mode': 'normal'}, dict(id=8, app_user_id='canonical', ban_status='normal')

    operations.access = access
    monkeypatch.setattr(module, 'connect', connection)
    participants = Mock()
    monkeypatch.setattr(module.PostgresOwnership, '_transaction', participants)
    with pytest.raises(GuitarMissing):
        with CloudOwnership(None, operations).transaction('canonical', 12):
            pytest.fail('Hidden guitar cannot reveal projection state.')
    participants.assert_not_called()


def test_maintenance_busy_stops_before_authority_and_projection(monkeypatch):
    import ygc.cloud_ownership as module
    raw, operations = Mock(), Mock()
    raw.execute.return_value.fetchone.return_value = {'locked': False}

    @contextmanager
    def connection(*args):
        yield raw

    monkeypatch.setattr(module, 'connect', connection)
    with pytest.raises(ClaimConflict):
        with CloudOwnership(None, operations).transaction('canonical', 12, write=True):
            pytest.fail('Busy maintenance cannot permit writes.')
    operations.access.assert_not_called()


def test_silent_ban_rejected_before_private_read_or_projection_discovery(monkeypatch):
    import ygc.cloud_ownership as module
    raw, operations = Mock(), Mock()

    @contextmanager
    def connection(*args):
        yield raw

    @contextmanager
    def access(*args):
        yield None, {'mode': 'normal'}, dict(id=8, app_user_id='canonical', ban_status='silent_ban')

    operations.access = access
    monkeypatch.setattr(module, 'connect', connection)
    participants = Mock()
    monkeypatch.setattr(module.PostgresOwnership, '_transaction', participants)
    with pytest.raises(PermissionError):
        with CloudOwnership(None, operations).transaction('canonical', 12):
            pytest.fail('Silent-BAN cannot participate.')
    participants.assert_not_called()


def test_canonical_disabled_participant_changes_flags_and_revision(workflow):
    from ygc.cloud_ownership import transfer_projection, transfer_row
    repo, service, a, b, _, individual = workflow
    pending = create(workflow)
    with repo.connect() as con:
        class CanonicalConnection:
            canonical_account_status = {a: {'disabled': False, 'projection_version': 1},
                                        b: {'disabled': True, 'projection_version': 2}}
            execute = con.execute
        wrapped = CanonicalConnection()
        projected = transfer_projection(wrapped, transfer_row(wrapped, int(pending['id']), b), b, True)
    assert not projected['can_accept'] and projected['can_decline']
    assert projected['state'] == 'pending' and projected['acceptance'] is None
    assert projected['revision'] != pending['revision']
    assert 'disabled' not in str(projected) and 'projection_version' not in str(projected)


def test_listing_evidence_is_bound_even_if_snapshot_timestamps_do_not_change(workflow):
    repo, service, a, _, _, individual = workflow
    before = service.view(a, individual)['revision']
    with repo.connect() as con:
        con.execute("UPDATE claim_listing_items SET value_text='Another maker' WHERE field_name='manufacturer'")
    assert service.view(a, individual)['revision'] != before
