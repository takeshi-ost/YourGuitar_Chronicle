from pathlib import Path

from ygc.db.repository import Repository


def test_claim_vote_toggles_to_neutral_and_switches_sides(tmp_path: Path):
    repository = Repository(tmp_path / "votes.db")
    repository.init_db()

    owner_id = repository.create_user("Owner")
    voter_id = repository.create_user("Voter")

    individual_id, _, _, _ = repository.create_initial_listing_claim(
        owner_id,
        manufacturer="Fender",
        model="Telecaster",
        serial_number="VOTE-001",
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

    assert repository.set_claim_vote(claim_id, voter_id, "good")
    with repository.connect() as con:
        row = con.execute(
            "SELECT vote FROM claim_votes WHERE claim_id = ? AND user_id = ?",
            (claim_id, voter_id),
        ).fetchone()
        assert row["vote"] == "good"

    assert repository.set_claim_vote(claim_id, voter_id, "good")
    with repository.connect() as con:
        row = con.execute(
            "SELECT vote FROM claim_votes WHERE claim_id = ? AND user_id = ?",
            (claim_id, voter_id),
        ).fetchone()
        assert row is None

    assert repository.set_claim_vote(claim_id, voter_id, "bad")
    with repository.connect() as con:
        row = con.execute(
            "SELECT vote FROM claim_votes WHERE claim_id = ? AND user_id = ?",
            (claim_id, voter_id),
        ).fetchone()
        assert row["vote"] == "bad"

    assert repository.set_claim_vote(claim_id, voter_id, "good")
    with repository.connect() as con:
        row = con.execute(
            "SELECT vote FROM claim_votes WHERE claim_id = ? AND user_id = ?",
            (claim_id, voter_id),
        ).fetchone()
        assert row["vote"] == "good"

    assert repository.set_claim_vote(claim_id, voter_id, "good")
    with repository.connect() as con:
        row = con.execute(
            "SELECT vote FROM claim_votes WHERE claim_id = ? AND user_id = ?",
            (claim_id, voter_id),
        ).fetchone()
        assert row is None
