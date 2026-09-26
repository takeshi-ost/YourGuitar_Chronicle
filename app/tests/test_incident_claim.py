from pathlib import Path

from ygc.db.repository import Repository


def test_incident_claim_is_recorded_without_changing_snapshot(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-incident.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="INC-001",
        media_storage_path="test/incident.jpg",
        occurred_at="2026-01-01",
    )

    before, _ = repository.get_individual(individual_id)
    assert before is not None

    claim_id = repository.create_incident_claim(
        user_id,
        individual_id,
        incident_kind="damage",
        occurred_at="2026-03-15",
        detail="Body edge was chipped during transport.",
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
    incident = next(row for row in claims if int(row["id"]) == claim_id)
    assert incident["claim_type"] == "incident"
    assert incident["field_name"] == "incident_kind"
    assert incident["value_text"] == "damage"
    assert incident["occurred_at"] == "2026-03-15"
    assert incident["body"] == "Body edge was chipped during transport."


def test_incident_claim_validates_tag_and_detail(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle-incident-validation.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Gibson",
        model="Les Paul",
        serial_number="INC-002",
        media_storage_path="test/incident-validation.jpg",
        occurred_at="2026-01-01",
    )

    try:
        repository.create_incident_claim(
            user_id,
            individual_id,
            incident_kind="unknown",
            detail="Something happened.",
        )
    except ValueError as exc:
        assert "incident_kind" in str(exc)
    else:
        raise AssertionError("Unknown Incident tag must be rejected")

    try:
        repository.create_incident_claim(
            user_id,
            individual_id,
            incident_kind="lost",
            detail="",
        )
    except ValueError as exc:
        assert "detail" in str(exc)
    else:
        raise AssertionError("Empty Incident detail must be rejected")
