"""Explicit opt-in browser page for the cloud account API."""
import json
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

STATIC = Path(__file__).with_name('static')


def public_config(web_config, *, project_id, tenant):
    if (not isinstance(web_config, dict) or set(web_config) != {'apiKey', 'authDomain'}
            or not isinstance(web_config['apiKey'], str) or not web_config['apiKey'].strip()
            or web_config['authDomain'] != project_id + '.firebaseapp.com'):
        raise ValueError('Explicit matching Identity Platform Web configuration is required.')
    return {'firebase': {**web_config, 'projectId': project_id}, 'tenant': tenant}


def install(app, config):
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
        return FileResponse(STATIC / 'cloud_public_catalog_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/ui')
    @app.get('/ui/guitars/{individual_id}')
    def formal_ui_page(individual_id: str = None):
        if individual_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(individual_id)
            except ValueError:
                raise HTTPException(404, 'Guitar not found.') from None
        return FileResponse(STATIC / 'cloud_ui_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/ui/profile')
    @app.get('/ui/profile/guitars/{individual_id}')
    def formal_profile_page(individual_id: str = None):
        if individual_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(individual_id)
            except ValueError:
                raise HTTPException(404, 'Guitar not found.') from None
        return FileResponse(STATIC / 'cloud_ui_profile_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/assets/pages/user-view.css')
    def formal_ui_styles():
        return FileResponse(STATIC / 'pages/user-view.css', headers={'Cache-Control': 'no-store'})

    @app.get('/assets/logos/{filename}')
    def wordmark(filename: str):
        if filename not in ('script.png', 'block.png', 'badge.png'):
            raise HTTPException(404, 'Asset not found.') from None
        return FileResponse(STATIC / 'logos' / filename, headers={'Cache-Control': 'no-store'})

    @app.get('/api/auth/config')
    def configuration():
        return JSONResponse(config, headers={'Cache-Control': 'no-store'})

    @app.get('/account')
    def account_page():
        return FileResponse(STATIC / 'cloud_account_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/members')
    @app.get('/members/{member_id}')
    def members_page(member_id: str = None):
        if member_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(member_id)
            except ValueError:
                raise HTTPException(404, 'Member not found.') from None
        return FileResponse(STATIC / 'cloud_members_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/ui/members')
    @app.get('/ui/members/{member_id}')
    def formal_members_page(member_id: str = None):
        if member_id is not None:
            from ygc.cloud_follow_routes import identifier
            try:
                identifier(member_id)
            except ValueError:
                raise HTTPException(404, 'Member not found.') from None
        return FileResponse(STATIC / 'cloud_ui_members_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/console')
    def console_page():
        return FileResponse(STATIC / 'cloud_console_html.html', headers={'Cache-Control': 'no-store'})

    @app.get('/assets/i18n.js')
    def i18n():
        from ygc.localization import ui_resources
        resources = json.dumps(ui_resources(), ensure_ascii=True)
        return Response('globalThis.YGCI18nResources=' + resources + ';\n' +
                        (STATIC / 'i18n.js').read_text(), media_type='text/javascript',
                        headers={'Cache-Control': 'no-store'})

    @app.get('/assets/{filename}')
    def asset(filename: str):
        if filename not in ('cloud-ui.js', 'cloud-ui.css', 'cloud-ui-profile.js', 'cloud-ui-profile.css', 'themes.css', 'sunburst-wood.webp', 'identity-platform-auth.js', 'cloud-auth-loader.js',
                            'cloud-public-catalog.js', 'cloud-public-catalog.css', 'cloud-members.js', 'cloud-member-icons.js', 'cloud-members.css',
                            'cloud-account-favorites.js', 'cloud-account-visibility.js', 'cloud-account-disputes.js', 'cloud-account-page.js', 'cloud-account-notifications.js', 'cloud-account-profile.js', 'cloud-account-guitars.js', 'cloud-account-ownership.js', 'cloud-account-identity.js', 'cloud-account-applications.js', 'cloud-account-claims.js', 'cloud-account-media.js', 'cloud-account-avatar.js', 'cloud-account.css', 'cloud-console-page.js', 'cloud-console-applications.js', 'cloud-console-guitars.js', 'cloud-console-media.js', 'cloud-console-users.js', 'cloud-console-backups.js', 'cloud-console-crawl.js', 'cloud-console.css', 'ui-components.css', 'overlays.js'):
            raise HTTPException(404, 'Asset not found.')
        return FileResponse(STATIC / filename, headers={'Cache-Control': 'no-store'})
