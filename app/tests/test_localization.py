import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from ygc import localization
from ygc.web import app


def test_locale_bundle_is_public_and_default_is_english():
    with TestClient(app) as client:
        response = client.get('/assets/i18n.js')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/javascript')
        assert response.headers['cache-control'] == 'no-store'
        data = json.loads(response.text.split('=', 1)[1].split(';\n', 1)[0])
        assert data['manifest']['defaultLocale'] == 'en'
        assert [item['code'] for item in data['manifest']['languages']] == ['en', 'ja']
        assert data['catalogs']['en']['header.notifications'] == 'Notifications'
        assert data['catalogs']['ja']['header.notifications'] == '通知'
        for page in ('/', '/user-view', '/user-view/edit'):
            assert '/assets/i18n.js' in client.get(page).text


def test_static_translation_keys_exist_and_options_keep_protocol_values():
    resources = localization.ui_resources()
    english = resources['catalogs']['en']
    static = Path(localization.__file__).with_name('static')
    for path in static.glob('*.html'):
        for key in re.findall(r'data-i18n(?:-[\w-]+)?="([^"]+)"', path.read_text()):
            assert key in english, (path, key)
    assert 'value="user"' in (static / 'user_edit_html.html').read_text()
    assert 'value="electric_acoustic"' in (static / 'index_html.html').read_text()
    for text, key in localization.error_message_keys().items():
        assert english[key] == text


def test_http_errors_add_translation_key_without_changing_status_or_detail():
    with TestClient(app) as client:
        response = client.get('/assets/pages/unknown.js')
        assert response.status_code == 404
        assert response.json()['detail'] == 'Asset not found'
        key = response.json()['message_key']
        assert localization.ui_resources()['catalogs']['en'][key] == 'Asset not found'


def test_manifest_can_add_partial_rtl_dictionary(tmp_path, monkeypatch):
    manifest = {'defaultLocale': 'en', 'languages': [
        {'code': 'en', 'label': 'English', 'dir': 'ltr'},
        {'code': 'ar', 'label': 'العربية', 'dir': 'rtl'}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'en.json').write_text('{"action.close":"Close"}')
    (tmp_path / 'ar.json').write_text('{"action.close":"إغلاق"}')
    monkeypatch.setattr(localization, 'LOCALES', tmp_path)
    resources = localization.ui_resources()
    assert resources['catalogs']['ar']['action.close'] == 'إغلاق'
    manifest['languages'][1]['code'] = '../accounts'
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    import pytest
    with pytest.raises(ValueError, match='language code'):
        localization.ui_resources()


def test_japanese_draft_covers_every_key_and_keeps_placeholders():
    resources = localization.ui_resources()
    english, japanese = resources['catalogs']['en'], resources['catalogs']['ja']
    assert set(english) == set(japanese)
    for key, original in english.items():
        translated = japanese[key]
        assert type(original) is type(translated), key
        original_forms = original if isinstance(original, dict) else {'text': original}
        translated_forms = translated if isinstance(translated, dict) else {'text': translated}
        assert set(original_forms) == set(translated_forms), key
        for form, text in original_forms.items():
            assert translated_forms[form].strip(), (key, form)
            assert sorted(re.findall(r'\{\w+\}', text)) == sorted(re.findall(r'\{\w+\}', translated_forms[form])), (key, form)
    assert japanese['header.notifications'] == '通知'
    assert japanese['values.visibility.Private'] == '非公開'
    assert japanese['requests.updated'] == '更新：{time} / 申請 {count}件'
