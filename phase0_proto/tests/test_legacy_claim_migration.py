from __future__ import annotations

from pathlib import Path

from ygc.db.repository import Repository


def _seed_legacy_observation(
    repository: Repository,
) -> tuple[int, int]:
    now = "2026-09-25T00:00:00+00:00"

    with repository.connect() as con:
        individual = con.execute(
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
            VALUES (
                'Fender',
                'Stratocaster',
                'Natural',
                '1974',
                '524436',
                'fender',
                'stratocaster',
                '524436',
                ?,
                ?
            )
            """,
            (now, now),
        )
        individual_id = int(
            individual.lastrowid
        )

        observation = con.execute(
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
                seller,
                location_country,
                location_region,
                event_type,
                source_site,
                source_url,
                image_url,
                source_listing_id,
                observed_at,
                listing_date,
                title,
                created_at
            )
            VALUES (
                ?,
                'Fender',
                'Stratocaster',
                'Natural',
                '1974',
                '524436',
                'Vintage Shop',
                'shop',
                'Vintage Shop',
                'US',
                'CA',
                'listing',
                'reverb',
                'https://reverb.example/item/12345',
                'https://reverb.example/image.jpg',
                '12345',
                ?,
                '1974-01-01',
                '1974 Fender Stratocaster',
                ?
            )
            """,
            (
                individual_id,
                now,
                now,
            ),
        )

        return (
            individual_id,
            int(observation.lastrowid),
        )


def test_init_db_does_not_convert_legacy_observation(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()
    _seed_legacy_observation(
        repository
    )

    repository.init_db()

    with repository.connect() as con:
        claim_count = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM claims
                WHERE claim_type = 'listing'
                """
            ).fetchone()[0]
        )

    assert claim_count == 0


def test_legacy_observation_migration_is_explicit_and_idempotent(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()
    individual_id, observation_id = (
        _seed_legacy_observation(
            repository
        )
    )

    first = (
        repository
        .migrate_legacy_observations_to_claims()
    )

    assert first["claims_created"] == 1
    assert first["listing_items_created"] == 0
    assert first["snapshots_rebuilt"] == 1

    with repository.connect() as con:
        claim = con.execute(
            """
            SELECT id
            FROM claims
            WHERE observation_id = ?
              AND claim_type = 'listing'
            """,
            (observation_id,),
        ).fetchone()
        assert claim is not None

        claim_id = int(claim["id"])

        item_count = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM claim_listing_items
                WHERE claim_id = ?
                """,
                (claim_id,),
            ).fetchone()[0]
        )
        assert item_count == 16

        snapshot = con.execute(
            """
            SELECT
                manufacturer,
                model,
                finish,
                year,
                serial_number,
                location_country,
                location_region
            FROM individuals
            WHERE id = ?
            """,
            (individual_id,),
        ).fetchone()

        assert snapshot is not None
        assert snapshot["manufacturer"] == "Fender"
        assert snapshot["model"] == "Stratocaster"
        assert snapshot["finish"] == "Natural"
        assert snapshot["year"] == "1974"
        assert snapshot["serial_number"] == "524436"
        assert snapshot["location_country"] == "US"
        assert snapshot["location_region"] == "CA"

    second = (
        repository
        .migrate_legacy_observations_to_claims()
    )

    assert second["claims_created"] == 0
    assert second["listing_items_created"] == 0
    assert second["snapshots_rebuilt"] == 1

    with repository.connect() as con:
        assert int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM claims
                WHERE observation_id = ?
                  AND claim_type = 'listing'
                """,
                (observation_id,),
            ).fetchone()[0]
        ) == 1

        assert int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM claim_listing_items
                WHERE claim_id = ?
                """,
                (claim_id,),
            ).fetchone()[0]
        ) == 16
