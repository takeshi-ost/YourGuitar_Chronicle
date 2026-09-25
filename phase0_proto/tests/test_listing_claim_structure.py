from __future__ import annotations

from pathlib import Path

from ygc.db.repository import Repository


def _source_user(con, now: str) -> int:
    cur = con.execute(
        """
        INSERT INTO users (
            display_name,
            account_type,
            created_at,
            updated_at
        )
        VALUES ('Reverb', 'source', ?, ?)
        """,
        (now, now),
    )
    return int(cur.lastrowid)


def test_list_claims_reads_listing_semantics_from_claim_items(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()
    now = "2026-09-25T00:00:00+00:00"

    with repository.connect() as con:
        author_id = _source_user(con, now)

        individual = con.execute(
            """
            INSERT INTO individuals (
                manufacturer,
                normalized_manufacturer,
                normalized_serial,
                created_at,
                updated_at
            )
            VALUES ('Fender', 'fender', '524436', ?, ?)
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
                'WRONG MAKER',
                'WRONG MODEL',
                'WRONG FINISH',
                '1900',
                'WRONG SERIAL',
                'Wrong Owner',
                'unknown',
                'Wrong Seller',
                'XX',
                'Wrong Region',
                'wrong-source',
                'https://wrong.example/',
                'https://wrong.example/image.jpg',
                'wrong-id',
                ?,
                '1900-01-01',
                'Wrong title',
                ?
            )
            """,
            (
                individual_id,
                now,
                now,
            ),
        )
        observation_id = int(
            observation.lastrowid
        )

        claim = con.execute(
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
                ?, ?, ?, 'listing',
                'listing', '12345',
                '1974-01-01',
                'active', ?, ?
            )
            """,
            (
                individual_id,
                observation_id,
                author_id,
                now,
                now,
            ),
        )
        claim_id = int(claim.lastrowid)

        values = {
            "manufacturer": "Fender",
            "model": "Stratocaster",
            "finish": "Natural",
            "year": "1974",
            "serial_number": "524436",
            "owner_name": "Correct Owner",
            "owner_type": "shop",
            "seller": "Correct Seller",
            "location_country": "US",
            "location_region": "CA",
            "listing_title": "1974 Fender Stratocaster",
            "listing_date": "1974-01-01",
            "source_site": "reverb",
            "source_url": "https://reverb.example/item/12345",
            "source_listing_id": "12345",
            "image_url": "https://reverb.example/image.jpg",
        }
        con.executemany(
            """
            INSERT INTO claim_listing_items (
                claim_id,
                field_name,
                value_text,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    claim_id,
                    field,
                    value,
                    now,
                )
                for field, value
                in values.items()
            ],
        )

    rows = repository.list_claims(
        individual_id
    )
    listing = rows[0]

    assert listing["observed_manufacturer"] == "Fender"
    assert listing["observed_model"] == "Stratocaster"
    assert listing["observed_finish"] == "Natural"
    assert listing["observed_year"] == "1974"
    assert listing["observed_serial_number"] == "524436"
    assert listing["observed_owner_name"] == "Correct Owner"
    assert listing["observed_owner_type"] == "shop"
    assert listing["seller"] == "Correct Seller"
    assert listing["location_country"] == "US"
    assert listing["location_region"] == "CA"
    assert listing["listing_title"] == "1974 Fender Stratocaster"
    assert listing["listing_date"] == "1974-01-01"
    assert listing["source_site"] == "reverb"
    assert listing["source_url"] == "https://reverb.example/item/12345"
    assert listing["source_listing_id"] == "12345"
    assert listing["image_url"] == "https://reverb.example/image.jpg"


def test_legacy_listing_claim_backfill_copies_complete_structure(
    tmp_path: Path,
):
    repository = Repository(
        tmp_path / "chronicle.db"
    )
    repository.init_db()
    now = "2026-09-25T00:00:00+00:00"

    with repository.connect() as con:
        author_id = _source_user(con, now)

        individual = con.execute(
            """
            INSERT INTO individuals (
                manufacturer,
                normalized_manufacturer,
                normalized_serial,
                created_at,
                updated_at
            )
            VALUES ('Fender', 'fender', '524436', ?, ?)
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
        observation_id = int(
            observation.lastrowid
        )

        con.execute(
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
                ?, ?, ?, 'listing',
                'listing', '12345',
                '1974-01-01',
                'active', ?, ?
            )
            """,
            (
                individual_id,
                observation_id,
                author_id,
                now,
                now,
            ),
        )

    repository.init_db()

    rows = repository.list_claims(
        individual_id
    )
    listing = rows[0]

    assert listing["observed_manufacturer"] == "Fender"
    assert listing["observed_owner_type"] == "shop"
    assert listing["seller"] == "Vintage Shop"
    assert listing["listing_title"] == "1974 Fender Stratocaster"
    assert listing["listing_date"] == "1974-01-01"
    assert listing["source_site"] == "reverb"
    assert listing["source_url"] == "https://reverb.example/item/12345"
    assert listing["source_listing_id"] == "12345"
    assert listing["image_url"] == "https://reverb.example/image.jpg"
