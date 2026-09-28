import tempfile
import unittest
from pathlib import Path

from ygc.crawl_detail_cache import save_detail
from ygc.db.repository import Repository


class ObservationMatrixTest(unittest.TestCase):
    def test_claim_proposals_order_and_current_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / 'chronicle.db')
            repo.init_db()
            save_detail(repo, '401', {'id': '401', 'description': 'Pickups: P90'})
            listing = repo.persist_reverb_listing_claim({
                'manufacturer': 'Gibson', 'model': 'Les Paul', 'finish': 'Goldtop',
                'year': '1956', 'serial_number': 'A-123', 'owner_name': 'Shop',
                'owner_type': 'shop', 'location_country': 'US',
                'source_site': 'reverb', 'source_listing_id': '401',
                'source_url': 'https://reverb.com/item/401', 'listing_date': '2026-09-20',
            }, {
                'source_site': 'reverb', 'source_listing_id': '401',
                'source_url': 'https://reverb.com/item/401',
                'observed_at': '2026-09-20', 'listing_date': '2026-09-20',
            })
            guitar = listing['individual_id']
            owner = repo.create_user('Owner')
            other = repo.create_user('Other')
            _, acquire = repo.create_ownership_claim(
                owner, guitar, ownership_kind='acquire', occurred_at='2026-09-21')
            pending_spec = repo.create_specification_claim_group(
                other, guitar, specification_kind='specification',
                items=[{'field_name': 'pickups', 'value_text': 'Humbuckers'}],
                occurred_at='2026-09-22')
            _, release = repo.create_ownership_claim(
                owner, guitar, ownership_kind='release', occurred_at='2026-09-23')
            diagnostic = repo.observation_diagnostic(guitar)
            matrix = diagnostic['matrix']
            self.assertEqual(diagnostic['differences'], {})
            self.assertEqual([row['claim_id'] for row in matrix['rows']],
                             [listing['claim_id'], listing['specification_claim_id'],
                              acquire, pending_spec, release])
            self.assertIn('spec:pickups', [col['key'] for col in matrix['columns']])
            rows = {row['claim_id']: row for row in matrix['rows']}
            self.assertTrue(rows[listing['claim_id']]['cells']['manufacturer']['adopted'])
            self.assertFalse(rows[acquire]['cells']['current_owner_name']['adopted'])
            self.assertEqual(rows[release]['cells']['current_owner_name']['value'], 'Unknown')
            self.assertTrue(rows[release]['cells']['location_country']['adopted'])
            self.assertIsNone(rows[release]['cells']['location_country']['value'])
            self.assertTrue(rows[listing['specification_claim_id']]['cells']['spec:pickups']['adopted'])
            self.assertFalse(rows[pending_spec]['cells']['spec:pickups']['adopted'])
            self.assertEqual(matrix['current']['current_owner_name'], 'Unknown')
            self.assertEqual(matrix['current']['spec:pickups'], 'P90')
            self.assertNotIn('year', rows[pending_spec]['cells'])


if __name__ == '__main__':
    unittest.main()
