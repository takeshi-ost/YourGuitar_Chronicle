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
    assert (
        "representative_media_asset_id"
        in individual_columns
    )

    with repository.connect() as con:
        tables = {
            row["name"]
            for row
            in con.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

    assert "media_assets" in tables
    assert "claim_evidence" in tables


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


def test_statistics_use_individual_snapshot_location(
    tmp_path,
):
    repository = Repository(
        tmp_path
        / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Collector"
    )
    assert repository.update_user(
        user_id,
        display_name="Collector",
        account_type="user",
        location_country="JP",
        location_region="Kyoto",
    )

    (
        individual_id,
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Stratocaster",
        finish="Sunburst",
        year="1965",
        serial_number="S12345",
        media_storage_path="media/stats.jpg",
    )

    with repository.connect() as con:
        con.execute(
            """
            UPDATE observations
            SET location_country = 'US',
                location_region = 'CA'
            WHERE individual_id = ?
            """,
            (individual_id,),
        )

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

    initial_owner_id = repository.create_user(
        "Initial Owner"
    )
    owner_id = repository.create_user(
        "Owner"
    )
    other_id = repository.create_user(
        "Other User"
    )
    (
        individual_id,
        _listing_observation_id,
        _listing_claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        initial_owner_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="S20001",
        media_storage_path="media/s20001.jpg",
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
    owner_claim = next(
        row
        for row in claims
        if row["id"] == claim_id
    )
    assert owner_claim["claim_type"] == (
        "owner_change"
    )
    assert owner_claim["author_user_id"] == (
        owner_id
    )

    individual, _observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert individual is not None
    assert individual["current_owner_name"] == (
        "Owner"
    )
    assert individual["current_owner_type"] == (
        "user"
    )
    assert int(
        individual["current_owner_user_id"]
    ) == owner_id

    _other_observation_id, other_claim_id = (
        repository.create_owner_change_claim(
            other_id,
            individual_id,
            acquired_at="2026-09-26",
            body="Other ownership Claim.",
        )
    )

    individual, _observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert individual is not None
    assert individual["current_owner_name"] == (
        "Other User"
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

    repository.migrate_legacy_observations_to_claims()

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
        media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster Thinline",
        finish="Natural",
        year="1976",
        serial_number="524436",
        occurred_at="2026-09-25",
        body="Initial user registration.",
        media_storage_path="media/test.jpg",
        media_original_filename="guitar.jpg",
        media_mime_type="image/jpeg",
    )

    assert individual_id > 0
    assert observation_id > 0
    assert claim_id > 0
    assert media_asset_id > 0

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
    assert (
        individual[
            "representative_media_asset_id"
        ]
        == media_asset_id
    )
    assert len(observations) == 1
    assert observations[0]["event_type"] == (
        "listing"
    )
    assert observations[0]["source_site"] == (
        "user"
    )
    assert observations[0]["manufacturer"] is None
    assert observations[0]["model"] is None
    assert observations[0]["serial_number"] is None
    assert observations[0]["owner_name"] is None
    assert observations[0]["location_country"] is None

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
    assert claims[0]["observed_manufacturer"] == (
        "Fender"
    )
    assert claims[0]["observed_model"] == (
        "Telecaster Thinline"
    )
    assert claims[0]["observed_finish"] == (
        "Natural"
    )
    assert claims[0]["observed_year"] == (
        "1976"
    )
    assert claims[0]["observed_serial_number"] == (
        "524436"
    )
    assert claims[0]["body"] == (
        "Initial user registration."
    )
    assert claims[0]["evidence_media_id"] == (
        media_asset_id
    )

    media = repository.get_media_asset(
        media_asset_id
    )
    assert media is not None
    assert media["individual_id"] == (
        individual_id
    )
    assert media["uploader_user_id"] == (
        user_id
    )
    assert media["storage_path"] == (
        "media/test.jpg"
    )
    assert media["mime_type"] == (
        "image/jpeg"
    )

    with repository.connect() as con:
        evidence = con.execute(
            """
            SELECT *
            FROM claim_evidence
            WHERE claim_id = ?
              AND media_asset_id = ?
            """,
            (
                claim_id,
                media_asset_id,
            ),
        ).fetchone()
    assert evidence is not None

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
        media_storage_path="media/first.jpg",
    )

    try:
        repository.create_initial_listing_claim(
            user_id,
            manufacturer="Fender",
            model="Telecaster",
            serial_number="ABC123",
            media_storage_path="media/second.jpg",
        )
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError(
            "duplicate registration should fail"
        )



def test_new_guitar_registration_requires_representative_image(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Collector"
    )

    try:
        repository.create_initial_listing_claim(
            user_id,
            manufacturer="Fender",
            model="Jazzmaster",
            serial_number="IMG001",
            media_storage_path="",
        )
    except ValueError as exc:
        assert (
            "representative image is required"
            in str(exc)
        )
    else:
        raise AssertionError(
            "representative image should be required"
        )



def test_user_owner_name_tracks_account_display_name(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Old Name"
    )

    (
        individual_id,
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="NAME001",
        media_storage_path="media/name001.jpg",
    )

    assert repository.update_user(
        user_id,
        display_name="New Name",
        account_type="user",
        location_country=None,
        location_region=None,
    )

    _individual, observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert observations[0]["owner_name"] is None
    assert observations[0]["actor_user_id"] == (
        user_id
    )

    claims = repository.list_claims(
        individual_id
    )
    assert claims[0]["author_name"] == (
        "New Name"
    )
    assert claims[0]["observed_owner_name"] == (
        "New Name"
    )

    individual, _observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert individual is not None
    assert individual["current_owner_name"] == (
        "New Name"
    )



def test_specification_claims_stack_by_field_and_date(
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
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster Thinline",
        serial_number="SPEC001",
        media_storage_path="media/spec001.jpg",
    )

    first_nut = (
        repository.create_specification_claim(
            user_id,
            individual_id,
            field_name="nut",
            value_text="Original",
            occurred_at="1976-01-01",
            body="Factory state.",
        )
    )
    fret_claim = (
        repository.create_specification_claim(
            user_id,
            individual_id,
            field_name="frets",
            value_text="Leveled",
            occurred_at="2024-06-01",
            body="Fret dressing completed.",
        )
    )
    latest_nut = (
        repository.create_specification_claim(
            user_id,
            individual_id,
            field_name="nut",
            value_text="Bone",
            occurred_at="2025-05-01",
            body="Nut replaced.",
        )
    )

    claims = repository.list_claims(
        individual_id
    )
    specifications = [
        row
        for row in claims
        if row["claim_type"]
           == "specification"
    ]

    assert [
        row["id"]
        for row in specifications
    ] == [
        first_nut,
        fret_claim,
        latest_nut,
    ]

    current = (
        repository.list_current_specifications(
            individual_id
        )
    )
    by_field = {
        row["field_name"]: row
        for row in current
    }

    assert (
        by_field["nut"]["value_text"]
        == "Bone"
    )
    assert (
        by_field["nut"]["id"]
        == latest_nut
    )
    assert (
        by_field["frets"]["value_text"]
        == "Leveled"
    )
    assert (
        by_field["frets"]["id"]
        == fret_claim
    )


def test_specification_claim_requires_field_and_value(
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
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="SPEC002",
        media_storage_path="media/spec002.jpg",
    )

    for field_name, value_text in (
        ("", "Bone"),
        ("nut", ""),
    ):
        try:
            repository.create_specification_claim(
                user_id,
                individual_id,
                field_name=field_name,
                value_text=value_text,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "field and value should be required"
            )



def test_grouped_specification_repair_claim_updates_multiple_fields(
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
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster Thinline",
        serial_number="SPEC003",
        media_storage_path="media/spec003.jpg",
    )

    claim_id = (
        repository.create_specification_claim_group(
            user_id,
            individual_id,
            specification_kind="repair",
            items=[
                {
                    "field_name": "nut",
                    "value_text": "Bone",
                },
                {
                    "field_name": "frets",
                    "value_text": "Leveled",
                },
                {
                    "field_name": "pickguard",
                    "value_text": "New 3-ply white",
                },
            ],
            occurred_at="2025-05-01",
            body="Repair completed.",
        )
    )

    claims = repository.list_claims(
        individual_id
    )
    claim = next(
        row
        for row in claims
        if row["id"] == claim_id
    )
    assert (
        claim["specification_kind"]
        == "repair"
    )
    assert claim["field_name"] is None
    assert claim["value_text"] is None

    items = repository.list_specification_items(
        individual_id
    )
    claim_items = [
        row
        for row in items
        if row["claim_id"] == claim_id
    ]
    assert [
        (
            row["field_name"],
            row["value_text"],
        )
        for row in claim_items
    ] == [
        ("nut", "Bone"),
        ("frets", "Leveled"),
        ("pickguard", "New 3-ply white"),
    ]

    current = repository.list_current_specifications(
        individual_id
    )
    by_field = {
        row["field_name"]: row
        for row in current
    }
    assert by_field["nut"]["value_text"] == "Bone"
    assert by_field["frets"]["value_text"] == "Leveled"
    assert (
        by_field["pickguard"]["value_text"]
        == "New 3-ply white"
    )
    assert (
        by_field["nut"]["specification_kind"]
        == "repair"
    )


def test_grouped_specification_claim_rejects_duplicate_items(
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
        _observation_id,
        _claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="SPEC004",
        media_storage_path="media/spec004.jpg",
    )

    try:
        repository.create_specification_claim_group(
            user_id,
            individual_id,
            specification_kind="specification",
            items=[
                {
                    "field_name": "nut",
                    "value_text": "Bone",
                },
                {
                    "field_name": "nut",
                    "value_text": "Plastic",
                },
            ],
        )
    except ValueError as exc:
        assert "only once" in str(exc)
    else:
        raise AssertionError(
            "duplicate items should be rejected"
        )



def test_specification_claim_author_can_edit_group(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    author_id = repository.create_user(
        "Author"
    )
    other_id = repository.create_user(
        "Other"
    )
    (
        individual_id,
        _observation_id,
        _listing_claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        author_id,
        manufacturer="Fender",
        model="Telecaster Thinline",
        serial_number="EDIT001",
        media_storage_path="media/edit001.jpg",
    )

    claim_id = repository.create_specification_claim_group(
        author_id,
        individual_id,
        specification_kind="specification",
        items=[
            {
                "field_name": "nut",
                "value_text": "Original",
            },
            {
                "field_name": "frets",
                "value_text": "Original",
            },
        ],
        occurred_at="1976-01-01",
        body="Original specification.",
    )

    assert repository.update_specification_claim_group(
        claim_id,
        author_id,
        specification_kind="repair",
        items=[
            {
                "field_name": "nut",
                "value_text": "Bone",
            },
            {
                "field_name": "frets",
                "value_text": "Leveled",
            },
            {
                "field_name": "pickguard",
                "value_text": "New 3-ply white",
            },
        ],
        occurred_at="2025-05-01",
        body="Repair completed.",
    )

    claims = repository.list_claims(
        individual_id
    )
    claim = next(
        row
        for row in claims
        if row["id"] == claim_id
    )
    assert claim["specification_kind"] == "repair"
    assert claim["occurred_at"] == "2025-05-01"
    assert claim["body"] == "Repair completed."

    items = [
        row
        for row in repository.list_specification_items(
            individual_id
        )
        if row["claim_id"] == claim_id
    ]
    assert [
        (
            row["field_name"],
            row["value_text"],
        )
        for row in items
    ] == [
        ("nut", "Bone"),
        ("frets", "Leveled"),
        ("pickguard", "New 3-ply white"),
    ]

    try:
        repository.update_specification_claim_group(
            claim_id,
            other_id,
            specification_kind="specification",
            items=[
                {
                    "field_name": "nut",
                    "value_text": "Plastic",
                }
            ],
        )
    except ValueError as exc:
        assert "author" in str(exc).lower()
    else:
        raise AssertionError(
            "non-author should not edit a Claim"
        )



def test_release_marks_former_owner_and_sets_unknown(
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
        _listing_observation_id,
        _listing_claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="REL001",
        media_storage_path="media/rel001.jpg",
    )

    observation_id, claim_id = (
        repository.create_release_claim(
            user_id,
            individual_id,
            reason="Sold to another collector.",
        )
    )

    assert observation_id > 0
    assert claim_id > 0

    _user, guitars = repository.get_user(
        user_id
    )
    former = next(
        row
        for row in guitars
        if row["individual_id"] == individual_id
    )
    assert former["ownership_status"] == (
        "former_owner"
    )
    assert former["released_at"] is not None

    _individual, observations = (
        repository.get_individual(
            individual_id
        )
    )
    latest = observations[-1]
    assert latest["event_type"] == "release"
    assert latest["owner_name"] == "Unknown"
    assert latest["owner_type"] == "unknown"

    claims = repository.list_claims(
        individual_id
    )
    release = next(
        row
        for row in claims
        if row["id"] == claim_id
    )
    assert release["claim_type"] == "release"
    assert release["body"] == (
        "Sold to another collector."
    )
    assert release["field_name"] == "owner_user_id"
    assert release["value_text"] == "unknown"

    individual, _observations = (
        repository.get_individual(
            individual_id
        )
    )
    assert individual is not None
    assert individual["current_owner_name"] == "Unknown"
    assert individual["current_owner_type"] == "unknown"


def test_release_claim_requires_current_ownership(
    tmp_path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()

    user_id = repository.create_user(
        "Collector"
    )
    other_id = repository.create_user(
        "Other"
    )
    (
        individual_id,
        _listing_observation_id,
        _listing_claim_id,
        _media_asset_id,
    ) = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Jazzmaster",
        serial_number="REL002",
        media_storage_path="media/rel002.jpg",
    )

    try:
        repository.create_release_claim(
            other_id,
            individual_id,
        )
    except ValueError as exc:
        assert "current owner" in str(exc)
    else:
        raise AssertionError(
            "non-owner should not be able to release"
        )
