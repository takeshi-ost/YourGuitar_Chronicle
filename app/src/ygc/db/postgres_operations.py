"""Shared service modes; canonical Admin checks fenced against revocation."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json

from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts

MODES = ('normal', 'read_only', 'offline', 'admin_only')


class ModeConflict(ValueError):
    pass


class ServiceRestricted(PermissionError):
    pass


class PostgresOperations:
    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def _state(row):
        if not row or row['mode'] not in MODES or row['version'] < 0:
            raise RuntimeError('Invalid service state.')
        return dict(row)

    def public_status(self):
        with connect(self.settings, 'operations') as con:
            row = self._state(con.execute('SELECT mode,message,version FROM settings WHERE id=1').fetchone())
            return {'mode': row['mode'], 'message': row['message'] if row['mode'] != 'normal' else ''}

    @contextmanager
    def _access(self, kind, app_user_id=None, *, account_write=False):
        """Keep role and mode locks until the caller's work commits.

        Future content routes must retain this context around their transaction;
        the mode gate never replaces Ownership or private-resource checks.
        """
        if kind not in ('public_read', 'user_read', 'user_write', 'admin_read', 'admin_write'):
            raise ValueError('Unknown access category.')
        if account_write and kind not in ('user_write', 'admin_write'):
            raise ValueError('Account writes require a write category.')
        with connect(self.settings, 'accounts') as source:
            actor = None
            if app_user_id is not None:
                actor = source.execute('SELECT * FROM account_records WHERE app_user_id=%s ' + ('FOR UPDATE' if account_write else 'FOR SHARE'),
                                       (app_user_id,)).fetchone()
                PostgresAccounts._active(actor)
            admin = bool(actor and actor['role'] == 'admin')
            if kind.startswith('admin_') and not admin:
                raise PermissionError('An active administrator is required.')
            if kind.startswith('user_') and actor is None:
                raise PermissionError('Sign in to continue.')
            with connect(self.settings, 'operations') as con:
                lock = 'FOR UPDATE' if kind == 'admin_write' else 'FOR SHARE'
                row = self._state(con.execute('SELECT mode,message,version FROM settings WHERE id=1 ' + lock).fetchone())
                if not kind.startswith('admin_'):
                    allowed = (row['mode'] == 'normal' or
                               (row['mode'] == 'read_only' and kind.endswith('_read')) or
                               (row['mode'] == 'admin_only' and admin))
                    if not allowed:
                        raise ServiceRestricted('Service access is temporarily restricted.')
                yield con, row, actor, source
                if account_write:
                    # Publish Accounts changes before releasing the service-mode lock.
                    source.commit()

    @contextmanager
    def access(self, kind, app_user_id=None):
        with self._access(kind, app_user_id) as (con, row, actor, source):
            yield con, row, actor

    @contextmanager
    def account_access(self, kind, app_user_id):
        """Use the already locked canonical connection for atomic account updates."""
        with self._access(kind, app_user_id, account_write=kind.endswith('_write')) as (con, row, actor, source):
            yield source, row, actor

    def details(self, app_user_id):
        with self.access('admin_read', app_user_id) as (con, row, actor):
            return row

    def set_mode(self, app_user_id, *, mode, message, version):
        if mode not in MODES or not isinstance(message, str) or len(message) > 2000 or type(version) is not int or version < 0:
            raise ValueError('Invalid mode, message or version.')
        with self.access('admin_write', app_user_id) as (con, previous, actor):
            if previous['version'] != version:
                raise ModeConflict('Service status changed. Reload before retrying.')
            updated = con.execute('UPDATE settings SET mode=%s,message=%s,version=version+1 WHERE id=1 RETURNING mode,message,version',
                                  (mode, message,)).fetchone()
            audit = {'action': 'service_mode', 'actor_id': actor['id'], 'actor_app_user_id': actor['app_user_id'],
                     'previous_mode': previous['mode'], 'version': updated['version']}
            con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s)',
                        (datetime.now(timezone.utc).isoformat(), mode, json.dumps(audit)))
            return dict(updated)

    def review_status(self, app_user_id):
        with self.access('admin_read', app_user_id) as (con, _, actor):
            return {'enabled': bool(con.execute('SELECT enabled FROM review_settings WHERE id=1').fetchone()['enabled'])}

    def set_review(self, app_user_id, *, enabled, expected_enabled):
        if type(enabled) is not bool or type(expected_enabled) is not bool:
            raise ValueError('Boolean review state required.')
        with connect(self.settings, 'operations') as guard:
            if not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ModeConflict('Maintenance or review is running.')
            with self.access('admin_write', app_user_id) as (con, state, actor):
                previous = bool(con.execute('SELECT enabled FROM review_settings WHERE id=1 FOR UPDATE').fetchone()['enabled'])
                if previous != expected_enabled:
                    raise ModeConflict('Review status changed.')
                con.execute('UPDATE review_settings SET enabled=%s WHERE id=1', (int(enabled),))
                con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES(%s,%s,%s)',
                    (datetime.now(timezone.utc).isoformat(), state['mode'], json.dumps({'action':'review_mode','actor':actor['app_user_id'],'enabled':enabled})))
                return {'enabled': enabled}
