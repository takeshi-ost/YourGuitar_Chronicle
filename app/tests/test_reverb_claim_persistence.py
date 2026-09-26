from __future__ import annotations

from pathlib import Path

import pytest

from ygc.db.repository import Repository


def _claim_data(
    *,
    listing_id: str,
    region: str = "CA",
    serial: str | None = "524436",
) -> dict:
    return {
        "manufacturer": "Fender",
        "model": "Stratocaster",
        "finish": "Natural",
        "year": "1974",
        "serial_number": serial,
        "owner_name": "Vintage Shop",
        "owner_type": "shop",
        "seller": "Vintage Shop",
        "location_country": "US",
        "location_region": region,
        "listing_title": "1974 Fender Stratocaster",
        "listing_date": "2026-09-20T00:00:00Z",
        "source_site": "reverb",
        "source_url": f"https://reverb.example/item/{listing_id}",
        "source_listing_id": listing_id,
        "image_url": "https://reverb.example/image.jpg",
        "vintage_status": "vintage",
        "vintage_reason": "structured_year:1974",
        "estimated_year": 1974,
        "serial_confidence": 0.99,
        "extraction_version": "test",
    }


def _provenance(
    *,
    listing_id: str,
) -> dict:
    return {
        "individual_id": None,
        "event_type": "listing",
        "source_site": "reverb",
        "source_url": f"https://reverb.example/item/{listing_id}",
        "source_listing_id": listing_id,
        "observed_at": "2026-09-25T00:00:00+00:00",
        "listing_date": "2026-09-20T00:00:00Z",
        "title": "1974 Fender Stratocaster",
        "raw_text": "Serial number 524436.",
        "serial_confidence": 0.99,
        "extraction_version": "test",
        "image_url": "https://reverb.example/image.jpg",
        "created_at": "2026-09-25T00:00:00+00:00",
    }


def test_reverb_listing_creates_claim_and_snapshot(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    result = repository.persist_reverb_listing_claim(
        _claim_data(listing_id="1"),
        _provenance(listing_id="1"),
    )

    assert result["created"] is True
    assert result["individual_id"] is not None
    assert result["claim_id"] is not None

    individual_id = int(
        result["individual_id"]
    )
    observation_id = int(
        result["observation_id"]
    )

    with repository.connect() as con:
        individual = con.execute(
            """
            SELECT *
            FROM individuals
            WHERE id = ?
            """,
            (individual_id,),
        ).fetchone()
        observation = con.execute(
            """
            SELECT *
            FROM observations
            WHERE id = ?
            """,
            (observation_id,),
        ).fetchone()

    assert individual is not None
    assert individual["manufacturer"] == "Fender"
    assert individual["model"] == "Stratocaster"
    assert individual["finish"] == "Natural"
    assert individual["year"] == "1974"
    assert individual["serial_number"] == "524436"
    assert individual["location_country"] == "US"
    assert individual["location_region"] == "CA"

    assert observation is not None
    assert observation["source_site"] == "reverb"
    assert observation["source_listing_id"] == "1"
    assert observation["manufacturer"] is None
    assert observation["model"] is None
    assert observation["finish"] is None
    assert observation["year"] is None
    assert observation["serial_number"] is None
    assert observation["owner_name"] is None
    assert observation["location_country"] is None

    claims = repository.list_claims(
        individual_id
    )
    assert len(claims) == 1
    assert claims[0]["claim_type"] == "listing"
    assert claims[0]["observed_manufacturer"] == "Fender"
    assert claims[0]["observed_serial_number"] == "524436"
    assert claims[0]["observed_owner_name"] == "Vintage Shop"
    assert claims[0]["location_region"] == "CA"


def test_second_reverb_listing_reuses_individual_and_rebuilds_location(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    first = repository.persist_reverb_listing_claim(
        _claim_data(
            listing_id="1",
            region="CA",
        ),
        _provenance(listing_id="1"),
    )

    second_claim = _claim_data(
        listing_id="2",
        region="NY",
    )
    second_claim["listing_date"] = (
        "2026-09-21T00:00:00Z"
    )
    second = repository.persist_reverb_listing_claim(
        second_claim,
        _provenance(listing_id="2"),
    )

    assert (
        second["individual_id"]
        == first["individual_id"]
    )

    with repository.connect() as con:
        row = con.execute(
            """
            SELECT location_region
            FROM individuals
            WHERE id = ?
            """,
            (first["individual_id"],),
        ).fetchone()

    assert row is not None
    assert row["location_region"] == "NY"

    claims = repository.list_claims(
        int(first["individual_id"])
    )
    assert len(
        [
            row
            for row in claims
            if row["claim_type"] == "listing"
        ]
    ) == 2


def test_reverb_external_duplicate_does_not_create_second_claim(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    first = repository.persist_reverb_listing_claim(
        _claim_data(listing_id="1"),
        _provenance(listing_id="1"),
    )
    second = repository.persist_reverb_listing_claim(
        _claim_data(listing_id="1"),
        _provenance(listing_id="1"),
    )

    assert first["created"] is True
    assert second["created"] is False

    with repository.connect() as con:
        assert int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM observations
                WHERE source_site = 'reverb'
                  AND source_listing_id = '1'
                """
            ).fetchone()[0]
        ) == 1
        assert int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM claims
                WHERE claim_type = 'listing'
                """
            ).fetchone()[0]
        ) == 1


def test_reverb_listing_without_identity_stores_provenance_only(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    result = repository.persist_reverb_listing_claim(
        _claim_data(
            listing_id="no-serial",
            serial=None,
        ),
        _provenance(
            listing_id="no-serial"
        ),
    )

    assert result["created"] is True
    assert result["individual_id"] is None
    assert result["claim_id"] is None

    with repository.connect() as con:
        assert int(
            con.execute(
                "SELECT COUNT(*) FROM individuals"
            ).fetchone()[0]
        ) == 0
        assert int(
            con.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
        ) == 0
        assert int(
            con.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
        ) == 1


def test_reverb_refuses_unmigrated_matching_individual(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    now = "2026-09-25T00:00:00+00:00"
    with repository.connect() as con:
        con.execute(
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

    with pytest.raises(
        ValueError,
        match="Run legacy Observation migration",
    ):
        repository.persist_reverb_listing_claim(
            _claim_data(listing_id="1"),
            _provenance(listing_id="1"),
        )

    with repository.connect() as con:
        assert int(
            con.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
        ) == 0
        assert int(
            con.execute(
                "SELECT COUNT(*) FROM claims"
            ).fetchone()[0]
        ) == 0
