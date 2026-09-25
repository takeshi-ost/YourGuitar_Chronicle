from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
            },
            "user_guitars": {
                "display_order": "INTEGER",
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

            con.execute(
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
                        o.source_site
                            AS source_site,
                        o.source_url
                            AS source_url,
                        o.image_url
                            AS image_url,
                        o.title
                            AS listing_title,
                        o.seller
                            AS seller,
                        o.owner_name
                            AS observed_owner_name,
                        o.location_country
                            AS location_country,
                        o.location_region
                            AS location_region,
                        o.manufacturer
                            AS observed_manufacturer,
                        o.model
                            AS observed_model,
                        o.finish
                            AS observed_finish,
                        o.year
                            AS observed_year,
                        o.serial_number
                            AS observed_serial_number,
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
                    LEFT JOIN observations o
                      ON o.id = c.observation_id
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
                    SELECT *
                    FROM observations
                    WHERE individual_id=?
                    ORDER BY
                        COALESCE(
                            listing_date,
                            observed_at
                        ),
                        id
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
