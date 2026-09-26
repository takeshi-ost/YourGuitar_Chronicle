from pathlib import Path

from ygc.db.repository import Repository


def test_media_claim_records_image_without_changing_snapshot(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-media.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Mustang",
        serial_number="MED-001",
        media_storage_path="test/base.jpg",
        occurred_at="2026-01-01",
    )

    before, _ = repository.get_individual(individual_id)
    assert before is not None

    claim_id, media_asset_id = repository.create_media_claim(
        user_id,
        individual_id,
        storage_path="media/example.jpg",
        original_filename="example.jpg",
        mime_type="image/jpeg",
        occurred_at="2026-05-20",
        caption="Studio photo after setup.",
    )

    after, _ = repository.get_individual(individual_id)
    assert after is not None
    assert after["current_owner_user_id"] == before["current_owner_user_id"]
    assert after["location_country"] == before["location_country"]
    assert after["location_region"] == before["location_region"]

    claims = repository.list_claims(individual_id)
    media_claim = next(row for row in claims if int(row["id"]) == claim_id)
    assert media_claim["claim_type"] == "media"
    assert media_claim["field_name"] == "media_type"
    assert media_claim["value_text"] == "image"
    assert media_claim["occurred_at"] == "2026-05-20"
    assert media_claim["body"] == "Studio photo after setup."
    assert int(media_claim["evidence_media_id"]) == media_asset_id

    asset = repository.get_media_asset(media_asset_id)
    assert asset is not None
    assert asset["media_type"] == "image"
    assert asset["storage_path"] == "media/example.jpg"
    assert asset["mime_type"] == "image/jpeg"


def test_media_assets_are_available_for_product_gallery(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-media-gallery.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, representative_id = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Jaguar",
        serial_number="MED-003",
        media_storage_path="media/representative.jpg",
        media_original_filename="representative.jpg",
        media_mime_type="image/jpeg",
        occurred_at="2026-01-01",
    )

    _, media_id = repository.create_media_claim(
        user_id,
        individual_id,
        storage_path="media/gallery.jpg",
        original_filename="gallery.jpg",
        mime_type="image/jpeg",
        occurred_at="2026-06-01",
        caption="Back of the guitar.",
    )

    gallery = repository.list_media_assets(individual_id)
    assert [int(row["id"]) for row in gallery] == [representative_id, media_id]
    media_row = next(row for row in gallery if int(row["id"]) == media_id)
    assert media_row["claim_type"] == "media"
    assert media_row["claim_caption"] == "Back of the guitar."
    assert media_row["claim_occurred_at"] == "2026-06-01"


def test_media_claim_group_supports_multiple_images(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-media-group.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Duo-Sonic",
        serial_number="MED-010",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    claim_id, media_ids = repository.create_media_claim_group(
        user_id,
        individual_id,
        media_items=[
            {
                "storage_path": "media/one.jpg",
                "original_filename": "one.jpg",
                "mime_type": "image/jpeg",
            },
            {
                "storage_path": "media/two.png",
                "original_filename": "two.png",
                "mime_type": "image/png",
            },
            {
                "storage_path": "media/three.webp",
                "original_filename": "three.webp",
                "mime_type": "image/webp",
            },
        ],
        occurred_at="2026-07-01",
        caption="Three views.",
    )

    assert len(media_ids) == 3

    attached = repository.list_claim_media_assets(individual_id)
    claim_attached = [
        row for row in attached
        if int(row["claim_id"]) == claim_id
    ]
    assert [int(row["id"]) for row in claim_attached] == media_ids

    claims = repository.list_claims(individual_id)
    media_claims = [
        row for row in claims
        if row["claim_type"] == "media"
    ]
    assert len(media_claims) == 1
    assert int(media_claims[0]["id"]) == claim_id
    assert media_claims[0]["body"] == "Three views."


def test_media_claim_group_rejects_more_than_ten_images(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-media-limit.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Gibson",
        model="SG",
        serial_number="MED-011",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    items = [
        {
            "storage_path": f"media/{index}.jpg",
            "original_filename": f"{index}.jpg",
            "mime_type": "image/jpeg",
        }
        for index in range(11)
    ]

    try:
        repository.create_media_claim_group(
            user_id,
            individual_id,
            media_items=items,
            occurred_at="2026-07-01",
        )
    except ValueError as exc:
        assert "up to 10 images" in str(exc)
    else:
        raise AssertionError("More than 10 images must be rejected")
