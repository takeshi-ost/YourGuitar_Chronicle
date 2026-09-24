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
            "observations": {
                "finish": "TEXT",
                "year": "TEXT",
                "image_url": "TEXT",
                "owner_name": "TEXT",
                "owner_type": "TEXT",
                "owner_profile_url": "TEXT",
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
                        owner_profile_url
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
