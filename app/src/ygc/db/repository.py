from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ygc.extractors.normalization import (
    normalize_manufacturer,
    normalize_model,
    normalize_serial,
)


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
                "avatar_storage_path": "TEXT",
                "avatar_original_filename": "TEXT",
                "avatar_mime_type": "TEXT",
            },
            "user_guitars": {
                "display_order": "INTEGER",
            },
            "claims": {
                "specification_kind": "TEXT",
                "ownership_kind": "TEXT",
                "target_claim_id": "INTEGER",
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

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_claims_target_claim_id
            ON claims(target_claim_id)
            """
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
            source_name = (
                "Reverb"
                if source_site.lower()
                   == "reverb"
                else source_site
            )

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
        Rebuild one Individual's materialized current-state snapshot
        exclusively from active Claims.

        Observation metadata is intentionally not consulted here.
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

        state: dict[str, str | None] = {
            "manufacturer": None,
            "model": None,
            "finish": None,
            "year": None,
            "serial_number": None,
            "location_country": None,
            "location_region": None,
            "current_owner_name": None,
            "current_owner_type": None,
            "current_owner_user_id": None,
            "current_owner_source_url": None,
        }

        listing_rows = list(
            con.execute(
                """
                SELECT
                    c.id AS claim_id,
                    li.field_name,
                    li.value_text
                FROM claims c
                INNER JOIN claim_listing_items li
                  ON li.claim_id = c.id
                WHERE c.individual_id = ?
                  AND c.claim_type = 'listing'
                  AND c.status = 'active'
                ORDER BY
                    COALESCE(
                        c.occurred_at,
                        c.created_at
                    ),
                    c.created_at,
                    c.id,
                    li.id
                """,
                (individual_id,),
            )
        )

        first_listing_id: int | None = None
        identity_fields = {
            "manufacturer",
            "model",
            "year",
            "serial_number",
        }
        listing_snapshot_fields = {
            "manufacturer",
            "model",
            "finish",
            "year",
            "serial_number",
            "location_country",
            "location_region",
        }

        for row in listing_rows:
            claim_id = int(
                row["claim_id"]
            )
            field = str(
                row["field_name"]
                or ""
            ).strip().lower()
            value = (
                str(row["value_text"]).strip()
                if row["value_text"] is not None
                else None
            )
            if (
                field not in listing_snapshot_fields
                or not value
            ):
                continue

            if first_listing_id is None:
                first_listing_id = claim_id

            if claim_id == first_listing_id:
                state[field] = value
                continue

            if field in (
                "location_country",
                "location_region",
            ):
                state[field] = value
            elif (
                field == "finish"
                and state["finish"] is None
            ):
                state["finish"] = value
            elif (
                field in identity_fields
                and state[field] is None
            ):
                state[field] = value

        correction_rows = list(
            con.execute(
                """
                SELECT
                    ci.field_name,
                    ci.new_value
                FROM claims c
                INNER JOIN claim_identity_items ci
                  ON ci.claim_id = c.id
                WHERE c.individual_id = ?
                  AND c.claim_type = 'identity_correction'
                  AND c.status = 'active'
                ORDER BY
                    COALESCE(
                        c.occurred_at,
                        c.created_at
                    ),
                    c.created_at,
                    c.id,
                    ci.id
                """,
                (individual_id,),
            )
        )

        for row in correction_rows:
            field = str(
                row["field_name"]
                or ""
            ).strip().lower()
            if field not in identity_fields:
                continue
            value = row["new_value"]
            state[field] = (
                str(value).strip()
                if value is not None
                and str(value).strip()
                else None
            )

        specification_rows = list(
            con.execute(
                """
                SELECT
                    si.field_name,
                    si.value_text
                FROM claims c
                INNER JOIN claim_spec_items si
                  ON si.claim_id = c.id
                WHERE c.individual_id = ?
                  AND c.claim_type = 'specification'
                  AND c.status = 'active'
                ORDER BY
                    COALESCE(
                        c.occurred_at,
                        c.created_at
                    ),
                    c.created_at,
                    c.id,
                    si.id
                """,
                (individual_id,),
            )
        )

        for row in specification_rows:
            field = str(
                row["field_name"]
                or ""
            ).strip().lower()
            value = (
                str(row["value_text"]).strip()
                if row["value_text"] is not None
                else None
            )
            if field == "finish" and value:
                state["finish"] = value

        owner_claims = list(
            con.execute(
                """
                SELECT
                    c.id,
                    c.claim_type,
                    c.value_text,
                    c.ownership_kind,
                    c.occurred_at,
                    c.created_at
                FROM claims c
                WHERE c.individual_id = ?
                  AND c.status = 'active'
                  AND c.claim_type IN (
                        'listing',
                        'ownership',
                        'owner_change',
                        'release'
                  )
                ORDER BY
                    COALESCE(
                        c.occurred_at,
                        c.created_at
                    ),
                    c.created_at,
                    c.id
                """,
                (individual_id,),
            )
        )

        for claim in owner_claims:
            claim_type = str(
                claim["claim_type"]
            )
            if claim_type == "listing":
                items = {
                    str(row["field_name"]): (
                        str(row["value_text"]).strip()
                        if row["value_text"] is not None
                        else None
                    )
                    for row
                    in con.execute(
                        """
                        SELECT field_name, value_text
                        FROM claim_listing_items
                        WHERE claim_id = ?
                        """,
                        (claim["id"],),
                    )
                }
                owner_name = items.get(
                    "owner_name"
                )
                owner_type = items.get(
                    "owner_type"
                )
                owner_user_id = items.get(
                    "owner_user_id"
                )
                owner_user = (
                    con.execute(
                        """
                        SELECT display_name, account_type
                        FROM users
                        WHERE id = ?
                        """,
                        (owner_user_id,),
                    ).fetchone()
                    if owner_user_id
                    else None
                )
                state["current_owner_name"] = (
                    str(owner_user["display_name"])
                    if owner_user
                    else (
                        owner_name
                        if owner_name
                        else None
                    )
                )
                state["current_owner_type"] = (
                    str(owner_user["account_type"])
                    if owner_user
                    else (
                        owner_type
                        if owner_type
                        else None
                    )
                )
                state["current_owner_user_id"] = (
                    owner_user_id
                    if owner_user
                    else None
                )
                state["current_owner_source_url"] = (
                    items.get("source_url")
                    or None
                )
            elif claim_type in ("ownership", "owner_change"):
                ownership_kind = (
                    str(claim["ownership_kind"] or "acquire").strip().lower()
                    if "ownership_kind" in claim.keys()
                    else "acquire"
                )
                if ownership_kind in ("transfer", "release", "inherit"):
                    state["current_owner_name"] = "Unknown"
                    state["current_owner_type"] = "unknown"
                    state["current_owner_user_id"] = None
                    state["current_owner_source_url"] = None
                    state["location_country"] = None
                    state["location_region"] = None
                    continue
                owner_user_id = (
                    str(claim["value_text"]).strip()
                    if claim["value_text"] is not None
                    else ""
                )
                user = (
                    con.execute(
                        """
                        SELECT
                            display_name,
                            account_type,
                            location_country,
                            location_region
                        FROM users
                        WHERE id = ?
                        """,
                        (owner_user_id,),
                    ).fetchone()
                    if owner_user_id
                    else None
                )
                state["current_owner_name"] = (
                    str(user["display_name"])
                    if user
                    else None
                )
                state["current_owner_type"] = (
                    str(user["account_type"])
                    if user
                    else None
                )
                state["current_owner_user_id"] = (
                    owner_user_id
                    if user
                    else None
                )
                state["current_owner_source_url"] = None
                state["location_country"] = (
                    str(user["location_country"]).strip()
                    if user
                    and user["location_country"]
                    and str(user["location_country"]).strip()
                    else None
                )
                state["location_region"] = (
                    str(user["location_region"]).strip()
                    if user
                    and user["location_region"]
                    and str(user["location_region"]).strip()
                    else None
                )
            elif claim_type == "release":
                state["current_owner_name"] = "Unknown"
                state["current_owner_type"] = "unknown"
                state["current_owner_user_id"] = None
                state["current_owner_source_url"] = None
                state["location_country"] = None
                state["location_region"] = None

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
                "Reverb",
            )
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
                SELECT *
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
                        i.serial_number
                    FROM user_guitars ug
                    INNER JOIN individuals i
                      ON i.id = ug.individual_id
                    WHERE ug.user_id = ?
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

    def update_user(
        self,
        user_id: int,
        *,
        display_name: str,
        account_type: str,
        location_country: str | None,
        location_region: str | None,
    ) -> bool:
        name = display_name.strip()
        account = account_type.strip().lower()

        if not name:
            raise ValueError(
                "display_name is required"
            )

        if account not in (
            "user",
            "shop",
        ):
            raise ValueError(
                "account_type must be user or shop"
            )

        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE users
                SET display_name = ?,
                    account_type = ?,
                    location_country = ?,
                    location_region = ?,
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
                                        'owner_change',
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
                "SELECT 1 FROM users WHERE id = ?",
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
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, 'ownership',
                    'owner_user_id', ?, ?, ?, ?,
                    'active', ?, ?
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
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)

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
            else:
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

    def create_owner_change_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        acquired_at: str | None = None,
        previous_owner_text: str | None = None,
        body: str | None = None,
    ) -> tuple[int, int]:
        return self.create_ownership_claim(
            user_id,
            individual_id,
            ownership_kind="acquire",
            occurred_at=acquired_at,
            previous_owner_text=previous_owner_text,
            body=body,
        )

    def create_release_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        reason: str | None = None,
    ) -> tuple[int, int]:
        return self.create_ownership_claim(
            user_id,
            individual_id,
            ownership_kind="release",
            body=reason,
        )

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
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'incident',
                    'incident_kind', ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
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
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'event',
                    'event_kind', ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
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
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, NULL, ?, 'specification',
                    NULL, NULL, ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    user_id,
                    kind,
                    note,
                    event_date,
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
                elif claim["claim_type"] == "release":
                    con.execute(
                        """
                        UPDATE observations
                        SET raw_text = ?,
                            occurred_at = ?
                        WHERE id = ?
                        """,
                        (
                            note,
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

            if claim["claim_type"] in ("ownership", "owner_change"):
                ownership_kind = (
                    str(claim["ownership_kind"] or "acquire").strip().lower()
                    if claim["claim_type"] == "ownership"
                    else "acquire"
                )
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
            elif claim["claim_type"] == "release":
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
                          ON u.id = c.author_user_id
                        WHERE c.individual_id = ?
                          AND c.claim_type = 'specification'
                          AND c.status = 'active'
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
                          ON u.id = c.author_user_id
                        WHERE c.individual_id = ?
                          AND c.claim_type = 'specification'
                          AND c.status = 'active'
                    ),
                    ranked AS (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY field_name
                                ORDER BY
                                    COALESCE(
                                        occurred_at,
                                        created_at
                                    ) DESC,
                                    created_at DESC,
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
                        u.display_name
                            AS author_name,
                        (
                            SELECT o.raw_text
                            FROM observations o
                            WHERE o.id = c.observation_id
                            LIMIT 1
                        ) AS observation_raw_text,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_site'
                            LIMIT 1
                        ) AS source_site,
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_url'
                            LIMIT 1
                        ) AS source_url,
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
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'source_listing_id'
                            LIMIT 1
                        ) AS source_listing_id,
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
                        FROM claim_votes
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
                        individual_id,
                    ),
                )
            )

    def get_media_asset(
        self,
        media_asset_id: int,
    ) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(
                """
                SELECT *
                FROM media_assets
                WHERE id = ?
                """,
                (media_asset_id,),
            ).fetchone()


    def set_claim_response(
        self,
        claim_id: int,
        responder_user_id: int,
        stance: str,
    ) -> bool:
        normalized = stance.strip().lower()
        if normalized not in (
            "endorse",
            "dispute",
            "neutral",
        ):
            raise ValueError(
                "stance must be endorse, dispute, or neutral"
            )

        now = utcnow()
        with self.connect() as con:
            claim = con.execute(
                """
                SELECT individual_id, author_user_id
                FROM claims
                WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
            if not claim:
                return False

            if int(claim["author_user_id"]) == int(
                responder_user_id
            ):
                raise ValueError(
                    "Owner response is only for another user's Claim"
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
                raise ValueError(
                    "Only the current owner can respond to another user's Claim"
                )

            con.execute(
                """
                INSERT INTO claim_responses (
                    claim_id,
                    responder_user_id,
                    stance,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(
                    claim_id,
                    responder_user_id
                )
                DO UPDATE SET
                    stance = excluded.stance,
                    updated_at = excluded.updated_at
                """,
                (
                    claim_id,
                    responder_user_id,
                    normalized,
                    now,
                    now,
                ),
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
                "SELECT 1 FROM users WHERE id = ?",
                (user_id,),
            ).fetchone():
                return False

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
                        COUNT(o.id)
                            observation_count
                    FROM individuals i
                    LEFT JOIN observations o
                      ON o.individual_id=i.id
                    GROUP BY i.id
                    ORDER BY
                        observation_count DESC,
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

            serial = con.execute(
                """
                SELECT COUNT(DISTINCT c.id)
                FROM claims c
                INNER JOIN claim_listing_items li
                  ON li.claim_id = c.id
                 AND li.field_name = 'serial_number'
                WHERE c.claim_type = 'listing'
                  AND c.status = 'active'
                  AND NULLIF(TRIM(li.value_text), '') IS NOT NULL
                """
            ).fetchone()[0]

            individuals = con.execute(
                """
                SELECT COUNT(*)
                FROM individuals
                """
            ).fetchone()[0]

            repeated = con.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT c.individual_id
                    FROM claims c
                    WHERE c.claim_type = 'listing'
                      AND c.status = 'active'
                    GROUP BY c.individual_id
                    HAVING COUNT(*) >= 2
                )
                """
            ).fetchone()[0]

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
