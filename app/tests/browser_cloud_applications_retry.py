"""Application retry, service-mode and dismissal browser regressions.

Uses the real application module, overlay lifecycle, CSS and translations. The
fixture auth wrapper pauses a delivered POST or GET response before handing it
to the component, so server success and UI reconciliation can be separated
without timers. Sign-out/account changes exercise the component's clear/render
boundary; this is not a Google authentication or live-service acceptance test.
Run explicitly, or through run_browser_checks.py, when Chromium is permitted.
"""
import json
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from browser_diagnostics import diagnostic_page
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-retry-fixture.invalid'
REVISION = 'c' * 32
HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/assets/cloud-account.css">
<link rel="stylesheet" href="/assets/ui-components.css">
<script src="/assets/i18n.js"></script><script src="/assets/overlays.js"></script>
</head><body><main><section id="selfApplications"></section></main>
<script type="module">
import {createApplications} from '/assets/cloud-account-applications.js';
let state={user:{app_user_id:'first'},identity:{email_verified:true}},busy=false;
const fixture=globalThis.fixture={hold:null,waiting:null,busy:false,ready:false};
const auth={authorizedFetch:async(url,options={})=>{
  const method=options.method||'GET';
  const response=await fetch(url,{...options,headers:{...options.headers,'X-Fixture-Account':state?.user?.app_user_id||''}});
  if(fixture.hold===method){
    fixture.hold=null;fixture.waiting=method;
    await new Promise(resolve=>{fixture.release=()=>{fixture.waiting=null;resolve()}});
  }
  return response;
}};
const component=createApplications({auth:()=>auth,state:()=>state,busy:()=>busy,work:async work=>{
  busy=fixture.busy=true;component.render();
  try{await work()}finally{busy=fixture.busy=false;component.render()}
}});
fixture.switchAccount=async id=>{
  component.clear();state=id?{user:{app_user_id:id},identity:{email_verified:true}}:null;
  component.render();if(state)await component.refresh();
};
component.render();await component.refresh();fixture.ready=true;
</script></body></html>'''


def application(status='error', serial='FIRST'):
    return dict(revision=REVISION, kind='acquire', serial=serial,
                individual_id='12', status=status, photos=[],
                expires_at=2000000000, claim_id=None, reasons=[])


def listing_application(status='pending'):
    return application(status) | dict(kind='listing', individual_id=None,
        challenge='ABCD1234', photos=['closeup', 'overview'],
        acquisition_date='2020-01-01', body='Private application explanation',
        payload=dict(manufacturer='Fender', serial_number='FIRST', model='Fixture',
                     finish='', year='', occurred_at='2020-01-01', body='Private application explanation'))


def main():
    catalog = ui_resources()
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in (
        'cloud-account-applications.js', 'overlays.js',
        'cloud-account.css', 'ui-components.css')}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(catalog) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    photo = BytesIO()
    Image.new('RGB', (12, 8), 'white').save(photo, format='JPEG')
    record = {}

    def reset(row=None, mode='normal'):
        record.update(row=row or application(), requests=[], photo_reads=[],
                      mode=mode, read_failure=None, write_failure=None)

    reset()
    errors = []
    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_applications_retry') as page:
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            assert parsed.scheme + '://' + parsed.netloc == BASE, request.url
            path = parsed.path
            if path == '/retry-fixture':
                route.fulfill(content_type='text/html', body=HTML)
            elif path.startswith('/assets/') and path[len('/assets/'):] in assets:
                name = path[len('/assets/'):]
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
            elif path == '/api/auth/applications' and request.method == 'GET':
                actor = request.headers.get('x-fixture-account')
                assert actor in ('first', 'second')
                record['requests'].append(('GET', actor))
                if actor == 'first' and record['read_failure']:
                    route.fulfill(status=record['read_failure'], json={'detail': 'Applicant unavailable.'})
                    return
                if actor == 'first' and record['mode'] == 'offline':
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                row = record['row'] if actor == 'first' else application('accepted', 'SECOND')
                route.fulfill(json={'items': [row], 'can_write': actor == 'second' or record['mode'] == 'normal'})
            elif path in ('/api/auth/applications/' + REVISION + '/retry',
                          '/api/auth/applications/' + REVISION + '/cancel') and request.method == 'POST':
                assert request.headers.get('x-fixture-account') == 'first'
                assert request.post_data_json == {}
                record['requests'].append(('POST', 'first'))
                if record['write_failure']:
                    route.fulfill(status=record['write_failure'], json={'detail': 'Applicant unavailable.'})
                    return
                if record['mode'] != 'normal':
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if path.endswith('/retry'):
                    assert record['row']['status'] == 'error'
                    record['row'] = record['row'] | {'status': 'pending'}
                else:
                    assert record['row']['status'] in ('draft', 'pending', 'processing', 'error')
                    record['row'] = record['row'] | {'status': 'cancelled'}
                route.fulfill(json=record['row'])
            elif path in ('/api/auth/applications/' + REVISION + '/photos/closeup',
                          '/api/auth/applications/' + REVISION + '/photos/overview') and request.method == 'GET':
                assert request.headers.get('x-fixture-account') == 'first'
                role = path.rsplit('/', 1)[1]
                assert role in record['row']['photos']
                assert record['mode'] in ('normal', 'read_only') and not record['read_failure']
                record['photo_reads'].append(role)
                route.fulfill(content_type='image/jpeg', body=photo.getvalue())
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + request.url)

        # Every request is intercepted; there is no live account or service.
        page.route('**/*', respond)
        dialog = page.locator('#applicationDialog')
        listing = page.locator('#selfApplications')

        def begin(held_method):
            reset()
            page.goto(BASE + '/retry-fixture')
            page.wait_for_function('fixture.ready')
            expect(listing.locator('li')).to_contain_text('Review retry required')
            listing.get_by_role('button', name='Detail', exact=True).click()
            page.locator('#applicationRetry').click()
            assert record['requests'] == [('GET', 'first')]
            page.evaluate('method => { fixture.hold=method; }', held_method)
            page.locator('#applicationRetry').click()
            page.wait_for_function('method => fixture.waiting===method', arg=held_method)
            # A repeated event while busy must not issue another POST.
            page.evaluate("document.getElementById('applicationRetry').onclick()")
            assert record['requests'].count(('POST', 'first')) == 1
            assert record['row']['status'] == 'pending'

        def release():
            page.evaluate('fixture.release()')
            page.wait_for_function('!fixture.busy')

        checked = 0
        for viewport in ({'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}):
            page.set_viewport_size(viewport)
            for held_method in ('POST', 'GET'):
                for dismissal in ('escape', 'close', 'backdrop'):
                    begin(held_method)
                    history_length = page.evaluate('history.length')
                    if dismissal == 'escape':
                        page.keyboard.press('Escape')
                    elif dismissal == 'close':
                        dialog.get_by_role('button', name='Close', exact=True).click()
                    else:
                        page.mouse.click(1, 1)
                    expect(dialog).not_to_be_visible()
                    release()
                    expect(listing.locator('li')).to_contain_text('Pending review')
                    expect(listing.locator('li')).not_to_contain_text('Review retry required')
                    expect(dialog).not_to_be_visible()
                    assert record['requests'] == [('GET', 'first'), ('POST', 'first'), ('GET', 'first')]
                    assert page.evaluate('document.body.style.overflow') == ''
                    assert page.url == BASE + '/retry-fixture'
                    assert page.evaluate('history.length') == history_length
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    listing.get_by_role('button', name='Detail', exact=True).click()
                    expect(page.locator('#applicationRetry')).not_to_be_visible()
                    page.keyboard.press('Escape')
                    checked += 1

        for held_method in ('POST', 'GET'):
            for transition in ('sign out', 'other account', 'sign out and return'):
                begin(held_method)
                if transition == 'other account':
                    page.evaluate("async () => await fixture.switchAccount('second')")
                else:
                    page.evaluate('async () => await fixture.switchAccount(null)')
                    if transition == 'sign out and return':
                        page.evaluate("async () => await fixture.switchAccount('first')")
                count_before = len(record['requests'])
                release()
                assert len(record['requests']) == count_before
                expect(dialog).not_to_be_visible()
                if transition == 'sign out':
                    expect(listing).not_to_be_visible()
                    expect(listing.locator('li')).to_have_count(0)
                elif transition == 'other account':
                    expect(listing.locator('li')).to_contain_text('SECOND')
                    expect(listing.locator('li')).not_to_contain_text('FIRST')
                else:
                    expect(listing.locator('li')).to_contain_text('Pending review')
                checked += 1

        def open_application(row=None, mode='normal'):
            reset(row or listing_application(), mode)
            page.goto(BASE + '/retry-fixture')
            page.wait_for_function('fixture.ready')
            listing.get_by_role('button', name='Detail', exact=True).click()
            expect(dialog).to_be_visible()

        def wait_idle():
            page.wait_for_function('!fixture.busy')

        def assert_mutations_blocked():
            for identity in ('applicationListing', 'applicationAcquire', 'applicationCreate',
                             'applicationSubmit', 'applicationCancel', 'applicationRetry',
                             'application_closeup', 'application_overview'):
                expect(page.locator('#' + identity)).to_be_disabled()
            previous = list(record['requests'])
            # Native disabled controls and direct/repeated handler calls must
            # both refuse mutations, including the hidden form submit handler.
            page.evaluate('''async () => {
              for (const id of ['applicationListing','applicationAcquire',
                  'applicationSubmit','applicationCancel','applicationRetry']) {
                await document.getElementById(id).onclick();
              }
              document.querySelector('#applicationDialog form').onsubmit({preventDefault(){}});
              await document.getElementById('applicationRetry').onclick();
            }''')
            wait_idle()
            assert record['requests'] == previous

        def assert_private_cleared():
            expect(listing.locator('li')).to_have_count(0)
            expect(dialog).not_to_be_visible()
            assert 'FIRST' not in dialog.text_content()
            assert 'Private application explanation' not in dialog.text_content()
            assert page.locator('#applicationDialog img[src]').count() == 0
            expect(page.locator('#applicationListing')).to_be_disabled()

        # Read-only affects every mutation while retaining details, photo GETs
        # and refresh. Actual Chromium disabled-state checks catch fieldset
        # inheritance errors that a lightweight DOM fixture cannot model.
        for viewport in ({'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}):
            page.set_viewport_size(viewport)
            open_application(mode='read_only')
            expect(listing.locator('li')).to_contain_text('Pending review')
            expect(dialog).to_contain_text('Applications are read-only.')
            expect(page.locator('#applicationCancel')).to_be_visible()
            assert_mutations_blocked()
            for role in ('closeup', 'overview'):
                view = dialog.get_by_role('button', name='View ' + role, exact=True)
                expect(view).to_be_enabled()
                view.click()
                wait_idle()
            assert record['photo_reads'] == ['closeup', 'overview']
            expect(dialog.locator('img')).to_have_count(2)
            page.wait_for_function('''() => [...document.querySelectorAll('#applicationDialog img')]
                .every(image => !image.hidden && image.complete && image.naturalWidth === 12)''')
            expect(page.locator('#applicationRefresh')).to_be_enabled()
            assert record['requests'] == [('GET', 'first')]
            expect(dialog).to_contain_text('Private application explanation')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            checked += 1

        # Cover the visible submit/retry states as well as pending cancellation.
        for status, control in (('draft', 'applicationSubmit'), ('error', 'applicationRetry')):
            open_application(listing_application(status), 'read_only')
            expect(page.locator('#' + control)).to_be_visible()
            assert_mutations_blocked()
            assert record['requests'] == [('GET', 'first')]
            checked += 1

        # A server mode change can beat the stale normal-mode UI. A rejected
        # cancellation revalidates reading without losing the list or dialog.
        open_application()
        expect(page.locator('#applicationCancel')).to_be_enabled()
        record['mode'] = 'read_only'
        page.locator('#applicationCancel').click()
        wait_idle()
        assert record['requests'] == [('GET', 'first'), ('POST', 'first'), ('GET', 'first')]
        assert record['row']['status'] == 'pending'
        expect(listing.locator('li')).to_contain_text('FIRST')
        expect(listing.locator('li')).to_contain_text('Pending review')
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('The service mode changed.')
        assert_mutations_blocked()
        record['mode'] = 'normal'
        page.locator('#applicationRefresh').click()
        wait_idle()
        expect(page.locator('#applicationCancel')).to_be_enabled()
        expect(dialog).not_to_contain_text('Applications are read-only.')
        page.locator('#applicationCancel').click()
        wait_idle()
        assert record['row']['status'] == 'cancelled'
        expect(listing.locator('li')).to_contain_text('Cancelled')
        expect(page.locator('#applicationCancel')).not_to_be_visible()
        checked += 1

        # Refresh/focus should update access on an already open draft without
        # discarding the user's unsaved input. A disabled create handler also
        # needs coverage with selected=null, when the early selected guard
        # cannot mask a missing permission check.
        reset()
        page.goto(BASE + '/retry-fixture')
        page.wait_for_function('fixture.ready')
        page.locator('#applicationListing').click()
        page.locator('#application_manufacturer').fill('Unsaved maker')
        page.locator('#application_serial_number').fill('UNSAVED123')
        record['mode'] = 'read_only'
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        wait_idle()
        expect(page.locator('#applicationCreate')).to_be_visible()
        assert_mutations_blocked()
        expect(page.locator('#application_manufacturer')).to_have_value('Unsaved maker')
        expect(page.locator('#application_serial_number')).to_have_value('UNSAVED123')
        record['mode'] = 'normal'
        page.locator('#applicationRefresh').click()
        wait_idle()
        expect(page.locator('#applicationCreate')).to_be_enabled()
        expect(page.locator('#application_manufacturer')).to_have_value('Unsaved maker')
        expect(page.locator('#application_serial_number')).to_have_value('UNSAVED123')
        assert not any(method == 'POST' for method, _ in record['requests'])
        checked += 1

        # A mode denial is distinguishable from revoked read/auth access. All
        # inaccessible reads purge private rows, details and cached photo URLs.
        for failure in ('offline', 401, 403):
            open_application()
            dialog.get_by_role('button', name='View closeup', exact=True).click()
            wait_idle()
            expect(dialog.locator('img[src]')).to_have_count(1)
            if failure == 'offline':
                record['mode'] = 'offline'
            else:
                record['read_failure'] = failure
            page.locator('#applicationRefresh').click()
            wait_idle()
            assert_private_cleared()
            checked += 1

        for failure in ('offline', 401, 403):
            open_application()
            if failure == 'offline':
                record['mode'] = 'offline'
            else:
                record['write_failure'] = failure
            page.locator('#applicationCancel').click()
            wait_idle()
            assert_private_cleared()
            expected = [('GET', 'first'), ('POST', 'first')]
            if failure == 'offline':
                expected.append(('GET', 'first'))
            assert record['requests'] == expected
            assert record['row']['status'] == 'pending'
            checked += 1

        # Dismissing before a denied POST arrives must still update account
        # access, but it must never reopen the user's dismissed dialog.
        for failure in ('read_only', 403):
            open_application()
            if failure == 'read_only':
                record['mode'] = 'read_only'
            else:
                record['write_failure'] = failure
            page.evaluate("fixture.hold='POST'")
            page.locator('#applicationCancel').click()
            page.wait_for_function("fixture.waiting==='POST'")
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            release()
            expect(dialog).not_to_be_visible()
            if failure == 'read_only':
                expect(listing.locator('li')).to_contain_text('FIRST')
                expect(listing.locator('li')).to_contain_text('Pending review')
                expect(page.locator('#applicationListing')).to_be_disabled()
                assert record['requests'] == [('GET', 'first'), ('POST', 'first'), ('GET', 'first')]
            else:
                assert_private_cleared()
                assert record['requests'] == [('GET', 'first'), ('POST', 'first')]
            assert page.evaluate('document.body.style.overflow') == ''
            checked += 1

        # A late denial belongs only to its original account epoch, including
        # a sign-out and return to the same account identifier.
        for failure in ('read_only', 403):
            for transition in ('other account', 'sign out', 'sign out and return'):
                open_application()
                if failure == 'read_only':
                    record['mode'] = 'read_only'
                else:
                    record['write_failure'] = failure
                page.evaluate("fixture.hold='POST'")
                page.locator('#applicationCancel').click()
                page.wait_for_function("fixture.waiting==='POST'")
                if transition == 'other account':
                    page.evaluate("async () => await fixture.switchAccount('second')")
                else:
                    page.evaluate('async () => await fixture.switchAccount(null)')
                    if transition == 'sign out and return':
                        page.evaluate("async () => await fixture.switchAccount('first')")
                previous = list(record['requests'])
                release()
                assert record['requests'] == previous
                expect(dialog).not_to_be_visible()
                if transition == 'other account':
                    expect(listing.locator('li')).to_contain_text('SECOND')
                    expect(listing.locator('li')).not_to_contain_text('FIRST')
                    expect(page.locator('#applicationListing')).to_be_enabled()
                elif transition == 'sign out':
                    expect(listing).not_to_be_visible()
                    expect(listing.locator('li')).to_have_count(0)
                else:
                    expect(listing.locator('li')).to_contain_text('FIRST')
                    expect(listing.locator('li')).to_contain_text('Pending review')
                checked += 1
        assert not errors, errors
    print(f'{checked} application journeys: retry, service modes, private reads, denial recovery, dismissal and account isolation passed')


if __name__ == '__main__':
    main()
