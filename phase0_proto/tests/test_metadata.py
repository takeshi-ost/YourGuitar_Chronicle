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
