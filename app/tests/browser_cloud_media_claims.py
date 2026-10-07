"""Private Media Claim journeys with disposable, fully intercepted fixtures.

No live identity, cloud store, PostgreSQL, public photo, or third-party image is
used. Compile independently; execute only via an authorized Chromium runner.
The mock proves the browser contract, not server-side authorization enforcement.
"""
from copy import deepcopy
from email import policy
from email.parser import BytesParser
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from browser_cloud_account import SDK
from browser_cloud_public_catalog import HOLD_SCRIPT
from browser_diagnostics import diagnostic_page
from ygc.cloud_registration import DOCUMENTS
from ygc.localization import ui_resources

STATIC = Path(__file__).resolve().parents[1] / 'src' / 'ygc' / 'static'
BASE = 'http://ygc-media-claims-fixture.invalid'
GUITAR_ID = '9007199254740993'
OTHER_GUITAR_ID = '9007199254740995'
ROOT = '/api/auth/guitars/' + GUITAR_ID
API = ROOT + '/claims'
UPLOAD = ROOT + '/media-claims'
OWNER = ROOT + '/owner-responses'
ATTACK = '<img src=x onerror=globalThis.fixtureXss=true>'
PRIVATE = 'PRIVATE MEDIA FIXTURE ' + ATTACK

# Record object URL lifetime and the options reaching fetch after the production
# auth adapter has injected the bearer token. Blob URLs never leave this page.
AUDIT_SCRIPT = r'''
(() => {
  const audit = globalThis.mediaFixture = {created: [], revoked: [], requests: []};
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = blob => {const url = create(blob); audit.created.push(url); return url;};
  URL.revokeObjectURL = url => {audit.revoked.push(url); return revoke(url);};
  const request = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.pathname.includes('/claims/') && url.pathname.includes('/media/')) {
      audit.requests.push({url: url.href, credentials: options.credentials,
        cache: options.cache, redirect: options.redirect,
        authorization: new Headers(options.headers).get('authorization')});
    }
    return request(input, options);
  };
})();
'''


def guitar(identifier=GUITAR_ID):
    return dict(id=identifier, manufacturer='Fixture maker', model='Private media',
                finish='Sunburst', year='1965', serial_number='SERIAL-' + identifier,
                photo=None, specifications=[])


def image_bytes(kind='JPEG', size=(32, 24), color='blue'):
    stream = io.BytesIO()
    Image.new('RGB', size, color).save(stream, format=kind)
    return stream.getvalue()


def upload_file(kind='JPEG', name=None, size=(32, 24)):
    mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[kind]
    return dict(name=name or 'fixture.' + kind.lower(), mimeType=mime,
                buffer=image_bytes(kind, size))


def multipart(request):
    """Inspect exact wire fields without treating a multipart body as JSON."""
    content_type = request.headers.get('content-type', '')
    assert content_type.startswith('multipart/form-data; boundary='), content_type
    body = request.post_data_buffer
    assert body is not None
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + body)
    assert message.is_multipart()
    parts = list(message.iter_parts())
    names = [part.get_param('name', header='content-disposition') for part in parts]
    assert names.count('metadata') == 1 and set(names) == {'metadata', 'images'}, names
    metadata_part = next(part for part in parts if part.get_param('name', header='content-disposition') == 'metadata')
    assert metadata_part.get_filename() is None
    metadata = json.loads(metadata_part.get_payload(decode=True).decode('utf-8'))
    assert set(metadata) == {'claim_type', 'body', 'occurred_at'}
    assert metadata['claim_type'] == 'media'
    assert metadata['body'] is None or isinstance(metadata['body'], str)
    assert metadata['occurred_at'] is None or isinstance(metadata['occurred_at'], str)
    images = [part for part in parts if part.get_param('name', header='content-disposition') == 'images']
    assert 1 <= len(images) <= 10
    files = []
    for part in images:
        data = part.get_payload(decode=True)
        mime = part.get_content_type()
        assert mime in ('image/jpeg', 'image/png', 'image/webp')
        assert 0 < len(data) <= 8 * 1024 * 1024
        with Image.open(io.BytesIO(data)) as image:
            assert image.width * image.height <= 8_000_000
            image.verify()
        files.append(dict(name=part.get_filename(), mime=mime, data=data))
    return metadata, files


def main():
    names = ['cloud-account-page.js', 'cloud-account-ownership.js', 'cloud-account-profile.js', 'cloud-account-avatar.js',
             'cloud-account-guitars.js', 'cloud-account-applications.js', 'cloud-account-claims.js',
             'cloud-account-media.js', 'cloud-account.css', 'cloud-public-catalog.js',
             'cloud-public-catalog.css', 'cloud-auth-loader.js', 'identity-platform-auth.js',
             'overlays.js', 'ui-components.css']
    assets = {name: (STATIC / name).read_text(encoding='utf-8') for name in names}
    assets['i18n.js'] = ('globalThis.YGCI18nResources=' + json.dumps(ui_resources()) + ';\n'
                         + (STATIC / 'i18n.js').read_text(encoding='utf-8'))
    account_html = (STATIC / 'cloud_account_html.html').read_text(encoding='utf-8')
    public_html = (STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8')
    store = dict(rows=[], calls=[], writes=[], decisions=[], external=[], revision=0,
                 can_write=True, own_read_error=None, write_restricted_once=False,
                 drop_before_commit=False, drop_after_commit=False, media_failures={},
                 corrupt_media=False, change_owner_revision_once=False, owner_rows=[])
    normalized_image = image_bytes()
    errors = []

    def revision():
        store['revision'] += 1
        return format(store['revision'], '064x')

    def media_row(identifier, media_ids, **extra):
        row = dict(id=identifier, individual_id=GUITAR_ID, claim_type='media', body=PRIVATE,
                   occurred_at='2026-01-01', status='active', verification_status='unverified',
                   field_name=None, value_text=None, specification_kind=None, incident_kind=None,
                   ownership_kind=None, spec_items=[], created_at='2026-01-01T12:00:00Z',
                   updated_at='2026-01-01T12:00:00Z', revision=revision(),
                   media_items=[dict(id=asset, mime_type='image/jpeg') for asset in media_ids])
        row.update(extra)
        return row

    def media_path(row, index=0):
        return API + '/' + row['id'] + '/media/' + row['media_items'][index]['id']

    with sync_playwright() as playwright, diagnostic_page(playwright, 'browser_cloud_media_claims') as page:
        page.add_init_script(HOLD_SCRIPT + AUDIT_SCRIPT)
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
            call = dict(method=method, path=path, params=parse_qs(parsed.query),
                        authorization=request.headers.get('authorization'), body=None)
            if method in ('POST', 'PATCH'):
                if path == UPLOAD:
                    call['body'], call['files'] = multipart(request)
                else:
                    call['body'] = request.post_data_json
            store['calls'].append(call)

            def private():
                assert call['authorization'] == 'Bearer fixture-verified-media@example.invalid', call

            if path == '/api/auth/config':
                route.fulfill(json={'firebase': {'apiKey': 'fixture', 'authDomain': 'fixture.firebaseapp.com',
                                                'projectId': 'fixture'}, 'tenant': ''})
            elif path == '/api/auth/registration':
                route.fulfill(json={'documents': DOCUMENTS})
            elif path == '/api/auth/me':
                assert call['authorization']
                route.fulfill(json={'user': {'id': '1', 'app_user_id': 'fixture-media-owner',
                    'display_name': 'Media Fixture', 'account_type': 'user', 'role': 'member', 'status': 'active'},
                    'identity': {'email_verified': 'fixture-verified-' in call['authorization']}})
            elif path == '/api/auth/profile':
                private()
                route.fulfill(json={'profile_revision': '1', 'fields': {'display_name': 'Media Fixture',
                    'location_country': '', 'location_region': '', 'bio': ''}})
            elif path == '/api/auth/guitars':
                private()
                rows = [guitar()] if call['params'].get('kind') == ['owned'] else []
                route.fulfill(json={'items': rows, 'total': str(len(rows)), 'next_after': None})
            elif path == '/api/auth/ownership-transfers':
                route.fulfill(json={'viewer_user_id': '1', 'items': [], 'can_write': store['can_write'], 'next_after': None})
            elif path == '/api/auth/applications':
                private()
                route.fulfill(json={'items': [], 'can_write': store['can_write']})
            elif path == '/api/auth/avatar':
                private()
                route.fulfill(status=404, json={'detail': 'No fixture avatar'})
            elif path == '/api/service/status':
                route.fulfill(json={'mode': 'normal', 'message': ''})
            elif path == '/api/public/guitars':
                route.fulfill(json={'items': [guitar()], 'total': '1', 'page': 1, 'page_size': 24, 'total_pages': 1})
            elif path.startswith('/api/public/guitars/'):
                identifier = path.split('/')[4]
                route.fulfill(json={'items': [], 'next_after': None} if path.endswith('/chronicle') else guitar(identifier))
            elif re.fullmatch(r'/api/auth/guitars/[1-9][0-9]*/claims', path) and method == 'GET':
                private()
                if store['own_read_error']:
                    route.fulfill(status=store['own_read_error'], json={'detail': 'Private read denied'})
                    return
                identifier = path.split('/')[4]
                route.fulfill(json={'individual': guitar(identifier), 'items': deepcopy(store['rows'])
                                    if identifier == GUITAR_ID else [], 'can_write': store['can_write'], 'next_after': None})
            elif re.fullmatch(re.escape(API) + r'/[1-9][0-9]*/media/[1-9][0-9]*', path) and method == 'GET':
                private()
                assert request.resource_type == 'fetch', 'Never send an img element to the authenticated endpoint'
                assert set(call['params']) == {'revision'}
                assert len(call['params']['revision']) == 1
                assert re.fullmatch(r'[a-f0-9]{64}', call['params']['revision'][0])
                claim_id, asset_id = path.split('/')[6], path.split('/')[8]
                row = next(row for row in store['rows'] + store['owner_rows'] if row['id'] == claim_id)
                assert asset_id in [item['id'] for item in row['media_items']]
                if store['change_owner_revision_once'] and claim_id == '71':
                    store['change_owner_revision_once'] = False
                    row.update(revision=revision(), body='UPDATED OWNER MEDIA')
                failure = store['media_failures'].get(asset_id)
                if failure or call['params']['revision'] != [row['revision']]:
                    route.fulfill(status=failure or 409, json={'detail': {'code': 'claim_conflict'}})
                elif store['corrupt_media']:
                    route.fulfill(content_type='image/jpeg', body=b'not-an-image')
                else:
                    route.fulfill(content_type='image/jpeg', body=normalized_image,
                                  headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
            elif path == OWNER and method == 'GET':
                private()
                route.fulfill(json={'items': deepcopy(store['owner_rows']), 'can_write': store['can_write']})
            elif path.startswith(OWNER + '/') and method == 'POST':
                private()
                assert store['can_write']
                row = next(row for row in store['owner_rows'] if row['id'] == path.rsplit('/', 1)[-1])
                assert call['body']['revision'] == row['revision']
                assert set(call['body']) == {'revision', 'stance'}
                store['decisions'].append(call)
                row.update(verification_status=call['body']['stance'], revision=revision())
                route.fulfill(json={'claim_id': row['id'], 'verification_status': row['verification_status']})
            elif path == UPLOAD and method == 'POST' or path.startswith(API + '/') and method in ('POST', 'PATCH'):
                private()
                assert request.headers.get('x-ygc-timezone')
                store['writes'].append(call)
                if store['write_restricted_once'] or not store['can_write']:
                    store.update(write_restricted_once=False, can_write=False)
                    route.fulfill(status=403, json={'detail': {'code': 'service_restricted'}})
                    return
                if store['drop_before_commit']:
                    store['drop_before_commit'] = False
                    route.abort()
                    return
                if path == UPLOAD:
                    identifier = str(100 + len(store['rows']))
                    row = media_row(identifier, [str(1000 + len(store['rows']) * 10 + i)
                                                 for i in range(len(call['files']))], **call['body'])
                    store['rows'].insert(0, row)
                else:
                    row = next(row for row in store['rows'] if row['id'] == path.split('/')[6])
                    if call['body']['revision'] != row['revision']:
                        route.fulfill(status=409, json={'detail': {'code': 'claim_conflict'}})
                        return
                    if path.endswith('/deactivate'):
                        assert method == 'POST' and set(call['body']) == {'revision'}
                        row['status'] = 'inactive'
                    else:
                        assert method == 'PATCH'
                        assert set(call['body']) == {'claim_type', 'body', 'occurred_at', 'revision'}
                        assert call['body']['claim_type'] == 'media'
                        row.update({key: value for key, value in call['body'].items() if key != 'revision'})
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
        page.goto(BASE + '/account?claim=' + GUITAR_ID)
        page.wait_for_function('globalThis.YGCCloudAccountReady === true')
        dialog = page.locator('#claimDialog')
        media_input = page.locator('#claimMediaInput')
        photos = page.locator('#claimMediaPhotos img')

        def settle():
            page.wait_for_function('catalogFixture.pending === 0')
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

        def hold(path, name):
            page.evaluate('([path, name]) => catalogFixture.hold(path, "", name)', [path, name])

        def waiting(name):
            page.wait_for_function('name => typeof catalogFixture.waiting[name] === "function"', arg=name)

        def release(name):
            page.evaluate('name => catalogFixture.release(name)', name)
            settle()

        def no_blobs():
            page.wait_for_function('mediaFixture.created.every(url => mediaFixture.revoked.includes(url))')

        def ready_images(locator, count, selector='#claimMediaPhotos img'):
            expect(locator).to_have_count(count)
            locator.first.wait_for(state='visible')
            page.wait_for_function('selector => [...document.querySelectorAll(selector)].every(image => '
                                   'image.src.startsWith("blob:") && image.complete && image.naturalWidth > 0)',
                                   arg=selector)

        def start(files=None):
            expect(page.locator('#catalogClaimStart')).to_be_enabled()
            page.locator('#catalogClaimStart').click()
            page.locator('#claimKind').select_option('media')
            expect(media_input).to_be_visible()
            expect(page.locator('#claimSave')).to_be_disabled()
            if files:
                media_input.set_input_files(files)
                ready_images(photos, len(files))
                expect(page.locator('#claimSave')).to_be_enabled()

        def mutate(method, path, *, button='#claimSave', status=200, message='Claim saved.'):
            # Existing saved text and photos can still be visible during the
            # next preflight. Bind completion to this exact network mutation,
            # then wait for its production work (including list refresh) to end.
            before = len(store['writes'])
            with page.expect_response(lambda response: response.request.method == method
                    and urlsplit(response.url).path == path) as response:
                page.locator(button).click()
            result = response.value
            result.finished()
            assert result.status == status
            expect(page.locator('#signOut')).to_be_enabled()
            if message is not None:
                expect(page.locator('#claimMessage')).to_have_text(message)
            assert len(store['writes']) == before + 1
            assert store['writes'][-1]['method'] == method and store['writes'][-1]['path'] == path
            return result.json()

        def refresh_claims():
            # Disabled Add/Save also means merely busy, so it cannot establish
            # that a mode change was read before opening another Claim.
            with page.expect_response(lambda response: response.request.method == 'GET'
                    and urlsplit(response.url).path == API) as response:
                page.locator('#claimsRefresh').click()
            response.value.finished()
            assert response.value.status == 200
            expect(page.locator('#signOut')).to_be_enabled()

        def own(identifier, visible=True):
            page.locator('#claimsList li').filter(has_text=re.compile(r'^#' + identifier + r' ·')).get_by_role('button').click()
            if visible:
                expect(dialog).to_be_visible()

        def close():
            page.locator('#claimClose').click()
            expect(dialog).to_be_hidden()
            expect(photos).to_have_count(0)
            expect(media_input).to_have_value('')
            no_blobs()
            assert page.evaluate('document.body.style.overflow') != 'hidden'

        # An anonymous/unverified page never requests private claims or photos.
        expect(page.locator('#catalogClaimStart')).to_be_disabled()
        page.locator('#email').fill('media@example.invalid')
        page.locator('#password').fill('fixture-password')
        page.locator('#submit').click()
        expect(page.locator('#catalogClaimStatus')).to_contain_text('Verify your email')
        assert not any(call['path'] == API or '/media/' in call['path'] for call in store['calls'])
        page.evaluate("sessionStorage.setItem('verified-media@example.invalid', 'true')")
        page.locator('#refreshVerification').click()
        expect(page.locator('#catalogClaimStart')).to_be_enabled()
        owner_dialog = page.locator('#ownerResponseDialog')
        owner_photos = owner_dialog.locator('section img')

        # Reject invalid local selections before any multipart request is made.
        for files in (
            [upload_file('PNG', name=str(index) + '.png') for index in range(11)],
            [dict(name='unsupported.gif', mimeType='image/gif', buffer=b'GIF89a')],
            [dict(name='large.jpg', mimeType='image/jpeg', buffer=b'x' * (8 * 1024 * 1024 + 1))],
            [dict(name=str(index) + '.jpg', mimeType='image/jpeg', buffer=b'x' * (6 * 1024 * 1024 + 1))
             for index in range(4)],
            [upload_file('PNG', name='too-many-pixels.png', size=(3000, 3000))],
        ):
            start()
            media_input.set_input_files(files)
            expect(page.locator('#claimMediaMessage')).to_contain_text('Choose 1–10')
            expect(page.locator('#claimSave')).to_be_disabled()
            expect(photos).to_have_count(0)
            assert not store['writes']
            close()

        # Local JPEG/PNG/WebP previews remain local; saving sends only exact
        # metadata plus the original image bytes, then renders private JPEGs.
        files = [upload_file('JPEG'), upload_file('PNG'), upload_file('WEBP')]
        start(files)
        assert not any('/media/' in call['path'] for call in store['calls'])
        page.locator('#claimBody').fill(PRIVATE)
        page.locator('#claimDate').fill('2026-01-03')
        mutate('POST', UPLOAD)
        ready_images(photos, 3)
        assert len(store['writes']) == 1 and store['writes'][0]['path'] == UPLOAD
        assert store['writes'][0]['body'] == dict(claim_type='media', body=PRIVATE, occurred_at='2026-01-03')
        assert [item['data'] for item in store['writes'][0]['files']] == [item['buffer'] for item in files]
        first_id = store['rows'][0]['id']
        first_media = deepcopy(store['rows'][0]['media_items'])
        expect(page.locator('#claimKind')).to_be_disabled()
        expect(media_input).to_be_hidden()
        expect(media_input).to_have_value('')
        expect(page.locator('#claimSavedState')).to_contain_text(PRIVATE)
        assert page.evaluate('globalThis.fixtureXss || false') is False

        # Edits preserve photo identity and clear optional body/date with null.
        page.locator('#claimBody').fill('')
        page.locator('#claimDate').fill('')
        edited = mutate('PATCH', API + '/' + first_id)
        assert edited['claim']['revision'] != store['writes'][-1]['body']['revision']
        ready_images(photos, 3)
        assert store['writes'][-1]['method'] == 'PATCH'
        assert store['writes'][-1]['body']['body'] is None
        assert store['writes'][-1]['body']['occurred_at'] is None
        assert store['rows'][0]['media_items'] == first_media
        close()

        # Photos alone are valid: creation also sends optional text/date as null.
        start([files[0]])
        page.locator('#claimDate').fill('')
        mutate('POST', UPLOAD)
        assert store['writes'][-1]['body'] == dict(claim_type='media', body=None, occurred_at=None)
        ready_images(photos, 1)
        close()

        # An uncertain upload retains actual File objects. Neither Save nor
        # list reconciliation resends; retry requires a separate user decision.
        for committed in (False, True):
            start([files[1]])
            text = 'LOST UPLOAD RESPONSE ' + str(committed)
            page.locator('#claimBody').fill(text)
            before, rows_before = len(store['writes']), len(store['rows'])
            store['drop_after_commit' if committed else 'drop_before_commit'] = True
            page.locator('#claimSave').click()
            expect(page.locator('#claimMessage')).to_contain_text('Could not confirm')
            expect(page.locator('#claimSave')).to_be_disabled()
            assert media_input.evaluate('input => input.files.length') == 1
            expect(page.locator('#claimBody')).to_have_value(text)
            expect(page.locator('#claimRetryCreate')).to_be_hidden()
            page.locator('#claimCheckSubmission').click()
            expect(page.locator('#claimRetryCreate')).to_be_visible()
            expect(page.locator('#claimSave')).to_be_disabled()
            assert len(store['writes']) == before + 1
            assert media_input.evaluate('input => input.files[0].name') == files[1]['name']
            if committed:
                expect(page.locator('#claimUncertainResults')).to_contain_text(text)
            else:
                expect(page.locator('#claimUncertainResults')).not_to_contain_text(text)
                page.locator('#claimRetryCreate').click()
                expect(page.locator('#claimSave')).to_be_enabled()
                assert len(store['writes']) == before + 1
                mutate('POST', UPLOAD)
                assert len(store['writes']) == before + 2
            assert len(store['rows']) == rows_before + 1
            close()

        # Read-only still permits authorized image viewing. A write-only
        # maintenance denial revalidates read access and preserves private rows.
        store['can_write'] = False
        refresh_claims()
        expect(page.locator('#catalogClaimStart')).to_be_disabled()
        own(first_id)
        ready_images(photos, 3)
        expect(page.locator('#claimSave')).to_be_disabled()
        expect(page.locator('#claimDeactivate')).to_be_disabled()
        close()
        store['can_write'] = True
        refresh_claims()
        expect(page.locator('#catalogClaimStart')).to_be_enabled()
        own(first_id)
        ready_images(photos, 3)
        page.locator('#claimBody').fill('READ-ONLY RECOVERY')
        store['write_restricted_once'] = True
        mutate('PATCH', API + '/' + first_id, status=403, message=None)
        expect(page.locator('#claimMessage')).to_contain_text('The service mode changed.')
        expect(page.locator('#claimSave')).to_be_disabled()
        expect(page.locator('#claimBody')).to_have_value('READ-ONLY RECOVERY')
        expect(page.locator('#claimsList li')).to_have_count(len(store['rows']))
        expect(page.locator('#accountSummary')).to_be_visible()
        close()
        store['can_write'] = True
        refresh_claims()
        expect(page.locator('#catalogClaimStart')).to_be_enabled()

        # Mobile dismissal, navigation, Back and Forward invalidate preflight
        # continuations before POST, revoke previews, and release scroll locks.
        page.set_viewport_size({'width': 390, 'height': 844})
        for dismissal in ('escape', 'navigation', 'back', 'forward'):
            if dismissal == 'back':
                page.evaluate("history.pushState({}, '', '/account?claim=' + " + json.dumps(OTHER_GUITAR_ID)
                              + "); history.pushState({}, '', '/account?claim=' + " + json.dumps(GUITAR_ID) + ")")
            if dismissal == 'forward':
                page.evaluate("history.pushState({}, '', '/account?claim=' + " + json.dumps(OTHER_GUITAR_ID) + "); history.back()")
                page.wait_for_url(BASE + '/account?claim=' + GUITAR_ID)
                expect(page.locator('#catalogClaimDetail')).to_contain_text(GUITAR_ID)
            start([files[0]])
            assert dialog.evaluate('element => element.scrollWidth <= element.clientWidth + 1')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            before = len(store['writes'])
            hold(API, 'preflight')
            page.locator('#claimSave').click()
            waiting('preflight')
            if dismissal == 'escape':
                page.keyboard.press('Escape')
            elif dismissal == 'navigation':
                page.evaluate("history.pushState({}, '', '/account?claim=' + " + json.dumps(OTHER_GUITAR_ID)
                              + "); dispatchEvent(new PopStateEvent('popstate'))")
            elif dismissal == 'back':
                page.evaluate("history.back()")
            else:
                page.evaluate("history.forward()")
            expect(dialog).to_be_hidden()
            release('preflight')
            assert len(store['writes']) == before
            no_blobs()
            assert page.evaluate('document.body.style.overflow') != 'hidden'
            page.evaluate("history.pushState({}, '', '/account?claim=' + " + json.dumps(GUITAR_ID)
                          + "); dispatchEvent(new PopStateEvent('popstate'))")
            expect(page.locator('#catalogClaimStart')).to_be_enabled()
        page.set_viewport_size({'width': 1440, 'height': 1000})

        # A dismissed private image fetch must not revive photos in a different
        # draft; a 403 cannot be retried through an anonymous/public image URL.
        first_row = next(row for row in store['rows'] if row['id'] == first_id)
        hold(media_path(first_row), 'old-photo')
        own(first_id)
        waiting('old-photo')
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()
        start()
        release('old-photo')
        expect(photos).to_have_count(0)
        expect(media_input).to_have_value('')
        no_blobs()
        close()
        store['media_failures'][first_media[0]['id']] = 403
        own(first_id, visible=False)
        expect(dialog).to_be_hidden()
        settle()
        expect(photos).to_have_count(0)
        no_blobs()
        store['media_failures'].clear()
        expect(page.locator('#claimsList li')).to_have_count(len(store['rows']))
        # Successful HTTP alone cannot make invalid bytes into a private photo.
        store['corrupt_media'] = True
        own(first_id)
        expect(page.locator('#claimMediaReload')).to_be_visible()
        expect(photos).to_have_count(0)
        no_blobs()
        store['corrupt_media'] = False
        page.locator('#claimMediaReload').click()
        ready_images(photos, 3)
        close()

        # Owner review never exposes self-review. All image fetches must finish
        # before any third-party decision control is enabled.
        store['owner_rows'] = [media_row('71', ['701', '702'], author_user_id='2',
                                        author_name='Other contributor', decline_reason_required=False)]
        owner_row = store['owner_rows'][0]
        owner_start = page.locator('#selfGuitars_owned').get_by_role('button', name='Review owner responses', exact=True)

        def open_owner():
            expect(owner_start).to_be_enabled()
            owner_start.click()
            expect(owner_dialog).to_be_visible()
            expect(owner_dialog.locator('section')).to_have_count(1)
            expect(owner_photos).to_have_count(0)
            owner_dialog.get_by_role('button', name='View photos', exact=True).click()

        def close_owner():
            owner_dialog.get_by_role('button', name='Close', exact=True).click()
            expect(owner_dialog).to_be_hidden()
            expect(owner_photos).to_have_count(0)
            no_blobs()

        hold(media_path(owner_row), 'owner-photo')
        open_owner()
        waiting('owner-photo')
        expect(owner_dialog.get_by_role('combobox')).to_be_disabled()
        expect(owner_dialog.get_by_role('button', name='Review decision', exact=True)).to_be_disabled()
        assert not store['decisions']
        release('owner-photo')
        ready_images(owner_photos, 2, '#ownerResponseDialog section img')
        expect(owner_dialog.get_by_role('combobox')).to_be_enabled()
        owner_dialog.get_by_role('combobox').select_option('positive')
        owner_dialog.get_by_role('button', name='Review decision', exact=True).click()
        expect(owner_dialog.locator('[data-owner-confirm]')).to_be_visible()
        assert not store['decisions']
        owner_dialog.locator('[data-owner-confirm]').click()
        expect(owner_dialog).to_be_hidden()
        assert len(store['decisions']) == 1
        no_blobs()

        # A real revision change between list and image GET discards old photos
        # and reloads text only. Fresh images need an explicit second action.
        store['change_owner_revision_once'] = True
        open_owner()
        expect(page.locator('#ownerMediaReload')).to_be_visible()
        expect(owner_dialog).to_contain_text('UPDATED OWNER MEDIA')
        expect(owner_photos).to_have_count(0)
        expect(owner_dialog.get_by_role('combobox')).to_be_disabled()
        expect(owner_dialog.get_by_role('button', name='Review decision', exact=True)).to_be_disabled()
        no_blobs()
        page.locator('#ownerMediaReload').click()
        expect(owner_photos).to_have_count(0)
        owner_dialog.get_by_role('button', name='View photos', exact=True).click()
        ready_images(owner_photos, 2, '#ownerResponseDialog section img')
        expect(owner_dialog.get_by_role('combobox')).to_be_enabled()
        assert len(store['decisions']) == 1
        close_owner()

        # Repeated image denial never enables review. Read-only preserves
        # photos while continuing to forbid writes.
        for failure in (409, 403):
            store['media_failures']['701'] = failure
            open_owner()
            settle()
            expect(owner_dialog.get_by_role('combobox')).to_be_disabled()
            expect(owner_dialog.get_by_role('button', name='Review decision', exact=True)).to_be_disabled()
            assert len(store['decisions']) == 1
            close_owner()
        store['media_failures'].clear()
        store['can_write'] = False
        open_owner()
        ready_images(owner_photos, 2, '#ownerResponseDialog section img')
        expect(owner_dialog.get_by_role('combobox')).to_be_disabled()
        expect(owner_dialog.get_by_role('button', name='Review decision', exact=True)).to_be_disabled()
        close_owner()
        store['can_write'] = True

        # Late owner images cannot repopulate a closed/reopened dialog.
        hold(media_path(owner_row), 'old-owner-photo')
        open_owner()
        waiting('old-owner-photo')
        page.keyboard.press('Escape')
        expect(owner_dialog).to_be_hidden()
        open_owner()
        ready_images(owner_photos, 2, '#ownerResponseDialog section img')
        urls = owner_photos.evaluate_all('images => images.map(image => image.src)')
        release('old-owner-photo')
        assert owner_photos.evaluate_all('images => images.map(image => image.src)') == urls
        close_owner()

        # An unpaginated Owner list never starts image downloads by itself.
        # Selecting one Claim discards the earlier photos and its confirmation.
        store['owner_rows'] = [media_row(str(800 + index), [str(8000 + index)],
                                        author_name='Fixture contributor', decline_reason_required=False)
                               for index in range(30)]
        before_photos = len([call for call in store['calls'] if '/media/' in call['path']])
        owner_start.click()
        cards = owner_dialog.locator('section')
        expect(cards).to_have_count(30)
        settle()
        expect(owner_photos).to_have_count(0)
        assert len([call for call in store['calls'] if '/media/' in call['path']]) == before_photos
        cards.nth(0).get_by_role('button', name='View photos', exact=True).click()
        ready_images(owner_photos, 1, '#ownerResponseDialog section img')
        first_urls = owner_photos.evaluate_all('images => images.map(image => image.src)')
        cards.nth(0).get_by_role('button', name='Review decision', exact=True).click()
        expect(cards.nth(0).locator('[data-owner-confirm]')).to_be_visible()
        cards.nth(1).get_by_role('button', name='View photos', exact=True).click()
        ready_images(owner_photos, 1, '#ownerResponseDialog section img')
        expect(cards.nth(0).locator('img')).to_have_count(0)
        expect(cards.nth(0).locator('[data-owner-confirm]')).to_be_hidden()
        expect(cards.nth(0).get_by_role('button', name='Review decision', exact=True)).to_be_disabled()
        assert page.evaluate('urls => urls.every(url => mediaFixture.revoked.includes(url))', first_urls)
        assert len([call for call in store['calls'] if '/media/' in call['path']]) == before_photos + 2
        close_owner()

        # Deactivation remains a two-step edit with the current revision; media
        # identity stays immutable, and the inactive Claim remains visible.
        own(first_id)
        ready_images(photos, 3)
        before = len(store['writes'])
        page.locator('#claimDeactivate').click()
        assert len(store['writes']) == before
        mutate('POST', API + '/' + first_id + '/deactivate', button='#claimDeactivate',
               message='Claim deactivated. Its history is retained.')
        expect(page.locator('#claimSave')).to_be_disabled()
        assert store['writes'][-1]['path'] == API + '/' + first_id + '/deactivate'
        assert next(row for row in store['rows'] if row['id'] == first_id)['media_items'] == first_media
        close()
        expect(page.locator('#claimsList')).to_contain_text('Inactive')

        # Sign-out while an already-received photo is held purges every private
        # value and URL. Releasing the old continuation must not restore them.
        hold(media_path(first_row), 'logout-photo')
        own(first_id)
        waiting('logout-photo')
        page.keyboard.press('Escape')
        expect(page.locator('#signOut')).to_be_enabled()
        page.locator('#signOut').click()
        expect(page.locator('#selfClaims')).to_be_hidden()
        expect(page.locator('#claimsList li')).to_have_count(0)
        release('logout-photo')
        expect(photos).to_have_count(0)
        expect(owner_photos).to_have_count(0)
        expect(page.locator('#claimBody')).to_have_value('')
        expect(media_input).to_have_value('')
        no_blobs()

        for request in page.evaluate('mediaFixture.requests'):
            assert request['credentials'] == 'omit' and request['cache'] == 'no-store'
            assert request['redirect'] == 'error'
            assert request['authorization'] == 'Bearer fixture-verified-media@example.invalid'
        private_reads = len([call for call in store['calls'] if '/media/' in call['path']])
        page.goto(BASE + '/guitars/' + GUITAR_ID)
        page.wait_for_function('globalThis.YGCCloudPublicCatalogReady === true')
        expect(page.locator('body')).not_to_contain_text(PRIVATE)
        assert len([call for call in store['calls'] if '/media/' in call['path']]) == private_reads
        assert not any('/public/' in call['path'] and '/media/' in call['path'] for call in store['calls'])
        assert not store['external'], store['external']
        assert not errors, errors


if __name__ == '__main__':
    main()
