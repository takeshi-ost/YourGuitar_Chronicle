"""Cloud Transfer/Release journeys against intercepted synthetic fixtures.

Production account/catalog assets and auth adapter are used. No real identity,
email, database or cloud service is accessed. Run with the authorized Chromium
aggregate runner; compilation alone is not a browser acceptance result.
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
BASE = 'http://ygc-ownership-fixture.invalid'
GUITAR = '9007199254741009'
ROOT = '/api/auth/guitars/' + GUITAR
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'


def main():
    names = ('cloud-account-page.js', 'cloud-account-notifications.js', 'cloud-account-identity.js', 'cloud-account-profile.js', 'cloud-account-avatar.js',
        'cloud-account-guitars.js', 'cloud-account-applications.js', 'cloud-account-claims.js',
        'cloud-account-media.js', 'cloud-account-ownership.js', 'cloud-account.css',
        'cloud-public-catalog.js', 'cloud-public-catalog.css', 'cloud-auth-loader.js',
        'identity-platform-auth.js', 'overlays.js', 'ui-components.css')
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    account_html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    public_html = (STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8')
    users = {name: dict(id=str(index), display_name=name.title() + ' ' + ATTACK,
                       account_type='user') for index, name in enumerate(('owner', 'buyer', 'other'), 1)}
    guitar = dict(id=GUITAR, manufacturer='Fixture maker', model='Ownership journey',
                  finish='Natural', year='1965', serial_number='TRANSFER-' + GUITAR, photo=None, specifications=[])
    store = dict(owner='owner', former=set(), items=[], revision=1, can_write=True,
                 restricted=False, writes=[], reads=[], external=[], drop=None, stale=False)
    errors = []

    def revision():
        return format(store['revision'], '064x')

    def bump():
        store['revision'] += 1
        return revision()

    def own_items(actor):
        return [detail(row, actor) if row['ownership_kind'] == 'transfer' else deepcopy(row)
                for row in reversed(store['items']) if (row.get('author') == actor or
                row.get('from_user', {}).get('id') == users[actor]['id'] or
                row.get('to_user', {}).get('id') == users[actor]['id'])]

    def detail(row, actor):
        data = deepcopy(row)
        pending = row['state'] == 'pending' and row['status'] == 'active'
        data.update(viewer_user_id=users[actor]['id'], can_write=store['can_write'], can_accept=pending and
            row['to_user']['id'] == users[actor]['id'] and
            row['from_user']['id'] == (users[store['owner']]['id'] if store['owner'] else None),
            can_decline=pending and row['to_user']['id'] == users[actor]['id'],
            can_cancel=pending and row['from_user']['id'] == users[actor]['id'])
        return data

    def ownership(actor):
        current = actor == store['owner']
        return dict(viewer_user_id=users[actor]['id'], individual=deepcopy(guitar), current_owner_user_id=users[store['owner']]['id'] if store['owner'] else None,
            is_current_owner=current, can_write=store['can_write'], can_transfer=current,
            can_release=current, revision=revision(), items=own_items(actor), next_after=None)

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_ownership') as page:
        page.add_init_script(HOLD_SCRIPT)
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
                route.fulfill(content_type='text/html', body=account_html)
                return
            if path == '/' or path.startswith('/guitars/'):
                route.fulfill(content_type='text/html', body=public_html)
                return
            if path == '/favicon.ico':
                route.fulfill(status=204)
                return
            token = request.headers.get('authorization', '')
            actor = token.replace('Bearer fixture-verified-', '').replace('Bearer fixture-', '').split('@')[0]
            query = parse_qs(parsed.query)
            payload = request.post_data_json if method == 'POST' else None
            store['reads' if method == 'GET' else 'writes'].append(dict(path=path, actor=actor, data=payload, query=query))
            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture', 'authDomain': 'fixture.firebaseapp.com', 'projectId': 'fixture'}, 'tenant': ''})
            elif path == '/api/auth/registration':
                route.fulfill(json={'documents': DOCUMENTS})
            elif path == '/api/service/status':
                route.fulfill(json={'mode': 'offline' if store['restricted'] else 'normal', 'message': ''})
            elif path.startswith('/api/public/guitars'):
                route.fulfill(json={'items': [], 'next_after': None} if path.endswith('/chronicle') else guitar)
            elif actor not in users or 'fixture-verified-' not in token:
                if path == '/api/auth/me' and actor in users:
                    route.fulfill(json={'user': dict(users[actor], app_user_id=actor, role='member', status='active'), 'identity': {'email_verified': False}})
                else:
                    route.fulfill(status=403, json={'detail': 'Fixture verified identity required'})
            elif path == '/api/auth/me':
                route.fulfill(json={'user': dict(users[actor], app_user_id=actor, role='member', status='active'), 'identity': {'email_verified': True}})
            elif path == '/api/auth/profile':
                route.fulfill(json={'profile_revision': '1', 'fields': {'display_name': users[actor]['display_name'], 'location_country': '', 'location_region': '', 'bio': ''}})
            elif path == '/api/auth/avatar':
                route.fulfill(status=404, json={'detail': 'No avatar'})
            elif path == '/api/auth/applications':
                route.fulfill(json={'items': [], 'can_write': store['can_write']})
            elif path == '/api/auth/guitars':
                kind = query.get('kind', [''])[0]
                included = actor == store['owner'] if kind == 'owned' else actor in store['former']
                route.fulfill(json={'items': [guitar] if included else [], 'total': '1' if included else '0', 'next_after': None})
            elif path.endswith('/owner-responses') or path.endswith('/claims'):
                route.fulfill(json={'items': [], 'can_write': store['can_write'], 'individual': guitar, 'next_after': None})
            elif store['restricted']:
                route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
            elif path == '/api/auth/notifications':
                route.fulfill(json={'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True})
            elif path == '/api/auth/identity-corrections':
                route.fulfill(json={'items': [], 'next_after': None, 'can_write': store['can_write']})
            elif path == '/api/auth/ownership-transfers':
                route.fulfill(json={'viewer_user_id': users[actor]['id'], 'items': [row for row in own_items(actor) if row['ownership_kind'] == 'transfer'], 'next_after': None, 'can_write': store['can_write']})
            elif path == ROOT + '/ownership':
                route.fulfill(json=ownership(actor))
            elif path == ROOT + '/transfer-users':
                assert actor == store['owner']
                term = query.get('q', [''])[0].strip().lower()
                rows = [value for key, value in users.items() if key != actor and term and (term in value['display_name'].lower() or term == value['id'])]
                route.fulfill(json={'items': rows, 'next_offset': None})
            elif re.fullmatch('/api/auth/transfers/[1-9][0-9]*', path):
                row = next(row for row in store['items'] if row['id'] == path.rsplit('/', 1)[-1])
                assert users[actor]['id'] in (row['from_user']['id'], row['to_user']['id'])
                route.fulfill(json=detail(row, actor))
            elif method == 'POST' and (path in (ROOT + '/transfers', ROOT + '/release') or path.endswith('/resolve')):
                assert request.headers.get('sec-fetch-site') != 'cross-site'
                assert isinstance(payload, dict) and re.fullmatch('[0-9a-f]{64}', payload['revision'])
                if not store['can_write']:
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if store['stale']:
                    store['stale'] = False
                    bump()
                    route.fulfill(status=409, json={'detail': 'Fixture revision changed'})
                    return
                drop, store['drop'] = store['drop'], None
                if drop == 'before':
                    route.abort('failed')
                    return
                if path == ROOT + '/transfers':
                    assert actor == store['owner'] and set(payload) == {'to_user_id', 'revision'}
                    assert payload['revision'] == revision()
                    row = dict(id=str(9007199254742000 + len(store['items'])), individual_id=GUITAR, individual=guitar,
                        ownership_kind='transfer', from_user=users[actor], to_user=next(value for value in users.values() if value['id'] == payload['to_user_id']),
                        state='pending', status='active', verification_status='unverified', created_at='2026-01-02T00:00:00Z',
                        resolved_at=None, occurred_at=None, acceptance=None, revision=bump())
                    store['items'].append(row)
                    result = {'transfer': detail(row, actor)}
                elif path == ROOT + '/release':
                    assert actor == store['owner'] and set(payload) == {'occurred_at', 'body', 'revision'}
                    assert payload['revision'] == revision()
                    row = dict(id=str(9007199254742000 + len(store['items'])), individual_id=GUITAR, ownership_kind='release',
                        author=actor, body=payload['body'], occurred_at=payload['occurred_at'], status='active', verification_status='positive', revision=bump())
                    store['items'].append(row)
                    store['former'].add(actor)
                    store['owner'] = None
                    result = {'claim': deepcopy(row), 'ownership': ownership(actor)}
                else:
                    row = next(row for row in store['items'] if row['id'] == path.split('/')[-2])
                    assert set(payload) == {'action', 'revision'} and row['revision'] == payload['revision']
                    action = payload['action']
                    assert users[actor]['id'] == row['from_user' if action == 'cancel' else 'to_user']['id']
                    assert row['state'] == 'pending'
                    row.update(state={'accept': 'accepted', 'decline': 'declined', 'cancel': 'cancelled'}[action],
                               resolved_at='2026-02-01T12:00:00Z', revision=bump())
                    if action == 'accept':
                        row.update(occurred_at=row['resolved_at'], verification_status='positive',
                            acceptance=dict(accepted_by_user_id=users[actor]['id'], accepted_at=row['resolved_at'], current_owner_user_id=users[store['owner']]['id']))
                        store['former'].add(store['owner'])
                        store['owner'] = actor
                    result = {'transfer': detail(row, actor)}
                if drop == 'after':
                    route.abort('failed')
                else:
                    route.fulfill(json=result)
            else:
                raise AssertionError('Unexpected synthetic ownership request: ' + method + ' ' + path)

        page.route('**/*', respond)
        dialog = page.locator('#ownershipDialog')
        inbox = page.locator('#ownershipInbox')
        owned = page.locator('#selfGuitars_owned')
        former = page.locator('#selfGuitars_formerly_owned')
        account_url = BASE + '/account?ownership=' + GUITAR

        def settle():
            page.wait_for_function('globalThis.catalogFixture.pending===0')
            expect(page.locator('#signOut')).to_be_enabled()

        def sign_in(actor, verified=True):
            page.evaluate("""([actor, verified]) => {
                sessionStorage.clear();
                const email=actor+'@example.invalid';
                sessionStorage.setItem('fixture-sdk-email', email);
                sessionStorage.setItem('verified-'+email, String(verified));
            }""", [actor, verified])
            page.goto(account_url)
            page.wait_for_function('globalThis.YGCCloudAccountReady===true')
            settle()

        def compose(target='buyer'):
            page.locator('#ownershipStart').click()
            expect(dialog).to_be_visible()
            page.locator('#ownershipSearch').fill(target)
            page.locator('#ownershipSearchButton').click()
            expect(page.locator('#ownershipCandidates li')).to_have_count(1)
            page.locator('#ownershipCandidates li button').click()
            page.locator('#ownershipReview').click()
            expect(page.locator('#ownershipConfirm')).to_be_visible()

        def close():
            page.locator('#ownershipClose').click()
            expect(dialog).to_be_hidden()

        def open_inbox(identifier=None):
            row = inbox.locator('li')
            if identifier:
                row = row.filter(has_text='#'+identifier+' ·')
            row.first.locator('button').click()
            expect(dialog).to_be_visible()
            settle()

        page.goto(BASE + '/guitars/' + GUITAR)
        page.wait_for_function('globalThis.YGCCloudPublicCatalogReady===true')
        expect(page.locator('#ownershipLink')).to_have_attribute('href', '/account?ownership=' + GUITAR)
        page.locator('#ownershipLink').click()
        page.wait_for_function('globalThis.YGCCloudAccountReady===true')
        expect(page.locator('#selfOwnership')).to_be_hidden()
        assert not store['writes']
        sign_in('owner', verified=False)
        expect(page.locator('#selfOwnership')).to_be_hidden()
        assert not store['writes']
        sign_in('owner')
        expect(owned.locator('li')).to_have_count(1)
        expect(page.locator('#ownershipStart')).to_be_enabled()
        assert not store['writes']

        # Dismissal must neither submit nor retain candidate/private text.
        original_history = page.evaluate('history.length')
        for dismissal in ('close', 'escape', 'backdrop'):
            compose()
            if dismissal == 'close':
                close()
            elif dismissal == 'escape':
                page.keyboard.press('Escape')
            else:
                page.mouse.click(2, 2)
            expect(dialog).to_be_hidden()
            expect(page.locator('#ownershipCandidates li')).to_have_count(0)
            assert page.evaluate('history.length') == original_history
            assert not store['writes']
        assert page.locator('#ownershipDialog img, #ownershipInbox img, #catalogOwnershipIntent img').count() == 0
        assert page.evaluate('Boolean(globalThis.fixtureXss)') is False

        # A held search response cannot repopulate a closed dialog.
        page.locator('#ownershipStart').click()
        page.locator('#ownershipSearch').fill('buyer')
        page.evaluate('path=>catalogFixture.hold(path,"buyer","search")', ROOT + '/transfer-users')
        page.locator('#ownershipSearchButton').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.search)')
        close()
        page.evaluate('catalogFixture.release("search")')
        settle()
        expect(page.locator('#ownershipCandidates li')).to_have_count(0)
        assert not store['writes']

        # A delayed Owned-list entry must not reopen after newer navigation.
        page.evaluate('path=>catalogFixture.hold(path,"","navigation")', ROOT + '/ownership')
        owned.get_by_role('button', name='Transfer / Release', exact=True).click()
        page.wait_for_function('Boolean(catalogFixture.waiting.navigation)')
        page.evaluate("history.pushState({},'', '/account'); dispatchEvent(new PopStateEvent('popstate'))")
        page.evaluate('catalogFixture.release("navigation")')
        settle()
        expect(dialog).to_be_hidden()
        page.evaluate('id=>{history.pushState({},"","/account?ownership="+id); dispatchEvent(new PopStateEvent("popstate"))}', GUITAR)
        expect(page.locator('#ownershipStart')).to_be_enabled()
        settle()

        # Unchanged pending ownership and safe repeated clicks: only one POST.
        compose()
        page.locator('#ownershipConfirm').evaluate('(button)=>{button.click();button.click()}')
        expect(page.locator('#ownershipSaved')).to_contain_text('Pending')
        settle()
        assert len(store['writes']) == 1 and store['owner'] == 'owner'
        first = store['items'][-1]['id']
        assert store['items'][-1]['acceptance'] is None
        expect(owned.locator('li')).to_have_count(1)
        expect(page.locator('#ownershipAccept')).to_be_hidden()
        expect(page.locator('#ownershipCancel')).to_be_visible()
        close()

        # Recipient acceptance is a separate reviewed action, not Verification.
        sign_in('buyer')
        expect(owned.locator('li')).to_have_count(0)
        open_inbox(first)
        expect(page.locator('#ownershipCancel')).to_be_hidden()
        expect(page.locator('#ownershipAccept')).to_be_visible()
        page.locator('#ownershipAccept').click()
        assert len(store['writes']) == 1
        expect(page.locator('#ownershipConfirm')).to_be_visible()
        page.evaluate('path=>catalogFixture.hold(path,"","accepted")', '/api/auth/transfers/' + first + '/resolve')
        page.locator('#ownershipConfirm').click()
        page.wait_for_function('Boolean(catalogFixture.waiting.accepted)')
        assert store['owner'] == 'buyer'
        close()
        page.evaluate('catalogFixture.release("accepted")')
        expect(owned.locator('li')).to_have_count(1)
        settle()
        expect(dialog).to_be_hidden()
        open_inbox(first)
        expect(page.locator('#ownershipEvidence')).to_contain_text('#2')
        expect(page.locator('#ownershipEvidence')).to_contain_text('#1')
        expect(page.locator('#ownershipEvidence')).to_contain_text('2026-02-01T12:00:00Z')
        expect(page.locator('#ownershipAccept')).to_be_hidden()
        assert store['items'][0]['verification_status'] == 'positive'
        assert len(store['writes']) == 2
        close()
        sign_in('owner')
        expect(owned.locator('li')).to_have_count(0)
        expect(former.locator('li')).to_have_count(1)

        # Source Cancel and recipient Decline preserve owner and add no Evidence.
        sign_in('buyer')
        compose('other')
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipCancel')).to_be_visible()
        settle()
        page.locator('#ownershipCancel').click()
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipSaved')).to_contain_text('Cancelled')
        settle(); close()
        compose('other')
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipCancel')).to_be_visible()
        settle(); close()
        pending = store['items'][-1]['id']
        sign_in('other'); open_inbox(pending)
        page.locator('#ownershipDecline').click()
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipSaved')).to_contain_text('Declined')
        settle(); close()
        assert store['owner'] == 'buyer' and store['items'][-1]['acceptance'] is None

        # Read-only keeps history readable; writes and destination selection stop.
        store['can_write'] = False
        sign_in('buyer')
        page.locator('#ownershipStart').click()
        expect(page.locator('#ownershipKind')).to_be_disabled()
        expect(page.locator('#ownershipReview')).to_be_disabled()
        expect(page.locator('#ownershipConfirm')).to_be_hidden()
        count = len(store['writes'])
        close()
        assert len(store['writes']) == count
        store['can_write'] = True
        page.locator('#ownershipIntentRefresh').click(); settle()

        # A server CAS conflict requires fresh review, and does not auto-retry.
        compose('other'); store['stale'] = True
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipConfirm')).to_be_hidden()
        settle()
        assert len(store['writes']) == count + 1
        assert store['items'][-1]['state'] == 'declined'
        close()

        # Unknown POST outcome after commit is discoverable without a duplicate.
        compose('other'); store['drop'] = 'after'
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipCheck')).to_be_visible()
        settle()
        count = len(store['writes'])
        assert store['items'][-1]['state'] == 'pending'
        close()
        page.locator('#ownershipStart').click()
        expect(page.locator('#ownershipReview')).to_be_disabled()
        page.locator('#ownershipCheck').click()
        expect(page.locator('#ownershipAcknowledge')).to_be_visible()
        settle()
        expect(page.locator('#ownershipSaved')).to_contain_text('Pending')
        page.locator('#ownershipAcknowledge').click()
        assert len(store['writes']) == count
        close()

        # Lost Release response: former-owner history and recovery remain usable.
        page.locator('#ownershipStart').click()
        page.locator('#ownershipKind').select_option('release')
        page.locator('#ownershipDate').fill('2026-03-01')
        page.locator('#ownershipBody').fill('Private release ' + ATTACK)
        page.locator('#ownershipReview').click()
        expect(page.locator('#ownershipConfirm')).to_be_visible()
        store['drop'] = 'after'
        page.locator('#ownershipConfirm').click()
        expect(page.locator('#ownershipCheck')).to_be_visible()
        expect(owned.locator('li')).to_have_count(0)
        expect(former.locator('li')).to_have_count(1)
        settle(); close()
        page.locator('#ownershipStart').click()
        page.locator('#ownershipCheck').click()
        expect(page.locator('#ownershipAcknowledge')).to_be_visible()
        settle()
        expect(page.locator('#ownershipSaved')).to_contain_text('Private release')
        page.locator('#ownershipAcknowledge').click()
        expect(page.locator('#ownershipReview')).to_be_disabled()
        assert len(store['writes']) == count + 1 and store['owner'] is None
        assert page.locator('#ownershipDialog img').count() == 0
        close()

        # Offline revocation purges participant content; sign-out clears all UI.
        store['restricted'] = True
        page.locator('#ownershipRefresh').click()
        expect(inbox.locator('li')).to_have_count(0)
        settle()
        page.locator('#signOut').click()
        expect(page.locator('#selfOwnership')).to_be_hidden()
        expect(inbox.locator('li')).to_have_count(0)
        expect(page.locator('#ownershipHistory li')).to_have_count(0)
        assert not store['external'] and not errors, (store['external'], errors)
        # Finish intercepted work before closing its page/context.
        page.wait_for_function('catalogFixture.pending===0')
        page.unroute_all(behavior='wait')
    print('Cloud Transfer/Release browser: verified identity, role-specific agreement, '
          'Evidence display, current/former history, stale CAS, read-only/offline, '
          'double click, dismissal, late search, unknown writes and SignOut passed.')


if __name__ == '__main__':
    main()
