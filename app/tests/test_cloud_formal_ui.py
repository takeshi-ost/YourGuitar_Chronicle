import re
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ygc.cloud_account_page import install


def test_formal_entry_preserves_existing_pages_and_asset_boundary():
    app=FastAPI()
    install(app,{})
    with TestClient(app) as client:
        for path in ('/ui','/ui/guitars/9007199254741009'):
            r=client.get(path)
            assert r.status_code==200 and r.headers['cache-control']=='no-store'
            assert 'data-catalog-autostart="false"' in r.text
            assert '/assets/pages/user-view.css' in re.sub(r'/assets/v/[0-9a-f]{64}/', '/assets/', r.text)
            assert '/assets/local-auth.js' not in r.text
            assert '/assets/pages/user-view.js' not in r.text
        for path in ('/ui/guitars/01','/ui/guitars/9223372036854775808','/assets/logos/unknown.png',
                     '/assets/pages/user-view.js','/assets/local-auth.js','/api/local-auth/login'):
            assert client.get(path).status_code==404
        for path in ('/','/account','/members','/console','/assets/logos/script.png',
                     '/assets/logos/block.png','/assets/logos/badge.png','/assets/themes.css',
                     '/assets/sunburst-wood.webp','/assets/pages/user-view.css','/assets/cloud-ui.js',
                     '/assets/cloud-catalog-insights.js','/assets/cloud-catalog-insights.css','/assets/cloud-world-geometry.js'):
            assert client.get(path).status_code==200


def test_formal_self_profile_is_a_complete_shell_with_unique_controller_roots():
    import re
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        for path in ('/ui/profile','/ui/profile/guitars/9007199254741009','/ui/members','/ui/members/9007199254741009'):
            r=client.get(path)
            assert r.status_code==200 and r.headers['cache-control']=='no-store'
            assert '/assets/pages/user-view.css' in re.sub(r'/assets/v/[0-9a-f]{64}/', '/assets/', r.text) and '/assets/themes.css' in re.sub(r'/assets/v/[0-9a-f]{64}/', '/assets/', r.text)
            ids=re.findall(r'\bid="([^"]+)"',r.text)
            assert len(ids)==len(set(ids))
            assert '/assets/local-auth.js' not in r.text and 'viewer_id' not in r.text
        body=client.get('/ui/profile').text
        for element in ('selfProfile','selfGuitars','selfFavorites','selfVisibility','accountAvatar','selfApplications','selfClaims','selfNotifications','selfOwnership','selfDisputes','catalogDetail'):
            assert 'id="'+element+'"' in body
        assert 'data-formal-profile="true"' in body
        assert 'id="authActions" hidden' in body and 'id="cloudAccountForm" hidden' in body
        for path in ('/ui/profile/guitars/01','/ui/profile/guitars/9223372036854775808','/ui/members/01','/ui/members/9223372036854775808'):
            assert client.get(path).status_code==404
        for asset in ('cloud-ui-profile.js','cloud-ui-profile.css'):
            assert client.get('/assets/'+asset).status_code==200


def test_shared_static_assets_revalidate_and_shells_config_remain_uncached():
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        for path in ('/assets/cloud-public-catalog.js','/assets/themes.css','/assets/i18n.js','/assets/ownership-presentation.js','/assets/pages/user-view.css','/assets/pages/user-edit.css','/assets/logos/script.png','/assets/no-icon.svg','/assets/no-picture.svg'):
            first=client.get(path);assert first.status_code==200
            assert first.headers['cache-control']=='public, no-cache, max-age=0, must-revalidate'
            second=client.get(path,headers={'If-None-Match':first.headers['etag']})
            assert second.status_code==304 and second.content==b''
            assert client.get(path,headers={'If-None-Match':'"old-content"'}).status_code==200
        for path in ('/ui','/ui/profile','/ui/members','/account','/console','/api/auth/config'):
            response=client.get(path,headers={'If-None-Match':'*'})
            assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert client.get('/assets/local-auth.js',headers={'If-None-Match':'*'}).status_code==404


def test_static_etag_changes_with_actual_bytes_even_if_size_does_not_change(tmp_path,monkeypatch):
    from ygc import cloud_account_page
    (tmp_path/'i18n.js').write_bytes((cloud_account_page.STATIC/'i18n.js').read_bytes())
    path=tmp_path/'themes.css';path.write_text('body{color:red}')
    monkeypatch.setattr(cloud_account_page,'STATIC',tmp_path)
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        first=client.get('/assets/themes.css');path.write_text('body{color:tan}')
        second=client.get('/assets/themes.css',headers={'If-None-Match':first.headers['etag']})
        assert second.status_code==200 and second.headers['etag']!=first.headers['etag'] and second.text=='body{color:tan}'


def test_versioned_assets_are_frozen_immutable_and_preserve_route_allowlist():
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        body=client.get('/ui').text
        prefix=re.search(r'/assets/v/[0-9a-f]{64}/',body).group()
        for path in ['/ui/profile','/ui/settings','/ui/members','/account','/console','/']:
            shell=client.get(path);assert prefix in shell.text;assert shell.headers['cache-control']=='no-store'
        for path in ['cloud-ui.js','cloud-public-catalog.js','cloud-ui-profile.js','themes.css','pages/user-view.css','i18n.js','ownership-presentation.js','logos/script.png','no-icon.svg']:
            first=client.get(prefix+path);assert first.status_code==200
            assert first.headers['cache-control']=='public, max-age=31536000, immutable'
            assert client.get(prefix+path,headers={'If-None-Match':first.headers['etag']}).status_code==304
        source=client.get(prefix+'cloud-ui.js').text
        assert "from './cloud-public-catalog.js'" in source # Relative modules inherit the same version directory.
        assert '/assets/no-icon.svg' not in client.get(prefix+'cloud-account-hub.js').text
        for path in ['local-auth.js','pages/user-view.js','cloud_ui_html.html','%2e%2e/%2e%2e/api/auth/config','does-not-exist.js']:
            response=client.get(prefix+path);assert response.status_code==404;assert response.headers['cache-control']=='no-store'
        response=client.get('/assets/v/'+'0'*64+'/cloud-ui.js')
        assert response.status_code==404 and response.headers['cache-control']=='no-store'


def test_version_fingerprint_changes_and_old_version_cannot_serve_new_bytes(tmp_path,monkeypatch):
    from ygc import cloud_account_page
    (tmp_path/'i18n.js').write_bytes((cloud_account_page.STATIC/'i18n.js').read_bytes())
    (tmp_path/'cloud_ui_html.html').write_text('<script src="/assets/cloud-ui.js"></script>')
    file=tmp_path/'cloud-ui.js';file.write_text('export const version=1;')
    monkeypatch.setattr(cloud_account_page,'STATIC',tmp_path)
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        # Use the legacy public page with a fixture shell, no generated templates.
        (tmp_path/'cloud_public_catalog_html.html').write_text('<script src="/assets/cloud-ui.js"></script>')
        prefix=re.search(r'/assets/v/[0-9a-f]{64}/',client.get('/').text).group()
        first=client.get(prefix+'cloud-ui.js');file.write_text('export const version=2;')
        assert client.get(prefix+'cloud-ui.js').content==first.content
        assert client.get('/assets/cloud-ui.js').content!=first.content
    newer=FastAPI();install(newer,{})
    with TestClient(newer) as client:
        new_prefix=re.search(r'/assets/v/[0-9a-f]{64}/',client.get('/').text).group()
        assert new_prefix!=prefix
        assert client.get(prefix+'cloud-ui.js').status_code==404
        assert client.get(new_prefix+'cloud-ui.js').text=='export const version=2;'


def test_versioned_formal_module_graph_resolves_inside_same_allowlisted_revision():
    from urllib.parse import urljoin
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        prefix=re.search(r'/assets/v/[0-9a-f]{64}/',client.get('/ui').text).group()
        todo=[prefix+name for name in ['cloud-ui.js','cloud-ui-profile.js','cloud-members.js','cloud-console-page.js','cloud-user-settings.js']]
        seen=set()
        while todo:
            path=todo.pop()
            if path in seen:continue
            seen.add(path)
            response=client.get(path)
            assert response.status_code==200,(path,response.text)
            assert response.headers['cache-control']=='public, max-age=31536000, immutable'
            imports=re.findall(r"(?:from\s+|import\s*\(\s*|import\s+)['\"]([^'\"\n]+)",response.text)
            for target in imports:
                if target.startswith(('./','../','/assets/')):
                    resolved=urljoin(path,target)
                    assert resolved.startswith(prefix),resolved
                    todo.append(resolved)
        assert len(seen)>25


def test_wallpapers_are_served_as_immutable_curated_images():
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        prefix=re.search(r'/assets/v/[0-9a-f]{64}/',client.get('/ui').text)[0]
        for name in ('butterscotch-wood.webp','rellic-black-wood.webp','cherry-wood.webp','white-pearl.webp'):
            response=client.get(prefix+'theme-textures/'+name)
            assert response.status_code==200 and response.headers['content-type']=='image/webp'
            assert 'immutable' in response.headers['cache-control'] and len(response.content)>100
        assert client.get(prefix+'theme-textures/unknown.webp').status_code==404
        html=client.get('/ui').text
        assert html.index('cloud-theme.js')<html.index('themes.css')
