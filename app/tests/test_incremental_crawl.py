from datetime import datetime, timedelta, timezone

import pytest

from ygc.collectors.reverb import ReverbAPICollector
from ygc.db.repository import Repository
from ygc.db.repository import utcnow
from ygc.incremental_crawl import advance_program, restart_program
from ygc.incremental_crawl import MAX_SUMMARIES
from ygc.incremental_crawl import _year_matches, _year_span


@pytest.mark.parametrize("value, expected", [
    ("‘67-‘69", (1967, 1969)),
    ("'70-'80", (1970, 1980)),
    ("80-84", (1980, 1984)),
    ("‘67–‘69", (1967, 1969)),
    ("1967-69", (1967, 1969)),
    ("1998-02", (1998, 2002)),
    ("69-67", None),
    ("20-24", None),
])
def test_abbreviated_manufacture_year_ranges(value, expected):
    assert _year_span({"year": value}) == expected


def test_abbreviated_range_must_fit_entire_search_interval():
    assert _year_matches({"year": "‘67-‘69"}, 1950, 1980)
    assert _year_matches({"year": "'70-'80"}, 1950, 1980)
    assert not _year_matches({"year": "80-84"}, 1950, 1980)
    assert not _year_matches({"year": "1967-69"}, 1967, 1967)


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


def test_summary_budget_continues_mid_page(tmp_path, monkeypatch):
    monkeypatch.setattr("ygc.incremental_crawl.MAX_SUMMARIES", 6)
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
    assert first["summaries_processed"] == 6
    assert first["details_fetched"] == 6
    assert not first["finished"]
    repo.init_db()
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["listing_pages_fetched"] == 0
    assert second["summaries_processed"] == 1
    assert second["processed"] == 7
    assert second["finished"]


def test_production_budget_handles_more_than_hundred_details_in_one_click(tmp_path):
    assert MAX_SUMMARIES == 2000
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()
    collector = Collector([
        {"listings": [_summary(n) for n in range(1, 121)],
         "_links": {"next": {"href": "https://api.reverb.com/api/listings?page=2"}}},
        {"listings": [_summary(n) for n in range(121, 151)]},
    ])
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["summaries_processed"] == 150
    assert first["details_fetched"] == 150
    assert first["new_observations"] == 150
    assert first["finished"]
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["summaries_processed"] == 0
    assert second["new_observations"] == 0
    assert second["processed"] == 150
    assert second["finished"]


def test_more_than_five_pages_are_processed(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class ManyPages(Collector):
        def _get_json(self, url, params=None):
            if url.endswith("/listings") or "?page=" in url:
                page = int(url.split("?page=")[-1]) if "?page=" in url else 1
                payload = {"listings": [_summary(page)]}
                if page < 6:
                    payload["_links"] = {"next": {"href":
                        f"https://api.reverb.com/api/listings?page={page + 1}"}}
                return payload
            return super()._get_json(url, params)

    result = advance_program(repo, ManyPages(), "electric", 1970, 1979)
    assert result["listing_pages_fetched"] == 6
    assert result["summaries_processed"] == 6
    assert result["details_fetched"] == 6
    assert result["finished"]


def test_two_thousand_summary_limit_resumes_on_next_click(tmp_path):
    repo = Repository(tmp_path / "ygc.db")
    repo.init_db()

    class ManySummaryPages(Collector):
        def _get_json(self, url, params=None):
            if url.endswith("/listings") or "?page=" in url:
                page = int(url.split("?page=")[-1]) if "?page=" in url else 1
                payload = {"listings": [{**_summary(n), "year": "2020"}
                            for n in range((page - 1) * 24 + 1,
                                           min(page * 24, 2001) + 1)]}
                if page < 84:
                    payload["_links"] = {"next": {"href":
                        f"https://api.reverb.com/api/listings?page={page + 1}"}}
                return payload
            return super()._get_json(url, params)

    collector = ManySummaryPages()
    first = advance_program(repo, collector, "electric", 1970, 1979)
    assert first["summaries_processed"] == 2000
    assert first["details_fetched"] == 0
    assert not first["finished"]
    second = advance_program(repo, collector, "electric", 1970, 1979)
    assert second["summaries_processed"] == 1
    assert second["processed"] == 2001
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
                        "make": "Fender", "model": "Stratocaster",
                        "description": "Serial number 524436"}
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
    with repo.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM crawl_detail_cache").fetchone()[0] == 1
    # Expanding the range uses the retained detail, without another API call.
    from ygc.crawl_detail_cache import reprocess_details
    retried = reprocess_details(repo, "electric", 2000, 2030)
    assert retried["new_individuals"] == 1


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


def test_two_missing_checks_create_lost_only_for_current_reverb_owner(tmp_path):
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
    assert second["confirmed_missing"] == 2
    assert second["unavailable_claims"] == 1
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
            "SELECT COUNT(*) FROM crawl_listing_checks WHERE status = 'unavailable' "
            "AND source_listing_id IN ('11', '22')"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM claims WHERE individual_id = ? AND "
            "(claim_type = 'event' OR (ownership_source = 'automation' "
            "AND ownership_kind = 'lost'))", (user_owned_id,),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM claims WHERE individual_id = ? AND "
            "ownership_source = 'automation' AND ownership_kind = 'lost'",
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
    assert first["owner_lost"]
    assert next(c for c in repo.list_claims(guitar_id) if c['id'] == first['claim_id'])['ownership_kind'] == 'lost'
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


@pytest.mark.parametrize('event_date', ['2026-09-28', '2030-01-01'])
def test_lost_is_automation_only_and_admin_can_redecide(tmp_path, monkeypatch, event_date):
    # Lost records a timestamp while manual Acquire records only a date.
    # Freeze the clock so they stay on the same day regardless of the test date.
    monkeypatch.setattr('ygc.db.repository.utcnow', lambda: event_date + 'T23:59:59Z')
    repo = Repository(tmp_path / 'lost.db')
    repo.init_db()
    individual_id = _seed(repo, '11', '524436')
    lost_id = repo.record_reverb_unavailable('11')['claim_id']
    automation_id = next(c for c in repo.list_claims(individual_id)
                         if c['id'] == lost_id)['author_user_id']
    user_id = repo.create_user('Owner')
    with pytest.raises(ValueError, match='ownership_kind'):
        repo.create_ownership_claim(user_id, individual_id,
                                    ownership_kind='lost', occurred_at=event_date)
    _, acquire_id = repo.create_ownership_claim(user_id, individual_id,
                                ownership_kind='acquire', occurred_at=event_date)
    assert lost_id < acquire_id
    claims = repo.list_claims(individual_id)
    assert [c['id'] for c in claims if c['id'] in (lost_id, acquire_id)] == [lost_id, acquire_id]
    diagnostic = repo.observation_diagnostic(individual_id)
    assert [r['claim_id'] for r in diagnostic['matrix']['rows']
            if r['claim_id'] in (lost_id, acquire_id)] == [lost_id, acquire_id]
    assert diagnostic['differences'] == {}
    assert lost_id not in repo.owner_verifiable_claim_ids(individual_id, user_id)
    with pytest.raises(ValueError, match='Verification'):
        repo.set_claim_response(lost_id, user_id, 'negative')
    with pytest.raises(ValueError, match='cannot be edited'):
        repo.update_claim(lost_id, automation_id, occurred_at='2026-09-29')
    with pytest.raises(ValueError, match='cannot be deactivated'):
        repo.deactivate_claim(lost_id, automation_id)
    assert repo.get_individual(individual_id)[0]['current_owner_user_id'] == user_id
    repo.admin_moderate_claim(lost_id, 'negative')
    assert repo.get_individual(individual_id)[0]['current_owner_user_id'] == user_id
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


def test_existing_automation_release_keeps_its_snapshot_and_prevents_duplicate_lost(tmp_path):
    repo = Repository(tmp_path / 'legacy-release.db')
    repo.init_db()
    individual_id = _seed(repo, '11', '524436')
    claim_id = repo.record_reverb_unavailable('11')['claim_id']
    with repo.connect() as con:
        con.execute("UPDATE claims SET ownership_kind='release' WHERE id=?", (claim_id,))
    assert repo.rebuild_individual_snapshot(individual_id)['current_owner_name'] == 'Unknown'
    assert repo.record_reverb_unavailable('11')['reason'] == 'already_recorded'
    assert repo.observation_diagnostic(individual_id)['differences'] == {}


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
    assert result == {"created": False, "reason": "not_current_external_source"}
    with repo.connect() as con:
        row = con.execute(
            "SELECT current_owner_name, location_region FROM individuals WHERE id = ?",
            (guitar_id,),
        ).fetchone()
        assert tuple(row) == ("Current Shop", "NY")
        assert con.execute(
            "SELECT COUNT(*) FROM claims WHERE target_claim_id = "
            "(SELECT c.id FROM claims c JOIN claim_source_evidence e ON e.claim_id = c.id "
            "WHERE e.source_site = 'reverb' AND e.source_listing_id = '11')"
        ).fetchone()[0] == 0


def test_run_log_tracks_each_stage_and_survives_restart(tmp_path):
    repo = Repository(tmp_path / 'ygc.db')
    repo.init_db()
    stages = []
    collector = Collector([{'listings': [_summary(1),
        {**_summary(2), 'year': '2020'}]}])
    result = advance_program(repo, collector, 'electric', 1970, 1979,
                             progress_callback=lambda c: stages.append(c))
    assert result['summaries_processed'] == 2
    assert result['details_fetched'] == 1
    assert result['detail_scope_matched'] == 1
    assert result['serial_candidates'] == 1
    assert result['new_individuals'] == 1
    assert {'listing', 'matching', 'availability', 'done'} <= {s['phase'] for s in stages}
    repo.init_db()
    log = repo.crawl_run_log('electric', 1970, 1979)
    assert len(log) == 1
    assert log[0]['status'] == 'ok'
    assert log[0]['counts']['new_individuals'] == 1
    assert log[0]['counts']['skipped_year'] == 1
    assert repo.crawl_run_log('acoustic', 1970, 1979) == []


def test_failed_run_keeps_partial_counts_in_log(tmp_path):
    repo = Repository(tmp_path / 'ygc.db')
    repo.init_db()
    class Broken(Collector):
        def _get_json(self, url, params=None):
            if url.endswith('/listings/2'):
                raise RuntimeError('detail unavailable')
            return super()._get_json(url, params)
    with pytest.raises(RuntimeError):
        advance_program(repo, Broken([{'listings': [_summary(1), _summary(2)]}]),
                        'electric', 1970, 1979)
    run = repo.crawl_run_log('electric', 1970, 1979)[0]
    assert run['status'] == 'error'
    assert run['phase'] == 'error'
    assert run['counts']['summaries_processed'] == 1
    assert run['counts']['details_fetched'] == 1
