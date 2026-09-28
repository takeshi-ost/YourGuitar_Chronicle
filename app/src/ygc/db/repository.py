from __future__ import annotations

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ygc.extractors.normalization import (
    normalize_manufacturer,
    normalize_model,
    normalize_serial,
)
from ygc.theme_catalog import THEME_IDS
from ygc.observation_evaluator import FIELDS as OBSERVATION_FIELDS, evaluate_observation


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        con = sqlite3.connect(
            self.db_path
        )
        con.row_factory = sqlite3.Row
        con.execute(
            "PRAGMA foreign_keys = ON"
        )
        return con

    def backfill_claim_source_evidence(self) -> dict[str, int]:
        """Copy legacy external listing provenance without altering Claims or snapshots.

        A source occurrence belongs to its Listing or relisting Acquire Claim.
        Unregistered crawl observations deliberately stay outside Individual data.
        This may be run repeatedly; conflicting links are reported, not overwritten.
        """
        created = existing = conflicts = 0
        with self.connect() as con:
            rows = con.execute(
                """SELECT o.id AS legacy_id, o.source_site, o.source_listing_id,
                          o.source_url, o.observed_at, o.listing_date,
                          o.owner_name, o.owner_type, o.location_country,
                          o.location_region, o.raw_text, o.title, o.image_url,
                          o.serial_confidence, o.extraction_version,
                          c.id AS claim_id, c.claim_type, c.ownership_kind,
                          c.occurred_at
                   FROM observations o
                   JOIN claims c ON c.observation_id=o.id
                   WHERE o.source_site <> 'user'
                     AND o.source_listing_id IS NOT NULL
                     AND (c.claim_type='listing' OR
                          (c.claim_type='ownership' AND c.ownership_kind='acquire'))
                   ORDER BY o.id, CASE c.claim_type WHEN 'listing' THEN 0 ELSE 1 END, c.id"""
            ).fetchall()
            for row in rows:
                prior = con.execute(
                    """SELECT claim_id FROM claim_source_evidence
                       WHERE legacy_observation_id=? OR (source_site=? AND source_listing_id=?)""",
                    (row['legacy_id'], row['source_site'], row['source_listing_id']),
                ).fetchone()
                if prior:
                    if prior['claim_id'] == row['claim_id']:
                        existing += 1
                    else:
                        conflicts += 1
                    continue
                detail = con.execute(
                    """SELECT payload_json FROM crawl_detail_cache
                       WHERE source_site=? AND source_listing_id=?""",
                    (row['source_site'], row['source_listing_id']),
                ).fetchone()
                claim_payload = {
                    'legacy_observation_id': row['legacy_id'],
                    'owner_name': row['owner_name'], 'owner_type': row['owner_type'],
                    'location_country': row['location_country'],
                    'location_region': row['location_region'],
                }
                source_payload = {
                    'legacy_observation_id': row['legacy_id'],
                    'title': row['title'], 'raw_text': row['raw_text'],
                    'image_url': row['image_url'],
                    'serial_confidence': row['serial_confidence'],
                    'extraction_version': row['extraction_version'],
                }
                if detail:
                    source_payload['raw_detail'] = json.loads(detail['payload_json'])
                payload = json.dumps({'claim': claim_payload, 'source': source_payload},
                                     ensure_ascii=False)
                is_acquire = row['claim_type'] == 'ownership'
                con.execute(
                    """INSERT INTO claim_source_evidence
                       (claim_id,evidence_type,source_site,source_listing_id,
                        source_url,captured_at,effective_date,date_basis,
                        payload_json,legacy_observation_id,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (row['claim_id'], 'marketplace_listing', row['source_site'],
                     row['source_listing_id'], row['source_url'], row['observed_at'],
                     row['occurred_at'] if is_acquire else row['listing_date'],
                     'observed_at' if is_acquire else 'listing_date', payload,
                     row['legacy_id'], utcnow()),
                )
                created += 1
        return {'created': created, 'existing': existing, 'conflicts': conflicts}

    def backfill_acquisition_date_evidence(self) -> dict[str, int]:
        """Copy explicitly recorded dates on older user Acquire Claims.

        Never infer an acquisition date from submission time or a marketplace
        observation; those have different meanings and stay distinguishable.
        """
        created = existing = missing_date = 0
        with self.connect() as con:
            claims = con.execute(
                """SELECT id,author_user_id,occurred_at FROM claims
                   WHERE claim_type='ownership' AND ownership_kind='acquire'
                     AND COALESCE(ownership_source,'user') NOT IN ('automation','merged_listing')
                   ORDER BY id"""
            ).fetchall()
            for claim in claims:
                if con.execute(
                    """SELECT 1 FROM claim_source_evidence
                       WHERE claim_id=? AND evidence_type='acquisition_date'""",
                    (claim['id'],),
                ).fetchone():
                    existing += 1
                    continue
                date = str(claim['occurred_at'] or '')
                try:
                    if len(date) != 10:
                        raise ValueError('Incomplete date')
                    datetime.strptime(date, '%Y-%m-%d')
                except ValueError:
                    missing_date += 1
                    continue
                con.execute(
                    """INSERT INTO claim_source_evidence
                       (claim_id,evidence_type,effective_date,date_basis,payload_json,created_at)
                       VALUES (?, 'acquisition_date', ?, 'legacy_claim_date', ?, ?)""",
                    (claim['id'], date,
                     json.dumps({'reported_by_user_id': claim['author_user_id']}, ensure_ascii=False),
                     utcnow()),
                )
                created += 1
        return {'created': created, 'existing': existing, 'missing_date': missing_date}

    def observation_diagnostic(self, individual_id: int) -> dict[str, Any]:
        """Compare a read-only Observation evaluation to the saved Individual."""
        with self.connect() as con:
            con.execute('PRAGMA query_only=ON')
            row = con.execute('SELECT * FROM individuals WHERE id=?',
                              (individual_id,)).fetchone()
            if row is None:
                raise ValueError('Individual not found')
            evaluated = evaluate_observation(con, individual_id)
            current = {field: row[field] for field in OBSERVATION_FIELDS}
            differences = {
                field: {'saved': current[field], 'evaluated': evaluated.values[field],
                        'claim_id': evaluated.sources.get(field)}
                for field in OBSERVATION_FIELDS
                if (str(current[field]) if current[field] is not None else None) !=
                   (str(evaluated.values[field]) if evaluated.values[field] is not None else None)
            }
            return {**evaluated.as_dict(), 'saved': current, 'differences': differences}

    def audit_observation_migration(self, sample_limit: int = 20) -> dict[str, Any]:
        """Compare every Individual on a consistent, read-only DB snapshot."""
        if sample_limit < 0 or sample_limit > 100:
            raise ValueError('sample_limit must be between 0 and 100')
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        with self.connect() as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            try:
                ids = [int(row[0]) for row in con.execute('SELECT id FROM individuals ORDER BY id')]
                mismatched = failed = 0
                mismatch_fields: dict[str, int] = {}
                samples: list[dict[str, Any]] = []
                for individual_id in ids:
                    try:
                        individual = con.execute('SELECT * FROM individuals WHERE id=?',
                                                 (individual_id,)).fetchone()
                        evaluated = evaluate_observation(con, individual_id)
                        differing = [field for field in OBSERVATION_FIELDS
                                     if (str(individual[field]) if individual[field] is not None else None)
                                     != (str(evaluated.values[field]) if evaluated.values[field] is not None else None)]
                    except (ValueError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
                        failed += 1
                        if len(samples) < sample_limit:
                            samples.append({'individual_id': individual_id, 'error': str(exc)})
                        continue
                    if differing:
                        mismatched += 1
                        for field in differing:
                            mismatch_fields[field] = mismatch_fields.get(field, 0) + 1
                        if len(samples) < sample_limit:
                            samples.append({'individual_id': individual_id, 'fields': differing})
                source_missing = con.execute(
                    """SELECT COUNT(*) FROM claims c JOIN observations o ON o.id=c.observation_id
                       WHERE o.source_site<>'user' AND o.source_listing_id IS NOT NULL
                         AND (c.claim_type='listing' OR
                              (c.claim_type='ownership' AND c.ownership_kind='acquire'))
                         AND NOT EXISTS (SELECT 1 FROM claim_source_evidence e
                                         WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing')"""
                ).fetchone()[0]
                date_missing = con.execute(
                    """SELECT COUNT(*) FROM claims c
                       WHERE c.claim_type='ownership' AND c.ownership_kind='acquire'
                         AND COALESCE(c.ownership_source,'user') NOT IN ('automation','merged_listing')
                         AND (c.occurred_at IS NULL OR LENGTH(c.occurred_at)<>10 OR
                              NOT EXISTS (SELECT 1 FROM claim_source_evidence e
                                          WHERE e.claim_id=c.id AND e.evidence_type='acquisition_date'
                                            AND e.effective_date=c.occurred_at))"""
                ).fetchone()[0]
                result = {
                    'individuals_checked': len(ids), 'individuals_mismatched': mismatched,
                    'evaluation_errors': failed, 'mismatch_fields': mismatch_fields,
                    'samples': samples, 'marketplace_claims_without_evidence': source_missing,
                    'user_acquires_without_date_evidence': date_missing,
                    'unregistered_legacy_crawl_rows': con.execute(
                        'SELECT COUNT(*) FROM observations WHERE individual_id IS NULL'
                    ).fetchone()[0],
                }
                return result
            finally:
                con.rollback()

    @staticmethod
    def _insert_marketplace_evidence(con: sqlite3.Connection, claim_id: int,
                                     observation_id: int, claim_data: dict,
                                     provenance: dict, *, acquire: bool) -> None:
        """Keep the new Evidence and the legacy crawl record in one transaction."""
        con.execute(
            """INSERT INTO claim_source_evidence
               (claim_id,evidence_type,source_site,source_listing_id,
                source_url,captured_at,effective_date,date_basis,payload_json,
                legacy_observation_id,created_at)
               VALUES (?, 'marketplace_listing', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, provenance.get('source_site') or 'reverb',
             str(provenance['source_listing_id']), provenance.get('source_url') or '',
             provenance.get('observed_at'),
             (provenance.get('observed_at') if acquire else
              claim_data.get('listing_date') or provenance.get('listing_date')),
             'observed_at' if acquire else 'listing_date',
             json.dumps({'claim': claim_data, 'provenance': provenance},
                        ensure_ascii=False, default=str),
             observation_id, utcnow()),
        )

    def init_db(self) -> None:
        schema_path = Path(
            __file__
        ).with_name(
            "schema.sql"
        )

        with self.connect() as con:
            con.executescript(
                schema_path.read_text(
                    encoding="utf-8"
                )
            )
            self._migrate_metadata_columns(
                con
            )

    @staticmethod
    def _table_columns(
        con: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        return {
            str(row["name"])
            for row
            in con.execute(
                f"PRAGMA table_info({table})"
            )
        }

    def _migrate_metadata_columns(
        self,
        con: sqlite3.Connection,
    ) -> None:
        migrations = {
            "individuals": {
                "finish": "TEXT",
                "year": "TEXT",
                "location_country": "TEXT",
                "location_region": "TEXT",
                "current_owner_name": "TEXT",
                "current_owner_type": "TEXT",
                "current_owner_user_id": "INTEGER",
                "current_owner_source_url": "TEXT",
                "representative_media_asset_id": "INTEGER",
            },
            "users": {
                "ban_status": "TEXT NOT NULL DEFAULT 'normal'",
                "identity_provider": "TEXT",
                "identity_subject": "TEXT",
                "bio": "TEXT",
                "avatar_storage_path": "TEXT",
                "avatar_original_filename": "TEXT",
                "avatar_mime_type": "TEXT",
                "birth_visibility": "TEXT NOT NULL DEFAULT 'Private'",
                "residence_visibility": "TEXT NOT NULL DEFAULT 'Private'",
                "bio_visibility": "TEXT NOT NULL DEFAULT 'Public'",
                "avatar_visibility": "TEXT NOT NULL DEFAULT 'Public'",
                "signature_individual_id": "INTEGER",
                "theme": "TEXT NOT NULL DEFAULT 'dark_default'",
                # Older databases restrict users.theme to the first three choices.
                # Store curated additions here without rebuilding the referenced users table.
                "theme_override": "TEXT",
            },
            "user_guitars": {
                "display_order": "INTEGER",
            },
            "claims": {
                "specification_kind": "TEXT",
                "ownership_kind": "TEXT",
                "ownership_source": "TEXT",
                "ownership_pair_id": "TEXT",
                "target_claim_id": "INTEGER",
                "verification_status": "TEXT NOT NULL DEFAULT 'positive'",
                "admin_verification": "INTEGER NOT NULL DEFAULT 0",
            },
            "crawl_runs": {
                "category": "TEXT",
                "year_min": "INTEGER",
                "year_max": "INTEGER",
                "phase": "TEXT",
                "counts_json": "TEXT",
                "updated_at": "TEXT",
            },
            "observations": {
                "event_type": "TEXT NOT NULL DEFAULT 'listing'",
                "actor_user_id": "INTEGER",
                "occurred_at": "TEXT",
                "finish": "TEXT",
                "year": "TEXT",
                "image_url": "TEXT",
                "owner_name": "TEXT",
                "owner_type": "TEXT",
                "owner_profile_url": "TEXT",
                "location_country": "TEXT",
                "location_region": "TEXT",
                "location_source": "TEXT",
            },
        }

        for table, columns in (
            migrations.items()
        ):
            existing = (
                self._table_columns(
                    con,
                    table,
                )
            )

            for (
                column,
                data_type,
            ) in columns.items():
                if column in existing:
                    continue

                con.execute(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN {column} "
                    f"{data_type}"
                )

        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_identity_subject "
                    "ON users(identity_provider, identity_subject) WHERE identity_subject IS NOT NULL")

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_claims_target_claim_id
            ON claims(target_claim_id)
            """
        )

        # Backfill Former Owner pairs created before ownership_source existed.
        former_links = list(
            con.execute(
                """
                SELECT
                    user_id,
                    individual_id,
                    acquired_at,
                    released_at
                FROM user_guitars
                WHERE ownership_status = 'former_owner'
                  AND acquired_at IS NOT NULL
                  AND released_at IS NOT NULL
                """
            )
        )
        for link in former_links:
            acquire = con.execute(
                """
                SELECT id
                FROM claims
                WHERE individual_id = ?
                  AND author_user_id = ?
                  AND claim_type = 'ownership'
                  AND COALESCE(ownership_kind, 'acquire') = 'acquire'
                  AND substr(COALESCE(occurred_at, ''), 1, 10) = substr(?, 1, 10)
                  AND COALESCE(ownership_source, '') = ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    link["individual_id"],
                    link["user_id"],
                    link["acquired_at"],
                ),
            ).fetchone()
            release = con.execute(
                """
                SELECT id
                FROM claims
                WHERE individual_id = ?
                  AND author_user_id = ?
                  AND claim_type = 'ownership'
                  AND ownership_kind = 'release'
                  AND substr(COALESCE(occurred_at, ''), 1, 10) = substr(?, 1, 10)
                  AND COALESCE(ownership_source, '') = ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    link["individual_id"],
                    link["user_id"],
                    link["released_at"],
                ),
            ).fetchone()
            if acquire and release:
                pair_id = str(uuid.uuid4())
                con.execute(
                    """
                    UPDATE claims
                    SET ownership_source = 'former_owner',
                        ownership_pair_id = ?,
                        verification_status = 'unverified'
                    WHERE id IN (?, ?)
                    """,
                    (
                        pair_id,
                        acquire["id"],
                        release["id"],
                    ),
                )

        con.execute(
            """
            UPDATE observations
            SET owner_name = COALESCE(
                    NULLIF(owner_name, ''),
                    seller
                ),
                owner_type = COALESCE(
                    NULLIF(owner_type, ''),
                    CASE
                        WHEN source_site = 'reverb'
                         AND seller IS NOT NULL
                         AND TRIM(seller) <> ''
                        THEN 'shop'
                        ELSE NULL
                    END
                )
            WHERE source_site = 'reverb'
            """
        )

    def _source_user_id(
        self,
        con: sqlite3.Connection,
        source_name: str,
    ) -> int:
        row = con.execute(
            """
            SELECT id
            FROM users
            WHERE account_type = 'source'
              AND display_name = ?
            ORDER BY id
            LIMIT 1
            """,
            (
                source_name,
            ),
        ).fetchone()

        if row:
            return int(
                row["id"]
            )

        now = utcnow()
        cur = con.execute(
            """
            INSERT INTO users (
                display_name,
                account_type,
                created_at,
                updated_at
            )
            VALUES (?, 'source', ?, ?)
            """,
            (
                source_name,
                now,
                now,
            ),
        )

        return int(
            cur.lastrowid
        )

    def _backfill_listing_claims(
        self,
        con: sqlite3.Connection,
    ) -> int:
        source_ids: dict[str, int] = {}
        created = 0

        rows = list(
            con.execute(
                """
                SELECT o.*
                FROM observations o
                WHERE o.individual_id
                      IS NOT NULL
                  AND COALESCE(
                        o.event_type,
                        'listing'
                      ) = 'listing'
                  AND NOT EXISTS (
                        SELECT 1
                        FROM claims c
                        WHERE c.observation_id
                              = o.id
                          AND c.claim_type
                              = 'listing'
                  )
                ORDER BY o.id
                """
            )
        )

        for row in rows:
            source_site = str(
                row["source_site"]
                or "source"
            ).strip()
            source_name = "Automation"

            if source_name not in source_ids:
                source_ids[
                    source_name
                ] = self._source_user_id(
                    con,
                    source_name,
                )

            occurred_at = (
                row["listing_date"]
                or row["occurred_at"]
                or row["observed_at"]
            )

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, 'listing',
                    'listing', ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    row["individual_id"],
                    row["id"],
                    source_ids[
                        source_name
                    ],
                    (
                        row[
                            "source_listing_id"
                        ]
                        or row[
                            "source_url"
                        ]
                    ),
                    row["title"],
                    occurred_at,
                    row["created_at"],
                    row["created_at"],
                ),
            )
            claim_id = int(cur.lastrowid)
            created += 1

            listing_values = {
                "manufacturer": row["manufacturer"],
                "model": row["model"],
                "finish": row["finish"],
                "year": row["year"],
                "serial_number": row["serial_number"],
                "owner_name": row["owner_name"],
                "owner_type": row["owner_type"],
                "owner_user_id": row["actor_user_id"],
                "seller": row["seller"],
                "location_country": row["location_country"],
                "location_region": row["location_region"],
                "listing_title": row["title"],
                "listing_date": occurred_at,
                "source_site": row["source_site"],
                "source_url": row["source_url"],
                "source_listing_id": row["source_listing_id"],
                "image_url": row["image_url"],
            }
            for field_name, value in listing_values.items():
                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                con.execute(
                    """
                    INSERT INTO claim_listing_items (
                        claim_id,
                        field_name,
                        value_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        field_name,
                        value_text,
                        row["created_at"],
                    ),
                )

        return created

    def _backfill_listing_claim_items(
        self,
        con: sqlite3.Connection,
    ) -> int:
        """
        One-time compatibility migration.

        Older Listing Claims kept their structured values only on the
        attached Observation. Copy those values into the Claim-owned
        structured item table. After migration, normal reads must use
        claim_listing_items rather than Observation metadata.
        """
        inserted = 0
        rows = list(
            con.execute(
                """
                SELECT
                    c.id AS claim_id,
                    c.created_at,
                    o.manufacturer,
                    o.model,
                    o.finish,
                    o.year,
                    o.serial_number,
                    COALESCE(
                        owner_user.display_name,
                        o.owner_name
                    ) AS owner_name,
                    o.location_country,
                    o.location_region,
                    o.owner_type,
                    CASE
                        WHEN o.owner_type = 'user'
                        THEN o.actor_user_id
                        ELSE NULL
                    END AS owner_user_id,
                    o.seller,
                    o.title AS listing_title,
                    COALESCE(
                        o.listing_date,
                        o.occurred_at,
                        o.observed_at
                    ) AS listing_date,
                    o.source_site,
                    o.source_url,
                    o.source_listing_id,
                    o.image_url
                FROM claims c
                INNER JOIN observations o
                  ON o.id = c.observation_id
                LEFT JOIN users owner_user
                  ON owner_user.id = o.actor_user_id
                 AND o.owner_type = 'user'
                WHERE c.claim_type = 'listing'
                ORDER BY c.id
                """
            )
        )

        fields = (
            "manufacturer",
            "model",
            "finish",
            "year",
            "serial_number",
            "owner_name",
            "owner_type",
            "owner_user_id",
            "seller",
            "location_country",
            "location_region",
            "listing_title",
            "listing_date",
            "source_site",
            "source_url",
            "source_listing_id",
            "image_url",
        )

        for row in rows:
            for field_name in fields:
                value = row[field_name]
                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO claim_listing_items (
                        claim_id,
                        field_name,
                        value_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        row["claim_id"],
                        field_name,
                        value_text,
                        row["created_at"],
                    ),
                )
                inserted += int(
                    cur.rowcount > 0
                )

        return inserted

    def claim_architecture_status(
        self,
    ) -> dict[str, Any]:
        """
        Diagnose whether the database is ready for Claim-centered writes.
        This method does not modify data.
        """
        with self.connect() as con:
            unmigrated_listing_observations = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM observations o
                    WHERE o.individual_id IS NOT NULL
                      AND COALESCE(
                            o.event_type,
                            'listing'
                          ) = 'listing'
                      AND NOT EXISTS (
                            SELECT 1
                            FROM claims c
                            WHERE c.observation_id = o.id
                              AND c.claim_type = 'listing'
                      )
                    """
                ).fetchone()[0]
            )

            claimless_individuals = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM individuals i
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM claims c
                        WHERE c.individual_id = i.id
                          AND c.claim_type = 'listing'
                          AND c.status = 'active'
                    )
                    """
                ).fetchone()[0]
            )

            active_listing_claims = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM claims
                    WHERE claim_type = 'listing'
                      AND status = 'active'
                    """
                ).fetchone()[0]
            )

            incomplete_identity_claims = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM claims c
                    WHERE c.claim_type = 'listing'
                      AND c.status = 'active'
                      AND (
                            NOT EXISTS (
                                SELECT 1
                                FROM claim_listing_items li
                                WHERE li.claim_id = c.id
                                  AND li.field_name = 'manufacturer'
                                  AND TRIM(li.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1
                                FROM claim_listing_items li
                                WHERE li.claim_id = c.id
                                  AND li.field_name = 'serial_number'
                                  AND TRIM(li.value_text) <> ''
                            )
                      )
                    """
                ).fetchone()[0]
            )

            pending_shells = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM individuals
                    WHERE manufacturer = '__pending__'
                       OR normalized_manufacturer
                          LIKE '__pending__:%'
                       OR normalized_serial
                          LIKE '__pending__:%'
                    """
                ).fetchone()[0]
            )

            stale_owner_snapshots = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM individuals i
                    WHERE i.current_owner_name IS NULL
                      AND EXISTS (
                            SELECT 1
                            FROM claims c
                            INNER JOIN claim_listing_items li
                              ON li.claim_id = c.id
                             AND li.field_name = 'owner_name'
                             AND TRIM(li.value_text) <> ''
                            WHERE c.individual_id = i.id
                              AND c.claim_type = 'listing'
                              AND c.status = 'active'
                      )
                    """
                ).fetchone()[0]
            )

            listing_claims_missing_location = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM claims c
                    WHERE c.claim_type = 'listing'
                      AND c.status = 'active'
                      AND EXISTS (
                            SELECT 1
                            FROM claim_listing_items src
                            WHERE src.claim_id = c.id
                              AND src.field_name = 'source_site'
                              AND LOWER(TRIM(src.value_text)) = 'reverb'
                      )
                      AND NOT EXISTS (
                            SELECT 1
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'location_country'
                              AND TRIM(li.value_text) <> ''
                      )
                    """
                ).fetchone()[0]
            )

            ready = (
                unmigrated_listing_observations == 0
                and claimless_individuals == 0
                and incomplete_identity_claims == 0
                and pending_shells == 0
                and stale_owner_snapshots == 0
            )

            return {
                "ready": ready,
                "migration_required": (
                    unmigrated_listing_observations > 0
                    or claimless_individuals > 0
                ),
                "unmigrated_listing_observations": (
                    unmigrated_listing_observations
                ),
                "claimless_individuals": (
                    claimless_individuals
                ),
                "active_listing_claims": (
                    active_listing_claims
                ),
                "incomplete_identity_claims": (
                    incomplete_identity_claims
                ),
                "pending_shells": (
                    pending_shells
                ),
                "stale_owner_snapshots": (
                    stale_owner_snapshots
                ),
                "listing_claims_missing_location": (
                    listing_claims_missing_location
                ),
                "backfill_recommended": (
                    listing_claims_missing_location > 0
                ),
            }

    def rebuild_all_individual_snapshots(
        self,
    ) -> dict[str, int]:
        rebuilt = 0
        skipped = 0

        with self.connect() as con:
            individual_ids = [
                int(row["id"])
                for row
                in con.execute(
                    """
                    SELECT id
                    FROM individuals
                    ORDER BY id
                    """
                )
            ]

            for individual_id in individual_ids:
                try:
                    self._rebuild_individual_snapshot_in_connection(
                        con,
                        individual_id,
                    )
                except ValueError:
                    skipped += 1
                    continue
                rebuilt += 1

        return {
            "snapshots_rebuilt": rebuilt,
            "snapshots_skipped": skipped,
        }

    def migrate_legacy_observations_to_claims(
        self,
    ) -> dict[str, int]:
        """
        Explicit compatibility migration for pre-Claim-centered databases.

        This operation is intentionally separate from init_db(). It is
        idempotent: existing Listing Claims are detected by their linked
        Observation, and structured Listing items use a unique
        (claim_id, field_name) key with INSERT OR IGNORE.
        """
        with self.connect() as con:
            claims_created = (
                self._backfill_listing_claims(
                    con
                )
            )
            items_created = (
                self._backfill_listing_claim_items(
                    con
                )
            )

            migrated_individuals = [
                int(row["individual_id"])
                for row
                in con.execute(
                    """
                    SELECT DISTINCT c.individual_id
                    FROM claims c
                    WHERE c.claim_type = 'listing'
                      AND c.observation_id IS NOT NULL
                    ORDER BY c.individual_id
                    """
                )
            ]

            snapshots_rebuilt = 0
            for individual_id in migrated_individuals:
                try:
                    self._rebuild_individual_snapshot_in_connection(
                        con,
                        individual_id,
                    )
                except ValueError:
                    # Some legacy rows may not have enough identity data
                    # to build a valid snapshot yet. Preserve them for a
                    # later repair/backfill rather than aborting migration.
                    continue
                snapshots_rebuilt += 1

            return {
                "claims_created": claims_created,
                "listing_items_created": items_created,
                "snapshots_rebuilt": snapshots_rebuilt,
            }

    def rebuild_individual_snapshot(
        self,
        individual_id: int,
    ) -> dict[str, Any]:
        """
        Rebuild one Individual's materialized current state from its logical
        Observation evaluation of Claims and Evidence. Legacy crawl rows are
        not an input to the result.
        """
        with self.connect() as con:
            return self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )

    def _rebuild_individual_snapshot_in_connection(
        self,
        con: sqlite3.Connection,
        individual_id: int,
    ) -> dict[str, Any]:
        individual = con.execute(
            """
            SELECT id
            FROM individuals
            WHERE id = ?
            """,
            (individual_id,),
        ).fetchone()
        if not individual:
            raise ValueError(
                "Individual not found"
            )

        # One logical Observation evaluates the Claims for this Individual.
        # Build the candidate without writing; only a valid complete identity
        # is materialized to Individual and user_guitars below.
        evaluation = evaluate_observation(con, individual_id)
        state = evaluation.values

        normalized_maker = normalize_manufacturer(
            state["manufacturer"]
            or ""
        )
        normalized_model = normalize_model(
            state["model"]
        )
        normalized_serial = normalize_serial(
            state["serial_number"]
            or ""
        )

        if (
            not normalized_maker
            or not normalized_serial
        ):
            raise ValueError(
                "Active Claims do not define a complete Individual identity"
            )

        now = utcnow()
        con.execute(
            """
            UPDATE individuals
            SET manufacturer = ?,
                model = ?,
                finish = ?,
                year = ?,
                serial_number = ?,
                location_country = ?,
                location_region = ?,
                current_owner_name = ?,
                current_owner_type = ?,
                current_owner_user_id = ?,
                current_owner_source_url = ?,
                normalized_manufacturer = ?,
                normalized_model = ?,
                normalized_serial = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                state["manufacturer"],
                state["model"],
                state["finish"],
                state["year"],
                state["serial_number"],
                state["location_country"],
                state["location_region"],
                state["current_owner_name"],
                state["current_owner_type"],
                state["current_owner_user_id"],
                state["current_owner_source_url"],
                normalized_maker,
                normalized_model,
                normalized_serial,
                now,
                individual_id,
            ),
        )

        # Keep the user's Owned / Formerly Owned classification derived
        # from the same Claim-ordered snapshot as Current Owner.  This avoids
        # action-order bugs when an Ownership Claim is entered with a
        # backdated occurred_at value.
        effective_owner_user_id = state["current_owner_user_id"]
        con.execute(
            """
            UPDATE user_guitars
            SET ownership_status = CASE
                    WHEN ? IS NOT NULL
                     AND CAST(user_id AS TEXT) = CAST(? AS TEXT)
                    THEN 'current_owner'
                    ELSE 'former_owner'
                END,
                updated_at = ?
            WHERE individual_id = ?
            """,
            (
                effective_owner_user_id,
                effective_owner_user_id,
                now,
                individual_id,
            ),
        )

        return {
            "id": individual_id,
            **state,
            "normalized_manufacturer": (
                normalized_maker
            ),
            "normalized_model": (
                normalized_model
            ),
            "normalized_serial": (
                normalized_serial
            ),
        }

    def find_individual(
        self,
        maker: str,
        model: str | None,
        serial: str,
    ):
        with self.connect() as con:
            return con.execute(
                """
                SELECT *
                FROM individuals
                WHERE normalized_manufacturer=?
                  AND COALESCE(normalized_model,'')
                      = COALESCE(?,'')
                  AND normalized_serial=?
                """,
                (
                    maker,
                    model,
                    serial,
                ),
            ).fetchone()

    def create_individual(
        self,
        manufacturer: str,
        model: str | None,
        serial_number: str,
        norm_maker: str,
        norm_model: str | None,
        norm_serial: str,
        finish: str | None = None,
        year: str | None = None,
    ) -> int:
        now = utcnow()

        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO individuals (
                    manufacturer,
                    model,
                    finish,
                    year,
                    serial_number,
                    normalized_manufacturer,
                    normalized_model,
                    normalized_serial,
                    created_at,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    manufacturer,
                    model,
                    finish,
                    year,
                    serial_number,
                    norm_maker,
                    norm_model,
                    norm_serial,
                    now,
                    now,
                ),
            )

            return int(
                cur.lastrowid
            )

    def update_individual_metadata(
        self,
        individual_id: int,
        model: str | None = None,
        finish: str | None = None,
        year: str | None = None,
    ) -> None:
        with self.connect() as con:
            if con.execute(
                "SELECT 1 FROM claims WHERE individual_id = ? AND status = 'active' LIMIT 1",
                (individual_id,),
            ).fetchone():
                raise ValueError(
                    "Claim-backed Individuals must be changed through Claims"
                )
            con.execute(
                """
                UPDATE individuals
                SET model = COALESCE(model, ?),
                    finish = COALESCE(finish, ?),
                    year = COALESCE(year, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    model,
                    finish,
                    year,
                    utcnow(),
                    individual_id,
                ),
            )

    def persist_reverb_listing_claim(
        self,
        claim_data: dict[str, Any],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist one Reverb Listing through the Claim-centered pipeline.

        External duplicate detection uses Observation provenance.
        Physical guitar matching uses the current Individual snapshot.
        Semantic state is written only to Listing Claim items, then the
        Individual snapshot is rebuilt from active Claims.
        """
        source_site = str(
            provenance.get("source_site")
            or "reverb"
        ).strip()
        source_listing_id = str(
            provenance.get("source_listing_id")
            or ""
        ).strip()
        if not source_listing_id:
            raise ValueError(
                "source_listing_id is required"
            )

        maker = str(
            claim_data.get("manufacturer")
            or ""
        ).strip()
        model = (
            str(claim_data.get("model")).strip()
            if claim_data.get("model") is not None
            and str(claim_data.get("model")).strip()
            else None
        )
        serial = str(
            claim_data.get("serial_number")
            or ""
        ).strip()

        normalized_maker = normalize_manufacturer(
            maker
        )
        normalized_model = normalize_model(
            model
        )
        normalized_serial = normalize_serial(
            serial
        )

        with self.connect() as con:
            recorded_source = con.execute(
                """SELECT o.id AS legacy_observation_id,c.individual_id
                   FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
                   LEFT JOIN observations o ON o.id=e.legacy_observation_id
                   WHERE e.source_site=? AND e.source_listing_id=? LIMIT 1""",
                (source_site, source_listing_id),
            ).fetchone()
            if recorded_source:
                return {
                    'created': False,
                    'observation_id': recorded_source['legacy_observation_id'],
                    'claim_id': None,
                    'individual_id': int(recorded_source['individual_id']),
                }
            existing_observation = con.execute(
                """
                SELECT
                    id,
                    individual_id
                FROM observations
                WHERE source_site = ?
                  AND source_listing_id = ?
                ORDER BY id
                LIMIT 1
                """,
                (
                    source_site,
                    source_listing_id,
                ),
            ).fetchone()
            if existing_observation:
                return {
                    "created": False,
                    "observation_id": int(
                        existing_observation["id"]
                    ),
                    "claim_id": None,
                    "individual_id": (
                        int(
                            existing_observation[
                                "individual_id"
                            ]
                        )
                        if existing_observation[
                            "individual_id"
                        ] is not None
                        else None
                    ),
                }

            individual_id: int | None = None
            existing_individual = None

            if (
                normalized_maker
                and normalized_serial
            ):
                existing_individual = con.execute(
                    """
                    SELECT *
                    FROM individuals
                    WHERE normalized_manufacturer = ?
                      AND COALESCE(
                            normalized_model,
                            ''
                          ) = COALESCE(?, '')
                      AND normalized_serial = ?
                    ORDER BY id
                    LIMIT 1
                    """,
                    (
                        normalized_maker,
                        normalized_model,
                        normalized_serial,
                    ),
                ).fetchone()

                if existing_individual:
                    individual_id = int(
                        existing_individual["id"]
                    )
                    has_listing_claim = con.execute(
                        """
                        SELECT 1
                        FROM claims
                        WHERE individual_id = ?
                          AND claim_type = 'listing'
                          AND status = 'active'
                        LIMIT 1
                        """,
                        (
                            individual_id,
                        ),
                    ).fetchone()
                    if not has_listing_claim:
                        raise ValueError(
                            "Matched Individual has no active Listing Claim. "
                            "Run legacy Observation migration before crawling."
                        )
                else:
                    pending_token = (
                        "__pending__:"
                        + uuid.uuid4().hex
                    )
                    cur = con.execute(
                        """
                        INSERT INTO individuals (
                            manufacturer,
                            normalized_manufacturer,
                            normalized_serial,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            "__pending__",
                            pending_token,
                            pending_token,
                            provenance.get(
                                "created_at"
                            )
                            or utcnow(),
                            provenance.get(
                                "created_at"
                            )
                            or utcnow(),
                        ),
                    )
                    individual_id = int(
                        cur.lastrowid
                    )

            observation_columns = [
                "individual_id",
                "owner_name",
                "owner_type",
                "location_country",
                "location_region",
                "event_type",
                "source_site",
                "source_url",
                "image_url",
                "source_listing_id",
                "observed_at",
                "listing_date",
                "title",
                "raw_text",
                "serial_confidence",
                "extraction_version",
                "created_at",
            ]
            observation_values = {
                "individual_id": individual_id,
                "owner_name": claim_data.get("owner_name"),
                "owner_type": claim_data.get("owner_type"),
                "location_country": claim_data.get("location_country"),
                "location_region": claim_data.get("location_region"),
                "event_type": (
                    provenance.get(
                        "event_type"
                    )
                    or "listing"
                ),
                "source_site": source_site,
                "source_url": (
                    provenance.get(
                        "source_url"
                    )
                    or ""
                ),
                "image_url": provenance.get(
                    "image_url"
                ),
                "source_listing_id": (
                    source_listing_id
                ),
                "observed_at": (
                    provenance.get(
                        "observed_at"
                    )
                    or utcnow()
                ),
                "listing_date": provenance.get(
                    "listing_date"
                ),
                "title": provenance.get(
                    "title"
                ),
                "raw_text": provenance.get(
                    "raw_text"
                ),
                "serial_confidence": (
                    provenance.get(
                        "serial_confidence"
                    )
                ),
                "extraction_version": (
                    provenance.get(
                        "extraction_version"
                    )
                ),
                "created_at": (
                    provenance.get(
                        "created_at"
                    )
                    or utcnow()
                ),
            }
            placeholders = ",".join(
                "?"
                for _ in observation_columns
            )
            cur = con.execute(
                f"""
                INSERT INTO observations (
                    {",".join(observation_columns)}
                )
                VALUES ({placeholders})
                """,
                [
                    observation_values[column]
                    for column
                    in observation_columns
                ],
            )
            observation_id = int(
                cur.lastrowid
            )

            if individual_id is None:
                return {
                    "created": True,
                    "observation_id": observation_id,
                    "claim_id": None,
                    "individual_id": None,
                }

            author_user_id = self._source_user_id(
                con,
                "Automation",
            )
            if existing_individual is not None:
                current_owner_user_id = existing_individual["current_owner_user_id"]
                verification = "unverified" if current_owner_user_id else "positive"
                occurred_at = provenance.get("observed_at") or utcnow()
                now = provenance.get("created_at") or utcnow()
                cur = con.execute(
                    """
                    INSERT INTO claims (
                        individual_id, observation_id, author_user_id,
                        claim_type, field_name, value_text, ownership_kind,
                        ownership_source, verification_status, occurred_at,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'ownership', 'owner', ?, 'acquire',
                              'automation', ?, ?, 'active', ?, ?)
                    """,
                    (individual_id, observation_id, author_user_id,
                     claim_data.get("owner_name"), verification, occurred_at, now, now),
                )
                claim_id = int(cur.lastrowid)
                self._insert_marketplace_evidence(
                    con, claim_id, observation_id, claim_data, provenance,
                    acquire=True,
                )
                if verification == "positive":
                    self._rebuild_individual_snapshot_in_connection(con, individual_id)
                return {
                    "created": True, "observation_id": observation_id,
                    "claim_id": claim_id, "individual_id": individual_id,
                    "verification_status": verification,
                }
            occurred_at = (
                claim_data.get(
                    "listing_date"
                )
                or provenance.get(
                    "listing_date"
                )
                or provenance.get(
                    "observed_at"
                )
                or utcnow()
            )
            now = provenance.get(
                "created_at"
            ) or utcnow()

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, 'listing',
                    'listing', ?, NULL, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    observation_id,
                    author_user_id,
                    source_listing_id,
                    occurred_at,
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
            )

            listing_fields = (
                "manufacturer",
                "model",
                "finish",
                "year",
                "serial_number",
                "owner_name",
                "owner_type",
                "seller",
                "location_country",
                "location_region",
                "listing_title",
                "listing_date",
                "source_site",
                "source_url",
                "source_listing_id",
                "image_url",
            )
            for field_name in listing_fields:
                value = claim_data.get(
                    field_name
                )
                if value is None:
                    continue
                value_text = str(
                    value
                ).strip()
                if not value_text:
                    continue
                con.execute(
                    """
                    INSERT INTO claim_listing_items (
                        claim_id,
                        field_name,
                        value_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        field_name,
                        value_text,
                        now,
                    ),
                )

            self._insert_marketplace_evidence(
                con, claim_id, observation_id, claim_data, provenance,
                acquire=False,
            )

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )

            return {
                "created": True,
                "observation_id": observation_id,
                "claim_id": claim_id,
                "individual_id": individual_id,
            }

    def record_reverb_unavailable(self, listing_id: str) -> dict[str, Any]:
        """Record a confirmed absence as a Claim, preserving independent owners."""
        with self.connect() as con:
            evidence = con.execute(
                """SELECT e.claim_id,e.legacy_observation_id,e.source_url,c.individual_id
                   FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
                   WHERE e.source_site='reverb' AND e.source_listing_id=?
                   LIMIT 1""",
                (listing_id,),
            ).fetchone()
            observation = evidence or con.execute(
                "SELECT id, individual_id, source_url FROM observations "
                "WHERE source_site = 'reverb' AND source_listing_id = ?",
                (listing_id,),
            ).fetchone()
            if not observation or observation["individual_id"] is None:
                return {"created": False, "reason": "no_individual"}
            legacy_id = (observation['legacy_observation_id'] if evidence else observation['id'])
            source_claim_id = evidence['claim_id'] if evidence else None
            individual_id = int(observation["individual_id"])
            individual = con.execute(
                "SELECT current_owner_user_id, current_owner_source_url "
                "FROM individuals WHERE id = ?", (individual_id,),
            ).fetchone()
            reverb_only = bool(
                individual and individual["current_owner_user_id"] is None
                and individual["current_owner_source_url"]
                and individual["current_owner_source_url"] == observation["source_url"]
            )
            if con.execute(
                "SELECT 1 FROM claims WHERE (observation_id = ? OR target_claim_id = ?) AND "
                "status = 'active' AND ((ownership_source = 'automation' AND ownership_kind = 'release') "
                "OR (claim_type = 'event' AND value_text = 'reverb_unavailable'))",
                (legacy_id, source_claim_id),
            ).fetchone():
                return {"created": False, "reason": "already_recorded"}
            author_id = self._source_user_id(con, "Automation")
            now = utcnow()
            cur = con.execute(
                """INSERT INTO claims (
                    individual_id, observation_id, target_claim_id, author_user_id,
                    claim_type, field_name, value_text, ownership_kind,
                    ownership_source, body, occurred_at, status,
                    verification_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active',
                          'positive', ?, ?)""",
                (individual_id, legacy_id if con.execute(
                    'SELECT 1 FROM observations WHERE id=?', (legacy_id,)).fetchone() else None,
                 source_claim_id, author_id,
                 "ownership" if reverb_only else "event",
                 "owner" if reverb_only else "event",
                 "unknown" if reverb_only else "reverb_unavailable",
                 "release" if reverb_only else None,
                 "automation" if reverb_only else None,
                 "Reverb listing no longer publicly available (confirmed twice).",
                 now, now, now),
            )
            if reverb_only:
                self._rebuild_individual_snapshot_in_connection(con, individual_id)
            return {"created": True, "claim_id": int(cur.lastrowid),
                    "owner_released": reverb_only, "individual_id": individual_id}

    def upsert_observation(
        self,
        obs: dict[str, Any],
    ):
        with self.connect() as con:
            existing = con.execute(
                """
                SELECT id
                FROM observations
                WHERE source_site=?
                  AND source_listing_id=?
                """,
                (
                    obs["source_site"],
                    obs[
                        "source_listing_id"
                    ],
                ),
            ).fetchone()

            if existing:
                return (
                    int(
                        existing["id"]
                    ),
                    False,
                )

            columns = [
                "individual_id",
                "manufacturer",
                "model",
                "finish",
                "year",
                "serial_number",
                "owner_name",
                "owner_type",
                "owner_profile_url",
                "location_country",
                "location_region",
                "location_source",
                "seller",
                "source_site",
                "source_url",
                "image_url",
                "source_listing_id",
                "observed_at",
                "listing_date",
                "title",
                "raw_text",
                "serial_confidence",
                "extraction_version",
                "created_at",
            ]

            values = [
                obs.get(column)
                for column
                in columns
            ]

            placeholders = ",".join(
                "?"
                for _ in columns
            )

            cur = con.execute(
                f"""
                INSERT INTO observations (
                    {",".join(columns)}
                )
                VALUES ({placeholders})
                """,
                values,
            )

            return (
                int(
                    cur.lastrowid
                ),
                True,
            )

    def list_listing_claims_for_backfill(
        self,
    ) -> list[sqlite3.Row]:
        """
        Return active Reverb Listing Claims whose structured Claim data
        is incomplete and can be supplemented by refetching the source.
        """
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        c.id AS claim_id,
                        c.individual_id,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_listing_id'
                            LIMIT 1
                        ) AS source_listing_id,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'model'
                            LIMIT 1
                        ) AS model,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'finish'
                            LIMIT 1
                        ) AS finish,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'year'
                            LIMIT 1
                        ) AS year,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'image_url'
                            LIMIT 1
                        ) AS image_url,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'owner_name'
                            LIMIT 1
                        ) AS owner_name,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'location_country'
                            LIMIT 1
                        ) AS location_country,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'location_region'
                            LIMIT 1
                        ) AS location_region
                    FROM claims c
                    WHERE c.claim_type = 'listing'
                      AND c.status = 'active'
                      AND EXISTS (
                            SELECT 1
                            FROM claim_listing_items src
                            WHERE src.claim_id = c.id
                              AND src.field_name = 'source_site'
                              AND LOWER(TRIM(src.value_text)) = 'reverb'
                      )
                      AND (
                            NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'model'
                                  AND TRIM(x.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'finish'
                                  AND TRIM(x.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'year'
                                  AND TRIM(x.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'image_url'
                                  AND TRIM(x.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'owner_name'
                                  AND TRIM(x.value_text) <> ''
                            )
                            OR NOT EXISTS (
                                SELECT 1 FROM claim_listing_items x
                                WHERE x.claim_id = c.id
                                  AND x.field_name = 'location_country'
                                  AND TRIM(x.value_text) <> ''
                            )
                      )
                    ORDER BY c.id
                    """
                )
            )

    def supplement_listing_claim(
        self,
        claim_id: int,
        values: dict[str, Any],
    ) -> bool:
        """
        Fill missing structured fields on an existing Listing Claim.

        Existing non-empty Claim values are preserved. Observation is not
        modified. The Individual snapshot is rebuilt when data is added.
        """
        allowed_fields = {
            "model",
            "finish",
            "year",
            "image_url",
            "owner_name",
            "owner_type",
            "seller",
            "location_country",
            "location_region",
            "listing_title",
            "listing_date",
            "source_url",
        }

        with self.connect() as con:
            claim = con.execute(
                """
                SELECT id, individual_id
                FROM claims
                WHERE id = ?
                  AND claim_type = 'listing'
                  AND status = 'active'
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return False

            inserted = False
            now = utcnow()

            for field_name, value in values.items():
                if field_name not in allowed_fields:
                    continue
                if value is None:
                    continue

                value_text = str(value).strip()
                if not value_text:
                    continue

                existing = con.execute(
                    """
                    SELECT value_text
                    FROM claim_listing_items
                    WHERE claim_id = ?
                      AND field_name = ?
                    LIMIT 1
                    """,
                    (
                        claim_id,
                        field_name,
                    ),
                ).fetchone()
                if (
                    existing
                    and existing["value_text"] is not None
                    and str(existing["value_text"]).strip()
                ):
                    continue

                con.execute(
                    """
                    INSERT INTO claim_listing_items (
                        claim_id,
                        field_name,
                        value_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(claim_id, field_name)
                    DO UPDATE SET value_text = excluded.value_text
                    """,
                    (
                        claim_id,
                        field_name,
                        value_text,
                        now,
                    ),
                )
                inserted = True

            if inserted:
                self._rebuild_individual_snapshot_in_connection(
                    con,
                    int(claim["individual_id"]),
                )

            return inserted

    def statistics(
        self,
    ) -> dict[str, Any]:
        with self.connect() as con:
            summary = con.execute(
                """
                SELECT
                    COUNT(*) AS individuals,
                    COUNT(
                        DISTINCT NULLIF(
                            TRIM(manufacturer),
                            ''
                        )
                    ) AS makers,
                    COUNT(
                        DISTINCT NULLIF(
                            TRIM(model),
                            ''
                        )
                    ) AS models,
                    COUNT(
                        DISTINCT NULLIF(
                            TRIM(finish),
                            ''
                        )
                    ) AS finishes
                FROM individuals
                """
            ).fetchone()

            def grouped(
                expression: str,
                where_sql: str,
                limit: int = 10,
            ) -> list[dict[str, Any]]:
                rows = con.execute(
                    f"""
                    SELECT
                        {expression} AS label,
                        COUNT(*) AS count
                    FROM individuals
                    WHERE {where_sql}
                    GROUP BY {expression}
                    ORDER BY
                        count DESC,
                        label COLLATE NOCASE
                    LIMIT ?
                    """,
                    (
                        limit,
                    ),
                )

                return [
                    {
                        "label": str(
                            row["label"]
                        ),
                        "count": int(
                            row["count"]
                        ),
                    }
                    for row in rows
                ]

            maker_counts = grouped(
                "TRIM(manufacturer)",
                (
                    "manufacturer IS NOT NULL "
                    "AND TRIM(manufacturer) <> ''"
                ),
            )

            model_counts = grouped(
                "TRIM(model)",
                (
                    "model IS NOT NULL "
                    "AND TRIM(model) <> ''"
                ),
            )

            finish_counts = grouped(
                "TRIM(finish)",
                (
                    "finish IS NOT NULL "
                    "AND TRIM(finish) <> ''"
                ),
            )

            latest_locations = list(
                con.execute(
                    """
                    SELECT
                        TRIM(location_country)
                            AS label,
                        COUNT(*) AS count
                    FROM individuals
                    WHERE location_country
                          IS NOT NULL
                      AND TRIM(
                            location_country
                      ) <> ''
                    GROUP BY
                        TRIM(
                            location_country
                        )
                    ORDER BY
                        count DESC,
                        label COLLATE NOCASE
                    LIMIT 10
                    """
                )
            )

            located_individuals = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM individuals
                    WHERE location_country
                          IS NOT NULL
                      AND TRIM(
                            location_country
                      ) <> ''
                    """
                ).fetchone()[0]
            )

            return {
                "summary": {
                    "individuals": int(
                        summary["individuals"]
                    ),
                    "makers": int(
                        summary["makers"]
                    ),
                    "models": int(
                        summary["models"]
                    ),
                    "finishes": int(
                        summary["finishes"]
                    ),
                    "located_individuals": (
                        located_individuals
                    ),
                },
                "makers": maker_counts,
                "models": model_counts,
                "finishes": finish_counts,
                "current_countries": [
                    {
                        "label": str(
                            row["label"]
                        ),
                        "count": int(
                            row["count"]
                        ),
                    }
                    for row
                    in latest_locations
                ],
            }


    def create_user(
        self,
        display_name: str | None = None,
    ) -> int:
        now = utcnow()

        with self.connect() as con:
            if display_name:
                name = display_name.strip()
            else:
                next_id = int(
                    con.execute(
                        "SELECT COALESCE(MAX(id), 0) + 1 FROM users"
                    ).fetchone()[0]
                )
                name = f"User {next_id}"

            cur = con.execute(
                """
                INSERT INTO users (
                    display_name,
                    account_type,
                    created_at,
                    updated_at
                )
                VALUES (?, 'user', ?, ?)
                """,
                (
                    name or "User",
                    now,
                    now,
                ),
            )

            return int(
                cur.lastrowid
            )

    def list_users(
        self,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        COALESCE(u.theme_override,u.theme) AS theme,
                        u.*,
                        COUNT(
                            CASE
                                WHEN ug.ownership_status
                                     = 'current_owner'
                                THEN 1
                            END
                        ) AS current_guitar_count
                    FROM users u
                    LEFT JOIN user_guitars ug
                      ON ug.user_id = u.id
                    WHERE u.account_type <> 'source'
                    GROUP BY u.id
                    ORDER BY u.id
                    """
                )
            )

    def get_user(
        self,
        user_id: int,
    ) -> tuple[
        sqlite3.Row | None,
        list[sqlite3.Row],
    ]:
        with self.connect() as con:
            user = con.execute(
                """
                SELECT COALESCE(theme_override,theme) AS theme, *
                FROM users
                WHERE id = ?
                """,
                (
                    user_id,
                ),
            ).fetchone()

            guitars = list(
                con.execute(
                    """
                    SELECT
                        ug.*,
                        i.manufacturer,
                        i.model,
                        i.finish,
                        i.year,
                        i.serial_number,
                        (SELECT COUNT(*) FROM claims c
                         WHERE c.individual_id = i.id
                           AND c.status = 'active') AS claim_count
                    FROM user_guitars ug
                    INNER JOIN individuals i
                      ON i.id = ug.individual_id
                    WHERE ug.user_id = ?
                      AND (ug.ownership_status <> 'former_owner'
                           OR EXISTS (
                               SELECT 1 FROM claims c
                               WHERE c.individual_id=ug.individual_id
                                 AND c.author_user_id=ug.user_id
                                 AND c.claim_type='ownership'
                                 AND c.ownership_kind='acquire'
                                 AND c.status='active'
                                 AND c.verification_status='positive'
                           )
                           OR EXISTS (
                               SELECT 1 FROM claims c
                               JOIN claim_listing_items li ON li.claim_id=c.id
                               WHERE c.individual_id=ug.individual_id
                                 AND c.claim_type='listing'
                                 AND c.status='active'
                                 AND c.verification_status='positive'
                                 AND li.field_name='owner_user_id'
                                 AND li.value_text=CAST(ug.user_id AS TEXT)
                           )
                           OR NOT EXISTS (
                               SELECT 1 FROM claims c
                               WHERE c.individual_id=ug.individual_id
                                 AND c.author_user_id=ug.user_id
                                 AND c.claim_type='ownership'
                                 AND c.ownership_kind='acquire'
                                 AND c.ownership_source='former_owner'
                           ))
                    ORDER BY
                        CASE
                            WHEN ug.ownership_status
                                 = 'current_owner'
                            THEN 0
                            ELSE 1
                        END,
                        CASE
                            WHEN ug.display_order
                                 IS NULL
                            THEN 1
                            ELSE 0
                        END,
                        ug.display_order,
                        ug.id
                    """,
                    (
                        user_id,
                    ),
                )
            )

            return (
                user,
                guitars,
            )

    def get_user_favorites(self, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(con.execute("""
                SELECT f.individual_id, f.created_at, i.manufacturer, i.model,
                       i.finish, i.year, i.serial_number,
                       (SELECT COUNT(*) FROM claims c WHERE c.individual_id=i.id
                        AND c.status='active') AS claim_count
                FROM user_favorites f
                JOIN individuals i ON i.id=f.individual_id
                WHERE f.user_id=?
                ORDER BY f.created_at DESC, f.individual_id DESC
            """, (user_id,)))

    def set_user_favorite(self, user_id: int, individual_id: int, favorite: bool) -> bool:
        with self.connect() as con:
            user = con.execute("SELECT account_type, ban_status FROM users WHERE id=?", (user_id,)).fetchone()
            if not user or user['account_type'] == 'source' or user['ban_status'] == 'ban':
                raise ValueError("User not available")
            if not con.execute("SELECT 1 FROM individuals WHERE id=?", (individual_id,)).fetchone():
                raise ValueError("Guitar not found")
            if favorite:
                con.execute("INSERT OR IGNORE INTO user_favorites (user_id, individual_id, created_at) VALUES (?,?,?)",
                            (user_id, individual_id, utcnow()))
            else:
                con.execute("DELETE FROM user_favorites WHERE user_id=? AND individual_id=?", (user_id, individual_id))
            return favorite

    def preview_silent_profile(self, user_id: int, individual_id: int | None = None) -> dict:
        """Show a silent user's own Claim-derived state without persisting it."""
        with self.connect() as con:
            user = con.execute("SELECT ban_status FROM users WHERE id=?", (user_id,)).fetchone()
            if not user or user["ban_status"] != 'silent_ban':
                return {}
            con.execute('SAVEPOINT silent_preview')
            try:
                con.execute("UPDATE users SET ban_status='normal' WHERE id=?", (user_id,))
                ids = {r[0] for r in con.execute(
                    "SELECT DISTINCT individual_id FROM claims WHERE author_user_id=?", (user_id,))}
                ids.update(r[0] for r in con.execute(
                    "SELECT DISTINCT c.individual_id FROM claims c JOIN claim_listing_items li "
                    "ON li.claim_id=c.id WHERE li.field_name='owner_user_id' AND li.value_text=?",
                    (str(user_id),)))
                for iid in (ids if individual_id is None else ids & {individual_id}):
                    self._rebuild_individual_snapshot_in_connection(con, iid)
                if individual_id is not None:
                    row = con.execute("SELECT * FROM individuals WHERE id=?", (individual_id,)).fetchone()
                    return dict(row) if row else {}
                rows = con.execute("SELECT individual_id,ownership_status FROM user_guitars WHERE user_id=?",
                                   (user_id,)).fetchall()
                return {int(r['individual_id']): r['ownership_status'] for r in rows}
            finally:
                con.execute('ROLLBACK TO silent_preview')
                con.execute('RELEASE silent_preview')

    def list_user_chronicle(self, user_id: int, limit: int = 100, viewer_user_id: int | None = None) -> list[dict[str, Any]]:
        """Visible user milestones and actions, sorted by the time they happened."""
        entries: list[dict[str, Any]] = []

        def add(category: str, when: str | None, subject: str, message: str,
                individual_id: int | None = None) -> None:
            if when:
                entries.append({
                    "category": category, "event_at": when,
                    "subject": subject, "message": message,
                    "individual_id": individual_id,
                })

        def product_name(row: sqlite3.Row) -> str:
            return " ".join(part for part in (row["manufacturer"], row["model"]) if part) \
                or f"Product #{row['individual_id']}"

        with self.connect() as con:
            user = con.execute(
                "SELECT display_name, created_at, updated_at, ban_status FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not user:
                return []
            name = str(user["display_name"])
            add("User", user["created_at"], name, "joined Your Guitar Chronicle.")
            if user["updated_at"] > user["created_at"]:
                add("User", user["updated_at"], name, "updated their profile.")

            products = "JOIN individuals i ON i.id = c.individual_id"
            claims = con.execute(f"""
                SELECT c.id, c.individual_id, c.claim_type, c.ownership_kind,
                       c.specification_kind, c.value_text, c.created_at,
                       i.manufacturer, i.model
                FROM claims c {products}
                WHERE c.author_user_id = ? AND c.status = 'active' AND EXISTS (SELECT 1 FROM users actor WHERE actor.id=c.author_user_id AND (actor.ban_status='normal' OR (actor.ban_status='silent_ban' AND actor.id=?)))
                ORDER BY c.created_at DESC, c.id DESC LIMIT ?
            """, (user_id, viewer_user_id, limit))
            for row in claims:
                kind = str(row["claim_type"])
                if kind == "ownership":
                    kind = str(row["ownership_kind"] or "acquire")
                elif kind == "specification" and row["specification_kind"] == "repair":
                    kind = "repair"
                elif kind in ("incident", "event"):
                    kind = str(row["value_text"] or kind)
                add("Claim", row["created_at"], product_name(row),
                    f"has a new {kind.replace('_', ' ').title()} Claim on record.",
                    int(row["individual_id"]))

            for table, actor, value, action in (
                ("claim_votes", "user_id", "vote", "voted"),
                ("claim_responses", "responder_user_id", "stance", "responded"),
            ):
                rows = con.execute(f"""
                    SELECT c.individual_id, i.manufacturer, i.model,
                           interaction.{value} AS value, interaction.updated_at
                    FROM {table} interaction
                    JOIN claims c ON c.id = interaction.claim_id AND c.status = 'active'
                    JOIN users actor ON actor.id=c.author_user_id AND (actor.ban_status='normal' OR (actor.ban_status='silent_ban' AND actor.id=?) )
                    JOIN individuals i ON i.id = c.individual_id
                    WHERE interaction.{actor} = ? AND EXISTS (SELECT 1 FROM users participant WHERE participant.id=interaction.{actor} AND participant.ban_status<>'ban')
                    ORDER BY interaction.updated_at DESC, interaction.id DESC LIMIT ?
                """, (viewer_user_id, user_id, limit))
                for row in rows:
                    value_text = str(row["value"] or "").replace("_", " ").title()
                    message = (f"has a Claim with a {value_text} vote from this user."
                               if action == "voted" else
                               f"has a Claim with a {value_text} response from this user.")
                    add("Social", row["updated_at"], product_name(row),
                        message, int(row["individual_id"]))

            links = con.execute("""
                SELECT ug.individual_id, ug.created_at, i.manufacturer, i.model
                FROM user_guitars ug
                JOIN individuals i ON i.id = ug.individual_id
                WHERE ug.user_id = ?
                ORDER BY ug.created_at DESC, ug.id DESC LIMIT ?
            """, (user_id, limit))
            for row in links:
                if user["ban_status"] == 'silent_ban' and viewer_user_id != user_id:
                    continue
                add("Product", row["created_at"], product_name(row),
                    "was added to this user's Chronicle.", int(row["individual_id"]))

        def sort_time(item: dict[str, Any]) -> float:
            try:
                timestamp = datetime.fromisoformat(item["event_at"].replace("Z", "+00:00"))
                return timestamp.replace(tzinfo=timezone.utc).timestamp() \
                    if timestamp.tzinfo is None else timestamp.timestamp()
            except ValueError:
                return 0.0

        entries.sort(key=sort_time, reverse=True)
        return entries[:limit]

    def create_claim_notification(
        self,
        claim_id: int,
    ) -> int | None:
        now = utcnow()
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT
                    c.id,
                    c.individual_id,
                    c.author_user_id,
                    c.claim_type,
                    c.specification_kind,
                    c.ownership_source,
                    u.display_name AS author_name,
                    i.manufacturer,
                    i.model,
                    i.serial_number,
                    i.current_owner_user_id
                FROM claims c
                INNER JOIN users u
                  ON u.id = c.author_user_id
                INNER JOIN individuals i
                  ON i.id = c.individual_id
                WHERE c.id = ?
                  AND c.status = 'active'
                  AND u.ban_status='normal'
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return None

            recipient = claim["current_owner_user_id"]
            if recipient is None:
                return None
            if int(recipient) == int(claim["author_user_id"]):
                return None

            claim_type = str(claim["claim_type"] or "claim")
            if claim_type == "specification":
                label = (
                    "Repair"
                    if str(claim["specification_kind"] or "") == "repair"
                    else "Specification"
                )
            elif (
                claim_type == "ownership"
                and str(claim["ownership_source"] or "") == "former_owner"
            ):
                label = "Former Owner"
            else:
                label = claim_type.replace("_", " ").title()

            guitar = " ".join(
                part
                for part in (
                    str(claim["manufacturer"] or "").strip(),
                    str(claim["model"] or "").strip(),
                )
                if part
            ) or f"Individual #{claim['individual_id']}"

            cur = con.execute(
                """
                INSERT INTO notifications (
                    recipient_user_id,
                    actor_user_id,
                    notification_type,
                    individual_id,
                    claim_id,
                    title,
                    body,
                    is_read,
                    created_at
                )
                VALUES (?, ?, 'claim_added', ?, ?, ?, ?, 0, ?)
                """,
                (
                    int(recipient),
                    int(claim["author_user_id"]),
                    int(claim["individual_id"]),
                    int(claim["id"]),
                    f"New {label} Claim",
                    f"{claim['author_name']} added a {label} Claim to {guitar}.",
                    now,
                ),
            )
            return int(cur.lastrowid)

    def create_verification_notification(
        self,
        claim_id: int,
        verifier_user_id: int,
        stance: str,
    ) -> int | None:
        now = utcnow()
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT
                    c.id,
                    c.individual_id,
                    c.author_user_id,
                    c.claim_type,
                    c.ownership_source,
                    i.manufacturer,
                    i.model,
                    v.display_name AS verifier_name
                FROM claims c
                INNER JOIN individuals i
                  ON i.id = c.individual_id
                INNER JOIN users v
                  ON v.id = ?
                WHERE c.id = ?
                """,
                (
                    verifier_user_id,
                    claim_id,
                ),
            ).fetchone()
            if not claim:
                return None
            if int(claim["author_user_id"]) == int(verifier_user_id):
                return None

            guitar = " ".join(
                part
                for part in (
                    str(claim["manufacturer"] or "").strip(),
                    str(claim["model"] or "").strip(),
                )
                if part
            ) or f"Individual #{claim['individual_id']}"

            cur = con.execute(
                """
                INSERT INTO notifications (
                    recipient_user_id,
                    actor_user_id,
                    notification_type,
                    individual_id,
                    claim_id,
                    title,
                    body,
                    is_read,
                    created_at
                )
                VALUES (?, ?, 'claim_verified', ?, ?, ?, ?, 0, ?)
                """,
                (
                    int(claim["author_user_id"]),
                    int(verifier_user_id),
                    int(claim["individual_id"]),
                    int(claim["id"]),
                    f"Claim Verification: {stance.title()}",
                    f"{claim['verifier_name']} set your Claim on {guitar} to {stance.title()}.",
                    now,
                ),
            )
            return int(cur.lastrowid)

    def list_notifications(
        self,
        user_id: int,
        *,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        n.*,
                        actor.display_name AS actor_name,
                        i.manufacturer,
                        i.model,
                        i.serial_number
                    FROM notifications n
                    LEFT JOIN users actor
                      ON actor.id = n.actor_user_id
                    LEFT JOIN individuals i
                      ON i.id = n.individual_id
                    WHERE n.recipient_user_id = ?
                      AND (n.actor_user_id IS NULL OR actor.ban_status='normal')
                      AND (n.claim_id IS NULL OR EXISTS
                          (SELECT 1 FROM claims c JOIN users author ON author.id=c.author_user_id
                           WHERE c.id=n.claim_id AND c.status='active' AND author.ban_status='normal'))
                    ORDER BY n.created_at DESC, n.id DESC
                    LIMIT ?
                    """,
                    (
                        user_id,
                        max(1, min(int(limit), 100)),
                    ),
                )
            )

    def unread_notification_count(
        self,
        user_id: int,
    ) -> int:
        with self.connect() as con:
            return int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM notifications n
                    LEFT JOIN users actor ON actor.id=n.actor_user_id
                    WHERE n.recipient_user_id = ?
                      AND n.is_read = 0
                      AND (n.actor_user_id IS NULL OR actor.ban_status='normal')
                      AND (n.claim_id IS NULL OR EXISTS
                          (SELECT 1 FROM claims c JOIN users author ON author.id=c.author_user_id
                           WHERE c.id=n.claim_id AND c.status='active' AND author.ban_status='normal'))
                    """,
                    (user_id,),
                ).fetchone()[0]
            )

    def mark_notification_read(
        self,
        notification_id: int,
        user_id: int,
    ) -> bool:
        now = utcnow()
        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE notifications
                SET is_read = 1,
                    read_at = COALESCE(read_at, ?)
                WHERE id = ?
                  AND recipient_user_id = ?
                """,
                (
                    now,
                    notification_id,
                    user_id,
                ),
            )
            return cur.rowcount > 0

    def mark_all_notifications_read(
        self,
        user_id: int,
    ) -> int:
        now = utcnow()
        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE notifications
                SET is_read = 1,
                    read_at = COALESCE(read_at, ?)
                WHERE recipient_user_id = ?
                  AND is_read = 0
                """,
                (
                    now,
                    user_id,
                ),
            )
            return int(cur.rowcount)

    def get_user_summary(
        self,
        user_id: int,
        viewer_user_id: int | None = None,
    ) -> dict[str, int]:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM user_guitars
                        WHERE user_id = ?
                          AND ownership_status = 'current_owner'
                    ) AS owned_count,
                    (
                        SELECT COUNT(*)
                        FROM user_guitars
                        WHERE user_id = ?
                          AND ownership_status = 'former_owner'
                          AND (EXISTS (
                              SELECT 1 FROM claims c
                              WHERE c.individual_id=user_guitars.individual_id
                                AND c.author_user_id=user_guitars.user_id
                                AND c.claim_type='ownership'
                                AND c.ownership_kind='acquire'
                                AND c.status='active'
                                AND c.verification_status='positive'
                          ) OR EXISTS (
                              SELECT 1 FROM claims c
                              JOIN claim_listing_items li ON li.claim_id=c.id
                              WHERE c.individual_id=user_guitars.individual_id
                                AND c.claim_type='listing'
                                AND c.status='active'
                                AND c.verification_status='positive'
                                AND li.field_name='owner_user_id'
                                AND li.value_text=CAST(user_guitars.user_id AS TEXT)
                          ) OR NOT EXISTS (
                              SELECT 1 FROM claims c
                              WHERE c.individual_id=user_guitars.individual_id
                                AND c.author_user_id=user_guitars.user_id
                                AND c.claim_type='ownership'
                                AND c.ownership_kind='acquire'
                                AND c.ownership_source='former_owner'
                          ))
                    ) AS former_count,
                    (
                        SELECT COUNT(*)
                        FROM claims c JOIN users u ON u.id=c.author_user_id
                        WHERE c.author_user_id = ?
                          AND c.status = 'active'
                          AND (u.ban_status='normal' OR
                              (u.ban_status='silent_ban' AND u.id=?))
                    ) AS claim_count
                """,
                (
                    user_id,
                    user_id,
                    user_id,
                    viewer_user_id,
                ),
            ).fetchone()
            return {
                "owned_count": int(row["owned_count"] or 0),
                "former_count": int(row["former_count"] or 0),
                "claim_count": int(row["claim_count"] or 0),
            }

    def admin_update_user(self, user_id: int, fields: dict) -> bool:
        """Edit only supported user fields; moderation is audited and snapshots are rebuilt."""
        name = str(fields["display_name"]).strip()
        account = str(fields["account_type"]).strip().lower()
        status = str(fields["ban_status"]).strip().lower()
        if not name or account not in ("user", "shop", "builder", "repairer", "organization"):
            raise ValueError("Invalid display name or account type")
        if status not in ("normal", "silent_ban", "ban"):
            raise ValueError("Invalid BAN status")
        theme = fields.get("theme")
        if theme is not None and theme not in THEME_IDS:
            raise ValueError("Invalid theme")
        for key in ("birth_visibility", "residence_visibility", "bio_visibility", "avatar_visibility"):
            if fields[key] not in ("Public", "Members", "Followers", "Private"):
                raise ValueError("Invalid visibility: " + key)
        signature = fields["signature_individual_id"]
        with self.connect() as con:
            user = con.execute("SELECT COALESCE(theme_override,theme) AS theme, * FROM users WHERE id=? AND account_type<>'source'", (user_id,)).fetchone()
            if not user:
                return False
            theme = theme or user["theme"]
            if signature is not None and signature != user["signature_individual_id"] and not con.execute(
                "SELECT 1 FROM user_guitars WHERE user_id=? AND individual_id=? AND ownership_status='current_owner'",
                (user_id, signature)).fetchone():
                raise ValueError("Signature guitar must be currently owned")
            profile_changed = any(user[key] != fields[key] for key in
                ("display_name", "account_type", "location_country", "location_region",
                 "bio", "birth_visibility", "residence_visibility", "bio_visibility",
                 "avatar_visibility", "signature_individual_id")) or theme != user["theme"]
            con.execute("""UPDATE users SET display_name=?,account_type=?,location_country=?,
                location_region=?,bio=?,birth_visibility=?,residence_visibility=?,
                bio_visibility=?,avatar_visibility=?,signature_individual_id=?,theme_override=?,ban_status=?,updated_at=?
                WHERE id=?""", (name, account, fields["location_country"], fields["location_region"],
                fields["bio"], fields["birth_visibility"], fields["residence_visibility"],
                fields["bio_visibility"], fields["avatar_visibility"], signature, theme, status,
                utcnow() if profile_changed else user["updated_at"], user_id))
            if user["ban_status"] != status:
                con.execute("INSERT INTO user_admin_actions (user_id,previous_ban_status,ban_status,created_at) "
                            "VALUES (?,?,?,?)", (user_id,user["ban_status"],status,utcnow()))
            affected = [r[0] for r in con.execute(
                "SELECT DISTINCT individual_id FROM claims WHERE author_user_id=?", (user_id,))]
            affected.extend(r[0] for r in con.execute(
                "SELECT DISTINCT c.individual_id FROM claims c JOIN claim_listing_items li ON li.claim_id=c.id "
                "WHERE li.field_name='owner_user_id' AND li.value_text=?", (str(user_id),)))
            for individual_id in set(affected):
                self._rebuild_individual_snapshot_in_connection(con, individual_id)
        return True

    def update_user(
        self,
        user_id: int,
        *,
        display_name: str,
        account_type: str,
        location_country: str | None,
        location_region: str | None,
        bio: str | None = None,
        visibility: dict[str, str] | None = None,
        signature_individual_id: int | None = None,
        update_signature: bool = False,
        theme: str | None = None,
    ) -> bool:
        name = display_name.strip()
        account = account_type.strip().lower()

        if not name:
            raise ValueError(
                "display_name is required"
            )

        if account not in (
            "user", "shop", "builder", "repairer", "organization",
        ):
            raise ValueError(
                "account_type must be user, shop, builder, repairer, or organization"
            )

        visibility = visibility or {}
        if any(value not in ("Public", "Members", "Followers", "Private")
               for value in visibility.values()):
            raise ValueError("Invalid profile visibility")
        if theme is not None and theme not in THEME_IDS:
            raise ValueError("Invalid theme")

        with self.connect() as con:
            if update_signature and signature_individual_id is not None:
                owned = con.execute(
                    "SELECT 1 FROM user_guitars WHERE user_id = ? AND individual_id = ? "
                    "AND ownership_status = 'current_owner'",
                    (user_id, signature_individual_id),
                ).fetchone()
                if not owned:
                    raise ValueError("Signature guitar must be an owned guitar")
            cur = con.execute(
                """
                UPDATE users
                SET display_name = ?,
                    account_type = ?,
                    location_country = ?,
                    location_region = ?,
                    bio = COALESCE(?, bio),
                    birth_visibility = COALESCE(?, birth_visibility),
                    residence_visibility = COALESCE(?, residence_visibility),
                    bio_visibility = COALESCE(?, bio_visibility),
                    avatar_visibility = COALESCE(?, avatar_visibility),
                    theme_override = COALESCE(?, theme_override),
                    signature_individual_id = CASE WHEN ? THEN ? ELSE signature_individual_id END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    account,
                    (
                        location_country.strip()
                        if location_country
                        else None
                    ),
                    (
                        location_region.strip()
                        if location_region
                        else None
                    ),
                    bio.strip() if bio is not None else None,
                    visibility.get("birth"),
                    visibility.get("residence"),
                    visibility.get("bio"),
                    visibility.get("avatar"),
                    theme,
                    update_signature,
                    signature_individual_id,
                    utcnow(),
                    user_id,
                ),
            )

            updated = (
                cur.rowcount
                > 0
            )
            if updated:
                individual_ids = {
                    int(row["individual_id"])
                    for row
                    in con.execute(
                        """
                        SELECT DISTINCT c.individual_id
                        FROM claims c
                        WHERE c.status = 'active'
                          AND (
                                (
                                    c.claim_type IN (
                                        'ownership'
                                    )
                                    AND c.value_text = ?
                                )
                                OR EXISTS (
                                    SELECT 1
                                    FROM claim_listing_items li
                                    WHERE li.claim_id = c.id
                                      AND li.field_name = 'owner_user_id'
                                      AND li.value_text = ?
                                )
                              )
                        """,
                        (
                            str(user_id),
                            str(user_id),
                        ),
                    )
                }
                for individual_id in individual_ids:
                    self._rebuild_individual_snapshot_in_connection(
                        con,
                        individual_id,
                    )

            return updated

    def update_user_avatar(
        self,
        user_id: int,
        *,
        storage_path: str,
        original_filename: str | None,
        mime_type: str | None,
    ) -> bool:
        path = storage_path.strip()
        if not path:
            raise ValueError(
                "storage_path is required"
            )

        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE users
                SET avatar_storage_path = ?,
                    avatar_original_filename = ?,
                    avatar_mime_type = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    path,
                    (
                        original_filename.strip()
                        if original_filename
                        else None
                    ),
                    (
                        mime_type.strip()
                        if mime_type
                        else None
                    ),
                    utcnow(),
                    user_id,
                ),
            )

            return cur.rowcount > 0


    def link_user_guitar(
        self,
        user_id: int,
        individual_id: int,
        ownership_status: str = (
            "current_owner"
        ),
        acquired_at: str | None = None,
        released_at: str | None = None,
    ) -> bool:
        status = (
            ownership_status
            .strip()
            .lower()
        )

        if status not in (
            "current_owner",
            "former_owner",
        ):
            raise ValueError(
                "ownership_status must be "
                "current_owner or former_owner"
            )

        now = utcnow()

        with self.connect() as con:
            if not con.execute(
                "SELECT 1 FROM users WHERE id = ? AND ban_status <> 'ban'",
                (
                    user_id,
                ),
            ).fetchone():
                return False

            if not con.execute(
                "SELECT 1 FROM individuals WHERE id = ?",
                (
                    individual_id,
                ),
            ).fetchone():
                return False

            next_order = int(
                con.execute(
                    """
                    SELECT COALESCE(
                        MAX(display_order),
                        -1
                    ) + 1
                    FROM user_guitars
                    WHERE user_id = ?
                    """,
                    (
                        user_id,
                    ),
                ).fetchone()[0]
            )

            con.execute(
                """
                INSERT INTO user_guitars (
                    user_id,
                    individual_id,
                    ownership_status,
                    display_order,
                    acquired_at,
                    released_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    user_id,
                    individual_id
                )
                DO UPDATE SET
                    ownership_status
                        = excluded.ownership_status,
                    acquired_at
                        = COALESCE(
                            excluded.acquired_at,
                            user_guitars.acquired_at
                        ),
                    released_at
                        = excluded.released_at,
                    updated_at
                        = excluded.updated_at
                """,
                (
                    user_id,
                    individual_id,
                    status,
                    next_order,
                    acquired_at,
                    released_at,
                    now,
                    now,
                ),
            )

            return True

    def reorder_user_guitars(
        self,
        user_id: int,
        individual_ids: list[int],
    ) -> bool:
        with self.connect() as con:
            rows = list(
                con.execute(
                    """
                    SELECT individual_id
                    FROM user_guitars
                    WHERE user_id = ?
                      AND ownership_status
                          = 'current_owner'
                    """,
                    (
                        user_id,
                    ),
                )
            )

            existing = {
                int(
                    row[
                        "individual_id"
                    ]
                )
                for row in rows
            }

            requested = [
                int(value)
                for value
                in individual_ids
            ]

            if (
                len(requested)
                != len(set(requested))
                or set(requested)
                != existing
            ):
                return False

            for index, individual_id in enumerate(
                requested
            ):
                con.execute(
                    """
                    UPDATE user_guitars
                    SET display_order = ?,
                        updated_at = ?
                    WHERE user_id = ?
                      AND individual_id = ?
                    """,
                    (
                        index,
                        utcnow(),
                        user_id,
                        individual_id,
                    ),
                )

            return True


    def unlink_user_guitar(
        self,
        user_id: int,
        individual_id: int,
    ) -> bool:
        with self.connect() as con:
            cur = con.execute(
                """
                DELETE FROM user_guitars
                WHERE user_id = ?
                  AND individual_id = ?
                """,
                (
                    user_id,
                    individual_id,
                ),
            )

            return (
                cur.rowcount
                > 0
            )


    def create_initial_listing_claim(
        self,
        user_id: int,
        *,
        manufacturer: str,
        serial_number: str,
        media_storage_path: str,
        media_original_filename: str | None = None,
        media_mime_type: str | None = None,
        media_captured_at: str | None = None,
        model: str | None = None,
        finish: str | None = None,
        year: str | None = None,
        occurred_at: str | None = None,
        body: str | None = None,
    ) -> tuple[int, int, int, int]:
        maker = manufacturer.strip()
        serial = serial_number.strip()
        storage_path = media_storage_path.strip()
        model_value = (
            model.strip()
            if model and model.strip()
            else None
        )
        finish_value = (
            finish.strip()
            if finish and finish.strip()
            else None
        )
        year_value = (
            year.strip()
            if year and year.strip()
            else None
        )
        note = (
            body.strip()
            if body and body.strip()
            else None
        )

        normalized_maker = normalize_manufacturer(
            maker
        )
        normalized_model = normalize_model(
            model_value
        )
        normalized_serial = normalize_serial(
            serial
        )

        if (
            not normalized_maker
            or not normalized_serial
        ):
            raise ValueError(
                "manufacturer and serial_number are required"
            )

        if not storage_path:
            raise ValueError(
                "representative image is required"
            )

        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at
            and occurred_at.strip()
            else now[:10]
        )

        with self.connect() as con:
            user = con.execute(
                """
                SELECT *
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            if not user:
                raise ValueError(
                    "User not found"
                )

            existing = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE normalized_manufacturer = ?
                  AND COALESCE(
                        normalized_model,
                        ''
                      ) = COALESCE(?, '')
                  AND normalized_serial = ?
                LIMIT 1
                """,
                (
                    normalized_maker,
                    normalized_model,
                    normalized_serial,
                ),
            ).fetchone()
            if existing:
                raise ValueError(
                    "An Individual with the same maker, model, and serial already exists"
                )

            pending_token = (
                "__pending__:"
                + uuid.uuid4().hex
            )
            cur = con.execute(
                """
                INSERT INTO individuals (
                    manufacturer,
                    normalized_manufacturer,
                    normalized_serial,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "__pending__",
                    pending_token,
                    pending_token,
                    now,
                    now,
                ),
            )
            individual_id = int(
                cur.lastrowid
            )

            title = " ".join(
                value
                for value in (
                    maker,
                    model_value,
                )
                if value
            )

            source_listing_id = (
                f"user-initial-{individual_id}"
            )

            cur = con.execute(
                """
                INSERT INTO observations (
                    individual_id,
                    event_type,
                    actor_user_id,
                    occurred_at,
                    source_site,
                    source_url,
                    source_listing_id,
                    observed_at,
                    listing_date,
                    title,
                    raw_text,
                    created_at
                )
                VALUES (
                    ?, 'listing', ?, ?,
                    'user', '', ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    event_date,
                    source_listing_id,
                    now,
                    event_date,
                    title,
                    note,
                    now,
                ),
            )

            observation_id = int(
                cur.lastrowid
            )

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, 'listing',
                    'listing', ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    observation_id,
                    user_id,
                    source_listing_id,
                    note,
                    event_date,
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
            )

            listing_values = {
                "manufacturer": maker,
                "model": model_value,
                "finish": finish_value,
                "year": year_value,
                "serial_number": serial,
                "owner_name": user["display_name"],
                "owner_type": "user",
                "owner_user_id": str(user_id),
                "location_country": user["location_country"],
                "location_region": user["location_region"],
                "listing_title": title,
                "listing_date": event_date,
                "source_site": "user",
                "source_listing_id": source_listing_id,
            }
            for field_name, value in listing_values.items():
                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                con.execute(
                    """
                    INSERT INTO claim_listing_items (
                        claim_id,
                        field_name,
                        value_text,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        field_name,
                        value_text,
                        now,
                    ),
                )

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )

            next_order = int(
                con.execute(
                    """
                    SELECT COALESCE(
                        MAX(display_order),
                        -1
                    ) + 1
                    FROM user_guitars
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()[0]
            )

            con.execute(
                """
                INSERT INTO user_guitars (
                    user_id,
                    individual_id,
                    ownership_status,
                    display_order,
                    acquired_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, 'current_owner',
                    ?, ?, ?, ?
                )
                """,
                (
                    user_id,
                    individual_id,
                    next_order,
                    event_date,
                    now,
                    now,
                ),
            )

            cur = con.execute(
                """
                INSERT INTO media_assets (
                    individual_id,
                    uploader_user_id,
                    media_type,
                    storage_path,
                    original_filename,
                    mime_type,
                    captured_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, 'image', ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    storage_path,
                    (
                        media_original_filename.strip()
                        if media_original_filename
                        else None
                    ),
                    (
                        media_mime_type.strip()
                        if media_mime_type
                        else None
                    ),
                    (
                        media_captured_at.strip()
                        if media_captured_at
                        else event_date
                    ),
                    now,
                    now,
                ),
            )
            media_asset_id = int(
                cur.lastrowid
            )

            con.execute(
                """
                INSERT INTO claim_evidence (
                    claim_id,
                    media_asset_id,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    claim_id,
                    media_asset_id,
                    now,
                ),
            )

            con.execute(
                """
                UPDATE individuals
                SET representative_media_asset_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    media_asset_id,
                    now,
                    individual_id,
                ),
            )

            return (
                individual_id,
                observation_id,
                claim_id,
                media_asset_id,
            )


    def create_ownership_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        ownership_kind: str,
        occurred_at: str | None = None,
        previous_owner_text: str | None = None,
        body: str | None = None,
    ) -> tuple[int, int]:
        kind = ownership_kind.strip().lower()
        if kind not in ("acquire", "transfer", "release", "inherit"):
            raise ValueError(
                "ownership_kind must be acquire, transfer, release, or inherit"
            )

        if kind == "acquire":
            if not occurred_at or not occurred_at.strip():
                raise ValueError("Acquisition Date is required for Acquire")
            try:
                datetime.strptime(occurred_at.strip(), "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("Acquisition Date must use YYYY-MM-DD") from exc
            if len(occurred_at.strip()) != 10:
                raise ValueError("Acquisition Date must use YYYY-MM-DD")

        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at and occurred_at.strip()
            else now[:10]
        )
        note = body.strip() if body and body.strip() else None

        with self.connect() as con:
            user = con.execute(
                """
                SELECT *
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                "SELECT * FROM individuals WHERE id = ?",
                (individual_id,),
            ).fetchone()
            if not user or not individual:
                raise ValueError("User or Individual not found")

            ownership = con.execute(
                """
                SELECT *
                FROM user_guitars
                WHERE user_id = ?
                  AND individual_id = ?
                  AND ownership_status = 'current_owner'
                """,
                (user_id, individual_id),
            ).fetchone()

            ending_kinds = ("transfer", "release", "inherit")
            if kind in ending_kinds and not ownership:
                raise ValueError(
                    "User is not the current owner of this Individual"
                )

            pending_owner_verification = (
                kind == "acquire"
                and individual["current_owner_user_id"] is not None
                and int(individual["current_owner_user_id"]) != user_id
            )

            owner_name = (
                "Unknown"
                if kind in ending_kinds
                else user["display_name"]
            )
            owner_type = (
                "unknown"
                if kind in ending_kinds
                else "user"
            )
            event_title = f"Ownership / {kind.capitalize()}"
            details: list[str] = []
            if previous_owner_text:
                details.append(
                    f"Previous owner: {previous_owner_text.strip()}"
                )
            if note:
                details.append(note)
            raw_text = "\n".join(details) or None

            cur = con.execute(
                """
                INSERT INTO observations (
                    individual_id,
                    manufacturer,
                    model,
                    finish,
                    year,
                    serial_number,
                    owner_name,
                    owner_type,
                    event_type,
                    actor_user_id,
                    occurred_at,
                    source_site,
                    source_url,
                    observed_at,
                    title,
                    raw_text,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    'ownership', ?, ?,
                    'user', ?, ?, ?, ?, ?
                )
                """,
                (
                    individual_id,
                    individual["manufacturer"],
                    individual["model"],
                    individual["finish"],
                    individual["year"],
                    individual["serial_number"],
                    owner_name,
                    owner_type,
                    user_id,
                    event_date,
                    f"user://{user_id}",
                    now,
                    event_title,
                    raw_text,
                    now,
                ),
            )
            observation_id = int(cur.lastrowid)

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    ownership_kind,
                    body,
                    occurred_at,
                    status,
                    verification_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, 'ownership',
                    'owner_user_id', ?, ?, ?, ?,
                    'active', ?, ?, ?
                )
                """,
                (
                    individual_id,
                    observation_id,
                    user_id,
                    (
                        "unknown"
                        if kind in ending_kinds
                        else str(user_id)
                    ),
                    kind,
                    note,
                    event_date,
                    "unverified" if pending_owner_verification else "positive",
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)

            if kind == "acquire":
                con.execute(
                    """INSERT INTO claim_source_evidence
                       (claim_id,evidence_type,effective_date,date_basis,payload_json,created_at)
                       VALUES (?, 'acquisition_date', ?, 'user_reported', ?, ?)""",
                    (claim_id, event_date,
                     json.dumps({'reported_by_user_id': user_id}, ensure_ascii=False), now),
                )

            if kind in ending_kinds:
                con.execute(
                    """
                    UPDATE user_guitars
                    SET released_at = ?,
                        updated_at = ?
                    WHERE user_id = ?
                      AND individual_id = ?
                    """,
                    (event_date, now, user_id, individual_id),
                )
            elif not pending_owner_verification:
                next_order = int(
                    con.execute(
                        """
                        SELECT COALESCE(MAX(display_order), -1) + 1
                        FROM user_guitars
                        WHERE user_id = ?
                        """,
                        (user_id,),
                    ).fetchone()[0]
                )
                con.execute(
                    """
                    INSERT INTO user_guitars (
                        user_id,
                        individual_id,
                        ownership_status,
                        display_order,
                        acquired_at,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, 'current_owner', ?, ?, ?, ?)
                    ON CONFLICT(user_id, individual_id)
                    DO UPDATE SET
                        acquired_at = COALESCE(
                            excluded.acquired_at,
                            user_guitars.acquired_at
                        ),
                        updated_at = excluded.updated_at
                    """,
                    (
                        user_id,
                        individual_id,
                        next_order,
                        event_date,
                        now,
                        now,
                    ),
                )

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )
            return observation_id, claim_id

    @staticmethod
    def _record_accepted_acquire(con: sqlite3.Connection, claim: sqlite3.Row) -> None:
        """Add a user guitar only after its Acquire becomes accepted."""
        if (claim['claim_type'] != 'ownership' or claim['ownership_kind'] != 'acquire'
                or claim['ownership_source'] not in (None, 'user')):
            return
        date_evidence = con.execute(
            """SELECT 1 FROM claim_source_evidence
               WHERE claim_id=? AND evidence_type='acquisition_date' AND effective_date=?""",
            (claim['id'], claim['occurred_at']),
        ).fetchone()
        if date_evidence is None:
            return
        user_id = claim['value_text']
        if not user_id or not con.execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
            return
        now = utcnow()
        next_order = int(con.execute(
            'SELECT COALESCE(MAX(display_order), -1) + 1 FROM user_guitars WHERE user_id=?',
            (user_id,),
        ).fetchone()[0])
        con.execute(
            """INSERT INTO user_guitars
               (user_id,individual_id,ownership_status,display_order,acquired_at,created_at,updated_at)
               VALUES (?,?,'current_owner',?,?,?,?)
               ON CONFLICT(user_id,individual_id) DO UPDATE SET
                 acquired_at=COALESCE(user_guitars.acquired_at,excluded.acquired_at),
                 updated_at=excluded.updated_at""",
            (user_id, claim['individual_id'], next_order, claim['occurred_at'], now, now),
        )

    def create_former_owner_claims(
        self,
        user_id: int,
        individual_id: int,
        *,
        acquisition_date: str,
        release_date: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        acquired = acquisition_date.strip()
        released = release_date.strip()
        try:
            datetime.strptime(acquired, "%Y-%m-%d")
            datetime.strptime(released, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                "Acquisition Date and Release Date must use YYYY-MM-DD"
            ) from exc

        if acquired >= released:
            raise ValueError(
                "Acquisition Date must be earlier than Release Date"
            )

        note = (
            detail.strip()
            if detail and detail.strip()
            else None
        )
        now = utcnow()
        ownership_pair_id = str(uuid.uuid4())

        with self.connect() as con:
            user = con.execute(
                """
                SELECT *
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                """
                SELECT *
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            if not user or not individual:
                raise ValueError("User or Individual not found")

            if (
                individual["current_owner_user_id"] is not None
                and str(individual["current_owner_user_id"]) == str(user_id)
            ):
                raise ValueError(
                    "Current owner cannot use Former Owner Claim"
                )

            current_owner_user_id = (
                str(individual["current_owner_user_id"]).strip()
                if individual["current_owner_user_id"] is not None
                else ""
            )
            current_owner_name = (
                str(individual["current_owner_name"]).strip()
                if individual["current_owner_name"] is not None
                else ""
            )

            current_owner_start = None
            if current_owner_user_id:
                current_owner_start = con.execute(
                    """
                    SELECT effective_at
                    FROM (
                        SELECT
                            c.id,
                            COALESCE(
                                c.occurred_at,
                                c.created_at
                            ) AS effective_at,
                            c.created_at
                        FROM claims c
                        WHERE c.individual_id = ?
                          AND c.status = 'active'
                          AND c.claim_type = 'ownership'
                          AND COALESCE(
                                c.ownership_kind,
                                'acquire'
                              ) NOT IN (
                                'transfer',
                                'release',
                                'inherit'
                              )
                          AND TRIM(COALESCE(c.value_text, '')) = ?

                        UNION ALL

                        SELECT
                            c.id,
                            COALESCE(
                                c.occurred_at,
                                c.created_at
                            ) AS effective_at,
                            c.created_at
                        FROM claims c
                        INNER JOIN claim_listing_items li
                          ON li.claim_id = c.id
                         AND li.field_name = 'owner_user_id'
                        WHERE c.individual_id = ?
                          AND c.status = 'active'
                          AND c.claim_type = 'listing'
                          AND TRIM(COALESCE(li.value_text, '')) = ?
                    )
                    ORDER BY effective_at DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (
                        individual_id,
                        current_owner_user_id,
                        individual_id,
                        current_owner_user_id,
                    ),
                ).fetchone()
            elif current_owner_name and current_owner_name.lower() != "unknown":
                current_owner_start = con.execute(
                    """
                    SELECT
                        COALESCE(
                            c.occurred_at,
                            c.created_at
                        ) AS effective_at
                    FROM claims c
                    INNER JOIN claim_listing_items li
                      ON li.claim_id = c.id
                     AND li.field_name = 'owner_name'
                    WHERE c.individual_id = ?
                      AND c.status = 'active'
                      AND c.claim_type = 'listing'
                      AND LOWER(TRIM(COALESCE(li.value_text, '')))
                          = LOWER(?)
                    ORDER BY
                        COALESCE(
                            c.occurred_at,
                            c.created_at
                        ) DESC,
                        c.created_at DESC,
                        c.id DESC
                    LIMIT 1
                    """,
                    (
                        individual_id,
                        current_owner_name,
                    ),
                ).fetchone()

            if (
                (
                    current_owner_user_id
                    or (
                        current_owner_name
                        and current_owner_name.lower() != "unknown"
                    )
                )
                and not current_owner_start
            ):
                raise ValueError(
                    "Current owner acquisition date could not be determined"
                )

            if current_owner_start:
                current_owner_date = str(
                    current_owner_start["effective_at"]
                )[:10]
                if released >= current_owner_date:
                    raise ValueError(
                        "Release Date must be earlier than the current owner's acquisition date "
                        f"({current_owner_date})"
                    )

            observation_ids: list[int] = []
            claim_ids: list[int] = []

            def insert_ownership_event(
                kind: str,
                event_date: str,
                body: str | None,
            ) -> tuple[int, int]:
                ending = kind == "release"
                owner_name = (
                    "Unknown"
                    if ending
                    else str(user["display_name"])
                )
                owner_type = (
                    "unknown"
                    if ending
                    else "user"
                )
                raw_text = body if body else None

                cur = con.execute(
                    """
                    INSERT INTO observations (
                        individual_id,
                        manufacturer,
                        model,
                        finish,
                        year,
                        serial_number,
                        owner_name,
                        owner_type,
                        event_type,
                        actor_user_id,
                        occurred_at,
                        source_site,
                        source_url,
                        observed_at,
                        title,
                        raw_text,
                        created_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        'ownership', ?, ?,
                        'user', ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        individual_id,
                        individual["manufacturer"],
                        individual["model"],
                        individual["finish"],
                        individual["year"],
                        individual["serial_number"],
                        owner_name,
                        owner_type,
                        user_id,
                        event_date,
                        f"user://{user_id}",
                        now,
                        f"Ownership / {kind.capitalize()}",
                        raw_text,
                        now,
                    ),
                )
                observation_id = int(cur.lastrowid)

                cur = con.execute(
                    """
                    INSERT INTO claims (
                        individual_id,
                        observation_id,
                        author_user_id,
                        claim_type,
                        field_name,
                        value_text,
                        ownership_kind,
                        ownership_source,
                        ownership_pair_id,
                        body,
                        occurred_at,
                        status,
                        verification_status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, ?, ?, 'ownership',
                        'owner_user_id', ?, ?,
                        'former_owner', ?, ?, ?,
                        'active', 'unverified', ?, ?
                    )
                    """,
                    (
                        individual_id,
                        observation_id,
                        user_id,
                        "unknown" if ending else str(user_id),
                        kind,
                        ownership_pair_id,
                        body,
                        event_date,
                        now,
                        now,
                    ),
                )
                new_claim_id = int(cur.lastrowid)
                if kind == "acquire":
                    con.execute(
                        """INSERT INTO claim_source_evidence
                           (claim_id,evidence_type,effective_date,date_basis,payload_json,created_at)
                           VALUES (?, 'acquisition_date', ?, 'user_reported', ?, ?)""",
                        (new_claim_id, event_date,
                         json.dumps({'reported_by_user_id': user_id}, ensure_ascii=False), now),
                    )
                return observation_id, new_claim_id

            acquire_observation_id, acquire_claim_id = (
                insert_ownership_event(
                    "acquire",
                    acquired,
                    note,
                )
            )
            release_observation_id, release_claim_id = (
                insert_ownership_event(
                    "release",
                    released,
                    None,
                )
            )
            observation_ids.extend(
                [
                    acquire_observation_id,
                    release_observation_id,
                ]
            )
            claim_ids.extend(
                [
                    acquire_claim_id,
                    release_claim_id,
                ]
            )

            snapshot = self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )

            return {
                "observation_ids": observation_ids,
                "claim_ids": claim_ids,
                "snapshot": snapshot,
            }

    def create_incident_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        incident_kind: str,
        occurred_at: str | None = None,
        detail: str | None = None,
    ) -> int:
        kind = incident_kind.strip().lower()
        if kind not in ("damage", "lost", "theft"):
            raise ValueError(
                "incident_kind must be damage, lost, or theft"
            )

        note = (
            detail.strip()
            if detail and detail.strip()
            else None
        )
        if not note:
            raise ValueError("detail is required")

        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at and occurred_at.strip()
            else now[:10]
        )

        with self.connect() as con:
            user = con.execute(
                """
                SELECT id
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            if not user or not individual:
                raise ValueError("User or Individual not found")

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    verification_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'incident',
                    'incident_kind', ?, ?, ?,
                    'active', ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
                    self._claim_verification_status(
                        con,
                        user_id,
                        individual_id,
                    ),
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )
            return claim_id


    @staticmethod
    def _claim_verification_status(
        con: sqlite3.Connection,
        user_id: int,
        individual_id: int,
    ) -> str:
        owner = con.execute(
            """
            SELECT 1
            FROM user_guitars
            WHERE user_id = ?
              AND individual_id = ?
              AND ownership_status = 'current_owner'
            LIMIT 1
            """,
            (user_id, individual_id),
        ).fetchone()
        return "positive" if owner else "unverified"

    def create_media_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        storage_path: str,
        original_filename: str | None = None,
        mime_type: str | None = None,
        occurred_at: str | None = None,
        caption: str | None = None,
    ) -> tuple[int, int]:
        claim_id, media_asset_ids = self.create_media_claim_group(
            user_id,
            individual_id,
            media_items=[
                {
                    "storage_path": storage_path,
                    "original_filename": original_filename,
                    "mime_type": mime_type,
                }
            ],
            occurred_at=occurred_at,
            caption=caption,
        )
        return claim_id, media_asset_ids[0]

    def create_media_claim_group(
        self,
        user_id: int,
        individual_id: int,
        *,
        media_items: list[dict[str, str | None]],
        occurred_at: str | None = None,
        caption: str | None = None,
    ) -> tuple[int, list[int]]:
        if not media_items:
            raise ValueError("At least one image is required")
        if len(media_items) > 10:
            raise ValueError("A Media Claim can contain up to 10 images")

        normalized_items: list[
            tuple[str, str | None, str | None]
        ] = []
        for item in media_items:
            storage_path = str(
                item.get("storage_path") or ""
            ).strip()
            if not storage_path:
                raise ValueError("storage_path is required")
            original_filename = (
                str(item.get("original_filename")).strip()
                if item.get("original_filename")
                else None
            )
            mime_type = (
                str(item.get("mime_type")).strip()
                if item.get("mime_type")
                else None
            )
            normalized_items.append(
                (
                    storage_path,
                    original_filename,
                    mime_type,
                )
            )

        note = (
            caption.strip()
            if caption and caption.strip()
            else None
        )
        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at and occurred_at.strip()
            else now[:10]
        )

        with self.connect() as con:
            user = con.execute(
                """
                SELECT id
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            if not user or not individual:
                raise ValueError("User or Individual not found")

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    verification_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'media',
                    'media_type', 'image', ?, ?,
                    'active', ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    note,
                    event_date,
                    self._claim_verification_status(
                        con,
                        user_id,
                        individual_id,
                    ),
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)
            media_asset_ids: list[int] = []

            for (
                storage_path,
                original_filename,
                mime_type,
            ) in normalized_items:
                cur = con.execute(
                    """
                    INSERT INTO media_assets (
                        individual_id,
                        uploader_user_id,
                        media_type,
                        storage_path,
                        original_filename,
                        mime_type,
                        captured_at,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, ?, 'image', ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        individual_id,
                        user_id,
                        storage_path,
                        original_filename,
                        mime_type,
                        event_date,
                        now,
                        now,
                    ),
                )
                media_asset_id = int(cur.lastrowid)
                media_asset_ids.append(media_asset_id)

                con.execute(
                    """
                    INSERT INTO claim_evidence (
                        claim_id,
                        media_asset_id,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        claim_id,
                        media_asset_id,
                        now,
                    ),
                )

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )
            return claim_id, media_asset_ids


    def create_event_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        event_kind: str,
        occurred_at: str | None = None,
        detail: str | None = None,
    ) -> int:
        kind = event_kind.strip().lower()
        if kind not in (
            "exhibition",
            "performance",
            "recording",
            "auction",
            "other",
        ):
            raise ValueError(
                "event_kind must be exhibition, performance, recording, auction, or other"
            )

        note = (
            detail.strip()
            if detail and detail.strip()
            else None
        )
        if not note:
            raise ValueError("detail is required")

        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at and occurred_at.strip()
            else now[:10]
        )

        with self.connect() as con:
            user = con.execute(
                """
                SELECT id
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            if not user or not individual:
                raise ValueError("User or Individual not found")

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    occurred_at,
                    status,
                    verification_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'event',
                    'event_kind', ?, ?, ?,
                    'active', ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
                    self._claim_verification_status(
                        con,
                        user_id,
                        individual_id,
                    ),
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )
            return claim_id


    def create_specification_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        field_name: str,
        value_text: str,
        occurred_at: str | None = None,
        body: str | None = None,
    ) -> int:
        return self.create_specification_claim_group(
            user_id,
            individual_id,
            specification_kind="specification",
            items=[
                {
                    "field_name": field_name,
                    "value_text": value_text,
                }
            ],
            occurred_at=occurred_at,
            body=body,
        )

    def create_specification_claim_group(
        self,
        user_id: int,
        individual_id: int,
        *,
        specification_kind: str,
        items: list[dict[str, str]],
        occurred_at: str | None = None,
        body: str | None = None,
    ) -> int:
        kind = specification_kind.strip().lower()
        if kind not in (
            "specification",
            "repair",
        ):
            raise ValueError(
                "specification_kind must be specification or repair"
            )

        normalized_items: list[
            tuple[str, str]
        ] = []
        seen_fields: set[str] = set()

        for item in items:
            field = str(
                item.get(
                    "field_name",
                    "",
                )
            ).strip().lower()
            value = str(
                item.get(
                    "value_text",
                    "",
                )
            ).strip()

            if not field:
                raise ValueError(
                    "field_name is required"
                )
            if not value:
                raise ValueError(
                    "value_text is required"
                )
            if field in seen_fields:
                raise ValueError(
                    "Each specification item can appear only once per Claim"
                )

            seen_fields.add(
                field
            )
            normalized_items.append(
                (
                    field,
                    value,
                )
            )

        if not normalized_items:
            raise ValueError(
                "At least one specification item is required"
            )

        note = (
            body.strip()
            if body and body.strip()
            else None
        )

        now = utcnow()
        event_date = (
            occurred_at.strip()
            if occurred_at
            and occurred_at.strip()
            else now[:10]
        )

        with self.connect() as con:
            user = con.execute(
                """
                SELECT id
                FROM users
                WHERE id = ?
                  AND account_type <> 'source'
                  AND ban_status <> 'ban'
                """,
                (user_id,),
            ).fetchone()
            individual = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()

            if not user or not individual:
                raise ValueError(
                    "User or Individual not found"
                )

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    specification_kind,
                    body,
                    occurred_at,
                    status,
                    verification_status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'specification',
                    NULL, NULL, ?, ?, ?,
                    'active', ?, ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
                    self._claim_verification_status(
                        con,
                        user_id,
                        individual_id,
                    ),
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
            )

            con.executemany(
                """
                INSERT INTO claim_spec_items (
                    claim_id,
                    field_name,
                    value_text,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        claim_id,
                        field,
                        value,
                        now,
                    )
                    for field, value
                    in normalized_items
                ],
            )

            self._rebuild_individual_snapshot_in_connection(
                con,
                individual_id,
            )

            return claim_id

    def update_specification_claim_group(
        self,
        claim_id: int,
        user_id: int,
        *,
        specification_kind: str,
        items: list[dict[str, str]],
        occurred_at: str | None = None,
        body: str | None = None,
    ) -> bool:
        kind = specification_kind.strip().lower()
        if kind not in (
            "specification",
            "repair",
        ):
            raise ValueError(
                "specification_kind must be specification or repair"
            )

        normalized_items: list[
            tuple[str, str]
        ] = []
        seen_fields: set[str] = set()

        for item in items:
            field = str(
                item.get(
                    "field_name",
                    "",
                )
            ).strip().lower()
            value = str(
                item.get(
                    "value_text",
                    "",
                )
            ).strip()

            if not field:
                raise ValueError(
                    "field_name is required"
                )
            if not value:
                raise ValueError(
                    "value_text is required"
                )
            if field in seen_fields:
                raise ValueError(
                    "Each specification item can appear only once per Claim"
                )

            seen_fields.add(field)
            normalized_items.append(
                (field, value)
            )

        if not normalized_items:
            raise ValueError(
                "At least one specification item is required"
            )

        note = (
            body.strip()
            if body and body.strip()
            else None
        )
        event_date = (
            occurred_at.strip()
            if occurred_at
            and occurred_at.strip()
            else None
        )
        now = utcnow()

        with self.connect() as con:
            claim = con.execute(
                """
                SELECT *
                FROM claims
                WHERE id = ?
                  AND claim_type = 'specification'
                  AND status = 'active'
                """,
                (claim_id,),
            ).fetchone()

            if not claim:
                return False

            if int(
                claim["author_user_id"]
            ) != int(user_id):
                raise ValueError(
                    "Only the Claim author can edit this Claim"
                )

            con.execute(
                """
                UPDATE claims
                SET field_name = NULL,
                    value_text = NULL,
                    specification_kind = ?,
                    body = ?,
                    occurred_at = COALESCE(
                        ?,
                        occurred_at
                    ),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    kind,
                    note,
                    event_date,
                    now,
                    claim_id,
                ),
            )

            con.execute(
                """
                DELETE FROM claim_spec_items
                WHERE claim_id = ?
                """,
                (claim_id,),
            )

            con.executemany(
                """
                INSERT INTO claim_spec_items (
                    claim_id,
                    field_name,
                    value_text,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        claim_id,
                        field,
                        value,
                        now,
                    )
                    for field, value
                    in normalized_items
                ],
            )

            self._rebuild_individual_snapshot_in_connection(
                con,
                int(claim["individual_id"]),
            )

            return True


    def update_claim(
        self,
        claim_id: int,
        user_id: int,
        *,
        occurred_at: str | None = None,
        body: str | None = None,
    ) -> bool:
        note = (
            body.strip()
            if body and body.strip()
            else None
        )
        event_date = (
            occurred_at.strip()
            if occurred_at
            and occurred_at.strip()
            else None
        )
        now = utcnow()

        with self.connect() as con:
            claim = con.execute(
                """
                SELECT *
                FROM claims
                WHERE id = ?
                  AND status = 'active'
                """,
                (claim_id,),
            ).fetchone()

            if not claim:
                return False

            if int(claim["author_user_id"]) != int(user_id):
                raise ValueError(
                    "Only the Claim author can edit this Claim"
                )

            if claim["claim_type"] == "specification":
                raise ValueError(
                    "Specification Claims use the dedicated editor"
                )
            if claim["claim_type"] == "listing":
                raise ValueError(
                    "Listing Claims cannot be edited directly"
                )
            if claim["claim_type"] == "identity_correction":
                raise ValueError(
                    "Identity Correction Claims cannot be edited directly"
                )

            if claim["claim_type"] == "ownership" and (claim["ownership_kind"] or "acquire") == "acquire":
                if not event_date:
                    raise ValueError("Acquisition Date is required for Acquire")
                try:
                    datetime.strptime(event_date, "%Y-%m-%d")
                except ValueError as exc:
                    raise ValueError("Acquisition Date must use YYYY-MM-DD") from exc
                if len(event_date) != 10:
                    raise ValueError("Acquisition Date must use YYYY-MM-DD")
                updated = con.execute(
                    """UPDATE claim_source_evidence SET effective_date=?
                       WHERE claim_id=? AND evidence_type='acquisition_date'""",
                    (event_date, claim_id),
                )
                if not updated.rowcount:
                    con.execute(
                        """INSERT INTO claim_source_evidence
                           (claim_id,evidence_type,effective_date,date_basis,payload_json,created_at)
                           VALUES (?, 'acquisition_date', ?, 'user_reported', ?, ?)""",
                        (claim_id, event_date,
                         json.dumps({'reported_by_user_id': user_id}, ensure_ascii=False), now),
                    )

            con.execute(
                """
                UPDATE claims
                SET body = ?,
                    occurred_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    note,
                    event_date,
                    now,
                    claim_id,
                ),
            )

            observation_id = claim["observation_id"]
            if observation_id is not None:
                if claim["claim_type"] == "listing":
                    con.execute(
                        """
                        UPDATE observations
                        SET raw_text = ?,
                            occurred_at = ?,
                            listing_date = ?
                        WHERE id = ?
                        """,
                        (
                            note,
                            event_date,
                            event_date,
                            observation_id,
                        ),
                    )
                else:
                    con.execute(
                        """
                        UPDATE observations
                        SET occurred_at = ?
                        WHERE id = ?
                        """,
                        (
                            event_date,
                            observation_id,
                        ),
                    )

            if claim["claim_type"] == "ownership":
                ownership_kind = str(claim["ownership_kind"] or "acquire").strip().lower()
                if ownership_kind == "release":
                    con.execute(
                        """
                        UPDATE user_guitars
                        SET released_at = ?,
                            updated_at = ?
                        WHERE user_id = ?
                          AND individual_id = ?
                          AND ownership_status = 'former_owner'
                        """,
                        (
                            event_date,
                            now,
                            user_id,
                            claim["individual_id"],
                        ),
                    )
                else:
                    con.execute(
                        """
                        UPDATE user_guitars
                        SET acquired_at = ?,
                            updated_at = ?
                        WHERE user_id = ?
                          AND individual_id = ?
                        """,
                        (
                            event_date,
                            now,
                            user_id,
                            claim["individual_id"],
                        ),
                    )

            self._rebuild_individual_snapshot_in_connection(
                con,
                int(claim["individual_id"]),
            )

            return True


    def create_identity_correction(
        self,
        user_id: int,
        listing_claim_id: int,
        *,
        manufacturer: str,
        model: str | None,
        year: str | None,
        serial_number: str,
        reason: str | None = None,
    ) -> int:
        maker = manufacturer.strip()
        model_value = (
            model.strip()
            if model and model.strip()
            else None
        )
        year_value = (
            year.strip()
            if year and year.strip()
            else None
        )
        serial = serial_number.strip()
        note = (
            reason.strip()
            if reason and reason.strip()
            else None
        )

        normalized_maker = normalize_manufacturer(
            maker
        )
        normalized_model = normalize_model(
            model_value
        )
        normalized_serial = normalize_serial(
            serial
        )

        if (
            not normalized_maker
            or not normalized_serial
        ):
            raise ValueError(
                "Maker and Serial are required"
            )

        now = utcnow()

        with self.connect() as con:
            listing_claim = con.execute(
                """
                SELECT *
                FROM claims
                WHERE id = ?
                  AND claim_type = 'listing'
                  AND status = 'active'
                """,
                (listing_claim_id,),
            ).fetchone()

            if not listing_claim:
                raise ValueError(
                    "Listing Claim not found"
                )

            if int(
                listing_claim["author_user_id"]
            ) != int(user_id):
                raise ValueError(
                    "Only the Listing Claim author can create its Identity Correction"
                )

            individual = con.execute(
                """
                SELECT *
                FROM individuals
                WHERE id = ?
                """,
                (
                    listing_claim[
                        "individual_id"
                    ],
                ),
            ).fetchone()
            if not individual:
                raise ValueError(
                    "Individual not found"
                )

            duplicate = con.execute(
                """
                SELECT id
                FROM individuals
                WHERE id <> ?
                  AND normalized_manufacturer = ?
                  AND COALESCE(
                        normalized_model,
                        ''
                      ) = COALESCE(?, '')
                  AND normalized_serial = ?
                ORDER BY id
                LIMIT 1
                """,
                (
                    individual["id"],
                    normalized_maker,
                    normalized_model,
                    normalized_serial,
                ),
            ).fetchone()
            if duplicate:
                raise ValueError(
                    "Identity Correction would duplicate "
                    f"Individual #{duplicate['id']}. "
                    "Consider merging the Individuals instead."
                )

            values = {
                "manufacturer": maker,
                "model": model_value,
                "year": year_value,
                "serial_number": serial,
            }
            changes: list[
                tuple[str, str | None, str | None]
            ] = []
            for field, new_value in values.items():
                old_value = individual[field]
                if (
                    (old_value or None)
                    != (new_value or None)
                ):
                    changes.append(
                        (
                            field,
                            old_value,
                            new_value,
                        )
                    )

            if not changes:
                raise ValueError(
                    "No identity fields were changed"
                )

            correction_date = (
                listing_claim["occurred_at"]
                or listing_claim["created_at"]
            )

            cur = con.execute(
                """
                INSERT INTO claims (
                    individual_id,
                    observation_id,
                    author_user_id,
                    claim_type,
                    field_name,
                    value_text,
                    body,
                    target_claim_id,
                    occurred_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'identity_correction',
                    NULL, NULL, ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual["id"],
                    user_id,
                    note,
                    listing_claim_id,
                    correction_date,
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
            )

            con.executemany(
                """
                INSERT INTO claim_identity_items (
                    claim_id,
                    field_name,
                    old_value,
                    new_value,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        claim_id,
                        field,
                        old_value,
                        new_value,
                        now,
                    )
                    for (
                        field,
                        old_value,
                        new_value,
                    ) in changes
                ],
            )

            self._rebuild_individual_snapshot_in_connection(
                con,
                int(individual["id"]),
            )

            return claim_id

    def list_identity_correction_items(
        self,
        individual_id: int,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        ii.*,
                        c.individual_id,
                        c.target_claim_id
                    FROM claim_identity_items ii
                    INNER JOIN claims c
                      ON c.id = ii.claim_id
                    WHERE c.individual_id = ?
                      AND c.claim_type = 'identity_correction'
                      AND c.status = 'active'
                    ORDER BY
                        ii.claim_id,
                        ii.id
                    """,
                    (individual_id,),
                )
            )


    def list_specification_items(
        self,
        individual_id: int,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        si.*,
                        c.individual_id
                    FROM claim_spec_items si
                    INNER JOIN claims c
                      ON c.id = si.claim_id
                    WHERE c.individual_id = ?
                      AND c.claim_type = 'specification'
                      AND c.status = 'active'
                    ORDER BY
                        si.claim_id,
                        si.id
                    """,
                    (individual_id,),
                )
            )

    def list_current_specifications(
        self,
        individual_id: int,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    WITH candidates AS (
                        SELECT
                            c.id AS claim_id,
                            c.field_name,
                            c.value_text,
                            COALESCE(
                                c.specification_kind,
                                'specification'
                            ) AS specification_kind,
                            c.occurred_at,
                            c.created_at,
                            c.author_user_id,
                            u.display_name
                                AS author_name
                        FROM claims c
                        INNER JOIN users u
                          ON u.id = c.author_user_id AND u.ban_status='normal'
                        WHERE c.individual_id = ?
                          AND c.claim_type = 'specification'
                          AND c.status = 'active'
                          AND COALESCE(c.verification_status, 'positive') = 'positive'
                          AND c.field_name IS NOT NULL
                          AND TRIM(c.field_name) <> ''

                        UNION ALL

                        SELECT
                            c.id AS claim_id,
                            si.field_name,
                            si.value_text,
                            COALESCE(
                                c.specification_kind,
                                'specification'
                            ) AS specification_kind,
                            c.occurred_at,
                            c.created_at,
                            c.author_user_id,
                            u.display_name
                                AS author_name
                        FROM claim_spec_items si
                        INNER JOIN claims c
                          ON c.id = si.claim_id
                        INNER JOIN users u
                          ON u.id = c.author_user_id AND u.ban_status='normal'
                        WHERE c.individual_id = ?
                          AND c.claim_type = 'specification'
                          AND c.status = 'active'
                          AND COALESCE(c.verification_status, 'positive') = 'positive'
                    ),
                    ranked AS (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY field_name
                                ORDER BY
                                    SUBSTR(COALESCE(occurred_at, created_at), 1, 10) DESC,
                                    claim_id DESC
                            ) AS row_number
                        FROM candidates
                    )
                    SELECT
                        claim_id AS id,
                        *
                    FROM ranked
                    WHERE row_number = 1
                    ORDER BY
                        field_name COLLATE NOCASE
                    """,
                    (
                        individual_id,
                        individual_id,
                    ),
                )
            )

    def list_claims(
        self,
        individual_id: int,
        viewer_user_id: int | None = None,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        c.*,
                        CASE WHEN u.ban_status='normal' OR
                            (u.ban_status='silent_ban' AND u.id=?)
                            THEN c.status ELSE 'inactive' END AS effective_status,
                        u.display_name
                            AS author_name,
                        COALESCE((
                            SELECT COALESCE(
                                json_extract(e.payload_json, '$.provenance.raw_text'),
                                json_extract(e.payload_json, '$.source.raw_text'))
                            FROM claim_source_evidence e
                            WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing'
                            ORDER BY e.id LIMIT 1
                        ), (
                            SELECT o.raw_text
                            FROM observations o
                            WHERE o.id = c.observation_id
                            LIMIT 1
                        )) AS observation_raw_text,
                        COALESCE((
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_site'
                            LIMIT 1
                        ), (SELECT e.source_site FROM claim_source_evidence e
                            WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing'
                            ORDER BY e.id LIMIT 1), (SELECT o.source_site FROM observations o
                            WHERE o.id = c.observation_id)) AS source_site,
                        COALESCE((
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_url'
                            LIMIT 1
                        ), (SELECT e.source_url FROM claim_source_evidence e
                            WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing'
                            ORDER BY e.id LIMIT 1), (SELECT o.source_url FROM observations o
                            WHERE o.id = c.observation_id)) AS source_url,
                        COALESCE((
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'image_url'
                            LIMIT 1
                        ), (SELECT json_extract(e.payload_json, '$.provenance.image_url')
                            FROM claim_source_evidence e
                            WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing'
                            ORDER BY e.id LIMIT 1)) AS image_url,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'listing_title'
                            LIMIT 1
                        ) AS listing_title,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'seller'
                            LIMIT 1
                        ) AS seller,
                        COALESCE(
                            (
                                SELECT ou.display_name
                                FROM claim_listing_items li
                                INNER JOIN users ou
                                  ON CAST(ou.id AS TEXT) = li.value_text
                                WHERE li.claim_id = c.id
                                  AND li.field_name = 'owner_user_id'
                                LIMIT 1
                            ),
                            (
                                SELECT li.value_text
                                FROM claim_listing_items li
                                WHERE li.claim_id = c.id
                                  AND li.field_name = 'owner_name'
                                LIMIT 1
                            )
                        ) AS observed_owner_name,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'owner_type'
                            LIMIT 1
                        ) AS observed_owner_type,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'location_country'
                            LIMIT 1
                        ) AS location_country,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'location_region'
                            LIMIT 1
                        ) AS location_region,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'manufacturer'
                            LIMIT 1
                        ) AS observed_manufacturer,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'model'
                            LIMIT 1
                        ) AS observed_model,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'finish'
                            LIMIT 1
                        ) AS observed_finish,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'year'
                            LIMIT 1
                        ) AS observed_year,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'serial_number'
                            LIMIT 1
                        ) AS observed_serial_number,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'listing_date'
                            LIMIT 1
                        ) AS listing_date,
                        COALESCE((
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_listing_id'
                            LIMIT 1
                        ), (SELECT e.source_listing_id FROM claim_source_evidence e
                            WHERE e.claim_id=c.id AND e.evidence_type='marketplace_listing'
                            ORDER BY e.id LIMIT 1)) AS source_listing_id,
                        (
                            SELECT ce.media_asset_id
                            FROM claim_evidence ce
                            INNER JOIN media_assets ma
                              ON ma.id = ce.media_asset_id
                            WHERE ce.claim_id = c.id
                              AND ma.media_type = 'image'
                            ORDER BY ce.id
                            LIMIT 1
                        ) AS evidence_media_id,
                        COALESCE(v.good_count, 0)
                            AS good_count,
                        COALESCE(v.bad_count, 0)
                            AS bad_count,
                        (
                            SELECT cv.vote
                            FROM claim_votes cv
                            WHERE cv.claim_id = c.id
                              AND cv.user_id = ?
                            LIMIT 1
                        ) AS viewer_vote,
                        (
                            SELECT cr.stance
                            FROM claim_responses cr
                            WHERE cr.claim_id = c.id
                              AND cr.responder_user_id = ?
                            LIMIT 1
                        ) AS viewer_stance
                    FROM claims c
                    INNER JOIN users u
                      ON u.id = c.author_user_id
                    LEFT JOIN (
                        SELECT
                            claim_id,
                            SUM(
                                CASE
                                    WHEN vote = 'good'
                                    THEN 1
                                    ELSE 0
                                END
                            ) AS good_count,
                            SUM(
                                CASE
                                    WHEN vote = 'bad'
                                    THEN 1
                                    ELSE 0
                                END
                            ) AS bad_count
                        FROM claim_votes cv
                        JOIN users voter ON voter.id=cv.user_id AND voter.ban_status<>'ban'
                        GROUP BY claim_id
                    ) v
                      ON v.claim_id = c.id
                    WHERE c.individual_id = ?
                    ORDER BY
                        COALESCE(
                            c.occurred_at,
                            c.created_at
                        ),
                        c.id
                    """,
                    (
                        viewer_user_id,
                        viewer_user_id,
                        viewer_user_id,
                        individual_id,
                    ),
                )
            )

    def list_media_assets(
        self,
        individual_id: int,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT DISTINCT
                        ma.*,
                        c.claim_type AS claim_type,
                        c.body AS claim_caption,
                        c.occurred_at AS claim_occurred_at
                    FROM media_assets ma
                    INNER JOIN claim_evidence ce
                      ON ce.media_asset_id = ma.id
                    INNER JOIN claims c
                      ON c.id = ce.claim_id
                     AND c.status = 'active'
                     AND EXISTS (SELECT 1 FROM users u WHERE u.id=c.author_user_id AND u.ban_status='normal')
                     AND COALESCE(c.verification_status, 'positive') = 'positive'
                    WHERE ma.individual_id = ?
                      AND ma.media_type = 'image'
                    ORDER BY
                        COALESCE(ma.captured_at, ma.created_at),
                        ma.id
                    """,
                    (individual_id,),
                )
            )

    def list_claim_media_assets(
        self,
        individual_id: int,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        ce.claim_id,
                        ma.*
                    FROM claim_evidence ce
                    INNER JOIN claims c
                      ON c.id = ce.claim_id
                    INNER JOIN media_assets ma
                      ON ma.id = ce.media_asset_id
                    WHERE c.individual_id = ?
                      AND c.status = 'active'
                      AND EXISTS (SELECT 1 FROM users u WHERE u.id=c.author_user_id AND u.ban_status='normal')
                      AND ma.media_type = 'image'
                    ORDER BY
                        ce.claim_id,
                        ce.id
                    """,
                    (individual_id,),
                )
            )

    def get_media_asset(
        self,
        media_asset_id: int,
        viewer_user_id: int | None = None,
    ) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """
                SELECT ma.*
                FROM media_assets ma JOIN users uploader ON uploader.id=ma.uploader_user_id
                WHERE ma.id = ? AND (
                  EXISTS (SELECT 1 FROM claim_evidence ce JOIN claims c ON c.id=ce.claim_id
                          JOIN users author ON author.id=c.author_user_id
                          WHERE ce.media_asset_id=ma.id AND c.status='active'
                            AND c.verification_status='positive'
                            AND (author.ban_status='normal' OR
                                (author.ban_status='silent_ban' AND author.id=?)))
                  OR (uploader.ban_status='normal' AND NOT EXISTS
                      (SELECT 1 FROM claim_evidence ce WHERE ce.media_asset_id=ma.id))
                )
                """,
                (media_asset_id, viewer_user_id),
            ).fetchone()


    def admin_moderate_claim(self, claim_id: int, action: str, *,
                             confirm_individual_delete: bool = False) -> dict | None:
        if action not in ("positive", "negative", "unverified", "delete"):
            raise ValueError("Invalid admin action")
        with self.connect() as con:
            claim = con.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if not claim:
                return None
            individual_id = int(claim["individual_id"])
            targets = [claim]
            if claim["ownership_pair_id"]:
                targets = con.execute(
                    "SELECT * FROM claims WHERE individual_id=? AND ownership_pair_id=?",
                    (individual_id, claim["ownership_pair_id"]),
                ).fetchall()
            delete_individual = False
            if action == "delete" and claim["claim_type"] == "listing" and claim["status"] == "active":
                other = con.execute("SELECT 1 FROM claims WHERE individual_id=? AND claim_type='listing' "
                                    "AND status='active' AND id<>?", (individual_id, claim_id)).fetchone()
                delete_individual = not other
                if delete_individual and not confirm_individual_delete:
                    raise ValueError("Deleting the last Listing also deletes the Individual and its related records. Confirmation required.")
            for target in targets:
                con.execute("INSERT INTO claim_admin_actions "
                            "(claim_id, individual_id, action, previous_verification, actor, created_at) "
                            "VALUES (?, ?, ?, ?, 'local-console-admin', ?)",
                            (target["id"], individual_id, action, target["verification_status"], utcnow()))
            if delete_individual:
                con.execute("DELETE FROM observations WHERE individual_id=?", (individual_id,))
                con.execute("DELETE FROM individuals WHERE id=?", (individual_id,))
                return {"claim_id": claim_id, "individual_id": individual_id, "individual_deleted": True}
            for target in targets:
                if action == "delete":
                    con.execute("DELETE FROM claims WHERE id=?", (target["id"],))
                else:
                    con.execute("UPDATE claims SET verification_status=?, admin_verification=1, updated_at=? WHERE id=?",
                                (action, utcnow(), target["id"]))
                    if action == 'positive':
                        self._record_accepted_acquire(con, target)
            snapshot = self._rebuild_individual_snapshot_in_connection(con, individual_id)
            return {"claim_id": claim_id, "individual_id": individual_id,
                    "individual_deleted": False, "snapshot": snapshot}

    def set_claim_response(
        self,
        claim_id: int,
        responder_user_id: int,
        stance: str,
    ) -> bool:
        normalized = stance.strip().lower()
        if normalized not in (
            "positive",
            "negative",
            "unverified",
        ):
            raise ValueError(
                "stance must be positive, negative, or unverified"
            )

        now = utcnow()
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT
                    id,
                    individual_id,
                    author_user_id,
                    admin_verification,
                    claim_type,
                    ownership_kind,
                    ownership_source,
                    ownership_pair_id,
                    value_text,
                    occurred_at
                FROM claims
                WHERE id = ?
                  AND status = 'active'
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return False
            if not con.execute("SELECT 1 FROM users WHERE id=? AND ban_status<>'ban'",
                               (responder_user_id,)).fetchone():
                raise ValueError("Account is banned")
            if claim["claim_type"] in ("listing", "identity_correction"):
                raise ValueError("This Claim type does not use Owner Verification")

            is_former_owner_claim = (
                claim["claim_type"] == "ownership"
                and str(claim["ownership_source"] or "") == "former_owner"
            )
            is_manual_acquire = (
                claim["claim_type"] == "ownership"
                and claim["ownership_kind"] == "acquire"
                and claim["ownership_source"] not in ("automation", "merged_listing", "former_owner")
            )

            owner = con.execute(
                """
                SELECT 1
                FROM user_guitars
                WHERE user_id = ?
                  AND individual_id = ?
                  AND ownership_status = 'current_owner'
                """,
                (
                    responder_user_id,
                    claim["individual_id"],
                ),
            ).fetchone()
            if not owner:
                if claim['admin_verification']:
                    raise ValueError('Only the current owner may change an administrator verification')
                raise ValueError(
                    "Only the current owner can verify this Claim"
                )
            if int(claim['author_user_id']) == int(responder_user_id):
                raise ValueError("Owner Verification is only for another user's Claim")

            if is_former_owner_claim and claim["ownership_pair_id"]:
                con.execute(
                    """
                    UPDATE claims
                    SET verification_status = ?, admin_verification = 0,
                        updated_at = ?
                    WHERE ownership_pair_id = ?
                      AND ownership_source = 'former_owner'
                      AND status = 'active'
                    """,
                    (
                        normalized,
                        now,
                        claim["ownership_pair_id"],
                    ),
                )
                if normalized == 'positive':
                    pair = con.execute(
                        """SELECT ownership_kind,occurred_at FROM claims
                           WHERE ownership_pair_id=? AND ownership_source='former_owner'
                             AND status='active' AND verification_status='positive'""",
                        (claim["ownership_pair_id"],),
                    ).fetchall()
                    dates = {row['ownership_kind']: row['occurred_at'] for row in pair}
                    if 'acquire' in dates and 'release' in dates:
                        next_order = int(con.execute(
                            'SELECT COALESCE(MAX(display_order), -1) + 1 FROM user_guitars WHERE user_id=?',
                            (claim['author_user_id'],),
                        ).fetchone()[0])
                        con.execute(
                            """INSERT INTO user_guitars
                               (user_id,individual_id,ownership_status,display_order,
                                acquired_at,released_at,created_at,updated_at)
                               VALUES (?,?,'former_owner',?,?,?,?,?)
                               ON CONFLICT(user_id,individual_id) DO UPDATE SET
                                 acquired_at=COALESCE(user_guitars.acquired_at,excluded.acquired_at),
                                 released_at=COALESCE(user_guitars.released_at,excluded.released_at),
                                 updated_at=excluded.updated_at""",
                            (claim['author_user_id'], claim['individual_id'], next_order,
                             dates['acquire'], dates['release'], now, now),
                        )
            else:
                con.execute(
                    """
                    UPDATE claims
                    SET verification_status = ?, admin_verification = 0,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        normalized,
                        now,
                        claim_id,
                    ),
                )

            if normalized == 'positive' and is_manual_acquire:
                self._record_accepted_acquire(con, claim)

            self._rebuild_individual_snapshot_in_connection(
                con,
                int(claim["individual_id"]),
            )
            return True

    def set_claim_vote(
        self,
        claim_id: int,
        user_id: int,
        vote: str,
    ) -> bool:
        normalized = vote.strip().lower()
        if normalized not in (
            "good",
            "bad",
        ):
            raise ValueError(
                "vote must be good or bad"
            )

        now = utcnow()
        with self.connect() as con:
            if not con.execute(
                "SELECT 1 FROM claims WHERE id = ?",
                (claim_id,),
            ).fetchone():
                return False
            if not con.execute(
                "SELECT 1 FROM users WHERE id = ? AND ban_status <> 'ban'",
                (user_id,),
            ).fetchone():
                return False

            existing = con.execute(
                """
                SELECT vote
                FROM claim_votes
                WHERE claim_id = ?
                  AND user_id = ?
                """,
                (
                    claim_id,
                    user_id,
                ),
            ).fetchone()

            if (
                existing
                and str(existing["vote"]).lower()
                == normalized
            ):
                con.execute(
                    """
                    DELETE FROM claim_votes
                    WHERE claim_id = ?
                      AND user_id = ?
                    """,
                    (
                        claim_id,
                        user_id,
                    ),
                )
                return True

            con.execute(
                """
                INSERT INTO claim_votes (
                    claim_id,
                    user_id,
                    vote,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(
                    claim_id,
                    user_id
                )
                DO UPDATE SET
                    vote = excluded.vote,
                    updated_at = excluded.updated_at
                """,
                (
                    claim_id,
                    user_id,
                    normalized,
                    now,
                    now,
                ),
            )
            return True


    def deactivate_claim(
        self,
        claim_id: int,
        user_id: int,
    ) -> dict[str, Any] | None:
        now = utcnow()
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT *
                FROM claims
                WHERE id = ?
                  AND status = 'active'
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return None

            if int(claim["author_user_id"]) != int(user_id):
                raise ValueError(
                    "Only the Claim author can deactivate this Claim"
                )

            if claim["claim_type"] in (
                "listing",
                "identity_correction",
            ):
                raise ValueError(
                    "This Claim type cannot be deactivated from Edit"
                )

            if (claim['claim_type'] == 'ownership'
                    and (claim['ownership_kind'] or 'acquire') == 'acquire'
                    and claim['verification_status'] == 'positive'):
                current_owner = con.execute(
                    'SELECT current_owner_user_id FROM individuals WHERE id=?',
                    (claim['individual_id'],),
                ).fetchone()
                if (current_owner and current_owner['current_owner_user_id'] is not None
                        and int(current_owner['current_owner_user_id']) == user_id):
                    raise ValueError('Current owner cannot deactivate their own accepted Acquire')

            individual_id = int(claim["individual_id"])
            con.execute(
                """
                UPDATE claims
                SET status = 'inactive',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    now,
                    claim_id,
                ),
            )

            snapshot = (
                self._rebuild_individual_snapshot_in_connection(
                    con,
                    individual_id,
                )
            )

            return {
                "claim_id": claim_id,
                "individual_id": individual_id,
                "snapshot": snapshot,
            }


    def delete_claim(
        self,
        claim_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT id, individual_id, claim_type, status
                FROM claims
                WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return None

            individual_id = int(
                claim["individual_id"]
            )

            if (
                claim["claim_type"] == "listing"
                and claim["status"] == "active"
            ):
                other_listing = con.execute(
                    """
                    SELECT 1
                    FROM claims
                    WHERE individual_id = ?
                      AND claim_type = 'listing'
                      AND status = 'active'
                      AND id <> ?
                    LIMIT 1
                    """,
                    (
                        individual_id,
                        claim_id,
                    ),
                ).fetchone()
                if not other_listing:
                    raise ValueError(
                        "The last active Listing Claim cannot be deleted. "
                        "Delete the Individual instead."
                    )

            con.execute(
                "DELETE FROM claims WHERE id = ?",
                (claim_id,),
            )
            snapshot = (
                self._rebuild_individual_snapshot_in_connection(
                    con,
                    individual_id,
                )
            )

            return {
                "claim_id": claim_id,
                "individual_id": individual_id,
                "snapshot": snapshot,
            }

    def delete_individual(
        self,
        individual_id: int,
    ) -> bool:
        with self.connect() as con:
            exists = con.execute(
                """
                SELECT 1
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            if not exists:
                return False

            # observations.individual_id does not cascade. Delete provenance
            # rows first; linked claims are detached automatically via
            # ON DELETE SET NULL, then removed with the Individual cascade.
            con.execute(
                """
                DELETE FROM observations
                WHERE individual_id = ?
                """,
                (individual_id,),
            )
            con.execute(
                """
                DELETE FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            )
            return True


    def cache_listing_rejection(
        self,
        source_site: str,
        source_listing_id: str,
        status: str,
        *,
        recheck_after: str,
    ) -> None:
        now = utcnow()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO crawl_listing_cache (
                    source_site,
                    source_listing_id,
                    status,
                    checked_at,
                    recheck_after
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_site, source_listing_id)
                DO UPDATE SET
                    status = excluded.status,
                    checked_at = excluded.checked_at,
                    recheck_after = excluded.recheck_after
                """,
                (
                    source_site,
                    source_listing_id,
                    status,
                    now,
                    recheck_after,
                ),
            )

    def active_cached_listing_ids(
        self,
        source_site: str,
        listing_ids: list[str],
        *,
        now: str | None = None,
    ) -> set[str]:
        ids = [
            str(value)
            for value in listing_ids
            if value
        ]
        if not ids:
            return set()

        current = now or utcnow()
        result: set[str] = set()
        with self.connect() as con:
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                placeholders = ",".join(
                    "?" for _ in chunk
                )
                rows = con.execute(
                    """
                    SELECT source_listing_id
                    FROM crawl_listing_cache
                    WHERE source_site = ?
                      AND recheck_after > ?
                      AND source_listing_id IN (""" + placeholders + ")",
                    [
                        source_site,
                        current,
                        *chunk,
                    ],
                )
                result.update(
                    str(row["source_listing_id"])
                    for row in rows
                )
        return result


    def start_run(
        self,
        source_site: str,
    ) -> int:
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO crawl_runs(
                    source_site,
                    started_at,
                    status
                )
                VALUES (?,?,'running')
                """,
                (
                    source_site,
                    utcnow(),
                ),
            )

            return int(
                cur.lastrowid
            )

    def update_crawl_run(self, run_id: int, phase: str, counts: dict,
                         category: str, year_min: int, year_max: int) -> None:
        import json
        with self.connect() as con:
            con.execute("UPDATE crawl_runs SET phase=?, counts_json=?, category=?, "
                        "year_min=?, year_max=?, updated_at=? WHERE id=?",
                        (phase, json.dumps(counts), category, year_min, year_max,
                         utcnow(), run_id))

    def crawl_run_log(self, category: str, year_min: int, year_max: int,
                      limit: int = 20) -> list[dict]:
        import json
        with self.connect() as con:
            rows = con.execute("SELECT id,started_at,finished_at,status,phase,counts_json, "
                               "error_message FROM crawl_runs WHERE source_site='reverb' "
                               "AND category=? AND year_min=? AND year_max=? "
                               "ORDER BY id DESC LIMIT ?",
                               (category, year_min, year_max, limit)).fetchall()
        return [{**dict(row), "counts": json.loads(row["counts_json"] or "{}")}
                for row in rows]

    def finish_run(
        self,
        run_id: int,
        **stats,
    ):
        allowed = {
            "pages_discovered",
            "pages_fetched",
            "observations_created",
            "status",
            "error_message",
        }

        sets = []
        values = []

        for key, value in (
            stats.items()
        ):
            if key in allowed:
                sets.append(
                    f"{key}=?"
                )
                values.append(
                    value
                )

        sets.append(
            "finished_at=?"
        )
        values.append(
            utcnow()
        )
        values.append(
            run_id
        )

        with self.connect() as con:
            con.execute(
                f"""
                UPDATE crawl_runs
                SET {", ".join(sets)}
                WHERE id=?
                """,
                values,
            )

    def list_individuals(
        self,
    ):
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        i.*,
                        COUNT(c.id)
                            claim_count
                    FROM individuals i
                    LEFT JOIN claims c
                      ON c.individual_id=i.id
                     AND c.status='active'
                     AND EXISTS (SELECT 1 FROM users u WHERE u.id=c.author_user_id AND u.ban_status='normal')
                    GROUP BY i.id
                    ORDER BY
                        claim_count DESC,
                        i.id
                    """
                )
            )

    def get_individual(
        self,
        individual_id: int,
    ):
        with self.connect() as con:
            individual = con.execute(
                """
                SELECT *
                FROM individuals
                WHERE id=?
                """,
                (
                    individual_id,
                ),
            ).fetchone()

            observations = list(
                con.execute(
                    """
                    SELECT
                        o.*,
                        owner_user.display_name
                            AS owner_user_name
                    FROM observations o
                    LEFT JOIN users owner_user
                      ON owner_user.id = o.actor_user_id
                     AND o.owner_type = 'user'
                    WHERE o.individual_id=?
                    ORDER BY
                        COALESCE(
                            o.listing_date,
                            o.observed_at
                        ),
                        o.id
                    """,
                    (
                        individual_id,
                    ),
                )
            )

            return (
                individual,
                observations,
            )

    def unverified_acquires(self, limit: int = 100, offset: int = 0) -> dict:
        """Active pending Acquire claims from both users and Automation."""
        where = ("c.claim_type='ownership' AND c.ownership_kind='acquire' "
                 "AND c.status='active' AND c.verification_status='unverified' "
                 "AND EXISTS (SELECT 1 FROM users author WHERE author.id=c.author_user_id "
                 "AND author.ban_status='normal')")
        with self.connect() as con:
            rows = con.execute(
                "SELECT c.id AS claim_id, c.individual_id, c.author_user_id, c.ownership_pair_id, "
                "COALESCE(proposed.display_name, c.value_text) AS proposed_owner, "
                "c.ownership_source, c.occurred_at, c.created_at, "
                "u.display_name AS author_name, i.manufacturer, i.model, i.serial_number, "
                "i.current_owner_name, i.current_owner_user_id, i.current_owner_type, "
                "o.source_site, o.source_listing_id "
                "FROM claims c JOIN individuals i ON i.id=c.individual_id "
                "JOIN users u ON u.id=c.author_user_id "
                "LEFT JOIN users proposed ON CAST(proposed.id AS TEXT)=c.value_text "
                "AND COALESCE(c.ownership_source, 'user') <> 'automation' "
                "LEFT JOIN observations o ON o.id=c.observation_id WHERE " + where +
                " ORDER BY c.created_at DESC, c.id DESC",
            ).fetchall()
            eligible = []
            def owner_key(row):
                uid = row["current_owner_user_id"]
                if uid is not None:
                    return ("user", str(uid))
                return ("external", row["current_owner_name"] or "Unknown",
                        row["current_owner_type"] or "unknown")
            for row in rows:
                # Use exactly the same chronological reducer and paired approval
                # as moderation. Roll back ALL snapshot/user_guitars changes.
                con.execute("SAVEPOINT acquire_preview")
                try:
                    if row["ownership_pair_id"]:
                        con.execute("UPDATE claims SET verification_status='positive' "
                                    "WHERE individual_id=? AND ownership_pair_id=?",
                                    (row["individual_id"], row["ownership_pair_id"]))
                    else:
                        con.execute("UPDATE claims SET verification_status='positive' WHERE id=?",
                                    (row["claim_id"],))
                    snapshot = self._rebuild_individual_snapshot_in_connection(con, row["individual_id"])
                    if owner_key(snapshot) != owner_key(row):
                        item = dict(row)
                        item["proposed_owner"] = snapshot["current_owner_name"] or "Unknown"
                        eligible.append(item)
                finally:
                    con.execute("ROLLBACK TO acquire_preview")
                    con.execute("RELEASE acquire_preview")
        return {"total": len(eligible), "items": eligible[offset:offset + limit],
                "limit": limit, "offset": offset}

    @staticmethod
    def _repeated_groups(con) -> list[dict]:
        rows = con.execute("""
            SELECT i.*,
              (SELECT COUNT(*) FROM observations o WHERE o.individual_id=i.id) AS listing_count,
              (SELECT COUNT(*) FROM claims c WHERE c.individual_id=i.id) AS claim_count
            FROM individuals i JOIN (
                SELECT normalized_manufacturer, normalized_serial FROM individuals
                WHERE NULLIF(TRIM(normalized_manufacturer),'') IS NOT NULL
                  AND NULLIF(TRIM(normalized_serial),'') IS NOT NULL
                GROUP BY normalized_manufacturer, normalized_serial HAVING COUNT(*)>1
            ) d USING(normalized_manufacturer, normalized_serial)
            ORDER BY normalized_manufacturer, normalized_serial, i.id
        """).fetchall()
        groups = {}
        for row in rows:
            key = (row["normalized_manufacturer"], row["normalized_serial"])
            group = groups.setdefault(key, {"manufacturer": key[0], "serial": key[1], "items": []})
            group["items"].append(dict(row))
        return list(groups.values())

    def repeated_groups(self) -> dict:
        with self.connect() as con:
            groups = self._repeated_groups(con)
        return {"total": len(groups), "items": groups}

    def resolve_repeated(self, keep_id: int, member_ids: list[int], action: str) -> dict:
        if action not in ("merge", "delete"):
            raise ValueError("Invalid resolution action")
        members = set(member_ids)
        if len(members) != len(member_ids) or len(members) < 2 or keep_id not in members:
            raise ValueError("Select one survivor and at least two distinct members")
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            keeper = con.execute("SELECT * FROM individuals WHERE id=?", (keep_id,)).fetchone()
            if not keeper or not keeper["normalized_manufacturer"] or not keeper["normalized_serial"]:
                raise ValueError("Duplicate group no longer exists; refresh the list")
            actual = {r[0] for r in con.execute(
                "SELECT id FROM individuals WHERE normalized_manufacturer=? AND normalized_serial=?",
                (keeper["normalized_manufacturer"], keeper["normalized_serial"]))}
            if actual != members:
                raise ValueError("Duplicate group changed; refresh before resolving")
            for source_id in sorted(members - {keep_id}):
                if action == "merge":
                    incoming = con.execute("SELECT * FROM claims WHERE individual_id=?", (source_id,)).fetchall()
                    for claim in incoming:
                        con.execute("INSERT INTO claim_admin_actions "
                                    "(claim_id,individual_id,action,previous_verification,actor,created_at) "
                                    "VALUES (?,?,?,?, 'local-console-admin',?)",
                                    (claim["id"], source_id, f"merge_into:{keep_id}", claim["verification_status"], utcnow()))
                        if claim["claim_type"] == "listing":
                            items = {r[0]: r[1] for r in con.execute(
                                "SELECT field_name,value_text FROM claim_listing_items WHERE claim_id=?", (claim["id"],))}
                            con.execute("UPDATE claims SET claim_type='ownership',ownership_kind='acquire', "
                                        "ownership_source='merged_listing',value_text=? WHERE id=?",
                                        (items.get("owner_name") or "Unknown", claim["id"]))
                        if claim["claim_type"] in ("listing", "ownership", "identity_correction", "specification"):
                            con.execute("UPDATE claims SET verification_status=CASE WHEN verification_status='positive' "
                                        "THEN 'unverified' ELSE verification_status END WHERE id=?", (claim["id"],))
                    for table in ("observations", "claims", "media_assets", "notifications"):
                        con.execute(f"UPDATE {table} SET individual_id=? WHERE individual_id=?", (keep_id, source_id))
                    con.execute("UPDATE OR IGNORE user_guitars SET individual_id=? WHERE individual_id=?", (keep_id, source_id))
                    con.execute("INSERT OR IGNORE INTO user_favorites (user_id,individual_id,created_at) "
                                "SELECT user_id,?,created_at FROM user_favorites WHERE individual_id=?", (keep_id, source_id))
                    con.execute("UPDATE users SET signature_individual_id=? WHERE signature_individual_id=?", (keep_id, source_id))
                else:
                    con.execute("DELETE FROM observations WHERE individual_id=?", (source_id,))
                    con.execute("UPDATE users SET signature_individual_id=NULL WHERE signature_individual_id=?", (source_id,))
                con.execute("INSERT INTO individual_resolution_actions "
                            "(source_id,keep_id,action,created_at) VALUES (?,?,?,?)",
                            (source_id, keep_id, action, utcnow()))
                con.execute("DELETE FROM individuals WHERE id=?", (source_id,))
            if action == "merge":
                self._rebuild_individual_snapshot_in_connection(con, keep_id)
        return {"individual_id": keep_id, "resolved": len(members)-1, "action": action}

    def stats(
        self,
    ):
        with self.connect() as con:
            total = con.execute(
                """
                SELECT COUNT(*)
                FROM observations
                """
            ).fetchone()[0]

            # Count external listings represented by active Listing/Acquire
            # claims, not Claim rows: a relisting has an Acquire, not a second
            # Listing Claim. Ownership verification does not erase its evidence.
            listing_counts = con.execute(
                """
                WITH linked AS (
                    SELECT DISTINCT o.individual_id, o.source_site, o.source_listing_id
                    FROM observations o
                    JOIN individuals i ON i.id = o.individual_id
                    WHERE NULLIF(TRIM(o.source_site), '') IS NOT NULL
                      AND o.source_site <> 'user'
                      AND NULLIF(TRIM(o.source_listing_id), '') IS NOT NULL
                      AND NULLIF(TRIM(i.serial_number), '') IS NOT NULL
                      AND EXISTS (
                        SELECT 1 FROM claims c
                        WHERE c.observation_id = o.id
                          AND c.individual_id = o.individual_id
                          AND c.status = 'active'
                          AND EXISTS (SELECT 1 FROM users u WHERE u.id=c.author_user_id AND u.ban_status='normal')
                          AND (c.claim_type = 'listing' OR
                               (c.claim_type = 'ownership' AND c.ownership_kind = 'acquire'))
                      )
                ), repeated AS (
                    SELECT individual_id FROM linked
                    GROUP BY individual_id HAVING COUNT(*) >= 2
                )
                SELECT (SELECT COUNT(*) FROM
                    (SELECT DISTINCT source_site, source_listing_id FROM linked)),
                    (SELECT COUNT(*) FROM repeated)
                """
            ).fetchone()
            serial, relisted = listing_counts
            repeated = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM individuals "
                                   "WHERE NULLIF(TRIM(normalized_manufacturer),'') IS NOT NULL "
                                   "AND NULLIF(TRIM(normalized_serial),'') IS NOT NULL "
                                   "GROUP BY normalized_manufacturer, normalized_serial HAVING COUNT(*)>1)").fetchone()[0]
            individuals = con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]

            max_observations = con.execute(
                """
                SELECT COALESCE(
                    MAX(c),
                    0
                )
                FROM (
                    SELECT COUNT(*) c
                    FROM observations
                    WHERE individual_id
                        IS NOT NULL
                    GROUP BY individual_id
                )
                """
            ).fetchone()[0]

            return {
                "observations": total,
                "serial_observations": serial,
                "serial_extraction_rate": (
                    serial
                    / total
                    * 100
                    if total
                    else 0.0
                ),
                "individuals": (
                    individuals
                ),
                "repeated_individuals": (
                    repeated
                ),
                "max_observations_per_individual": (
                    max_observations
                ),
            }
