from __future__ import annotations

from pathlib import Path

from ygc.db.repository import Repository


def _insert_user(con, name: str, now: str) -> int:
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
        (name, now, now),
    )
    return int(cur.lastrowid)


def _insert_listing_claim(
    con,
    *,
    individual_id: int,
    author_user_id: int,
    occurred_at: str,
    created_at: str,
    items: dict[str, str],
) -> int:
    cur = con.execute(
        """
        INSERT INTO claims (
            individual_id,
            observation_id,
            author_user_id,
            claim_type,
            field_name,
            value_text,
            occurred_at,
            status,
            created_at,
            updated_at
        )
        VALUES (
            ?, NULL, ?, 'listing',
            'listing', 'test',
            ?, 'active', ?, ?
        )
        """,
        (
            individual_id,
            author_user_id,
            occurred_at,
            created_at,
            created_at,
        ),
    )
    claim_id = int(cur.lastrowid)

    for field_name, value_text in items.items():
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
                created_at,
            ),
        )

    return claim_id


def test_rebuild_individual_snapshot_uses_claims_only(
    tmp_path: Path,
):
    db_path = tmp_path / "chronicle.db"
    repository = Repository(db_path)
    repository.init_db()

    now = "2026-09-25T00:00:00+00:00"

    with repository.connect() as con:
        user_id = _insert_user(
            con,
            "Owner",
            now,
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
            VALUES (
                'WRONG',
                'WRONG',
                'WRONG',
                '1900',
                'WRONG',
                'XX',
                'Wrong',
                'wrong',
                'wrong',
                'wrong',
                ?,
                ?
            )
            """,
            (now, now),
        )
        individual_id = int(cur.lastrowid)

        listing_claim_id = _insert_listing_claim(
            con,
            individual_id=individual_id,
            author_user_id=user_id,
            occurred_at="2020-01-01",
            created_at=now,
            items={
                "manufacturer": "Fender",
                "model": "Stratocaster",
                "finish": "Sunburst",
                "year": "1974",
                "serial_number": "524436",
                "location_country": "US",
                "location_region": "CA",
            },
        )

        correction = con.execute(
            """
            INSERT INTO claims (
                individual_id,
                observation_id,
                author_user_id,
                claim_type,
                target_claim_id,
                occurred_at,
                status,
                created_at,
                updated_at
            )
            VALUES (
                ?, NULL, ?, 'identity_correction',
                ?, '2020-01-01',
                'active', ?, ?
            )
            """,
            (
                individual_id,
                user_id,
                listing_claim_id,
                now,
                now,
            ),
        )
        correction_id = int(
            correction.lastrowid
        )
        con.execute(
            """
            INSERT INTO claim_identity_items (
                claim_id,
                field_name,
                old_value,
                new_value,
                created_at
            )
            VALUES (?, 'year', '1974', '1975', ?)
            """,
            (
                correction_id,
                now,
            ),
        )

        spec = con.execute(
            """
            INSERT INTO claims (
                individual_id,
                observation_id,
                author_user_id,
                claim_type,
                specification_kind,
                occurred_at,
                status,
                created_at,
                updated_at
            )
            VALUES (
                ?, NULL, ?, 'specification',
                'repair', '2021-01-01',
                'active', ?, ?
            )
            """,
            (
                individual_id,
                user_id,
                now,
                now,
            ),
        )
        spec_id = int(spec.lastrowid)
        con.execute(
            """
            INSERT INTO claim_spec_items (
                claim_id,
                field_name,
                value_text,
                created_at
            )
            VALUES (?, 'finish', 'Natural', ?)
            """,
            (
                spec_id,
                now,
            ),
        )

    snapshot = (
        repository.rebuild_individual_snapshot(
            individual_id
        )
    )

    assert snapshot["manufacturer"] == "Fender"
    assert snapshot["model"] == "Stratocaster"
    assert snapshot["finish"] == "Natural"
    assert snapshot["year"] == "1975"
    assert snapshot["serial_number"] == "524436"
    assert snapshot["location_country"] == "US"
    assert snapshot["location_region"] == "CA"

    with repository.connect() as con:
        row = con.execute(
            """
            SELECT *
            FROM individuals
            WHERE id = ?
            """,
            (individual_id,),
        ).fetchone()

    assert row is not None
    assert row["manufacturer"] == "Fender"
    assert row["finish"] == "Natural"
    assert row["year"] == "1975"


def test_inactive_identity_correction_is_ignored(
    tmp_path: Path,
):
    db_path = tmp_path / "chronicle.db"
    repository = Repository(db_path)
    repository.init_db()

    now = "2026-09-25T00:00:00+00:00"

    with repository.connect() as con:
        user_id = _insert_user(
            con,
            "Owner",
            now,
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
            VALUES ('Placeholder', 'placeholder', 'placeholder', ?, ?)
            """,
            (now, now),
        )
        individual_id = int(cur.lastrowid)

        listing_claim_id = _insert_listing_claim(
            con,
            individual_id=individual_id,
            author_user_id=user_id,
            occurred_at="2020-01-01",
            created_at=now,
            items={
                "manufacturer": "Fender",
                "model": "Stratocaster",
                "year": "1974",
                "serial_number": "524436",
            },
        )

        correction = con.execute(
            """
            INSERT INTO claims (
                individual_id,
                observation_id,
                author_user_id,
                claim_type,
                target_claim_id,
                occurred_at,
                status,
                created_at,
                updated_at
            )
            VALUES (
                ?, NULL, ?, 'identity_correction',
                ?, '2020-01-01',
                'inactive', ?, ?
            )
            """,
            (
                individual_id,
                user_id,
                listing_claim_id,
                now,
                now,
            ),
        )
        correction_id = int(
            correction.lastrowid
        )
        con.execute(
            """
            INSERT INTO claim_identity_items (
                claim_id,
                field_name,
                old_value,
                new_value,
                created_at
            )
            VALUES (?, 'year', '1974', '1975', ?)
            """,
            (
                correction_id,
                now,
            ),
        )

    snapshot = (
        repository.rebuild_individual_snapshot(
            individual_id
        )
    )

    assert snapshot["year"] == "1974"
