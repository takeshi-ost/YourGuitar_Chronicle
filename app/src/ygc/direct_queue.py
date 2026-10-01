"""Durable local experiment queue, isolated from the Chronicle database."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import secrets
import sqlite3
import time

from ygc import config

LEASE_SECONDS = 7200
MAX_ATTEMPTS = 3
MAX_JOBS = 100
MAX_IMAGE_STORAGE = 256 * 1024 * 1024


def utc(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat(timespec='seconds')


@contextmanager
def transaction():
    folder = config.DATA_DIR / 'direct-review'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    path = folder / 'queue.sqlite3'
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    os.chmod(path, 0o600)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL, revision TEXT UNIQUE NOT NULL,
                serial TEXT NOT NULL, challenge TEXT NOT NULL,
                images TEXT NOT NULL, image_meta TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                lease_token TEXT, lease_until REAL,
                error TEXT, received TEXT, result TEXT, report TEXT,
                prompt_version TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                revision TEXT NOT NULL REFERENCES jobs(revision) ON DELETE CASCADE,
                at TEXT NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL
            );
        ''')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def event(db, revision, kind, note=''):
    db.execute('INSERT INTO events(revision,at,kind,note) VALUES (?,?,?,?)', (revision, utc(), kind, note))


def token(db, create=False):
    row = db.execute("SELECT value FROM settings WHERE name='connection_token'").fetchone()
    if row:
        return row['value']
    if create:
        value = secrets.token_urlsafe(32)
        db.execute("INSERT INTO settings VALUES ('connection_token',?)", (value,))
        return value
    return None


def expire_leases(db):
    for row in db.execute("SELECT revision,attempts FROM jobs WHERE status='processing' AND lease_until<=?", (time.time(),)).fetchall():
        state = 'error' if row['attempts'] >= MAX_ATTEMPTS else 'pending'
        db.execute('UPDATE jobs SET status=?,lease_token=NULL,lease_until=NULL,error=? WHERE revision=?',
                   (state, '審議が2時間以内に完了しませんでした。', row['revision']))
        event(db, row['revision'], 'timeout', state)


def find(db, revision):
    row = db.execute('SELECT * FROM jobs WHERE revision=?', (revision,)).fetchone()
    if not row:
        raise ValueError('申請がありません。')
    return row


def detail(db, revision):
    row = find(db, revision)
    return dict(application_id=row['application_id'], revision=row['revision'], status=row['status'],
                created_at=row['created_at'], started_at=row['started_at'], completed_at=row['completed_at'],
                attempts=row['attempts'], lease_until=utc(row['lease_until']) if row['lease_until'] else None,
                error=row['error'], images=json.loads(row['image_meta']),
                result=json.loads(row['result']) if row['result'] else None,
                review=json.loads(row['received']) if row['received'] else None,
                report_text=row['report'], prompt_version=row['prompt_version'],
                events=[dict(e) for e in db.execute('SELECT at,kind,note FROM events WHERE revision=? ORDER BY id',(revision,))])


def listing(db):
    rows = db.execute('''SELECT application_id,revision,status,created_at,started_at,completed_at,
                        attempts,error,result FROM jobs ORDER BY seq DESC''').fetchall()
    return [dict(application_id=r['application_id'],revision=r['revision'],status=r['status'],
                 created_at=r['created_at'],started_at=r['started_at'],completed_at=r['completed_at'],
                 attempts=r['attempts'],error=r['error'],
                 accepted=json.loads(r['result'])['adjudication']['accepted'] if r['result'] else None) for r in rows]
