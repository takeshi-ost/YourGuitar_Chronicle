"""Shared profile visibility for materialized ownership links (ug alias)."""
VISIBLE_SQL = """
(ug.ownership_status <> 'former_owner'
                           OR EXISTS (
                               SELECT 1 FROM claims c
                               WHERE c.individual_id=ug.individual_id
                                 AND c.author_user_id=ug.user_id
                                 AND c.claim_type='ownership'
                                 AND c.ownership_kind='acquire'
                                 AND c.status='active'
                                 AND c.verification_status='positive'
                           )
                           OR EXISTS (
                               SELECT 1 FROM claims c
                               JOIN claim_listing_items li ON li.claim_id=c.id
                               WHERE c.individual_id=ug.individual_id
                                 AND c.claim_type='listing'
                                 AND c.status='active'
                                 AND c.verification_status='positive'
                                 AND li.field_name='owner_user_id'
                                 AND li.value_text=CAST(ug.user_id AS TEXT)
                           )
                           OR EXISTS (SELECT 1 FROM claim_transfers t JOIN claims tc ON tc.id=t.claim_id
                               JOIN claim_transfer_acceptance e ON e.claim_id=tc.id
                               WHERE tc.individual_id=ug.individual_id AND t.to_user_id=ug.user_id
                                 AND t.state='accepted')
                           OR NOT EXISTS (
                               SELECT 1 FROM claims c
                               WHERE c.individual_id=ug.individual_id
                                 AND c.author_user_id=ug.user_id
                                 AND c.claim_type='ownership'
                                 AND c.ownership_kind='acquire'
                                 AND c.ownership_source='former_owner'
                           ))
"""
