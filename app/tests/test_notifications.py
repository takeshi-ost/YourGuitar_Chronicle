from pathlib import Path

from ygc.db.repository import Repository


def test_claim_added_notification_and_read_flow(tmp_path: Path):
    repository = Repository(tmp_path / "notifications.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    other_id = repository.create_user("Other")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="NOTIFY-001",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    claim_id = repository.create_incident_claim(
        other_id,
        individual_id,
        incident_kind="damage",
        occurred_at="2026-02-01",
        detail="Small dent.",
    )

    notification_id = repository.create_claim_notification(claim_id)
    assert notification_id is not None
    assert repository.unread_notification_count(owner_id) == 1

    rows = repository.list_notifications(owner_id)
    assert len(rows) == 1
    assert rows[0]["notification_type"] == "claim_added"
    assert int(rows[0]["claim_id"]) == claim_id
    assert int(rows[0]["actor_user_id"]) == other_id
    assert int(rows[0]["is_read"]) == 0

    assert repository.mark_notification_read(notification_id, owner_id)
    assert repository.unread_notification_count(owner_id) == 0


def test_owner_does_not_receive_notification_for_own_claim(tmp_path: Path):
    repository = Repository(tmp_path / "notifications-own.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Gibson",
        model="SG",
        serial_number="NOTIFY-002",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    claim_id = repository.create_event_claim(
        owner_id,
        individual_id,
        event_kind="performance",
        occurred_at="2026-02-01",
        detail="Live show.",
    )

    assert repository.create_claim_notification(claim_id) is None
    assert repository.unread_notification_count(owner_id) == 0


def test_verification_notifies_claim_author(tmp_path: Path):
    repository = Repository(tmp_path / "notifications-verify.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    other_id = repository.create_user("Other")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Fender",
        model="Jazzmaster",
        serial_number="NOTIFY-003",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    claim_id = repository.create_specification_claim_group(
        other_id,
        individual_id,
        specification_kind="specification",
        items=[{"field_name": "pickups", "value_text": "Changed"}],
        occurred_at="2026-02-01",
        body=None,
    )

    assert repository.set_claim_response(
        claim_id,
        owner_id,
        "positive",
    )
    notification_id = repository.create_verification_notification(
        claim_id,
        owner_id,
        "positive",
    )
    assert notification_id is not None

    rows = repository.list_notifications(other_id)
    assert len(rows) == 1
    assert rows[0]["notification_type"] == "claim_verified"
    assert int(rows[0]["actor_user_id"]) == owner_id
    assert int(rows[0]["claim_id"]) == claim_id


def test_mark_all_notifications_read(tmp_path: Path):
    repository = Repository(tmp_path / "notifications-all.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    other_id = repository.create_user("Other")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Fender",
        model="Mustang",
        serial_number="NOTIFY-004",
        media_storage_path="media/base.jpg",
        occurred_at="2026-01-01",
    )

    for kind, date, detail in [
        ("damage", "2026-02-01", "Dent"),
        ("lost", "2026-03-01", "Lost briefly"),
    ]:
        claim_id = repository.create_incident_claim(
            other_id,
            individual_id,
            incident_kind=kind,
            occurred_at=date,
            detail=detail,
        )
        repository.create_claim_notification(claim_id)

    assert repository.unread_notification_count(owner_id) == 2
    assert repository.mark_all_notifications_read(owner_id) == 2
    assert repository.unread_notification_count(owner_id) == 0
