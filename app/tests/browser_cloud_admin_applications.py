"""Private administrator application browser regressions, with no live service.

The real module, overlay lifecycle, styles and translations run against an
intercepted API. Responses can be held after the server has answered, separating
an accepted decision from a late browser reconciliation without timing sleeps.
Run explicitly, or through run_browser_checks.py, where Chromium is permitted.
This fixture is not an Identity Platform, PostgreSQL or external-MCP acceptance
test and never launches a reviewer.
"""
import copy
import json
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from browser_diagnostics import diagnostic_page
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-admin-applications-fixture.invalid'
API = '/api/admin/applications'
REVISION = '0' * 31 + '1'
SECOND_REVISION = 'f' * 32
PRIVATE = 'Private application explanation <img src=x onerror=globalThis.fixtureXss=true>'
MANUAL = dict(mode='external_mcp', automatic_start=False,
              instructions='An external MCP client must explicitly claim and answer the queue.')
HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/assets/cloud-account.css">
<link rel="stylesheet" href="/assets/cloud-console.css">
<script src="/assets/i18n.js"></script><script src="/assets/overlays.js"></script>
</head><body><header><h1>Administrator application fixture</h1></header>
<main class="console-workspace"><section class="console-main-layer">
<section class="panel" id="applicationBrowser"></section></section></main>
<script type="module">
import {createApplicationBrowser} from '/assets/cloud-console-applications.js';
let actor='first';
const fixture=globalThis.fixture={ready:false,pending:0,operations:0,holds:[],waiting:{},
  unauthorized:[],guitars:[],created:[],revoked:[]};
const createURL=URL.createObjectURL.bind(URL),revokeURL=URL.revokeObjectURL.bind(URL);
URL.createObjectURL=blob=>{const url=createURL(blob);fixture.created.push(url);return url};
URL.revokeObjectURL=url=>{fixture.revoked.push(url);revokeURL(url)};
fixture.hold=(method,path,id='held')=>fixture.holds.push({method,path,id});
fixture.release=id=>{const resolve=fixture.waiting[id];delete fixture.waiting[id];resolve()};
const request=async(path,options={},binary=false)=>{
  const method=options.method||'GET',pathname=new URL(path,location.href).pathname;
  const index=fixture.holds.findIndex(item=>item.method===method&&item.path===pathname);
  const hold=index<0?null:fixture.holds.splice(index,1)[0];
  fixture.pending++;
  try{
    const response=await fetch(path,{...options,headers:{...options.headers,
      'Authorization':'Bearer fixture-'+actor,'X-Fixture-Account':actor||''}});
    const payload=binary&&response.ok?await response.blob():await response.json();
    if(hold)await new Promise(resolve=>{fixture.waiting[hold.id]=resolve});
    if(!response.ok)throw Object.assign(Error('Operation unavailable'),{
      status:response.status,code:payload.detail?.code,detail:payload.detail});
    if(binary&&!response.headers.get('Content-Type')?.startsWith('image/jpeg'))throw Error('Unexpected image');
    return payload;
  }finally{fixture.pending--}
};
const component=createApplicationBrowser({request,authorized:()=>!!actor,
  onUnauthorized:error=>{fixture.unauthorized.push(error.status);actor=null;component.clear();component.render()},
  onGuitar:id=>fixture.guitars.push(id)});
fixture.invoke=(name,...args)=>{
  fixture.operations++;
  Promise.resolve(component[name](...args)).finally(()=>{fixture.operations--});
};
fixture.setAccount=id=>{actor=id;component.clear();component.render();if(actor)fixture.invoke('refresh')};
component.render();await component.refresh();fixture.ready=true;
</script></body></html>'''


def application(index=1, *, status='pending', kind='listing', serial=None):
    """Use the wire format: identifiers and counts are strings, not JS numbers."""
    return dict(
        revision=f'{index:032x}', request_kind=kind, status=status,
        applicant_id='9007199254740993', applicant_name='<b>Private applicant</b>',
        product_name='<b>Private guitar</b>', serial=serial or f'FIRST{index:03}',
        individual_id='9007199254740995' if kind == 'acquire' else None,
        claim_id=None, verification_status=None, created_at=1780000000,
        submitted_at=1780000010, completed_at=None, error=None, attempts=2,
        lease_until=None, paused_answers=[dict(kind='image_review', received_at=1780000020)],
        admin_actions=['accept', 'reject', 'retry', 'cancel'], management_version='1' * 64,
        body=PRIVATE, acquisition_date='2020-01-01', challenge='ABCD1234',
        photos=['closeup', 'overview', 'reference'], result={'message': '<script>fixtureXss=true</script>'},
        received={'answer': '<b>Retained answer</b>'}, report='Private diagnostic <img src=x>',
        product_details={'manufacturer': 'Fender', 'model': '<b>Fixture model</b>'},
        product_observations={'finish': '<b>Observed finish</b>'},
        admin_review={'reason': '<b>Prior administrator reason</b>'},
        events=[dict(id='9007199254740997', at=1780000030, kind='review_paused', note='<b>Private event</b>')],
        review_enabled=False, manual_review=copy.deepcopy(MANUAL))


def summary(row):
    private = {'body', 'acquisition_date', 'challenge', 'photos', 'result', 'received',
               'report', 'product_details', 'product_observations', 'admin_review',
               'events', 'review_enabled', 'manual_review'}
    return {key: value for key, value in row.items() if key not in private}


def main():
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in (
        'cloud-console-applications.js', 'overlays.js', 'cloud-account.css', 'cloud-console.css')}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    photo = BytesIO()
    Image.new('RGB', (12, 8), 'white').save(photo, format='JPEG')
    record = {}

    def reset(row=None):
        first = row or application()
        rows = [first] + [application(index, kind='acquire',
                status='error' if index == 2 else 'pending',
                serial='NEEDLE002' if index == 2 else None) for index in range(2, 28)]
        second = application(99, kind='acquire', serial='SECOND-PRIVATE')
        second['revision'] = SECOND_REVISION
        second['body'] = 'Private second account explanation'
        record.clear()
        record.update(rows={row['revision']: row for row in rows}, second=second,
                      requests=[], decisions=[], photo_reads=[], read_failure=None,
                      write_failure=None, photo_failure=None, review_enabled=False)

    reset()
    errors = []
    checked = 0
    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_admin_applications') as page:
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            assert parsed.scheme + '://' + parsed.netloc == BASE, request.url
            path = parsed.path
            if path == '/admin-applications-fixture':
                route.fulfill(content_type='text/html', body=HTML)
                return
            if path.startswith('/assets/') and path[len('/assets/'):] in assets:
                name = path[len('/assets/'):]
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
                return
            assert path == API or path.startswith(API + '/'), 'Unexpected fixture request: ' + request.url
            actor = request.headers.get('x-fixture-account')
            assert actor in ('first', 'second')
            assert request.headers.get('authorization') == 'Bearer fixture-' + actor
            params = {key: value[-1] for key, value in parse_qs(parsed.query, keep_blank_values=True).items()}
            entry = dict(method=request.method, path=path, actor=actor, params=params)
            record['requests'].append(entry)
            if request.method == 'GET' and record['read_failure'] and actor == 'first':
                route.fulfill(status=record['read_failure'], json={'detail': {'code': 'admin_required'}})
                return
            if path == API and request.method == 'GET':
                limit = int(params.get('limit', 25))
                assert 1 <= limit <= 25
                assert set(params) <= {'q', 'status', 'kind', 'after', 'limit'}
                rows = list(record['rows'].values()) if actor == 'first' else [record['second']]
                q, status, kind = (params.get(key, '') for key in ('q', 'status', 'kind'))
                matching = [row for row in rows if
                    (not q or q.lower() in ' '.join(str(row[key]) for key in (
                        'revision', 'applicant_id', 'applicant_name', 'product_name', 'serial')).lower())
                    and (not status or row['status'] == status)
                    and (not kind or row['request_kind'] == kind)]
                following = [row for row in matching if row['revision'] > params.get('after', '')]
                route.fulfill(json=dict(items=[summary(row) for row in following[:limit]],
                    next_after=following[limit - 1]['revision'] if len(following) > limit else None,
                    total=str(len(matching)), review_enabled=record['review_enabled'], manual_review=MANUAL))
                return
            suffix = path[len(API) + 1:].split('/')
            row = record['rows'].get(suffix[0]) if actor == 'first' else record['second']
            assert row is not None and row['revision'] == suffix[0], path
            if len(suffix) == 1 and request.method == 'GET':
                route.fulfill(json=row | {'review_enabled': record['review_enabled']})
            elif len(suffix) == 3 and suffix[1] == 'photos' and request.method == 'GET':
                assert suffix[2] in row['photos']
                record['photo_reads'].append((actor, suffix[0], suffix[2]))
                if record['photo_failure']:
                    route.fulfill(status=record['photo_failure'], json={'detail': 'Photo unavailable.'})
                else:
                    route.fulfill(content_type='image/jpeg', body=photo.getvalue())
            elif len(suffix) == 2 and suffix[1] == 'decision' and request.method == 'POST':
                data = request.post_data_json
                assert set(data) == {'operation', 'reason', 'expected_version'}
                assert data['operation'] in ('accept', 'reject', 'retry', 'cancel')
                assert data['reason'] == data['reason'].strip() and 1 <= len(data['reason']) <= 2000
                record['decisions'].append((actor, suffix[0], data))
                if record['write_failure']:
                    route.fulfill(status=record['write_failure'], json={'detail': {'code': 'application_conflict'}})
                elif data['expected_version'] != row['management_version']:
                    route.fulfill(status=409, json={'detail': {'code': 'application_conflict'}})
                else:
                    row.update(status={'accept': 'accepted', 'reject': 'rejected', 'retry': 'pending',
                        'cancel': 'cancelled'}[data['operation']], management_version='2' * 64,
                        admin_review={'operation': data['operation'], 'reason': data['reason']})
                    route.fulfill(json=row | {'review_enabled': record['review_enabled']})
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + request.url)

        # Unknown/public-media URLs and any automatic reviewer request fail here.
        page.route('**/*', respond)
        root = page.locator('#applicationBrowser')
        rows = page.locator('#adminApplicationRows')
        dialog = page.locator('#adminApplicationDialog')
        review = page.locator('#adminApplicationReviewAction')
        confirm = page.locator('#adminApplicationConfirm')
        reason = page.locator('#adminApplicationReason')
        operation = page.locator('#adminApplicationOperation')

        def idle():
            page.wait_for_function('fixture.pending===0&&fixture.operations===0')

        def navigate(row=None, *, locale='en'):
            reset(row)
            page.goto(BASE + '/admin-applications-fixture')
            page.wait_for_function('fixture.ready')
            if page.evaluate('YGCI18n.locale') != locale:
                page.evaluate('locale=>localStorage.setItem("ygc_ui_language",locale)', locale)
                page.reload()
                page.wait_for_function('fixture.ready')
            expect(root).to_be_visible()
            expect(rows).to_contain_text('FIRST001')

        def open_application(row=None, *, locale='en'):
            navigate(row, locale=locale)
            rows.locator('button').first.click()
            idle()
            expect(dialog).to_be_visible()
            expect(page.locator('#adminApplicationDetailFields')).to_contain_text('FIRST001')

        def hold(method, path, identity='held'):
            page.evaluate('args=>fixture.hold(...args)', [method, path, identity])

        def held(identity='held'):
            page.wait_for_function('id=>typeof fixture.waiting[id]==="function"', arg=identity)

        def release(identity='held'):
            page.evaluate('id=>fixture.release(id)', identity)
            idle()

        def prepare(selected='accept', message='Evidence checked by administrator'):
            operation.select_option(selected)
            reason.fill(message)
            review.click()
            expect(confirm).to_be_visible()
            expect(confirm).to_be_enabled()

        def assert_purged():
            expect(root).to_be_hidden()
            expect(rows.locator(':scope > *')).to_have_count(0)
            expect(dialog).to_be_hidden()
            assert PRIVATE not in dialog.text_content()
            assert 'FIRST001' not in dialog.text_content()
            assert 'Private diagnostic' not in dialog.text_content()
            expect(dialog.locator('img[src]')).to_have_count(0)
            assert page.evaluate('fixture.created.every(url=>fixture.revoked.includes(url))')
            expect(confirm).to_be_disabled()

        # Search and both filters use the server query, and navigation retains
        # them while an entirely new search resets the opaque revision cursor.
        navigate()
        expect(rows.locator(':scope > *')).to_have_count(25)
        expect(page.locator('#adminApplicationPrevious')).to_be_disabled()
        page.locator('#adminApplicationNext').click(); idle()
        expect(rows.locator(':scope > *')).to_have_count(2)
        assert record['requests'][-1]['params']['after'] == f'{25:032x}'
        expect(page.locator('#adminApplicationNext')).to_be_disabled()
        page.locator('#adminApplicationPrevious').click(); idle()
        expect(rows.locator(':scope > *')).to_have_count(25)
        page.locator('#adminApplicationSearch').fill(' NEEDLE ')
        page.locator('#adminApplicationStatusFilter').select_option('error')
        page.locator('#adminApplicationKindFilter').select_option('acquire')
        page.locator('#adminApplicationSearchSubmit').click(); idle()
        expect(rows.locator(':scope > *')).to_have_count(1)
        expect(rows).to_contain_text('NEEDLE002')
        query = record['requests'][-1]['params']
        assert query['q'] == 'NEEDLE' and query['status'] == 'error' and query['kind'] == 'acquire'
        assert not query.get('after')
        page.locator('#adminApplicationRefresh').click(); idle()
        assert record['requests'][-1]['params'] == query
        checked += 1

        # User-provided strings in every detail section remain literal text;
        # photos use authenticated fetches and object URLs, never public links.
        open_application()
        expect(page.locator('#adminApplicationManualReview')).to_have_text(MANUAL['instructions'])
        expect(page.locator('#adminApplicationDetailManual')).to_have_text(MANUAL['instructions'])
        expect(page.locator('#adminApplicationDetailReview')).to_contain_text('OFF')
        expect(rows).to_contain_text('<b>Private applicant</b>')
        expect(dialog).to_contain_text(PRIVATE)
        for identity, text in (
                ('Result', '<script>fixtureXss=true</script>'), ('Received', '<b>Retained answer</b>'),
                ('Report', 'Private diagnostic <img src=x>'), ('ProductDetails', '<b>Fixture model</b>'),
                ('ProductObservations', '<b>Observed finish</b>'),
                ('AdminReview', '<b>Prior administrator reason</b>'), ('Events', '<b>Private event</b>')):
            expect(page.locator('#adminApplication' + identity)).to_contain_text(text)
        assert page.evaluate('globalThis.fixtureXss===undefined')
        expect(dialog.locator('script,b')).to_have_count(0)
        assert not record['photo_reads']
        for role in ('closeup', 'overview', 'reference'):
            page.locator('#adminApplicationPhoto_' + role).click(); idle()
        assert [role for _, _, role in record['photo_reads']] == ['closeup', 'overview', 'reference']
        expect(dialog.locator('figure img[src]')).to_have_count(3)
        page.wait_for_function('''() => [...document.querySelectorAll('#adminApplicationPhotos img[src]')]
            .every(image=>image.src.startsWith('blob:')&&image.complete&&image.naturalWidth===12)''')
        page.evaluate('fixture.setAccount(null)'); idle(); assert_purged()
        checked += 1

        # Review OFF permits explicit administrative decisions. All four
        # operations require a nonblank reason and a separate confirmation.
        for selected in ('accept', 'reject', 'retry', 'cancel'):
            open_application(application(status='error' if selected == 'retry' else 'pending'))
            operation.select_option(selected)
            reason.fill('   ')
            expect(review).to_be_disabled()
            page.evaluate("document.getElementById('adminApplicationReviewAction').click()")
            assert not record['decisions']
            prepare(selected, '  Explicit ' + selected + ' reason  ')
            assert not record['decisions']
            reason.fill('Updated ' + selected + ' reason')
            expect(confirm).to_be_disabled()
            review.click(); expect(confirm).to_be_enabled()
            alternative = 'cancel' if selected != 'cancel' else 'accept'
            operation.select_option(alternative)
            expect(confirm).to_be_disabled()
            prepare(selected, '  Explicit ' + selected + ' reason  ')
            hold('POST', API + '/' + REVISION + '/decision')
            confirm.click(); held()
            # Bypass native disabled buttons to exercise the busy handler guard.
            page.evaluate("document.getElementById('adminApplicationConfirm').onclick()")
            assert len(record['decisions']) == 1
            assert record['decisions'][0] == ('first', REVISION, dict(operation=selected,
                reason='Explicit ' + selected + ' reason', expected_version='1' * 64))
            release()
            expect(dialog).to_be_visible()
            assert record['review_enabled'] is False
            assert record['rows'][REVISION]['status'] == {
                'accept': 'accepted', 'reject': 'rejected', 'retry': 'pending', 'cancel': 'cancelled'}[selected]
            assert len(record['decisions']) == 1
            checked += 1

        # Closing or Escape while the server's accepted response is pending
        # cannot reopen the dialog, alter history or leave the page locked.
        for viewport in ({'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}):
            page.set_viewport_size(viewport)
            for held_method in ('GET', 'POST'):
                for dismissal in ('close', 'escape'):
                    open_application(locale='ja' if viewport['width'] == 390 else 'en')
                    if held_method == 'POST':
                        prepare('retry', 'Explicit queued retry; do not start a reviewer')
                        hold('POST', API + '/' + REVISION + '/decision')
                        confirm.click()
                    else:
                        hold('GET', API + '/' + REVISION)
                        page.locator('#adminApplicationDetailRefresh').click()
                    held()
                    original_url, history_length = page.url, page.evaluate('history.length')
                    if dismissal == 'close':
                        page.locator('#adminApplicationClose').click()
                    else:
                        page.keyboard.press('Escape')
                    expect(dialog).to_be_hidden()
                    release()
                    expect(dialog).to_be_hidden()
                    assert page.url == original_url and page.evaluate('history.length') == history_length
                    assert page.evaluate('document.body.style.overflow') == ''
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert len(record['decisions']) == (1 if held_method == 'POST' else 0)
                    checked += 1

        # A changed version and a generic failed write both remove permission
        # to decide from stale detail until an explicit successful detail GET.
        for failure in (409, 500):
            open_application()
            prepare('reject', 'Rejected after manual inspection')
            if failure == 409:
                record['rows'][REVISION]['management_version'] = '3' * 64
            else:
                record['write_failure'] = failure
            confirm.click(); idle()
            expect(dialog).to_be_visible()
            expect(review).to_be_disabled()
            expect(confirm).to_be_disabled()
            assert len(record['decisions']) == 1
            page.evaluate("document.getElementById('adminApplicationConfirm').onclick()")
            assert len(record['decisions']) == 1
            record['write_failure'] = None
            page.locator('#adminApplicationDetailRefresh').click(); idle()
            prepare('reject', 'Freshly checked reason')
            confirm.click(); idle()
            assert len(record['decisions']) == 2
            assert record['decisions'][-1][2]['expected_version'] == ('3' * 64 if failure == 409 else '1' * 64)
            checked += 1

        # A newer query wins within one account even if an earlier delivered
        # list response arrives later. Its stale denial cannot sign the user out.
        for failure in (None, 403):
            navigate()
            record['read_failure'] = failure
            hold('GET', API)
            page.locator('#adminApplicationRefresh').click(); held()
            record['read_failure'] = None
            page.locator('#adminApplicationSearch').fill('NEEDLE')
            page.locator('#adminApplicationSearchSubmit').click()
            expect(rows).to_contain_text('NEEDLE002')
            release()
            expect(rows.locator(':scope > *')).to_have_count(1)
            expect(rows).not_to_contain_text('FIRST001')
            assert not page.evaluate('fixture.unauthorized')
            checked += 1

        # The same guarantee applies when a different detail is selected while
        # an old GET or private photo is waiting, without an account change.
        for source in ('detail', 'photo'):
            for failure in (None, 403):
                open_application()
                if source == 'detail':
                    record['read_failure'] = failure
                    hold('GET', API + '/' + REVISION)
                    page.locator('#adminApplicationDetailRefresh').click()
                else:
                    record['photo_failure'] = failure
                    hold('GET', API + '/' + REVISION + '/photos/closeup')
                    page.locator('#adminApplicationPhoto_closeup').click()
                held()
                record['read_failure'] = record['photo_failure'] = None
                page.evaluate('revision=>fixture.invoke("detail",revision)', f'{2:032x}')
                expect(page.locator('#adminApplicationDetailFields')).to_contain_text('NEEDLE002')
                release()
                expect(dialog).to_be_visible()
                expect(page.locator('#adminApplicationDetailFields')).to_contain_text('NEEDLE002')
                expect(page.locator('#adminApplicationDetailFields')).not_to_contain_text('FIRST001')
                expect(dialog.locator('img[src]')).to_have_count(0)
                assert not page.evaluate('fixture.unauthorized')
                assert not page.evaluate('fixture.created')
                checked += 1

        # Two loads of one photo have their own ordering within a detail epoch.
        # A late failure cannot discard the successful newer preview or auth.
        open_application()
        record['photo_failure'] = 403
        hold('GET', API + '/' + REVISION + '/photos/closeup')
        page.locator('#adminApplicationPhoto_closeup').click(); held()
        record['photo_failure'] = None
        page.locator('#adminApplicationPhoto_closeup').click()
        expect(dialog.locator('img[src]')).to_have_count(1)
        release()
        expect(dialog.locator('img[src]')).to_have_count(1)
        assert len(page.evaluate('fixture.created')) == 1
        assert not page.evaluate('fixture.unauthorized')
        checked += 1

        # Delivered but held list/detail/photo results must not resurrect
        # private content after sign-out or overwrite a newer account epoch.
        for source in ('list', 'detail', 'photo'):
            for transition in ('sign out', 'other account', 'sign out and return'):
                open_application()
                if source == 'list':
                    page.locator('#adminApplicationClose').click()
                    hold('GET', API)
                    page.locator('#adminApplicationRefresh').click()
                elif source == 'detail':
                    hold('GET', API + '/' + REVISION)
                    page.locator('#adminApplicationDetailRefresh').click()
                else:
                    hold('GET', API + '/' + REVISION + '/photos/closeup')
                    page.locator('#adminApplicationPhoto_closeup').click()
                held()
                if transition == 'other account':
                    page.evaluate("fixture.setAccount('second')")
                    expect(rows).to_contain_text('SECOND-PRIVATE')
                else:
                    page.evaluate('fixture.setAccount(null)')
                    if transition == 'sign out and return':
                        page.evaluate("fixture.setAccount('first')")
                        expect(rows).to_contain_text('FIRST001')
                previous_count = len(record['requests'])
                release()
                assert len(record['requests']) == previous_count
                expect(dialog).to_be_hidden()
                expect(dialog.locator('img[src]')).to_have_count(0)
                if transition == 'sign out':
                    assert_purged()
                elif transition == 'other account':
                    expect(rows).to_contain_text('SECOND-PRIVATE')
                    expect(rows).not_to_contain_text('FIRST001')
                else:
                    expect(rows).to_contain_text('FIRST001')
                checked += 1

        # Late POST success or denial also belongs to the original epoch.
        # Neither can clear a new administrator session or issue extra reads.
        for failure in (None, 403):
            for transition in ('sign out', 'other account', 'sign out and return'):
                open_application()
                prepare('accept')
                record['write_failure'] = failure
                hold('POST', API + '/' + REVISION + '/decision')
                confirm.click(); held()
                page.evaluate('fixture.setAccount(null)')
                if transition != 'sign out':
                    account = 'second' if transition == 'other account' else 'first'
                    page.evaluate('id=>fixture.setAccount(id)', account)
                    expect(rows).to_contain_text('SECOND-PRIVATE' if account == 'second' else 'FIRST001')
                count_before = len(record['requests'])
                release()
                assert len(record['requests']) == count_before
                assert not page.evaluate('fixture.unauthorized')
                expect(dialog).to_be_hidden()
                if transition == 'sign out':
                    assert_purged()
                else:
                    expect(root).to_be_visible()
                    expect(rows).to_contain_text('SECOND-PRIVATE' if transition == 'other account' else 'FIRST001')
                checked += 1

        # Current-session access revocation purges both visible and cached
        # private data even when it is discovered by a photo or decision call.
        for source in ('list', 'detail', 'photo', 'decision'):
            for failure in (401, 403):
                open_application()
                page.locator('#adminApplicationPhoto_closeup').click(); idle()
                if source == 'decision':
                    prepare('cancel')
                    record['write_failure'] = failure
                    confirm.click()
                elif source == 'photo':
                    record['photo_failure'] = failure
                    page.locator('#adminApplicationPhoto_overview').click()
                else:
                    record['read_failure'] = failure
                    if source == 'list':
                        page.locator('#adminApplicationClose').click()
                        page.locator('#adminApplicationRefresh').click()
                    else:
                        page.locator('#adminApplicationDetailRefresh').click()
                idle(); assert_purged()
                assert page.evaluate('fixture.unauthorized') == [failure]
                checked += 1

        # Japanese UI labels must resolve through the real catalog, while
        # protocol enum values, user text, and opaque identifiers stay intact.
        page.set_viewport_size({'width': 390, 'height': 844})
        open_application(locale='ja')
        assert page.locator('html').get_attribute('lang') == 'ja'
        assert not page.locator('#adminApplicationClose').text_content().strip().startswith('admin_applications.')
        assert page.locator('#adminApplicationClose').text_content().strip() != 'Close'
        expect(dialog).to_contain_text(PRIVATE)
        operation.select_option('accept')
        expect(operation).to_have_value('accept')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.keyboard.press('Escape')
        assert page.evaluate('document.body.style.overflow') == ''
        checked += 1
        assert not errors, errors
    print(f'{checked} administrator application journeys: filters, private evidence, explicit decisions, '
          'conflicts, stale responses, dismissal, account isolation and Japanese mobile passed')


if __name__ == '__main__':
    main()
