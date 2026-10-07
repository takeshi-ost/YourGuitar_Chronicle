"""Real Chromium private Favorites and visibility journeys, entirely synthetic.

Production HTML, CSS, JavaScript and the auth adapter run against intercepted
in-memory fixtures. No live identity, PostgreSQL, photo, cloud service or public
profile publishing is accessed. Run only on an authorized Mac/CI browser runner;
compiling this module is not evidence that Chromium acceptance has passed.
"""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_cloud_account import SDK
from browser_cloud_public_catalog import HOLD_SCRIPT
from browser_diagnostics import diagnostic_page
from ygc.cloud_registration import DOCUMENTS
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-favorites-visibility-fixture.invalid'
FAVORITES = '/api/auth/favorites'
VISIBILITY = '/api/auth/profile/visibility'
PUBLIC = '/api/public/guitars'
BIG_ID = '9223372036854775807'
TARGET = '9007199254741999'
REVISION = '9007199254741111'
FIELDS = ('birth_visibility', 'residence_visibility', 'bio_visibility', 'avatar_visibility')
CHOICES = ('Public', 'Members', 'Followers', 'Private')
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'
SECRET = 'PRIVATE-FIXTURE-MUST-NOT-RENDER'
AUDIT = r'''
(() => {
  const original = globalThis.fetch.bind(globalThis);
  const fixture = globalThis.favoritesFixture = {requests: [], holdLogout: false, waitingLogout: false};
  globalThis.fetch = (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname.startsWith('/api/auth/favorites') || url.pathname === '/api/auth/profile/visibility') {
      fixture.requests.push({path: url.pathname, method: options.method || 'GET',
        credentials: options.credentials, cache: options.cache, redirect: options.redirect,
        authorization: new Headers(options.headers).get('authorization')});
    }
    return original(input, options);
  };
})();
'''
SDK_WITH_CONTROLS = SDK.replace(
    'export async function signOut(){',
    '''export async function signOut(){
      if (globalThis.favoritesFixture?.holdLogout) {
        favoritesFixture.holdLogout = false; favoritesFixture.waitingLogout = true;
        await new Promise(resolve => { favoritesFixture.releaseLogout = () => {
          favoritesFixture.waitingLogout = false; resolve();
        }; });
      }
    ''') + r'''
const fixtureIdentityListeners = new Set();
export function onAuthStateChanged(_auth, listener) {
  fixtureIdentityListeners.add(listener);
  return () => fixtureIdentityListeners.delete(listener);
}
globalThis.favoritesFixtureSwitchUser = email => {
  auth.currentUser = makeUser(email);
  sessionStorage.setItem('fixture-sdk-email', email);
  sessionStorage.setItem('verified-' + email, 'true');
  for (const listener of fixtureIdentityListeners) listener(auth.currentUser);
};
'''


def main():
    names = [path.name for path in STATIC.glob('cloud-account-*.js')]
    names += ['cloud-account.css', 'cloud-public-catalog.js', 'cloud-public-catalog.css',
              'cloud-auth-loader.js', 'identity-platform-auth.js', 'overlays.js', 'ui-components.css']
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    account_html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    public_html = (STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8')
    users = {name: dict(id=str(index), app_user_id='fixture-' + name,
        display_name=name.title(), account_type='user', role='member', status='active')
        for index, name in enumerate(('alice', 'other'), 1)}
    favorite_ids = [BIG_ID] + [str(9007199254741300 - index) for index in range(27)]
    guitars = {identifier: dict(id=identifier, manufacturer='Fixture maker',
        model='Private favorite ' + str(index), finish='Natural', year='1965',
        serial_number='SYNTHETIC-' + identifier, photo=None)
        for index, identifier in enumerate(favorite_ids + [TARGET])}
    guitars[BIG_ID].update(manufacturer='Maker ' + ATTACK, model='Big integer guitar')
    guitars[TARGET].update(model='Toggle target')
    initial_fields = dict(zip(FIELDS, CHOICES))
    store = dict(favorites={'alice': set(favorite_ids), 'other': set()},
        visibility={'alice': dict(profile_revision=REVISION, fields=deepcopy(initial_fields)),
                    'other': dict(profile_revision='3', fields=dict.fromkeys(FIELDS, 'Private'))},
        calls=[], writes=[], external=[], mode='normal', drop=None, reject=None,
        malformed=None, read_error=None)
    errors, audits = [], []

    def private(path):
        return path == FAVORITES or path.startswith(FAVORITES + '/') or path == VISIBILITY

    def favorite_page(actor, query):
        assert set(query) <= {'after', 'limit'} and query.get('limit') == ['25'], query
        after = query.get('after', [None])[0]
        source = sorted(store['favorites'][actor], key=int, reverse=True)
        source = [identifier for identifier in source if after is None or int(identifier) < int(after)]
        selected = source[:25]
        result = dict(items=[deepcopy(guitars[identifier]) for identifier in selected],
            total=str(len(store['favorites'][actor])),
            next_after=selected[-1] if len(source) > 25 else None)
        if store['malformed'] == 'favorite-id' and selected:
            result['items'][0]['id'] = int(result['items'][0]['id'])
        if store['malformed'] == 'favorite-private' and selected:
            result['items'][0]['owner_email'] = SECRET
        return result

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_favorites_visibility') as page:
        page.add_init_script(HOLD_SCRIPT + AUDIT)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            path, method = parsed.path, request.method
            if parsed.netloc == 'www.gstatic.com' and path.startswith('/firebasejs/'):
                route.fulfill(content_type='text/javascript',
                    body='export const initializeApp = config => config;'
                    if path.endswith('/firebase-app.js') else SDK_WITH_CONTROLS)
                return
            if parsed.scheme + '://' + parsed.netloc != BASE:
                store['external'].append(request.url)
                route.abort()
                return
            if path.startswith('/assets/') and path.removeprefix('/assets/') in assets:
                name = path.removeprefix('/assets/')
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
                return
            if path == '/account':
                route.fulfill(content_type='text/html', body=account_html)
                return
            if path == '/' or path.startswith('/guitars/'):
                route.fulfill(content_type='text/html', body=public_html)
                return
            if path == '/favicon.ico':
                route.fulfill(status=204)
                return
            assert request.resource_type != 'image', 'Favorites and visibility must not fetch photos'
            token = request.headers.get('authorization', '')
            actor = token.replace('Bearer fixture-verified-', '').replace('Bearer fixture-', '').split('@')[0]
            query = parse_qs(parsed.query, keep_blank_values=True)
            call = dict(path=path, method=method, actor=actor, query=query, authorization=token)
            store['calls'].append(call)
            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture', 'authDomain': 'fixture.firebaseapp.com',
                    'projectId': 'fixture'}, 'tenant': ''})
            elif path == '/api/auth/registration':
                route.fulfill(json={'documents': DOCUMENTS})
            elif path == '/api/service/status':
                route.fulfill(json={'mode': store['mode'], 'message': ''})
            elif path == '/api/auth/me' and actor in users:
                route.fulfill(json={'user': users[actor], 'identity': {'email_verified': 'fixture-verified-' in token}})
            elif path == PUBLIC:
                assert method == 'GET' and set(query) <= {'q', 'sort', 'page', 'limit'}
                source = sorted(guitars.values(), key=lambda row: int(row['id']), reverse=True)
                term = query.get('q', [''])[0].lower()
                source = [row for row in source if not term or any(term in str(row[key]).lower()
                    for key in ('manufacturer', 'model', 'serial_number'))]
                number, limit = int(query.get('page', ['1'])[0]), int(query.get('limit', ['24'])[0])
                route.fulfill(json=dict(items=deepcopy(source[(number - 1) * limit:number * limit]),
                    total=str(len(source)), page=number, page_size=limit, total_pages=(len(source) + limit - 1) // limit))
            elif path.startswith(PUBLIC + '/'):
                assert method == 'GET'
                parts = path.removeprefix(PUBLIC + '/').split('/')
                row = guitars.get(parts[0])
                if row is None:
                    route.fulfill(status=404, json={'detail': 'Unavailable'})
                elif len(parts) == 1:
                    route.fulfill(json=dict(deepcopy(row), specifications=[], owner_email=SECRET, storage_path=SECRET))
                else:
                    assert parts[1:] == ['chronicle']
                    route.fulfill(json={'items': [], 'next_after': None})
            elif actor not in users or 'fixture-verified-' not in token:
                route.fulfill(status=403, json={'detail': 'Synthetic verified identity required'})
            elif private(path):
                assert actor in users and token.startswith('Bearer fixture-verified-')
                assert request.headers.get('sec-fetch-site') != 'cross-site'
                if store['mode'] in ('offline', 'admin_only') or method == 'PUT' and store['mode'] == 'read_only':
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if method == 'GET':
                    if store['read_error']:
                        route.fulfill(status=store['read_error'], json={'detail': SECRET})
                    elif path == FAVORITES:
                        route.fulfill(json=favorite_page(actor, query))
                    elif path == VISIBILITY:
                        assert not query
                        value = deepcopy(store['visibility'][actor])
                        if store['malformed'] == 'visibility-revision':
                            value['profile_revision'] = int(value['profile_revision'])
                        if store['malformed'] == 'visibility-private':
                            value['fields']['birth_date'] = SECRET
                        route.fulfill(json=value)
                    else:
                        assert not query
                        identifier = path.removeprefix(FAVORITES + '/')
                        assert identifier in guitars, identifier
                        value = dict(individual_id=identifier, favorite=identifier in store['favorites'][actor])
                        if store['malformed'] == 'favorite-state':
                            value['individual_id'] = int(identifier)
                        route.fulfill(json=value)
                    return
                assert method == 'PUT' and not query and path != FAVORITES
                assert request.headers['content-type'].startswith('application/json')
                payload = request.post_data_json
                store['writes'].append(dict(call, body=deepcopy(payload)))
                if store['reject']:
                    status, store['reject'] = store['reject'], None
                    route.fulfill(status=status, json={'detail': SECRET})
                    return
                drop, store['drop'] = store['drop'], None
                if drop == 'before':
                    route.abort('failed')
                    return
                if path == VISIBILITY:
                    assert set(payload) == {'revision', 'fields'}
                    assert isinstance(payload['revision'], str) and set(payload['fields']) == set(FIELDS)
                    assert all(value in CHOICES for value in payload['fields'].values())
                    current = store['visibility'][actor]
                    if payload['revision'] != current['profile_revision']:
                        route.fulfill(status=409, json={'detail': SECRET})
                        return
                    current.update(profile_revision=str(int(current['profile_revision']) + 1), fields=deepcopy(payload['fields']))
                    result = deepcopy(current)
                else:
                    identifier = path.removeprefix(FAVORITES + '/')
                    assert identifier in guitars and set(payload) == {'favorite'} and type(payload['favorite']) is bool
                    selected = store['favorites'][actor]
                    selected.add(identifier) if payload['favorite'] else selected.discard(identifier)
                    result = dict(individual_id=identifier, favorite=payload['favorite'])
                if drop == 'after':
                    route.abort('failed')
                else:
                    route.fulfill(json=result)
            elif path == '/api/auth/profile':
                assert method == 'GET', 'Visibility settings must never edit profile contents'
                route.fulfill(json={'profile_revision': '1', 'fields': {'display_name': users[actor]['display_name'],
                    'location_country': '', 'location_region': '', 'bio': ''}})
            elif path == '/api/auth/avatar':
                assert method == 'GET'
                route.fulfill(status=404, json={'detail': 'No fixture avatar'})
            elif path in ('/api/auth/applications', '/api/auth/identity-corrections'):
                assert method == 'GET'
                route.fulfill(json={'items': [], 'next_after': None, 'can_write': True})
            elif path == '/api/auth/guitars':
                assert method == 'GET'
                route.fulfill(json={'items': [], 'total': '0', 'next_after': None})
            elif path in ('/api/auth/ownership-transfers', '/api/auth/ownership-disputes', '/api/auth/ownership-disputes/options'):
                assert method == 'GET'
                route.fulfill(json={'viewer_user_id': users[actor]['id'], 'items': [], 'next_after': None, 'can_write': True})
            elif path == '/api/auth/notifications':
                assert method == 'GET'
                route.fulfill(json={'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True})
            else:
                raise AssertionError('Unexpected private settings journey request: ' + method + ' ' + path)

        page.context.route('**/*', respond)
        rows = page.locator('#favoritesList [data-favorite-id]')
        values = page.locator('#visibilityValues')
        dialog = page.locator('#visibilityDialog')

        def idle(account=False):
            page.wait_for_function('catalogFixture.pending === 0')
            if account:
                expect(page.locator('#signOut')).to_be_enabled()
            else:
                page.wait_for_function("document.getElementById('catalogDetail').getAttribute('aria-busy') === 'false'")

        def audit():
            audits.extend(page.evaluate('favoritesFixture.requests'))
            page.evaluate('favoritesFixture.requests = []')

        def open_account(actor='alice', verified=True):
            audit()
            page.evaluate('''([actor, verified]) => {
                sessionStorage.clear();
                if (actor) {
                    const email = actor + '@example.invalid';
                    sessionStorage.setItem('fixture-sdk-email', email);
                    sessionStorage.setItem('verified-' + email, String(verified));
                }
            }''', [actor, verified])
            page.goto(BASE + '/account')
            page.wait_for_function('globalThis.YGCCloudAccountReady === true')
            idle(account=True)

        def open_public(identifier=TARGET):
            audit()
            page.goto(BASE + ('/guitars/' + identifier if identifier else '/'))
            page.wait_for_function('globalThis.YGCCloudPublicCatalogReady === true')
            idle()

        def refresh_favorites():
            page.locator('#favoritesRefresh').click()
            idle(account=True)

        def refresh_visibility():
            page.locator('#visibilityRefresh').click()
            idle(account=True)

        def resume_account():
            page.evaluate('dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}))')
            idle(account=True)

        def sign_in_form(actor):
            expect(page.locator('#cloudAccountForm')).to_be_visible()
            page.locator('#email').fill(actor + '@example.invalid')
            page.locator('#password').fill('fixture-password')
            page.locator('#submit').click()
            idle(account=True)

        def change_visibility(field=FIELDS[0], value='Private'):
            page.locator('#visibilityEdit').click()
            expect(dialog).to_be_visible()
            page.locator('#visibility_' + field).select_option(value)

        def safe_content():
            assert page.evaluate('globalThis.fixtureXss !== true')
            assert not store['external'], store['external']
            assert SECRET not in page.locator('body').inner_text()

        page.goto(BASE + '/account')
        page.wait_for_function('globalThis.YGCCloudAccountReady === true')
        expect(page.locator('#selfFavorites')).to_be_hidden()
        expect(page.locator('#selfVisibility')).to_be_hidden()
        open_public()
        expect(page.locator('#favoriteAccount')).to_have_attribute('href', '/account#selfFavorites')
        expect(page.locator('#favoriteToggle')).to_be_hidden()
        assert not [call for call in store['calls'] if private(call['path'])]
        open_account(verified=False)
        expect(page.locator('#selfFavorites')).to_be_hidden()
        expect(page.locator('#selfVisibility')).to_be_hidden()
        open_public()
        expect(page.locator('#favoriteToggle')).to_be_hidden()
        assert not [call for call in store['calls'] if private(call['path'])]
        assert not store['writes']

        # Self-only, exact decimal cursor, plaintext allowlist and inert rows.
        open_account('other')
        expect(rows).to_have_count(0)
        expect(page.locator('#favoritesCount')).to_contain_text('0')
        open_account()
        expect(rows).to_have_count(25)
        expect(rows.first).to_have_attribute('data-favorite-id', BIG_ID)
        expect(rows.first).to_contain_text(ATTACK)
        expect(rows.first.locator('a')).to_have_attribute('href', '/guitars/' + BIG_ID)
        expect(page.locator('#favoritesCount')).to_contain_text('28')
        assert page.locator('#favoritesList img, #favoritesList script, #favoritesList button').count() == 0
        page.locator('#favoritesNext').click(); idle(account=True)
        expect(rows).to_have_count(3)
        expect(page.locator('#favoritesNext')).to_be_disabled()
        page.locator('#favoritesPrevious').click(); idle(account=True)
        expect(rows).to_have_count(25)
        expect(page.locator('#favoritesPrevious')).to_be_disabled()
        assert any(call['query'].get('after') == [favorite_ids[24]] for call in store['calls'])
        assert not store['writes']
        safe_content()

        # Opening and canceling a dialog never saves. Each field shows its exact
        # stored enum; null stays a required empty choice instead of a default.
        for value in CHOICES:
            expect(values).to_contain_text(value)
        for dismissal in ('cancel', 'escape', 'backdrop'):
            change_visibility()
            expect(page.locator('#visibilitySave')).to_be_enabled()
            assert not store['writes']
            if dismissal == 'cancel':
                page.locator('#visibilityCancel').click()
            elif dismissal == 'escape':
                page.keyboard.press('Escape')
            else:
                page.mouse.click(2, 2)
            expect(dialog).to_be_hidden()
            assert store['visibility']['alice']['fields'] == initial_fields and not store['writes']
        page.locator('#visibilityEdit').click()
        expect(page.locator('#visibilitySave')).to_be_disabled()
        for field, value in initial_fields.items():
            expect(page.locator('#visibility_' + field)).to_have_value(value)
        page.locator('#visibilityCancel').click()
        store['visibility']['alice']['fields'][FIELDS[0]] = None
        refresh_visibility()
        page.locator('#visibilityEdit').click()
        expect(page.locator('#visibility_' + FIELDS[0])).to_have_value('')
        expect(page.locator('#visibility_' + FIELDS[0])).to_have_attribute('required', '')
        expect(page.locator('#visibilitySave')).to_be_disabled()
        page.locator('#visibility_' + FIELDS[1]).select_option('Public')
        expect(page.locator('#visibilitySave')).to_be_disabled()
        page.locator('#visibility_' + FIELDS[0]).select_option('Private')
        expect(page.locator('#visibilitySave')).to_be_enabled()
        assert not store['writes']
        page.locator('#visibilitySave').evaluate('(button) => { button.click(); button.click(); }')
        idle(account=True)
        expect(dialog).to_be_hidden()
        assert len(store['writes']) == 1
        assert store['writes'][-1]['body'] == {'revision': REVISION, 'fields': {
            'birth_visibility': 'Private', 'residence_visibility': 'Public',
            'bio_visibility': 'Followers', 'avatar_visibility': 'Private'}}
        assert store['visibility']['alice']['profile_revision'] == str(int(REVISION) + 1)

        # A concurrent update cannot be overwritten with the old revision.
        change_visibility(value='Members')
        store['visibility']['alice']['profile_revision'] = str(int(REVISION) + 2)
        before = len(store['writes'])
        page.locator('#visibilitySave').click(); idle(account=True)
        expect(page.locator('#visibilityEdit')).to_be_disabled()
        expect(page.locator('#visibilityStatus')).not_to_have_text('')
        assert len(store['writes']) == before + 1
        assert store['visibility']['alice']['fields'][FIELDS[0]] == 'Private'
        refresh_visibility()
        assert len(store['writes']) == before + 1
        change_visibility(value='Members')
        page.locator('#visibilitySave').click(); idle(account=True)
        assert store['writes'][-1]['body']['revision'] == str(int(REVISION) + 2)
        assert store['visibility']['alice']['fields'][FIELDS[0]] == 'Members'

        # Lost replies, before and after commit, never retry or infer success.
        for drop in ('before', 'after'):
            desired = 'Public' if store['visibility']['alice']['fields'][FIELDS[0]] != 'Public' else 'Private'
            previous = store['visibility']['alice']['fields'][FIELDS[0]]
            change_visibility(value=desired)
            store['drop'] = drop; before = len(store['writes'])
            page.locator('#visibilitySave').click(); idle(account=True)
            expect(page.locator('#visibilityEdit')).to_be_disabled()
            expect(page.locator('#visibilityStatus')).not_to_have_text('')
            assert len(store['writes']) == before + 1
            assert store['visibility']['alice']['fields'][FIELDS[0]] == (desired if drop == 'after' else previous)
            refresh_visibility()
            expect(page.locator('#visibilityEdit')).to_be_enabled()
            assert len(store['writes']) == before + 1
        safe_content()

        # A saved response arriving after Back/Forward invalidation cannot
        # restore either private panel or reopen the dismissed editor.
        desired = 'Private' if store['visibility']['alice']['fields'][FIELDS[0]] != 'Private' else 'Members'
        change_visibility(value=desired)
        page.evaluate('path => catalogFixture.hold(path, "", "visibilityWriteLate")', VISIBILITY)
        before = len(store['writes'])
        page.locator('#visibilitySave').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.visibilityWriteLate)')
        assert store['visibility']['alice']['fields'][FIELDS[0]] == desired
        page.evaluate('dispatchEvent(new Event("popstate"))')
        expect(values).to_be_empty()
        expect(dialog).to_be_hidden()
        page.evaluate('catalogFixture.release("visibilityWriteLate")'); idle(account=True)
        expect(values).to_be_empty()
        expect(rows).to_have_count(0)
        assert len(store['writes']) == before + 1
        refresh_favorites(); refresh_visibility()

        # Private reads clear retained data on malformed DTOs and access errors.
        for malformed in ('favorite-id', 'favorite-private'):
            store['malformed'] = malformed; refresh_favorites()
            expect(rows).to_have_count(0)
            expect(page.locator('#favoritesCount')).to_be_empty()
            store['malformed'] = None; refresh_favorites()
        for malformed in ('visibility-revision', 'visibility-private'):
            store['malformed'] = malformed; refresh_visibility()
            expect(values).to_be_empty()
            expect(page.locator('#visibilityEdit')).to_be_disabled()
            store['malformed'] = None; refresh_visibility()
        for status in (401, 403, 503):
            store['read_error'] = status
            refresh_favorites(); refresh_visibility()
            expect(rows).to_have_count(0)
            expect(values).to_be_empty()
            safe_content()
            store['read_error'] = None
            refresh_favorites(); refresh_visibility()

        # An already-received success released after navigation cannot repopulate
        # private account panels. Browser Back/Forward performs no writes either.
        for event in ('popstate', 'pagehide'):
            for path, refresh_id in ((FAVORITES, 'favoritesRefresh'), (VISIBILITY, 'visibilityRefresh')):
                page.evaluate('path => catalogFixture.hold(path, "", "late")', path)
                page.locator('#' + refresh_id).click()
                page.wait_for_function('Boolean(catalogFixture.waiting.late)')
                page.evaluate('event => dispatchEvent(new Event(event))', event)
                expect(rows).to_have_count(0)
                expect(values).to_be_empty()
                expect(dialog).to_be_hidden()
                page.evaluate('catalogFixture.release("late")'); idle(account=True)
                expect(rows).to_have_count(0)
                expect(values).to_be_empty()
                if event == 'pagehide':
                    expect(page.locator('#selfFavorites')).to_be_hidden()
                    expect(page.locator('#selfVisibility')).to_be_hidden()
                    resume_account()
                    expect(rows).to_have_count(25)
                else:
                    refresh_favorites(); refresh_visibility()

        # BFCache restoration must revalidate canonical identity before private
        # reads. A second pagehide invalidates a completed-but-held /me response,
        # so that late restore cannot reopen panels or start private requests.
        page.evaluate('dispatchEvent(new Event("pagehide"))')
        before = len(store['calls'])
        page.evaluate('catalogFixture.hold("/api/auth/me", "", "restoreLate")')
        page.evaluate('dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}))')
        page.wait_for_function('Boolean(catalogFixture.waiting.restoreLate)')
        expect(page.locator('#accountSummary')).to_be_hidden()
        expect(page.locator('#selfFavorites')).to_be_hidden()
        expect(page.locator('#selfVisibility')).to_be_hidden()
        expect(rows).to_have_count(0)
        expect(values).to_be_empty()
        assert not [call for call in store['calls'][before:] if private(call['path'])]
        page.evaluate('dispatchEvent(new Event("pagehide"))')
        page.evaluate('catalogFixture.release("restoreLate")')
        page.wait_for_function('catalogFixture.pending === 0')
        expect(page.locator('#accountSummary')).to_be_hidden()
        expect(page.locator('#selfFavorites')).to_be_hidden()
        expect(page.locator('#selfVisibility')).to_be_hidden()
        assert not [call for call in store['calls'][before:] if private(call['path'])]
        resume_account()
        expect(rows).to_have_count(25)
        expect(values.locator('dd')).to_have_count(4)

        before = len(store['writes'])
        page.evaluate("history.pushState({}, '', '/account?fixture=navigation')")
        page.go_back(); idle(account=True)
        expect(rows).to_have_count(0)
        expect(values).to_be_empty()
        page.go_forward(); idle(account=True)
        expect(rows).to_have_count(0)
        expect(values).to_be_empty()
        assert len(store['writes']) == before
        refresh_favorites(); refresh_visibility()

        # The SDK identity event clears both projections immediately, even when
        # an already-delivered read is pending and the account shell is busy.
        for path, refresh_id in ((FAVORITES, 'favoritesRefresh'), (VISIBILITY, 'visibilityRefresh')):
            open_account()
            page.evaluate('path => catalogFixture.hold(path, "", "accountLate")', path)
            page.locator('#' + refresh_id).click()
            page.wait_for_function('Boolean(catalogFixture.waiting.accountLate)')
            page.evaluate("favoritesFixtureSwitchUser('other@example.invalid')")
            expect(rows).to_have_count(0)
            expect(values).to_be_empty()
            expect(page.locator('#selfFavorites')).to_be_hidden()
            expect(page.locator('#selfVisibility')).to_be_hidden()
            page.evaluate('catalogFixture.release("accountLate")'); idle(account=True)
            expect(rows).to_have_count(0)
            expect(values).to_be_empty()
            expect(page.locator('#refreshVerification')).to_be_hidden()
            sign_in_form('other')
            expect(rows).to_have_count(0)
            expect(page.locator('#favoritesCount')).to_contain_text('0')
            assert values.locator('dd').all_text_contents() == ['Private'] * 4

        open_account()
        change_visibility(value='Followers')
        before = len(store['writes'])
        page.evaluate("favoritesFixtureSwitchUser('other@example.invalid')")
        expect(dialog).to_be_hidden()
        expect(values).to_be_empty()
        page.locator('#visibilityForm').evaluate('(form) => form.dispatchEvent(new Event("submit", {cancelable: true}))')
        assert len(store['writes']) == before

        # SignOut erases both panels on the click, before the synthetic SDK
        # finishes its asynchronous call. The dialog remains mobile-safe.
        open_account()
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(rows.first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        change_visibility(value='Followers')
        expect(dialog).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#visibilityCancel').click()
        page.evaluate('favoritesFixture.holdLogout = true')
        page.locator('#signOut').click()
        page.wait_for_function('favoritesFixture.waitingLogout === true')
        expect(rows).to_have_count(0)
        expect(values).to_be_empty()
        expect(dialog).to_be_hidden()
        page.evaluate('favoritesFixture.releaseLogout()')
        expect(page.locator('#selfFavorites')).to_be_hidden()
        expect(page.locator('#selfVisibility')).to_be_hidden()
        page.wait_for_function('catalogFixture.pending === 0')

        # The public detail action reads only this canonical self's state. A list
        # or detail visit never creates a favorite, and double clicks write once.
        open_account()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        open_public(None)
        before = len(store['writes'])
        page.evaluate('path => catalogFixture.hold(path, "", "independentFavorite")', FAVORITES + '/' + TARGET)
        page.locator('#catalogRows a[href^="/guitars/' + TARGET + '"]').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.independentFavorite)')
        expect(page.locator('#detailContent')).to_be_visible()
        expect(page.locator('#catalogDetail')).to_have_attribute('aria-busy', 'false')
        expect(page.locator('#catalogRefresh')).to_be_enabled()
        expect(page.locator('#catalogNext')).to_be_enabled()
        page.locator('#catalogNext').click()
        expect(page.locator('#catalogRows .guitar-card')).to_have_count(5)
        expect(page.locator('#detailContent')).to_be_hidden()
        page.evaluate('catalogFixture.release("independentFavorite")'); idle()
        assert parse_qs(urlsplit(page.url).query).get('page') == ['2']
        assert len(store['writes']) == before
        open_public()
        toggle = page.locator('#favoriteToggle')
        expect(toggle).to_be_visible()
        expect(toggle).to_contain_text('Add')
        before = len(store['writes'])
        toggle.evaluate('(button) => { button.click(); button.click(); }'); idle()
        assert len(store['writes']) == before + 1 and TARGET in store['favorites']['alice']
        assert store['writes'][-1]['body'] == {'favorite': True}
        expect(toggle).to_contain_text('Remove')
        toggle.click(); idle()
        assert TARGET not in store['favorites']['alice']
        assert store['writes'][-1]['path'] == FAVORITES + '/' + TARGET
        assert store['writes'][-1]['body'] == {'favorite': False}
        expect(toggle).to_contain_text('Add')
        # Removing a stale visible favorite is deliberately idempotent.
        store['favorites']['alice'].add(TARGET)
        page.locator('#favoriteRefresh').click(); idle()
        expect(toggle).to_contain_text('Remove')
        store['favorites']['alice'].discard(TARGET)
        before = len(store['writes'])
        toggle.click(); idle()
        assert len(store['writes']) == before + 1 and TARGET not in store['favorites']['alice']
        assert store['writes'][-1]['body'] == {'favorite': False}
        expect(toggle).to_contain_text('Add')
        for drop in ('before', 'after'):
            store['favorites']['alice'].discard(TARGET)
            page.locator('#favoriteRefresh').click(); idle()
            before = len(store['writes']); store['drop'] = drop
            toggle.click(); idle()
            expect(toggle).to_be_disabled()
            expect(page.locator('#favoriteStatus')).not_to_have_text('')
            assert len(store['writes']) == before + 1
            assert (TARGET in store['favorites']['alice']) == (drop == 'after')
            page.locator('#favoriteRefresh').click(); idle()
            expect(toggle).to_be_enabled()
            expect(toggle).to_contain_text('Remove' if drop == 'after' else 'Add')
            assert len(store['writes']) == before + 1
        store['reject'] = 409; before = len(store['writes'])
        toggle.click(); idle()
        expect(toggle).to_be_disabled()
        expect(page.locator('#favoriteStatus')).not_to_have_text('')
        assert len(store['writes']) == before + 1
        page.locator('#favoriteRefresh').click(); idle()
        store['malformed'] = 'favorite-state'
        page.locator('#favoriteRefresh').click(); idle()
        expect(toggle).to_be_disabled()
        store['malformed'] = None
        page.locator('#favoriteRefresh').click(); idle()
        safe_content()

        # Holding a completed state read proves route epochs, independently of
        # abort: navigating to another guitar cannot adopt the previous state.
        page.set_viewport_size({'width': 390, 'height': 844})
        before = len(store['writes'])
        page.evaluate('path => catalogFixture.hold(path, "", "favoriteLate")', FAVORITES + '/' + TARGET)
        page.locator('#favoriteRefresh').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.favoriteLate)')
        page.locator('#catalogBack').click()
        expect(page.locator('#detailContent')).to_be_hidden()
        page.locator('#catalogRows a[href^="/guitars/' + BIG_ID + '"]').click()
        expect(page.locator('#detailTitle')).to_contain_text('Big integer guitar')
        page.evaluate('catalogFixture.release("favoriteLate")'); idle()
        assert urlsplit(page.url).path == '/guitars/' + BIG_ID
        expect(page.locator('#favoriteToggle')).to_contain_text('Remove')
        assert len(store['writes']) == before
        page.go_back(); idle()
        expect(page.locator('#detailContent')).to_be_hidden()
        page.go_forward(); idle()
        expect(page.locator('#detailTitle')).to_contain_text('Big integer guitar')
        expect(page.locator('#favoriteToggle')).to_contain_text('Remove')
        assert len(store['writes']) == before
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        # A completed PUT released after navigation updates only its target on
        # the server, never the newly selected guitar's own-state control.
        page.set_viewport_size({'width': 1440, 'height': 1000})
        open_public()
        store['favorites']['alice'].discard(TARGET)
        page.locator('#favoriteRefresh').click(); idle()
        page.evaluate('path => catalogFixture.hold(path, "", "writeLate")', FAVORITES + '/' + TARGET)
        before = len(store['writes'])
        page.locator('#favoriteToggle').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.writeLate)')
        assert TARGET in store['favorites']['alice'] and len(store['writes']) == before + 1
        page.locator('#catalogBack').click()
        page.locator('#catalogRows a[href^="/guitars/' + BIG_ID + '"]').click()
        expect(page.locator('#detailTitle')).to_contain_text('Big integer guitar')
        page.evaluate('catalogFixture.release("writeLate")'); idle()
        expect(page.locator('#favoriteToggle')).to_contain_text('Remove')
        assert BIG_ID in store['favorites']['alice'] and len(store['writes']) == before + 1

        # Pagehide clears even an already-received response; a subsequent
        # Refresh revalidates access. An SDK account switch does the same.
        for event in ('pagehide', 'identity'):
            page.evaluate('path => catalogFixture.hold(path, "", "publicLate")', FAVORITES + '/' + BIG_ID)
            page.locator('#favoriteRefresh').click()
            page.wait_for_function('Boolean(catalogFixture.waiting.publicLate)')
            if event == 'pagehide':
                page.evaluate('dispatchEvent(new Event("pagehide"))')
            else:
                page.evaluate("favoritesFixtureSwitchUser('other@example.invalid')")
            expect(page.locator('#detailFavorite')).to_be_hidden()
            page.evaluate('catalogFixture.release("publicLate")'); idle()
            expect(page.locator('#detailFavorite')).to_be_hidden()
            if event == 'pagehide':
                page.evaluate('dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}))')
            else:
                page.locator('#catalogRefresh').click()
            idle()
            expect(page.locator('#favoriteToggle')).to_contain_text('Add' if event == 'identity' else 'Remove')
        assert len(store['writes']) == before + 1
        safe_content()
        audit()
        assert not errors, errors
        assert not store['external'], store['external']
        assert all(call['method'] == 'GET' or private(call['path']) and call['method'] == 'PUT'
                   for call in store['calls'])
        assert all(call['actor'] == 'alice' for call in store['writes'])
        assert audits and all(request['credentials'] == 'omit' and request['cache'] == 'no-store'
            and request['redirect'] == 'error'
            and request['authorization'].startswith('Bearer fixture-verified-') for request in audits)
        page.unroute_all(behavior='wait')
    print('Cloud Favorites/visibility browser: private exact-ID paging, guest/unverified gates, plaintext '
          'allowlist, explicit duplicate-safe toggle and Save, nulls/cancel/conflict, unknown outcomes, '
          'malformed/access errors, stale navigation, account isolation, immediate SignOut and mobile passed.')


if __name__ == '__main__':
    main()
