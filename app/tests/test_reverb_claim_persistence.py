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
    assert observation["owner_name"] == "Vintage Shop"
    assert observation["location_country"] == "US"

    claims = repository.list_claims(
        individual_id
    )
    assert len(claims) == 1
    assert claims[0]["claim_type"] == "listing"
    assert claims[0]["observed_manufacturer"] == "Fender"
    assert claims[0]["observed_serial_number"] == "524436"
    assert claims[0]["observed_owner_name"] == "Vintage Shop"
    assert claims[0]["location_region"] == "CA"
    with repository.connect() as con:
        author = con.execute(
            "SELECT display_name, account_type FROM users WHERE id = ?",
            (claims[0]["author_user_id"],),
        ).fetchone()
    assert tuple(author) == ("Automation", "source")
    with pytest.raises(ValueError, match="through Claims"):
        repository.update_individual_metadata(individual_id, finish="Red")


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
    assert [row["claim_type"] for row in claims].count("listing") == 1
    acquire = [row for row in claims if row["claim_type"] == "ownership"]
    assert len(acquire) == 1
    assert acquire[0]["ownership_kind"] == "acquire"
    assert acquire[0]["verification_status"] == "positive"


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
                "SELECT COUNT(*) FROM claims WHERE claim_type = 'listing'"
            ).fetchone()[0]
        ) == 1


def test_relisted_guitar_owned_by_user_waits_for_owner_confirmation(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()
    first = repository.persist_reverb_listing_claim(
        _claim_data(listing_id="1"), _provenance(listing_id="1"),
    )
    user_id = repository.create_user("Current owner")
    repository.create_ownership_claim(
        user_id, first["individual_id"], ownership_kind="acquire",
        occurred_at="2026-09-25",
    )
    second = repository.persist_reverb_listing_claim(
        _claim_data(listing_id="2", region="NY"),
        _provenance(listing_id="2"),
    )
    assert second["verification_status"] == "unverified"
    assert repository.claim_architecture_status()['ready'] is True
    assert repository.migrate_legacy_observations_to_claims()['claims_created'] == 0
    with repository.connect() as con:
        individual = con.execute(
            "SELECT current_owner_user_id, location_region FROM individuals WHERE id = ?",
            (first["individual_id"],),
        ).fetchone()
    assert int(individual["current_owner_user_id"]) == user_id
    assert individual["location_region"] is None
    repository.init_db()
    with repository.connect() as con:
        status = con.execute(
            "SELECT verification_status FROM claims WHERE id = ?",
            (second["claim_id"],),
        ).fetchone()[0]
    assert status == "unverified"
    assert repository.set_claim_response(second["claim_id"], user_id, "positive")
    with repository.connect() as con:
        approved = con.execute(
            "SELECT current_owner_name, current_owner_user_id, location_region "
            "FROM individuals WHERE id = ?", (first["individual_id"],),
        ).fetchone()
    assert approved["current_owner_name"] == "Vintage Shop"
    assert approved["current_owner_user_id"] is None
    assert approved["location_region"] == "NY"


def test_relist_acquires_are_ready_for_crawl_and_not_migrated_into_listings(tmp_path: Path):
    repository = Repository(tmp_path / 'relist-readiness.db')
    repository.init_db()
    first = repository.persist_reverb_listing_claim(
        _claim_data(listing_id='1'), _provenance(listing_id='1'))
    for listing_id in ('2', '3'):
        relisted = repository.persist_reverb_listing_claim(
            _claim_data(listing_id=listing_id), _provenance(listing_id=listing_id))
        assert relisted['individual_id'] == first['individual_id']
        assert relisted['claim_id'] is not None

    status = repository.claim_architecture_status()
    assert status['ready'] is True
    assert status['migration_required'] is False
    assert status['unmigrated_listing_observations'] == 0
    assert repository.migrate_legacy_observations_to_claims()['claims_created'] == 0
    with repository.connect() as con:
        claims = con.execute(
            "SELECT claim_type, ownership_kind FROM claims WHERE individual_id=? ORDER BY id",
            (first['individual_id'],),
        ).fetchall()
    assert [(c['claim_type'], c['ownership_kind']) for c in claims] == [
        ('listing', None), ('ownership', 'acquire'), ('ownership', 'acquire'),
    ]
    assert repository.audit_observation_migration()['individuals_mismatched'] == 0


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
