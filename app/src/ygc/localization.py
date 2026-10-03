"""UI locale resources; never translate stored content or authorization values."""
import json
import re
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).with_name('static') / 'locales'


@lru_cache(maxsize=1)
def error_message_keys() -> dict[str, str]:
    return json.loads((LOCALES / 'error-keys.json').read_text(encoding='utf-8'))


def ui_resources() -> dict:
    manifest = json.loads((LOCALES / 'manifest.json').read_text(encoding='utf-8'))
    catalogs = {}
    for language in manifest['languages']:
        code = language['code']
        if not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', code):
            raise ValueError('Invalid UI language code')
        if language['dir'] not in ('ltr', 'rtl'):
            raise ValueError('Invalid UI language direction')
        catalogs[code] = json.loads((LOCALES / f'{code}.json').read_text(encoding='utf-8'))
    if manifest['defaultLocale'] not in catalogs:
        raise ValueError('Default UI language is missing')
    registry = LOCALES / 'error-keys.json'
    return {'manifest': manifest, 'catalogs': catalogs,
            'errorKeys': json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}}
