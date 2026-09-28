import tempfile
import unittest
from pathlib import Path

from ygc.crawl_detail_cache import save_detail
from ygc.db.repository import Repository
from ygc.specification_extractor import extract_specifications


class CachedSpecificationBackfillTest(unittest.TestCase):
    def test_explicit_values_only_and_ownerless_idempotent_backfill(self):
        self.assertEqual(
            extract_specifications({"description": "<p>Pickups: Two humbuckers</p>"
                                    "<p>May have a vintage bridge.</p>"}),
            {"pickups": "Two humbuckers"},
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "chronicle.db")
            repo.init_db()
            claim = {
                "manufacturer": "Fender", "model": "Stratocaster", "finish": "Natural",
                "year": "1974", "serial_number": "524436", "owner_name": "Shop",
                "owner_type": "shop", "seller": "Shop", "source_site": "reverb",
                "source_listing_id": "101", "source_url": "https://reverb.com/item/101",
                "listing_date": "2026-09-20", "serial_confidence": .99,
            }
            provenance = {
                "source_site": "reverb", "source_listing_id": "101",
                "source_url": "https://reverb.com/item/101",
                "observed_at": "2026-09-25", "listing_date": "2026-09-20",
                "title": "Test", "raw_text": "Serial 524436", "serial_confidence": .99,
                "extraction_version": "test", "created_at": "2026-09-25",
            }
            individual_id = repo.persist_reverb_listing_claim(claim, provenance)["individual_id"]
            save_detail(repo, "101", {"id": "101", "description":
                        "Pickups: Two humbuckers\nBridge: Tune-o-matic"})
            first = repo.backfill_cached_specifications()
            self.assertEqual((first["created"], first["items"]), (1, 2))
            self.assertEqual(repo.backfill_cached_specifications()["created"], 0)
            specs = repo.list_current_specifications(individual_id)
            self.assertEqual({row["field_name"] for row in specs}, {"pickups", "bridge"})
            source_claim = next(row for row in repo.list_claims(individual_id)
                                if row["claim_type"] == "specification")
            self.assertEqual(source_claim["source_listing_id"], "101")
            self.assertEqual(source_claim["verification_status"], "positive")
            with repo.connect() as connection:
                connection.execute("UPDATE individuals SET current_owner_user_id=? WHERE id=?",
                                   (repo.create_user("Owner"), individual_id))
            save_detail(repo, "101", {"id": "101", "description": "Weight: 3.6 kg"})
            self.assertEqual(repo.backfill_cached_specifications()["created"], 0)


if __name__ == "__main__":
    unittest.main()
