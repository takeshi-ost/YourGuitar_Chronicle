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
