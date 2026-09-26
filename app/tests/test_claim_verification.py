from pathlib import Path

from ygc.db.repository import Repository


def _setup(tmp_path: Path):
    repository = Repository(tmp_path / "verification.db")
    repository.init_db()
    owner_id = repository.create_user("Owner")
    other_id = repository.create_user("Other")
    individual_id, _, _, representative_id = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Fender",
        model="Mustang",
        serial_number="VER-001",
        media_storage_path="media/base.jpg",
        media_original_filename="base.jpg",
        media_mime_type="image/jpeg",
        occurred_at="2026-01-01",
    )
    return repository, owner_id, other_id, individual_id, representative_id


def test_owner_claim_starts_positive(tmp_path: Path):
    repository, owner_id, _, individual_id, _ = _setup(tmp_path)

    claim_id = repository.create_specification_claim_group(
        owner_id,
        individual_id,
        specification_kind="specification",
        items=[{"field_name": "finish", "value_text": "Sunburst"}],
        occurred_at="2026-02-01",
    )

    claim = next(
        row for row in repository.list_claims(individual_id)
        if int(row["id"]) == claim_id
    )
    assert claim["verification_status"] == "positive"

    current = repository.list_current_specifications(individual_id)
    assert any(
        row["field_name"] == "finish" and row["value_text"] == "Sunburst"
        for row in current
    )


def test_third_party_specification_requires_owner_positive(tmp_path: Path):
    repository, owner_id, other_id, individual_id, _ = _setup(tmp_path)

    claim_id = repository.create_specification_claim_group(
        other_id,
        individual_id,
        specification_kind="specification",
        items=[{"field_name": "finish", "value_text": "Olympic White"}],
        occurred_at="2026-03-01",
    )

    claim = next(
        row for row in repository.list_claims(individual_id)
        if int(row["id"]) == claim_id
    )
    assert claim["verification_status"] == "unverified"

    current = repository.list_current_specifications(individual_id)
    assert not any(
        row["field_name"] == "finish" and row["value_text"] == "Olympic White"
        for row in current
    )

    assert repository.set_claim_response(
        claim_id,
        owner_id,
        "positive",
    )

    claim = next(
        row for row in repository.list_claims(individual_id)
        if int(row["id"]) == claim_id
    )
    assert claim["verification_status"] == "positive"

    current = repository.list_current_specifications(individual_id)
    assert any(
        row["field_name"] == "finish" and row["value_text"] == "Olympic White"
        for row in current
    )

    assert repository.set_claim_response(
        claim_id,
        owner_id,
        "negative",
    )

    current = repository.list_current_specifications(individual_id)
    assert not any(
        row["field_name"] == "finish" and row["value_text"] == "Olympic White"
        for row in current
    )


def test_third_party_media_enters_gallery_only_when_positive(tmp_path: Path):
    repository, owner_id, other_id, individual_id, representative_id = _setup(tmp_path)

    claim_id, media_ids = repository.create_media_claim_group(
        other_id,
        individual_id,
        media_items=[
            {
                "storage_path": "media/third-party.jpg",
                "original_filename": "third-party.jpg",
                "mime_type": "image/jpeg",
            }
        ],
        occurred_at="2026-04-01",
        caption="Third-party photo",
    )

    claim = next(
        row for row in repository.list_claims(individual_id)
        if int(row["id"]) == claim_id
    )
    assert claim["verification_status"] == "unverified"

    gallery = repository.list_media_assets(individual_id)
    assert [int(row["id"]) for row in gallery] == [representative_id]

    repository.set_claim_response(
        claim_id,
        owner_id,
        "positive",
    )
    gallery = repository.list_media_assets(individual_id)
    assert [int(row["id"]) for row in gallery] == [
        representative_id,
        media_ids[0],
    ]


def test_non_owner_cannot_verify_claim(tmp_path: Path):
    repository, _, other_id, individual_id, _ = _setup(tmp_path)
    third_id = repository.create_user("Third")

    claim_id = repository.create_event_claim(
        other_id,
        individual_id,
        event_kind="exhibition",
        occurred_at="2026-05-01",
        detail="Displayed at an exhibition.",
    )

    try:
        repository.set_claim_response(
            claim_id,
            third_id,
            "positive",
        )
    except ValueError as exc:
        assert "current owner" in str(exc)
    else:
        raise AssertionError("Non-owner verification must be rejected")
