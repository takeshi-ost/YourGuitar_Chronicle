"""Explicit Cloud Run entry point; never starts local WebUI or migrations."""
import os
import re
import uvicorn
from ygc.cloud_account_api import create_app
from ygc.db.postgres import PostgresSettings
from ygc.cloud_storage import CloudStorage, StorageSettings


def application():
    for key, value in [('YGC_PLATFORM_TARGET', 'gcp'),
                       ('YGC_DATABASE_BACKEND', 'postgres'),
                       ('YGC_IDENTITY_BACKEND', 'identity_platform')]:
        if os.environ.get(key) != value:
            raise ValueError(f'{key} must be {value}.')
    project = os.environ.get('YGC_IDENTITY_PROJECT_ID', '')
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project):
        raise ValueError('Set a valid YGC_IDENTITY_PROJECT_ID.')
    settings = PostgresSettings.from_environment()
    if settings.host.startswith('/cloudsql/'):
        if not settings.host.startswith('/cloudsql/' + project + ':'):
            raise ValueError('Cloud SQL and Identity Platform projects must match.')
    storage = CloudStorage(StorageSettings.from_environment(project))
    try:
        return create_app(settings, storage=storage, project_id=project,
                      tenant=os.environ.get('YGC_IDENTITY_TENANT', ''),
                      web_config={'apiKey': os.environ.get('YGC_FIREBASE_API_KEY', ''),
                                  'authDomain': os.environ.get('YGC_FIREBASE_AUTH_DOMAIN', '')})
    except Exception:
        storage.close()
        raise


def main():
    try:
        port = int(os.environ.get('PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid PORT.')
        app = application()
    except Exception:
        raise SystemExit('Cloud account startup configuration is invalid.') from None
    uvicorn.run(app, host='0.0.0.0', port=port, workers=1, access_log=False)


if __name__ == '__main__':
    main()
