from pathlib import Path

from ygc.db.repository import Repository


def test_ownership_claim_acquire_starts_ownership(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    repository.update_user(
        user_id,
        display_name="Owner",
        account_type="user",
        location_country="Japan",
        location_region="Kyoto",
    )
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="OWN-001",
        media_storage_path="test/ownership.jpg",
        occurred_at="2026-01-01",
    )

    repository.create_ownership_claim(
        user_id,
        individual_id,
        ownership_kind="acquire",
        occurred_at="2026-02-01",
    )
    acquired, _ = repository.get_individual(individual_id)
    assert acquired is not None

    assert acquired["current_owner_name"] == "Owner"
    assert int(acquired["current_owner_user_id"]) == user_id
    assert acquired["location_country"] == "Japan"
    assert acquired["location_region"] == "Kyoto"

    repository.update_user(
        user_id,
        display_name="Owner",
        account_type="user",
        location_country="Japan",
        location_region="Osaka",
    )
    refreshed, _ = repository.get_individual(individual_id)
    assert refreshed is not None
    assert refreshed["location_country"] == "Japan"
    assert refreshed["location_region"] == "Osaka"


def test_transfer_release_and_inherit_end_ownership(tmp_path: Path):
    for index, kind in enumerate(("transfer", "release", "inherit"), start=1):
        repository = Repository(tmp_path / f"chronicle-{kind}.db")
        repository.init_db()

        user_id = repository.create_user("Owner")
        individual_id, _, _, _ = repository.create_initial_listing_claim(
            user_id,
            manufacturer="Fender",
            model="Telecaster",
            serial_number=f"OWN-END-{index}",
            media_storage_path=f"test/ownership-{kind}.jpg",
            occurred_at="2026-01-01",
        )

        _, claim_id = repository.create_ownership_claim(
            user_id,
            individual_id,
            ownership_kind=kind,
            occurred_at="2026-02-01",
            previous_owner_text="Counterparty",
            body=f"{kind} ownership",
        )

        ended, _ = repository.get_individual(individual_id)
        assert ended is not None
        assert ended["current_owner_name"] == "Unknown"
        assert ended["current_owner_user_id"] is None
        assert ended["location_country"] is None
        assert ended["location_region"] is None

        claims = [
            dict(row)
            for row in repository.list_claims(individual_id)
        ]
        claim = next(
            row for row in claims
            if int(row["id"]) == claim_id
        )
        assert claim["claim_type"] == "ownership"
        assert claim["ownership_kind"] == kind


def test_ownership_ending_kind_requires_current_owner(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    other_user_id = repository.create_user("Other User")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Gibson",
        model="SG",
        serial_number="OWN-002",
        media_storage_path="test/ownership-2.jpg",
    )

    for kind in ("transfer", "release", "inherit"):
        try:
            repository.create_ownership_claim(
                other_user_id,
                individual_id,
                ownership_kind=kind,
            )
        except ValueError as exc:
            assert "current owner" in str(exc)
        else:
            raise AssertionError(
                f"{kind} was accepted for a non-owner"
            )


def test_ownership_kind_is_validated(tmp_path: Path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    user_id = repository.create_user("Owner")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        user_id,
        manufacturer="Gibson",
        model="SG",
        serial_number="OWN-003",
        media_storage_path="test/ownership-3.jpg",
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
