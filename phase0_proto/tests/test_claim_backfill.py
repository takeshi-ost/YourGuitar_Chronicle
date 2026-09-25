from __future__ import annotations

from pathlib import Path

from ygc.db.repository import Repository


def test_listing_claim_backfill_supplements_claim_only(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    claim_data = {
        "manufacturer": "Fender",
        "model": "Stratocaster",
        "finish": "Natural",
        "year": "1974",
        "serial_number": "524436",
        "owner_name": "Vintage Shop",
        "owner_type": "shop",
        "seller": "Vintage Shop",
        "location_country": "US",
        "location_region": "CA",
        "listing_title": "1974 Fender Stratocaster",
        "listing_date": "2026-09-20T00:00:00Z",
        "source_site": "reverb",
        "source_url": "https://reverb.example/item/1",
        "source_listing_id": "1",
        "image_url": "https://reverb.example/image.jpg",
    }
    provenance = {
        "source_site": "reverb",
        "source_url": "https://reverb.example/item/1",
        "source_listing_id": "1",
        "observed_at": "2026-09-25T00:00:00+00:00",
        "listing_date": "2026-09-20T00:00:00Z",
        "title": "1974 Fender Stratocaster",
        "raw_text": "Serial 524436",
        "serial_confidence": 0.99,
        "extraction_version": "test",
        "image_url": "https://reverb.example/image.jpg",
        "event_type": "listing",
        "created_at": "2026-09-25T00:00:00+00:00",
    }

    result = repository.persist_reverb_listing_claim(
        claim_data,
        provenance,
    )
    claim_id = int(result["claim_id"])
    individual_id = int(result["individual_id"])
    observation_id = int(result["observation_id"])

    with repository.connect() as con:
        con.execute(
            """
            DELETE FROM claim_listing_items
            WHERE claim_id = ?
              AND field_name IN (
                    'finish',
                    'location_country'
              )
            """,
            (claim_id,),
        )
        con.execute(
            """
            UPDATE observations
            SET finish = 'WRONG',
                location_country = 'ZZ'
            WHERE id = ?
            """,
            (observation_id,),
        )

    rows = repository.list_listing_claims_for_backfill()
    assert [int(row["claim_id"]) for row in rows] == [
        claim_id
    ]

    changed = repository.supplement_listing_claim(
        claim_id,
        {
            "finish": "Olympic White",
            "location_country": "JP",
        },
    )
    assert changed is True

    with repository.connect() as con:
        observation = con.execute(
            """
            SELECT finish, location_country
            FROM observations
            WHERE id = ?
            """,
            (observation_id,),
        ).fetchone()
        individual = con.execute(
            """
            SELECT finish, location_country
            FROM individuals
            WHERE id = ?
            """,
            (individual_id,),
        ).fetchone()

    assert observation is not None
    assert observation["finish"] == "WRONG"
    assert observation["location_country"] == "ZZ"

    assert individual is not None
    assert individual["finish"] == "Olympic White"
    assert individual["location_country"] == "JP"

    assert (
        repository.supplement_listing_claim(
            claim_id,
            {
                "finish": "Should Not Replace",
                "location_country": "XX",
            },
        )
        is False
    )
