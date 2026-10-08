"""Start a seeded, disposable server for the explicit browser checks."""
import os
from pathlib import Path
import socket
import tempfile
import threading


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
                from browser_ui_components import main as components
                from browser_modal_dismissal import main as dismissal
                components()
                dismissal()
                from browser_user_journeys import main as journeys
                journeys(repository)
                from browser_cloud_account import main as cloud_account
                cloud_account()
                from browser_cloud_applications_retry import main as cloud_applications_retry
                cloud_applications_retry()
                from browser_cloud_owner import main as cloud_owner
                cloud_owner()
                from browser_cloud_console import main as cloud_console
                cloud_console()
                from browser_cloud_admin_applications import main as cloud_admin_applications
                cloud_admin_applications()
                from browser_cloud_public_catalog import main as cloud_public_catalog
                cloud_public_catalog()
                from browser_cloud_formal_ui import main as cloud_formal_ui
                cloud_formal_ui()
                from browser_cloud_claim_posting import main as cloud_claim_posting
                cloud_claim_posting()
                from browser_cloud_media_claims import main as cloud_media_claims
                cloud_media_claims()
                from browser_cloud_event_claims import main as cloud_event_claims
                cloud_event_claims()
                from browser_cloud_identity_correction import main as cloud_identity_correction
                cloud_identity_correction()
                from browser_cloud_notifications import main as cloud_notifications
                cloud_notifications()
                from browser_cloud_ownership_disputes import main as cloud_ownership_disputes
                cloud_ownership_disputes()
                from browser_cloud_favorites_visibility import main as cloud_favorites_visibility
                cloud_favorites_visibility()
                from browser_cloud_follows import main as cloud_follows
                cloud_follows()
                from browser_cloud_ownership import main as cloud_ownership
                cloud_ownership()
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                if thread.is_alive():
                    raise RuntimeError('Browser test server did not stop')


if __name__ == '__main__':
    main()
