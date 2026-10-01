from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from ygc.claim_dates import validate_claim_date, viewer_timezone

NOW=datetime(2026,10,1,16,tzinfo=timezone.utc)

@pytest.mark.parametrize('zone,today,tomorrow',[
    ('Asia/Tokyo','2026-10-02','2026-10-03'),
    ('America/Los_Angeles','2026-10-01','2026-10-02'),
    ('UTC','2026-10-01','2026-10-02'),
])
def test_local_calendar_boundary(zone,today,tomorrow):
    token=viewer_timezone.set(ZoneInfo(zone))
    try:
        assert validate_claim_date(today,now=NOW)==today
        with pytest.raises(ValueError,match='future'):validate_claim_date(tomorrow,now=NOW)
        assert validate_claim_date('2020-01-01',now=NOW)=='2020-01-01'
    finally:viewer_timezone.reset(token)


def test_datetime_uses_instant_not_date():
    assert validate_claim_date('2026-10-02T01:00:00+09:00',now=NOW)=='2026-10-01T16:00:00+00:00'
    with pytest.raises(ValueError,match='future'):
        validate_claim_date('2026-10-02T01:00:01+09:00',now=NOW)


def test_http_future_claim_rejected_before_writes(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from ygc import config
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'untouched.db')
    from ygc.web import app
    client=TestClient(app)
    for path,payload in [
        ('/api/individuals/1/event-claim',dict(user_id=1,event_kind='performance',detail='test',occurred_at='2999-01-01')),
        ('/api/claims/1',dict(user_id=1,occurred_at='2999-01-01')),
        ('/api/ownership-drafts/keep',dict(revision='a'*32,acquisition_date='2999-01-01')),
    ]:
        response=client.request('PATCH' if path=='/api/claims/1' else 'POST',path,json=payload,headers={'X-YGC-Timezone':'Asia/Tokyo'})
        assert response.status_code==422,response.text
        assert 'future' in response.text
    response=client.post('/api/individuals/1/media-claim',data={'user_id':'1','occurred_at':'2999-01-01'},files={'images':('x.jpg',b'x','image/jpeg')})
    assert response.status_code==400
    assert 'future' in response.text
    assert not (tmp_path/'untouched.db').exists()
