#!/usr/bin/env python3
"""Check live MCP/OAuth discovery before attempting client integration; no login or secrets."""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

class CheckFailure(ValueError):
    pass

def get_json(url):
    if urlsplit(url).scheme != 'https':
        raise CheckFailure('Discovery endpoints must use HTTPS.')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept':'application/json'}), timeout=20) as response:
        if response.geturl().split(':', 1)[0] != 'https':
            raise CheckFailure('Discovery redirected to an insecure endpoint.')
        return json.load(response)

def assess_oidc(metadata, configured_scopes, require_jwks=True):
    failures = []
    if 'S256' not in metadata.get('code_challenge_methods_supported', []):
        failures.append('Authorization server does not advertise PKCE S256. Cognito may omit this metadata field; client integration is blocked until tested/resolved.')
    for key in ['issuer','authorization_endpoint','token_endpoint'] + (['jwks_uri'] if require_jwks else []):
        if not isinstance(metadata.get(key), str) or not metadata[key].startswith('https://'):
            failures.append('Missing or insecure OIDC field: ' + key)
    advertised = set(metadata.get('scopes_supported', [])) & {'openid', 'email', 'profile', 'phone'}
    if advertised - set(configured_scopes):
        failures.append('OIDC scopes advertised but not enabled for the app client: ' + ', '.join(sorted(advertised - set(configured_scopes))))
    if 'authorization_code' not in metadata.get('grant_types_supported', ['authorization_code']):
        failures.append('Authorization-code grant not advertised.')
    if set(configured_scopes) - set(metadata.get('scopes_supported', [])):
        failures.append('Authorization server does not advertise all configured scopes.')
    return failures

def discover_authorization_server(issuer):
    parsed = urlsplit(issuer)
    # RFC 8414 first, then OIDC discovery; do not silently replace successful
    # but incompatible metadata with a different document.
    oauth_url = parsed.scheme + '://' + parsed.netloc + '/.well-known/oauth-authorization-server' + parsed.path.rstrip('/')
    try:
        return get_json(oauth_url), False
    except urllib.error.HTTPError as error:
        if error.code not in (400, 404):
            raise
    return get_json(issuer.rstrip('/') + '/.well-known/openid-configuration'), True

def discover_protected_resource(endpoint, challenge):
    import re
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    if match:
        return get_json(match.group(1)), 'challenge'
    # MCP 2025-11-25 requires clients to try these well-known locations when
    # no resource_metadata challenge is available. Lambda Function URLs remap
    # WWW-Authenticate; do not depend on their vendor-specific renamed header.
    parsed = urlsplit(endpoint)
    base = parsed.scheme + '://' + parsed.netloc + '/.well-known/oauth-protected-resource'
    candidates = list(dict.fromkeys([base + parsed.path.rstrip('/'), base]))
    for i, url in enumerate(candidates):
        try:
            return get_json(url), 'well-known'
        except urllib.error.HTTPError as error:
            if error.code != 404 or i == len(candidates) - 1:
                raise
    raise CheckFailure('Protected resource metadata discovery failed.')

def run(outputs):
    endpoint = outputs['mcp_url']['value']
    issuer = outputs['oauth_issuer']['value']
    scopes = outputs['oauth_scope']['value'].split()
    protocol = {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'mcp-kit-preflight','version':'0.1.0'}}}
    request = urllib.request.Request(endpoint, data=json.dumps(protocol).encode(), headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
    try:
        with urllib.request.urlopen(request, timeout=20):
            raise CheckFailure('Gateway accepted an unauthenticated MCP request; expected 401.')
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise CheckFailure('Expected unauthenticated 401, received HTTP ' + str(error.code))
        challenge = error.headers.get('WWW-Authenticate', '')
    prm, discovery_method = discover_protected_resource(endpoint, challenge)
    failures = []
    custom_scopes = set(scopes) - {'openid', 'email', 'profile', 'phone'}
    if custom_scopes - set(prm.get('scopes_supported', [])):
        failures.append('Protected-resource metadata does not advertise the required tools scope.')
    if issuer not in prm.get('authorization_servers', []):
        failures.append('Protected-resource metadata does not advertise the configured OAuth authorization server.')
    if prm.get('resource') != endpoint:
        failures.append('Protected-resource resource identifier differs from the MCP URL; verify client resource binding.')
    metadata, is_oidc = discover_authorization_server(issuer)
    if metadata.get('issuer') != issuer:
        failures.append('Authorization server issuer mismatch.')
    failures.extend(assess_oidc(metadata, scopes, require_jwks=is_oidc))
    if 'none' not in metadata.get('token_endpoint_auth_methods_supported', []):
        failures.append('Static public client authentication method none is not advertised.')
    for key, output in [('authorization_endpoint', 'oauth_authorization_url'), ('token_endpoint', 'oauth_token_url')]:
        if output in outputs and metadata.get(key) != outputs[output]['value']:
            failures.append('OAuth adapter advertises an unexpected Cognito endpoint: ' + key)
    if 'token_issuer' in outputs:
        token_issuer = outputs['token_issuer']['value']
        token_metadata = get_json(token_issuer.rstrip('/') + '/.well-known/openid-configuration')
        if token_metadata.get('issuer') != token_issuer or not token_metadata.get('jwks_uri', '').startswith(token_issuer + '/'):
            failures.append('Cognito token issuer or public key endpoint mismatch.')
    if failures:
        for failure in failures:
            print('FAIL: ' + failure)
        return 1
    print('Protected resource discovery: ' + discovery_method + '.')
    print('Discovery checks passed. Browser authorization, token refresh and tools/call still require a live client test.')
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(run(json.loads(Path(args.outputs).read_text())))
    except (ValueError, KeyError, urllib.error.URLError) as error:
        raise SystemExit('Preflight failed: ' + str(error))
