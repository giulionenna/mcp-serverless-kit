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

def test_oauth_discovery_prioritizes_rfc8414_and_does_not_require_oidc_keys(monkeypatch):
    preflight = load('preflight')
    calls = []
    metadata = {'issuer': 'https://auth.example', 'authorization_endpoint': 'https://cognito.example/authorize', 'token_endpoint': 'https://cognito.example/token', 'code_challenge_methods_supported': ['S256'], 'scopes_supported': ['mcp/tools'], 'grant_types_supported': ['authorization_code', 'refresh_token']}
    def get_json(url):
        calls.append(url)
        return metadata
    monkeypatch.setattr(preflight, 'get_json', get_json)
    result, is_oidc = preflight.discover_authorization_server('https://auth.example')
    assert calls == ['https://auth.example/.well-known/oauth-authorization-server']
    assert result == metadata and not is_oidc
    assert not preflight.assess_oidc(result, ['mcp/tools'], require_jwks=is_oidc)

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

def test_bootstrap_update_preserves_trust_and_storage_parameters():
    bootstrap = load('bootstrap')
    calls = []
    class ClientError(Exception):
        pass
    class Waiter:
        def wait(self, **kwargs):
            calls.append(('wait', kwargs))
    class Client:
        def describe_stacks(self, **kwargs):
            return {'Stacks': [{'Parameters': [
                {'ParameterKey': 'ProjectName', 'ParameterValue': 'personal-mcp'},
                {'ParameterKey': 'GitHubSubject', 'ParameterValue': 'repo:owner@1/kit@2:ref:refs/heads/main'},
                {'ParameterKey': 'ExistingOidcProviderArn', 'ParameterValue': 'shared-provider'},
            ]}]}
        def update_stack(self, **kwargs):
            calls.append(('update', kwargs))
        def get_waiter(self, name):
            assert name == 'stack_update_complete'
            return Waiter()
    bootstrap.update_stack(Client(), 'personal-mcp-bootstrap', 'template', ClientError)
    request = calls[0][1]
    assert request['StackName'] == 'personal-mcp-bootstrap'
    assert request['Parameters'] == [
        {'ParameterKey': 'ProjectName', 'UsePreviousValue': True},
        {'ParameterKey': 'GitHubSubject', 'UsePreviousValue': True},
        {'ParameterKey': 'ExistingOidcProviderArn', 'UsePreviousValue': True},
    ]
    assert calls[1] == ('wait', {'StackName': 'personal-mcp-bootstrap'})

def test_bootstrap_update_with_no_changes_is_successful(capsys):
    bootstrap = load('bootstrap')
    class ClientError(Exception):
        response = {'Error': {'Code': 'ValidationError', 'Message': 'No updates are to be performed.'}}
    class Client:
        def describe_stacks(self, **kwargs):
            return {'Stacks': [{'Parameters': []}]}
        def update_stack(self, **kwargs):
            raise ClientError()
        def get_waiter(self, name):
            pytest.fail('There is no update to wait for')
    bootstrap.update_stack(Client(), 'personal-mcp-bootstrap', 'template', ClientError)
    assert 'already up to date' in capsys.readouterr().out
