"""Application retry/dismissal browser regression, using fixture-only HTTP routes.

Uses the real application module, overlay lifecycle, CSS and translations. The
fixture auth wrapper pauses a delivered POST or GET response before handing it
to the component, so server success and UI reconciliation can be separated
without timers. Sign-out/account changes exercise the component's clear/render
boundary; this is not a Google authentication or live-service acceptance test.
Run explicitly, or through run_browser_checks.py, when Chromium is permitted.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

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


def main():
    catalog = ui_resources()
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in (
        'cloud-account-applications.js', 'overlays.js',
        'cloud-account.css', 'ui-components.css')}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(catalog) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    record = {'row': application(), 'requests': []}
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
                row = record['row'] if actor == 'first' else application('accepted', 'SECOND')
                route.fulfill(json={'items': [row]})
            elif path == '/api/auth/applications/' + REVISION + '/retry' and request.method == 'POST':
                assert request.headers.get('x-fixture-account') == 'first'
                assert request.post_data_json == {}
                assert record['row']['status'] == 'error'
                record['requests'].append(('POST', 'first'))
                record['row'] = application('pending')
                route.fulfill(json=record['row'])
            else:
                raise AssertionError('Unexpected fixture request: ' + request.method + ' ' + request.url)

        # Every request is intercepted; there is no live account or service.
        page.route('**/*', respond)
        dialog = page.locator('#applicationDialog')
        listing = page.locator('#selfApplications')

        def begin(held_method):
            record.update(row=application(), requests=[])
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
        assert not errors, errors
    print(f'{checked} application retry journeys: response races, dismissal, repeat clicks and account isolation passed')


if __name__ == '__main__':
    main()
