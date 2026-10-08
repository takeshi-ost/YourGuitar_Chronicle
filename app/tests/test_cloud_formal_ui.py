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
            assert '/assets/pages/user-view.css' in r.text
            assert '/assets/local-auth.js' not in r.text
            assert '/assets/pages/user-view.js' not in r.text
        for path in ('/ui/guitars/01','/ui/guitars/9223372036854775808','/assets/logos/unknown.png',
                     '/assets/pages/user-view.js','/assets/local-auth.js','/api/local-auth/login'):
            assert client.get(path).status_code==404
        for path in ('/','/account','/members','/console','/assets/logos/script.png',
                     '/assets/logos/block.png','/assets/logos/badge.png','/assets/themes.css',
                     '/assets/sunburst-wood.webp','/assets/pages/user-view.css','/assets/cloud-ui.js'):
            assert client.get(path).status_code==200


def test_formal_self_profile_is_a_complete_shell_with_unique_controller_roots():
    import re
    app=FastAPI();install(app,{})
    with TestClient(app) as client:
        for path in ('/ui/profile','/ui/profile/guitars/9007199254741009','/ui/members','/ui/members/9007199254741009'):
            r=client.get(path)
            assert r.status_code==200 and r.headers['cache-control']=='no-store'
            assert '/assets/pages/user-view.css' in r.text and '/assets/themes.css' in r.text
            ids=re.findall(r'\bid="([^"]+)"',r.text)
            assert len(ids)==len(set(ids))
            assert '/assets/local-auth.js' not in r.text and 'viewer_id' not in r.text
        body=client.get('/ui/profile').text
        for element in ('selfProfile','selfGuitars','selfFavorites','selfVisibility','accountAvatar','selfApplications','selfClaims','selfNotifications','selfOwnership','selfDisputes','catalogDetail'):
            assert 'id="'+element+'"' in body
        assert 'data-formal-profile="true"' in body
        for path in ('/ui/profile/guitars/01','/ui/profile/guitars/9223372036854775808','/ui/members/01','/ui/members/9223372036854775808'):
            assert client.get(path).status_code==404
        for asset in ('cloud-ui-profile.js','cloud-ui-profile.css'):
            assert client.get('/assets/'+asset).status_code==200
