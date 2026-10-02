"""Local-prototype HTTP boundary for private ownership disputes."""
import sqlite3
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from ygc import disputes as d
from ygc.acquire_review import transaction

router=APIRouter()


def context(request,viewer_id=None,admin=False):
    from ygc.web import repo, acquire_actor, _require_console_admin
    if admin:_require_console_admin(request)
    return repo(), None if admin else acquire_actor(request,viewer_id)


def fail(exc):
    return HTTPException(status_code=403 if isinstance(exc,PermissionError) else 409,detail=str(exc))


@router.get('/api/ownership-disputes')
def user_list(request:Request,viewer_id:int|None=None):
    repo,user=context(request,viewer_id)
    try:
        with repo.connect() as con:return d.listing(con,user)
    except (ValueError,PermissionError) as e:raise fail(e)


@router.get('/api/ownership-disputes/options')
def options(request:Request,viewer_id:int|None=None):
    repo,user=context(request,viewer_id)
    try:
        with transaction(repo) as con:
            d.available(con,user)
            rows=[]
            for r in con.execute("SELECT claim_id FROM acquire_applications WHERE applicant_id=? AND status='accepted' AND request_kind='acquire'",(user,)).fetchall():
                claim=d.candidate(con,r['claim_id'])
                if not d.eligible(con,claim):continue
                decline=con.execute('SELECT * FROM ownership_declines WHERE claim_id=?',(claim['id'],)).fetchone()
                if decline and decline['acknowledged_at']:continue
                rows.append(dict(claim_id=claim['id'],individual_id=claim['individual_id'],status=claim['verification_status'],
                  requested_at=claim['requested_at'],wait_days=d.WAIT_DAYS,decline_reason=decline['reason'] if decline else None))
            return rows
    except (ValueError,PermissionError) as e:raise fail(e)


@router.post('/api/ownership-disputes/acknowledge/{claim_id}')
def acknowledge(claim_id:int,request:Request,viewer_id:int|None=None):
    repo,user=context(request,viewer_id)
    try:
        with transaction(repo) as con:
            d.available(con,user)
            claim=d.candidate(con,claim_id)
            if not claim or claim['author_user_id']!=user:raise PermissionError('Only the applicant may accept the decline')
            d.guard(con,claim['individual_id'],claim_id)
            if claim['verification_status']!='negative':raise ValueError('The Acquire is not declined')
            if not con.execute('SELECT 1 FROM ownership_declines WHERE claim_id=?',(claim_id,)).fetchone():raise ValueError('No owner decline')
            con.execute('UPDATE ownership_declines SET acknowledged_at=? WHERE claim_id=?',(d.utcnow(),claim_id))
        return {'ok':True}
    except (ValueError,PermissionError) as e:raise fail(e)


@router.get('/api/ownership-disputes/{case_id}')
def user_detail(case_id:int,request:Request,viewer_id:int|None=None):
    repo,user=context(request,viewer_id)
    try:
        with repo.connect() as con:return d.detail(con,case_id,user)
    except (ValueError,PermissionError) as e:raise fail(e)


@router.post('/api/ownership-disputes/evidence/submit')
async def submit(request:Request,viewer_id:int|None=None,claim_id:int=Form(...),case_id:int|None=Form(None),round_number:int|None=Form(None),
                 explanation:str=Form(...,max_length=8000),summary:str=Form(...,max_length=4000),attachment:UploadFile|None=File(None)):
    repo,user=context(request,viewer_id)
    try:
        raw=await attachment.read(d.MAX_BYTES+1) if attachment else b''
        content,mime,name=d.validate_submission(explanation,summary,raw,attachment.filename if attachment else '')
        with transaction(repo) as con:
            if case_id:
                case=d.get_case(con,case_id,user)
                if round_number is None:raise ValueError('Refresh the dispute before submitting evidence')
                d.add_evidence(con,case,claim_id,user,explanation,summary,content,mime,name,expected_round=round_number)
            else:case_id=d.open_case(con,claim_id,user,explanation,summary,content,mime,name)
            return d.detail(con,case_id,user)
    except (ValueError,PermissionError) as e:raise fail(e)


def attachment_response(evidence_id,request,viewer_id=None,admin=False):
    repo,user=context(request,viewer_id,admin)
    try:
        with repo.connect() as con:
            row=con.execute('SELECT * FROM ownership_dispute_evidence WHERE id=?',(evidence_id,)).fetchone()
            if not row:raise ValueError('Evidence not found')
            d.get_case(con,row['dispute_id'],user,admin)
            if not admin and row['author_id']!=user:raise PermissionError('Original evidence is private')
            if not row['content']:raise ValueError('No attachment')
            return Response(row['content'],media_type=row['content_type'],headers={
                'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                'Content-Disposition':f'attachment; filename="{row["filename"]}"'})
    except (ValueError,PermissionError) as e:raise fail(e)


@router.get('/api/ownership-dispute-evidence/{evidence_id}')
def user_attachment(evidence_id:int,request:Request,viewer_id:int|None=None):
    return attachment_response(evidence_id,request,viewer_id)


@router.get('/api/admin/ownership-disputes')
def admin_list(request:Request):
    repo,_=context(request,admin=True)
    with repo.connect() as con:return d.listing(con,admin=True)


@router.get('/api/admin/ownership-disputes/{case_id}')
def admin_detail(case_id:int,request:Request):
    repo,_=context(request,admin=True)
    try:
        with repo.connect() as con:return d.detail(con,case_id,admin=True)
    except (ValueError,PermissionError) as e:raise fail(e)


@router.get('/api/admin/ownership-dispute-evidence/{evidence_id}')
def admin_attachment(evidence_id:int,request:Request):
    return attachment_response(evidence_id,request,admin=True)


class Decision(BaseModel):
    version:int=Field(ge=1)
    action:str=Field(max_length=30)
    reason:str=Field(min_length=1,max_length=4000)
    winner_claim:int|None=None


@router.post('/api/admin/ownership-disputes/{case_id}/decision')
def decision(case_id:int,body:Decision,request:Request):
    repo,_=context(request,admin=True)
    try:
        with transaction(repo) as con:
            d.decide(repo,con,case_id,body.version,body.action,body.reason,body.winner_claim)
            return d.detail(con,case_id,admin=True)
    except (ValueError,PermissionError,sqlite3.IntegrityError) as e:raise fail(e)


class Summary(BaseModel):
    version:int=Field(ge=1)
    summary:str=Field(min_length=1,max_length=4000)


@router.post('/api/admin/ownership-dispute-evidence/{evidence_id}/publish')
def publish(evidence_id:int,body:Summary,request:Request):
    repo,_=context(request,admin=True)
    try:
        with transaction(repo) as con:
            row=con.execute('SELECT * FROM ownership_dispute_evidence WHERE id=?',(evidence_id,)).fetchone()
            if not row:raise ValueError('Evidence not found')
            case=d.get_case(con,row['dispute_id'],admin=True)
            if case['status']!='open' or case['version']!=body.version:raise ValueError('Refresh this open dispute before publishing')
            if row['published_at']:raise ValueError('Published summaries cannot be overwritten; add a correction')
            if not body.summary.strip():raise ValueError('A summary is required')
            con.execute('UPDATE ownership_dispute_evidence SET published_summary=?,published_at=? WHERE id=?',(body.summary.strip(),d.utcnow(),evidence_id))
            d.event(con,case,'summary_published','A reviewed summary is available')
            return d.detail(con,case['id'],admin=True)
    except (ValueError,PermissionError) as e:raise fail(e)
