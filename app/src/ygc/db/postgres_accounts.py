"""Canonical PostgreSQL accounts and durable, idempotent Chronicle projection.

This store is not a token verifier. Identity keys must come from a verified
server-side Identity Platform result, never from a submitted browser user ID.
No password, ID token or session is written to the projection outbox.
"""
from datetime import datetime, timezone
import json
import uuid
from contextlib import contextmanager

from psycopg import sql
from ygc.db.postgres import connect, status
from ygc.theme_catalog import THEME_IDS

PROFILE_FIELDS = frozenset((
    'display_name', 'location_country', 'location_region', 'bio', 'date_of_birth',
    'birth_visibility', 'residence_visibility', 'bio_visibility', 'avatar_visibility',
    'theme', 'theme_override', 'avatar_storage_path', 'avatar_original_filename', 'avatar_mime_type',
))
# Role and disabled are deliberately absent from the content projection.
PROJECTION_FIELDS = (
    'id', 'display_name', 'account_type', 'ban_status', 'identity_provider',
    'identity_subject', 'location_country', 'location_region', 'bio', 'date_of_birth',
    'avatar_storage_path', 'avatar_original_filename', 'avatar_mime_type',
    'birth_visibility', 'residence_visibility', 'bio_visibility', 'avatar_visibility',
    'theme', 'theme_override', 'created_at', 'updated_at', 'app_user_id',
)


def now():
    return datetime.now(timezone.utc).isoformat()


class PostgresAccounts:
    def __init__(self, settings):
        self.settings = settings

    def check_schema(self):
        for target in ('accounts', 'chronicle'):
            if status(self.settings, target)['version'] < 2:
                raise ValueError('Apply account projection migration 002 first.')

    def ensure_identity(self, *, issuer, subject, display_name, tenant='', account_type='user', consents=()):
        """Idempotently reserve a participant for an already verified identity."""
        name = str(display_name).strip()
        if not issuer or not subject or not name or len(name) > 100 or account_type not in ('user', 'shop'):
            raise ValueError('Invalid account registration.')
        self.check_schema()
        with connect(self.settings, 'accounts') as con:
            # Also serialize first registrations before an account row exists.
            key = json.dumps([issuer, tenant, subject], ensure_ascii=False)
            con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (key,))
            existing = con.execute('''SELECT a.* FROM identity_links i JOIN account_records a
                ON a.app_user_id=i.app_user_id WHERE i.issuer=%s AND i.tenant=%s AND i.subject=%s''',
                (issuer, tenant, subject)).fetchone()
            if existing:
                self._active(existing)
                return existing
            at = now()
            account = con.execute('''INSERT INTO account_records
                (app_user_id,display_name,account_type,identity_provider,identity_subject,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (str(uuid.uuid4()), name, account_type, issuer, subject, at, at)).fetchone()
            con.execute('INSERT INTO identity_links(issuer,tenant,subject,app_user_id) VALUES(%s,%s,%s,%s)',
                        (issuer, tenant, subject, account['app_user_id']))
            for kind, version in consents:
                if not kind or not version:
                    raise ValueError('Invalid policy consent.')
                con.execute('INSERT INTO account_consents VALUES(%s,%s,%s,%s)',
                            (account['app_user_id'], kind, version, at))
            return account

    @staticmethod
    def _active(account):
        if not account or account['disabled'] or account['ban_status'] == 'ban' or account['account_type'] == 'source':
            raise PermissionError('Account is not available.')
        return account

    def resolve_identity(self, *, issuer, subject, tenant=''):
        """Read live authority; stale Chronicle fields cannot grant access."""
        with connect(self.settings, 'accounts') as con:
            account = con.execute('''SELECT a.* FROM identity_links i JOIN account_records a
                ON a.app_user_id=i.app_user_id WHERE i.issuer=%s AND i.tenant=%s AND i.subject=%s''',
                (issuer, tenant, subject)).fetchone()
            return self._active(account)

    def update_profile(self, app_user_id, changes):
        self.check_schema()
        if not changes or set(changes) - PROFILE_FIELDS:
            raise ValueError('Unsupported account profile fields.')
        changes = dict(changes)
        if 'display_name' in changes:
            changes['display_name'] = str(changes['display_name'] or '').strip()
            if not changes['display_name'] or len(changes['display_name']) > 100:
                raise ValueError('Invalid display name.')
        for key, value in changes.items():
            if key.endswith('_visibility') and value not in ('Public', 'Members', 'Followers', 'Private'):
                raise ValueError('Invalid visibility.')
            if key in ('theme', 'theme_override') and (value not in THEME_IDS and not (key == 'theme_override' and value is None)):
                raise ValueError('Invalid theme.')
        with connect(self.settings, 'accounts') as con:
            account = con.execute('SELECT * FROM account_records WHERE app_user_id=%s FOR UPDATE', (app_user_id,)).fetchone()
            self._active(account)
            changes['updated_at'] = now()
            assignments = sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(key)) for key in changes)
            return con.execute(sql.SQL('UPDATE account_records SET {} WHERE app_user_id=%s RETURNING *').format(assignments),
                               (*changes.values(), app_user_id)).fetchone()

    @contextmanager
    def content_transaction(self, actor_app_user_id, participant_ids, *, active_participant_ids=(), require_admin=False):
        """Fence a content action against stale account projections.

        The server must supply every relevant Claim author/Owner/recipient ID
        and verify that scope again inside this transaction. This is a database
        primitive, not an Ownership authorization decision or token verifier.
        """
        ids = sorted(set(participant_ids))
        if not ids or any(not isinstance(value, int) or value <= 0 for value in ids):
            raise ValueError('A complete participant scope is required.')
        self.check_schema()
        with connect(self.settings, 'accounts') as source:
            accounts = source.execute('''SELECT * FROM account_records
                WHERE id=ANY(%s) OR app_user_id=%s ORDER BY id FOR SHARE''', (ids, actor_app_user_id)).fetchall()
            by_id = {row['id']: row for row in accounts}
            actor = next((row for row in accounts if row['app_user_id'] == actor_app_user_id), None)
            self._active(actor)
            if require_admin and actor['role'] != 'admin':
                raise PermissionError('An active administrator account is required.')
            if any(value not in by_id for value in ids):
                raise ValueError('Unknown participant in the canonical account registry.')
            for value in active_participant_ids:
                self._active(by_id.get(value))
            with connect(self.settings, 'chronicle') as dest:
                dest.execute('SELECT pg_advisory_xact_lock(79432002)')
                projected = {row['id']: row for row in dest.execute('''SELECT u.*,
                    r.app_user_id AS receipt_uuid,r.revision FROM users u
                    JOIN account_projection_receipts r ON r.account_id=u.id WHERE u.id=ANY(%s)''', (list(by_id),))}
                for account in accounts:
                    row = projected.get(account['id'])
                    if (not row or row['app_user_id'] != account['app_user_id']
                            or row['receipt_uuid'] != account['app_user_id']
                            or row['revision'] != account['projection_version']
                            or any(row[key] != account[key] for key in PROJECTION_FIELDS
                                   if key not in ('identity_provider', 'identity_subject'))):
                        raise ValueError('Participant projection is pending or conflicts with the registry.')
                yield dest, actor

    def project_next(self, *, after_content_commit=None):
        """Commit content first, then acknowledge; a crash leaves a safe retry.

        Worker failures propagate and keep the event pending. The optional hook
        is for interruption tests; it is never used by a request handler.
        """
        self.check_schema()
        with connect(self.settings, 'accounts') as source:
            event = source.execute('''SELECT * FROM account_projection_outbox
                WHERE delivered_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''').fetchone()
            if not event:
                return False
            account = source.execute('SELECT * FROM account_records WHERE id=%s FOR UPDATE', (event['account_id'],)).fetchone()
            if not account or account['app_user_id'] != event['app_user_id']:
                raise ValueError('Projection identity does not match its registry.')
            self._project(account)
            if after_content_commit:
                after_content_commit()
            source.execute('UPDATE account_projection_outbox SET delivered_at=CURRENT_TIMESTAMP WHERE id=%s', (event['id'],))
            return True

    def drain_projection(self, *, limit=100):
        if not 1 <= limit <= 10000:
            raise ValueError('Invalid projection batch size.')
        count = 0
        while count < limit and self.project_next():
            count += 1
        return count

    def _project(self, account):
        with connect(self.settings, 'chronicle') as dest:
            # All projection workers lock content after taking the source row lock.
            dest.execute('SELECT pg_advisory_xact_lock(79432002)')
            self._apply_projection(dest, account)

    def reconcile_projection(self):
        """Rebuild from the current registry during an operator-controlled stop.

        Unknown content IDs and regressed registry revisions reject the whole
        content transaction. No accounts, Claims or signature guitars are deleted.
        """
        self.check_schema()
        with connect(self.settings, 'accounts') as source:
            accounts = source.execute('SELECT * FROM account_records ORDER BY id FOR UPDATE').fetchall()
            registry = {a['id']: a['app_user_id'] for a in accounts}
            with connect(self.settings, 'chronicle') as dest:
                dest.execute('SELECT pg_advisory_xact_lock(79432002)')
                for row in dest.execute('SELECT id,app_user_id FROM users FOR UPDATE'):
                    if registry.get(row['id']) != row['app_user_id']:
                        raise ValueError('Unknown/conflicting content identity; explicit restore mapping is required.')
                for account in accounts:
                    self._apply_projection(dest, account, force_rebuild=True)
            # Leave pending events for the worker: taking event locks after account
            # locks would invert its lock order, and could acknowledge a newly
            # registered account that was outside this snapshot.
            return len(accounts)

    def _apply_projection(self, dest, account, *, force_rebuild=False):
        user = dest.execute('SELECT * FROM users WHERE id=%s OR app_user_id=%s FOR UPDATE',
                            (account['id'], account['app_user_id'])).fetchall()
        if any(row['id'] != account['id'] or row['app_user_id'] != account['app_user_id'] for row in user):
            raise ValueError('Account ID/UUID conflict; explicit restore mapping is required.')
        receipt = dest.execute('SELECT * FROM account_projection_receipts WHERE account_id=%s', (account['id'],)).fetchone()
        if receipt and receipt['app_user_id'] != account['app_user_id']:
            raise ValueError('Projection receipt identity conflict.')
        if receipt and receipt['revision'] > account['projection_version']:
            raise ValueError('Account registry revision regressed; restore needs reconciliation.')
        # Equal revisions are re-applied to repair a restored content snapshot.
        previous = user[0] if user else None
        names = sql.SQL(',').join(map(sql.Identifier, PROJECTION_FIELDS))
        marks = sql.SQL(',').join(sql.Placeholder() for _ in PROJECTION_FIELDS)
        assignments = sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(key), sql.Identifier(key))
                                       for key in PROJECTION_FIELDS if key not in ('id', 'app_user_id'))
        # Legacy content identity columns cannot represent tenant-qualified keys.
        dest.execute(sql.SQL('INSERT INTO users ({}) VALUES ({}) ON CONFLICT(id) DO UPDATE SET {}').format(names, marks, assignments),
                     tuple(None if key in ('identity_provider', 'identity_subject') else account[key]
                           for key in PROJECTION_FIELDS))
        if force_rebuild or (previous and any(previous[key] != account[key] for key in
                            ('display_name', 'ban_status', 'account_type', 'location_country', 'location_region'))):
            self._rebuild_participant_snapshots(dest, account['id'])
        dest.execute('''INSERT INTO account_projection_receipts(account_id,app_user_id,revision)
            VALUES(%s,%s,%s) ON CONFLICT(account_id) DO UPDATE SET revision=EXCLUDED.revision,
            applied_at=CURRENT_TIMESTAMP''', (account['id'], account['app_user_id'], account['projection_version']))

    @staticmethod
    def _rebuild_participant_snapshots(con, user_id):
        from pathlib import Path
        from ygc.db.repository import Repository
        from ygc.db.postgres_queries import ObservationConnection
        ids = con.execute('''SELECT id AS individual_id FROM individuals WHERE current_owner_user_id=%s
            UNION SELECT individual_id FROM claims WHERE author_user_id=%s
               OR (ownership_source='user_transfer' AND value_text=%s)
            UNION SELECT c.individual_id FROM claims c JOIN claim_listing_items li ON li.claim_id=c.id
               WHERE li.field_name='owner_user_id' AND li.value_text=%s''', (user_id, user_id, str(user_id), str(user_id)))
        evaluator = Repository(Path(':memory:'))
        for row in ids.fetchall():
            evaluator._rebuild_individual_snapshot_in_connection(ObservationConnection(con), row['individual_id'])
