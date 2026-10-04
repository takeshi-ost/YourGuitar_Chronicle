"""Operator-only first Admin grant. Never exposed by an HTTP route."""
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import uuid

from ygc.account_projection_job import settings_from_environment
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts


def grant_first_admin(settings, app_user_id, operator):
    if not isinstance(operator, str) or not operator.strip() or len(operator) > 254:
        raise ValueError('Identify the operator.')
    with connect(settings, 'accounts') as con:
        con.execute('SELECT pg_advisory_xact_lock(79432003)')
        account = con.execute('SELECT * FROM account_records WHERE app_user_id=%s FOR UPDATE', (app_user_id,)).fetchone()
        PostgresAccounts._active(account)
        existing = con.execute("SELECT app_user_id FROM account_records WHERE role='admin' AND disabled=0 AND ban_status<>'ban' AND account_type<>'source'").fetchall()
        if account['role'] == 'admin':
            return False
        if existing:
            raise PermissionError('An administrator already exists; use a reviewed administrator management path.')
        con.execute("UPDATE account_records SET role='admin',updated_at=%s WHERE app_user_id=%s",
                    (datetime.now(timezone.utc).isoformat(), app_user_id))
        con.execute('INSERT INTO account_metadata(key,value) VALUES(%s,%s)',
            ('admin_bootstrap:' + str(uuid.uuid4()), json.dumps({'action': 'first_admin',
             'actor': operator.strip(), 'target_app_user_id': app_user_id,
             'occurred_at': datetime.now(timezone.utc).isoformat()})))
        return True


def registered_verified_account(settings, project, email):
    """Google lookup is only for the explicit IAM-authorized bootstrap operation."""
    if 'FIREBASE_AUTH_EMULATOR_HOST' in os.environ:
        raise ValueError('Auth Emulator is not allowed.')
    import firebase_admin
    from firebase_admin import auth, tenant_mgt
    app = firebase_admin.initialize_app(options={'projectId': project, 'httpTimeout': 10}, name='ygc-bootstrap-' + str(uuid.uuid4()))
    tenant = os.environ.get('YGC_IDENTITY_TENANT', '')
    try:
        user = (tenant_mgt.auth_for_tenant(tenant, app=app).get_user_by_email(email) if tenant
                else auth.get_user_by_email(email, app=app))
        if user.disabled or user.email_verified is not True:
            raise PermissionError('Complete Google email verification first.')
        return PostgresAccounts(settings).resolve_identity(
            issuer='https://securetoken.google.com/' + project, tenant=tenant, subject=user.uid)
    finally:
        firebase_admin.delete_app(app)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--confirm-project', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        settings = settings_from_environment()
        project = os.environ['YGC_GCP_PROJECT_ID']
        if args.confirm_project != project:
            raise ValueError('Project confirmation does not match.')
        account = registered_verified_account(settings, project, args.email)
        granted = False if args.dry_run else grant_first_admin(settings, account['app_user_id'], args.operator)
        print(json.dumps({'status': 'ok', 'dry_run': args.dry_run, 'granted': granted}))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
