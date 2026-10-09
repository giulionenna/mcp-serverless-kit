import base64
import io
import json
import urllib.error
from pathlib import Path
import importlib.util
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('oauth_compat', ROOT / 'runtime/oauth_compat.py')
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)
ORIGIN = 'https://abcdefgh.lambda-url.eu-south-1.on.aws'
COGNITO = 'https://personal-mcp.auth.eu-south-1.amazoncognito.com'


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv('AWS_REGION', 'eu-south-1')
    monkeypatch.setenv('MCP_SCOPE', 'personal-mcp/tools')
    monkeypatch.setenv('COGNITO_OAUTH_ORIGIN', COGNITO)


def event(path='/mcp', method='POST', token=None):
    headers = {'content-type': 'application/json'}
    if token:
        headers['authorization'] = token
    return {'requestContext': {'domainName': ORIGIN.removeprefix('https://'), 'http': {'method': method}}, 'rawPath': path, 'headers': headers, 'body': json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})}


def test_discovery_and_challenge_use_trusted_origin(monkeypatch):
    def forbidden():
        raise AssertionError('Unauthenticated request must not reach S3 or Gateway')
    monkeypatch.setattr(compat, 'gateway_url', forbidden)
    request = event()
    request['headers'].update({'host': 'attacker.test', 'x-forwarded-host': 'attacker.test'})
    result = compat.lambda_handler(request, None)
    assert result['statusCode'] == 401
    assert ORIGIN + '/.well-known/oauth-protected-resource' in result['headers']['WWW-Authenticate']
    metadata = json.loads(compat.lambda_handler(event('/.well-known/oauth-protected-resource/mcp', 'GET'), None)['body'])
    assert metadata['resource'] == ORIGIN + '/mcp'
    assert metadata['authorization_servers'] == [ORIGIN]


def test_metadata_delegates_oauth_without_claiming_oidc():
    metadata = json.loads(compat.lambda_handler(event('/.well-known/oauth-authorization-server', 'GET'), None)['body'])
    assert metadata['issuer'] == ORIGIN
    assert metadata['authorization_endpoint'] == COGNITO + '/oauth2/authorize'
    assert metadata['token_endpoint'] == COGNITO + '/oauth2/token'
    assert metadata['code_challenge_methods_supported'] == ['S256']
    assert metadata['token_endpoint_auth_methods_supported'] == ['none']
    assert metadata['scopes_supported'] == ['personal-mcp/tools']
    assert 'jwks_uri' not in metadata
    assert compat.lambda_handler(event('/.well-known/openid-configuration', 'GET'), None)['statusCode'] == 404


@pytest.mark.parametrize('token', ['Basic secret', 'Bearer bad\nheader', 'Bearer ' + 'a' * 17000])
def test_malformed_authorization_rejected_without_forwarding(token, monkeypatch):
    monkeypatch.setattr(compat, 'gateway_url', lambda: pytest.fail('Must not forward'))
    assert compat.lambda_handler(event(token=token), None)['statusCode'] == 401


class Upstream(io.BytesIO):
    status = 200
    headers = {'Mcp-Session-Id': 'session-1', 'Set-Cookie': 'must-not-forward'}


def test_transport_preserves_token_and_rpc_but_drops_unneeded_headers(monkeypatch):
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Upstream(b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    monkeypatch.setattr(compat, 'gateway_url', lambda: 'https://gateway.example/mcp')
    monkeypatch.setattr(compat.urllib.request, 'build_opener', lambda *args: Opener())
    request = event(token='Bearer original.signed.token')
    request['headers'].update({'cookie': 'private', 'x-forwarded-host': 'evil', 'mcp-protocol-version': '2025-03-26'})
    request['body'] = base64.b64encode(request['body'].encode()).decode()
    request['isBase64Encoded'] = True
    result = compat.lambda_handler(request, None)
    assert result['statusCode'] == 200
    sent = requests[0]
    assert sent.get_header('Authorization') == 'Bearer original.signed.token'
    assert sent.get_header('Accept') == 'application/json'
    assert sent.get_header('Cookie') is None
    assert json.loads(sent.data)['method'] == 'tools/list'
    assert result['headers']['Mcp-Session-Id'] == 'session-1'
    assert 'Set-Cookie' not in result['headers']


@pytest.mark.parametrize('status', [401, 403])
def test_gateway_remains_auth_authority_and_challenges_are_rewritten(status, monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, status, 'Denied', {'WWW-Authenticate': 'upstream-private'}, io.BytesIO(b'private'))
    monkeypatch.setattr(compat, 'gateway_url', lambda: 'https://gateway.example/mcp')
    monkeypatch.setattr(compat.urllib.request, 'build_opener', lambda *args: Opener())
    result = compat.lambda_handler(event(token='Bearer invalid.token'), None)
    assert result['statusCode'] == status
    assert ORIGIN in result['headers']['WWW-Authenticate']
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('body, status', [('{', 400), ('{"value":NaN}', 400), ('[]', 400), ('x' * (compat.MAX_BODY * 2 + 1), 413)])
def test_bad_or_oversized_bodies_do_not_reach_gateway(body, status, monkeypatch):
    monkeypatch.setattr(compat, 'gateway_url', lambda: pytest.fail('Must not forward'))
    request = event(token='Bearer a.b.c')
    request['body'] = body
    assert compat.lambda_handler(request, None)['statusCode'] == status


def test_exceptions_never_disclose_tokens(monkeypatch, capsys):
    def fail():
        raise ValueError('Bearer secret.token')
    monkeypatch.setattr(compat, 'gateway_url', fail)
    result = compat.lambda_handler(event(token='Bearer secret.token'), None)
    assert result['statusCode'] == 502
    assert 'secret' not in json.dumps(result)
    assert capsys.readouterr().out == ''


def test_transport_does_not_follow_redirects():
    assert compat.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test') is None


@pytest.mark.parametrize('url', ['http://gateway.gateway.bedrock-agentcore.eu-south-1.amazonaws.com/mcp', 'https://evil.test/mcp', 'https://gateway.gateway.bedrock-agentcore.eu-north-1.amazonaws.com/mcp', 'https://gateway.gateway.bedrock-agentcore.eu-south-1.amazonaws.com/mcp?other=1'])
def test_private_configuration_cannot_redirect_tokens_to_other_hosts(url, monkeypatch):
    import sys
    import types
    monkeypatch.setenv('CONFIG_BUCKET', 'private-bucket')
    monkeypatch.setenv('CONFIG_KEY', 'connection/gateway.json')
    compat._gateway_cache = None
    class S3:
        def get_object(self, **kwargs):
            assert kwargs == {'Bucket': 'private-bucket', 'Key': 'connection/gateway.json'}
            return {'Body': io.BytesIO(json.dumps({'gateway_url': url}).encode())}
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda service: S3()))
    with pytest.raises(ValueError, match='Invalid Gateway'):
        compat.gateway_url()


def test_adapter_package_contains_no_modules_or_credentials(tmp_path):
    build_spec = importlib.util.spec_from_file_location('build', ROOT / 'scripts/build.py')
    build = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(build)
    import zipfile
    first = build.package_oauth_compat(tmp_path).read_bytes()
    assert build.package_oauth_compat(tmp_path).read_bytes() == first
    with zipfile.ZipFile(tmp_path / 'oauth-compat.zip') as archive:
        assert archive.namelist() == ['oauth_compat.py']
