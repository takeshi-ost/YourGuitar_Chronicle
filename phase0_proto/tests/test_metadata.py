from __future__ import annotations

import sqlite3

from ygc.db.repository import (
    Repository,
)
from ygc.matching.individual_matcher import (
    match_or_create,
)


def test_init_db_migrates_existing_metadata_columns(
    tmp_path,
):
    db_path = (
        tmp_path
        / "chronicle.db"
    )

    with sqlite3.connect(
        db_path
    ) as con:
        con.executescript(
            """
            CREATE TABLE individuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manufacturer TEXT NOT NULL,
                model TEXT,
                serial_number TEXT,
                normalized_manufacturer TEXT NOT NULL,
                normalized_model TEXT,
                normalized_serial TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(
                    normalized_manufacturer,
                    normalized_model,
                    normalized_serial
                )
            );

            CREATE TABLE observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                individual_id INTEGER,
                manufacturer TEXT,
                model TEXT,
                serial_number TEXT,
                seller TEXT,
                source_site TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_listing_id TEXT,
                observed_at TEXT NOT NULL,
                listing_date TEXT,
                title TEXT,
                raw_text TEXT,
                serial_confidence REAL,
                extraction_version TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(
                    source_site,
                    source_listing_id
                )
            );
            """
        )

    repository = Repository(
        db_path
    )

    repository.init_db()

    with repository.connect() as con:
        individual_columns = {
            row["name"]
            for row
            in con.execute(
                "PRAGMA table_info(individuals)"
            )
        }

        observation_columns = {
            row["name"]
            for row
            in con.execute(
                "PRAGMA table_info(observations)"
            )
        }

    assert (
        "finish"
        in individual_columns
    )
    assert (
        "year"
        in individual_columns
    )
    assert (
        "finish"
        in observation_columns
    )
    assert (
        "year"
        in observation_columns
    )
    assert (
        "image_url"
        in observation_columns
    )
    assert (
        "owner_name"
        in observation_columns
    )
    assert (
        "owner_type"
        in observation_columns
    )
    assert (
        "location_country"
        in observation_columns
    )
    assert (
        "location_region"
        in observation_columns
    )
    assert (
        "location_source"
        in observation_columns
    )


def test_metadata_flows_to_individual_and_observation(
    tmp_path,
):
    repository = Repository(
        tmp_path
        / "chronicle.db"
    )
    repository.init_db()

    individual_id = (
        match_or_create(
            repository,
            "Fender",
            "Jazzmaster",
            "L13242",
            finish="Sunburst",
            year="1963",
        )
    )

    observation = {
        "individual_id": (
            individual_id
        ),
        "manufacturer": "Fender",
        "model": "Jazzmaster",
        "finish": "Sunburst",
        "year": "1963",
        "serial_number": "L13242",
        "owner_name": "Example Shop",
        "owner_type": "shop",
        "location_country": "NL",
        "location_region": "NH",
        "location_source": "reverb_listing",
        "seller": "Example Shop",
        "source_site": "reverb",
        "source_url": (
            "https://example.invalid/1"
        ),
        "image_url": (
            "https://images.example.invalid/1.jpg"
        ),
        "source_listing_id": "1",
        "observed_at": (
            "2026-09-23T00:00:00+00:00"
        ),
        "listing_date": None,
        "title": "1963 Jazzmaster",
        "raw_text": "Serial L13242",
        "serial_confidence": 0.95,
        "extraction_version": (
            "serial-v3"
        ),
        "created_at": (
            "2026-09-23T00:00:00+00:00"
        ),
    }

    repository.upsert_observation(
        observation
    )

    individual, observations = (
        repository.get_individual(
            individual_id
        )
    )

    assert (
        individual["finish"]
        == "Sunburst"
    )
    assert (
        individual["year"]
        == "1963"
    )
    assert (
        observations[0]["finish"]
        == "Sunburst"
    )
    assert (
        observations[0]["year"]
        == "1963"
    )
    assert (
        observations[0]["image_url"]
        == "https://images.example.invalid/1.jpg"
    )
    assert (
        observations[0]["owner_name"]
        == "Example Shop"
    )
    assert (
        observations[0]["owner_type"]
        == "shop"
    )
    assert (
        observations[0]["location_country"]
        == "NL"
    )
    assert (
        observations[0]["location_region"]
        == "NH"
    )
    assert (
        observations[0]["location_source"]
        == "reverb_listing"
    )


def test_statistics_use_latest_observation_location(
    tmp_path,
):
    repository = Repository(
        tmp_path
        / "chronicle.db"
    )
    repository.init_db()

    individual_id = (
        match_or_create(
            repository,
            "Fender",
            "Stratocaster",
            "S12345",
            finish="Sunburst",
            year="1965",
        )
    )

    base = {
        "individual_id": individual_id,
        "manufacturer": "Fender",
        "model": "Stratocaster",
        "finish": "Sunburst",
        "year": "1965",
        "serial_number": "S12345",
        "owner_name": "Example Shop",
        "owner_type": "shop",
        "location_source": "reverb_listing",
        "seller": "Example Shop",
        "source_site": "reverb",
        "source_url": (
            "https://example.invalid/"
        ),
        "image_url": None,
        "raw_text": "",
        "serial_confidence": 0.95,
        "extraction_version": "serial-v3",
        "created_at": (
            "2026-09-23T00:00:00+00:00"
        ),
    }

    first = {
        **base,
        "source_listing_id": "1",
        "observed_at": (
            "2020-01-01T00:00:00+00:00"
        ),
        "listing_date": (
            "2020-01-01T00:00:00+00:00"
        ),
        "title": "First listing",
        "location_country": "US",
        "location_region": "CA",
    }

    latest = {
        **base,
        "source_listing_id": "2",
        "observed_at": (
            "2026-01-01T00:00:00+00:00"
        ),
        "listing_date": (
            "2026-01-01T00:00:00+00:00"
        ),
        "title": "Latest listing",
        "location_country": "JP",
        "location_region": "13",
    }

    repository.upsert_observation(first)
    repository.upsert_observation(latest)

    stats = repository.statistics()

    assert stats["summary"]["individuals"] == 1
    assert stats["summary"]["makers"] == 1
    assert stats["summary"]["models"] == 1
    assert stats["summary"]["finishes"] == 1
    assert (
        stats["summary"][
            "located_individuals"
        ]
        == 1
    )
    assert stats["current_countries"] == [
        {
            "label": "JP",
            "count": 1,
        }
    ]


def test_user_account_and_guitar_ownership_link(
    tmp_path,
):
    repository = Repository(
        tmp_path
        / "chronicle.db"
    )
    repository.init_db()

    individual_id = (
        match_or_create(
            repository,
            "Fender",
            "Telecaster",
            "123456",
            finish="Blonde",
            year="1968",
        )
    )

    user_id = repository.create_user()

    updated = repository.update_user(
        user_id,
        display_name="Takeshi",
        account_type="user",
        location_country="JP",
        location_region="Kyoto",
    )

    assert updated is True

    linked = repository.link_user_guitar(
        user_id,
        individual_id,
        ownership_status="current_owner",
    )

    assert linked is True

    user, guitars = repository.get_user(
        user_id
    )

    assert user is not None
    assert user["display_name"] == "Takeshi"
    assert user["account_type"] == "user"
    assert user["location_country"] == "JP"
    assert user["location_region"] == "Kyoto"

    assert len(guitars) == 1
    assert (
        guitars[0]["individual_id"]
        == individual_id
    )
    assert (
        guitars[0]["ownership_status"]
        == "current_owner"
    )
    assert (
        guitars[0]["manufacturer"]
        == "Fender"
    )

    users = repository.list_users()

    assert len(users) == 1
    assert (
        users[0]["current_guitar_count"]
        == 1
    )


def test_user_owned_guitar_order_can_be_rearranged(
    tmp_path,
):
    repository = Repository(
        tmp_path
        / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user()

    first_id = match_or_create(
        repository,
        "Fender",
        "Stratocaster",
        "S10001",
    )
    second_id = match_or_create(
        repository,
        "Fender",
        "Jazzmaster",
        "S10002",
    )

    assert repository.link_user_guitar(
        user_id,
        first_id,
    )
    assert repository.link_user_guitar(
        user_id,
        second_id,
    )

    _user, guitars = repository.get_user(
        user_id
    )
    assert [
        row["individual_id"]
        for row
        in guitars
    ] == [
        first_id,
        second_id,
    ]

    assert repository.reorder_user_guitars(
        user_id,
        [
            second_id,
            first_id,
        ],
    )

    _user, guitars = repository.get_user(
        user_id
    )
    assert [
        row["individual_id"]
        for row
        in guitars
    ] == [
        second_id,
        first_id,
    ]


def test_owner_change_claim_response_and_vote(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    owner_id = repository.create_user(
        "Owner"
    )
    other_id = repository.create_user(
        "Other User"
    )
    individual_id = match_or_create(
        repository,
        "Fender",
        "Telecaster",
        "S20001",
    )

    observation_id, claim_id = (
        repository.create_owner_change_claim(
            owner_id,
            individual_id,
            acquired_at="2026-09-25",
            previous_owner_text="Shop A",
            body="Purchased in person.",
        )
    )

    assert observation_id > 0
    assert claim_id > 0

    user, guitars = repository.get_user(
        owner_id
    )
    assert user is not None
    assert guitars[0]["individual_id"] == (
        individual_id
    )
    assert guitars[0]["ownership_status"] == (
        "current_owner"
    )

    claims = repository.list_claims(
        individual_id
    )
    assert len(claims) == 1
    assert claims[0]["claim_type"] == (
        "owner_change"
    )
    assert claims[0]["author_user_id"] == (
        owner_id
    )

    _other_observation_id, other_claim_id = (
        repository.create_owner_change_claim(
            other_id,
            individual_id,
            acquired_at="2026-09-26",
            body="Other ownership Claim.",
        )
    )

    assert repository.set_claim_response(
        other_claim_id,
        owner_id,
        "endorse",
    )
    assert repository.set_claim_vote(
        claim_id,
        other_id,
        "good",
    )

    claims = repository.list_claims(
        individual_id,
        viewer_user_id=owner_id,
    )
    owner_claim = next(
        row
        for row in claims
        if row["id"] == claim_id
    )
    other_claim = next(
        row
        for row in claims
        if row["id"] == other_claim_id
    )
    assert owner_claim["good_count"] == 1
    assert owner_claim["bad_count"] == 0
    assert other_claim["viewer_stance"] == (
        "endorse"
    )


def test_listing_observation_is_backfilled_as_claim(
    tmp_path,
):
    db_path = tmp_path / "chronicle.db"
    repository = Repository(
        db_path
    )
    repository.init_db()

    individual_id = match_or_create(
        repository,
        "Fender",
        "Jazzmaster",
        "S30001",
    )

    observation_id, created = (
        repository.upsert_observation(
            {
                "individual_id": individual_id,
                "manufacturer": "Fender",
                "model": "Jazzmaster",
                "finish": "Sunburst",
                "year": "1965",
                "serial_number": "S30001",
                "owner_name": "Example Shop",
                "owner_type": "shop",
                "owner_profile_url": None,
                "location_country": "US",
                "location_region": "CA",
                "location_source": "reverb_listing",
                "seller": "Example Shop",
                "source_site": "reverb",
                "source_url": "https://example.com/listing/1",
                "image_url": None,
                "source_listing_id": "listing-1",
                "observed_at": "2026-09-25T00:00:00+00:00",
                "listing_date": "2026-09-24",
                "title": "1965 Fender Jazzmaster",
                "raw_text": None,
                "serial_confidence": 1.0,
                "extraction_version": "test",
                "created_at": "2026-09-25T00:00:00+00:00",
            }
        )
    )

    assert created
    assert observation_id > 0

    repository.init_db()

    claims = repository.list_claims(
        individual_id
    )

    listing_claims = [
        row
        for row
        in claims
        if row["claim_type"]
           == "listing"
    ]

    assert len(listing_claims) == 1
    claim = listing_claims[0]
    assert claim["observation_id"] == (
        observation_id
    )
    assert claim["author_name"] == "Reverb"
    assert claim["listing_title"] == (
        "1965 Fender Jazzmaster"
    )
    assert claim["source_url"] == (
        "https://example.com/listing/1"
    )


def test_new_guitar_registration_creates_initial_listing_claim(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Collector"
    )

    (
        individual_id,
        observation_id,
        claim_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster Thinline",
        finish="Natural",
        year="1976",
        serial_number="524436",
        occurred_at="2026-09-25",
        body="Initial user registration.",
    )

    assert individual_id > 0
    assert observation_id > 0
    assert claim_id > 0

    individual, observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert individual is not None
    assert individual["manufacturer"] == (
        "Fender"
    )
    assert individual["serial_number"] == (
        "524436"
    )
    assert len(observations) == 1
    assert observations[0]["event_type"] == (
        "listing"
    )
    assert observations[0]["owner_name"] == (
        "Collector"
    )
    assert observations[0]["owner_type"] == (
        "user"
    )

    claims = repository.list_claims(
        individual_id,
        viewer_user_id=user_id,
    )
    assert len(claims) == 1
    assert claims[0]["id"] == claim_id
    assert claims[0]["claim_type"] == (
        "listing"
    )
    assert claims[0]["author_user_id"] == (
        user_id
    )
    assert claims[0]["observed_owner_name"] == (
        "Collector"
    )
    assert claims[0]["body"] == (
        "Initial user registration."
    )

    _user, guitars = repository.get_user(
        user_id
    )
    assert len(guitars) == 1
    assert guitars[0]["individual_id"] == (
        individual_id
    )
    assert guitars[0]["ownership_status"] == (
        "current_owner"
    )


def test_new_guitar_registration_rejects_duplicate_identity(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Collector"
    )

    repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="ABC123",
    )

    try:
        repository.create_initial_listing_claim(
            user_id,
            manufacturer="Fender",
            model="Telecaster",
            serial_number="ABC123",
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError(
            "duplicate registration should fail"
        )
