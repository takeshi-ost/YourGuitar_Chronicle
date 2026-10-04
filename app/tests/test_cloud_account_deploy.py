"""Exercise deployment ordering and preservation without contacting GCP."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

spec = importlib.util.spec_from_file_location('cloud_deploy', Path(__file__).resolve().parents[2] / 'scripts/deploy_cloud_account.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.mark.parametrize('corrupt_api_targets', [False, True])
def test_domain_updates_preserve_restrictions_before_public_access(monkeypatch, corrupt_api_targets):
    url = 'https://test-service.run.app'
    config = {'authorizedDomains': ['existing.example']}
    restrictions = {'apiTargets': [{'service': 'identitytoolkit.googleapis.com'}],
                    'browserKeyRestrictions': {'allowedReferrers': ['https://existing.example/*']}}
    calls, env_paths = [], []
    monkeypatch.setattr(sys, 'argv', ['deploy', '--project=test-project', '--region=asia-northeast1',
        '--instance=test-db', '--image=registry/image@sha256:' + 'a' * 64,
        '--api-key-resource=projects/123/locations/global/keys/test'])

    def run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ['services', 'api-keys', 'describe']:
            output = json.dumps({'restrictions': restrictions})
        elif command[1:4] == ['services', 'api-keys', 'get-key-string']:
            output = json.dumps({'keyString': 'public-key'})
        elif command[1:3] == ['run', 'deploy']:
            path = Path(next(part.split('=', 1)[1] for part in command if part.startswith('--env-vars-file=')))
            env_paths.append(path)
            env = json.loads(path.read_text())
            assert 'YGC_POSTGRES_PASSWORD' not in env
            assert env['YGC_DATABASE_BACKEND'] == 'postgres'
            assert env['YGC_MEDIA_BACKEND'] == 'gcs'
            assert env['YGC_CONTENT_BUCKET'] != env['YGC_ACCOUNTS_BUCKET']
            assert path.stat().st_mode & 0o777 == 0o600
            assert '--no-allow-unauthenticated' in command
            output = url
        elif command[1:4] == ['services', 'api-keys', 'update']:
            refs_arg = next(part for part in command if part.startswith('--allowed-referrers='))
            restrictions['browserKeyRestrictions']['allowedReferrers'] = refs_arg.split('=', 1)[1].split(',')
            if corrupt_api_targets:
                # Replacement, not mutation: the original restriction snapshot must remain intact.
                restrictions['apiTargets'] = [{'service': 'unexpected.googleapis.com'}]
            output = ''
        else:
            output = 'token' if command[1:3] == ['auth', 'print-access-token'] else ''
        return SimpleNamespace(returncode=0, stdout=output)

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps(config).encode()

    def open_request(request, **kwargs):
        if request.method == 'PATCH':
            config.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr(deploy.subprocess, 'run', run)
    monkeypatch.setattr(deploy.urllib.request, 'urlopen', open_request)
    if corrupt_api_targets:
        with pytest.raises(RuntimeError, match='API restrictions changed'):
            deploy.main()
    else:
        deploy.main()
    public = [command for command in calls if '--member=allUsers' in command]
    assert bool(public) is (not corrupt_api_targets)
    assert config['authorizedDomains'] == ['existing.example', 'test-service.run.app']
    assert restrictions['browserKeyRestrictions']['allowedReferrers'][0] == 'https://existing.example/*'
    assert 'https://test-project.firebaseapp.com/*' in restrictions['browserKeyRestrictions']['allowedReferrers']
    assert url + '/*' in restrictions['browserKeyRestrictions']['allowedReferrers']
    assert all(not path.exists() for path in env_paths)
