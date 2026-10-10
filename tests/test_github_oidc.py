import io
import json
import stat
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import github_oidc


def environment(tmp_path):
    return {
        'DEPLOY_ROLE': 'arn:aws:iam::123456789012:role/personal-mcp-deploy',
        'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://pipelines.actions.githubusercontent.com/token?api-version=2.0',
        'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'PRIVATE_REQUEST_CREDENTIAL',
        'RUNNER_TEMP': str(tmp_path),
        'GITHUB_ENV': str(tmp_path / 'github-env'),
    }


def test_oidc_exports_only_selectors_and_uses_private_token_file(tmp_path, monkeypatch, capsys):
    env = environment(tmp_path)
    def fetch(request, timeout):
        assert timeout == 15
        assert request.get_header('Authorization') == 'Bearer PRIVATE_REQUEST_CREDENTIAL'
        assert parse_qs(urlsplit(request.full_url).query) == {'api-version': ['2.0'], 'audience': ['sts.amazonaws.com']}
        return io.StringIO(json.dumps({'value': 'PRIVATE_JWT'}))
    monkeypatch.setattr(github_oidc, 'urlopen', fetch)
    github_oidc.configure(env)
    exported = dict(line.split('=', 1) for line in (tmp_path / 'github-env').read_text().splitlines() if line)
    assert exported['AWS_ROLE_ARN'] == env['DEPLOY_ROLE']
    assert exported['AWS_ROLE_SESSION_NAME'] == 'mcp-kit-deploy'
    token_file = next(tmp_path.glob('aws-web-identity-*.jwt'))
    assert exported['AWS_WEB_IDENTITY_TOKEN_FILE'] == str(token_file)
    assert token_file.read_text() == 'PRIVATE_JWT'
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert 'PRIVATE_' not in (tmp_path / 'github-env').read_text()
    output = capsys.readouterr()
    assert output.out == output.err == ''


@pytest.mark.parametrize('url', ['http://pipelines.actions.githubusercontent.com/token', 'https://actions.githubusercontent.com.attacker.test/token'])
def test_oidc_rejects_untrusted_endpoint_before_sending_credentials(tmp_path, monkeypatch, url):
    env = environment(tmp_path)
    env['ACTIONS_ID_TOKEN_REQUEST_URL'] = url
    monkeypatch.setattr(github_oidc, 'urlopen', lambda *args, **kwargs: pytest.fail('Credentials must not be sent'))
    with pytest.raises(ValueError):
        github_oidc.configure(env)


@pytest.mark.parametrize('token', [None, '', 'injected\nAWS_SECRET_ACCESS_KEY=bad'])
def test_oidc_rejects_invalid_token_without_files(tmp_path, monkeypatch, token):
    monkeypatch.setattr(github_oidc, 'urlopen', lambda *args, **kwargs: io.StringIO(json.dumps({'value': token})))
    with pytest.raises(ValueError):
        github_oidc.configure(environment(tmp_path))
    assert not list(tmp_path.iterdir())


def test_oidc_removes_token_when_environment_write_fails(tmp_path, monkeypatch):
    env = environment(tmp_path)
    env['GITHUB_ENV'] = str(tmp_path / 'missing' / 'env')
    monkeypatch.setattr(github_oidc, 'urlopen', lambda *args, **kwargs: io.StringIO('{"value":"PRIVATE_JWT"}'))
    with pytest.raises(OSError):
        github_oidc.configure(env)
    assert not list(tmp_path.glob('*.jwt'))


def test_oidc_main_redacts_remote_errors(monkeypatch, capsys):
    def fail(environ):
        raise RuntimeError('PRIVATE_TOKEN_FROM_REMOTE_EXCEPTION')
    monkeypatch.setattr(github_oidc, 'configure', fail)
    assert github_oidc.main() == 1
    output = capsys.readouterr()
    assert 'OIDC setup failed' in output.err
    assert 'PRIVATE_' not in output.out + output.err
