"""OAuth discovery adapter and stateless JSON MCP transport.

Cognito owns authorization and token endpoints. AgentCore owns JWT validation.
This is OAuth authorization-server metadata, not an alternative OIDC issuer:
the tokens retain Cognito's issuer, which the Gateway is configured to trust.
Never log request bodies, authorization headers, or upstream exception strings.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_BODY = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
PROTOCOL_VERSIONS = {'2025-03-26', '2025-06-18', '2025-11-25', '2026-07-28'}
DIAGNOSTIC_METHODS = {'initialize', 'notifications/initialized', 'server/discover',
                      'tools/list', 'tools/call', 'resources/list',
                      'resources/templates/list', 'resources/read', 'prompts/list',
                      'prompts/get', 'ping'}
_gateway_cache = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def diagnostic(event, **fields):
    # Callers supply only fixed categories, numeric codes and counts. Never
    # pass a request/response body, arbitrary header or exception message.
    print(json.dumps({'event': event, **fields}), flush=True)


def request_diagnostic(message, headers):
    method = message.get('method')
    params = message.get('params')
    params = params if isinstance(params, dict) else {}
    version = headers.get('mcp-protocol-version', params.get('protocolVersion'))
    diagnostic('mcp_request',
               method=method if isinstance(method, str) and method in DIAGNOSTIC_METHODS else 'other',
               version=version if isinstance(version, str) and version in PROTOCOL_VERSIONS else 'other_or_absent')


def rejected_token_diagnostic(authorization, public_origin, upstream_headers):
    # These are UNVERIFIED payload comparisons for diagnosis only. They never
    # authorize a request or replace Gateway's signature/expiry/claim checks.
    # Log only booleans and a fixed token-kind category, never claim values.
    fields = {'parsed': False,
              'insufficient_scope_challenge': bool(re.search(
                  r'error\s*=\s*"?insufficient_scope(?:"|\s|,|$)',
                  upstream_headers.get('WWW-Authenticate', ''), re.IGNORECASE))}
    try:
        parts = authorization.split(' ', 1)[1].split('.')
        if len(parts) != 3:
            raise ValueError('Not a JWT')
        payload = parts[1]
        decoded = base64.b64decode(payload + '=' * (-len(payload) % 4), altchars=b'-_', validate=True)
        claims = json.loads(decoded)
        if not isinstance(claims, dict):
            raise ValueError('Invalid claims')
        scope = claims.get('scope')
        audience = claims.get('aud')
        kind = claims.get('token_use')
        fields.update({
            'parsed': True,
            'token_kind': kind if isinstance(kind, str) and kind in ('access', 'id') else 'other',
            'issuer_matches': claims.get('iss') == os.environ['COGNITO_TOKEN_ISSUER'],
            'client_matches': claims.get('client_id') == os.environ['COGNITO_CLIENT_ID'],
            'audience_matches': (audience == public_origin + '/mcp' or
                                 isinstance(audience, list) and public_origin + '/mcp' in audience),
            'scope_present': isinstance(scope, str) and os.environ['MCP_SCOPE'] in scope.split(),
        })
    except (ValueError, UnicodeError, IndexError, KeyError, RecursionError):
        pass
    diagnostic('mcp_rejected_token_checks', **fields)


def response(status, body=None, headers=None):
    return {
        'statusCode': status,
        'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store', **(headers or {})},
        'body': '' if body is None else json.dumps(body, allow_nan=False),
    }


def origin(event):
    # Lambda supplies requestContext; do not construct discovery from Host or
    # X-Forwarded-Host, which callers can supply themselves.
    domain = event['requestContext']['domainName']
    region = os.environ['AWS_REGION']
    if not re.fullmatch(r'[a-z0-9]+\.lambda-url\.' + re.escape(region) + r'\.on\.aws', domain):
        raise ValueError('Invalid Function URL origin')
    return 'https://' + domain


def challenge(public_origin, insufficient_scope=False):
    value = 'Bearer resource_metadata="' + public_origin + '/.well-known/oauth-protected-resource", scope="' + os.environ['MCP_SCOPE'] + '"'
    if insufficient_scope:
        value += ', error="insufficient_scope"'
    return {'WWW-Authenticate': value}


def authorization_metadata(public_origin):
    # Advertise only API access, avoiding OIDC ID-token discovery under an
    # issuer different from Cognito. The static public client uses PKCE.
    return {
        'issuer': public_origin,
        'authorization_endpoint': os.environ['COGNITO_OAUTH_ORIGIN'] + '/oauth2/authorize',
        'token_endpoint': os.environ['COGNITO_OAUTH_ORIGIN'] + '/oauth2/token',
        'revocation_endpoint': os.environ['COGNITO_OAUTH_ORIGIN'] + '/oauth2/revoke',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'],
        'code_challenge_methods_supported': ['S256'],
        'scopes_supported': [os.environ['MCP_SCOPE']],
        'authorization_response_iss_parameter_supported': False,
    }


def gateway_url():
    global _gateway_cache
    if _gateway_cache and _gateway_cache[0] > time.monotonic():
        return _gateway_cache[1]
    import boto3
    obj = boto3.client('s3').get_object(Bucket=os.environ['CONFIG_BUCKET'], Key=os.environ['CONFIG_KEY'])
    with obj['Body'] as body:
        config = json.loads(body.read(4096))
    url = config['gateway_url']
    parsed = urlsplit(url)
    suffix = '.gateway.bedrock-agentcore.' + os.environ['AWS_REGION'] + '.amazonaws.com'
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith(suffix)
            or parsed.username or parsed.password or parsed.port or parsed.path != '/mcp'
            or parsed.query or parsed.fragment):
        raise ValueError('Invalid Gateway endpoint')
    _gateway_cache = (time.monotonic() + 60, url)
    return url


def forward(event, public_origin, headers):
    authorization = headers.get('authorization', '')
    if not re.fullmatch(r'Bearer [A-Za-z0-9._~+/=-]+', authorization, flags=re.IGNORECASE) or len(authorization) > 16384:
        return response(401, {'error': 'Authentication required'}, challenge(public_origin))
    if headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        return response(415, {'error': 'Use application/json'})
    raw = event.get('body') or ''
    if len(raw) > MAX_BODY * 2:
        return response(413, {'error': 'Request too large'})
    try:
        body = base64.b64decode(raw, validate=True) if event.get('isBase64Encoded') else raw.encode('utf-8')
        if len(body) > MAX_BODY:
            return response(413, {'error': 'Request too large'})
        def reject_constant(value):
            raise ValueError('Non-finite JSON')
        message = json.loads(body, parse_constant=reject_constant)
        if not isinstance(message, dict):
            raise ValueError('Expected JSON object')
    except (ValueError, UnicodeError):
        return response(400, {'error': 'Invalid JSON request'})
    request_diagnostic(message, headers)
    outbound = {'Authorization': authorization, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    # MCP 2026-07-28 binds method/name headers to the JSON-RPC body. Dropping
    # these headers makes a conformant request invalid at Gateway.
    for name in ('mcp-protocol-version', 'mcp-session-id', 'mcp-method', 'mcp-name'):
        if name in headers:
            outbound[name] = headers[name]
    request = urllib.request.Request(gateway_url(), data=body, headers=outbound, method='POST')
    opener = urllib.request.build_opener(NoRedirect())
    try:
        upstream = opener.open(request, timeout=40)
    except urllib.error.HTTPError as error:
        upstream = error
    with upstream:
        status = upstream.status
        diagnostic('mcp_upstream', status=status)
        if status in (401, 403):
            rejected_token_diagnostic(authorization, public_origin, upstream.headers)
            return response(status, {'error': 'Authentication required' if status == 401 else 'Insufficient permissions'}, challenge(public_origin, status == 403))
        if status >= 500 or 300 <= status < 400:
            return response(502, {'error': 'Gateway unavailable'})
        data = upstream.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            return response(502, {'error': 'Gateway response too large'})
        result = json.loads(data) if data else None
        if isinstance(result, dict):
            error = result.get('error')
            if isinstance(error, dict) and type(error.get('code')) is int:
                diagnostic('mcp_rpc_error', code=error['code'])
            payload = result.get('result')
            if isinstance(payload, dict) and isinstance(payload.get('tools'), list):
                diagnostic('mcp_tools', count=len(payload['tools']))
        output_headers = {name: upstream.headers[name] for name in ('Mcp-Session-Id', 'Mcp-Protocol-Version', 'Retry-After') if name in upstream.headers}
        return response(status, result, output_headers)


def lambda_handler(event, context):
    try:
        public_origin = origin(event)
        method = event['requestContext']['http']['method']
        path = event.get('rawPath', '/')
        if method == 'GET' and path in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp'):
            return response(200, {'resource': public_origin + '/mcp', 'authorization_servers': [public_origin], 'scopes_supported': [os.environ['MCP_SCOPE']], 'bearer_methods_supported': ['header']})
        if method == 'GET' and path == '/.well-known/oauth-authorization-server':
            return response(200, authorization_metadata(public_origin))
        if path != '/mcp':
            return response(404, {'error': 'Not found'})
        if method != 'POST':
            return response(405, {'error': 'Stateless MCP endpoint supports POST'}, {'Allow': 'POST'})
        headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
        return forward(event, public_origin, headers)
    except Exception as error:
        # No exception text: upstream libraries may put tokens in messages.
        category = ('invalid_upstream_json' if isinstance(error, json.JSONDecodeError)
                    else 'transport_error' if isinstance(error, (urllib.error.URLError, TimeoutError))
                    else 'configuration_or_internal_error')
        diagnostic('mcp_failure', category=category)
        return response(502, {'error': 'MCP service unavailable'})
