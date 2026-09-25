from __future__ import annotations

import sqlite3
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
            self._backfill_listing_claims(
                con
            )
            self._backfill_listing_claim_items(
                con
            )
            self._sync_individual_locations_from_listing_claims(
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
    ) -> None:
        source_ids: dict[str, int] = {}

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

            listing_values = {
                "manufacturer": row["manufacturer"],
                "model": row["model"],
                "finish": row["finish"],
                "year": row["year"],
                "serial_number": row["serial_number"],
                "owner_name": row["owner_name"],
                "owner_type": row["owner_type"],
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

    def _backfill_listing_claim_items(
        self,
        con: sqlite3.Connection,
    ) -> None:
        """
        One-time compatibility migration.

        Older Listing Claims kept their structured values only on the
        attached Observation. Copy those values into the Claim-owned
        structured item table. After migration, normal reads must use
        claim_listing_items rather than Observation metadata.
        """
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
                con.execute(
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

    def _sync_individual_locations_from_listing_claims(
        self,
        con: sqlite3.Connection,
    ) -> None:
        """
        Individual Location is initialized from the earliest active
        Listing Claim that explicitly defines Location. Observation is
        not consulted here.
        """
        rows = list(
            con.execute(
                """
                SELECT
                    i.id AS individual_id,
                    (
                        SELECT li.value_text
                        FROM claims c
                        INNER JOIN claim_listing_items li
                          ON li.claim_id = c.id
                        WHERE c.individual_id = i.id
                          AND c.claim_type = 'listing'
                          AND c.status = 'active'
                          AND li.field_name = 'location_country'
                          AND TRIM(li.value_text) <> ''
                        ORDER BY
                            COALESCE(c.occurred_at, c.created_at) ASC,
                            c.id ASC
                        LIMIT 1
                    ) AS location_country,
                    (
                        SELECT li.value_text
                        FROM claims c
                        INNER JOIN claim_listing_items li
                          ON li.claim_id = c.id
                        WHERE c.individual_id = i.id
                          AND c.claim_type = 'listing'
                          AND c.status = 'active'
                          AND li.field_name = 'location_region'
                          AND TRIM(li.value_text) <> ''
                        ORDER BY
                            COALESCE(c.occurred_at, c.created_at) ASC,
                            c.id ASC
                        LIMIT 1
                    ) AS location_region
                FROM individuals i
                ORDER BY i.id
                """
            )
        )

        for row in rows:
            con.execute(
                """
                UPDATE individuals
                SET location_country = ?,
                    location_region = ?
                WHERE id = ?
                """,
                (
                    row["location_country"],
                    row["location_region"],
                    row["individual_id"],
                ),
            )

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
        listing_snapshot_fields = set(
            state.keys()
        )

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
                normalized_maker,
                normalized_model,
                normalized_serial,
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

    def list_observations_for_backfill(
        self,
    ) -> list[sqlite3.Row]:
        with self.connect() as con:
            return list(
                con.execute(
                    """
                    SELECT
                        id,
                        individual_id,
                        source_listing_id,
                        model,
                        finish,
                        year,
                        image_url,
                        owner_name,
                        owner_type,
                        owner_profile_url,
                        location_country,
                        location_region,
                        location_source
                    FROM observations
                    WHERE source_site = 'reverb'
                      AND source_listing_id
                          IS NOT NULL
                      AND TRIM(
                          source_listing_id
                      ) <> ''
                      AND (
                          finish IS NULL
                          OR TRIM(finish) = ''
                          OR year IS NULL
                          OR TRIM(year) = ''
                          OR image_url IS NULL
                          OR TRIM(image_url) = ''
                          OR owner_profile_url IS NULL
                          OR TRIM(owner_profile_url) = ''
                          OR location_country IS NULL
                          OR TRIM(location_country) = ''
                      )
                    ORDER BY id
                    """
                )
            )

    def update_observation_metadata(
        self,
        observation_id: int,
        model: str | None,
        finish: str | None,
        year: str | None,
        image_url: str | None = None,
        owner_name: str | None = None,
        owner_type: str | None = None,
        owner_profile_url: str | None = None,
        location_country: str | None = None,
        location_region: str | None = None,
        location_source: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE observations
                SET model = COALESCE(
                        NULLIF(?, ''),
                        model
                    ),
                    finish = COALESCE(
                        NULLIF(?, ''),
                        finish
                    ),
                    year = COALESCE(
                        NULLIF(?, ''),
                        year
                    ),
                    image_url = COALESCE(
                        NULLIF(?, ''),
                        image_url
                    ),
                    owner_name = COALESCE(
                        NULLIF(?, ''),
                        owner_name
                    ),
                    owner_type = COALESCE(
                        NULLIF(?, ''),
                        owner_type
                    ),
                    owner_profile_url = COALESCE(
                        NULLIF(?, ''),
                        owner_profile_url
                    ),
                    location_country = COALESCE(
                        NULLIF(?, ''),
                        location_country
                    ),
                    location_region = COALESCE(
                        NULLIF(?, ''),
                        location_region
                    ),
                    location_source = COALESCE(
                        NULLIF(?, ''),
                        location_source
                    )
                WHERE id = ?
                """,
                (
                    model,
                    finish,
                    year,
                    image_url,
                    owner_name,
                    owner_type,
                    owner_profile_url,
                    location_country,
                    location_region,
                    location_source,
                    observation_id,
                ),
            )

    def sync_individual_metadata_from_observations(
        self,
    ) -> int:
        updated = 0

        with self.connect() as con:
            rows = list(
                con.execute(
                    """
                    SELECT id
                    FROM individuals
                    ORDER BY id
                    """
                )
            )

            for row in rows:
                individual_id = int(
                    row["id"]
                )

                source = con.execute(
                    """
                    SELECT
                        (
                            SELECT model
                            FROM observations
                            WHERE individual_id = ?
                              AND model IS NOT NULL
                              AND TRIM(model) <> ''
                            ORDER BY
                                COALESCE(
                                    listing_date,
                                    observed_at
                                ) DESC,
                                id DESC
                            LIMIT 1
                        ) AS model,
                        (
                            SELECT finish
                            FROM observations
                            WHERE individual_id = ?
                              AND finish IS NOT NULL
                              AND TRIM(finish) <> ''
                            ORDER BY
                                COALESCE(
                                    listing_date,
                                    observed_at
                                ) DESC,
                                id DESC
                            LIMIT 1
                        ) AS finish,
                        (
                            SELECT year
                            FROM observations
                            WHERE individual_id = ?
                              AND year IS NOT NULL
                              AND TRIM(year) <> ''
                            ORDER BY
                                COALESCE(
                                    listing_date,
                                    observed_at
                                ) DESC,
                                id DESC
                            LIMIT 1
                        ) AS year
                    """,
                    (
                        individual_id,
                        individual_id,
                        individual_id,
                    ),
                ).fetchone()

                con.execute(
                    """
                    UPDATE individuals
                    SET model = COALESCE(
                            NULLIF(?, ''),
                            model
                        ),
                        finish = COALESCE(
                            NULLIF(?, ''),
                            finish
                        ),
                        year = COALESCE(
                            NULLIF(?, ''),
                            year
                        ),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        source["model"],
                        source["finish"],
                        source["year"],
                        utcnow(),
                        individual_id,
                    ),
                )

                updated += 1

        return updated

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
                    WITH latest_observation AS (
                        SELECT o.*
                        FROM observations o
                        INNER JOIN (
                            SELECT
                                individual_id,
                                MAX(
                                    COALESCE(
                                        listing_date,
                                        observed_at
                                    )
                                ) AS latest_date
                            FROM observations
                            WHERE individual_id
                                IS NOT NULL
                            GROUP BY individual_id
                        ) latest
                          ON latest.individual_id
                             = o.individual_id
                         AND COALESCE(
                                o.listing_date,
                                o.observed_at
                             )
                             = latest.latest_date
                        WHERE o.id = (
                            SELECT MAX(o2.id)
                            FROM observations o2
                            WHERE o2.individual_id
                                  = o.individual_id
                              AND COALESCE(
                                    o2.listing_date,
                                    o2.observed_at
                                  )
                                  = COALESCE(
                                    o.listing_date,
                                    o.observed_at
                                  )
                        )
                    )
                    SELECT
                        TRIM(location_country)
                            AS label,
                        COUNT(*) AS count
                    FROM latest_observation
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
                    WITH latest_observation AS (
                        SELECT o.*
                        FROM observations o
                        INNER JOIN (
                            SELECT
                                individual_id,
                                MAX(
                                    COALESCE(
                                        listing_date,
                                        observed_at
                                    )
                                ) AS latest_date
                            FROM observations
                            WHERE individual_id
                                IS NOT NULL
                            GROUP BY individual_id
                        ) latest
                          ON latest.individual_id
                             = o.individual_id
                         AND COALESCE(
                                o.listing_date,
                                o.observed_at
                             )
                             = latest.latest_date
                        WHERE o.id = (
                            SELECT MAX(o2.id)
                            FROM observations o2
                            WHERE o2.individual_id
                                  = o.individual_id
                              AND COALESCE(
                                    o2.listing_date,
                                    o2.observed_at
                                  )
                                  = COALESCE(
                                    o.listing_date,
                                    o.observed_at
                                  )
                        )
                    )
                    SELECT COUNT(*)
                    FROM latest_observation
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

            return (
                cur.rowcount
                > 0
            )

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

            cur = con.execute(
                """
                INSERT INTO individuals (
                    manufacturer,
                    model,
                    finish,
                    year,
                    serial_number,
                    location_country,
                    location_region,
                    normalized_manufacturer,
                    normalized_model,
                    normalized_serial,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    maker,
                    model_value,
                    finish_value,
                    year_value,
                    serial,
                    user["location_country"],
                    user["location_region"],
                    normalized_maker,
                    normalized_model,
                    normalized_serial,
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
                    manufacturer,
                    model,
                    finish,
                    year,
                    serial_number,
                    owner_name,
                    owner_type,
                    location_country,
                    location_region,
                    location_source,
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
                    ?, ?, ?, ?, ?, ?, ?, 'user',
                    ?, ?, 'user_profile',
                    'listing', ?, ?, 'user', '',
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    individual_id,
                    maker,
                    model_value,
                    finish_value,
                    year_value,
                    serial,
                    user["display_name"],
                    user["location_country"],
                    user["location_region"],
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


    def create_owner_change_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        acquired_at: str | None = None,
        previous_owner_text: str | None = None,
        body: str | None = None,
    ) -> tuple[int, int]:
        now = utcnow()

        with self.connect() as con:
            user = con.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            individual = con.execute(
                "SELECT * FROM individuals WHERE id = ?",
                (individual_id,),
            ).fetchone()

            if not user or not individual:
                raise ValueError(
                    "User or Individual not found"
                )

            event_title = "Owner Change"
            details = []
            if previous_owner_text:
                details.append(
                    f"Previous owner: {previous_owner_text.strip()}"
                )
            if body:
                details.append(body.strip())
            raw_text = "\n".join(
                value
                for value in details
                if value
            ) or None

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
                    ?, ?, ?, ?, ?, ?, ?, 'user',
                    'owner_change', ?, ?,
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
                    user["display_name"],
                    user_id,
                    acquired_at,
                    f"user://{user_id}",
                    now,
                    event_title,
                    raw_text,
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
                    ?, ?, ?, 'owner_change',
                    'owner_user_id', ?, ?, ?,
                    'active', ?, ?
                )
                """,
                (
                    individual_id,
                    observation_id,
                    user_id,
                    str(user_id),
                    (
                        body.strip()
                        if body
                        else None
                    ),
                    acquired_at,
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
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
                VALUES (?, ?, 'current_owner', ?, ?, ?, ?)
                ON CONFLICT(
                    user_id,
                    individual_id
                )
                DO UPDATE SET
                    ownership_status = 'current_owner',
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
                    acquired_at,
                    now,
                    now,
                ),
            )

            return (
                observation_id,
                claim_id,
            )

    def create_release_claim(
        self,
        user_id: int,
        individual_id: int,
        *,
        reason: str | None = None,
    ) -> tuple[int, int]:
        now = utcnow()
        event_date = now[:10]
        note = (
            reason.strip()
            if reason and reason.strip()
            else None
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
            individual = con.execute(
                """
                SELECT *
                FROM individuals
                WHERE id = ?
                """,
                (individual_id,),
            ).fetchone()
            ownership = con.execute(
                """
                SELECT *
                FROM user_guitars
                WHERE user_id = ?
                  AND individual_id = ?
                  AND ownership_status = 'current_owner'
                """,
                (
                    user_id,
                    individual_id,
                ),
            ).fetchone()

            if not user or not individual:
                raise ValueError(
                    "User or Individual not found"
                )
            if not ownership:
                raise ValueError(
                    "User is not the current owner of this Individual"
                )

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
                    ?, ?, ?, ?, ?, ?,
                    'Unknown', 'unknown',
                    'release', ?, ?,
                    'user', ?, ?, 'Release',
                    ?, ?
                )
                """,
                (
                    individual_id,
                    individual["manufacturer"],
                    individual["model"],
                    individual["finish"],
                    individual["year"],
                    individual["serial_number"],
                    user_id,
                    event_date,
                    f"user://{user_id}",
                    now,
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
                    ?, ?, ?, 'release',
                    'owner_user_id', 'unknown',
                    ?, ?, 'active', ?, ?
                )
                """,
                (
                    individual_id,
                    observation_id,
                    user_id,
                    note,
                    event_date,
                    now,
                    now,
                ),
            )
            claim_id = int(
                cur.lastrowid
            )

            con.execute(
                """
                UPDATE user_guitars
                SET ownership_status = 'former_owner',
                    released_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                  AND individual_id = ?
                  AND ownership_status = 'current_owner'
                """,
                (
                    event_date,
                    now,
                    user_id,
                    individual_id,
                ),
            )

            return (
                observation_id,
                claim_id,
            )

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

            if claim["claim_type"] == "owner_change":
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

            con.execute(
                """
                UPDATE individuals
                SET manufacturer = ?,
                    model = ?,
                    year = ?,
                    serial_number = ?,
                    normalized_manufacturer = ?,
                    normalized_model = ?,
                    normalized_serial = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    maker,
                    model_value,
                    year_value,
                    serial,
                    normalized_maker,
                    normalized_model,
                    normalized_serial,
                    now,
                    individual["id"],
                ),
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
                        (
                            SELECT li.value_text
                            FROM claim_listing_items li
                            WHERE li.claim_id = c.id
                              AND li.field_name = 'owner_name'
                            LIMIT 1
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
                SELECT COUNT(*)
                FROM observations
                WHERE serial_number
                    IS NOT NULL
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
                    SELECT individual_id
                    FROM observations
                    WHERE individual_id
                        IS NOT NULL
                    GROUP BY individual_id
                    HAVING COUNT(*)>=2
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
