import tempfile
import unittest
from pathlib import Path

from ygc.crawl_detail_cache import save_detail
from ygc.db.repository import Repository
from ygc.specification_extractor import extract_specifications


class CachedSpecificationBackfillTest(unittest.TestCase):
    def test_new_listing_creates_positive_specification_not_relisting(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "chronicle.db")
            repo.init_db()
            claim = {"manufacturer": "Fender", "model": "Mustang", "finish": "Natural",
                     "year": "1974", "serial_number": "ABC-123", "owner_name": "Shop",
                     "owner_type": "shop", "source_site": "reverb", "source_listing_id": "301",
                     "source_url": "https://reverb.com/item/301", "listing_date": "2026-09-20"}
            provenance = {"source_site": "reverb", "source_listing_id": "301",
                          "source_url": "https://reverb.com/item/301", "observed_at": "2026-09-25"}
            save_detail(repo, "301", {"id": "301", "finish": "Natural",
                        "description": "Pickups: Two humbuckers\n"
                                       "Pickguard: a hairline crack near the screw."})
            result = repo.persist_reverb_listing_claim(claim, provenance)
            self.assertTrue(result["specification_claim_id"] > result["claim_id"])
            guitar = result["individual_id"]
            spec = next(row for row in repo.list_claims(guitar)
                        if row["claim_type"] == "specification")
            self.assertEqual(spec["verification_status"], "positive")
            self.assertEqual(spec["source_listing_id"], "301")
            self.assertEqual({row["field_name"] for row in repo.list_current_specifications(guitar)},
                             {"pickups"})
            self.assertFalse(repo.persist_reverb_listing_claim(claim, provenance)["created"])

            relist = {**claim, "source_listing_id": "302",
                      "source_url": "https://reverb.com/item/302"}
            new_provenance = {**provenance, "source_listing_id": "302",
                              "source_url": "https://reverb.com/item/302"}
            save_detail(repo, "302", {"id": "302", "description": "Bridge: Fixed"})
            second = repo.persist_reverb_listing_claim(relist, new_provenance)
            self.assertEqual(second["individual_id"], guitar)
            self.assertEqual(second["claim_id"], max(
                row["id"] for row in repo.list_claims(guitar)))
            self.assertEqual({row["field_name"] for row in repo.list_current_specifications(guitar)},
                             {"pickups"})

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
            owner = repo.create_user("Owner")
            with repo.connect() as connection:
                connection.execute("UPDATE individuals SET current_owner_user_id=? WHERE id=?",
                                   (owner, individual_id))
            save_detail(repo, "101", {"id": "101", "description": "Weight: 3.6 kg"})
            self.assertEqual(repo.backfill_cached_specifications()["created"], 0)

    def test_rejects_prose_decoration_and_duplicate_finish(self):
        self.assertEqual(extract_specifications({
            "finish": "Natural",
            "description": "Pickguard: a hairline crack near the upper mounting screw. Original guard, still solid.\n"
                           "Pickups: Dual HiLo'Tron single-coil pickups controlled by a master volume, individual pickup volumes, and a 3-way selector.\n"
                           "Neck: Maple neck featuring a bound rosewood fingerboard with mother-of-pearl thumbnail inlays.\n"
                           "Bridge: Tune-o-matic\nWeight: 3.6 kg\nPickups: ★★★★ ·",
        }), {"bridge": "Tune-o-matic", "weight": "3.6 kg"})

    def test_repairs_only_original_automation_items_including_owned_guitar(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "chronicle.db")
            repo.init_db()
            claim = {"manufacturer": "Fender", "model": "Mustang", "finish": "Natural",
                     "year": "1974", "serial_number": "ABC-123", "owner_name": "Shop",
                     "owner_type": "shop", "source_site": "reverb", "source_listing_id": "201",
                     "source_url": "https://reverb.com/item/201", "listing_date": "2026-09-20"}
            provenance = {"source_site": "reverb", "source_listing_id": "201",
                          "source_url": "https://reverb.com/item/201", "observed_at": "2026-09-25"}
            guitar = repo.persist_reverb_listing_claim(claim, provenance)["individual_id"]
            save_detail(repo, "201", {"id": "201", "finish": "Natural",
                        "description": "Pickguard: a hairline crack near the screw.\nBridge: Tune-o-matic"})
            with repo.connect() as con:
                automation = con.execute("SELECT id FROM users WHERE display_name='Automation'").fetchone()[0]
                now = "2026-09-25"
                cursor = con.execute(
                    """INSERT INTO claims (individual_id,author_user_id,claim_type,
                       specification_kind,occurred_at,status,verification_status,created_at,updated_at)
                       VALUES (?,?,'specification','specification',?,'active','positive',?,?)""",
                    (guitar, automation, now, now, now),
                )
                claim_id = cursor.lastrowid
                original = {"finish": "Natural", "pickguard": "a hairline crack near the screw.",
                            "bridge": "Tune-o-matic"}
                import json
                con.execute("""INSERT INTO claim_specification_source
                    (claim_id,source_site,source_listing_id,source_url,captured_at,extracted_json)
                    VALUES (?,'reverb','201','https://reverb.com/item/201',?,?)""",
                    (claim_id, now, json.dumps(original)),
                )
                for field, value in original.items():
                    con.execute("""INSERT INTO claim_spec_items
                        (claim_id,field_name,value_text,created_at) VALUES (?,?,?,?)""",
                        (claim_id, field, value, now),
                    )
            owner = repo.create_user("Owner")
            with repo.connect() as con:
                con.execute("UPDATE individuals SET current_owner_user_id=? WHERE id=?", (owner, guitar))
            result = repo.backfill_cached_specifications()
            self.assertEqual((result["corrected_items"], result["created"]), (2, 0))
            self.assertEqual({row["field_name"] for row in repo.list_current_specifications(guitar)},
                             {"bridge"})
            self.assertEqual(repo.backfill_cached_specifications()["corrected_items"], 0)


if __name__ == "__main__":
    unittest.main()
