"""Member-only Follow and minimal member directory.

The router and authenticated facade accept credentials. CloudFollows is a server-only
primitive receiving a canonical app UUID, like the existing account services.
Followers grants only the explicitly approved member-avatar read. Other profile
fields and private media remain outside this service.
"""
import json
import uuid

from ygc.cloud_users import MAX_ID
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts, now

ELIGIBLE = "u.disabled=0 AND u.ban_status<>'ban' AND u.account_type<>'source'"


class FollowConflict(ValueError):
    pass


class FollowTargetMissing(LookupError):
    pass


def target_id(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ValueError('Invalid Follow target.')
    return value


class AuthenticatedFollows:
    """Internal authentication boundary; deliberately not mounted in HTTP."""
    def __init__(self, verifier, service):
        self.verifier, self.service = verifier, service

    def _actor(self, token):
        if not isinstance(token, str) or not token or len(token) > 16384 or token != token.strip():
            raise PermissionError('One valid token is required.')
        identity = self.verifier.verify(bearer_token=token)
        if identity.email_verified is not True:
            raise PermissionError('Verified email required.')
        account = self.verifier.accounts.resolve_identity(
            issuer=identity.issuer, subject=identity.subject, tenant=identity.tenant)
        return account['app_user_id']

    def state(self, token, target):
        return self.service.state(self._actor(token), target)

    def set_following(self, token, target, following):
        return self.service.set_following(self._actor(token), target, following)


class CloudFollows:
    def __init__(self, settings, operations, storage=None):
        self.settings, self.operations, self.storage = settings, operations, storage

    @staticmethod
    def _page_args(after, limit):
        if type(after) is not int or not 0 <= after <= MAX_ID or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid member page.')

    @staticmethod
    def _member(con, target):
        row = con.execute('SELECT id,app_user_id,display_name,disabled,ban_status,account_type,avatar_visibility,avatar_storage_path '
                          'FROM account_records WHERE id=%s FOR SHARE', (target,)).fetchone()
        try:
            PostgresAccounts._active(row)
        except PermissionError:
            raise FollowTargetMissing('Member unavailable.') from None
        return row

    def avatar(self, actor, target):
        """Read a pinned private object only while canonical read locks are held.

        There is no signed/public URL or admin bypass. Unknown visibility and
        legacy local paths fail closed; only the existing normalized GCS format
        is accepted. A committed revocation is checked on every new request.
        """
        from ygc.cloud_avatar import AvatarMissing, decode_reference
        target_id(target)
        with self.operations.account_access('user_read', actor) as (con, _, account):
            con.execute("SET LOCAL lock_timeout='2s'")
            con.execute("SET LOCAL statement_timeout='5s'")
            person = self._member(con, target)
            allowed = target == account['id'] or person['avatar_visibility'] in ('Public', 'Members')
            if not allowed and person['avatar_visibility'] == 'Followers':
                allowed = con.execute('SELECT 1 FROM account_user_follows WHERE follower_user_id=%s '
                    'AND followed_user_id=%s FOR SHARE', (account['id'], target)).fetchone() is not None
            if not allowed or not person['avatar_storage_path']:
                raise AvatarMissing()
            try:
                reference = decode_reference(person['avatar_storage_path'])
            except (ValueError, TypeError, KeyError):
                raise AvatarMissing() from None
            if self.storage is None:
                raise RuntimeError('Image storage unavailable.')
            return self.storage.get(reference)

    @staticmethod
    def _page(con, condition, params, after, limit):
        # One SQL snapshot for count and page; IDs are stable internal cursors,
        # including for identically named people. Never search UUID/email.
        row = con.execute(f'''WITH eligible AS (
            SELECT u.id,u.display_name FROM account_records u WHERE {ELIGIBLE} AND {condition}
        ), page AS (SELECT * FROM eligible WHERE id>%s ORDER BY id LIMIT %s)
        SELECT (SELECT COUNT(*) FROM eligible) AS total,
          COALESCE((SELECT json_agg(page ORDER BY id) FROM page),'[]'::json) AS items''',
            (*params, after, limit + 1)).fetchone()
        items = row['items']
        more = len(items) > limit
        items = items[:limit]
        return {'items': [dict(id=str(p['id']), display_name=p['display_name'], icon=None) for p in items],
                'total': str(row['total']), 'next_after': str(items[-1]['id']) if more else None}

    def search(self, actor, *, q='', after=0, limit=25):
        self._page_args(after, limit)
        if not isinstance(q, str) or len(q) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in q):
            raise ValueError('Invalid member search.')
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        with self.operations.account_access('user_read', actor) as (con, _, account):
            con.execute("SET LOCAL statement_timeout='5s'")
            return self._page(con, 'u.display_name ILIKE %s', ('%' + escaped + '%',), after, limit)

    def connections(self, actor, target, *, direction, after=0, limit=25):
        target_id(target)
        self._page_args(after, limit)
        if direction not in ('followers', 'following'):
            raise ValueError('Invalid connection direction.')
        subject, other = (('followed_user_id', 'follower_user_id') if direction == 'followers'
                          else ('follower_user_id', 'followed_user_id'))
        with self.operations.account_access('user_read', actor) as (con, _, account):
            con.execute("SET LOCAL lock_timeout='2s'")
            con.execute("SET LOCAL statement_timeout='5s'")
            self._member(con, target)
            return self._page(con, f'EXISTS (SELECT 1 FROM account_user_follows f '
                              f'WHERE f.{subject}=%s AND f.{other}=u.id)', (target,), after, limit)

    def profile(self, actor, target):
        target_id(target)
        with self.operations.account_access('user_read', actor) as (con, mode, account):
            con.execute("SET LOCAL lock_timeout='2s'")
            con.execute("SET LOCAL statement_timeout='5s'")
            person = self._member(con, target)
            counts = con.execute(f'''SELECT
                (SELECT COUNT(*) FROM account_user_follows f JOIN account_records u
                 ON u.id=f.follower_user_id WHERE f.followed_user_id=%s AND {ELIGIBLE}) AS followers,
                (SELECT COUNT(*) FROM account_user_follows f JOIN account_records u
                 ON u.id=f.followed_user_id WHERE f.follower_user_id=%s AND {ELIGIBLE}) AS following,
                EXISTS(SELECT 1 FROM account_user_follows WHERE follower_user_id=%s
                  AND followed_user_id=%s) AS selected''', (target, target, account['id'], target)).fetchone()
            return {'person': {'id': str(target), 'display_name': person['display_name'], 'icon': None},
                    'is_self': target == account['id'], 'following': bool(counts['selected']),
                    'followers_count': str(counts['followers']), 'following_count': str(counts['following']),
                    'can_write': mode['mode'] in ('normal', 'admin_only')}

    @staticmethod
    def _target(con, actor, target):
        if target == actor['id']:
            raise ValueError('You cannot follow yourself.')
        row = con.execute('SELECT id,app_user_id,disabled,ban_status,account_type '
                          'FROM account_records WHERE id=%s FOR SHARE', (target,)).fetchone()
        try:
            PostgresAccounts._active(row)
        except PermissionError:
            # Missing, disabled, BAN and source share one internal result.
            raise FollowTargetMissing('Follow target unavailable.') from None
        return row

    def state(self, actor, target):
        target_id(target)
        with self.operations.account_access('user_read', actor) as (con, _, account):
            con.execute("SET LOCAL lock_timeout='2s'")
            con.execute("SET LOCAL statement_timeout='5s'")
            self._target(con, account, target)
            row = con.execute('SELECT 1 FROM account_user_follows '
                              'WHERE follower_user_id=%s AND followed_user_id=%s',
                              (account['id'], target)).fetchone()
            return {'target_id': str(target), 'following': row is not None}

    def set_following(self, actor, target, following):
        target_id(target)
        if type(following) is not bool:
            raise ValueError('Boolean Follow state required.')
        # Use the existing cross-DB maintenance fence. It also serializes
        # reciprocal follows before account locks, avoiding A/B lock inversion.
        with connect(self.settings, 'operations') as guard:
            if not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise FollowConflict('Maintenance or another update is running.')
            with self.operations.account_access('user_write', actor) as (con, _, account):
                con.execute("SET LOCAL lock_timeout='2s'")
                con.execute("SET LOCAL statement_timeout='5s'")
                other = self._target(con, account, target)
                timestamp = now()
                if following:
                    changed = con.execute('INSERT INTO account_user_follows '
                        '(follower_user_id,followed_user_id,created_at) VALUES(%s,%s,%s) '
                        'ON CONFLICT(follower_user_id,followed_user_id) DO NOTHING RETURNING followed_user_id',
                        (account['id'], target, timestamp)).fetchone()
                else:
                    changed = con.execute('DELETE FROM account_user_follows '
                        'WHERE follower_user_id=%s AND followed_user_id=%s RETURNING followed_user_id',
                        (account['id'], target)).fetchone()
                if changed is not None:
                    con.execute('INSERT INTO account_metadata(key,value) VALUES(%s,%s)',
                        ('self_follow:' + str(uuid.uuid4()), json.dumps({
                            'action': 'self_follow_set', 'actor_app_user_id': account['app_user_id'],
                            'target_app_user_id': other['app_user_id'], 'following': following,
                            'occurred_at': timestamp})))
                # Accounts commits before service-mode and maintenance locks
                # release. No profile revision/outbox/Chronicle change needed.
                result = {'target_id': str(target), 'following': following}
            return result


def result_projection(kind, result):
    """Whitelist every member response; no saved avatar/profile fields escape."""
    from ygc.cloud_favorite_routes import identifier
    from ygc.registration_fields import DISPLAY_NAME_MAX
    def person(row):
        key = row['id']
        if not isinstance(key, str) or str(identifier(key)) != key:
            raise ValueError()
        name = row['display_name']
        if not isinstance(name, str) or not name.strip() or len(name) > DISPLAY_NAME_MAX or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError()
        if row['icon'] is not None:
            raise ValueError()
        return {'id': key, 'display_name': name, 'icon': None}
    def count(value):
        if value != '0' and (not isinstance(value, str) or str(identifier(value)) != value):
            raise ValueError()
        return value
    try:
        if kind in ('search', 'connections'):
            if not isinstance(result['items'], list) or len(result['items']) > 50:
                raise ValueError()
            items = [person(row) for row in result['items']]
            if any(int(a['id']) >= int(b['id']) for a, b in zip(items, items[1:])):
                raise ValueError()
            cursor = result['next_after']
            if cursor is not None and (not items or cursor != items[-1]['id']):
                raise ValueError()
            return {'items': items, 'total': count(result['total']), 'next_after': cursor}
        if kind == 'profile':
            if any(type(result[k]) is not bool for k in ('is_self', 'following', 'can_write')):
                raise ValueError()
            return {'person': person(result['person']), **{k: result[k] for k in ('is_self', 'following', 'can_write')},
                    **{k: count(result[k]) for k in ('followers_count', 'following_count')}}
        if kind == 'set_following':
            key = result['target_id']
            if not isinstance(key, str) or str(identifier(key)) != key or type(result['following']) is not bool:
                raise ValueError()
            return {'target_id': key, 'following': result['following']}
        raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise RuntimeError('Invalid member result.') from None
