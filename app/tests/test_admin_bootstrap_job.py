from types import SimpleNamespace
from unittest.mock import Mock
import pytest
pytest.importorskip('psycopg')
from ygc import admin_bootstrap_job as job


@pytest.mark.parametrize('disabled,verified', [(True,True),(False,False),(False,1),(False,'true')])
def test_google_unavailable_or_unverified_never_grants(monkeypatch, disabled, verified):
    firebase = pytest.importorskip('firebase_admin')
    from firebase_admin import auth
    monkeypatch.delenv('FIREBASE_AUTH_EMULATOR_HOST',raising=False)
    monkeypatch.delenv('YGC_IDENTITY_TENANT',raising=False)
    sdk_app = object()
    delete = Mock()
    resolve = Mock()
    monkeypatch.setattr(firebase,'initialize_app',Mock(return_value=sdk_app))
    monkeypatch.setattr(firebase,'delete_app',delete)
    monkeypatch.setattr(auth,'get_user_by_email',Mock(return_value=SimpleNamespace(disabled=disabled,email_verified=verified,uid='subject')))
    monkeypatch.setattr(job,'PostgresAccounts',Mock(return_value=SimpleNamespace(resolve_identity=resolve)))
    with pytest.raises(PermissionError): job.registered_verified_account(object(),'test-project','operator@example.invalid')
    resolve.assert_not_called()
    delete.assert_called_once_with(sdk_app)


def test_confirm_project_precedes_google_and_database(monkeypatch,capsys):
    monkeypatch.setenv('YGC_GCP_PROJECT_ID','test-project')
    monkeypatch.setattr(job,'settings_from_environment',Mock(return_value=object()))
    lookup, grant = Mock(), Mock()
    monkeypatch.setattr(job,'registered_verified_account',lookup)
    monkeypatch.setattr(job,'grant_first_admin',grant)
    assert job.main(['--email','private@example.invalid','--operator','operator','--confirm-project','other-project']) == 1
    lookup.assert_not_called();grant.assert_not_called()
    assert 'private@example.invalid' not in capsys.readouterr().err


def test_dry_run_never_changes_role(monkeypatch):
    monkeypatch.setenv('YGC_GCP_PROJECT_ID','test-project')
    monkeypatch.setattr(job,'settings_from_environment',Mock(return_value=object()))
    monkeypatch.setattr(job,'registered_verified_account',Mock(return_value={'app_user_id':'canonical'}))
    grant=Mock()
    monkeypatch.setattr(job,'grant_first_admin',grant)
    assert job.main(['--email','email@example.invalid','--operator','operator','--confirm-project','test-project','--dry-run']) == 0
    grant.assert_not_called()
