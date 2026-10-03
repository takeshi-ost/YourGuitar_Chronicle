from ygc.crawl_service import crawl_query
from ygc.db.repository import Repository


class Collector:
    details_requested = 0

    def listing_id(self, item):
        return str(item["id"])

    def iter_listing_summaries(self, **kwargs):
        return [
            {"id": 1, "make": "Fender", "model": "Stratocaster",
             "product_type": "electric-guitars", "year": "1974", "title": "1974 Fender Stratocaster",
             "description": "Serial number 524436",
             "_links": {"web": {"href": "https://reverb.example/1"}}},
            {"id": 2, "make": "Fender", "model": "Stratocaster",
             "year": "2020", "title": "2020 Fender Stratocaster"},
        ]

    def fetch_listing_details(self, candidates):
        self.details_requested += len(candidates)
        return candidates


def test_crawl_reuses_stored_listing_and_records_each_run(tmp_path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()
    collector = Collector()

    first = crawl_query(repository, collector, "Fender", 10, year_min=1950, year_max=1980)
    second = crawl_query(repository, collector, "Fender", 10, year_min=1950, year_max=1980)

    assert first["new_observations"] == 1
    assert first["skipped_non_target"] == 1
    assert second["new_observations"] == 0
    assert second["skipped_existing"] == 1
    assert collector.details_requested == 1
    with repository.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM crawl_runs WHERE status='ok'").fetchone()[0] == 2


def test_crawl_only_registers_serial_bearing_guitars(tmp_path):
    repository = Repository(tmp_path / "chronicle.db")
    repository.init_db()

    class NoSerial(Collector):
        def iter_listing_summaries(self, **kwargs):
            return [{"id": 3, "make": "Fender", "model": "Stratocaster",
                     "product_type": "electric-guitars", "year": "1974", "title": "1974 Stratocaster"}]

    collector = NoSerial()
    first = crawl_query(repository, collector, "Fender", 10, year_min=1950, year_max=1980)
    second = crawl_query(repository, collector, "Fender", 10, year_min=1950, year_max=1980)
    assert first["missing_identity"] == 1
    assert first["new_individuals"] == 0
    assert second["skipped_existing"] == 1
    with repository.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
