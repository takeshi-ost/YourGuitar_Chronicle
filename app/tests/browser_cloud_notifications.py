"""Real Chromium notification inbox journeys with fully synthetic intercepted data.

Runs production account HTML, CSS, auth adapter, inbox and destination modules.
No live identity, user data, PostgreSQL, photo or cloud service is accessed. This
suite is for the authorized Mac/CI browser runner; compilation is not acceptance.
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
BASE = 'http://ygc-notifications-fixture.invalid'
API = '/api/auth/notifications'
GUITAR = '9007199254741021'
TRANSFER = '9223372036854775807'
CLAIM = '9007199254741001'
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'
NOW = '2026-10-07T01:00:00Z'
READ_AT = '2026-10-07T02:00:00Z'
AUDIT = r'''
(() => {
 const original=globalThis.fetch.bind(globalThis);
 const fixture=globalThis.notificationFixture={requests:[],holdLogout:false,waitingLogout:false};
 globalThis.fetch=async(input,options={})=>{
   const url=new URL(typeof input==='string'?input:input.url,location.href);
   if(url.pathname.startsWith('/api/auth/notifications'))fixture.requests.push({path:url.pathname,
     method:options.method||'GET',credentials:options.credentials,cache:options.cache,
     redirect:options.redirect,authorization:new Headers(options.headers).get('authorization')});
   return original(input,options);
 };
})();
'''
SDK_WITH_HELD_LOGOUT = SDK.replace(
    'export async function signOut(){',
    '''export async function signOut(){
      if(globalThis.notificationFixture?.holdLogout){
        notificationFixture.holdLogout=false;notificationFixture.waitingLogout=true;
        await new Promise(resolve=>{notificationFixture.releaseLogout=()=>{
          notificationFixture.waitingLogout=false;resolve();
        }});
      }
    ''')


def main():
    names = [path.name for path in STATIC.glob('cloud-account-*.js')]
    names += ['cloud-account.css', 'cloud-auth-loader.js', 'identity-platform-auth.js',
              'overlays.js', 'ui-components.css']
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                        + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    users = {name: dict(id=str(index), app_user_id='fixture-' + name,
             display_name=name.title(), account_type='user', role='member', status='active')
             for index, name in enumerate(('recipient', 'sender', 'other'), 1)}
    guitar = dict(id=GUITAR, manufacturer='Fixture maker', model='Notification guitar',
                  finish='Natural', year='1965', serial_number='PRIVATE-SERIAL')
    rows = [dict(id=str(9007199254741100 - index), notification_type='claim_verified',
                 title='Historical notice ' + str(index), body='Private history ' + str(index),
                 created_at=NOW, is_read=False, read_at=None, actor=None, destination=None)
            for index in range(28)]
    rows[0].update(notification_type='transfer_request', title='Transfer notice ' + ATTACK,
                   body='This notice does not accept a Transfer.', actor=dict(id='2', display_name='Sender ' + ATTACK),
                   destination=dict(kind='transfer', claim_id=TRANSFER))
    rows[1].update(notification_type='claim_added', title='Owner review notice',
                   destination=dict(kind='owner', individual_id=GUITAR, claim_id=CLAIM))
    rows[2].update(notification_type='ownership_decline', title='Historical decline',
                   body='Reading this is not acknowledgement. ' + ATTACK)
    rows[3].update(notification_type='dispute_resolved', title='Historical dispute result', body=None)
    store = dict(rows=rows, calls=[], writes=[], external=[], can_write=True, mode='normal',
                 drop=None, reject=None, malformed=False, transfer_available=True, owner_claim=True)
    errors = []

    def recipient_rows(actor):
        return store['rows'] if actor == 'recipient' else []

    def unread(actor):
        return str(sum(not row['is_read'] for row in recipient_rows(actor)))

    def inbox(actor, query):
        after = query.get('after', [None])[0]
        source = [row for row in recipient_rows(actor) if after is None or int(row['id']) < int(after)]
        limit = int(query.get('limit', ['25'])[0])
        assert limit == 25 and set(query) <= {'after', 'limit'}
        selected = deepcopy(source[:limit])
        if store['malformed'] and selected:
            selected[0]['id'] = 9007199254741100
        return dict(items=selected, next_after=selected[-1]['id'] if len(source) > limit else None,
                    unread_count=unread(actor), can_write=store['can_write'])

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_notifications') as page:
        page.add_init_script(HOLD_SCRIPT + AUDIT)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            parsed = urlsplit(request.url)
            path, method = parsed.path, request.method
            if parsed.netloc == 'www.gstatic.com' and path.startswith('/firebasejs/'):
                route.fulfill(content_type='text/javascript', body='export const initializeApp=config=>config;'
                              if path.endswith('/firebase-app.js') else SDK_WITH_HELD_LOGOUT)
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
            store['calls'].append(dict(path=path, method=method, actor=actor, query=query))
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
                route.fulfill(json={'items': [], 'total': '0', 'next_after': None})
            elif path == '/api/auth/ownership-transfers':
                route.fulfill(json={'viewer_user_id': users[actor]['id'], 'items': [], 'can_write': store['can_write'], 'next_after': None})
            elif path == '/api/auth/identity-corrections':
                route.fulfill(json={'items': [], 'next_after': None, 'can_write': store['can_write']})
            elif path == '/api/auth/transfers/' + TRANSFER:
                assert method == 'GET', 'Opening a notification must not resolve a Transfer'
                if actor != 'recipient' or not store['transfer_available']:
                    route.fulfill(status=404, json={'detail': 'Unavailable'})
                    return
                route.fulfill(json=dict(viewer_user_id='1', id=TRANSFER, individual_id=GUITAR,
                    individual=deepcopy(guitar), ownership_kind='transfer', from_user=dict(id='2', display_name='Sender', account_type='user'),
                    to_user=dict(id='1', display_name='Recipient', account_type='user'), state='pending',
                    status='active', verification_status='unverified', revision='a' * 64,
                    created_at=NOW, resolved_at=None, occurred_at=None, acceptance=None,
                    can_write=store['can_write'], can_accept=store['can_write'], can_decline=store['can_write'], can_cancel=False))
            elif path == '/api/auth/guitars/' + GUITAR + '/owner-responses':
                assert method == 'GET', 'Opening a notification must not approve a Claim'
                row = dict(id=CLAIM, individual_id=GUITAR, author_name='Sender', claim_type='specification',
                    specification_kind='specification', ownership_kind=None, occurred_at='2026-01-01',
                    body='Private Owner review content', field_name=None, value_text=None,
                    spec_items=[dict(field_name='finish', value_text='Natural')], media_items=[],
                    verification_status='unverified', created_at=NOW, updated_at=NOW,
                    decline_reason_required=False, revision='b' * 64)
                route.fulfill(json={'items': [row] if store['owner_claim'] else [], 'can_write': store['can_write']})
            elif path.startswith(API):
                if store['mode'] in ('offline', 'admin_only') or method == 'POST' and not store['can_write']:
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if path == API and method == 'GET':
                    route.fulfill(json=inbox(actor, query))
                    return
                assert method == 'POST' and not query
                assert request.post_data_json == {} and request.headers['content-type'].startswith('application/json')
                assert request.headers.get('sec-fetch-site') != 'cross-site'
                assert path == API + '/read-all' or path.endswith('/read')
                store['writes'].append(dict(path=path, actor=actor))
                if store['reject']:
                    rejected, store['reject'] = store['reject'], None
                    route.fulfill(status=rejected, json={'detail': 'SECRET SQL / private@example.invalid'})
                    return
                drop, store['drop'] = store['drop'], None
                if drop == 'before':
                    route.abort('failed')
                    return
                selected = recipient_rows(actor)
                if path != API + '/read-all':
                    notification_id = path.removeprefix(API + '/').removesuffix('/read')
                    selected = [row for row in selected if row['id'] == notification_id]
                if not selected:
                    route.fulfill(status=404, json={'detail': 'Unavailable'})
                    return
                marked = sum(not row['is_read'] for row in selected)
                for row in selected:
                    row['is_read'] = True
                    row['read_at'] = row['read_at'] or READ_AT
                result = dict(marked_count=str(marked), unread_count=unread(actor)) if path.endswith('/read-all') else dict(
                    id=selected[0]['id'], is_read=True, read_at=selected[0]['read_at'], unread_count=unread(actor))
                if drop == 'after':
                    route.abort('failed')
                else:
                    route.fulfill(json=result)
            else:
                raise AssertionError('Unexpected notification journey request: ' + method + ' ' + path)

        page.route('**/*', respond)
        inbox_list = page.locator('#notificationList')
        notification = lambda index=0: page.locator('[data-notification-id="' + rows[index]['id'] + '"]')

        def settle():
            page.wait_for_function('catalogFixture.pending===0')
            expect(page.locator('#signOut')).to_be_enabled()

        def sign_in(actor='recipient', verified=True):
            page.evaluate("""([actor,verified])=>{
                sessionStorage.clear();const email=actor+'@example.invalid';
                sessionStorage.setItem('fixture-sdk-email',email);
                sessionStorage.setItem('verified-'+email,String(verified));
            }""", [actor, verified])
            page.goto(BASE + '/account')
            page.wait_for_function('globalThis.YGCCloudAccountReady===true')
            settle()

        def refresh():
            page.locator('#notificationRefresh').click()
            settle()

        def unread_first():
            rows[0].update(is_read=False, read_at=None)
            refresh()

        page.goto(BASE + '/account')
        page.wait_for_function('globalThis.YGCCloudAccountReady===true')
        expect(page.locator('#selfNotifications')).to_be_hidden()
        sign_in(verified=False)
        expect(page.locator('#selfNotifications')).to_be_hidden()
        assert not [call for call in store['calls'] if call['path'] == API]
        sign_in('other')
        expect(inbox_list.locator('li')).to_have_count(0)
        expect(page.locator('#notificationUnread')).to_have_text('Unread: 0')
        sign_in()
        expect(inbox_list.locator('li')).to_have_count(25)
        expect(page.locator('#notificationUnread')).to_have_text('Unread: 28')
        expect(notification(3)).to_contain_text('Historical dispute result')
        assert inbox_list.locator('img, a, script').count() == 0
        assert page.evaluate('Boolean(globalThis.fixtureXss)') is False
        assert not store['writes']

        # Exact decimal cursor pagination replaces rather than accumulates rows.
        page.locator('#notificationNext').click()
        settle()
        expect(inbox_list.locator('li')).to_have_count(3)
        expect(page.locator('#notificationNext')).to_be_disabled()
        page.locator('#notificationPrevious').click()
        settle()
        expect(inbox_list.locator('li')).to_have_count(25)
        expect(page.locator('#notificationPrevious')).to_be_disabled()
        assert any(call['query'].get('after') == [rows[24]['id']] for call in store['calls'])

        # Supported destinations use current APIs, without marking or decisions.
        notification().get_by_role('button', name='Open Transfer', exact=True).click()
        settle()
        expect(page.locator('#ownershipDialog')).to_be_visible()
        expect(page.locator('#ownershipConfirm')).to_be_hidden()
        page.locator('#ownershipClose').click()
        notification(1).get_by_role('button', name='Open Owner review', exact=True).click()
        settle()
        expect(page.locator('#ownerResponseDialog')).to_contain_text('Private Owner review content')
        expect(page.locator('#ownerResponseDialog [data-owner-confirm]')).to_be_hidden()
        page.locator('#ownerResponseDialog').get_by_role('button', name='Close', exact=True).click()
        assert not store['writes'] and not rows[0]['is_read'] and not rows[1]['is_read']

        # A historical hint cannot bypass changed role/claim/participant access.
        store['owner_claim'] = False
        notification(1).get_by_role('button', name='Open Owner review', exact=True).click()
        settle()
        expect(page.locator('#ownerResponseDialog')).to_contain_text('no longer available')
        expect(page.locator('#ownerResponseDialog')).not_to_contain_text('Private Owner review content')
        assert page.locator('#ownerResponseDialog [data-owner-confirm]').count() == 0
        page.locator('#ownerResponseDialog').get_by_role('button', name='Close', exact=True).click()
        store['owner_claim'] = True; store['transfer_available'] = False
        notification().get_by_role('button', name='Open Transfer', exact=True).click()
        settle()
        expect(page.locator('#ownershipDialog')).to_be_hidden()
        store['transfer_available'] = True
        assert not store['writes']

        # Explicit mark-one and mark-all only mutate notification read columns.
        notification().get_by_role('button', name='Mark as read', exact=True).evaluate('(button)=>{button.click();button.click()}')
        settle()
        assert len(store['writes']) == 1 and rows[0]['read_at'] == READ_AT
        expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_hidden()
        expect(page.locator('#notificationUnread')).to_have_text('Unread: 27')
        page.locator('#notificationMarkAll').click()
        settle()
        assert len(store['writes']) == 2 and unread('recipient') == '0'
        expect(page.locator('#notificationUnread')).to_have_text('Unread: 0')
        expect(page.locator('#notificationMarkAll')).to_be_disabled()
        assert rows[2]['is_read'] and rows[3]['is_read']

        # Both lost-before and lost-after writes stop; GET and an explicit click
        # are required before any further read update. No automatic retry.
        for drop in ('before', 'after'):
            unread_first(); store['drop'] = drop
            before = len(store['writes'])
            notification().get_by_role('button', name='Mark as read', exact=True).click()
            settle()
            expect(page.locator('#notificationStatus')).to_contain_text('result is unknown')
            expect(page.locator('#notificationMarkAll')).to_be_disabled()
            expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_disabled()
            assert len(store['writes']) == before + 1 and rows[0]['is_read'] == (drop == 'after')
            refresh()
            assert len(store['writes']) == before + 1
            expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_hidden() if drop == 'after' else expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_enabled()

        # Rejected read updates keep destination buttons functional; they still
        # perform current canonical GETs while further writes require Refresh.
        unread_first(); store['reject'] = 409
        notification().get_by_role('button', name='Mark as read', exact=True).click()
        settle()
        expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_disabled()
        notification().get_by_role('button', name='Open Transfer', exact=True).click()
        settle()
        expect(page.locator('#ownershipDialog')).to_be_visible()
        page.locator('#ownershipClose').click()
        expect(page.locator('#notificationStatus')).not_to_contain_text('SECRET')
        refresh()

        # Read-only permits list pages and destinations, but no read writes.
        store['can_write'] = False
        refresh()
        expect(notification().get_by_role('button', name='Mark as read', exact=True)).to_be_disabled()
        expect(page.locator('#notificationMarkAll')).to_be_disabled()
        before = len(store['writes'])
        notification().get_by_role('button', name='Open Transfer', exact=True).click()
        settle()
        expect(page.locator('#ownershipDialog')).to_be_visible()
        expect(page.locator('#ownershipConfirm')).to_be_hidden()
        page.locator('#ownershipClose').click()
        assert len(store['writes']) == before
        store['can_write'] = True
        refresh()

        # A malformed DTO and lost service access must remove all retained rows
        # and badge values, never partially render raw or another account data.
        store['malformed'] = True
        refresh()
        expect(inbox_list.locator('li')).to_have_count(0)
        expect(page.locator('#notificationUnread')).to_be_empty()
        store['malformed'] = False
        refresh()
        for mode in ('offline', 'admin_only'):
            store['mode'] = mode
            refresh()
            expect(inbox_list.locator('li')).to_have_count(0)
            expect(page.locator('#notificationUnread')).to_be_empty()
            store['mode'] = 'normal'
            refresh()

        # Already-delivered GETs held across navigation cannot repopulate the
        # private inbox; real Back/Forward likewise never marks anything read.
        for event in ('popstate', 'pagehide'):
            page.evaluate('path=>catalogFixture.hold(path,"","late")', API)
            page.locator('#notificationRefresh').click()
            page.wait_for_function('Boolean(catalogFixture.waiting.late)')
            page.evaluate('(event)=>dispatchEvent(new Event(event))', event)
            expect(inbox_list.locator('li')).to_have_count(0)
            page.evaluate('catalogFixture.release("late")')
            settle()
            expect(inbox_list.locator('li')).to_have_count(0)
            expect(page.locator('#notificationUnread')).to_be_empty()
            refresh()
        page.evaluate("history.pushState({},'', '/account?fixture=navigation')")
        page.go_back()
        expect(inbox_list.locator('li')).to_have_count(0)
        page.go_forward()
        expect(inbox_list.locator('li')).to_have_count(0)
        refresh()

        # Mobile is the same private list, with no overflow or image/profile UI.
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(notification()).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert inbox_list.locator('img, a').count() == 0

        # Purge on the click, before the asynchronous SDK SignOut completes.
        page.evaluate('notificationFixture.holdLogout=true')
        page.locator('#signOut').click()
        page.wait_for_function('notificationFixture.waitingLogout===true')
        expect(inbox_list.locator('li')).to_have_count(0)
        expect(page.locator('#notificationUnread')).to_be_empty()
        page.evaluate('notificationFixture.releaseLogout()')
        expect(page.locator('#selfNotifications')).to_be_hidden()
        page.wait_for_function('catalogFixture.pending===0')
        sign_in('other')
        expect(inbox_list.locator('li')).to_have_count(0)
        expect(page.locator('#notificationUnread')).to_have_text('Unread: 0')
        assert not store['external'] and not errors, (store['external'], errors)
        assert all(call['path'].startswith(API + '/') for call in store['writes'])
        assert all(call['method'] == 'GET' or call['path'] == API + '/read-all' or call['path'].endswith('/read')
                   for call in store['calls'])
        assert all(request['credentials'] == 'omit' and request['cache'] == 'no-store'
                   and request['redirect'] == 'error' and request['authorization'].startswith('Bearer fixture-verified-')
                   for request in page.evaluate('notificationFixture.requests'))
        page.unroute_all(behavior='wait')
    print('Cloud notifications browser: verified recipient inbox, exact IDs/cursors/count, plaintext/null body, '
          'mark-one/all separation, supported current-access targets, stale access, duplicate/unknown writes, '
          'read-only/service modes, malformed DTO, delayed navigation, mobile and immediate SignOut passed.')


if __name__ == '__main__':
    main()
