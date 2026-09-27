from ygc.crawl_candidates import reconcile_candidates, stage_candidate
from ygc.db.repository import Repository


def _candidate(listing_id, serial="524436", model="Stratocaster"):
    claim = {"manufacturer": "Fender", "model": model, "serial_number": serial,
             "owner_name": "Reverb Shop", "source_site": "reverb",
             "source_listing_id": listing_id, "source_url": f"https://reverb.com/item/{listing_id}"}
    provenance = {"source_site": "reverb", "source_listing_id": listing_id,
                  "source_url": claim["source_url"]}
    return claim, provenance


def test_batch_match_and_resume_pending_candidate(tmp_path):
    repo = Repository(tmp_path / "chronicle.db")
    repo.init_db()
    for number in ("1", "2"):
        assert stage_candidate(repo, *_candidate(number))
    repo.init_db()  # Candidate survives a process restart.
    result = reconcile_candidates(repo)
    assert result["new_individuals"] == 1
    assert result["existing_individuals_extended"] == 1
    assert reconcile_candidates(repo)["new_observations"] == 0
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM claims WHERE claim_type='listing'").fetchone()[0] == 1


def test_conflicting_models_are_held_for_review(tmp_path):
    repo = Repository(tmp_path / "chronicle.db")
    repo.init_db()
    stage_candidate(repo, *_candidate("1", model="Stratocaster"))
    stage_candidate(repo, *_candidate("2", model="Telecaster"))
    result = reconcile_candidates(repo)
    assert result["ambiguous_matches"] == 2
    assert result["new_individuals"] == 0
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM crawl_candidates WHERE status='review'").fetchone()[0] == 2
