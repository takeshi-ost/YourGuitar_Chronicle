"""Private summaries for unresolved ownership requests."""
from ygc import acquire_review


def for_user(repository, user_id):
    with repository.connect() as con:
        if not acquire_review.available_user(con, user_id):
            raise PermissionError('This account cannot view requests.')
        transfers = [dict(row) for row in con.execute("""
            SELECT t.claim_id,c.individual_id,u.display_name AS recipient_name,
                   i.manufacturer,i.model,i.serial_number
            FROM claim_transfers t JOIN claims c ON c.id=t.claim_id
            JOIN individuals i ON i.id=c.individual_id JOIN users u ON u.id=t.to_user_id
            WHERE t.from_user_id=? AND t.state='pending' AND c.status='active'
            ORDER BY c.created_at,c.id""", (user_id,))]
    applications = []
    for row in acquire_review.list_for(repository,user_id):
        ongoing = row['status'] in ('draft','pending','processing','error') or (row['status']=='accepted' and row.get('verification_status')=='unverified')
        if ongoing:
            applications.append({key:row.get(key) for key in (
                'revision','request_kind','status','verification_status','original_individual_id',
                'individual_id','product_name','expires_at','unread_result')})
    return {'applications':applications,'outgoing_transfers':transfers,'transfer_results':[]}
