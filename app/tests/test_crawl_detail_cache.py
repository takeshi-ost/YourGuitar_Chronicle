import json

from ygc.crawl_detail_cache import reprocess_details, save_detail
from ygc.crawl_service import crawl_query
from ygc.db.repository import Repository


def listing(number=1, **values):
    return {"id": str(number), "make": "Fender", "model": "Stratocaster",
            "year": "1967", "product_type": "electric-guitars",
            "description": "Serial number 524436",
            "_links": {"web": {"href": f"https://reverb.com/item/{number}"}}, **values}


def test_rejected_serial_can_be_reextracted_offline_and_is_idempotent(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class Collector:
        def listing_id(self, item):
            return item["id"]

        def iter_listing_summaries(self, **kwargs):
            return [listing()]

        def fetch_listing_details(self, candidates):
            yield from candidates

    monkeypatch.setattr("ygc.config.SERIAL_CONFIDENCE_THRESHOLD", 1.1)
    first = crawl_query(repo, Collector(), "Fender", 10, year_min=1950, year_max=1980)
    assert first["missing_identity"] == 1
    with repo.connect() as con:
        row = con.execute("SELECT * FROM crawl_detail_cache").fetchone()
        assert json.loads(row["payload_json"])["description"] == "Serial number 524436"
        con.execute("UPDATE crawl_detail_cache SET fetched_at='2026-01-01T00:00:00+00:00'")
        assert con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0] == 0
    monkeypatch.setattr("ygc.config.SERIAL_CONFIDENCE_THRESHOLD", 0.70)
    # A network access here is a failure, even if a future refactor adds one.
    monkeypatch.setattr("httpx.Client.get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Offline reprocessing must not fetch")))
    result = reprocess_details(repo, "electric", 1950, 1980)
    assert result["new_individuals"] == 1
    assert result["serial_candidates"] == 1
    again = reprocess_details(repo, "electric", 1950, 1980)
    assert again["new_individuals"] == 0
    assert again["skipped_existing"] == 1
    with repo.connect() as con:
        assert con.execute("SELECT observed_at FROM observations").fetchone()[0] == '2026-01-01T00:00:00+00:00'
        assert con.execute("SELECT COUNT(*) FROM claims WHERE claim_type='listing'").fetchone()[0] == 1


def test_unknown_year_and_nonserial_payloads_survive_restart(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    save_detail(repo, "1", listing(year="unreadable"))
    save_detail(repo, "2", listing(2, description="No serial provided"))
    repo.init_db()
    result = reprocess_details(repo, "electric", 1950, 1980)
    assert result["cached_processed"] == 2
    assert result["skipped_scope"] == 1
    assert result["missing_identity"] == 1
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM crawl_detail_cache").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_failed_fetch_does_not_overwrite_cached_detail(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    save_detail(repo, "1", listing())
    save_detail(repo, "1", {"id": "1", "_ygc_detail_unavailable": True})
    with repo.connect() as con:
        payload = json.loads(con.execute("SELECT payload_json FROM crawl_detail_cache").fetchone()[0])
        assert payload["description"] == "Serial number 524436"
