from ygc.collectors.reverb import ReverbAPICollector


def test_first_image_url_from_images_payload():
    payload = {
        "images": [
            {
                "id": 87485553,
                "url": (
                    "https://images.reverb.com/"
                    "image/upload/example.png"
                ),
            }
        ]
    }

    assert (
        ReverbAPICollector
        ._first_image_url(
            payload
        )
        == (
            "https://images.reverb.com/"
            "image/upload/example.png"
        )
    )


def test_first_image_url_from_embedded_payload():
    payload = {
        "_embedded": {
            "images": [
                {
                    "url": (
                        "https://images.reverb.com/"
                        "image/upload/example2.png"
                    )
                }
            ]
        }
    }

    assert (
        ReverbAPICollector
        ._first_image_url(
            payload
        )
        == (
            "https://images.reverb.com/"
            "image/upload/example2.png"
        )
    )


def test_first_image_url_from_root_array():
    payload = [
        {
            "id": 87485553,
            "url": (
                "https://images.reverb.com/"
                "image/upload/example3.png"
            ),
        }
    ]

    assert (
        ReverbAPICollector
        ._first_image_url(
            payload
        )
        == (
            "https://images.reverb.com/"
            "image/upload/example3.png"
        )
    )
