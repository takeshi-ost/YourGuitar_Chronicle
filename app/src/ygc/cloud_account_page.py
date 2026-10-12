"""Explicit opt-in browser page for the cloud account API."""
import json
import hashlib
import mimetypes
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

STATIC = Path(__file__).with_name('static')


def public_config(web_config, *, project_id, tenant):
    if (not isinstance(web_config, dict) or set(web_config) != {'apiKey', 'authDomain'}
            or not isinstance(web_config['apiKey'], str) or not web_config['apiKey'].strip()
            or web_config['authDomain'] != project_id + '.firebaseapp.com'):
        raise ValueError('Explicit matching Identity Platform Web configuration is required.')
    return {'firebase': {**web_config, 'projectId': project_id}, 'tenant': tenant}


class VersionedAssets:
    def __init__(self, app, revision):
        self.app, self.revision = app, revision

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not path.startswith('/assets/v/'):
            return await self.app(scope, receive, send)
        prefix = '/assets/v/' + self.revision + '/'
        if not path.startswith(prefix) or scope['method'] not in ('GET', 'HEAD'):
            return await Response(status_code=404, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        scope = dict(scope, path='/assets/' + path[len(prefix):],
                     state={**scope.get('state', {}), 'ygc_asset_revision': self.revision})
        async def safe_send(message):
            if message['type'] == 'http.response.start' and message['status'] >= 400:
                message = dict(message)
                message['headers'] = [(key, value) for key, value in message.get('headers', []) if key.lower() != b'cache-control'] + [(b'cache-control', b'no-store')]
            await send(message)
        await self.app(scope, receive, safe_send)


def install(app, config):
    from ygc.localization import ui_resources
    from ygc.ui_claim_templates import ownership_presentation_script
    from ygc.ui_placeholders import NO_PICTURE_SVG, NO_ICON_SVG
    def i18n_content():
        return ('globalThis.YGCI18nResources=' + json.dumps(ui_resources(), ensure_ascii=True) + ';\n' +
                (STATIC / 'i18n.js').read_text()).encode('utf-8')
    # Freeze versioned bytes for this process. Legacy URLs still revalidate the
    # actual source bytes. Only existing allowlisted routes can serve snapshots.
    snapshots = {'/assets/' + path.relative_to(STATIC).as_posix(): path.read_bytes()
                 for path in STATIC.rglob('*') if path.is_file()}
    snapshots.update({'/assets/theme-textures/' + name: (STATIC / name).read_bytes()
                      for name in ('butterscotch-wood.webp', 'rellic-black-wood.webp', 'cherry-wood.webp', 'white-pearl.webp') if (STATIC / name).is_file()})
    snapshots.update({'/assets/i18n.js': i18n_content(),
        '/assets/ownership-presentation.js': ownership_presentation_script().encode('utf-8'),
        '/assets/no-picture.svg': NO_PICTURE_SVG.encode('utf-8'),
        '/assets/no-icon.svg': NO_ICON_SVG.encode('utf-8')})
    digest = hashlib.sha256()
    for name, content in sorted(snapshots.items()):
        digest.update(name.encode('utf-8') + b'\0' + len(content).to_bytes(8, 'big') + content)
    revision = digest.hexdigest()
    asset_prefix = '/assets/v/' + revision + '/'
    app.add_middleware(VersionedAssets, revision=revision)

    def page_response(html):
        if '/assets/themes.css' not in html:
            html = html.replace('</head>', '<link rel="stylesheet" href="/assets/themes.css"></head>', 1)
        if '/assets/overlays.js' not in html:
            html = html.replace('</head>', '<script src="/assets/overlays.js" defer></script></head>', 1)
        html = html.replace('<head>', '<head><script src="/assets/cloud-theme.js"></script><link rel="stylesheet" href="/assets/cloud-auth-dialog.css">', 1)
        return HTMLResponse(html.replace('/assets/', asset_prefix), headers={'Cache-Control': 'no-store'})

    def static_response(request, content, media_type):
        versioned = getattr(request.state, 'ygc_asset_revision', None) == revision
        if versioned:
            content = snapshots[request.url.path]
        if isinstance(content, str):
            content = content.encode('utf-8')
        if versioned and (media_type == 'text/css' or 'javascript' in media_type):
            content = content.replace(b'/assets/', asset_prefix.encode('ascii'))
        tag = '"' + hashlib.sha256(content).hexdigest() + '"'
        headers = {'Cache-Control': 'public, max-age=31536000, immutable' if versioned else 'public, no-cache, max-age=0, must-revalidate',
                   'ETag': tag, 'X-Content-Type-Options': 'nosniff'}
        condition = request.headers.get('if-none-match', '')
        if len(condition) <= 8192 and any(value.strip().removeprefix('W/') in (tag, '*') for value in condition.split(',')):
            return Response(status_code=304, headers=headers)
        return Response(content, media_type=media_type, headers=headers)

    def static_file(request, path):
        content = snapshots[request.url.path] if getattr(request.state, 'ygc_asset_revision', None) == revision else path.read_bytes()
        return static_response(request, content, mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

    @app.get('/')
    @app.get('/guitars/{individual_id}')
    def public_catalog_page(individual_id: str = None):
        # A shell contains no data and never bypasses the API service-mode gate.
        if individual_id is not None:
            from ygc.cloud_guitars import positive_id
            try:
                positive_id(individual_id)
            except ValueError:
                raise HTTPException(404, 'Guitar not found.') from None
        return page_response((STATIC / 'cloud_public_catalog_html.html').read_text(encoding='utf-8'))

    @app.get('/ui')
    @app.get('/ui/guitars/{individual_id}')
    def formal_ui_page(individual_id: str = None):
        if individual_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(individual_id)
            except ValueError:
                raise HTTPException(404, 'Guitar not found.') from None
        from ygc.ui_claim_templates import formal_page
        return page_response(formal_page('cloud_ui_html.html'))

    @app.get('/ui/settings')
    def formal_settings_page():
        # Reuse the exact canonical local Settings markup and CSS. Only its
        # transport/auth adapter, destinations and auth-specific notice differ.
        html = (STATIC / 'user_edit_html.html').read_text(encoding='utf-8')
        html = html.replace('/assets/local-auth.js', '/assets/identity-platform-auth.js')
        html = html.replace('src="/assets/pages/user-edit.js" defer', 'src="/assets/cloud-user-settings.js" type="module"')
        html = html.replace('/user-view', '/ui')
        html = html.replace("window.location.href=activeUser?'/users/'+activeUser.user.id:'/ui'", "window.location.href='/ui/profile'")
        html = html.replace('ui.display_name_is_required_other_profile_information_is_opti_099887a7', 'settings.notice')
        html = html.replace('Email and password belong to authentication and are not saved by the local dummy.', 'Email and password are managed by authentication.')
        html = html.replace('image/jpeg,image/png,image/webp,image/gif', 'image/jpeg,image/png,image/webp')
        html = html.replace('ui.12_mb_maximum_f64390ed', 'avatar.limits').replace('12 MB maximum', 'JPEG, PNG or WebP · 8 MB maximum')
        return page_response(html)

    @app.get('/assets/ownership-presentation.js')
    def ownership_presentation(request: Request):
        from ygc.ui_claim_templates import ownership_presentation_script
        content = snapshots['/assets/ownership-presentation.js'] if getattr(request.state, 'ygc_asset_revision', None) == revision else ownership_presentation_script()
        return static_response(request, content, 'application/javascript')

    @app.get('/api/themes')
    def themes():
        from ygc.theme_catalog import THEMES
        return [{'id': key, 'label': label} for key, label in THEMES]

    @app.get('/assets/pages/user-edit.css')
    def formal_settings_styles(request: Request):
        return static_file(request, STATIC / 'pages/user-edit.css')

    @app.get('/ui/profile')
    @app.get('/ui/profile/guitars/{individual_id}')
    def formal_profile_page(individual_id: str = None):
        if individual_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(individual_id)
            except ValueError:
                raise HTTPException(404, 'Guitar not found.') from None
        from ygc.ui_claim_templates import formal_page
        return page_response(formal_page('cloud_ui_profile_html.html'))

    @app.get('/assets/pages/user-view.css')
    def formal_ui_styles(request: Request):
        return static_file(request, STATIC / 'pages/user-view.css')

    @app.get('/assets/theme-textures/{filename}')
    def theme_texture(filename: str, request: Request):
        if filename not in ('butterscotch-wood.webp', 'rellic-black-wood.webp', 'cherry-wood.webp', 'white-pearl.webp'):
            raise HTTPException(404, 'Asset not found.')
        return static_file(request, STATIC / filename)

    @app.get('/assets/logos/{filename}')
    def wordmark(filename: str, request: Request):
        if filename not in ('script.png', 'block.png', 'badge.png'):
            raise HTTPException(404, 'Asset not found.') from None
        return static_file(request, STATIC / 'logos' / filename)

    @app.get('/api/auth/config')
    def configuration():
        return JSONResponse(config, headers={'Cache-Control': 'no-store'})

    @app.get('/account')
    def account_page():
        return page_response((STATIC / 'cloud_account_html.html').read_text(encoding='utf-8'))

    @app.get('/members')
    @app.get('/members/{member_id}')
    def members_page(member_id: str = None):
        if member_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(member_id)
            except ValueError:
                raise HTTPException(404, 'Member not found.') from None
        return page_response((STATIC / 'cloud_members_html.html').read_text(encoding='utf-8'))

    @app.get('/ui/members')
    @app.get('/ui/members/{member_id}')
    def formal_members_page(member_id: str = None):
        if member_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(member_id)
            except ValueError:
                raise HTTPException(404, 'Member not found.') from None
        from ygc.ui_claim_templates import formal_members_page as member_markup
        return page_response(member_markup())

    @app.get('/console')
    def console_page():
        return page_response((STATIC / 'cloud_console_html.html').read_text(encoding='utf-8'))

    @app.get('/assets/i18n.js')
    def i18n(request: Request):
        content = snapshots['/assets/i18n.js'] if getattr(request.state, 'ygc_asset_revision', None) == revision else i18n_content()
        return static_response(request, content, 'text/javascript')

    @app.get('/assets/no-picture.svg')
    def no_picture(request: Request):
        from .ui_placeholders import NO_PICTURE_SVG
        return static_response(request, NO_PICTURE_SVG, 'image/svg+xml')

    @app.get('/assets/no-icon.svg')
    def no_icon(request: Request):
        from .ui_placeholders import NO_ICON_SVG
        return static_response(request, NO_ICON_SVG, 'image/svg+xml')

    @app.get('/assets/{filename}')
    def asset(filename: str, request: Request):
        if filename in ('cloud-catalog-insights.js', 'cloud-catalog-insights.css', 'cloud-world-geometry.js'):
            return static_file(request, STATIC / filename)
        if filename not in ('cloud-notification-text.js', 'cloud-claim-votes.js', 'cloud-auth-dialog.css', 'cloud-auth-dialog.js', 'cloud-theme.js', 'cloud-detail-dispute.js', 'cloud-application-presentation.js', 'cloud-ownership-presentation.js', 'cloud-account-hub.js', 'cloud-profile-connections.js', 'cloud-detail-claim-actions.js', 'cloud-claim-presentation.js', 'cloud-user-settings.js', 'profile-list.js', 'cloud-profile-list.js', 'list-navigation.js', 'product-detail.js', 'table-columns.js', 'cloud-ui.js', 'cloud-ui.css', 'cloud-ui-profile.js', 'cloud-ui-profile.css', 'themes.css', 'sunburst-wood.webp', 'identity-platform-auth.js', 'cloud-auth-loader.js',
                            'cloud-public-catalog.js', 'cloud-public-catalog.css', 'cloud-members.js', 'cloud-member-icons.js', 'cloud-members.css',
                            'cloud-account-favorites.js', 'cloud-account-visibility.js', 'cloud-account-disputes.js', 'cloud-account-page.js', 'cloud-account-notifications.js', 'cloud-account-profile.js', 'cloud-account-guitars.js', 'cloud-owner-acquire-inbox.js', 'cloud-account-ownership.js', 'cloud-account-identity.js', 'cloud-account-applications.js', 'cloud-account-claims.js', 'cloud-account-media.js', 'cloud-account-avatar.js', 'cloud-account.css', 'cloud-console-page.js', 'cloud-console-applications.js', 'cloud-console-guitars.js', 'cloud-console-media.js', 'cloud-console-users.js', 'cloud-console-backups.js', 'cloud-console-crawl.js', 'cloud-console.css', 'ui-components.css', 'overlays.js'):
            raise HTTPException(404, 'Asset not found.')
        return static_file(request, STATIC / filename)
