"""Disposable browser journeys for authenticated Claim posting.

All requests are intercepted. No live identity, PostgreSQL, cloud services or
user data are accessed. Prepared for the standard browser runner; Chromium
execution must be performed in an environment where it is permitted.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_cloud_account import SDK
from browser_cloud_public_catalog import HOLD_SCRIPT
from browser_diagnostics import diagnostic_page
from ygc.cloud_registration import DOCUMENTS
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-claim-posting-fixture.invalid'
GUITAR_ID = '9007199254740993'
API = '/api/auth/guitars/' + GUITAR_ID + '/claims'
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'


def guitar(identifier=GUITAR_ID):
    return dict(id=identifier, manufacturer='Maker', model='Claim fixture', finish='Sunburst',
                year='1965', serial_number='SERIAL-' + identifier, photo=None, specifications=[])


def main():
    names = ['cloud-account-page.js', 'cloud-account-ownership.js', 'cloud-account-profile.js', 'cloud-account-avatar.js',
             'cloud-account-guitars.js', 'cloud-account-applications.js', 'cloud-account-claims.js', 'cloud-account-media.js',
             'cloud-account.css', 'cloud-public-catalog.js', 'cloud-public-catalog.css',
             'cloud-auth-loader.js', 'identity-platform-auth.js', 'overlays.js', 'ui-components.css']
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    account_html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    public_html = (STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8')
    store = dict(rows=[], calls=[], writes=[], external=[], can_write=True, conflict_once=False, drop_after_commit=False, revision=0)
    errors = []

    def revision():
        store['revision'] += 1
        return format(store['revision'], '064x')

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_claim_posting') as page:
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
            call = dict(method=request.method, path=path, body=request.post_data_json
                        if request.method in ('POST', 'PATCH') else None,
                        authorization=request.headers.get('authorization'))
            store['calls'].append(call)
            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture', 'authDomain': 'fixture.firebaseapp.com',
                                                'projectId': 'fixture'}, 'tenant': ''})
            elif path == '/api/auth/registration':
                route.fulfill(json={'documents': DOCUMENTS})
            elif path == '/api/auth/me':
                assert call['authorization']
                route.fulfill(json={'user': {'id': '1', 'app_user_id': 'fixture-owner', 'display_name': 'Fixture User',
                    'account_type': 'user', 'role': 'member', 'status': 'active'},
                    'identity': {'email_verified': 'fixture-verified-' in call['authorization']}})
            elif path == '/api/auth/profile':
                route.fulfill(json={'profile_revision': '1', 'fields': {'display_name': 'Fixture User',
                    'location_country': '', 'location_region': '', 'bio': ''}})
            elif path == '/api/auth/guitars':
                route.fulfill(json={'items': [], 'total': '0', 'next_after': None})
            elif path == '/api/auth/ownership-transfers':
                route.fulfill(json={'viewer_user_id': '1', 'items': [], 'can_write': store['can_write'], 'next_after': None})
            elif path == '/api/auth/applications':
                route.fulfill(json={'items': [], 'can_write': store['can_write']})
            elif path == '/api/auth/avatar':
                route.fulfill(status=404, json={'detail': 'No fixture avatar'})
            elif path == '/api/service/status':
                route.fulfill(json={'mode': 'normal', 'message': ''})
            elif path == '/api/public/guitars':
                route.fulfill(json={'items': [guitar()], 'total': '1', 'page': 1, 'page_size': 24, 'total_pages': 1})
            elif path.startswith('/api/public/guitars/'):
                identifier = path.split('/')[4]
                route.fulfill(json={'items': [], 'next_after': None} if path.endswith('/chronicle') else guitar(identifier))
            elif re.fullmatch(r'/api/auth/guitars/[1-9][0-9]*/claims', path) and request.method == 'GET':
                assert call['authorization'] and 'fixture-verified-' in call['authorization']
                identifier = path.split('/')[4]
                route.fulfill(json={'individual': guitar(identifier), 'items': deepcopy(store['rows']) if identifier == GUITAR_ID else [],
                                    'can_write': store['can_write'], 'next_after': None})
            elif path == API and request.method == 'POST' or path.startswith(API + '/') and request.method in ('POST', 'PATCH'):
                assert call['authorization'] and 'fixture-verified-' in call['authorization']
                assert request.headers.get('x-ygc-timezone')
                store['writes'].append(call)
                if not store['can_write']:
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if store['conflict_once']:
                    store['conflict_once'] = False
                    route.fulfill(status=409, json={'detail': {'code': 'claim_conflict'}})
                    return
                data = deepcopy(call['body'])
                if path == API:
                    assert set(data) == {'claim_type', 'body', 'occurred_at'} | (
                        {'specification_kind', 'items'} if data['claim_type'] == 'specification' else {'incident_kind'})
                    row = dict(id=str(23 + len(store['rows'])), individual_id=GUITAR_ID, status='active',
                               verification_status='unverified', created_at='2026-01-01T12:00:00Z',
                               field_name=None, value_text=None, specification_kind=None, incident_kind=None)
                    store['rows'].insert(0, row)
                else:
                    row = next(row for row in store['rows'] if row['id'] == path.split('/')[6])
                    if data['revision'] != row['revision']:
                        route.fulfill(status=409, json={'detail': {'code': 'claim_conflict'}})
                        return
                if path.endswith('/deactivate'):
                    assert set(data) == {'revision'}
                    row['status'] = 'inactive'
                else:
                    row.update({key: value for key, value in data.items() if key not in ('items', 'revision')})
                    row['spec_items'] = data.get('items', [])
                row.update(revision=revision(), updated_at='2026-01-02T12:00:00Z')
                if store['drop_after_commit']:
                    store['drop_after_commit'] = False
                    route.abort()
                else:
                    route.fulfill(json={'claim': deepcopy(row)})
            else:
                store['external'].append(request.url)
                route.abort()

        page.route('**/*', respond)
        page.goto(BASE + '/guitars/' + GUITAR_ID)
        page.wait_for_function('globalThis.YGCCloudPublicCatalogReady === true')
        expect(page.locator('#addClaimLink')).to_have_attribute('href', '/account?claim=' + GUITAR_ID)
        page.locator('#addClaimLink').click()
        page.wait_for_function('globalThis.YGCCloudAccountReady === true')
        expect(page.locator('#catalogClaimStatus')).to_contain_text('Sign in')
        expect(page.locator('#catalogClaimStart')).to_be_disabled()
        assert not store['writes']
        assert not any(call['path'] == API for call in store['calls'])
        page.locator('#email').fill('claim@example.invalid')
        page.locator('#password').fill('fixture-password')
        page.locator('#submit').click()
        expect(page.locator('#catalogClaimStatus')).to_contain_text('Verify your email')
        page.locator('#sendVerification').click()
        page.wait_for_function('globalThis.fixtureVerificationURL !== undefined')
        assert page.evaluate('globalThis.fixtureVerificationURL') == BASE + '/account?claim=' + GUITAR_ID
        page.evaluate("sessionStorage.setItem('verified-claim@example.invalid', 'true')")
        page.locator('#refreshVerification').click()
        expect(page.locator('#catalogClaimStart')).to_be_enabled()
        assert not store['writes']
        dialog = page.locator('#claimDialog')
        page.locator('#catalogClaimStart').click()
        expect(dialog).to_be_visible()
        page.locator('#claimBody').fill('Dismiss me')
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()
        expect(page.locator('#claimBody')).to_have_value('')
        assert not store['writes']

        # Create an exact multi-field Repair with raw text treated as text, not markup.
        page.locator('#catalogClaimStart').click()
        page.locator('#claimKind').select_option('repair')
        page.locator('#claimDate').fill('2026-01-03')
        page.locator('#claimField_0').fill('finish')
        page.locator('#claimValue_0').fill(ATTACK)
        page.locator('#claimAddField').click()
        page.locator('#claimField_1').fill('neck wood')
        page.locator('#claimValue_1').fill('Maple')
        page.locator('#claimBody').fill('PRIVATE NOTE')
        page.locator('#claimSave').click()
        expect(page.locator('#claimMessage')).to_have_text('Claim saved.')
        assert len(store['writes']) == 1 and store['writes'][-1]['body']['specification_kind'] == 'repair'
        expect(page.locator('#claimSavedState')).to_contain_text('PRIVATE NOTE')
        expect(dialog.locator('img')).to_have_count(0)
        assert page.evaluate('globalThis.fixtureXss || false') is False

        # Preserve typed edits through an optimistic conflict and explicit rebase.
        page.locator('#claimBody').fill('MY UNSAVED EDIT')
        store['rows'][0].update(body='REMOTE NOTE', revision=revision())
        page.locator('#claimSave').click()
        expect(page.locator('#claimLatest')).to_contain_text('REMOTE NOTE')
        expect(page.locator('#claimBody')).to_have_value('MY UNSAVED EDIT')
        expect(page.locator('#claimSave')).to_be_disabled()
        assert len(store['writes']) == 1
        page.locator('#claimKeepEdits').click()
        page.locator('#claimSave').click()
        expect(page.locator('#claimMessage')).to_have_text('Claim saved.')
        assert len(store['writes']) == 2 and store['writes'][-1]['body']['body'] == 'MY UNSAVED EDIT'
        page.locator('#claimDeactivate').click()
        assert len(store['writes']) == 2
        expect(page.locator('#claimMessage')).to_contain_text('Deactivate Claim')
        page.locator('#claimDeactivate').click()
        expect(page.locator('#claimMessage')).to_contain_text('Claim deactivated')
        expect(page.locator('#claimSave')).to_be_disabled()
        page.locator('#claimClose').click()
        expect(page.locator('#claimsList')).to_contain_text('Inactive')

        # Native browser validation must not require hidden specification inputs for an Incident.
        for kind in ('damage', 'lost', 'theft'):
            page.locator('#catalogClaimStart').click()
            page.locator('#claimKind').select_option(kind)
            page.locator('#claimBody').fill(kind + ' fixture detail')
            page.locator('#claimSave').click()
            expect(page.locator('#claimMessage')).to_have_text('Claim saved.')
            assert store['writes'][-1]['body']['claim_type'] == 'incident'
            assert store['writes'][-1]['body']['incident_kind'] == kind
            assert 'ownership_kind' not in store['writes'][-1]['body']
            expect(page.locator('#claimKind')).to_be_disabled()
            page.locator('#claimClose').click()

        # A maintenance409 on creation remains a retryable draft rather than an edit conflict.
        page.locator('#catalogClaimStart').click()
        page.locator('#claimKind').select_option('damage')
        page.locator('#claimBody').fill('Retry this draft')
        store['conflict_once'] = True
        page.locator('#claimSave').click()
        expect(page.locator('#claimMessage')).to_contain_text('Try saving again')
        expect(page.locator('#claimBody')).to_have_value('Retry this draft')
        expect(page.locator('#claimSave')).to_be_enabled()
        page.locator('#claimSave').click()
        expect(page.locator('#claimMessage')).to_have_text('Claim saved.')
        page.locator('#claimClose').click()

        # A committed creation with a lost response cannot be duplicated by ordinary Save.
        page.locator('#catalogClaimStart').click()
        page.locator('#claimKind').select_option('theft')
        page.locator('#claimBody').fill('UNCONFIRMED POST')
        store['drop_after_commit'] = True
        page.locator('#claimSave').click()
        expect(page.locator('#claimMessage')).to_contain_text('Could not confirm')
        expect(page.locator('#claimSave')).to_be_disabled()
        before = len(store['writes'])
        page.locator('#claimCheckSubmission').click()
        expect(page.locator('#claimUncertainResults')).to_contain_text('UNCONFIRMED POST')
        expect(page.locator('#claimSave')).to_be_disabled()
        assert len(store['writes']) == before
        page.locator('#claimRetryCreate').click()
        expect(page.locator('#claimSave')).to_be_enabled()
        assert len(store['writes']) == before
        page.locator('#claimClose').click()

        # Closing or moving in browser history while revalidation is pending cannot POST.
        page.set_viewport_size({'width': 390, 'height': 844})
        for dismiss in ('escape', 'back'):
            page.locator('#catalogClaimStart').click()
            page.locator('#claimKind').select_option('lost')
            page.locator('#claimBody').fill('Do not submit')
            before = len(store['writes'])
            page.evaluate("path => catalogFixture.hold(path, '', 'preflight')", API)
            page.locator('#claimSave').click()
            page.wait_for_function("typeof catalogFixture.waiting.preflight === 'function'")
            if dismiss == 'escape':
                page.keyboard.press('Escape')
            else:
                page.evaluate("history.pushState({}, '', '/account'); dispatchEvent(new PopStateEvent('popstate'))")
            expect(dialog).to_be_hidden()
            page.evaluate("catalogFixture.release('preflight')")
            expect(page.locator('#signOut')).to_be_enabled()
            assert len(store['writes']) == before
            assert page.evaluate('document.body.style.overflow') != 'hidden'
            if dismiss == 'back':
                page.evaluate("history.back()")
                expect(page.locator('#catalogClaimStart')).to_be_enabled()
        page.set_viewport_size({'width': 1440, 'height': 1000})

        store['can_write'] = False
        page.locator('#claimsRefresh').click()
        expect(page.locator('#catalogClaimStart')).to_be_disabled()
        expect(page.locator('#claimsList li')).to_have_count(len(store['rows']))
        page.locator('#claimsList button').first.click()
        expect(dialog).to_be_visible()
        expect(page.locator('#claimSave')).to_be_disabled()
        expect(page.locator('#claimDeactivate')).to_be_disabled()
        page.locator('#claimClose').click()
        page.locator('#signOut').click()
        expect(page.locator('#selfClaims')).to_be_hidden()
        expect(page.locator('#claimsList li')).to_have_count(0)
        expect(page.locator('#claimBody')).to_have_value('')
        assert not store['external'], store['external']
        assert not errors, errors


if __name__ == '__main__':
    main()
