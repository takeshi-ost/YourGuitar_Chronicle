from fastapi.testclient import TestClient

from ygc.web import app


def test_page_assets_are_served_without_exposing_other_files():
    with TestClient(app) as client:
        for page in ('console', 'user-view', 'user-edit'):
            for extension, content_type in (('js', 'text/javascript'), ('css', 'text/css')):
                response = client.get(f'/assets/pages/{page}.{extension}')
                assert response.status_code == 200
                assert content_type in response.headers['content-type']
                assert response.text.strip()
        for filename in ('schema.sql', 'web.py', 'unknown.js'):
            assert client.get('/assets/pages/' + filename).status_code == 404
        assert client.get('/assets/overlays.js').status_code == 200
        assert client.get('/assets/ui-components.css').status_code == 200
