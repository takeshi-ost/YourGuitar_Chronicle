"""Private Acquire disputes, atomic decisions and ownership mutation guards."""
from datetime import datetime, timezone, timedelta
import os
from ygc.db.repository import utcnow
from ygc.observation_evaluator import evaluate_observation

WAIT_DAYS = max(1, int(os.getenv('YGC_DISPUTE_WAIT_DAYS', '14')))
MAX_BYTES = 12 * 1024 * 1024


def current_round(con, case_id):
    return con.execute('SELECT * FROM ownership_dispute_rounds WHERE dispute_id=? ORDER BY number DESC LIMIT 1',(case_id,)).fetchone()


def new_round(con, case, reason=''):
    previous=current_round(con,case['id'])
    number=previous['number']+1 if previous else 1
    rid=con.execute("INSERT INTO ownership_dispute_rounds(dispute_id,number,phase,request_reason,created_at) VALUES (?,?,'collecting',?,?)",
        (case['id'],number,reason,utcnow())).lastrowid
    for link in con.execute('SELECT * FROM ownership_dispute_claims WHERE dispute_id=?',(case['id'],)).fetchall():
        for user in {case['owner_id'],link['applicant_id']}:
            con.execute('INSERT INTO ownership_dispute_round_parties(round_id,claim_id,user_id) VALUES (?,?,?)',(rid,link['claim_id'],user))
    return current_round(con,case['id'])


def advance_round(con, round_id):
    if not con.execute('SELECT 1 FROM ownership_dispute_round_parties WHERE round_id=? AND submitted_at IS NULL',(round_id,)).fetchone():
        con.execute("UPDATE ownership_dispute_rounds SET phase='reviewing' WHERE id=?",(round_id,))


def migrate_rounds(con):
    # Preserve legacy evidence; multiple earlier submissions count as one completed turn.
    for case in con.execute('SELECT * FROM ownership_disputes WHERE id NOT IN (SELECT dispute_id FROM ownership_dispute_rounds)').fetchall():
        rnd=new_round(con,case)
        for evidence in con.execute('SELECT * FROM ownership_dispute_evidence WHERE dispute_id=? ORDER BY id',(case['id'],)).fetchall():
            con.execute('INSERT INTO ownership_dispute_round_evidence VALUES (?,?)',(evidence['id'],rnd['id']))
            con.execute('UPDATE ownership_dispute_round_parties SET submitted_at=? WHERE round_id=? AND claim_id=? AND user_id=?',
                (evidence['created_at'],rnd['id'],evidence['claim_id'],evidence['author_id']))
        advance_round(con,rnd['id'])


def round_view(con,case,user=None,admin=False,rnd=None):
    if rnd is None:rnd=current_round(con,case['id'])
    if not rnd:return None
    result=dict(rnd)
    result['parties']=[dict(p) for p in con.execute('SELECT * FROM ownership_dispute_round_parties WHERE round_id=?',(rnd['id'],))
        if admin or user==case['owner_id'] or con.execute('SELECT 1 FROM ownership_dispute_claims WHERE claim_id=? AND applicant_id=?',(p['claim_id'],user)).fetchone()]
    return result


def available(con, user):
    if not con.execute("SELECT 1 FROM users WHERE id=? AND account_type<>'source' AND ban_status='normal'", (user,)).fetchone():
        raise PermissionError('An active user account is required')


def active(con, individual):
    return con.execute("SELECT * FROM ownership_disputes WHERE individual_id=? AND status='open'", (individual,)).fetchone()


def guard(con, individual, claim=None):
    if active(con, individual):
        raise ValueError('Under dispute: ownership changes are paused')
    if claim and con.execute('SELECT 1 FROM ownership_dispute_claims WHERE claim_id=?', (claim,)).fetchone():
        raise ValueError('This Claim requires an administrator dispute reconsideration')


def candidate(con, claim_id):
    return con.execute("""SELECT c.*,c.created_at AS requested_at FROM claims c
        JOIN acquire_applications a ON a.claim_id=c.id AND a.status='accepted' AND a.request_kind='acquire'
        WHERE c.id=? AND c.status='active' AND c.claim_type='ownership'
        AND c.ownership_kind='acquire' AND COALESCE(c.ownership_source,'') NOT IN
        ('former_owner','automation','merged_listing')""", (claim_id,)).fetchone()


def eligible(con, claim):
    if not claim or con.execute('SELECT 1 FROM ownership_dispute_claims WHERE claim_id=?', (claim['id'],)).fetchone():
        return False
    owner = con.execute("SELECT u.* FROM individuals i JOIN users u ON u.id=i.current_owner_user_id WHERE i.id=? AND u.account_type<>'source'", (claim['individual_id'],)).fetchone()
    if not owner or owner['id'] == claim['author_user_id']:
        return False
    # Test the actual evaluator, not an approximation of Claim date/ID ordering.
    con.execute('SAVEPOINT dispute_eligibility')
    try:
        con.execute("UPDATE ownership_disputes SET status='checking' WHERE individual_id=? AND status='open'", (claim['individual_id'],))
        con.execute("UPDATE claims SET verification_status='positive',admin_verification=1 WHERE id=?", (claim['id'],))
        value = evaluate_observation(con, claim['individual_id']).values['current_owner_user_id']
        return str(value) == str(claim['author_user_id'])
    finally:
        con.execute('ROLLBACK TO dispute_eligibility')
        con.execute('RELEASE dispute_eligibility')


def record_decline(con, claim_id, owner, reason):
    claim = candidate(con, claim_id)
    if not eligible(con, claim):
        return
    reason = (reason or '').strip()
    if not reason or len(reason)>4000:
        raise ValueError('A decline reason (1–4,000 characters) is required and will be shared with the applicant')
    con.execute("""INSERT INTO ownership_declines(claim_id,owner_id,reason,created_at) VALUES (?,?,?,?)
        ON CONFLICT(claim_id) DO UPDATE SET owner_id=excluded.owner_id,reason=excluded.reason,
        created_at=excluded.created_at,acknowledged_at=NULL""", (claim_id,owner,reason,utcnow()))
    con.execute("""INSERT INTO notifications(recipient_user_id,actor_user_id,notification_type,individual_id,
        claim_id,title,body,created_at) VALUES (?,?,'ownership_decline',?,?,'Acquire declined',?,?)""",
        (claim['author_user_id'],owner,claim['individual_id'],claim_id,reason,utcnow()))


def participants(con, case):
    return {case['owner_id']} | {r[0] for r in con.execute('SELECT applicant_id FROM ownership_dispute_claims WHERE dispute_id=?',(case['id'],))}


def get_case(con, case_id, user=None, admin=False):
    case=con.execute('SELECT * FROM ownership_disputes WHERE id=?',(case_id,)).fetchone()
    if not case: raise ValueError('Dispute not found')
    if not admin:
        available(con,user)
        if user not in participants(con,case): raise PermissionError('Only dispute participants may access this case')
    return case


def event(con, case, kind, note, user=None):
    con.execute('INSERT INTO ownership_dispute_events(dispute_id,actor_id,kind,note,created_at) VALUES (?,?,?,?,?)', (case['id'],user,kind,note,utcnow()))
    con.execute('UPDATE ownership_disputes SET version=version+1,updated_at=? WHERE id=?',(utcnow(),case['id']))
    for recipient in participants(con,case):
        if recipient==user: continue
        con.execute("""INSERT INTO notifications(recipient_user_id,actor_user_id,notification_type,individual_id,title,body,created_at)
          VALUES (?,?,'ownership_dispute',?,'Ownership dispute updated',?,?)""",(recipient,user,case['individual_id'],note,utcnow()))


def validate_submission(explanation,summary,content,filename):
    if not explanation.strip() or len(explanation)>8000 or not summary.strip() or len(summary)>4000:
        raise ValueError('Provide an explanation (up to 8,000 characters) and a summary (up to 4,000 characters)')
    if len(content)>MAX_BYTES: raise ValueError('The attachment must be at most 12 MB')
    if content:
        if content.startswith(b'%PDF-'): return content, 'application/pdf', 'document.pdf'
        from ygc.authentication_evidence import prepare_image
        import base64
        image=prepare_image(content)
        # prepare_image returns the sanitized image payload used by authentication.
        return base64.b64decode(image['data_url'].split(',',1)[1]), 'image/jpeg', 'photo.jpg'
    return b'',None,None


def add_evidence(con,case,claim_id,user,explanation,summary,content,mime,filename,expected_round=None,*,evidence_storage=None):
    """Append one submission using optional, explicit external original storage.

    Local callers retain the existing BYTEA/SQLite behavior. An external adapter
    supplies additional_bytes(con, case_id) and store(con, evidence_id, content,
    mime). It must persist its reference in this same transaction and must not
    delete originals on transaction failure: the commit outcome can be unknown.
    """
    if case['status']!='open': raise ValueError('Reopen the dispute before adding evidence')
    link=con.execute('SELECT * FROM ownership_dispute_claims WHERE dispute_id=? AND claim_id=?',(case['id'],claim_id)).fetchone()
    if not link or user not in (case['owner_id'],link['applicant_id']):
        raise PermissionError('Evidence must relate to your own disputed Acquire')
    rnd=current_round(con,case['id'])
    if not rnd or (expected_round is not None and expected_round!=rnd['number']):
        raise ValueError('The evidence round has changed. Refresh the dispute')
    if rnd['phase']!='collecting':raise ValueError('Under review. Wait for an additional evidence request')
    party=con.execute('SELECT submitted_at FROM ownership_dispute_round_parties WHERE round_id=? AND claim_id=? AND user_id=?',(rnd['id'],claim_id,user)).fetchone()
    if not party or party['submitted_at']:raise ValueError('Evidence already submitted for this round. Wait for an additional evidence request')
    if con.execute('SELECT COUNT(*) FROM ownership_dispute_evidence WHERE dispute_id=?',(case['id'],)).fetchone()[0]>=100:
        raise ValueError('This case has reached its 100-submission limit')
    total=con.execute('SELECT COALESCE(SUM(length(content)),0) FROM ownership_dispute_evidence WHERE dispute_id=?',(case['id'],)).fetchone()[0]
    if evidence_storage is not None:
        extra=evidence_storage.additional_bytes(con,case['id'])
        if type(extra) is not int or extra<0: raise RuntimeError('Invalid original storage accounting')
        total+=extra
    if len(content)>MAX_BYTES: raise ValueError('The attachment must be at most 12 MiB')
    if total+len(content)>256*1024*1024: raise ValueError('This case has reached its 256 MB attachment limit')
    evidence_id=con.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,claim_id,author_id,explanation,summary,
        content,content_type,filename,created_at) VALUES (?,?,?,?,?,?,?,?,?)''',
        (case['id'],claim_id,user,explanation.strip(),summary.strip(),
         (content or None) if evidence_storage is None else None,mime,filename,utcnow())).lastrowid
    if content and evidence_storage is not None:
        evidence_storage.store(con,evidence_id,content,mime)
    con.execute('INSERT INTO ownership_dispute_round_evidence VALUES (?,?)',(evidence_id,rnd['id']))
    con.execute('UPDATE ownership_dispute_round_parties SET submitted_at=? WHERE round_id=? AND claim_id=? AND user_id=?',(utcnow(),rnd['id'],claim_id,user))
    advance_round(con,rnd['id'])
    event(con,case,'evidence_submitted',f"Round {rnd['number']}: evidence submitted",user)
    if current_round(con,case['id'])['phase']=='reviewing':event(con,case,'under_review',f"Round {rnd['number']}: both parties submitted; under review")


def open_case(con,claim_id,user,explanation,summary,content,mime,filename,*,evidence_storage=None):
    available(con,user)
    claim=candidate(con,claim_id)
    if not claim or claim['author_user_id']!=user: raise PermissionError('Only the applicant can appeal this Acquire')
    if not eligible(con,claim): raise ValueError('Only an Acquire that would change the Current Owner can be disputed')
    decline=con.execute('SELECT * FROM ownership_declines WHERE claim_id=?',(claim_id,)).fetchone()
    current_owner=con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(claim['individual_id'],)).fetchone()[0]
    if decline and decline['owner_id']!=current_owner: raise ValueError('Current Owner changed; request a response from the new owner')
    if decline and decline['acknowledged_at']: raise ValueError('This decline was already accepted')
    if claim['verification_status']=='negative':
        if not decline: raise ValueError('An owner decline is required')
    elif claim['verification_status']=='unverified':
        since=datetime.fromisoformat(claim['requested_at'].replace('Z','+00:00'))
        if since.tzinfo is None: since=since.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)<since+timedelta(days=WAIT_DAYS):
            raise ValueError(f'An unanswered Acquire can be escalated after {WAIT_DAYS} days')
    else: raise ValueError('This Acquire cannot be appealed')
    if not content: raise ValueError('Additional evidence attachment is required to open a dispute')
    case=active(con,claim['individual_id'])
    if not case:
        owner=con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(claim['individual_id'],)).fetchone()[0]
        now=utcnow()
        cid=con.execute('INSERT INTO ownership_disputes(individual_id,owner_id,locked_owner_id,created_at,updated_at) VALUES (?,?,?,?,?)',(claim['individual_id'],owner,owner,now,now)).lastrowid
        case=con.execute('SELECT * FROM ownership_disputes WHERE id=?',(cid,)).fetchone()
    rnd=current_round(con,case['id'])
    if rnd and rnd['phase']=='reviewing':raise ValueError('This dispute is under review. Wait for the current round to finish')
    con.execute('INSERT INTO ownership_dispute_claims VALUES (?,?,?)',(case['id'],claim_id,user))
    if not rnd:rnd=new_round(con,case)
    else:
        for participant in {case['owner_id'],user}:
            con.execute('INSERT INTO ownership_dispute_round_parties(round_id,claim_id,user_id) VALUES (?,?,?)',(rnd['id'],claim_id,participant))
    event(con,case,'opened','Under dispute: ownership changes are paused',user)
    add_evidence(con,case,claim_id,user,explanation,summary,content,mime,filename,evidence_storage=evidence_storage)
    return case['id']


def detail(con,case_id,user=None,admin=False):
    case=get_case(con,case_id,user,admin)
    result=dict(case)
    result['round']=round_view(con,case,user,admin)
    result['rounds']=[round_view(con,case,user,admin,r) for r in con.execute('SELECT * FROM ownership_dispute_rounds WHERE dispute_id=? ORDER BY number',(case_id,)).fetchall()]
    result['claims']=[dict(r) for r in con.execute('''SELECT dc.*,u.display_name AS applicant_name,d.reason AS decline_reason,COALESCE(a.submitted_at,a.created_at,c.created_at) AS requested_at
       FROM ownership_dispute_claims dc JOIN users u ON u.id=dc.applicant_id JOIN claims c ON c.id=dc.claim_id LEFT JOIN acquire_applications a ON a.claim_id=c.id
       LEFT JOIN ownership_declines d ON d.claim_id=dc.claim_id WHERE dc.dispute_id=?''',(case_id,))]
    result['owner_name']=con.execute('SELECT display_name FROM users WHERE id=?',(case['owner_id'],)).fetchone()[0]
    owner=con.execute('SELECT u.id,u.display_name FROM individuals i LEFT JOIN users u ON u.id=i.current_owner_user_id WHERE i.id=?',(case['individual_id'],)).fetchone()
    result['current_owner_name']=owner['display_name'] if owner else None
    # Other applicants are not entitled to each other's evidence or summaries.
    allowed={r['claim_id'] for r in result['claims'] if admin or user in (case['owner_id'],r['applicant_id'])}
    result['claims']=[r for r in result['claims'] if r['claim_id'] in allowed]
    evidence=[]
    for r in con.execute('SELECT * FROM ownership_dispute_evidence WHERE dispute_id=? ORDER BY id',(case_id,)):
        if r['claim_id'] not in allowed: continue
        item={k:r[k] for k in ('id','claim_id','author_id','created_at','published_summary','published_at')}
        rnd=con.execute('SELECT r.number FROM ownership_dispute_rounds r JOIN ownership_dispute_round_evidence e ON e.round_id=r.id WHERE e.evidence_id=?',(r['id'],)).fetchone()
        item['round_number']=rnd[0] if rnd else 1
        if admin or r['author_id']==user:
            item.update({k:r[k] for k in ('explanation','summary','filename','content_type')})
            item['has_attachment']=bool(r['content'])
        elif not r['published_at']: continue
        evidence.append(item)
    result['evidence']=evidence
    result['events']=[dict(r) for r in con.execute('SELECT id,kind,note,created_at FROM ownership_dispute_events WHERE dispute_id=? ORDER BY id',(case_id,))]
    # Legacy requests migrated into round 1 must not create extra round boundaries.
    count=max(0,len(result['rounds'])-1)
    starts=[e['id'] for e in result['events'] if e['kind'] in ('request_evidence','reopened')]
    boundaries=set(starts[-count:]) if count else set()
    number=1
    for entry in result['events']:
        if entry['id'] in boundaries:number+=1
        entry['round_number']=number
    return result


def listing(con,user=None,admin=False):
    if not admin: available(con,user)
    result=[]
    for case in con.execute('SELECT d.*,i.manufacturer,i.model,i.serial_number FROM ownership_disputes d JOIN individuals i ON i.id=d.individual_id ORDER BY d.updated_at DESC'):
        if admin or user in participants(con,case):
            item=dict(case)
            rnd=current_round(con,case['id'])
            item['round_number']=rnd['number'] if rnd else 1
            item['round_phase']=rnd['phase'] if rnd else 'collecting'
            item['owner_name']=con.execute('SELECT display_name FROM users WHERE id=?',(case['owner_id'],)).fetchone()[0]
            item['applicants']=[dict(r) for r in con.execute('''SELECT dc.applicant_id,u.display_name
                FROM ownership_dispute_claims dc JOIN users u ON u.id=dc.applicant_id
                WHERE dc.dispute_id=? AND (? OR ?=dc.applicant_id OR ?=?)''',
                (case['id'],admin,user,user,case['owner_id']))]
            result.append(item)
    return result


def decide(repo,con,case_id,version,action,reason,winner_claim=None,*,actor=None,audit_actor=None):
    case=get_case(con,case_id,admin=True)
    if case['version']!=version: raise ValueError('The dispute has changed. Refresh before deciding')
    if not reason.strip() or len(reason)>4000: raise ValueError('A reason (1–4,000 characters) is required')
    if action=='reopen':
        if case['status']!='resolved': raise ValueError('Only resolved cases can be reopened')
        owner=con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(case['individual_id'],)).fetchone()[0]
        # Do not reopen an old dispute against an unrelated successor owner.
        if owner!=case['winner_id']: raise ValueError('Current Owner changed; a new Acquire is required')
        if active(con,case['individual_id']): raise ValueError('Another dispute is already open')
        con.execute("UPDATE ownership_disputes SET status='open',locked_owner_id=? WHERE id=?",(owner,case_id))
        new_round(con,case,reason)
        event(con,case,'reopened',reason,actor)
        return
    if case['status']!='open': raise ValueError('The dispute is already resolved')
    rnd=current_round(con,case_id)
    if action=='request_evidence':
        if not rnd or rnd['phase']!='reviewing':raise ValueError('Both parties must submit evidence before requesting the next round')
        new_round(con,case,reason)
        event(con,case,'request_evidence',reason,actor);return
    if action not in ('owner','applicant'): raise ValueError('Invalid decision')
    links=con.execute('SELECT * FROM ownership_dispute_claims WHERE dispute_id=?',(case_id,)).fetchall()
    if action=='applicant' and winner_claim not in {r['claim_id'] for r in links}: raise ValueError('Select an applicant Claim')
    owner=con.execute('SELECT current_owner_user_id FROM individuals WHERE id=?',(case['individual_id'],)).fetchone()[0]
    if owner!=case['locked_owner_id']: raise ValueError('Current Owner changed; refresh and investigate before deciding')
    con.execute("UPDATE ownership_disputes SET status='resolving' WHERE id=?",(case_id,))
    winner=case['owner_id']
    for link in links:
        positive=action=='applicant' and link['claim_id']==winner_claim
        repo.admin_moderate_claim_in_connection(con,link['claim_id'],'positive' if positive else 'negative',
            **({'actor':audit_actor} if audit_actor is not None else {}))
        if positive:winner=link['applicant_id']
    snapshot=repo._rebuild_individual_snapshot_in_connection(con,case['individual_id'])
    if str(snapshot['current_owner_user_id'])!=str(winner):
        raise ValueError('The decision conflicts with Claim chronology; no changes were saved')
    con.execute("UPDATE ownership_disputes SET status='resolved',decision=?,reason=?,winner_id=? WHERE id=?",(action,reason,winner,case_id))
    event(con,case,'resolved',('Original owner supported' if action=='owner' else f'Applicant supported (Acquire #{winner_claim})')+' — '+reason,actor)
