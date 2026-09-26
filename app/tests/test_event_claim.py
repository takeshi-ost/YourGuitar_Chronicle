from pathlib import Path

from ygc.db.repository import Repository


def test_event_claim_is_recorded_without_changing_snapshot(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-event.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Jazzmaster",
        serial_number="EVT-001",
        media_storage_path="test/event.jpg",
        occurred_at="2026-01-01",
    )

    before, _ = repository.get_individual(individual_id)
    assert before is not None

    claim_id = repository.create_event_claim(
        user_id,
        individual_id,
        event_kind="performance",
        occurred_at="2026-04-01",
        detail="Used on stage at a live performance.",
    )

    after, _ = repository.get_individual(individual_id)
    assert after is not None
    assert after["manufacturer"] == before["manufacturer"]
    assert after["model"] == before["model"]
    assert after["serial_number"] == before["serial_number"]
    assert after["current_owner_user_id"] == before["current_owner_user_id"]
    assert after["location_country"] == before["location_country"]
    assert after["location_region"] == before["location_region"]

    claims = repository.list_claims(individual_id)
    event = next(row for row in claims if int(row["id"]) == claim_id)
    assert event["claim_type"] == "event"
    assert event["field_name"] == "event_kind"
    assert event["value_text"] == "performance"
    assert event["occurred_at"] == "2026-04-01"
    assert event["body"] == "Used on stage at a live performance."


def test_event_claim_validates_tag_and_detail(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-event-validation.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Gibson",
        model="ES-335",
        serial_number="EVT-002",
        media_storage_path="test/event-validation.jpg",
        occurred_at="2026-01-01",
    )

    try:
        repository.create_event_claim(
            user_id,
            individual_id,
            event_kind="unknown",
            detail="Something happened.",
        )
    except ValueError as exc:
        assert "event_kind" in str(exc)
    else:
        raise AssertionError("Unknown Event tag must be rejected")

    try:
        repository.create_event_claim(
            user_id,
            individual_id,
            event_kind="recording",
            detail="",
        )
    except ValueError as exc:
        assert "detail" in str(exc)
    else:
        raise AssertionError("Empty Event detail must be rejected")
