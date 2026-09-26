from pathlib import Path

from ygc.db.repository import Repository


def test_ownership_claim_generalizes_owner_change_and_release(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    first_user_id = repository.create_user("First Owner")
    second_user_id = repository.create_user("Second Owner")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        first_user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="OWN-001",
        media_storage_path="test/ownership.jpg",
        occurred_at="2026-01-01",
    )

    repository.create_ownership_claim(
        first_user_id,
        individual_id,
        ownership_kind="release",
        occurred_at="2026-02-01",
        body="Released for transfer",
    )
    released = repository.rebuild_individual_snapshot(individual_id)
    assert released["current_owner_name"] == "Unknown"
    assert released["current_owner_user_id"] is None

    _, acquire_claim_id = repository.create_ownership_claim(
        second_user_id,
        individual_id,
        ownership_kind="transfer",
        occurred_at="2026-02-02",
        previous_owner_text="First Owner",
        body="Transferred from First Owner",
    )
    acquired = repository.rebuild_individual_snapshot(individual_id)

    assert acquired["current_owner_name"] == "Second Owner"
    assert int(acquired["current_owner_user_id"]) == second_user_id

    claims = [
        dict(row)
        for row in repository.list_claims(individual_id)
    ]
    claim = next(
        row for row in claims
        if int(row["id"]) == acquire_claim_id
    )
    assert claim["claim_type"] == "ownership"
    assert claim["ownership_kind"] == "transfer"


def test_ownership_kind_is_validated(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Gibson",
        model="SG",
        serial_number="OWN-002",
        media_storage_path="test/ownership-2.jpg",
    )

    try:
        repository.create_ownership_claim(
            user_id,
            individual_id,
            ownership_kind="unknown-tag",
        )
    except ValueError as exc:
        assert "ownership_kind" in str(exc)
    else:
        raise AssertionError("Invalid ownership_kind was accepted")
