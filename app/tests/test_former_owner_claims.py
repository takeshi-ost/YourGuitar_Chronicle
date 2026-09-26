from pathlib import Path

import pytest

from ygc.db.repository import Repository


def _setup(tmp_path: Path):
    repository = Repository(tmp_path / "former-owner.db")
    repository.init_db()

    current_owner_id = repository.create_user("Current Owner")
    former_owner_id = repository.create_user("Former Owner")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        current_owner_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="FORMER-001",
        media_storage_path="media/base.jpg",
        occurred_at="2026-06-01",
    )
    return (
        repository,
        current_owner_id,
        former_owner_id,
        individual_id,
    )


def test_former_owner_creates_acquire_release_and_former_link(tmp_path: Path):
    (
        repository,
        current_owner_id,
        former_owner_id,
        individual_id,
    ) = _setup(tmp_path)

    result = repository.create_former_owner_claims(
        former_owner_id,
        individual_id,
        acquisition_date="2020-01-15",
        release_date="2024-09-20",
        detail="Owned before the current owner.",
    )

    assert len(result["claim_ids"]) == 2
    claims = [
        row
        for row in repository.list_claims(individual_id)
        if int(row["id"]) in result["claim_ids"]
    ]
    assert [row["ownership_kind"] for row in claims] == [
        "acquire",
        "release",
    ]
    assert [row["occurred_at"] for row in claims] == [
        "2020-01-15",
        "2024-09-20",
    ]
    assert claims[0]["body"] == "Owned before the current owner."
    assert claims[1]["body"] is None
    assert all(row["ownership_source"] == "former_owner" for row in claims)
    assert all(row["verification_status"] == "unverified" for row in claims)
    assert len({row["ownership_pair_id"] for row in claims}) == 1

    individual, _ = repository.get_individual(individual_id)
    assert individual is not None
    assert int(individual["current_owner_user_id"]) == current_owner_id

    assert repository.set_claim_response(
        int(claims[0]["id"]),
        current_owner_id,
        "positive",
    )
    verified = [
        row
        for row in repository.list_claims(individual_id)
        if int(row["id"]) in result["claim_ids"]
    ]
    assert all(row["verification_status"] == "positive" for row in verified)

    assert repository.set_claim_response(
        int(claims[1]["id"]),
        current_owner_id,
        "negative",
    )
    rejected = [
        row
        for row in repository.list_claims(individual_id)
        if int(row["id"]) in result["claim_ids"]
    ]
    assert all(row["verification_status"] == "negative" for row in rejected)

    _, guitars = repository.get_user(former_owner_id)
    guitar = next(
        row
        for row in guitars
        if int(row["individual_id"]) == individual_id
    )
    assert guitar["ownership_status"] == "former_owner"
    assert guitar["acquired_at"] == "2020-01-15"
    assert guitar["released_at"] == "2024-09-20"


def test_former_owner_release_must_precede_current_owner_start(tmp_path: Path):
    (
        repository,
        _,
        former_owner_id,
        individual_id,
    ) = _setup(tmp_path)

    before = len(repository.list_claims(individual_id))

    with pytest.raises(
        ValueError,
        match="earlier than the current owner's acquisition date",
    ):
        repository.create_former_owner_claims(
            former_owner_id,
            individual_id,
            acquisition_date="2024-01-01",
            release_date="2026-06-01",
        )

    assert len(repository.list_claims(individual_id)) == before


def test_former_owner_requires_acquisition_before_release(tmp_path: Path):
    (
        repository,
        _,
        former_owner_id,
        individual_id,
    ) = _setup(tmp_path)

    with pytest.raises(
        ValueError,
        match="Acquisition Date must be earlier",
    ):
        repository.create_former_owner_claims(
            former_owner_id,
            individual_id,
            acquisition_date="2024-09-20",
            release_date="2024-09-20",
        )


def test_former_owner_cannot_be_verified_without_current_owner(tmp_path: Path):
    repository = Repository(tmp_path / "former-owner-no-current.db")
    repository.init_db()

    claimant_id = repository.create_user("Claimant")
    individual_id, _, _, _ = repository.create_initial_listing_claim(
        claimant_id,
        manufacturer="Fender",
        model="Jazzmaster",
        serial_number="FORMER-002",
        media_storage_path="media/base.jpg",
        occurred_at="2020-01-01",
    )
    repository.create_ownership_claim(
        claimant_id,
        individual_id,
        ownership_kind="release",
        occurred_at="2021-01-01",
    )

    other_id = repository.create_user("Other")
    result = repository.create_former_owner_claims(
        other_id,
        individual_id,
        acquisition_date="2018-01-01",
        release_date="2019-01-01",
    )

    with pytest.raises(
        ValueError,
        match="Only the current owner can verify",
    ):
        repository.set_claim_response(
            int(result["claim_ids"][0]),
            claimant_id,
            "positive",
        )
