"""Real Chromium Identity Correction journeys with intercepted synthetic data.

Production account HTML, CSS, modules and authentication adapter are exercised.
This fixture opens no real account/database/cloud/photo source. Compile anywhere;
run only in the authorized Mac/CI browser runner. Network mocks assert the wire
contract, while the separate PostgreSQL suite verifies authorization and storage.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
from browser_cloud_account import SDK
from browser_cloud_public_catalog import HOLD_SCRIPT
from browser_diagnostics import diagnostic_page
from ygc.cloud_registration import DOCUMENTS
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-identity-correction-fixture.invalid'
API = '/api/auth/identity-corrections'
LISTING = '9007199254741021'
GUITAR = '9007199254741009'
DETAIL = API + '/' + LISTING
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'
PRIVATE = 'Private correction reason ' + ATTACK
FIELDS = ('manufacturer', 'model', 'year', 'serial_number')
AUDIT = r'''
(() => {
 const original=globalThis.fetch.bind(globalThis);
 const requests=globalThis.identityRequests=[];
 const post=globalThis.identityPostFixture={hold:false,waiting:false,release:null};
 globalThis.fetch=async(input,options={})=>{
   const url=new URL(typeof input==='string'?input:input.url,location.href);
   if(url.pathname.startsWith('/api/auth/identity-corrections'))requests.push({path:url.pathname,
     method:options.method||'GET',credentials:options.credentials,cache:options.cache,
     redirect:options.redirect,authorization:new Headers(options.headers).get('authorization')});
   let response=await original(input,options);
   if(post.hold&&options.method==='POST'&&url.pathname.startsWith('/api/auth/identity-corrections/')){
     post.hold=false;const body=await response.arrayBuffer();
     response=new Response(body,{status:response.status,headers:response.headers});
     post.waiting=true;await new Promise(resolve=>{post.release=()=>{post.waiting=false;resolve()}});
   }
   return response;
 };
})();
'''


def main():
    names = ('cloud-account-disputes.js', 'cloud-account-page.js', 'cloud-account-notifications.js', 'cloud-account-identity.js', 'cloud-account-ownership.js',
        'cloud-account-profile.js', 'cloud-account-avatar.js', 'cloud-account-guitars.js',
        'cloud-account-applications.js', 'cloud-account-claims.js', 'cloud-account-media.js',
        'cloud-account.css', 'cloud-auth-loader.js', 'identity-platform-auth.js',
        'overlays.js', 'ui-components.css')
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    guitar = dict(id=GUITAR, manufacturer='Fixture maker', model='Original identity',
                  year='1965', serial_number='ORIGINAL-001')
    store = dict(rows=[], revision=1, can_write=True, mode='normal', author_available=True,
                 calls=[], writes=[], external=[], drop=None, malformed=False, history_size=25)
    users = {name: dict(id=str(index), app_user_id='fixture-' + name, display_name=name.title(),
                       account_type='user', role='member', status='active')
             for index, name in enumerate(('author', 'owner', 'other'), 1)}
    errors = []

    def revision():
        return format(store['revision'], '064x')

    def detail(query=None):
        query = query or {}
        after = int(query.get('after', ['0'])[0])
        rows = [row for row in reversed(store['rows']) if not after or int(row['id']) < after]
        selected = deepcopy(rows[:store['history_size']])
        return dict(listing=dict(id=LISTING, individual_id=GUITAR, occurred_at='2026-01-01'),
                    individual=deepcopy(guitar), items=selected, revision=revision(), can_write=store['can_write'],
                    next_after=selected[-1]['id'] if len(rows) > len(selected) else None)

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_identity_correction') as page:
        page.add_init_script(HOLD_SCRIPT + AUDIT)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            path, method = parsed.path, request.method
            if parsed.netloc == 'www.gstatic.com' and path.startswith('/firebasejs/'):
                route.fulfill(content_type='text/javascript', body='export const initializeApp=config=>config;'
                              if path.endswith('/firebase-app.js') else SDK)
                return
            if parsed.scheme + '://' + parsed.netloc != BASE:
                store['external'].append(request.url)
                route.abort()
                return
            if path.startswith('/assets/') and path[len('/assets/'):] in assets:
                name = path[len('/assets/'):]
                route.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=assets[name])
                return
            if path == '/account':
                route.fulfill(content_type='text/html', body=html)
                return
            if path == '/favicon.ico':
                route.fulfill(status=204)
                return
            token = request.headers.get('authorization', '')
            actor = token.replace('Bearer fixture-verified-', '').replace('Bearer fixture-', '').split('@')[0]
            query = parse_qs(parsed.query)
            payload = request.post_data_json if method == 'POST' else None
            store['calls'].append(dict(path=path, method=method, actor=actor, query=query, body=payload))
            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture', 'authDomain': 'fixture.firebaseapp.com', 'projectId': 'fixture'}, 'tenant': ''})
            elif path == '/api/auth/registration':
                route.fulfill(json={'documents': DOCUMENTS})
            elif path == '/api/service/status':
                route.fulfill(json={'mode': store['mode'], 'message': ''})
            elif path == '/api/auth/me' and actor in users:
                route.fulfill(json={'user': users[actor], 'identity': {'email_verified': 'fixture-verified-' in token}})
            elif actor not in users or 'fixture-verified-' not in token:
                route.fulfill(status=403, json={'detail': 'Synthetic verified identity required'})
            elif path == '/api/auth/profile':
                route.fulfill(json={'profile_revision': '1', 'fields': {'display_name': users[actor]['display_name'], 'location_country': '', 'location_region': '', 'bio': ''}})
            elif path == '/api/auth/avatar':
                route.fulfill(status=404, json={'detail': 'No fixture avatar'})
            elif path == '/api/auth/applications':
                route.fulfill(json={'items': [], 'can_write': store['can_write']})
            elif path == '/api/auth/guitars':
                # Author has no Owned/Formerly Owned guitar. The independent
                # Listing entrance must still be present; Owner has no Listing.
                included = actor == 'owner' and query.get('kind') == ['owned']
                route.fulfill(json={'items': [guitar] if included else [], 'total': '1' if included else '0', 'next_after': None})
            elif path in ('/api/auth/ownership-disputes', '/api/auth/ownership-disputes/options'):
                route.fulfill(json={'items': [], 'next_after': None, 'can_write': True, 'viewer_user_id': '1'})
            elif path == '/api/auth/notifications':
                route.fulfill(json={'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True})
            elif path == '/api/auth/ownership-transfers':
                route.fulfill(json={'viewer_user_id': users[actor]['id'], 'items': [], 'can_write': store['can_write'], 'next_after': None})
            elif path == API and method == 'GET':
                if store['mode'] in ('offline', 'admin_only'):
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                rows = [dict(id=LISTING, individual=deepcopy(guitar), occurred_at='2026-01-01')] if actor == 'author' and store['author_available'] else []
                route.fulfill(json={'items': rows, 'next_after': None, 'can_write': store['can_write']})
            elif path == DETAIL:
                if actor != 'author' or not store['author_available']:
                    route.fulfill(status=404, json={'detail': 'Own active Listing unavailable'})
                    return
                if store['mode'] in ('offline', 'admin_only') or method == 'POST' and not store['can_write']:
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if method == 'GET':
                    assert set(query) <= {'after', 'limit'}
                    route.fulfill(json=detail(query))
                    return
                assert method == 'POST' and isinstance(payload, dict)
                assert request.headers.get('sec-fetch-site') != 'cross-site'
                assert set(payload) == {'revision', *FIELDS, 'reason'}
                assert re.fullmatch('[0-9a-f]{64}', payload['revision'])
                assert payload['revision'] == revision(), 'UI must perform a current-revision preview and preflight'
                store['writes'].append(deepcopy(payload))
                drop, store['drop'] = store['drop'], None
                if drop == 'before':
                    route.abort('failed')
                    return
                changes = [dict(field_name=key, old_value=guitar[key], new_value=payload[key]) for key in FIELDS if guitar[key] != payload[key]]
                assert changes
                for key in FIELDS:
                    guitar[key] = payload[key]
                store['revision'] += 1
                row = dict(id=str(9007199254742000 + len(store['rows'])), target_claim_id=LISTING, individual_id=GUITAR,
                    body=payload['reason'], occurred_at='2026-01-01', created_at='2026-10-07T00:00:00Z',
                    status='active', verification_status='positive', changes=changes)
                store['rows'].append(row)
                result = {'correction': deepcopy(row), 'detail': detail()}
                if store['malformed']:
                    store['malformed'] = False
                    result['correction']['changes'][0]['old_value'] = 'A different unreviewed identity'
                if drop == 'after':
                    route.abort('failed')
                else:
                    route.fulfill(json=result)
            else:
                raise AssertionError('Unexpected identity browser request: ' + method + ' ' + path)

        page.route('**/*', respond)
        dialog, listings = page.locator('#identityDialog'), page.locator('#identityListings')
        def settle():
            page.wait_for_function('catalogFixture.pending===0')
            expect(page.locator('#signOut')).to_be_enabled()

        def sign_in(actor='author', verified=True):
            page.evaluate("""([actor,verified])=>{
                sessionStorage.clear();const email=actor+'@example.invalid';
                sessionStorage.setItem('fixture-sdk-email',email);
                sessionStorage.setItem('verified-'+email,String(verified));
            }""", [actor, verified])
            page.goto(BASE + '/account')
            page.wait_for_function('globalThis.YGCCloudAccountReady===true')
            settle()

        def open_listing():
            listings.get_by_role('button', name='Edit Listing', exact=True).click()
            expect(dialog).to_be_visible()
            settle()

        def close():
            page.locator('#identityClose').click()
            expect(dialog).to_be_hidden()

        def compose(model, reason=PRIVATE):
            open_listing()
            expect(page.locator('#identityForm')).to_be_hidden()
            page.locator('#identityCreate').click()
            expect(page.locator('#identity_model')).to_have_value(guitar['model'] or '')
            page.locator('#identity_model').fill(model)
            page.locator('#identityReason').fill(reason)
            page.locator('#identityReview').click()
            expect(page.locator('#identityConfirm')).to_be_visible()
            settle()

        def recover():
            expect(page.locator('#identityCreate')).to_be_disabled()
            page.locator('#identityCheckSubmission').click()
            expect(page.locator('#identityAcknowledge')).to_be_visible()
            settle()
            page.locator('#identityAcknowledge').click()
            expect(page.locator('#identityCreate')).to_be_enabled()
            expect(page.locator('#identityConfirm')).to_be_hidden()
            expect(page.locator('#identityReason')).to_have_value('')

        page.goto(BASE + '/account')
        page.wait_for_function('globalThis.YGCCloudAccountReady===true')
        expect(page.locator('#selfIdentityCorrections')).to_be_hidden()
        sign_in(verified=False)
        expect(page.locator('#selfIdentityCorrections')).to_be_hidden()
        assert not store['writes']
        sign_in('owner')
        expect(listings.locator('li')).to_have_count(0)
        expect(page.locator('#selfGuitars_owned li')).to_have_count(1)
        sign_in()
        expect(listings.locator('li')).to_have_count(1)
        expect(page.locator('#selfGuitars_owned li')).to_have_count(0)
        assert not store['writes']
        open_listing()
        expect(page.locator('#identityImmutable')).to_be_visible()
        expect(page.locator('#identityImmediate')).to_be_visible()
        expect(page.locator('#identityListingDate')).to_contain_text('2026-01-01')
        expect(page.locator('#identityForm')).to_be_hidden()
        assert not store['writes']
        close()

        # Explicit old/new preview; dismissal never performs a write or changes
        # browser history, and unsafe user text is rendered as text only.
        history_length = page.evaluate('history.length')
        for dismissal in ('close', 'escape', 'backdrop'):
            compose('Draft ' + ATTACK)
            expect(page.locator('#identityPreview')).to_contain_text('Original identity')
            expect(page.locator('#identityPreview')).to_contain_text('Draft ' + ATTACK)
            assert page.locator('#identityPreview img').count() == 0
            if dismissal == 'close':
                close()
            elif dismissal == 'escape':
                page.keyboard.press('Escape')
            else:
                page.mouse.click(2, 2)
            expect(dialog).to_be_hidden()
            expect(page.locator('#identityReason')).to_have_value('')
            assert page.evaluate('history.length') == history_length and not store['writes']

        # Late detail response after close/popstate cannot restore private data.
        for dismiss in ('close', 'popstate'):
            page.evaluate('path=>catalogFixture.hold(path,"","late")', DETAIL)
            listings.get_by_role('button', name='Edit Listing', exact=True).click()
            page.wait_for_function('Boolean(catalogFixture.waiting.late)')
            if dismiss == 'close':
                close()
            else:
                page.evaluate("history.pushState({},'', '/account?fixture=back');dispatchEvent(new PopStateEvent('popstate'))")
            page.evaluate('catalogFixture.release("late")')
            settle()
            expect(dialog).to_be_hidden()
            expect(page.locator('#identityGuitar')).to_be_empty()
            expect(page.locator('#identityHistory li')).to_have_count(0)
        assert not store['writes']

        # Actual same-document browser Back/Forward closes an active editor
        # and never resurrects the draft or submits it on traversal.
        page.evaluate("history.pushState({},'', '/account?fixture=navigation')")
        open_listing()
        page.locator('#identityCreate').click()
        page.locator('#identityReason').fill('Unsent navigation draft')
        page.go_back()
        expect(dialog).to_be_hidden()
        page.go_forward()
        expect(dialog).to_be_hidden()
        expect(page.locator('#identityReason')).to_have_value('')
        assert not store['writes']

        compose('First corrected ' + ATTACK)
        submitted_revision = revision()
        page.locator('#identityConfirm').evaluate('(button)=>{button.click();button.click()}')
        expect(page.locator('#identityMessage')).to_contain_text('Positive Identity Correction created')
        settle()
        assert len(store['writes']) == 1 and store['writes'][0]['revision'] == submitted_revision
        expect(page.locator('#identityHistory')).to_contain_text(PRIVATE)
        expect(page.locator('#identityHistory')).to_contain_text('Positive')
        expect(listings).to_contain_text('First corrected ' + ATTACK)
        assert page.locator('#identityDialog img, #identityListings img').count() == 0
        assert page.evaluate('Boolean(globalThis.fixtureXss)') is False
        close()

        # Changing a proposal invalidates its preview. A current identity
        # change after review is caught before sending a stale POST.
        compose('Unsent changed proposal')
        page.locator('#identity_model').fill('Another unsent draft')
        expect(page.locator('#identityConfirm')).to_be_hidden()
        page.locator('#identityReview').click()
        expect(page.locator('#identityConfirm')).to_be_visible()
        guitar['year'] = '1970'; store['revision'] += 1
        page.locator('#identityConfirm').click()
        settle()
        expect(page.locator('#identityConfirm')).to_be_hidden()
        assert len(store['writes']) == 1
        close()

        # Outcome unknown both before and after commit requires a fresh GET and
        # explicit acknowledgement; close, back/forward and reload cannot retry.
        for drop in ('before', 'after'):
            compose('Unknown ' + drop)
            store['drop'] = drop
            count, committed = len(store['writes']), len(store['rows'])
            page.locator('#identityConfirm').click()
            expect(page.locator('#identityCheckSubmission')).to_be_visible()
            settle()
            assert len(store['writes']) == count + 1
            assert len(store['rows']) == committed + (drop == 'after')
            marker = page.evaluate("sessionStorage.getItem('ygc.identity-correction.uncertain.v1')")
            assert marker and PRIVATE not in marker and 'Unknown' not in marker
            close()
            page.reload()
            page.wait_for_function('globalThis.YGCCloudAccountReady===true')
            settle(); open_listing()
            expect(page.locator('#identityConfirm')).to_be_hidden()
            recover()
            assert len(store['writes']) == count + 1
            if drop == 'after':
                expect(page.locator('#identityHistory')).to_contain_text('Unknown after')
            close()

        # A syntactically valid but mismatched success response is also unknown.
        compose('Malformed committed response'); store['malformed'] = True
        page.locator('#identityConfirm').click()
        expect(page.locator('#identityCheckSubmission')).to_be_visible()
        settle()
        count = len(store['writes'])
        recover()
        expect(page.locator('#identityHistory')).to_contain_text('Malformed committed response')
        assert len(store['writes']) == count
        close()

        # Private history can page independently without changing revision or
        # author. Read-only allows it but disables creation and confirmation.
        store['history_size'] = 1
        open_listing()
        expect(page.locator('#identityHistory li')).to_have_count(1)
        page.locator('#identityHistoryMore').click()
        expect(page.locator('#identityHistory li')).to_have_count(2)
        settle(); close()
        store['history_size'] = 25; store['can_write'] = False
        page.locator('#identityRefresh').click(); settle(); open_listing()
        expect(page.locator('#identityCreate')).to_be_disabled()
        expect(page.locator('#identityHistory')).to_contain_text('Malformed committed response')
        close()
        assert len(store['writes']) == count
        store['can_write'] = True
        page.locator('#identityRefresh').click(); settle()

        # Closing during the preflight GET prevents the write entirely.
        compose('Closed after successful commit')
        page.evaluate('path=>catalogFixture.hold(path,"","accepted")', DETAIL)
        page.locator('#identityConfirm').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.accepted)')
        close()
        page.evaluate('catalogFixture.release("accepted")')
        settle()
        expect(dialog).to_be_hidden()
        assert len(store['writes']) == count

        # A genuinely accepted POST response held after commit must not reopen
        # a closed dialog. Account history refresh still reflects the saved data.
        compose('Accepted while closed')
        page.evaluate('identityPostFixture.hold=true')
        page.locator('#identityConfirm').click()
        page.wait_for_function('identityPostFixture.waiting===true')
        assert len(store['writes']) == count + 1 and guitar['model'] == 'Accepted while closed'
        close()
        page.evaluate('identityPostFixture.release()')
        settle()
        expect(dialog).to_be_hidden()
        expect(listings).to_contain_text('Accepted while closed')
        expect(page.locator('#identityHistory li')).to_have_count(0)
        count += 1

        # Author permission loss and Offline erase retained private content.
        open_listing(); store['author_available'] = False
        page.locator('#identityReload').click(); settle()
        expect(dialog).to_be_hidden()
        expect(listings.locator('li')).to_have_count(0)
        expect(page.locator('#identityHistory li')).to_have_count(0)
        store['author_available'] = True
        page.locator('#identityRefresh').click(); settle(); open_listing()
        store['mode'] = 'offline'
        page.locator('#identityReload').click(); settle()
        expect(dialog).to_be_hidden()
        expect(page.locator('#identityHistory li')).to_have_count(0)
        store['mode'] = 'normal'
        page.locator('#identityRefresh').click(); settle(); open_listing()
        close(); page.locator('#signOut').click()
        expect(page.locator('#selfIdentityCorrections')).to_be_hidden()
        expect(listings.locator('li')).to_have_count(0)
        expect(page.locator('#identityHistory li')).to_have_count(0)
        assert not store['external'] and not errors, (store['external'], errors)
        assert all(request['credentials'] == 'omit' and request['cache'] == 'no-store' and
                   request['redirect'] == 'error' and request['authorization'].startswith('Bearer fixture-verified-')
                   for request in page.evaluate('identityRequests'))
        assert all(call['path'] == DETAIL for call in store['calls'] if call['method'] == 'POST')
        page.wait_for_function('catalogFixture.pending===0')
        page.unroute_all(behavior='wait')
    print('Cloud Identity Correction browser: author-only independent entry, immutable Listing explanation, '
          'current old/new preview, exact revision/IDs, immediate private history, repeat/stale/unknown result, '
          'dismissal/navigation/reload, late responses, read-only/revocation/offline, XSS and SignOut passed.')


if __name__ == '__main__':
    main()
