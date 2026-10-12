"""Start a seeded, disposable server for the explicit browser checks."""
import os
from pathlib import Path
import socket
import tempfile
import threading
import importlib
import traceback


def main():
    with tempfile.TemporaryDirectory(prefix='ygc-browser-tests-') as directory:
        root = Path(directory)
        for key in list(os.environ):
            if ((key.startswith('YGC_') and key not in ('YGC_BROWSER_EXECUTABLE', 'YGC_BROWSER_ARTIFACTS'))
                    or key in ('REVERB_API_TOKEN', 'K_SERVICE', 'CLOUD_RUN_JOB')):
                del os.environ[key]
        os.environ.update(YGC_DATA_DIR=directory, YGC_DB_PATH=str(root / 'chronicle.db'),
                          YGC_ACCOUNTS_DB_PATH=str(root / 'accounts.sqlite'),
                          YGC_LOG_DIR=str(root / 'logs'), YGC_IDENTITY_BACKEND='local_dummy')
        import uvicorn
        from ygc.web import app, repo
        from authentication_fixtures import image_bytes
        repository = repo()
        repository.init_db()
        owner = repository.create_user('Browser Test Owner')
        (root / 'reference.png').write_bytes(image_bytes())
        repository.create_initial_listing_claim(owner, manufacturer='Fender', model='Browser Test',
            serial_number='TEST001', media_storage_path='reference.png', occurred_at='2026-01-01')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            os.environ['YGC_BROWSER_URL'] = f'http://127.0.0.1:{sock.getsockname()[1]}'
            server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
            thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
            thread.start()
            try:
                # Independent fixture journeys must all run so one failure does
                # not hide regressions in the remaining browser coverage.
                failures = []
                checks = ('browser_ui_components', 'browser_modal_dismissal', 'browser_user_journeys', 'browser_cloud_account', 'browser_cloud_applications_retry', 'browser_cloud_owner', 'browser_cloud_console', 'browser_cloud_admin_applications', 'browser_cloud_public_catalog', 'browser_cloud_formal_ui', 'browser_detail_dispute', 'browser_formal_claim_actions', 'browser_cloud_claim_posting', 'browser_cloud_media_claims', 'browser_cloud_event_claims', 'browser_cloud_identity_correction', 'browser_cloud_notifications', 'browser_cloud_ownership_disputes', 'browser_cloud_favorites_visibility', 'browser_cloud_follows', 'browser_cloud_ownership')
                for module in checks:
                    print('START browser:', module, flush=True)
                    try:
                        check = importlib.import_module(module).main
                        check(repository) if module == 'browser_user_journeys' else check()
                    except Exception:
                        traceback.print_exc()
                        failures.append(module)
                        print('FAIL browser:', module, flush=True)
                    else:
                        print('PASS browser:', module, flush=True)
                if failures:
                    raise SystemExit('Browser checks failed: ' + ', '.join(failures))
                print('All browser groups passed:', len(checks), flush=True)
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError('Browser test server did not stop')


if __name__ == '__main__':
    main()
