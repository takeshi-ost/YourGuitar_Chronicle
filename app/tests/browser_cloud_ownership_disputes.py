"""Synthetic Chromium journeys for authenticated ownership disputes.

Runs the real participant/Admin component, notification destination handling,
translations, styles and overlay lifecycle against intercepted API responses.
No Identity Platform, PostgreSQL, cloud bucket, reviewer or live account is used.
Compile anywhere; execute only in an authorized browser acceptance environment.
A successful compile is deliberately not described as browser acceptance.
"""
from copy import deepcopy
from email import policy
from email.parser import BytesParser
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from browser_diagnostics import diagnostic_page
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-ownership-disputes-fixture.invalid'
API = '/api/auth/ownership-disputes'
ADMIN_API = '/api/auth/admin/ownership-disputes'
CASE = '9007199254741999'
SECOND_CASE = '9007199254741998'
CLAIM = '9007199254741021'
SECOND_CLAIM = '9007199254741022'
GUITAR = '9007199254741009'
APPLICANT = '9007199254740993'
OWNER = '9007199254740995'
OTHER = '9007199254740997'
ADMIN = '9223372036854775807'
EVIDENCE = '9007199254741101'
OWNER_EVIDENCE = '9007199254741102'
OTHER_EVIDENCE = '9007199254741103'
ROUND = '9007199254741201'
REVISION = 'a' * 64
NOW = '2026-10-07T01:00:00Z'
LATER = '2026-10-07T02:00:00Z'
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'
EXPLANATION = 'Private applicant acquisition explanation ' + ATTACK
SUMMARY = 'Applicant submitted summary ' + ATTACK
OWNER_PRIVATE = 'Private original Owner explanation ' + ATTACK
OWNER_SUMMARY = 'Original Owner unreviewed summary ' + ATTACK
REVIEWED = 'Administrator-reviewed account of the acquisition ' + ATTACK
OTHER_PRIVATE = 'Other applicant must never be disclosed'
DECLINE = 'Original Owner declined because the serial does not match ' + ATTACK
PERSONS = {
    'applicant': dict(id=APPLICANT, display_name='Applicant ' + ATTACK, account_type='user'),
    'owner': dict(id=OWNER, display_name='Original Owner', account_type='user'),
    'other': dict(id=OTHER, display_name='Other applicant', account_type='user'),
    'admin': dict(id=ADMIN, display_name='Administrator', account_type='user'),
}
HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/assets/cloud-account.css">
<link rel="stylesheet" href="/assets/cloud-console.css">
<script src="/assets/i18n.js"></script><script src="/assets/overlays.js"></script>
</head><body><h1>Private ownership-dispute fixture</h1>
<main><section id="selfNotifications"></section><section id="selfDisputes"></section>
<section id="disputeBrowser"></section></main>
<script type="module">
import {createDisputes} from '/assets/cloud-account-disputes.js';
import {createNotifications} from '/assets/cloud-account-notifications.js';
const query=new URLSearchParams(location.search),admin=query.get('admin')==='1';
let actor=query.get('actor')||(admin?'admin':'applicant'),verified=query.get('verified')!=='0',busy=false;
const users=__USERS__;
const fixture=globalThis.disputeFixture={ready:false,pending:0,operations:0,updated:0,
  requests:[],holds:[],waiting:{},created:[],revoked:[],failures:[],destinations:[],unauthorized:[]};
const createURL=URL.createObjectURL.bind(URL),revokeURL=URL.revokeObjectURL.bind(URL);
URL.createObjectURL=blob=>{const url=createURL(blob);fixture.created.push(url);return url};
URL.revokeObjectURL=url=>{fixture.revoked.push(url);revokeURL(url)};
fixture.hold=(method,path,id='held')=>fixture.holds.push({method,path,id});
fixture.release=id=>{const done=fixture.waiting[id];delete fixture.waiting[id];done()};
const state=()=>actor?{user:{...users[actor],app_user_id:'fixture-'+actor,
  role:actor==='admin'?'admin':'member',status:'active'},identity:{email_verified:verified}}:null;
const auth={authorizedFetch:async(path,options={},required)=>{
  const pathname=new URL(path,location.href).pathname,method=options.method||'GET';
  const index=fixture.holds.findIndex(item=>item.method===method&&item.path===pathname);
  const hold=index<0?null:fixture.holds.splice(index,1)[0];
  fixture.requests.push({path:pathname,method,actor,required,credentials:options.credentials,
    cache:options.cache,redirect:options.redirect,timezone:new Headers(options.headers).get('X-YGC-Timezone')});
  fixture.pending++;
  try{
    const response=await fetch(path,{...options,headers:{...options.headers,
      Authorization:'Bearer fixture-'+actor,'X-Fixture-Account':actor||''}});
    // Hold a fully delivered response, not the network request. The server may
    // already have committed while the old browser screen is still waiting.
    const payload=await response.arrayBuffer();
    if(hold)await new Promise(resolve=>{fixture.waiting[hold.id]=resolve});
    return new Response(payload,{status:response.status,statusText:response.statusText,
      headers:response.headers});
  }finally{fixture.pending--}
}};
let component,notifications;
const render=()=>{component?.render();notifications?.render()};
const work=async task=>{if(busy)return;busy=true;fixture.operations++;render();
  try{await task()}catch(error){fixture.failures.push(String(error))}
  finally{busy=false;fixture.operations--;render()}};
component=createDisputes({auth:()=>auth,state,busy:()=>busy,work,admin,
  updated:async()=>{fixture.updated++},
  onUnauthorized:error=>{fixture.unauthorized.push(error.status);actor=null;
    component.clear();notifications?.clear();render()}});
notifications=createNotifications({auth:()=>auth,state,busy:()=>busy,work,
  openTransfer:id=>fixture.destinations.push(['transfer',id]),
  openOwner:(id,claim)=>fixture.destinations.push(['owner',id,claim]),
  openDispute:id=>{fixture.destinations.push(['dispute',id]);return component.openDispute(id)},
  openDisputeOption:id=>{fixture.destinations.push(['dispute_option',id]);return component.openDisputeOption(id)}});
fixture.invoke=(name,...args)=>{fixture.operations++;
  Promise.resolve(component[name](...args)).catch(error=>fixture.failures.push(String(error)))
    .finally(()=>{fixture.operations--})};
fixture.setAccount=(value,emailVerified=true)=>{
  component.clear();notifications.clear();actor=value;verified=emailVerified;render();
  if(actor&&verified)fixture.invoke('refresh');
};
fixture.refreshNotifications=()=>{fixture.operations++;
  Promise.resolve(notifications.refresh()).finally(()=>{fixture.operations--})};
render();await component.refresh();fixture.ready=true;
</script></body></html>'''.replace('__USERS__', json.dumps(PERSONS))


def guitar(identifier=GUITAR, serial='PRIVATE-DISPUTE-001'):
    return dict(id=identifier, manufacturer='Fixture maker', model='Private guitar ' + ATTACK,
                finish='Natural', year='1965', serial_number=serial)


def option(*, declined=True, eligible=True):
    return dict(claim_id=CLAIM, individual=guitar(), applicant=deepcopy(PERSONS['applicant']),
                owner=deepcopy(PERSONS['owner']), requested_at='2026-09-01T00:00:00Z',
                verification_status='negative' if declined else 'unverified',
                decline=dict(reason=DECLINE, created_at=NOW, acknowledged_at=None) if declined else None,
                eligible=eligible, can_acknowledge=declined, can_appeal=eligible,
                wait_until='2026-09-15T00:00:00Z' if eligible else '2026-10-20T00:00:00Z',
                wait_days=14, revision=REVISION, can_write=True, case_id=None)


def evidence(identifier=EVIDENCE, *, actor='applicant', claim=CLAIM, round_number='1',
             attached=True, published=False):
    own = actor == 'applicant'
    return dict(id=identifier, claim_id=claim, author_id=PERSONS[actor]['id'],
                author_name=PERSONS[actor]['display_name'], created_at=NOW,
                published_summary=REVIEWED if published else None,
                published_at=LATER if published else None, round_number=round_number,
                can_publish=not published, explanation=EXPLANATION if own else OWNER_PRIVATE,
                summary=SUMMARY if own else OWNER_SUMMARY,
                filename='private-receipt.jpg' if attached else None,
                content_type='image/jpeg' if attached else None, has_attachment=attached)


def case_record(identifier=CASE, *, phase='collecting', submitted=('applicant',),
                status='open', multiple=False, reopen=True):
    claims = [dict(claim_id=CLAIM, applicant_id=APPLICANT,
                   applicant_name=PERSONS['applicant']['display_name'],
                   decline_reason=DECLINE, requested_at='2026-09-01T00:00:00Z')]
    if multiple:
        claims.append(dict(claim_id=SECOND_CLAIM, applicant_id=OTHER,
                           applicant_name=PERSONS['other']['display_name'], decline_reason=None,
                           requested_at='2026-09-02T00:00:00Z'))
    parties = [dict(claim_id=claim['claim_id'], user_id=PERSONS[actor]['id'],
                    display_name=PERSONS[actor]['display_name'],
                    submitted_at=NOW if actor in submitted else None, can_submit=False)
               for claim in claims for actor in (
                   'owner', 'applicant' if claim['applicant_id'] == APPLICANT else 'other')]
    current_round = dict(id=ROUND, number='1', phase=phase, request_reason='',
                         created_at=NOW, parties=parties)
    rows = []
    if 'applicant' in submitted:
        rows.append(evidence())
    if 'owner' in submitted:
        rows.append(evidence(OWNER_EVIDENCE, actor='owner'))
    if multiple and 'other' in submitted:
        rows.append(evidence(OTHER_EVIDENCE, actor='other', claim=SECOND_CLAIM))
        rows[-1].update(explanation=OTHER_PRIVATE, summary=OTHER_PRIVATE)
    return dict(id=identifier, individual_id=GUITAR, owner_id=OWNER, locked_owner_id=OWNER,
                winner_id=OWNER if status == 'resolved' else None, status=status, version='1',
                created_at=NOW, updated_at=NOW, decision='owner' if status == 'resolved' else None,
                reason='Prior reason' if status == 'resolved' else None, individual=guitar(),
                owner=deepcopy(PERSONS['owner']), current_owner=deepcopy(PERSONS['owner']),
                applicants=[deepcopy(PERSONS['applicant'])] + ([deepcopy(PERSONS['other'])] if multiple else []),
                round_number='1', round_phase=phase, viewer_user_id=APPLICANT, can_write=True,
                is_admin=False, can_reopen=reopen and status == 'resolved', claims=claims,
                round=current_round, rounds=[current_round], evidence=rows,
                events=[dict(id='9007199254741301', kind='opened', note='',
                             created_at=NOW, round_number='1')])


def multipart(request):
    """Check the real multipart payload without JSON-decoding the whole body."""
    content_type = request.headers.get('content-type', '')
    assert content_type.startswith('multipart/form-data; boundary='), content_type
    body = request.post_data_buffer
    assert body is not None
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    assert message.is_multipart()
    parts = list(message.iter_parts())
    names = [part.get_param('name', header='content-disposition') for part in parts]
    assert names.count('data') == 1 and names.count('attachment') <= 1
    assert set(names) <= {'data', 'attachment'}, names
    data_part = parts[names.index('data')]
    assert data_part.get_filename() is None
    payload = json.loads(data_part.get_payload(decode=True).decode('utf-8'))
    assert set(payload) == {'revision', 'case_id', 'version', 'round_number', 'explanation', 'summary'}
    for key in ('explanation', 'summary'):
        assert isinstance(payload[key], str) and payload[key] == payload[key].strip() and payload[key]
    attachments = [part for part in parts if part.get_param('name', header='content-disposition') == 'attachment']
    files = [dict(name=part.get_filename(), content_type=part.get_content_type(),
                  data=part.get_payload(decode=True)) for part in attachments]
    for item in files:
        assert item['content_type'] in ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf')
        assert 0 < len(item['data']) <= 12 * 1024 * 1024
    return payload, files


def main():
    names = [path.name for path in STATIC.glob('cloud-account-*.js')]
    names += ['cloud-account.css', 'cloud-console.css', 'overlays.js', 'ui-components.css']
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    stream = BytesIO()
    Image.new('RGB', (16, 12), 'white').save(stream, format='JPEG')
    attachment = dict(name='private-receipt.jpg', mimeType='image/jpeg', buffer=stream.getvalue())
    store = {}
    errors = []
    checked = 0

    def reset(row=None, candidate=None):
        store.clear()
        store.update(cases={row['id']: row} if row else {}, option=candidate or option(),
                     writes=[], calls=[], attachment_reads=[], external=[], mode='normal',
                     can_write=True, failure=None, malformed=None, malformed_write=None, drop=None, notifications=[],
                     attachment_type=None, attachment_body=None)

    def permitted(actor):
        return actor == 'admin' and store['mode'] != 'offline' or store['mode'] not in ('offline', 'admin_only')

    def writable(actor):
        return permitted(actor) and store['can_write'] and (actor == 'admin' or store['mode'] != 'read_only')

    def case_summary(row):
        return {key: deepcopy(value) for key, value in row.items() if key not in (
            'viewer_user_id', 'can_write', 'is_admin', 'can_reopen', 'claims', 'round', 'rounds', 'evidence', 'events')}

    def detail(row, actor):
        data = deepcopy(row)
        admin, viewer = actor == 'admin', PERSONS[actor]['id']
        data.update(viewer_user_id=viewer, is_admin=admin, can_write=writable(actor),
                    can_reopen=admin and row['can_reopen'] and writable(actor))
        for rnd in data['rounds']:
            for party in rnd['parties']:
                party['can_submit'] = (not admin and writable(actor) and row['status'] == 'open'
                    and rnd['number'] == row['round_number'] and rnd['phase'] == 'collecting'
                    and party['user_id'] == viewer and party['submitted_at'] is None)
        data['round'] = deepcopy(data['rounds'][-1])
        visible = []
        for item in data['evidence']:
            claim = next(claim for claim in data['claims'] if claim['claim_id'] == item['claim_id'])
            if not admin and viewer not in (OWNER, claim['applicant_id']):
                continue
            if not admin and item['author_id'] != viewer and not item['published_at']:
                continue
            item['can_publish'] = admin and writable(actor) and row['status'] == 'open' and item['published_at'] is None
            if not admin and item['author_id'] != viewer:
                for key in ('explanation', 'summary', 'filename', 'content_type', 'has_attachment'):
                    item.pop(key)
            visible.append(item)
        data['evidence'] = visible
        return data

    def option_detail(actor):
        data = deepcopy(store['option'])
        data['can_write'] = writable(actor)
        data['can_acknowledge'] = data['can_acknowledge'] and writable(actor)
        data['can_appeal'] = data['can_appeal'] and writable(actor)
        return data

    def bump(row):
        row['version'] = str(int(row['version']) + 1)
        row['updated_at'] = LATER

    def event(row, kind, note=None):
        row['events'].append(dict(id=str(9007199254741301 + len(row['events'])), kind=kind,
                                 note=note or '', created_at=LATER, round_number=row['round_number']))

    reset()
    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_ownership_disputes') as page:
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            path, method = parsed.path, request.method
            if parsed.scheme + '://' + parsed.netloc != BASE:
                store['external'].append(request.url)
                route.abort()
                return
            if path == '/ownership-disputes-fixture':
                route.fulfill(content_type='text/html', body=HTML)
                return
            if path == '/favicon.ico':
                route.fulfill(status=204)
                return
            if path.startswith('/assets/') and path.removeprefix('/assets/') in assets:
                name = path.removeprefix('/assets/')
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
                return
            actor = request.headers.get('x-fixture-account')
            assert actor in PERSONS, (method, path, actor)
            assert request.headers.get('authorization') == 'Bearer fixture-' + actor
            query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
            call = dict(method=method, path=path, actor=actor, query=query)
            store['calls'].append(call)
            if path == '/api/auth/notifications':
                assert method == 'GET'
                route.fulfill(json=dict(items=deepcopy(store['notifications']), next_after=None,
                    unread_count=str(sum(not item['is_read'] for item in store['notifications'])),
                    can_write=writable(actor)))
                return
            base = ADMIN_API if path.startswith(ADMIN_API) else API
            assert path == base or path.startswith(base + '/'), 'Unexpected fixture request: ' + request.url
            assert (base == ADMIN_API) == (actor == 'admin')
            if not permitted(actor) or method == 'POST' and not writable(actor):
                route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                return
            failure = store['failure']
            if failure and failure['method'] == method and failure['path'] in (None, path):
                route.fulfill(status=failure['status'], json={'detail': {'code': failure.get('code', 'access_denied'),
                              'message': 'SECRET SQL / private@example.invalid'}})
                return
            suffix = path.removeprefix(base).strip('/').split('/') if path != base else []
            if method == 'GET':
                if not suffix:
                    assert set(query) <= {'after', 'limit', 'status'}
                    selected = [row for row in store['cases'].values()
                                if actor == 'admin' or PERSONS[actor]['id'] in (row['owner_id'], *[p['id'] for p in row['applicants']])]
                    status = query.get('status', 'open')
                    selected = [row for row in selected if status in ('', 'all') or row['status'] == status]
                    selected.sort(key=lambda row: int(row['id']), reverse=True)
                    after, limit = query.get('after'), int(query.get('limit', '25'))
                    assert limit == 25
                    selected = [row for row in selected if after is None or int(row['id']) < int(after)]
                    rows = [case_summary(row) for row in selected[:limit]]
                    data = dict(items=rows, next_after=rows[-1]['id'] if len(selected) > limit else None,
                                viewer_user_id=PERSONS[actor]['id'], can_write=writable(actor))
                elif suffix == ['options']:
                    assert actor != 'admin' and set(query) <= {'after', 'limit'}
                    rows = [option_detail(actor)] if actor == 'applicant' and not store['option']['case_id'] and (
                        store['option']['decline'] is None or not store['option']['decline']['acknowledged_at']) else []
                    data = dict(items=rows, next_after=None, viewer_user_id=PERSONS[actor]['id'], can_write=writable(actor))
                elif len(suffix) == 2 and suffix[0] == 'options':
                    assert actor == 'applicant' and suffix[1] == CLAIM
                    data = option_detail(actor)
                elif len(suffix) == 3 and suffix[0] == 'evidence' and suffix[2] == 'attachment':
                    rows = [item for row in store['cases'].values() for item in row['evidence'] if item['id'] == suffix[1]]
                    assert len(rows) == 1 and rows[0]['has_attachment']
                    assert actor == 'admin' or rows[0]['author_id'] == PERSONS[actor]['id'], 'Private original disclosed to opponent'
                    store['attachment_reads'].append((actor, suffix[1]))
                    route.fulfill(content_type=store['attachment_type'] or rows[0]['content_type'],
                                  body=stream.getvalue() if store['attachment_body'] is None else store['attachment_body'],
                                  headers={'Cache-Control': 'private, no-store', 'Content-Disposition': 'attachment; filename="private-receipt.jpg"'})
                    return
                elif len(suffix) == 1 and suffix[0] in store['cases']:
                    data = detail(store['cases'][suffix[0]], actor)
                else:
                    route.fulfill(status=404, json={'detail': 'Unavailable'})
                    return
                malformed = store['malformed']
                if malformed and malformed['path'] == path:
                    data = deepcopy(data)
                    target = data
                    for key in malformed['keys'][:-1]:
                        target = target[key]
                    target[malformed['keys'][-1]] = malformed['value']
                route.fulfill(json=data)
                return

            assert method == 'POST' and not query
            if len(suffix) == 3 and suffix[0] == 'options' and suffix[2] == 'evidence':
                payload, files = multipart(request)
            else:
                assert request.headers.get('content-type', '').startswith('application/json')
                payload, files = request.post_data_json, []
            call.update(body=deepcopy(payload), attachments=[dict(name=item['name'], content_type=item['content_type']) for item in files])
            store['writes'].append(deepcopy(call))
            drop, store['drop'] = store['drop'], None
            if drop == 'before':
                route.abort('failed')
                return
            if len(suffix) == 3 and suffix[0] == 'options' and suffix[2] == 'acknowledge':
                assert actor == 'applicant' and suffix[1] == CLAIM and payload == {'revision': store['option']['revision']}
                store['option']['decline']['acknowledged_at'] = LATER
                store['option'].update(can_acknowledge=False, can_appeal=False, eligible=False, revision='b' * 64)
                result = {'option': option_detail(actor)}
            elif len(suffix) == 3 and suffix[0] == 'options' and suffix[2] == 'evidence':
                assert actor != 'admin' and suffix[1] in (CLAIM, SECOND_CLAIM)
                if payload['case_id'] is None:
                    assert payload['version'] is None and payload['round_number'] is None
                    assert payload['revision'] == store['option']['revision'] and files
                    row = case_record(submitted=())
                    store['cases'][CASE] = row
                    store['option'].update(case_id=CASE, can_acknowledge=False, can_appeal=False)
                else:
                    row = store['cases'][payload['case_id']]
                    assert payload['revision'] is None
                    assert payload['version'] == row['version'] and payload['round_number'] == row['round_number']
                    assert isinstance(payload['version'], str) and isinstance(payload['round_number'], str)
                rnd = row['rounds'][-1]
                parties = [party for party in rnd['parties'] if party['claim_id'] == suffix[1]
                           and party['user_id'] == PERSONS[actor]['id']]
                assert row['status'] == 'open' and rnd['phase'] == 'collecting' and len(parties) == 1
                assert parties[0]['submitted_at'] is None, 'Double submission in the same evidence round'
                parties[0]['submitted_at'] = LATER
                next_evidence = str(max((int(item['id']) for item in row['evidence']), default=int(EVIDENCE) - 1) + 1)
                item = evidence(next_evidence, actor=actor,
                                claim=suffix[1], round_number=rnd['number'], attached=bool(files))
                item.update(explanation=payload['explanation'], summary=payload['summary'])
                row['evidence'].append(item)
                if all(party['submitted_at'] for party in rnd['parties']):
                    rnd['phase'] = row['round_phase'] = 'reviewing'
                row['round'] = rnd
                bump(row)
                event(row, 'evidence_submitted')
                result = {'detail': detail(row, actor)}
            elif len(suffix) == 3 and suffix[0] == 'evidence' and suffix[2] == 'publish':
                assert actor == 'admin' and set(payload) == {'version', 'round_number', 'summary'}
                row = next(row for row in store['cases'].values() if any(item['id'] == suffix[1] for item in row['evidence']))
                assert payload['version'] == row['version'] and payload['round_number'] == row['round_number']
                assert payload['summary'].strip() == payload['summary'] and payload['summary']
                item = next(item for item in row['evidence'] if item['id'] == suffix[1])
                assert row['status'] == 'open' and item['published_at'] is None
                item.update(published_summary=payload['summary'], published_at=LATER, can_publish=False)
                bump(row)
                event(row, 'summary_published')
                result = {'detail': detail(row, actor)}
            elif len(suffix) == 2 and suffix[1] == 'decision':
                assert actor == 'admin' and set(payload) == {'version', 'round_number', 'action', 'reason', 'winner_claim_id'}
                row = store['cases'][suffix[0]]
                assert payload['version'] == row['version'] and payload['round_number'] == row['round_number']
                assert isinstance(payload['version'], str) and isinstance(payload['round_number'], str)
                assert payload['reason'].strip() == payload['reason'] and payload['reason']
                operation = payload['action']
                if operation in ('owner', 'applicant'):
                    assert row['status'] == 'open'
                    winner = next((claim['applicant_id'] for claim in row['claims']
                                   if claim['claim_id'] == payload['winner_claim_id']), None) if operation == 'applicant' else OWNER
                    assert winner is not None
                    assert operation == 'applicant' or payload['winner_claim_id'] is None
                    row.update(status='resolved', decision=operation, reason=payload['reason'], winner_id=winner, can_reopen=True,
                               current_owner=deepcopy(next(person for person in PERSONS.values() if person['id'] == winner)))
                    event(row, 'resolved', payload['reason'])
                else:
                    assert operation in ('request_evidence', 'reopen') and payload['winner_claim_id'] is None
                    assert (operation == 'reopen' and row['status'] == 'resolved' and row['can_reopen']) or (
                        operation == 'request_evidence' and row['status'] == 'open' and row['round_phase'] == 'reviewing')
                    previous = row['rounds'][-1]
                    number = str(int(previous['number']) + 1)
                    new_round = deepcopy(previous)
                    new_round.update(id=str(int(previous['id']) + 1), number=number, phase='collecting',
                                     request_reason=payload['reason'], created_at=LATER)
                    for party in new_round['parties']:
                        party.update(submitted_at=None, can_submit=False)
                    row['rounds'].append(new_round)
                    row.update(status='open', round=new_round, round_number=number, round_phase='collecting', can_reopen=False)
                    if operation == 'reopen':
                        row['locked_owner_id'] = row['current_owner']['id']
                    event(row, 'reopened' if operation == 'reopen' else operation, payload['reason'])
                bump(row)
                result = {'detail': detail(row, actor)}
            else:
                raise AssertionError('Unexpected write: ' + method + ' ' + path)
            if drop == 'after':
                route.abort('failed')
            else:
                if store['malformed_write']:
                    result = deepcopy(result)
                    target = result
                    for key in store['malformed_write']['keys'][:-1]:
                        target = target[key]
                    target[store['malformed_write']['keys'][-1]] = store['malformed_write']['value']
                route.fulfill(json=result)

        page.route('**/*', respond)
        dialog = page.locator('#disputeDialog')
        form = page.locator('#disputeForm')
        confirm = page.locator('#disputeConfirm')
        review = page.locator('#disputeReview')
        operation = page.locator('#disputeOperation')
        reason = page.locator('#disputeReason')
        review_decision = page.locator('#disputeReviewDecision')
        rounds = page.locator('#disputeRounds')
        case_list = page.locator('#disputeList')
        options = page.locator('#disputeOptions')

        def idle():
            page.wait_for_function('disputeFixture.pending===0&&disputeFixture.operations===0')
            assert not page.evaluate('disputeFixture.failures')
            assert not store['external'], store['external']
            assert page.evaluate('Boolean(globalThis.fixtureXss)') is False
            for request in page.evaluate('disputeFixture.requests'):
                assert request['required'] is True
                assert (request['cache'], request['credentials'], request['redirect']) == ('no-store', 'omit', 'error')

        def navigate(row=None, candidate=None, *, actor='applicant', verified=True, locale='en', preserve=False):
            if not preserve:
                reset(row, candidate)
                if page.url.startswith(BASE):
                    page.evaluate('sessionStorage.clear()')
            page.goto(BASE + '/ownership-disputes-fixture?actor=' + actor
                      + '&admin=' + ('1' if actor == 'admin' else '0') + '&verified=' + ('1' if verified else '0'))
            page.wait_for_function('disputeFixture.ready')
            if page.evaluate('YGCI18n.locale') != locale:
                page.evaluate('locale=>localStorage.setItem("ygc_ui_language",locale)', locale)
                page.reload()
                page.wait_for_function('disputeFixture.ready')
            idle()

        def open_case(row=None, *, actor='applicant', locale='en'):
            navigate(row or case_record(), actor=actor, locale=locale)
            page.evaluate('id=>disputeFixture.invoke("openDispute",id)', CASE)
            idle()
            expect(dialog).to_be_visible()
            expect(page.locator('#disputeMeta')).to_contain_text(CLAIM)

        def open_option(candidate=None):
            navigate(candidate=candidate)
            options.locator('button').first.click()
            idle()
            expect(dialog).to_be_visible()
            expect(dialog).to_contain_text(CLAIM)

        def compose(*, attached=True, explanation=EXPLANATION, summary=SUMMARY):
            expect(form).to_be_visible()
            page.locator('#disputeExplanation').fill(explanation)
            page.locator('#disputeSummary').fill(summary)
            if attached:
                page.locator('#disputeAttachment').set_input_files(attachment)
            review.click()
            idle()
            expect(confirm).to_be_visible()
            expect(confirm).to_be_enabled()

        def decide(action='owner', message='Administrator reviewed the available record'):
            operation.select_option(action)
            reason.fill(message)
            if action == 'applicant':
                page.locator('#disputeWinner').select_option(SECOND_CLAIM)
            review_decision.click()
            idle()
            expect(confirm).to_be_visible()
            expect(confirm).to_be_enabled()

        def hold(method, path, identity='held'):
            page.evaluate('args=>disputeFixture.hold(...args)', [method, path, identity])

        def held(identity='held'):
            page.wait_for_function('id=>typeof disputeFixture.waiting[id]==="function"', arg=identity)

        def release(identity='held'):
            page.evaluate('id=>disputeFixture.release(id)', identity)
            idle()

        def close():
            page.locator('#disputeClose').click()
            expect(dialog).to_be_hidden()

        def hidden_or_disabled(locator):
            assert not locator.is_visible() or not locator.is_enabled()

        def assert_private_purged():
            expect(dialog).to_be_hidden()
            for text in (EXPLANATION, OWNER_PRIVATE, SUMMARY, OWNER_SUMMARY, CLAIM, 'PRIVATE-DISPUTE-001'):
                assert text not in dialog.text_content()
            expect(dialog.locator('img[src],a[href^="blob:"]')).to_have_count(0)
            assert page.evaluate('disputeFixture.created.every(url=>disputeFixture.revoked.includes(url))')
            hidden_or_disabled(confirm)

        # Unverified identities never load the private surface. Opening a
        # declined option shows the exact reason without acknowledging it.
        navigate(verified=False)
        expect(page.locator('#selfDisputes')).to_be_hidden()
        assert not store['calls']
        navigate(actor='owner')
        expect(page.locator('#selfDisputes')).to_be_hidden()
        open_option()
        expect(dialog).to_contain_text(DECLINE)
        expect(form).to_be_visible()
        assert not store['writes']
        assert dialog.locator('img,script,b').count() == 0
        assert page.evaluate('Boolean(globalThis.fixtureXss)') is False
        checked += 1

        # Accept decision is a separate reviewed action. Merely opening the
        # dialog, previewing acknowledgement, or reading a notice does nothing.
        page.locator('#disputeAccept').click(); idle()
        expect(confirm).to_be_visible()
        assert not store['writes']
        confirm.click(); idle()
        assert len(store['writes']) == 1
        assert store['writes'][0]['path'] == API + '/options/' + CLAIM + '/acknowledge'
        assert store['writes'][0]['body'] == {'revision': REVISION}
        assert store['option']['decline']['acknowledged_at'] == LATER
        assert not store['cases']
        expect(form).to_be_hidden()
        hidden_or_disabled(page.locator('#disputeAccept'))
        checked += 1

        # Waiting never automatically transfers ownership. Escalation becomes
        # available only when the authoritative option marks it eligible.
        open_option(option(declined=False, eligible=False))
        expect(form).to_be_hidden()
        expect(page.locator('#disputeAccept')).to_be_hidden()
        assert not store['writes'] and not store['cases']
        open_option(option(declined=False, eligible=True))
        expect(form).to_be_visible()
        expect(page.locator('#disputeAccept')).to_be_hidden()
        checked += 1

        # The initial appeal requires a real additional attachment. Invalid
        # local choices are rejected before any multipart request is sent.
        open_option()
        page.locator('#disputeExplanation').fill(EXPLANATION)
        page.locator('#disputeSummary').fill(SUMMARY)
        review.click(); idle()
        hidden_or_disabled(confirm)
        assert not store['writes']
        for invalid in (
                dict(name='empty.jpg', mimeType='image/jpeg', buffer=b''),
                dict(name='executable.html', mimeType='text/html', buffer=b'<script>bad()</script>'),
                dict(name='large.pdf', mimeType='application/pdf', buffer=b'%' * (12 * 1024 * 1024 + 1))):
            open_option()
            page.locator('#disputeExplanation').fill(EXPLANATION)
            page.locator('#disputeSummary').fill(SUMMARY)
            page.locator('#disputeAttachment').set_input_files(invalid)
            review.click(); idle()
            hidden_or_disabled(confirm)
            assert not store['writes']
            checked += 1

        # Preview binds the exact values and is invalidated by editing. A held
        # accepted write cannot be double-submitted, even through the handler.
        open_option()
        compose()
        assert not store['writes']
        page.locator('#disputeSummary').fill('Revised public-facing summary')
        hidden_or_disabled(confirm)
        review.click(); idle()
        hold('POST', API + '/options/' + CLAIM + '/evidence')
        confirm.click(); held()
        page.evaluate("document.getElementById('disputeConfirm').onclick()")
        assert len(store['writes']) == 1
        sent = store['writes'][0]
        assert sent['body'] == dict(revision=REVISION, case_id=None, version=None,
            round_number=None, explanation=EXPLANATION, summary='Revised public-facing summary')
        assert sent['attachments'] == [dict(name='private-receipt.jpg', content_type='image/jpeg')]
        release()
        expect(dialog).to_be_visible()
        expect(form).to_be_hidden()
        expect(rounds).to_contain_text('Revised public-facing summary')
        expect(rounds).to_contain_text('Submitted')
        expect(rounds).not_to_contain_text('Review result')
        assert store['cases'][CASE]['current_owner']['id'] == OWNER
        assert len(store['writes']) == 1
        checked += 1

        # A participant sees their original and submitted summary immediately.
        # Opposing private records and another applicant's records stay absent;
        # only a reviewed published summary is visible to the other party.
        private_case = case_record(phase='reviewing', submitted=('applicant', 'owner', 'other'), multiple=True)
        open_case(deepcopy(private_case))
        expect(rounds).to_contain_text(SUMMARY)
        expect(rounds).to_contain_text(EXPLANATION)
        for secret in (OWNER_PRIVATE, OWNER_SUMMARY, OTHER_PRIVATE):
            assert secret not in dialog.text_content()
        assert page.locator('[data-dispute-attachment="' + EVIDENCE + '"]').count() == 1
        assert page.locator('[data-dispute-attachment="' + OWNER_EVIDENCE + '"]').count() == 0
        assert not store['attachment_reads']
        download = page.locator('[data-dispute-attachment="' + EVIDENCE + '"]')
        download.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
        with page.expect_download() as downloaded:
            download.click()
        idle()
        assert downloaded.value.suggested_filename == 'evidence-' + EVIDENCE + '.jpg'
        assert store['attachment_reads'] == [('applicant', EVIDENCE)]
        assert page.evaluate('disputeFixture.created.length') == 1
        close()
        assert_private_purged()
        private_case['evidence'][1].update(published_summary=REVIEWED, published_at=LATER)
        open_case(deepcopy(private_case))
        expect(rounds).to_contain_text(REVIEWED)
        assert OWNER_PRIVATE not in dialog.text_content() and OWNER_SUMMARY not in dialog.text_content()
        assert OTHER_PRIVATE not in dialog.text_content()
        expect(page.locator('[data-dispute-attachment="' + OWNER_EVIDENCE + '"]')).to_have_count(0)
        checked += 1

        # Only opening the appeal requires an attachment. The original Owner
        # can supply explanation and summary in that same first round without it.
        open_case(actor='owner')
        compose(attached=False, explanation='Original Owner acquisition chronology',
                summary='Original Owner first-round summary')
        confirm.click(); idle()
        assert store['writes'][0]['attachments'] == []
        assert store['writes'][0]['body'] == dict(revision=None, case_id=CASE, version='1',
            round_number='1', explanation='Original Owner acquisition chronology',
            summary='Original Owner first-round summary')
        assert store['cases'][CASE]['round_phase'] == 'reviewing'
        expect(form).to_be_hidden()
        expect(rounds).to_contain_text('Review result')
        checked += 1

        # Admin can inspect all originals but publication remains a reviewed,
        # version/round-bound mutation; the submitted summary is not rewritten.
        open_case(deepcopy(private_case), actor='admin')
        for value in (EXPLANATION, OWNER_PRIVATE, OTHER_PRIVATE):
            expect(rounds).to_contain_text(value)
        publish_summary = page.locator('#disputePublishSummary_' + EVIDENCE)
        publish_summary.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
        publish_summary.fill(REVIEWED)
        page.locator('[data-dispute-publish="' + EVIDENCE + '"]').click(); idle()
        expect(confirm).to_be_visible()
        assert not store['writes']
        confirm.click(); idle()
        assert store['writes'][0]['path'] == ADMIN_API + '/evidence/' + EVIDENCE + '/publish'
        assert store['writes'][0]['body'] == dict(version='1', round_number='1', summary=REVIEWED)
        assert store['cases'][CASE]['evidence'][0]['summary'] == SUMMARY
        expect(page.locator('[data-dispute-publish="' + EVIDENCE + '"]')).to_have_count(0)
        checked += 1

        # Incomplete evidence never blocks adjudication. The applicant choice
        # carries its original string Claim ID, not a user ID or JS number.
        for submitted in ((), ('applicant',), ('applicant', 'owner', 'other')):
            for action in ('owner', 'applicant'):
                complete = submitted == ('applicant', 'owner', 'other')
                open_case(case_record(submitted=submitted, multiple=True,
                          phase='reviewing' if complete else 'collecting'), actor='admin')
                operation.select_option(action)
                reason.fill('   ')
                review_decision.click(); idle()
                hidden_or_disabled(confirm)
                assert not store['writes']
                # Invalid local content locks stale controls until explicit read.
                page.locator('#disputeReload').click(); idle()
                decide(action, '  Explicit ' + action + ' reason  ')
                assert not store['writes']
                hold('POST', ADMIN_API + '/' + CASE + '/decision')
                confirm.click(); held()
                page.evaluate("document.getElementById('disputeConfirm').onclick()")
                assert len(store['writes']) == 1
                assert store['writes'][0]['body'] == dict(version='1', round_number='1',
                    action=action, reason='Explicit ' + action + ' reason',
                    winner_claim_id=SECOND_CLAIM if action == 'applicant' else None)
                release()
                assert store['cases'][CASE]['status'] == 'resolved'
                assert store['cases'][CASE]['current_owner']['id'] == (OTHER if action == 'applicant' else OWNER)
                expect(rounds).to_contain_text('Explicit ' + action + ' reason')
                checked += 1

        # Request additional evidence is present only after every party has
        # submitted. The next round preserves earlier evidence and its reason.
        open_case(case_record(submitted=()), actor='admin')
        expect(operation.locator('option[value="request_evidence"]')).to_have_count(0)
        open_case(case_record(phase='reviewing', submitted=('applicant', 'owner')), actor='admin')
        decide('request_evidence', 'Please add a dated receipt')
        confirm.click(); idle()
        assert store['cases'][CASE]['round_number'] == '2'
        assert len(store['cases'][CASE]['evidence']) == 2
        expect(rounds).to_contain_text('Please add a dated receipt')
        expect(rounds).to_contain_text('Round 2')
        expect(operation.locator('option[value="request_evidence"]')).to_have_count(0)
        second_round = deepcopy(store['cases'][CASE])
        open_case(second_round)
        expect(form).to_be_visible()
        expect(page.locator('#disputeClaim')).to_be_hidden()
        compose(attached=False, explanation='Additional context', summary='Additional reviewed summary')
        confirm.click(); idle()
        sent = store['writes'][0]
        assert sent['body'] == dict(revision=None, case_id=CASE, version='2', round_number='2',
            explanation='Additional context', summary='Additional reviewed summary')
        assert sent['attachments'] == []
        expect(form).to_be_hidden()
        assert len(store['cases'][CASE]['evidence']) == 3
        checked += 1

        # Multiple Acquire parties are tracked separately. The original Owner
        # submits once per target Claim; only the remaining target stays editable.
        open_case(case_record(multiple=True, submitted=('applicant', 'other')), actor='owner')
        expect(page.locator('#disputeClaim')).to_be_visible()
        page.locator('#disputeClaim').select_option(SECOND_CLAIM)
        compose(attached=False, explanation='Response to second applicant', summary='Second Claim response')
        confirm.click(); idle()
        assert store['writes'][0]['path'] == API + '/options/' + SECOND_CLAIM + '/evidence'
        assert store['cases'][CASE]['round_phase'] == 'collecting'
        expect(form).to_be_visible()
        expect(page.locator('#disputeClaim')).to_be_hidden()
        expect(page.locator('#disputeClaim')).to_have_value(CLAIM)
        compose(attached=False, explanation='Response to first applicant', summary='First Claim response')
        confirm.click(); idle()
        assert store['writes'][1]['path'] == API + '/options/' + CLAIM + '/evidence'
        assert store['cases'][CASE]['round_phase'] == 'reviewing'
        expect(form).to_be_hidden()
        assert len(store['cases'][CASE]['evidence']) == 4
        checked += 1

        # Resolved cases reopen only when the server permits reconsideration;
        # ownership after a later Transfer is never inferred or overridden.
        for available in (False, True):
            row = case_record(status='resolved', reopen=available)
            if not available:
                row['current_owner'] = deepcopy(PERSONS['other'])
            open_case(row, actor='admin')
            if available:
                decide('reopen', 'New material merits reconsideration')
                confirm.click(); idle()
                assert store['cases'][CASE]['status'] == 'open'
                assert store['cases'][CASE]['round_number'] == '2'
                assert store['cases'][CASE]['locked_owner_id'] == OWNER
                assert store['cases'][CASE]['owner_id'] == OWNER
                assert store['cases'][CASE]['claims'][0]['applicant_id'] == APPLICANT
                assert len(store['cases'][CASE]['evidence']) == 1
            else:
                expect(operation.locator('option[value="reopen"]')).to_have_count(0)
                hidden_or_disabled(review_decision)
                assert not store['writes']
                assert store['cases'][CASE]['current_owner']['id'] == OTHER
            checked += 1

        # Decimal IDs outside JS's exact range survive server-cursor pagination.
        # Changing Admin status clears the prior cursor instead of reusing it.
        navigate(case_record(), actor='admin')
        for index in range(1, 28):
            identifier = str(int(CASE) - index)
            store['cases'][identifier] = case_record(identifier)
        resolved = case_record(str(int(CASE) - 40), status='resolved')
        store['cases'][resolved['id']] = resolved
        page.locator('#disputeRefresh').click(); idle()
        expect(case_list.locator(':scope > li')).to_have_count(25)
        page.locator('#disputeNext').click(); idle()
        expect(case_list.locator(':scope > li')).to_have_count(3)
        assert store['calls'][-1]['query']['after'] == str(int(CASE) - 24)
        page.locator('#disputePrevious').click(); idle()
        expect(case_list.locator(':scope > li')).to_have_count(25)
        page.locator('#disputeFilter').select_option('resolved'); idle()
        expect(case_list.locator(':scope > li')).to_have_count(1)
        assert store['calls'][-1]['query']['status'] == 'resolved'
        assert 'after' not in store['calls'][-1]['query']
        page.locator('#disputeFilter').select_option('all'); idle()
        expect(case_list.locator(':scope > li')).to_have_count(25)
        assert store['calls'][-1]['query']['status'] == 'all'
        checked += 1

        # Returned wire values must be canonical decimal strings. Numeric,
        # zero-prefixed and out-of-range IDs, versions and rounds fail closed.
        malformed_fields = [
            (['id'], 9007199254741999), (['id'], '0' + CASE),
            (['version'], 1), (['version'], '0'), (['version'], '9223372036854775808'),
            (['round_number'], 1), (['round', 'number'], '01'),
            (['claims', 0, 'claim_id'], 9007199254741021),
            (['rounds', 0, 'parties', 0, 'user_id'], 9007199254740995),
            (['evidence', 0, 'id'], 9007199254741101),
        ]
        for keys, value in malformed_fields:
            open_case(actor='admin')
            store['malformed'] = dict(path=ADMIN_API + '/' + CASE, keys=keys, value=value)
            page.locator('#disputeReload').click(); idle()
            hidden_or_disabled(review_decision)
            hidden_or_disabled(confirm)
            assert not store['writes']
            assert 'SECRET SQL' not in dialog.text_content()
            checked += 1
        for keys, value in ((['claim_id'], 9007199254741021), (['revision'], 'invalid'),
                            (['revision'], 1), (['wait_days'], '14')):
            open_option()
            store['malformed'] = dict(path=API + '/options/' + CLAIM, keys=keys, value=value)
            page.locator('#disputeReload').click(); idle()
            hidden_or_disabled(review)
            hidden_or_disabled(page.locator('#disputeAccept'))
            assert not store['writes']
            checked += 1

        # Public entry points reject lossy numbers before concatenating them
        # into paths, including values above JavaScript's safe integer range.
        navigate(case_record())
        for method in ('openDispute', 'openDisputeOption'):
            for value in (9007199254741999, 1, None, '01', '0', '9223372036854775808', '../other'):
                before = len(store['calls'])
                page.evaluate('args=>disputeFixture.invoke(...args)', [method, value]); idle()
                assert len(store['calls']) == before
                expect(dialog).to_be_hidden()
                assert not store['writes']
                checked += 1

        # Private downloads reject an unexpected MIME or empty body before
        # constructing a blob URL or handing the bytes to the browser.
        for mime, body in (('text/html', b'<script>globalThis.fixtureXss=true</script>'),
                           ('application/pdf', b'')):
            open_case()
            store['attachment_type'], store['attachment_body'] = mime, body
            control = page.locator('[data-dispute-attachment="' + EVIDENCE + '"]')
            control.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
            control.click(); idle()
            assert page.evaluate('disputeFixture.created.length') == 0
            assert page.locator('[href^="blob:"]').count() == 0
            assert not store['writes']
            checked += 1

        # A changed version/round discovered during confirmation invalidates
        # the proposal without posting. A definite conflict requires a fresh read.
        for changed in ('version', 'round'):
            open_case(case_record(multiple=True), actor='admin')
            decide('applicant')
            row = store['cases'][CASE]
            bump(row)
            if changed == 'round':
                row['round_number'] = row['round']['number'] = row['rounds'][0]['number'] = '2'
                for item in row['evidence']:
                    item['round_number'] = '2'
                for item in row['events']:
                    item['round_number'] = '2'
            confirm.click(); idle()
            hidden_or_disabled(confirm)
            assert not store['writes']
            checked += 1
        open_case(case_record(multiple=True), actor='admin')
        decide('owner')
        store['failure'] = dict(method='POST', path=ADMIN_API + '/' + CASE + '/decision', status=409)
        confirm.click(); idle()
        hidden_or_disabled(review_decision)
        hidden_or_disabled(confirm)
        store['failure'] = None
        page.locator('#disputeReload').click(); idle()
        decide('owner', 'Explicitly reviewed again after conflict')
        confirm.click(); idle()
        assert len(store['writes']) == 1
        assert len([call for call in store['calls'] if call['method'] == 'POST']) == 2
        checked += 1

        # Unknown outcomes are never blindly retried, even if the response was
        # lost after commitment. Fresh read and explicit acknowledgement precede
        # a newly reviewed action; committed evidence cannot be resubmitted.
        for drop in ('before', 'after'):
            open_option()
            compose()
            store['drop'] = drop
            confirm.click(); idle()
            assert len(store['writes']) == 1
            hidden_or_disabled(review)
            page.evaluate("document.getElementById('disputeConfirm').onclick()")
            assert len(store['writes']) == 1
            # Closing/reopening and reload preserve only ID retry markers.
            close()
            page.reload(); page.wait_for_function('disputeFixture.ready'); idle()
            page.evaluate('id=>disputeFixture.invoke("openDisputeOption",id)', CLAIM); idle()
            hidden_or_disabled(review)
            stored = page.evaluate('JSON.stringify(sessionStorage)')
            for secret in (EXPLANATION, SUMMARY, DECLINE, 'private-receipt.jpg'):
                assert secret not in stored
            before_reads = len(store['calls'])
            page.locator('#disputeCheck').click(); idle()
            assert len(store['calls']) > before_reads
            expect(page.locator('#disputeAcknowledge')).to_be_visible()
            assert len(store['writes']) == 1
            page.locator('#disputeAcknowledge').click(); idle()
            assert len(store['writes']) == 1
            if drop == 'before':
                compose(explanation='Fresh explicit retry', summary='Fresh retry summary')
                confirm.click(); idle()
                assert len(store['writes']) == 2
                assert len(store['cases'][CASE]['evidence']) == 1
            else:
                expect(form).to_be_hidden()
                close()
                page.evaluate('id=>disputeFixture.invoke("openDispute",id)', CASE); idle()
                expect(form).to_be_hidden()
                expect(rounds).to_contain_text(SUMMARY)
                assert len(store['writes']) == 1
                assert len(store['cases'][CASE]['evidence']) == 1
            checked += 1

        # An ambiguous Admin decision is likewise checked without replaying it.
        for drop in ('before', 'after'):
            open_case(case_record(multiple=True), actor='admin')
            decide('owner')
            store['drop'] = drop
            confirm.click(); idle()
            hidden_or_disabled(review_decision)
            assert len(store['writes']) == 1
            page.locator('#disputeCheck').click(); idle()
            page.locator('#disputeAcknowledge').click(); idle()
            assert len(store['writes']) == 1
            if drop == 'before':
                decide('owner', 'New explicit decision after checking')
                confirm.click(); idle()
                assert len(store['writes']) == 2
            else:
                expect(operation.locator('option[value="owner"]')).to_have_count(0)
                assert store['cases'][CASE]['status'] == 'resolved'
            checked += 1

        # Acknowledgement and reviewed publication have the same ambiguity
        # guard. An accepted result can never be silently sent for a second time.
        for mutation in ('acknowledge', 'publish'):
            for drop in ('before', 'after'):
                if mutation == 'acknowledge':
                    open_option()
                    page.locator('#disputeAccept').click(); idle()
                else:
                    open_case(actor='admin')
                    publication = page.locator('#disputePublishSummary_' + EVIDENCE)
                    publication.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
                    publication.fill(REVIEWED)
                    page.locator('[data-dispute-publish="' + EVIDENCE + '"]').click(); idle()
                store['drop'] = drop
                confirm.click(); idle()
                assert len(store['writes']) == 1
                hidden_or_disabled(confirm)
                page.locator('#disputeCheck').click(); idle()
                page.locator('#disputeAcknowledge').click(); idle()
                assert len(store['writes']) == 1
                if drop == 'after':
                    if mutation == 'acknowledge':
                        expect(page.locator('#disputeAccept')).to_be_hidden()
                    else:
                        expect(page.locator('[data-dispute-publish="' + EVIDENCE + '"]')).to_have_count(0)
                else:
                    if mutation == 'acknowledge':
                        page.locator('#disputeAccept').click(); idle()
                    else:
                        publication = page.locator('#disputePublishSummary_' + EVIDENCE)
                        publication.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
                        publication.fill(REVIEWED)
                        page.locator('[data-dispute-publish="' + EVIDENCE + '"]').click(); idle()
                    confirm.click(); idle()
                    assert len(store['writes']) == 2
                checked += 1

        # A malformed successful write response is ambiguous, not permission
        # to replay. A fresh canonical GET establishes the committed result.
        open_case(case_record(multiple=True), actor='admin')
        decide('owner')
        store['malformed_write'] = dict(keys=['detail', 'version'], value=2)
        confirm.click(); idle()
        assert store['cases'][CASE]['status'] == 'resolved'
        assert len(store['writes']) == 1
        hidden_or_disabled(review_decision)
        page.locator('#disputeCheck').click(); idle()
        page.locator('#disputeAcknowledge').click(); idle()
        expect(operation.locator('option[value="owner"]')).to_have_count(0)
        assert len(store['writes']) == 1
        checked += 1

        # Normal/read-only/admin-only/offline semantics come from fresh server
        # permissions. A late mode change invalidates a prepared write.
        for actor in ('applicant', 'admin'):
            for mode in ('normal', 'read_only', 'admin_only', 'offline'):
                row = case_record(submitted=() if actor == 'applicant' else ('applicant',))
                navigate(row, actor=actor)
                store['mode'] = mode
                page.evaluate('id=>disputeFixture.invoke("openDispute",id)', CASE); idle()
                allowed = mode == 'normal' or actor == 'admin' and mode in ('read_only', 'admin_only')
                if allowed:
                    expect(dialog).to_be_visible()
                    expect(operation if actor == 'admin' else page.locator('#disputeExplanation')).to_be_enabled()
                elif mode == 'read_only':
                    expect(dialog).to_be_visible()
                    hidden_or_disabled(review)
                else:
                    expect(dialog).to_be_hidden()
                assert not store['writes']
                checked += 1
        open_option()
        compose()
        store['mode'] = 'read_only'
        confirm.click(); idle()
        assert not store['writes']
        hidden_or_disabled(review)
        checked += 1

        # A newly selected list owns the screen. A stale delivered denial from
        # the old list cannot erase newer results or current account state.
        for failure in (None, 403):
            navigate(case_record(), actor='admin')
            store['cases'][SECOND_CASE] = case_record(SECOND_CASE, status='resolved')
            if failure:
                store['failure'] = dict(method='GET', path=ADMIN_API, status=failure)
            hold('GET', ADMIN_API)
            page.evaluate('disputeFixture.invoke("refresh")'); held()
            store['failure'] = None
            page.locator('#disputeFilter').select_option('resolved')
            expect(case_list.locator(':scope > li')).to_have_count(1)
            expect(case_list.locator('[data-dispute-case="' + SECOND_CASE + '"]')).to_be_visible()
            release()
            expect(case_list.locator(':scope > li')).to_have_count(1)
            expect(case_list.locator('[data-dispute-case="' + SECOND_CASE + '"]')).to_be_visible()
            assert page.evaluate('disputeFixture.unauthorized') == []
            checked += 1

        # Dismissal or navigation while a server response is delivered cannot
        # resurrect private content or retain scroll lock.
        for method in ('GET', 'POST'):
            for dismissal in ('close', 'escape', 'navigation'):
                open_case(case_record(multiple=True), actor='admin')
                if method == 'POST':
                    decide('owner')
                    path = ADMIN_API + '/' + CASE + '/decision'
                    hold('POST', path)
                    confirm.click()
                else:
                    path = ADMIN_API + '/' + CASE
                    hold('GET', path)
                    page.locator('#disputeReload').click()
                held()
                old_url, old_history = page.url, page.evaluate('history.length')
                if dismissal == 'close':
                    close()
                elif dismissal == 'escape':
                    page.keyboard.press('Escape')
                else:
                    page.evaluate("dispatchEvent(new PopStateEvent('popstate'))")
                expect(dialog).to_be_hidden()
                release()
                assert_private_purged()
                assert page.url == old_url and page.evaluate('history.length') == old_history
                assert page.evaluate('document.body.style.overflow') == ''
                assert len(store['writes']) == (1 if method == 'POST' else 0)
                checked += 1

        # Held list/detail/original/decision success and denial remain in their
        # original account epoch. Sign-out, switch and returning to the same
        # account cannot restore private evidence or clear a newer session.
        for source in ('list', 'detail', 'attachment', 'decision'):
            for failure in (None, 403):
                for transition in ('sign out', 'other account', 'sign out and return'):
                    open_case(case_record(multiple=True), actor='admin')
                    if source == 'decision':
                        decide('owner')
                        method, path = 'POST', ADMIN_API + '/' + CASE + '/decision'
                    elif source == 'attachment':
                        method, path = 'GET', ADMIN_API + '/evidence/' + EVIDENCE + '/attachment'
                    else:
                        method, path = 'GET', ADMIN_API + ('/' + CASE if source == 'detail' else '')
                    if failure:
                        store['failure'] = dict(method=method, path=path, status=failure)
                    hold(method, path)
                    if source == 'decision':
                        confirm.click()
                    elif source == 'attachment':
                        control = page.locator('[data-dispute-attachment="' + EVIDENCE + '"]')
                        control.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
                        control.click()
                    elif source == 'detail':
                        page.locator('#disputeReload').click()
                    else:
                        page.evaluate('disputeFixture.invoke("refresh")')
                    held()
                    store['failure'] = None
                    page.evaluate('disputeFixture.setAccount(null)')
                    if transition == 'other account':
                        # A non-Admin account cannot inherit this Admin surface.
                        page.evaluate("disputeFixture.setAccount('other')")
                    elif transition == 'sign out and return':
                        page.evaluate("disputeFixture.setAccount('admin')")
                    page.wait_for_function('disputeFixture.pending===1&&disputeFixture.operations===1')
                    request_count = len(store['calls'])
                    release()
                    assert len(store['calls']) == request_count
                    assert_private_purged()
                    assert page.evaluate('disputeFixture.created.length') == 0
                    assert page.evaluate('disputeFixture.unauthorized') == []
                    if transition != 'sign out and return':
                        expect(page.locator('#disputeBrowser')).to_be_hidden()
                    checked += 1

        # Current-session revocation is different from a stale denial: it
        # purges originals and disables action even when discovered on download.
        for source in ('detail', 'attachment', 'decision'):
            for failure in (401, 403, 404):
                open_case(case_record(multiple=True), actor='admin')
                if source == 'decision':
                    decide('owner')
                    method, path = 'POST', ADMIN_API + '/' + CASE + '/decision'
                else:
                    method, path = 'GET', ADMIN_API + ('/' + CASE if source == 'detail'
                        else '/evidence/' + EVIDENCE + '/attachment')
                store['failure'] = dict(method=method, path=path, status=failure)
                if source == 'decision':
                    confirm.click()
                elif source == 'attachment':
                    control = page.locator('[data-dispute-attachment="' + EVIDENCE + '"]')
                    control.locator('xpath=ancestor::details').evaluate('(node)=>node.open=true')
                    control.click()
                else:
                    page.locator('#disputeReload').click()
                idle(); assert_private_purged()
                assert page.evaluate('disputeFixture.unauthorized') == ([failure] if failure in (401, 403) else [])
                if failure in (401, 403):
                    expect(page.locator('#disputeBrowser')).to_be_hidden()
                assert 'SECRET SQL' not in page.locator('body').text_content()
                checked += 1

        # A notification is a historical pointer, not acceptance/appeal. Both
        # new destination kinds must freshly authorize exact string IDs.
        navigate(case_record())
        store['notifications'] = [dict(id=str(9007199254743001 - index),
            notification_type='ownership_decline' if index else 'dispute_opened',
            title='Private historical dispute notice', body='Opening does not decide or acknowledge.',
            created_at=NOW, is_read=False, read_at=None, actor=None, destination=destination)
            for index, destination in enumerate((dict(kind='dispute', case_id=CASE),
                                               dict(kind='dispute_option', claim_id=CLAIM)))]
        page.evaluate('disputeFixture.refreshNotifications()'); idle()
        for index, destination in enumerate(('dispute', 'dispute_option')):
            identity = store['notifications'][index]['id']
            before = len(store['calls'])
            page.locator('[data-notification-open="' + identity + '"]').click(); idle()
            expect(dialog).to_be_visible()
            expected = API + ('/' + CASE if destination == 'dispute' else '/options/' + CLAIM)
            assert any(call['method'] == 'GET' and call['path'] == expected for call in store['calls'][before:])
            assert not store['writes']
            assert not any(item['is_read'] for item in store['notifications'])
            close()
            checked += 1

        # Real Japanese strings and narrow layouts retain safe literal user
        # content, string enum values, accessible labels and dismissal behavior.
        page.set_viewport_size({'width': 390, 'height': 844})
        open_case(case_record(multiple=True), actor='admin', locale='ja')
        assert page.locator('html').get_attribute('lang') == 'ja'
        assert page.locator('#disputeClose').text_content().strip() not in ('Close', 'action.close')
        assert 'cloud_disputes.' not in dialog.text_content()
        expect(rounds).to_contain_text(SUMMARY)
        operation.select_option('applicant')
        expect(operation).to_have_value('applicant')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.keyboard.press('Escape')
        assert_private_purged()
        assert page.evaluate('document.body.style.overflow') == ''
        checked += 1

        # Every private request uses the authenticated no-store boundary. No
        # original is linked to public media, gallery, or a cloud object URL.
        for request in page.evaluate('disputeFixture.requests'):
            assert request['required'] is True
            assert request['cache'] == 'no-store'
            assert request['credentials'] == 'omit'
            assert request['redirect'] == 'error'
        assert not page.locator('[src*="/media/"],[href*="/media/"]').count()

        assert not store['external'], store['external']
        assert not errors, errors
    print(f'{checked} synthetic ownership-dispute browser journeys passed: participant evidence, '
          'private originals, reviewed summaries, administrator decisions, conflict/unknown outcomes, '
          'service modes, account isolation, navigation and Japanese mobile')


if __name__ == '__main__':
    main()
