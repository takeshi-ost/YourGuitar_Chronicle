"""Persistent local operations settings, separate from the Chronicle database."""
import sqlite3
from datetime import datetime, timezone
from ygc import config


def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DATA_DIR / "operations.sqlite", timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL, message TEXT NOT NULL, version INTEGER NOT NULL)")
    con.execute("INSERT OR IGNORE INTO settings VALUES (1, 'normal', '', 0)")
    con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, mode TEXT NOT NULL, reason TEXT NOT NULL)")
    con.commit()
    return con


def state():
    con = connect()
    try:
        return dict(con.execute("SELECT mode,message,version FROM settings WHERE id=1").fetchone())
    finally:
        con.close()


def history():
    con = connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")]
    finally:
        con.close()


def update(mode, message, reason, version):
    con = connect()
    try:
        with con:
            result = con.execute("UPDATE settings SET mode=?,message=?,version=version+1 WHERE id=1 AND version=?", (mode,message,version))
            if not result.rowcount:
                raise ValueError("Settings changed. Refresh before saving.")
            con.execute("INSERT INTO events(occurred_at,mode,reason) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(),mode,reason))
    finally:
        con.close()
    return state()


def auto_crawl():
    con = connect()
    try:
        con.execute("CREATE TABLE IF NOT EXISTS auto_crawl (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, category TEXT NOT NULL, year_min INTEGER NOT NULL, year_max INTEGER NOT NULL, interval_seconds INTEGER NOT NULL, next_run REAL NOT NULL)")
        con.execute("INSERT OR IGNORE INTO auto_crawl VALUES(1,0,'electric_acoustic',1950,1980,3600,0)")
        con.execute("UPDATE auto_crawl SET category='electric_acoustic' WHERE id=1 AND category IN ('electric','acoustic')")
        con.commit()
        return dict(con.execute('SELECT * FROM auto_crawl WHERE id=1').fetchone())
    finally:
        con.close()


def set_auto_crawl(enabled, category, year_min, year_max, interval_seconds):
    import time
    auto_crawl()
    con = connect()
    try:
        with con:
            con.execute('UPDATE auto_crawl SET enabled=?,category=?,year_min=?,year_max=?,interval_seconds=?,next_run=? WHERE id=1',
                        (bool(enabled), category, year_min, year_max, interval_seconds, time.time()+interval_seconds))
            con.execute("INSERT INTO events(occurred_at,mode,reason) VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(),con.execute('SELECT mode FROM settings WHERE id=1').fetchone()[0],'Reverb Auto Crawl '+('ON' if enabled else 'OFF')))
    finally:
        con.close()
    return auto_crawl()


def reserve_auto_crawl(now):
    auto_crawl()
    con=connect()
    try:
        with con:
            return con.execute('UPDATE auto_crawl SET next_run=?+interval_seconds WHERE id=1 AND enabled=1 AND next_run<=?', (now,now)).rowcount == 1
    finally:
        con.close()


def chatgpt_review(enabled=None):
    con=connect()
    try:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS review_settings (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL)')
            con.execute('INSERT OR IGNORE INTO review_settings VALUES (1,1)')
            if enabled is not None:
                con.execute('UPDATE review_settings SET enabled=? WHERE id=1',(bool(enabled),))
                mode=con.execute('SELECT mode FROM settings WHERE id=1').fetchone()[0]
                con.execute('INSERT INTO events(occurred_at,mode,reason) VALUES (?,?,?)',(datetime.now(timezone.utc).isoformat(),mode,'ChatGPT review '+('ON' if enabled else 'OFF')))
        return {'enabled':bool(con.execute('SELECT enabled FROM review_settings WHERE id=1').fetchone()[0])}
    finally:
        con.close()


def retain_paused_answer(revision, kind, payload):
    import json
    con=connect()
    try:
        with con:
            con.execute('CREATE TABLE IF NOT EXISTS paused_review_answers (revision TEXT NOT NULL, kind TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(revision,kind))')
            encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
            previous=con.execute('SELECT payload FROM paused_review_answers WHERE revision=? AND kind=?',(revision,kind)).fetchone()
            if previous and previous[0]!=encoded:raise ValueError('A different answer was already retained while review was paused.')
            con.execute('INSERT OR IGNORE INTO paused_review_answers VALUES (?,?,?,?)',(revision,kind,datetime.now(timezone.utc).isoformat(),encoded))
    finally:
        con.close()


def last_paused_answer():
    con=connect()
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='paused_review_answers'").fetchone():return None
        return con.execute('SELECT MAX(received_at) FROM paused_review_answers WHERE kind LIKE \'%submit%\'').fetchone()[0]
    finally:
        con.close()
