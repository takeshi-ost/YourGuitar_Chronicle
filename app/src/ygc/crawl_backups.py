"""Target-specific retained backups and persistent periodic schedules."""
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from ygc import config, operations

TARGETS = ('chronicle', 'operations', 'authentication', 'accounts')
_lock = threading.RLock()
MAX_BYTES = 512 * 1024 * 1024


def directory():
    return config.DATA_DIR / 'crawl_backups'


def policies():
    con = operations.connect()
    try:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS backup_settings (id INTEGER PRIMARY KEY CHECK(id=1), generations INTEGER NOT NULL)')
            con.execute('INSERT OR IGNORE INTO backup_settings VALUES (1,10)')
            con.execute('CREATE TABLE IF NOT EXISTS backup_schedules (target TEXT PRIMARY KEY, enabled INTEGER NOT NULL, interval_hours INTEGER NOT NULL, generations INTEGER NOT NULL, next_run REAL NOT NULL, last_at TEXT, last_status TEXT, last_error TEXT)')
            old = con.execute('SELECT generations FROM backup_settings WHERE id=1').fetchone()[0]
            for target in TARGETS:
                con.execute('INSERT OR IGNORE INTO backup_schedules VALUES (?,0,24,?,0,NULL,NULL,NULL)', (target, old if target == 'chronicle' else 10))
        return [dict(row) for row in con.execute('SELECT * FROM backup_schedules ORDER BY target')]
    finally:
        con.close()


def configure(target, *, generations=None, enabled=None, interval_hours=None):
    if target not in TARGETS:
        raise ValueError('Invalid backup target.')
    old = next(row for row in policies() if row['target'] == target)
    generations = old['generations'] if generations is None else generations
    interval_hours = old['interval_hours'] if interval_hours is None else interval_hours
    if not 1 <= generations <= 100 or not 1 <= interval_hours <= 168:
        raise ValueError('Keep 1–100 backups and use an interval of 1–168 hours.')
    enabled = old['enabled'] if enabled is None else bool(enabled)
    next_run = old['next_run'] if (enabled == old['enabled'] and interval_hours == old['interval_hours']) else time.time() + interval_hours * 3600
    con = operations.connect()
    try:
        with con:
            con.execute('UPDATE backup_schedules SET enabled=?,interval_hours=?,generations=?,next_run=? WHERE target=?', (enabled, interval_hours, generations, next_run, target))
            if target == 'chronicle':
                con.execute('UPDATE backup_settings SET generations=? WHERE id=1', (generations,))
    finally:
        con.close()
    return next(row for row in policies() if row['target'] == target)


def retention(value=None):
    if value is not None:
        return configure('chronicle', generations=value)['generations']
    return next(row for row in policies() if row['target'] == 'chronicle')['generations']


def files():
    return sorted(directory().glob('ygc_*.zip'), key=lambda p: p.name, reverse=True)


def metadata(path):
    sidecar = path.with_suffix('.json')
    if sidecar.is_file():
        return json.loads(sidecar.read_text())
    # Legacy Crawl archives remain usable.
    return {'target': 'chronicle', 'reason': 'crawl', 'created_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def listing():
    return [{'name': p.name, 'size_bytes': p.stat().st_size, **metadata(p)} for p in files() if not p.is_symlink()]


def selected(name):
    if Path(name).name != name or not name.startswith('ygc_') or not name.endswith('.zip'):
        raise ValueError('Invalid backup name.')
    path = directory() / name
    if not path.is_file() or path.is_symlink():
        raise ValueError('Backup not found.')
    return path


def database_path(target):
    if target == 'accounts':
        return config.ACCOUNTS_DB_PATH
    if target == 'operations':
        return config.DATA_DIR / 'operations.sqlite'
    if target == 'authentication':
        return config.DATA_DIR / 'direct-review' / 'queue.sqlite3'
    if target == 'chronicle':
        return config.DB_PATH
    raise ValueError('Invalid backup target.')


def auxiliary_export(target):
    from starlette.responses import FileResponse
    if target not in TARGETS[1:]:
        raise ValueError('Invalid backup target.')
    if target == 'operations':
        operations.auto_crawl()
        operations.chatgpt_review()
    path = database_path(target)
    if not path.is_file():
        raise ValueError('This database has not been created yet.')
    folder = Path(tempfile.mkdtemp(prefix='ygc_aux_backup_'))
    try:
        snapshot = folder / 'database.sqlite'
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
        if target == 'accounts':
            with sqlite3.connect(snapshot) as destination:
                destination.execute('DELETE FROM local_sessions')
        archive_path = folder / 'backup.zip'
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, 'database.sqlite')
            archive.writestr('manifest.json', json.dumps({'version': 1, 'target': target}))
            if target == 'accounts':
                root = config.DATA_DIR / 'account_media'
                for media in root.rglob('*'):
                    if media.is_file() and not media.is_symlink() and media.resolve().is_relative_to(root.resolve()):
                        archive.write(media, 'account_media/' + media.relative_to(root).as_posix())
        return FileResponse(archive_path)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def record_result(target, status, error=''):
    policies()
    con = operations.connect()
    try:
        with con:
            con.execute('UPDATE backup_schedules SET last_at=?,last_status=?,last_error=? WHERE target=?', (datetime.now(timezone.utc).isoformat(), status, error, target))
    finally:
        con.close()


def create(export, target='chronicle', reason='crawl'):
    if target not in TARGETS or reason not in ('crawl', 'manual', 'scheduled', 'before_restore'):
        raise ValueError('Invalid backup target or reason.')
    with _lock:
        directory().mkdir(parents=True, exist_ok=True, mode=0o700)
        source = None
        temporary = None
        try:
            response = export() if target == 'chronicle' else auxiliary_export(target)
            source = Path(response.path)
            name = 'ygc_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8] + '.zip'
            dest = directory() / name
            temporary = dest.with_suffix('.tmp')
            shutil.copyfile(source, temporary)
            os.chmod(temporary, 0o600)
            if temporary.stat().st_size > MAX_BYTES:
                raise ValueError('Backup exceeds the restore limit of 512 MB.')
            # Metadata is committed before the archive becomes visible.
            dest.with_suffix('.json').write_text(json.dumps({'target': target, 'reason': reason, 'created_at': datetime.now(timezone.utc).isoformat()}))
            os.chmod(dest.with_suffix('.json'), 0o600)
            temporary.replace(dest)
            keep = next(row['generations'] for row in policies() if row['target'] == target)
            same_target = [p for p in files() if metadata(p)['target'] == target]
            for obsolete in same_target[keep:]:
                obsolete.unlink()
                obsolete.with_suffix('.json').unlink(missing_ok=True)
            record_result(target, 'ok')
            return name
        except Exception as exc:
            record_result(target, 'error', str(exc))
            raise
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            if source:
                shutil.rmtree(source.parent, ignore_errors=True)


def scheduled_tick(export):
    if not _lock.acquire(blocking=False):
        return
    try:
        for row in policies():
            now = time.time()
            if not row['enabled'] or row['next_run'] > now:
                continue
            con = operations.connect()
            try:
                with con:
                    claimed = con.execute('UPDATE backup_schedules SET next_run=? WHERE target=? AND enabled=1 AND next_run<=?', (now + row['interval_hours'] * 3600, row['target'], now)).rowcount
            finally:
                con.close()
            if claimed:
                try:
                    create(export, row['target'], 'scheduled')
                except Exception:
                    pass  # The persistent status records failure; other targets still run.
    finally:
        _lock.release()


def restore_auxiliary(payload, target):
    """Validate a private SQLite archive, then replace only the selected DB atomically."""
    import io
    if target not in TARGETS[1:] or len(payload) > MAX_BYTES:
        raise ValueError('Invalid auxiliary backup.')
    with tempfile.TemporaryDirectory(prefix='ygc_restore_aux_') as folder:
        candidate = Path(folder) / 'database.sqlite'
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            extras = set(names) - {'database.sqlite', 'manifest.json'}
            valid_media = target == 'accounts' and all(n.startswith('account_media/users/') and Path(n).name == n.removeprefix('account_media/users/') for n in extras)
            if not {'database.sqlite','manifest.json'} <= set(names) or len(set(names)) != len(names) or (extras and not valid_media):
                raise ValueError('Invalid auxiliary backup contents.')
            if sum(info.file_size for info in archive.infolist()) > MAX_BYTES:
                raise ValueError('Expanded backup exceeds 512 MB.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('target') != target or manifest.get('version') != 1:
                raise ValueError('Backup target does not match the selected target.')
            candidate.write_bytes(archive.read('database.sqlite'))
            for name in extras:
                media = Path(folder) / name
                media.parent.mkdir(parents=True, exist_ok=True)
                media.write_bytes(archive.read(name))
        with sqlite3.connect(candidate) as source:
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or source.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Invalid SQLite database.')
            tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {'account_records','identity_links','local_sessions'} if target == 'accounts' else {'settings', 'events'} | ({'jobs'} if target == 'authentication' else {'auto_crawl', 'review_settings'})
            if not required <= tables:
                raise ValueError('Backup does not contain the required target tables.')
            if target == 'operations':
                mode = operations.state()
                schedules = policies()
                source.execute("UPDATE settings SET mode=?,message=?,version=? WHERE id=1", (mode['mode'], mode['message'], mode['version'] + 1))
                source.execute('UPDATE auto_crawl SET enabled=0')
                source.execute('UPDATE review_settings SET enabled=0')
                source.execute('CREATE TABLE IF NOT EXISTS backup_schedules (target TEXT PRIMARY KEY, enabled INTEGER NOT NULL, interval_hours INTEGER NOT NULL, generations INTEGER NOT NULL, next_run REAL NOT NULL, last_at TEXT, last_status TEXT, last_error TEXT)')
                source.execute('DELETE FROM backup_schedules')
                for row in schedules:
                    source.execute('INSERT INTO backup_schedules VALUES (?,?,?,?,?,?,?,?)', tuple(row[k] for k in ('target','enabled','interval_hours','generations','next_run','last_at','last_status','last_error')))
                source.execute('CREATE TABLE IF NOT EXISTS backup_settings (id INTEGER PRIMARY KEY CHECK(id=1), generations INTEGER NOT NULL)')
                source.execute('INSERT OR REPLACE INTO backup_settings VALUES (1,?)', (next(r['generations'] for r in schedules if r['target'] == 'chronicle'),))
            elif target == 'authentication':
                source.execute("DELETE FROM settings WHERE name='connection_token'")
                source.execute("UPDATE jobs SET status='pending',lease_token=NULL,lease_until=NULL,started_at=NULL WHERE status='processing'")
            source.commit()
            path = database_path(target)
            if target == 'accounts':
                from ygc.accounts import prepare_restore
                for (raw,) in source.execute('SELECT avatar_storage_path FROM account_records WHERE avatar_storage_path IS NOT NULL'):
                    relative = Path(raw)
                    if not raw.startswith('account_media/users/') or relative.name != raw.removeprefix('account_media/users/') or relative.name in ('.','..'):
                        raise ValueError('Invalid avatar path in account backup.')
                    if not (Path(folder) / relative).is_file():
                        raise ValueError('Account backup is missing an avatar image.')
                prepare_restore(candidate, path)
                # Store immutable image names before installing their references.
                for media in (Path(folder) / 'account_media' / 'users').glob('*'):
                    destination_media = config.DATA_DIR / 'account_media' / 'users' / media.name
                    destination_media.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    if destination_media.is_symlink():
                        raise ValueError('Avatar destination cannot be a symbolic link.')
                    shutil.copyfile(media,destination_media)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sqlite3.connect(path) as destination:
                source.backup(destination)
            os.chmod(path, 0o600)
