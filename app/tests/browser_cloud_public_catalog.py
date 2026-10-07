"""Public catalog browser journeys using only disposable intercepted fixtures.

Run explicitly, or through run_browser_checks.py, on a developer machine or CI
where Chromium is permitted. This module is prepared/compiled independently of
execution. No live authentication, PostgreSQL, marketplace, cloud service, or
photo download is used. It runs the production HTML, CSS, JS and auth adapter.
"""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_cloud_account import SDK
from browser_diagnostics import diagnostic_page
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-public-catalog-fixture.invalid'
API = '/api/public/guitars'
BIG_ID = '9007199254741009'
TEXT = '<img src=x onerror=globalThis.fixtureXss=true>'
PRIVATE = 'PRIVATE-FIXTURE-MUST-NOT-RENDER'

# Hold an already received response rather than racing arbitrary wall-clock
# sleeps. An AbortController alone cannot protect this case; the route epoch
# must prevent the late continuation from repopulating another guitar or list.
HOLD_SCRIPT = r'''
(() => {
  const realFetch = globalThis.fetch.bind(globalThis);
  const fixture = globalThis.catalogFixture = {pending: 0, holds: [], waiting: {}};
  fixture.hold = (path, query = '', id = 'held') => fixture.holds.push({path, query, id});
  fixture.release = id => {const resolve = fixture.waiting[id]; delete fixture.waiting[id]; resolve();};
  globalThis.fetch = async (input, options) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const index = fixture.holds.findIndex(item => item.path === url.pathname &&
      (!item.query || url.searchParams.get('q') === item.query));
    const hold = index < 0 ? null : fixture.holds.splice(index, 1)[0];
    fixture.pending++;
    try {
      let response = await realFetch(input, options);
      if (hold) {
        // Fully consume and detach it so later abort cannot cancel its body.
        const body = await response.arrayBuffer();
        response = new Response(body, {status: response.status, statusText: response.statusText, headers: response.headers});
        await new Promise(resolve => {fixture.waiting[hold.id] = resolve;});
      }
      return response;
    } finally {fixture.pending--;}
  };
})();
'''


def fixtures():
    guitars = {str(i): dict(id=str(i), manufacturer='Fender', model=f'Model {i:02}',
        finish='Sunburst', year='1960', serial_number='SERIAL-' + str(i), photo=None)
        for i in range(1, 28)}
    guitars['10'].update(manufacturer='<b>Fender</b>', model=TEXT)
    guitars[BIG_ID] = dict(id=BIG_ID, manufacturer='Zemaitis', model='Big ID guitar',
                          finish='', year=None, serial_number='BIGINT-SERIAL', photo=None)
    history = [dict(id=str(i), claim_type='listing', ownership_kind=None,
        occurred_at='2026-01-01', created_at='2026-01-01', verification_status='positive',
        items=[], source_url=None) for i in range(100, 127)]
    history[-1].update(items=[dict(field_name='finish', value_text=TEXT)],
                       source_url='https://reverb.com/item/12345')
    history[-2].update(verification_status='unverified',
        items=[dict(field_name='neck', value_text=PRIVATE)], source_url='https://reverb.com/item/22222')
    history[-3].update(source_url='javascript:globalThis.fixtureXss=true')
    history[-4].update(verification_status='negative',
        items=[dict(field_name='neck', value_text=PRIVATE)], source_url='https://reverb.com/item/33333')
    history[-5].update(source_url='https://user:password@reverb.com/item/12345')
    return guitars, list(reversed(history))


def main():
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in (
        'cloud-account-favorites.js', 'cloud-public-catalog.js', 'cloud-public-catalog.css', 'identity-platform-auth.js',
        'cloud-auth-loader.js')}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    html = (STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8')
    guitars, history = fixtures()
    state = dict(requests=[], writes=[], external=[], failures={}, mode='normal', role='member')
    errors = []
    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_public_catalog') as page:
        page.add_init_script(HOLD_SCRIPT)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            path = parsed.path
            if parsed.netloc == 'www.gstatic.com' and path.startswith('/firebasejs/'):
                route.fulfill(content_type='text/javascript', body='export const initializeApp=config=>config;'
                    if path.endswith('/firebase-app.js') else SDK)
                return
            if parsed.scheme + '://' + parsed.netloc != BASE:
                state['external'].append(request.url)
                route.abort()
                return
            if path.startswith('/assets/') and path[len('/assets/'):] in assets:
                name = path[len('/assets/'):]
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
                return
            if path == '/' or path.startswith('/guitars/'):
                route.fulfill(content_type='text/html', body=html)
                return
            if path == '/account':
                route.fulfill(content_type='text/html', body='<p id="accountFixture">Account destination fixture</p>')
                return
            if path == '/favicon.ico':
                route.fulfill(status=204)
                return
            params = {key: value[-1] for key, value in parse_qs(parsed.query, keep_blank_values=True).items()}
            entry = dict(method=request.method, path=path, params=params,
                         authorization=request.headers.get('authorization'))
            state['requests'].append(entry)
            if request.method != 'GET':
                state['writes'].append(entry)
                route.fulfill(status=405, json={'detail': 'Fixture is read-only'})
                return
            if path in state['failures']:
                code = state['failures'][path]
                route.fulfill(status=code, json={'detail': {'code': 'service_restricted'}
                              if code == 403 else 'Fixture data unavailable'})
                return
            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture-key',
                    'authDomain': 'fixture-project.firebaseapp.com', 'projectId': 'fixture-project'}, 'tenant': ''})
                return
            if path == '/api/auth/me':
                assert entry['authorization']
                route.fulfill(json={'user': {'id': '1', 'app_user_id': 'public-fixture-user',
                    'display_name': 'Fixture User', 'account_type': 'user', 'role': state['role']},
                    'identity': {'email_verified': True}})
                return
            if path.startswith('/api/auth/favorites/'):
                assert entry['authorization']
                route.fulfill(json={'individual_id': path.rsplit('/', 1)[-1], 'favorite': False})
                return
            if (path == API or path.startswith(API + '/')) and (state['mode'] == 'offline' or
                    state['mode'] == 'admin_only' and (not entry['authorization'] or state['role'] != 'admin')):
                route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                return
            if path == '/api/service/status':
                route.fulfill(json=dict(mode=state['mode'], message='Fixture maintenance' if state['mode'] != 'normal' else ''))
                return
            if path == API:
                assert set(params) <= {'q', 'sort', 'page', 'limit'}, params
                q, sort = params.get('q', '').lower(), params.get('sort', 'newest')
                assert sort in ('newest', 'oldest', 'maker', 'model')
                rows = [row for row in guitars.values() if not q or any(q in str(row[key]).lower()
                        for key in ('manufacturer', 'model', 'serial_number'))]
                if sort in ('newest', 'oldest'):
                    rows.sort(key=lambda row: int(row['id']), reverse=sort == 'newest')
                else:
                    key = 'manufacturer' if sort == 'maker' else 'model'
                    rows.sort(key=lambda row: (row[key].lower(), int(row['id'])))
                number, limit = int(params.get('page', 1)), int(params.get('limit', 24))
                assert 1 <= limit <= 50 and number > 0
                route.fulfill(json=dict(items=deepcopy(rows[(number-1)*limit:number*limit]),
                    total=str(len(rows)), page=number, page_size=limit,
                    total_pages=(len(rows)+limit-1)//limit))
                return
            if path.startswith(API + '/'):
                suffix = path[len(API)+1:].split('/')
                row = guitars.get(suffix[0])
                if row is None:
                    route.fulfill(status=404, json={'detail': 'Guitar not found.'})
                elif len(suffix) == 1:
                    route.fulfill(json=dict(row, specifications=[dict(field_name='neck', value_text='Maple ' + TEXT)],
                        body=PRIVATE, current_owner_name=PRIVATE, location_country=PRIVATE,
                        storage_path='gcs-content-v1:' + PRIVATE))
                else:
                    assert suffix[1:] == ['chronicle']
                    assert set(params) <= {'after', 'limit'}
                    after, limit = int(params.get('after', 0)), int(params.get('limit', 25))
                    rows = [item for item in history if not after or int(item['id']) < after]
                    selected = rows[:limit]
                    route.fulfill(json=dict(items=deepcopy(selected),
                        next_after=selected[-1]['id'] if len(rows) > limit else None))
                return
            raise AssertionError('Unexpected fixture request: ' + request.url)

        page.context.route('**/*', respond)

        def idle():
            page.wait_for_function("catalogFixture.pending===0 && "
                "document.getElementById('catalogRows').getAttribute('aria-busy')==='false' && "
                "document.getElementById('catalogDetail').getAttribute('aria-busy')==='false'")

        def search(value):
            page.locator('#catalogSearch').fill(value)
            page.locator('#catalogSearchSubmit').click()
            idle()

        def open_guitar(identifier):
            link = page.locator('#catalogRows .guitar-detail-link[href^="/guitars/' + identifier + '"]')
            link.click()
            expect(page.locator('#detailContent')).to_be_visible()
            idle()

        def clean_content():
            assert page.evaluate('globalThis.fixtureXss !== true')
            assert page.locator('#publicCatalog img, #publicCatalog b, #publicCatalog script').count() == 0
            assert PRIVATE not in page.locator('#publicCatalog').inner_text()
            assert not state['external'], state['external']
            assert not state['writes'], state['writes']

        page.goto(BASE + '/')
        page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true')
        idle()
        rows = page.locator('#catalogRows .guitar-card')
        expect(rows).to_have_count(24)
        expect(page.locator('#catalogNext')).to_be_enabled()
        expect(page.locator('#catalogPrevious')).to_be_disabled()
        assert all(not row['authorization'] for row in state['requests'])
        assert page.locator('#accountLink').get_attribute('href') == '/account'
        page.locator('#catalogNext').click(); idle()
        expect(rows).to_have_count(4)
        assert parse_qs(urlsplit(page.url).query)['page'] == ['2']
        page.locator('#catalogPrevious').click(); idle()
        expect(rows).to_have_count(24)
        page.locator('#catalogSort').select_option('oldest'); idle()
        assert next(row for row in reversed(state['requests']) if row['path'] == API)['params'].get('sort') == 'oldest'
        expect(page.locator('#catalogPrevious')).to_be_disabled()

        search('SERIAL-10')
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text(TEXT)
        assert parse_qs(urlsplit(page.url).query)['q'] == ['SERIAL-10']
        list_url = page.url
        open_guitar('10')
        detail_url = page.url
        assert urlsplit(detail_url).path == '/guitars/10'
        expect(page.locator('#detailTitle')).to_contain_text(TEXT)
        expect(page.locator('#detailSpecifications')).to_contain_text('Maple ' + TEXT)
        expect(page.locator('#detailPhoto')).to_be_visible()
        assert page.locator('#acquireLink').get_attribute('href') == '/account?acquire=10'
        assert page.locator('#addClaimLink').get_attribute('href') == '/account?claim=10'
        expect(page.locator('#chronicleEntries .chronicle-record')).to_have_count(25)
        source = page.locator('#chronicleEntries a[href="https://reverb.com/item/12345"]')
        expect(source).to_have_count(1)
        assert {'noopener', 'noreferrer'} <= set((source.get_attribute('rel') or '').split())
        assert source.get_attribute('target') == '_blank'
        assert page.locator('#chronicleEntries a').count() == 1
        expect(page.locator('#chronicleEntries .unverified')).to_have_count(1)
        expect(page.locator('#chronicleEntries .negative')).to_have_count(1)
        clean_content()
        page.locator('#chronicleMore').click(); idle()
        expect(page.locator('#chronicleEntries .chronicle-record')).to_have_count(27)
        expect(page.locator('#chronicleMore')).to_be_hidden()
        page.go_back(); idle()
        assert page.url == list_url
        expect(page.locator('#detailContent')).to_be_hidden()
        page.go_forward(); idle()
        assert page.url == detail_url
        expect(page.locator('#detailContent')).to_be_visible()

        # URL state survives mobile navigation, dismissal and reload.
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.locator('#catalogList')).to_be_hidden()
        expect(page.locator('#catalogBack')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#catalogBack').click(); idle()
        expect(page.locator('#catalogList')).to_be_visible()
        expect(rows).to_have_count(1)
        assert page.locator('#catalogSearch').input_value() == 'SERIAL-10'
        open_guitar('10')
        page.reload(); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(page.locator('#detailContent')).to_be_visible()
        page.locator('#catalogLanguage').select_option('ja')
        expect(page.locator('html')).to_have_attribute('lang', 'ja')
        assert page.locator('#catalogBack').inner_text() != 'Back to catalog'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#catalogLanguage').select_option('en')
        page.locator('#catalogBack').click(); idle()
        page.set_viewport_size({'width': 1440, 'height': 1000})

        # Empty, missing, failed and maintenance reads never retain stale rows.
        search('no-such-public-guitar')
        expect(rows).to_have_count(0)
        expect(page.locator('#catalogNext')).to_be_disabled()
        expect(page.locator('#catalogStatus')).not_to_have_text('')
        state['failures'][API] = 503
        page.locator('#catalogRefresh').click(); idle()
        expect(rows).to_have_count(0)
        expect(page.locator('#catalogStatus')).not_to_have_text('')
        del state['failures'][API]
        search('SERIAL-10'); open_guitar('10')
        state['failures'][API + '/10'] = 503
        page.locator('#catalogRefresh').click(); idle()
        expect(page.locator('#detailContent')).to_be_hidden()
        expect(page.locator('#detailStatus')).not_to_have_text('')
        del state['failures'][API + '/10']
        page.locator('#catalogRefresh').click(); idle()
        expect(page.locator('#detailContent')).to_be_visible()
        state['mode'] = 'offline'; state['failures'][API] = 403
        state['failures'][API + '/10'] = 403
        page.locator('#catalogRefresh').click(); idle()
        expect(rows).to_have_count(0)
        expect(page.locator('#detailContent')).to_be_hidden()
        state['mode'] = 'normal'; state['failures'].clear()
        page.goto(BASE + '/guitars/999999')
        page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(page.locator('#detailContent')).to_be_hidden()
        expect(page.locator('#detailStatus')).not_to_have_text('')

        # SDK/load failures may still browse anonymously; rejected restored
        # identities must never silently retry the same reads as a guest.
        state['failures']['/api/auth/config'] = 503
        page.goto(BASE + '/'); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(rows).to_have_count(24)
        expect(page.locator('#authNotice')).to_be_visible()
        del state['failures']['/api/auth/config']
        state['mode'] = 'read_only'
        page.reload(); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(rows).to_have_count(24)
        expect(page.locator('#serviceNotice')).to_be_visible()
        state['mode'] = 'admin_only'
        page.locator('#catalogRefresh').click(); idle()
        expect(rows).to_have_count(0)
        page.evaluate('''() => {
            sessionStorage.setItem('fixture-sdk-email', 'catalog@example.invalid');
            sessionStorage.setItem('verified-catalog@example.invalid', 'true');
        }''')
        page.reload(); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(rows).to_have_count(0)  # Verified member is still not an Admin.
        state['role'] = 'admin'
        page.reload(); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(rows).to_have_count(24)
        assert next(row for row in reversed(state['requests']) if row['path'] == API)['authorization']
        state['mode'] = 'offline'
        page.locator('#catalogRefresh').click(); idle()
        expect(rows).to_have_count(0)  # Offline includes a verified Admin.
        state['mode'] = 'normal'
        state['failures']['/api/auth/me'] = 401
        previous = len(state['requests'])
        page.reload(); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        expect(rows).to_have_count(0)
        expect(page.locator('#authNotice')).to_be_visible()
        assert not any(row['path'].startswith(API) for row in state['requests'][previous:])
        del state['failures']['/api/auth/me']
        page.evaluate('sessionStorage.clear()')

        # Newer route/search wins even after an older successful response returns.
        page.goto(BASE + '/'); page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true'); idle()
        page.evaluate("catalogFixture.hold('/api/public/guitars', 'SERIAL-10', 'search')")
        page.locator('#catalogSearch').fill('SERIAL-10')
        page.locator('#catalogSearchSubmit').click()
        page.wait_for_function("Boolean(catalogFixture.waiting.search)")
        page.locator('#catalogSearch').fill('BIGINT-SERIAL')
        page.locator('#catalogSearchSubmit').click()
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('Big ID guitar')
        page.evaluate("catalogFixture.release('search')"); idle()
        expect(rows).to_have_count(1); expect(rows).to_contain_text('Big ID guitar')
        assert parse_qs(urlsplit(page.url).query)['q'] == ['BIGINT-SERIAL']
        open_guitar(BIG_ID)
        assert urlsplit(page.url).path == '/guitars/' + BIG_ID
        assert page.locator('#acquireLink').get_attribute('href') == '/account?acquire=' + BIG_ID
        assert page.locator('#addClaimLink').get_attribute('href') == '/account?claim=' + BIG_ID
        page.locator('#catalogBack').click(); idle()
        search('SERIAL-10')
        page.evaluate("catalogFixture.hold('/api/public/guitars/10', '', 'detail')")
        page.locator('#catalogRows .guitar-detail-link').click()
        page.wait_for_function("Boolean(catalogFixture.waiting.detail)")
        page.go_back()
        expect(page.locator('#detailContent')).to_be_hidden()
        page.evaluate("catalogFixture.release('detail')"); idle()
        expect(page.locator('#detailContent')).to_be_hidden()
        assert urlsplit(page.url).path == '/'
        open_guitar('10')
        page.evaluate("catalogFixture.hold('/api/public/guitars/10/chronicle', '', 'chronicle')")
        page.locator('#chronicleMore').click()
        page.wait_for_function("Boolean(catalogFixture.waiting.chronicle)")
        page.locator('#catalogBack').click()
        page.locator('#catalogSearch').fill('BIGINT-SERIAL')
        page.locator('#catalogSearchSubmit').click()
        expect(rows).to_have_count(1); expect(rows).to_contain_text('Big ID guitar')
        page.locator('#catalogRows .guitar-detail-link').click()
        expect(page.locator('#detailContent')).to_be_visible()
        expect(page.locator('#chronicleEntries .chronicle-record')).to_have_count(25)
        page.evaluate("catalogFixture.release('chronicle')"); idle()
        expect(page.locator('#chronicleEntries .chronicle-record')).to_have_count(25)
        assert urlsplit(page.url).path == '/guitars/' + BIG_ID
        page.locator('#catalogBack').click(); idle()
        search('SERIAL-10'); open_guitar('10')
        clean_content()
        page.locator('#acquireLink').click()
        expect(page.locator('#accountFixture')).to_be_visible()
        assert page.url == BASE + '/account?acquire=10'
        assert not state['writes'] and not state['external'] and not errors, (state, errors)
    print('Cloud public catalog browser: anonymous search/sort/pages, safe structured detail, '
          'Chronicle pagination, source links, mobile/Japanese and browser history, empty/errors/modes, '
          'stale response isolation, bigint IDs and non-writing Acquire handoff passed.')


if __name__ == '__main__':
    main()
