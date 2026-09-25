from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_listing_claim_data,
    to_observation,
    to_provenance_observation,
)


def test_adapter():
    item = {
        "id": 123,
        "make": "Fender",
        "model": "Stratocaster",
        "finish": "Olympic White",
        "year": "1985",
        "title": (
            "1985 Fender Stratocaster"
        ),
        "description": (
            "Made in Japan. "
            "Serial number E556368. "
            "Very good condition."
        ),
        "shop": {
            "name": "Example Vintage"
        },
        "location": {
            "region": "NH",
            "locality": "Amsterdam",
            "country_code": "NL",
            "display_location": (
                "Amsterdam, Netherlands"
            ),
        },
        "photos": [
            {
                "_links": {
                    "large_crop": {
                        "href": (
                            "https://images.reverb.com/"
                            "example.jpg"
                        )
                    }
                }
            }
        ],
        "_links": {
            "web": {
                "href": (
                    "https://reverb.example/"
                    "item/123"
                )
            }
        },
        "published_at": (
            "2026-09-01T00:00:00Z"
        ),
    }

    observation = (
        to_observation(
            item
        )
    )

    assert (
        observation[
            "manufacturer"
        ]
        == "Fender"
    )

    assert (
        observation[
            "model"
        ]
        == "Stratocaster"
    )

    assert (
        observation[
            "finish"
        ]
        == "Olympic White"
    )

    assert (
        observation[
            "year"
        ]
        == "1985"
    )

    assert (
        observation[
            "serial_number"
        ]
        == "E556368"
    )

    assert (
        observation[
            "seller"
        ]
        == "Example Vintage"
    )

    assert (
        observation[
            "owner_name"
        ]
        == "Example Vintage"
    )

    assert (
        observation[
            "owner_type"
        ]
        == "shop"
    )

    assert (
        observation[
            "source_listing_id"
        ]
        == "123"
    )

    assert (
        observation[
            "location_country"
        ]
        == "NL"
    )

    assert (
        observation[
            "location_region"
        ]
        == "NH"
    )

    assert (
        observation[
            "location_source"
        ]
        == "reverb_listing"
    )

    assert (
        observation[
            "image_url"
        ]
        == (
            "https://images.reverb.com/"
            "example.jpg"
        )
    )

    assert (
        observation[
            "vintage_status"
        ]
        == "modern"
    )


def test_real_1974_title_is_vintage():
    item = {
        "make": "Fender",
        "model": (
            "Fender Stratocaster "
            "- Natural - 1974 "
            "- 2nd Hand"
        ),
        "title": (
            "Fender Stratocaster "
            "- Natural - 1974 "
            "- 2nd Hand"
        ),
        "year": "",
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        == "vintage"
    )

    assert (
        result[
            "estimated_year"
        ]
        == 1974
    )


def test_custom_shop_time_capsule_is_modern():
    item = {
        "make": "Fender",
        "model": (
            "Fender Custom Shop "
            "Johnny A. Signature "
            "Stratocaster Time Capsule "
            "Sunset Glow Metallic"
        ),
        "title": (
            "Fender Custom Shop "
            "Johnny A. Signature "
            "Stratocaster Time Capsule "
            "Sunset Glow Metallic"
        ),
        "year": "",
        "description": (
            "Inspired by classic "
            "1960 instruments."
        ),
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        == "modern"
    )


def test_custom_shop_artisan_is_modern():
    item = {
        "make": "Fender",
        "model": (
            "Fender Custom Shop "
            "Artisan Koa Thinline "
            "Stratocaster"
        ),
        "title": (
            "Fender Custom Shop "
            "Artisan Koa Thinline "
            "Stratocaster Aged Natural "
            "DEMO"
        ),
        "year": "",
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        == "modern"
    )


def test_1978_neck_does_not_make_listing_vintage():
    item = {
        "make": "Fender",
        "model": (
            "Fender Stratocaster Plus"
        ),
        "title": (
            "Fender Stratocaster Plus "
            "- Olympic white "
            "(faded) with 1978 neck"
        ),
        "year": "",
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        != "vintage"
    )


def test_american_vintage_ii_is_modern():
    item = {
        "make": "Fender",
        "model": (
            "American Vintage II "
            "1957 Stratocaster"
        ),
        "title": (
            "Fender American Vintage II "
            "1957 Stratocaster "
            "- Vintage Blonde"
        ),
        "year": "2023",
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        == "modern"
    )


def test_description_year_does_not_create_vintage():
    item = {
        "make": "Fender",
        "model": "Stratocaster",
        "title": (
            "Fender Stratocaster"
        ),
        "year": "",
        "description": (
            "Features classic 1957 "
            "style specifications."
        ),
    }

    result = (
        classify_vintage_listing(
            item
        )
    )

    assert (
        result["status"]
        == "unknown"
    )


def test_claim_and_provenance_adapters_are_separated():
    item = {
        "id": 456,
        "make": "Fender",
        "model": "Telecaster",
        "finish": "Blonde",
        "year": "1968",
        "title": "1968 Fender Telecaster",
        "description": "Serial number 123456.",
        "shop": {
            "name": "Example Shop"
        },
        "location": {
            "country_code": "US",
            "region": "CA",
        },
        "_links": {
            "web": {
                "href": "https://reverb.example/item/456"
            }
        },
        "published_at": "2026-09-20T00:00:00Z",
    }

    claim = to_listing_claim_data(
        item
    )
    provenance = to_provenance_observation(
        item
    )

    assert claim["manufacturer"] == "Fender"
    assert claim["model"] == "Telecaster"
    assert claim["finish"] == "Blonde"
    assert claim["year"] == "1968"
    assert claim["serial_number"] == "123456"
    assert claim["owner_name"] == "Example Shop"
    assert claim["owner_type"] == "shop"
    assert claim["location_country"] == "US"
    assert claim["location_region"] == "CA"
    assert claim["source_listing_id"] == "456"
    assert claim["vintage_status"] == "vintage"

    assert provenance["source_site"] == "reverb"
    assert provenance["source_listing_id"] == "456"
    assert provenance["source_url"] == "https://reverb.example/item/456"
    assert provenance["event_type"] == "listing"

    assert "manufacturer" not in provenance
    assert "model" not in provenance
    assert "finish" not in provenance
    assert "year" not in provenance
    assert "serial_number" not in provenance
    assert "owner_name" not in provenance
    assert "location_country" not in provenance


def test_legacy_observation_adapter_still_available_during_transition():
    item = {
        "id": 789,
        "make": "Gibson",
        "model": "Les Paul",
        "year": "1978",
        "title": "1978 Gibson Les Paul",
        "description": "Serial number 99999999.",
    }

    legacy = to_observation(
        item
    )

    assert legacy["manufacturer"] == "Gibson"
    assert legacy["model"] == "Les Paul"
    assert legacy["year"] == "1978"
    assert legacy["source_listing_id"] == "789"
