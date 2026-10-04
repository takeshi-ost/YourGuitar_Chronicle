#!/usr/bin/env python3
"""Deploy the authentication-only staging service without exposing credentials.

Run after tests and Cloud Build succeed. Requires an immutable image digest,
existing Cloud SQL/secret/runtime service account and an existing browser API key.
It never initializes databases or deploys the local WebUI.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'region', 'instance', 'image', 'api-key-resource'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--service', default='ygc-staging-accounts')
    parser.add_argument('--secret', default='ygc-staging-db-password')
    parser.add_argument('--secret-version', default='1')
    parser.add_argument('--gcloud', default='gcloud')
    args = parser.parse_args()
    if '@sha256:' not in args.image:
        parser.error('Use an immutable image digest.')

    def cli(*parts):
        result = subprocess.run([args.gcloud, *parts, '--project=' + args.project],
                                capture_output=True, text=True)
        if result.returncode:
            # Never echo full command, env contents or provider responses.
            raise RuntimeError('GCP command failed: ' + ' '.join(parts[:3]))
        return result.stdout.strip()

    def request(url, method='GET', payload=None):
        token = cli('auth', 'print-access-token')
        req = urllib.request.Request(url, method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token,
                     'x-goog-user-project': args.project, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    key_info = json.loads(cli('services', 'api-keys', 'describe', args.api_key_resource, '--format=json'))
    restrictions = key_info.get('restrictions', {})
    if 'browserKeyRestrictions' not in restrictions or not restrictions.get('apiTargets'):
        raise RuntimeError('Require browser referrer and API restrictions before deployment.')
    key = json.loads(cli('services', 'api-keys', 'get-key-string', args.api_key_resource,
                        '--format=json'))['keyString']
    instance = args.project + ':' + args.region + ':' + args.instance
    env = {'YGC_PLATFORM_TARGET': 'gcp', 'YGC_DATABASE_BACKEND': 'postgres',
           'YGC_IDENTITY_BACKEND': 'identity_platform', 'YGC_IDENTITY_PROJECT_ID': args.project,
           'YGC_POSTGRES_HOST': '/cloudsql/' + instance, 'YGC_POSTGRES_USER': 'ygc_app',
           'YGC_POSTGRES_PREFIX': 'ygc_', 'YGC_FIREBASE_API_KEY': key,
           'YGC_FIREBASE_AUTH_DOMAIN': args.project + '.firebaseapp.com'}
    with tempfile.TemporaryDirectory(prefix='ygc-cloud-deploy-') as directory:
        path = Path(directory) / 'env.json'
        path.write_text(json.dumps(env))
        os.chmod(path, 0o600)
        url = cli('run', 'deploy', args.service, '--region=' + args.region,
                  '--image=' + args.image, '--service-account=ygc-staging-app@' + args.project + '.iam.gserviceaccount.com',
                  '--set-cloudsql-instances=' + instance, '--env-vars-file=' + str(path),
                  '--set-secrets=YGC_POSTGRES_PASSWORD=' + args.secret + ':' + args.secret_version,
                  '--execution-environment=gen2', '--cpu=1', '--memory=512Mi',
                  '--min=0', '--max=1', '--concurrency=8', '--timeout=30', '--no-cpu-boost',
                  '--startup-probe=httpGet.path=/health,httpGet.port=8080,periodSeconds=10,timeoutSeconds=2,failureThreshold=24',
                  '--no-allow-unauthenticated', '--quiet', '--format=value(status.url)')
    if not url.startswith('https://') or not url.endswith('.run.app'):
        raise RuntimeError('Unexpected Cloud Run URL.')
    domain = url.removeprefix('https://')
    config_url = 'https://identitytoolkit.googleapis.com/admin/v2/projects/' + args.project + '/config'
    config = request(config_url)
    domains = config.get('authorizedDomains', [])
    if domain not in domains:
        request(config_url + '?updateMask=authorizedDomains', 'PATCH',
                {'authorizedDomains': domains + [domain]})
    refs = restrictions['browserKeyRestrictions'].get('allowedReferrers', [])
    if url + '/*' not in refs:
        cli('services', 'api-keys', 'update', args.api_key_resource,
            '--allowed-referrers=' + ','.join(refs + [url + '/*']), '--quiet', '--format=value(name)')
    actual = json.loads(cli('services', 'api-keys', 'describe', args.api_key_resource, '--format=json'))
    if actual.get('restrictions', {}).get('apiTargets') != restrictions['apiTargets']:
        raise RuntimeError('API restrictions changed unexpectedly; service remains private.')
    if domain not in request(config_url).get('authorizedDomains', []):
        raise RuntimeError('Identity Platform domain update failed; service remains private.')
    if url + '/*' not in actual['restrictions']['browserKeyRestrictions']['allowedReferrers']:
        raise RuntimeError('Browser API key restriction update failed; service remains private.')
    # This page is public; every account read/write still verifies an Identity Platform token.
    cli('run', 'services', 'add-iam-policy-binding', args.service, '--region=' + args.region,
        '--member=allUsers', '--role=roles/run.invoker', '--quiet', '--format=value(version)')
    print('Authentication staging page: ' + url + '/account')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Staging deployment failed. Inspect GCP operation status; credentials were not printed.') from None
