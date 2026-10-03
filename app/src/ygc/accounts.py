"""Canonical local accounts, with a transactionally maintained content projection.

TEMP triggers can access attached SQLite databases. Account fields and their
projection commit in the same transaction; signature guitar stays in content.
"""
from __future__ import annotations
import os
import sqlite3
import uuid
from pathlib import Path

CONTENT_FIELDS = {'signature_individual_id'}
SOCIAL_TABLES = ('user_follows', 'direct_messages')


def initialize(con, path):
    columns = {r['name'] for r in con.execute('PRAGMA main.table_info(users)')}
    if 'app_user_id' not in columns:
        con.execute('ALTER TABLE users ADD COLUMN app_user_id TEXT')
    _attach(con, path)
    _drop_triggers(con)
    definitions = []
    for row in con.execute('PRAGMA main.table_info(users)'):
        if row['name'] in CONTENT_FIELDS:
            continue
        definition = '"' + row['name'] + '" ' + row['type']
        if row['name'] == 'id':
            definition += ' PRIMARY KEY'
        definitions.append(definition)
    con.execute('CREATE TABLE IF NOT EXISTS accounts.account_records (' + ','.join(definitions) + ', role TEXT NOT NULL DEFAULT \'member\', disabled INTEGER NOT NULL DEFAULT 0)')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS accounts.account_uuid ON account_records(app_user_id)')
    con.execute("CREATE TRIGGER IF NOT EXISTS accounts.immutable_account_identity BEFORE UPDATE OF id,app_user_id ON account_records WHEN NEW.id IS NOT OLD.id OR NEW.app_user_id IS NOT OLD.app_user_id BEGIN SELECT RAISE(ABORT,'Account identity is immutable'); END")
    con.execute("CREATE TRIGGER IF NOT EXISTS accounts.reserve_deleted_account_id BEFORE DELETE ON account_records BEGIN SELECT RAISE(ABORT,'Disable accounts instead of deleting their identity registry'); END")
    con.execute('CREATE TABLE IF NOT EXISTS accounts.account_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS accounts.identity_links (issuer TEXT NOT NULL, tenant TEXT NOT NULL DEFAULT \'\', subject TEXT NOT NULL, app_user_id TEXT NOT NULL REFERENCES account_records(app_user_id), PRIMARY KEY(issuer,tenant,subject))')
    con.execute('CREATE TABLE IF NOT EXISTS accounts.local_sessions (token_hash TEXT PRIMARY KEY, app_user_id TEXT NOT NULL REFERENCES account_records(app_user_id), expires_at REAL NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS accounts.account_consents (app_user_id TEXT NOT NULL REFERENCES account_records(app_user_id), policy_kind TEXT NOT NULL, version TEXT NOT NULL, accepted_at TEXT NOT NULL, PRIMARY KEY(app_user_id,policy_kind,version))')
    fields = _fields(con)
    if not con.execute("SELECT 1 FROM accounts.account_metadata WHERE key='initialized'").fetchone():
        for row in con.execute('SELECT id, app_user_id FROM users').fetchall():
            con.execute('UPDATE users SET app_user_id=? WHERE id=?', (row['app_user_id'] or str(uuid.uuid4()), row['id']))
        names = ','.join('"'+f+'"' for f in fields)
        con.execute(f'INSERT INTO accounts.account_records ({names}) SELECT {names} FROM users')
        con.execute("INSERT INTO accounts.account_metadata VALUES ('initialized','1')")
        con.execute("INSERT INTO accounts.identity_links SELECT identity_provider,'',identity_subject,app_user_id FROM accounts.account_records WHERE identity_provider IS NOT NULL AND identity_subject IS NOT NULL AND account_type<>'source'")
    for table in SOCIAL_TABLES:
        definition = con.execute('SELECT sql FROM main.sqlite_master WHERE name=?', (table,)).fetchone()[0]
        definition = definition.replace('CREATE TABLE '+table, 'CREATE TABLE IF NOT EXISTS accounts.account_'+table).replace('REFERENCES users(', 'REFERENCES account_records(')
        con.execute(definition)
    if not con.execute("SELECT 1 FROM accounts.account_metadata WHERE key='social_initialized'").fetchone():
        for table in SOCIAL_TABLES:
            con.execute(f'INSERT INTO accounts.account_{table} SELECT * FROM main.{table}')
        con.execute("INSERT INTO accounts.account_metadata VALUES ('social_initialized','1')")
    project(con)
    migrate_avatars(con, Path(path).parent)
    con.commit()
    _triggers(con)


def _attach(con, path):
    con.create_function('ygc_new_uuid', 0, lambda: str(uuid.uuid4()))
    if 'accounts' not in {r[1] for r in con.execute('PRAGMA database_list')}:
        if con.execute('PRAGMA main.journal_mode').fetchone()[0].lower() == 'wal':
            raise ValueError('Account splitting requires SQLite DELETE journal mode for atomic cross-database commits; checkpoint and switch journal mode before migration.')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con.execute('ATTACH DATABASE ? AS accounts', (str(path),))
        con.execute('PRAGMA accounts.journal_mode=DELETE')
        os.chmod(path, 0o600)


def _fields(con):
    return [r['name'] for r in con.execute('PRAGMA main.table_info(users)') if r['name'] not in CONTENT_FIELDS]


def project(con):
    fields = _fields(con)
    # Restored numeric IDs must never silently identify a different account.
    conflict = con.execute('SELECT u.id FROM main.users u JOIN accounts.account_records a ON a.id=u.id WHERE u.app_user_id IS NOT a.app_user_id LIMIT 1').fetchone()
    if conflict:
        raise ValueError('Account identity conflict in content database; restore requires an explicit user mapping.')
    # Unknown archive identities need an explicit mapping, never an automatic login.
    names = ','.join('"'+f+'"' for f in fields)
    if con.execute('SELECT id FROM main.users WHERE id NOT IN (SELECT id FROM accounts.account_records) LIMIT 1').fetchone():
        raise ValueError('Content database contains unknown accounts; restore the corresponding account registry or provide an explicit mapping.')
    changed_bans = [r[0] for r in con.execute('SELECT u.id FROM main.users u JOIN accounts.account_records a ON a.id=u.id WHERE u.ban_status IS NOT a.ban_status OR u.display_name IS NOT a.display_name OR u.account_type IS NOT a.account_type')]
    assignments = ','.join('"'+f+'"=excluded."'+f+'"' for f in fields if f != 'id')
    con.execute(f'INSERT INTO main.users ({names}) SELECT {names} FROM accounts.account_records WHERE 1 ON CONFLICT(id) DO UPDATE SET {assignments}')
    for table in SOCIAL_TABLES:
        con.execute(f'DELETE FROM main.{table}')
        con.execute(f'INSERT INTO main.{table} SELECT * FROM accounts.account_{table}')
    if changed_bans:
        from ygc.db.repository import Repository
        repository = Repository(Path(':memory:'))
        marks = ','.join('?' for _ in changed_bans)
        ids = [r[0] for r in con.execute(f'SELECT DISTINCT individual_id FROM claims WHERE author_user_id IN ({marks})', changed_bans)]
        # Transfer/listing participants may affect evaluation too.
        ids += [r[0] for r in con.execute('SELECT id FROM individuals')]
        for individual_id in set(ids):
            repository._rebuild_individual_snapshot_in_connection(con, individual_id)


def _drop_triggers(con):
    con.execute('DROP TRIGGER IF EXISTS temp.account_projection_insert')
    con.execute('DROP TRIGGER IF EXISTS temp.account_projection_update')
    con.execute('DROP TRIGGER IF EXISTS temp.immutable_participant_identity')
    for table in SOCIAL_TABLES:
        for action in ('insert','update','delete'):
            con.execute(f'DROP TRIGGER IF EXISTS temp.account_{table}_{action}')


def _triggers(con):
    _drop_triggers(con)
    fields = _fields(con)
    names = ','.join('"'+f+'"' for f in fields)
    values = ','.join("COALESCE(NEW.app_user_id,ygc_new_uuid())" if f == 'app_user_id' else 'NEW."'+f+'"' for f in fields)
    assignments = ','.join('"'+f+'"=NEW."'+f+'"' for f in fields if f != 'id')
    con.execute(f'CREATE TEMP TRIGGER account_projection_insert AFTER INSERT ON main.users BEGIN INSERT INTO account_records ({names}) VALUES ({values}); UPDATE users SET app_user_id=(SELECT app_user_id FROM account_records WHERE id=NEW.id) WHERE id=NEW.id; END')
    con.execute(f'CREATE TEMP TRIGGER account_projection_update AFTER UPDATE ON main.users BEGIN UPDATE account_records SET {assignments} WHERE id=NEW.id; END')
    con.execute("CREATE TEMP TRIGGER immutable_participant_identity BEFORE UPDATE OF id,app_user_id ON main.users WHEN OLD.app_user_id IS NOT NULL AND (NEW.id IS NOT OLD.id OR NEW.app_user_id IS NOT OLD.app_user_id) BEGIN SELECT RAISE(ABORT,'Participant identity is immutable'); END")
    for table in SOCIAL_TABLES:
        fields = [r['name'] for r in con.execute(f'PRAGMA main.table_info({table})')]
        keys = [r['name'] for r in con.execute(f'PRAGMA main.table_info({table})') if r['pk']]
        values = ','.join('NEW.'+f for f in fields)
        where = ' AND '.join(f'{f}=OLD.{f}' for f in keys)
        assignments = ','.join(f'{f}=NEW.{f}' for f in fields)
        con.execute(f'CREATE TEMP TRIGGER account_{table}_insert AFTER INSERT ON main.{table} BEGIN INSERT INTO account_{table} VALUES ({values}); END')
        con.execute(f'CREATE TEMP TRIGGER account_{table}_update AFTER UPDATE ON main.{table} BEGIN UPDATE account_{table} SET {assignments} WHERE {where}; END')
        con.execute(f'CREATE TEMP TRIGGER account_{table}_delete AFTER DELETE ON main.{table} BEGIN DELETE FROM account_{table} WHERE {where}; END')
    # Deleting content cannot delete an account or free its ID.


def attach_projection(con, path):
    _attach(con, path)
    if not con.execute("SELECT 1 FROM accounts.sqlite_master WHERE name='account_records'").fetchone():
        initialize(con, path)
        return
    con.execute('CREATE TABLE IF NOT EXISTS accounts.account_consents (app_user_id TEXT NOT NULL REFERENCES account_records(app_user_id), policy_kind TEXT NOT NULL, version TEXT NOT NULL, accepted_at TEXT NOT NULL, PRIMARY KEY(app_user_id,policy_kind,version))')
    project(con)
    con.commit()
    _triggers(con)


def migrate_avatars(con, root):
    import shutil
    for user in con.execute("SELECT id,avatar_storage_path FROM accounts.account_records WHERE avatar_storage_path LIKE 'media/users/%'").fetchall():
        old = (root / user['avatar_storage_path']).resolve()
        if not old.is_relative_to((root / 'media' / 'users').resolve()) or not old.is_file():
            continue
        relative = Path('account_media') / 'users' / old.name
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.exists():
            shutil.copyfile(old,target)
        con.execute('UPDATE accounts.account_records SET avatar_storage_path=? WHERE id=?', (relative.as_posix(), user['id']))
        con.execute('UPDATE main.users SET avatar_storage_path=? WHERE id=?', (relative.as_posix(), user['id']))


def login(repository, user_id, *, now=None):
    import hashlib
    import secrets
    import time
    now = time.time() if now is None else now
    with repository.connect() as con:
        user = con.execute("SELECT * FROM account_records WHERE id=? AND disabled=0 AND account_type<>'source' AND ban_status<>'ban'", (user_id,)).fetchone()
        if not user:
            raise PermissionError('Account is unavailable.')
        subject = 'local-' + user['app_user_id']
        con.execute("INSERT OR IGNORE INTO identity_links VALUES ('local-dummy','',?,?)", (subject,user['app_user_id']))
        token = secrets.token_urlsafe(32)
        con.execute('DELETE FROM local_sessions WHERE expires_at<=?', (now,))
        con.execute('INSERT INTO local_sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),user['app_user_id'],now+3600))
        from ygc.auth_session import SignInResult
        return SignInResult(user_id,user['app_user_id'],subject,token,user['display_name']).as_response()


def resolve_session(repository, token, *, now=None):
    import hashlib
    import time
    now = time.time() if now is None else now
    with repository.connect() as con:
        user = con.execute("SELECT a.* FROM local_sessions s JOIN account_records a USING(app_user_id) WHERE token_hash=? AND expires_at>? AND disabled=0 AND account_type<>'source' AND ban_status<>'ban'", (hashlib.sha256(token.encode()).hexdigest(),now)).fetchone()
        if not user:
            raise PermissionError('Invalid or expired local session.')
        return dict(user)


def logout(repository, token):
    import hashlib
    with repository.connect() as con:
        con.execute('DELETE FROM local_sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def prepare_restore(candidate, current):
    """Retain the ID registry and reject reassignment of IDs or provider subjects."""
    with sqlite3.connect(candidate) as source, sqlite3.connect(current) as live:
        source.row_factory = live.row_factory = sqlite3.Row
        required = {'account_records','account_metadata','identity_links','local_sessions','account_user_follows','account_direct_messages'}
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables:
            raise ValueError('Not an account database backup.')
        incoming = {r['id']:r['app_user_id'] for r in source.execute('SELECT id,app_user_id FROM account_records')}
        uuids = {value:key for key,value in incoming.items()}
        if None in uuids or len(uuids) != len(incoming):
            raise ValueError('Account UUIDs must be present and unique.')
        for row in live.execute('SELECT * FROM account_records').fetchall():
            if (row['id'] in incoming and incoming[row['id']] != row['app_user_id']) or (row['app_user_id'] in uuids and uuids[row['app_user_id']] != row['id']):
                raise ValueError('Backup would reassign an existing account ID.')
            if row['id'] not in incoming:
                values = dict(row); values['disabled'] = 1
                fields = list(values)
                source.execute('INSERT INTO account_records ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', tuple(values.values()))
        live_links = {tuple(r[:3]):r[3] for r in live.execute('SELECT issuer,tenant,subject,app_user_id FROM identity_links')}
        for row in source.execute('SELECT issuer,tenant,subject,app_user_id FROM identity_links'):
            if tuple(row[:3]) in live_links and live_links[tuple(row[:3])] != row[3]:
                raise ValueError('Backup would reassign an authentication identity.')
        # Keep historical provider links reserved, including absent accounts.
        for key,value in live_links.items():
            source.execute('INSERT OR IGNORE INTO identity_links VALUES (?,?,?,?)', (*key,value))
        source.execute('DELETE FROM local_sessions')
        source.commit()
        if source.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Invalid account references in backup.')
