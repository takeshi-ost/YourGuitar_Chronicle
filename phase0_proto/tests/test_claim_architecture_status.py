from __future__ import annotations

from pathlib import Path

from ygc.db.repository import Repository


def test_claim_architecture_status_and_migration(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    empty = repository.claim_architecture_status()
    assert empty["ready"] is True
    assert empty["migration_required"] is False

    now = "2026-09-25T00:00:00+00:00"
    with repository.connect() as con:
        individual = con.execute(
            """
            INSERT INTO individuals (
                manufacturer,
                model,
                serial_number,
                normalized_manufacturer,
                normalized_model,
                normalized_serial,
                created_at,
                updated_at
            )
            VALUES (
                'Fender',
                'Telecaster',
                'ABC123',
                'fender',
                'telecaster',
                'ABC123',
                ?,
                ?
            )
            """,
            (now, now),
        )
        individual_id = int(
            individual.lastrowid
        )

        con.execute(
            """
            INSERT INTO observations (
                individual_id,
                manufacturer,
                model,
                serial_number,
                owner_name,
                owner_type,
                source_site,
                source_url,
                source_listing_id,
                observed_at,
                listing_date,
                title,
                created_at
            )
            VALUES (
                ?,
                'Fender',
                'Telecaster',
                'ABC123',
                'Vintage Shop',
                'shop',
                'reverb',
                'https://reverb.example/item/1',
                '1',
                ?,
                '2026-09-20',
                'Fender Telecaster',
                ?
            )
            """,
            (
                individual_id,
                now,
                now,
            ),
        )

    before = repository.claim_architecture_status()
    assert before["ready"] is False
    assert before["migration_required"] is True
    assert before["unmigrated_listing_observations"] == 1
    assert before["claimless_individuals"] == 1

    result = repository.migrate_legacy_observations_to_claims()
    assert result["claims_created"] == 1
    assert result["snapshots_rebuilt"] == 1

    after = repository.claim_architecture_status()
    assert after["ready"] is True
    assert after["migration_required"] is False
    assert after["unmigrated_listing_observations"] == 0
    assert after["claimless_individuals"] == 0
    assert after["pending_shells"] == 0
