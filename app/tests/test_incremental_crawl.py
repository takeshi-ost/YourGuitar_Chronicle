from datetime import datetime, timedelta, timezone

import pytest

from ygc.collectors.reverb import ReverbAPICollector
from ygc.db.repository import Repository
from ygc.db.repository import utcnow
from ygc.incremental_crawl import advance_program, restart_program
from ygc.incremental_crawl import MAX_SUMMARIES, MAX_DETAILS, MAX_LIST_PAGES
from ygc.incremental_crawl import _year_matches


class Collector:
    api_base = "https://api.reverb.com/api"

    def __init__(self, pages=None, status="public"):
        self.pages = pages or [{"listings": []}]
        self.status = status
        self.requests = []

    def safe_api_url(self, href):
        return ReverbAPICollector.safe_api_url(self, href)

    def _next_href(self, payload):
        return ReverbAPICollector._next_href(payload)

    def _self_href(self, item):
        return ReverbAPICollector._self_href(item)

    def listing_id(self, item):
        return ReverbAPICollector.listing_id(item)

    def _get_json(self, url, params=None):
        self.requests.append(url)
        if url.endswith("/listings"):
            return self.pages[0]
        if "?page=2" in url:
            return self.pages[1]
        listing_id = url.rsplit("/", 1)[-1]
        return {"id": listing_id, "make": "Fender", "model": "Stratocaster",
                "year": "1974", "product_type": "electric-guitars",
                "title": "1974 Fender Stratocaster",
                "description": f"Serial number 52443{listing_id}.",
                "_links": {"web": {"href": f"https://reverb.com/item/{listing_id}"}}}

    def public_listing_status(self, listing_id, api_url=None):
        self.requests.append("check:" + listing_id)
        return self.status


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr("ygc.incremental_crawl.MIN_REQUEST_GAP", 0.0)


def _summary(n):
    return {"id": str(n), "year": "1974", "product_type": "electric-guitars",
            "_links": {"self": {"href": f"https://api.reverb.com/api/listings/{n}"}}}


def test_cursor_survives_restart_and_bounds_work(tmp_path, monkeypatch):
    monkeypatch.setattr("ygc.incremental_crawl.MAX_SUMMARIES", 5)
    monkeypatch.setattr("ygc.incremental_crawl.MAX_DETAILS", 5)
    monkeypatch.setattr("ygc.incremental_crawl.MAX_LIST_PAGES", 1)
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    pages = [
        {"listings": [_summary(n) for n in range(1, 8)],
         "_links": {"next": {"href": "https://api.reverb.com/api/listings?page=2"}}},
        {"listings": [_summary(8)]},
    ]
    collector = Collector(pages)
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["summaries_processed"] == 5
    assert first["details_fetched"] == 5
    assert first["processed"] == 5
    repo.init_db()
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["summaries_processed"] == 3
    assert second["processed"] == 8
    assert len([url for url in collector.requests if url.endswith("/listings")]) == 1
    third = advance_program(repo, collector, "electric", 1970, 1979)
    assert third["summaries_processed"] == 0
    assert third["processed"] == 8
    assert third["finished"]
    restart_program(repo, "electric", 1970, 1979)
    repeat = advance_program(repo, collector, "electric", 1970, 1979)
    assert repeat["summaries_processed"] == 5
    assert repeat["new_observations"] == 0
    assert repeat["skipped_existing"] == 5


def test_page_and_detail_budgets_continue_mid_page(tmp_path, monkeypatch):
    monkeypatch.setattr("ygc.incremental_crawl.MAX_SUMMARIES", 6)
    monkeypatch.setattr("ygc.incremental_crawl.MAX_DETAILS", 3)
    monkeypatch.setattr("ygc.incremental_crawl.MAX_LIST_PAGES", 2)
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    pages = [
        {"listings": [_summary(1), _summary(2)],
         "_links": {"next": {"href": "https://api.reverb.com/api/listings?page=2"}}},
        {"listings": [_summary(n) for n in range(3, 8)]},
    ]
    collector = Collector(pages)
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["listing_pages_fetched"] == 2
    assert first["summaries_processed"] == 3
    assert first["details_fetched"] == 3
    assert not first["finished"]
    repo.init_db()
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["listing_pages_fetched"] == 0
    assert second["summaries_processed"] == 3
    assert second["processed"] == 6
    third = advance_program(repo, collector, "electric", 1970, 1979)
    assert third["summaries_processed"] == 1
    assert third["processed"] == 7
    assert third["finished"]


def test_production_budget_handles_hundred_details_in_one_click(tmp_path):
    assert (MAX_SUMMARIES, MAX_DETAILS, MAX_LIST_PAGES) == (500, 100, 5)
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    collector = Collector([
        {"listings": [_summary(n) for n in range(1, 121)],
         "_links": {"next": {"href": "https://api.reverb.com/api/listings?page=2"}}},
        {"listings": [_summary(n) for n in range(121, 151)]},
    ])
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["summaries_processed"] == 100
    assert first["details_fetched"] == 100
    assert first["new_observations"] == 100
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["summaries_processed"] == 50
    assert second["new_observations"] == 50
    assert second["processed"] == 150
    assert second["finished"]


def test_failed_detail_keeps_the_same_candidate_for_next_click(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class FailsOnce(Collector):
        failed = False

        def _get_json(self, url, params=None):
            if url.endswith("/listings/1") and not self.failed:
                self.failed = True
                raise RuntimeError("temporary API failure")
            return super()._get_json(url, params)

    collector = FailsOnce([{"listings": [_summary(1)]}])
    with pytest.raises(RuntimeError, match="temporary"):
        advance_program(repo, collector, "electric", 1970, 1979)
    resumed = advance_program(repo, collector, "electric", 1970, 1979)
    assert resumed["summaries_processed"] == 1
    assert resumed["new_observations"] == 1
    assert resumed["finished"]


def test_detail_missing_filter_fields_keeps_summary_evidence(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class SparseDetail(Collector):
        def _get_json(self, url, params=None):
            if url.endswith("/listings/1"):
                return {"id": "1", "year": None, "product_type": None,
                        "make": "Fender", "model": "Stratocaster"}
            return super()._get_json(url, params)

    listing = {**_summary(1), "year": "1960s"}
    result = advance_program(repo, SparseDetail([{"listings": [listing]}]),
                             "electric", 1950, 1980)
    assert result["new_observations"] == 1
    assert result["missing_year"] == 0
    assert _year_matches({"year": "60s"}, 1950, 1980)
    assert not _year_matches({"year": "1960s"}, 1960, 1965)


def test_reverb_full_name_and_apostrophe_decade_are_accepted(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class ReverbStyleDetail(Collector):
        def _get_json(self, url, params=None):
            result = super()._get_json(url, params)
            if url.endswith("/listings/1"):
                result["product_type"] = None
                result["categories"] = [{"full_name": "Guitars / Electric Guitars"}]
                result["year"] = "1960's"
            if url.endswith("/listings/2"):
                result["product_type"] = None
                result["categories"] = [{"full_name": "Guitars / Electric Guitars"}]
                result["year"] = "Mid-60s"
            return result

    summaries = []
    for n in (1, 2):
        summary = _summary(n)
        summary.pop("product_type")
        summary["categories"] = [{"full_name": "Guitars / Electric Guitars"}]
        summary["year"] = "1960's" if n == 1 else "Mid-60s"
        summaries.append(summary)
    result = advance_program(repo, ReverbStyleDetail([{"listings": summaries}]),
                             "electric", 1950, 1980)
    assert result["new_observations"] == 2
    assert result["skipped_category"] == 0
    assert result["missing_year"] == 0
    assert _year_matches({"year": "1950’s"}, 1950, 1980)
    assert not _year_matches({"year": "Mid-60s"}, 1960, 1965)


def test_rejected_detail_explains_year_mismatch(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class ModernDetail(Collector):
        def _get_json(self, url, params=None):
            result = super()._get_json(url, params)
            if url.endswith("/listings/1"):
                result["year"] = "2020"
            return result

    listing = _summary(1)
    del listing["year"]
    result = advance_program(repo, ModernDetail([{"listings": [listing]}]),
                             "electric", 1950, 1980)
    assert result["details_fetched"] == 1
    assert result["new_observations"] == 0
    assert result["skipped_year"] == 1
    assert result["rejected_samples"][0]["reason"] == "skipped_year"
    assert result["rejected_samples"][0]["detail_year"] == "2020"


def _seed(repo, listing_id, serial):
    data = {"manufacturer": "Fender", "model": "Stratocaster",
            "serial_number": serial, "owner_name": "Reverb Shop",
            "owner_type": "shop", "location_country": "US", "location_region": "CA",
            "year": "1974", "source_site": "reverb",
            "source_url": f"https://reverb.com/item/{listing_id}",
            "source_listing_id": listing_id}
    provenance = {"source_site": "reverb", "source_listing_id": listing_id,
                  "source_url": data["source_url"], "observed_at": "2026-09-25T00:00:00Z"}
    return repo.persist_reverb_listing_claim(data, provenance)["individual_id"]


def test_two_missing_checks_release_only_reverb_owner(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    external_id = _seed(repo, "11", "524436")
    user_owned_id = _seed(repo, "22", "524437")
    user_id = repo.create_user("Owner")
    repo.create_ownership_claim(user_id, user_owned_id,
                                ownership_kind="acquire", occurred_at="2026-09-26")
    collector = Collector(status="missing")
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["missing_first_check"] == 2
    assert first["unavailable_claims"] == 0
    with repo.connect() as con:
        assert con.execute("SELECT current_owner_name FROM individuals WHERE id = ?",
                           (external_id,)).fetchone()[0] == "Reverb Shop"
        two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        con.execute("UPDATE crawl_listing_checks SET checked_at = ?, missing_since = ?",
                    (two_days_ago, two_days_ago))
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["unavailable_claims"] == 2
    assert second["owners_unknown"] == 1
    with repo.connect() as con:
        external = con.execute(
            "SELECT current_owner_name, location_country FROM individuals WHERE id = ?",
            (external_id,),
        ).fetchone()
        member = con.execute(
            "SELECT current_owner_user_id FROM individuals WHERE id = ?",
            (user_owned_id,),
        ).fetchone()
        assert tuple(external) == ("Unknown", None)
        assert int(member["current_owner_user_id"]) == user_id
        assert con.execute(
            "SELECT COUNT(*) FROM claims WHERE individual_id = ? AND "
            "ownership_source = 'automation' AND ownership_kind = 'release'",
            (external_id,),
        ).fetchone()[0] == 1


def test_rejects_external_pagination_link():
    collector = Collector()
    assert collector.safe_api_url("https://reverb.com/api/listings?page=2") == (
        "https://reverb.com/api/listings?page=2"
    )
    with pytest.raises(ValueError, match="Unexpected"):
        collector.safe_api_url("https://other.example/api/listings")


def test_relisting_after_unavailable_uses_acquire_claim(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    guitar_id = _seed(repo, "11", "524436")
    first = repo.record_reverb_unavailable("11")
    assert first["owner_released"]
    data = {"manufacturer": "Fender", "model": "Stratocaster",
            "serial_number": "524436", "owner_name": "New Shop", "owner_type": "shop",
            "location_country": "US", "location_region": "NY",
            "source_site": "reverb", "source_listing_id": "33",
            "source_url": "https://reverb.com/item/33"}
    provenance = {"source_site": "reverb", "source_listing_id": "33",
                  "source_url": data["source_url"], "observed_at": utcnow()}
    relisted = repo.persist_reverb_listing_claim(data, provenance)
    assert relisted["individual_id"] == guitar_id
    with repo.connect() as con:
        snapshot = con.execute(
            "SELECT current_owner_name, location_region FROM individuals WHERE id = ?",
            (guitar_id,),
        ).fetchone()
        assert tuple(snapshot) == ("New Shop", "NY")
        assert con.execute(
            "SELECT COUNT(*) FROM claims WHERE individual_id = ? AND claim_type = 'listing'",
            (guitar_id,),
        ).fetchone()[0] == 1


def test_unmatched_observation_keeps_public_status_without_claim(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    with repo.connect() as con:
        con.execute(
            "INSERT INTO observations (source_site, source_url, source_listing_id, "
            "observed_at, created_at) VALUES ('reverb', 'https://reverb.com/item/88', "
            "'88', ?, ?)", (utcnow(), utcnow()),
        )
    collector = Collector(status="missing")
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["missing_first_check"] == 1
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with repo.connect() as con:
        con.execute("UPDATE crawl_listing_checks SET checked_at = ?, missing_since = ?",
                    (past, past))
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["confirmed_missing"] == 1
    assert second["unavailable_claims"] == 0
    with repo.connect() as con:
        assert con.execute("SELECT status FROM crawl_listing_checks WHERE "
                           "source_listing_id = '88'").fetchone()[0] == "unavailable"


def test_older_listing_absence_keeps_newer_listing_owner(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    guitar_id = _seed(repo, "11", "524436")
    newer = {"manufacturer": "Fender", "model": "Stratocaster",
             "serial_number": "524436", "owner_name": "Current Shop",
             "owner_type": "shop", "location_region": "NY",
             "source_site": "reverb", "source_listing_id": "33",
             "source_url": "https://reverb.com/item/33"}
    repo.persist_reverb_listing_claim(
        newer, {"source_site": "reverb", "source_listing_id": "33",
                "source_url": newer["source_url"], "observed_at": utcnow()},
    )
    result = repo.record_reverb_unavailable("11")
    assert result["created"] and not result["owner_released"]
    with repo.connect() as con:
        row = con.execute(
            "SELECT current_owner_name, location_region FROM individuals WHERE id = ?",
            (guitar_id,),
        ).fetchone()
        assert tuple(row) == ("Current Shop", "NY")
