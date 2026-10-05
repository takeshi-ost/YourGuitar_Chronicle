"""PostgreSQL Owner Verification and Transfer business entry points.

Uses the same algorithms as SQLite inside fenced PG transactions. These methods
accept a server-resolved ActorContext. Admin verification is connected to the
cloud console; normal Owner/Transfer routes remain separate migration work.
Acquire image review, reset/backup and the remaining Repository methods are not
silently delegated to SQLite.
"""
from contextlib import contextmanager, nullcontext
from pathlib import Path
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_queries import ObservationConnection
from ygc.db.repository import Repository


class BoundRepository(Repository):
    def __init__(self, connection):
        super().__init__(Path(':memory:'))
        self.connection = connection

    def connect(self):
        return nullcontext(self.connection)


class PostgresOwnership:
    def __init__(self, settings):
        self.settings = settings
        self.accounts = PostgresAccounts(settings)

    @staticmethod
    def _verified(actor):
        if not actor.verified or not actor.app_user_id or actor.user_id is None:
            raise PermissionError('A server-verified account identity is required.')

    @staticmethod
    def _participants(con, individual_id):
        if not con.execute('SELECT 1 FROM individuals WHERE id=%s', (individual_id,)).fetchone():
            raise ValueError('Individual not found.')
        ids = {r['author_user_id'] for r in con.execute('SELECT author_user_id FROM claims WHERE individual_id=%s', (individual_id,))}
        ids.update(r['user_id'] for r in con.execute('SELECT user_id FROM user_guitars WHERE individual_id=%s', (individual_id,)))
        owner = con.execute('SELECT current_owner_user_id FROM individuals WHERE id=%s', (individual_id,)).fetchone()['current_owner_user_id']
        if owner is not None:
            ids.add(int(owner))
        for row in con.execute('''SELECT value_text FROM claims WHERE individual_id=%s AND claim_type='ownership'
            UNION SELECT li.value_text FROM claim_listing_items li JOIN claims c ON c.id=li.claim_id
                WHERE c.individual_id=%s AND li.field_name='owner_user_id' ''', (individual_id, individual_id)):
            value = str(row['value_text'] or '')
            if value.isascii() and value.isdigit() and int(value) > 0:
                ids.add(int(value))
        for row in con.execute('''SELECT t.from_user_id,t.to_user_id FROM claim_transfers t
            JOIN claims c ON c.id=t.claim_id WHERE c.individual_id=%s''', (individual_id,)):
            ids.update((row['from_user_id'], row['to_user_id']))
        return ids

    def _individual(self, claim_id):
        with connect(self.settings, 'chronicle') as con:
            row = con.execute('SELECT individual_id FROM claims WHERE id=%s', (claim_id,)).fetchone()
            if not row:
                raise ValueError('Claim not found.')
            return row['individual_id']

    @contextmanager
    def _transaction(self, actor, individual_id, extra_ids=(), *, active_ids=(), require_admin=False):
        self._verified(actor)
        with connect(self.settings, 'chronicle') as con:
            scope = self._participants(con, individual_id) | {actor.user_id} | set(extra_ids)
        with self.accounts.content_transaction(actor.app_user_id, scope, active_participant_ids=active_ids,
                                               require_admin=require_admin) as (con, account):
            if account['id'] != actor.user_id:
                raise PermissionError('Account participant mapping does not match the verified actor.')
            if not self._participants(con, individual_id).issubset(scope):
                raise ValueError('Participant scope changed; retry the operation.')
            yield BoundRepository(ObservationConnection(con)), account

    def owner_verifiable_claim_ids(self, individual_id, actor):
        with self._transaction(actor, individual_id) as (repo, account):
            return repo.owner_verifiable_claim_ids(individual_id, account['id'])

    def set_claim_response(self, claim_id, actor, stance, reason=None):
        self._verified(actor)
        individual = self._individual(claim_id)
        with self._transaction(actor, individual) as (repo, account):
            self._same_individual(repo, claim_id, individual)
            return repo.set_claim_response_in_connection(repo.connection, claim_id, account['id'], stance, reason)

    def create_transfer(self, individual_id, actor, to_user_id):
        with self._transaction(actor, individual_id, (to_user_id,), active_ids=(to_user_id,)) as (repo, account):
            return repo.create_transfer_in_connection(repo.connection, account['id'], individual_id, to_user_id)

    def resolve_transfer(self, claim_id, actor, action):
        self._verified(actor)
        individual = self._individual(claim_id)
        with connect(self.settings, 'chronicle') as con:
            transfer = con.execute('SELECT from_user_id,to_user_id FROM claim_transfers WHERE claim_id=%s', (claim_id,)).fetchone()
            if not transfer:
                raise ValueError('Transfer not found.')
            participants = (transfer['from_user_id'], transfer['to_user_id'])
        with self._transaction(actor, individual, active_ids=participants if action == 'accept' else ()) as (repo, account):
            self._same_individual(repo, claim_id, individual)
            current = repo.connection.execute('SELECT from_user_id,to_user_id FROM claim_transfers WHERE claim_id=?', (claim_id,)).fetchone()
            if not current or (current['from_user_id'], current['to_user_id']) != participants:
                raise ValueError('Transfer participants changed; retry the operation.')
            return repo.resolve_transfer_in_connection(repo.connection, claim_id, account['id'], action)

    def admin_moderate_claim(self, claim_id, actor, action, *, confirm_individual_delete=False, expected_revision=None, expected_individual_id=None):
        self._verified(actor)
        individual = self._individual(claim_id)
        with self._transaction(actor, individual, require_admin=True) as (repo, account):
            self._same_individual(repo, claim_id, individual)
            if expected_revision is not None:
                from ygc.claim_revision import revision,ClaimConflict
                current=repo.connection.execute('SELECT * FROM claims WHERE id=? FOR UPDATE',(claim_id,)).fetchone()
                if not current or current['individual_id']!=expected_individual_id or revision(current)!=expected_revision:
                    raise ClaimConflict('Claim changed; reload before retrying.')
            if account['role'] != 'admin':
                raise PermissionError('An active administrator account is required.')
            return repo.admin_moderate_claim_in_connection(repo.connection, claim_id, action,
                confirm_individual_delete=confirm_individual_delete, actor='identity-platform:' + account['app_user_id'])

    @staticmethod
    def _same_individual(repo, claim_id, expected):
        row = repo.connection.execute('SELECT individual_id FROM claims WHERE id=?', (claim_id,)).fetchone()
        if not row or row['individual_id'] != expected:
            raise ValueError('Claim target changed; retry the operation.')
