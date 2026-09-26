from pathlib import Path

from ygc.db.repository import Repository


def test_deactivate_claim_marks_inactive_and_rebuilds_snapshot(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-deactivate.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Mustang",
        serial_number="DEACT-001",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    _, release_claim_id = repository.create_ownership_claim(
        user_id,
        individual_id,
        ownership_kind="release",
        occurred_at="2026-03-01",
    )

    before, _ = repository.get_individual(individual_id)
    assert before is not None
    assert before["current_owner_user_id"] is None

    result = repository.deactivate_claim(
        release_claim_id,
        user_id,
    )
    assert result is not None

    claims = repository.list_claims(individual_id)
    release = next(row for row in claims if int(row["id"]) == release_claim_id)
    assert release["status"] == "inactive"

    after, _ = repository.get_individual(individual_id)
    assert after is not None
    assert int(after["current_owner_user_id"]) == user_id


def test_deactivate_media_claim_removes_images_from_gallery(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-deactivate-media.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, representative_id = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Jaguar",
        serial_number="DEACT-002",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    media_claim_id, media_ids = repository.create_media_claim_group(
        user_id,
        individual_id,
        media_items=[
            {
                "storage_path": "media/one.jpg",
                "original_filename": "one.jpg",
                "mime_type": "image/jpeg",
            },
            {
                "storage_path": "media/two.jpg",
                "original_filename": "two.jpg",
                "mime_type": "image/jpeg",
            },
        ],
        occurred_at="2026-04-01",
    )

    before = repository.list_media_assets(individual_id)
    assert [int(row["id"]) for row in before] == [representative_id, *media_ids]

    repository.deactivate_claim(
        media_claim_id,
        user_id,
    )

    after = repository.list_media_assets(individual_id)
    assert [int(row["id"]) for row in after] == [representative_id]
