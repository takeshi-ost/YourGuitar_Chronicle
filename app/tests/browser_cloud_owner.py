"""Real account/Owner UI journeys with disposable identity and store fixtures.

Run through run_browser_checks.py. No Google, PostgreSQL, or live data is used;
the production page, auth adapter, API routers, and native overlays are loaded.
Ownership transitions are fixture responses, not a substitute for database tests.
"""
from copy import deepcopy
import re
import socket
import threading

from fastapi import FastAPI, Request
from playwright.sync_api import expect, sync_playwright
import uvicorn

from browser_cloud_account import SDK
from browser_diagnostics import diagnostic_page
from ygc.claim_revision import ClaimConflict
from ygc.cloud_account_page import install, public_config
from ygc.cloud_account_routes import account_router
from ygc.cloud_owner_routes import owner_router
from ygc.cloud_registration import DOCUMENTS
from ygc.cloud_self_guitars_routes import self_guitars_router
from ygc.cloud_self_profile_routes import self_profile_router
from ygc.identity_platform import VerifiedIdentity


def main():
    accounts = {
        'fixture-owner@example.invalid': dict(id=1, app_user_id='owner-uuid',
            display_name='Original owner', account_type='user', role='member'),
        'fixture-buyer@example.invalid': dict(id=2, app_user_id='buyer-uuid',
            display_name='New owner', account_type='user', role='member'),
    }

    class Accounts:
        def resolve_identity(self, *, issuer, subject, tenant):
            if subject not in accounts:
                raise PermissionError()
            return accounts[subject]

    class Verifier:
        accounts = Accounts()

        def verify(self, *, bearer_token):
            if not bearer_token.startswith('fixture-'):
                raise PermissionError()
            return VerifiedIdentity('fixture-issuer',
                bearer_token.replace('fixture-verified-', 'fixture-', 1), '',
                bearer_token.startswith('fixture-verified-'))

    class Store:
        def __init__(self):
            self.current_owner = 'owner-uuid'
            self.former_owners = set()
            self.reads, self.pending_reads, self.attempts, self.decisions = [], [], [], []
            self.pending_started, self.release_pending = threading.Event(), threading.Event()
            self.transfer_started, self.release_transfer = threading.Event(), threading.Event()
            self.release_pending.set()
            self.release_transfer.set()
            self.guitar = dict(id=12, manufacturer='Fixture maker', model='Owner journey',
                               year=1960, serial_number='OWNER12')
            common = dict(individual_id='12', occurred_at='2026-10-01',
                          field_name=None, value_text=None, verification_status='unverified')
            self.claims = {
                23: dict(common, id='23', author_user_id=3, author_name='<b>Contributor</b>',
                    claim_type='specification', specification_kind='specification', ownership_kind=None,
                    body='Full specification <img src=x onerror=alert(1)>', revision='a' * 64,
                    spec_items=[dict(field_name='finish', value_text='Lake Placid Blue'),
                                dict(field_name='pickup_configuration', value_text='SSS <b>original</b>'),
                                dict(field_name='neck_material', value_text='Maple')],
                    decline_reason_required=False),
                24: dict(common, id='24', author_user_id=3, author_name='Other applicant',
                    claim_type='ownership', specification_kind=None, ownership_kind='acquire',
                    body='Accepted image review; awaiting Owner response', revision='b' * 64,
                    spec_items=[], decline_reason_required=True),
                25: dict(common, id='25', author_user_id=2, author_name='New owner',
                    claim_type='ownership', specification_kind=None, ownership_kind='acquire',
                    body='Accepted acquisition by the buyer', revision='c' * 64,
                    spec_items=[], decline_reason_required=True),
            }

        def own_guitars(self, actor, *, kind, after, limit):
            self.reads.append((actor, kind))
            included = actor == self.current_owner if kind == 'owned' else actor in self.former_owners
            rows = [dict(self.guitar)] if included else []
            return dict(items=[row for row in rows if row['id'] > after][:limit],
                        total=len(rows), next_after=None)

        def pending(self, actor, individual):
            self.pending_reads.append((actor, individual))
            if actor != self.current_owner or individual != 12:
                raise PermissionError()
            user_id = next(row['id'] for row in accounts.values() if row['app_user_id'] == actor)
            result = dict(can_write=not getattr(self, 'read_only', False), items=[deepcopy(row) for row in self.claims.values()
                                if row['author_user_id'] != user_id])
            self.pending_started.set()
            if not self.release_pending.wait(timeout=15):
                raise RuntimeError('Fixture Owner list response was not released')
            return result

        def respond(self, actor, individual, claim, data):
            self.attempts.append((actor, individual, claim, deepcopy(data)))
            if actor != self.current_owner or individual != 12:
                raise PermissionError()
            row = self.claims[claim]
            if data.get('revision') != row['revision']:
                raise ClaimConflict()
            if row['decline_reason_required'] and data.get('stance') == 'negative' and not data.get('reason', '').strip():
                raise ValueError()
            self.decisions.append((actor, individual, claim, deepcopy(data)))
            row['verification_status'] = data['stance']
            row['revision'] = format(int(row['revision'], 16) + 1, '064x')
            if claim == 25 and data['stance'] == 'positive':
                self.former_owners.add(actor)
                self.current_owner = 'buyer-uuid'
                self.transfer_started.set()
                if not self.release_transfer.wait(timeout=15):
                    raise RuntimeError('Fixture transfer response was not released')
            return dict(claim_id=str(claim), verification_status=data['stance'])

        def own_profile(self, actor):
            record = next(row for row in accounts.values() if row['app_user_id'] == actor)
            return dict(profile_revision='1', fields=dict(display_name=record['display_name'],
                        location_country='', location_region='', bio=''))

    store, verifier, app = Store(), Verifier(), FastAPI()
    app.include_router(account_router(verifier, DOCUMENTS))
    app.include_router(self_guitars_router(verifier, store))
    app.include_router(self_profile_router(verifier, store))
    app.include_router(owner_router(verifier, store))

    @app.get('/api/auth/notifications')
    def notifications():
        return {'items': [], 'next_after': None, 'unread_count': '0', 'can_write': True}

    @app.get('/api/auth/identity-corrections')
    def identity_corrections():
        return {'items': [], 'next_after': None, 'can_write': True}

    @app.get('/api/auth/ownership-transfers')
    def ownership_transfers(request: Request):
        identity = Verifier().verify(bearer_token=request.headers['authorization'].removeprefix('Bearer '))
        user = accounts[identity.subject]
        return {'viewer_user_id': str(user['id']), 'items': [], 'can_write': True, 'next_after': None}

    @app.get('/api/auth/applications')
    def applications():
        return {'items': [], 'can_write': True}

    install(app, public_config({'apiKey': 'fixture-key',
        'authDomain': 'fixture-project.firebaseapp.com'}, project_id='fixture-project', tenant=''))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        url = f'http://127.0.0.1:{sock.getsockname()[1]}/account'
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_owner') as page:
                page.context.route('https://www.gstatic.com/firebasejs/**', lambda route:
                    route.fulfill(content_type='text/javascript',
                        body='export const initializeApp=config=>config;'
                        if 'firebase-app.js' in route.request.url else SDK))
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                page.wait_for_function('window.YGCCloudAccountReady===true')
                owned = page.locator('#selfGuitars_owned')
                former = page.locator('#selfGuitars_formerly_owned')
                dialog = page.locator('#ownerResponseDialog')

                def sign_in_as(email, verified=True):
                    page.evaluate('''([email, verified]) => {
                        sessionStorage.clear();
                        sessionStorage.setItem('fixture-sdk-email', email);
                        sessionStorage.setItem('verified-' + email, String(verified));
                    }''', [email, verified])
                    page.reload()
                    page.wait_for_function('window.YGCCloudAccountReady===true')

                def open_owner():
                    owned.get_by_role('button', name='Review owner responses', exact=True).click()
                    expect(dialog).to_be_visible()
                    expect(dialog.locator('section')).to_have_count(3)
                    expect(dialog.locator('select').first).to_be_enabled()

                def card(claim):
                    return dialog.locator('section').filter(has_text=re.compile(r'^#' + str(claim) + r' ·'))

                def review(claim, stance):
                    row = card(claim)
                    row.get_by_role('combobox', name='Claim decision').select_option(stance)
                    row.get_by_role('button', name='Review decision', exact=True).click()
                    return row.locator('[data-owner-confirm]')

                expect(page.locator('#selfGuitars')).to_be_hidden()
                sign_in_as('owner@example.invalid', verified=False)
                expect(page.locator('#selfGuitars')).to_be_hidden()
                assert not store.reads and not store.pending_reads and not store.attempts
                sign_in_as('owner@example.invalid')
                expect(owned.locator('li')).to_have_count(1)
                expect(former.locator('li')).to_have_count(0)

                # Read-only access keeps review content visible and all decision controls inert.
                store.read_only = True
                owned.get_by_role('button', name='Review owner responses', exact=True).click()
                expect(dialog).to_be_visible()
                expect(dialog.locator('section')).to_have_count(3)
                expect(dialog.locator('select').first).to_be_disabled()
                expect(dialog.get_by_role('button', name='Review decision').first).to_be_disabled()
                expect(dialog.get_by_role('status')).to_contain_text('read-only')
                assert not store.attempts
                dialog.get_by_role('button', name='Close', exact=True).click()
                store.read_only = False

                # Every field must be visible as text before a decision is sent.
                open_owner()
                for content in ('specification', 'finish: Lake Placid Blue',
                                'pickup_configuration: SSS <b>original</b>', 'neck_material: Maple',
                                '<b>Contributor</b>', '<img src=x onerror=alert(1)>'):
                    expect(card(23)).to_contain_text(content)
                assert dialog.locator('img,b').count() == 0
                confirm = review(23, 'positive')
                expect(confirm).to_be_visible()
                card(23).get_by_role('combobox').select_option('unverified')
                expect(confirm).to_be_hidden()
                assert not store.attempts
                dialog.get_by_role('button', name='Close', exact=True).click()

                original_history = page.evaluate('history.length')
                original_overflow = page.evaluate('document.body.style.overflow')
                for dismissal in ('close', 'escape', 'backdrop'):
                    if dismissal == 'escape':page.set_viewport_size({'width': 390, 'height': 844})
                    open_owner();expect(review(23, 'positive')).to_be_visible()
                    assert not store.attempts
                    if dismissal == 'close':dialog.get_by_role('button', name='Close', exact=True).click()
                    elif dismissal == 'escape':page.keyboard.press('Escape')
                    else:page.mouse.click(2, 2)
                    expect(dialog).to_be_hidden();expect(dialog.locator('section')).to_have_count(0)
                    expect(owned.get_by_role('button', name='Review owner responses')).to_be_enabled()
                    assert page.url == url and page.evaluate('history.length') == original_history
                    assert page.evaluate('document.body.style.overflow') == original_overflow
                    assert not store.attempts
                page.set_viewport_size({'width': 1440, 'height': 1000})

                # A late initial read cannot repopulate a dismissed dialog.
                store.pending_started.clear();store.release_pending.clear()
                owned.get_by_role('button', name='Review owner responses', exact=True).click()
                assert store.pending_started.wait(timeout=5), 'Owner list did not reach the fixture'
                expect(dialog).to_be_visible();expect(dialog.locator('section')).to_have_count(0)
                page.keyboard.press('Escape');store.release_pending.set()
                expect(owned.get_by_role('button', name='Review owner responses')).to_be_enabled()
                expect(dialog).to_be_hidden();expect(dialog.locator('section')).to_have_count(0)
                assert not store.attempts

                # A stale decision now hides/disables Apply and all decisions.
                # Keeping the old confirmation enabled would allow stale photos
                # or content to be reviewed without a fresh authorized list.
                open_owner();confirm = review(23, 'positive')
                store.claims[23]['revision'] = 'd' * 64
                confirm.click()
                expect(dialog.get_by_role('status')).to_contain_text('Refresh before reviewing again')
                expect(confirm).to_be_hidden();expect(confirm).to_be_disabled()
                expect(card(23).get_by_role('button', name='Review decision')).to_be_disabled()
                assert len(store.attempts) == 1 and not store.decisions
                previous_pending_reads = len(store.pending_reads)
                page.locator('#ownerMediaReload').click()
                expect(dialog.locator('section')).to_have_count(3)
                expect(card(23).get_by_role('combobox')).to_be_enabled()
                expect(card(23).locator('[data-owner-confirm]')).to_be_hidden()
                assert len(store.pending_reads) == previous_pending_reads + 1
                assert len(store.attempts) == 1 and not store.decisions
                confirm = review(23, 'positive')
                expect(confirm).to_be_visible();expect(confirm).to_be_enabled()
                assert len(store.attempts) == 1 and not store.decisions
                with page.expect_response(lambda response: response.request.method == 'POST'
                        and response.url.endswith('/api/auth/guitars/12/owner-responses/23')) as accepted:
                    confirm.click()
                assert accepted.value.status == 200
                expect(dialog).to_be_hidden()
                expect(owned.get_by_role('button', name='Review owner responses')).to_be_enabled()
                successful_spec = ('owner-uuid', 12, 23, dict(stance='positive', revision='d' * 64))
                assert len(store.attempts) == 2 and store.decisions == [successful_spec]

                # Accepted image review still needs an explicit Owner decline reason.
                open_owner();confirm = review(24, 'negative')
                reason = page.locator('#ownerDeclineReason_24')
                expect(reason).to_be_visible();expect(reason).to_be_focused()
                expect(confirm).to_be_hidden()
                reason.fill('   ');card(24).get_by_role('button', name='Review decision').click()
                expect(confirm).to_be_hidden();assert len(store.attempts) == 2
                reason.fill('Wrong acquisition date')
                card(24).get_by_role('button', name='Review decision').click()
                expect(confirm).to_be_visible()
                reason.fill('  The photographed serial differs from my guitar.  ')
                expect(confirm).to_be_hidden()
                card(24).get_by_role('button', name='Review decision').click()
                expect(dialog.get_by_role('status')).to_contain_text('The photographed serial differs from my guitar.')
                assert len(store.attempts) == 2
                previous_reads = len(store.reads)
                confirm.click();expect(dialog).to_be_hidden()
                expect(owned.locator('li')).to_have_count(1);expect(former.locator('li')).to_have_count(0)
                expect(owned.get_by_role('button', name='Review owner responses')).to_be_enabled()
                assert store.decisions == [successful_spec, ('owner-uuid', 12, 24, dict(stance='negative',
                    revision='b' * 64, reason='The photographed serial differs from my guitar.'))]
                assert sorted(store.reads[previous_reads:]) == [('owner-uuid', 'formerly_owned'), ('owner-uuid', 'owned')]

                # Closing while an approved transfer is in flight must not skip list refresh.
                open_owner();confirm = review(25, 'positive')
                expect(page.locator('#ownerDeclineReason_25')).to_be_hidden()
                assert len(store.attempts) == 3
                previous_reads = len(store.reads)
                store.release_transfer.clear()
                confirm.click()
                assert store.transfer_started.wait(timeout=5), 'Owner decision did not reach the fixture'
                expect(confirm).to_be_disabled()
                dialog.get_by_role('button', name='Close', exact=True).click()
                expect(dialog).to_be_hidden()
                store.release_transfer.set()
                expect(owned.locator('li')).to_have_count(0)
                expect(former.locator('li')).to_have_count(1)
                expect(owned.get_by_role('button', name='Refresh', exact=True)).to_be_enabled()
                expect(former.get_by_role('button', name='Review owner responses')).to_have_count(0)
                expect(dialog).to_be_hidden();expect(dialog.locator('section')).to_have_count(0)
                assert sorted(store.reads[previous_reads:]) == [('owner-uuid', 'formerly_owned'), ('owner-uuid', 'owned')]
                assert store.decisions[-1] == ('owner-uuid', 12, 25, dict(stance='positive', revision='c' * 64))
                assert len(store.attempts) == 4 and len(store.decisions) == 3
                assert page.evaluate('document.body.style.overflow') == original_overflow

                page.locator('#signOut').click()
                expect(page.locator('#selfGuitars')).to_be_hidden()
                expect(page.locator('#selfGuitars li')).to_have_count(0)
                expect(dialog).to_be_hidden()
                sign_in_as('buyer@example.invalid')
                expect(owned.locator('li')).to_have_count(1);expect(former.locator('li')).to_have_count(0)
                owned.get_by_role('button', name='Review owner responses', exact=True).click()
                expect(dialog.locator('section')).to_have_count(2)
                expect(card(25)).to_have_count(0)  # The new owner cannot judge their own Acquire.
                expect(dialog.locator('[data-owner-confirm]:visible')).to_have_count(0)
                page.keyboard.press('Escape');page.locator('#signOut').click()
                expect(page.locator('#selfGuitars li')).to_have_count(0)
                assert len(store.attempts) == 4 and not errors, errors
        finally:
            store.release_pending.set()
            store.release_transfer.set()
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError('Owner browser fixture server did not stop')
    print('Cloud Owner: identity gates, complete specification content, explicit confirmation, dismissal, stale revision, reasoned decline, transfer refresh and SignOut passed.')


if __name__ == '__main__':
    main()
