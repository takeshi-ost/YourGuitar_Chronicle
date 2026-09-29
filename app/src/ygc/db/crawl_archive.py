"""Lossless, explicit preservation of unregistered legacy crawl records.

This is an archive, not an expiry cache. Nothing here deletes or rewrites
observations, Claims, crawl cursors, candidates, or public-status checks.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def archive_unregistered_crawl(db_path: Path) -> dict[str, int]:
    """Copy complete rows atomically; refuse changed or corrupt prior copies."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=rw', uri=True)) as con:
        con.row_factory = sqlite3.Row
        with con:
            con.execute('BEGIN IMMEDIATE')
            # Only add the archive; do not run unrelated startup migrations.
            con.execute(ARCHIVE_SCHEMA)
            rows = con.execute("""
                SELECT o.* FROM observations o
                WHERE o.individual_id IS NULL AND o.source_site <> 'user'
                  AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.observation_id=o.id)
                  AND NOT EXISTS (SELECT 1 FROM claim_source_evidence e
                                  WHERE e.legacy_observation_id=o.id OR
                                        (e.source_site=o.source_site AND
                                         e.source_listing_id=o.source_listing_id))
                ORDER BY o.id
            """).fetchall()
            created = 0
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                payload = json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'))
                digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
                previous = con.execute(
                    'SELECT payload_json,payload_sha256 FROM legacy_crawl_archive '
                    'WHERE legacy_observation_id=?', (row['id'],),
                ).fetchone()
                if previous:
                    if previous['payload_json'] != payload or previous['payload_sha256'] != digest:
                        raise ValueError(f'Archive mismatch for legacy observation {row["id"]}; no rows copied')
                    continue
                con.execute(
                    'INSERT INTO legacy_crawl_archive '
                    '(legacy_observation_id,payload_json,payload_sha256,archived_at) '
                    'VALUES (?,?,?,?)', (row['id'], payload, digest, now),
                )
                created += 1
            total = con.execute('SELECT COUNT(*) FROM legacy_crawl_archive').fetchone()[0]
            # Validate archived copies even when their original row is absent.
            for saved in con.execute('SELECT * FROM legacy_crawl_archive'):
                digest = hashlib.sha256(saved['payload_json'].encode('utf-8')).hexdigest()
                if digest != saved['payload_sha256']:
                    raise ValueError(f'Archive checksum mismatch for legacy observation {saved["legacy_observation_id"]}')
            return {'eligible': len(rows), 'created': created,
                    'already_archived': len(rows) - created, 'archive_total': total}


ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_crawl_archive (
 legacy_observation_id INTEGER PRIMARY KEY,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 payload_sha256 TEXT NOT NULL,
 archived_at TEXT NOT NULL
)
"""
