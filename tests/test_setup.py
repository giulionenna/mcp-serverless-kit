import json
from pathlib import Path
import importlib.util
import pytest
ROOT = Path(__file__).parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_live_discovery_requires_pkce_and_enabled_scopes():
    preflight = load('preflight')
    metadata = {'issuer':'https://issuer.example','authorization_endpoint':'https://issuer.example/authorize','token_endpoint':'https://issuer.example/token','jwks_uri':'https://issuer.example/jwks','scopes_supported':['openid','profile']}
    failures = preflight.assess_oidc(metadata, ['openid'])
    assert any('S256' in x for x in failures)
    assert any('profile' in x for x in failures)
    metadata['code_challenge_methods_supported'] = ['S256']
    assert not preflight.assess_oidc(metadata, ['openid','profile'])

def test_setup_rejects_placeholders_before_aws_access():
    config = {'AWS_REGION':'eu-west-1','STATE_BUCKET':'personal-mcp-123456789012-eu-west-1-tfstate','DEPLOY_ROLE':'arn:aws:iam::123456789012:role/personal-mcp-github-deploy','TF_VAR_project_name':'personal-mcp','TF_VAR_callback_urls':'["https://chatgpt.com/connector/oauth/{callback_id}"]'}
    with pytest.raises(ValueError):
        load('check_config').validate(config)
    config['TF_VAR_callback_urls'] = '["https://claude.ai/api/mcp/auth_callback"]'
    load('check_config').validate(config)

def test_connection_summary_never_dumps_secrets():
    output = {'oauth_client_id': {'value':'public-id','sensitive':False},'arbitrary_secret':{'value':'do-not-print','sensitive':True}}
    summary = load('connection_summary').render(output)
    assert 'public-id' in summary and 'do-not-print' not in summary
    output['oauth_client_id']['sensitive'] = True
    with pytest.raises(ValueError):
        load('connection_summary').render(output)

def test_owner_reset_is_explicit_and_does_not_recreate_user(monkeypatch, capsys):
    import sys
    import types
    owner = load('create_owner')
    class ClientError(Exception):
        def __init__(self, code):
            self.response = {'Error': {'Code': code}}
    calls = []
    class Client:
        def admin_create_user(self, **kwargs):
            calls.append('create')
            raise ClientError('UsernameExistsException')
        def admin_set_user_password(self, **kwargs):
            calls.append('set-password')
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda *a, **k: Client()))
    monkeypatch.setitem(sys.modules, 'botocore.exceptions', types.SimpleNamespace(ClientError=ClientError))
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'owner@example.test')
    monkeypatch.setattr(owner.getpass, 'getpass', lambda _: 'A-long-safe-password1!')
    argv = ['create_owner', '--pool-id', 'pool', '--region', 'eu-west-1']
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit, match='already exists'):
        owner.main()
    assert calls == ['create']
    calls.clear()
    monkeypatch.setattr(sys, 'argv', argv + ['--reset-password'])
    owner.main()
    assert calls == ['set-password']
    assert 'No email was sent' in capsys.readouterr().out
