from ygc.reverb_adapter import (
    classify_vintage_listing,
    to_observation,
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