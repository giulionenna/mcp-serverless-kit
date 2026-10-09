# AWS-only OAuth compatibility adapter

The original deployment reached a live Cognito discovery document that omitted
`code_challenge_methods_supported`. Cognito supports PKCE S256, but OpenAI's MCP
OAuth guide rejects metadata that does not advertise it.

This adapter is a Lambda Function URL in the same AWS region. It does not issue,
sign, store, decode, or validate tokens, and it does not collect passwords.

## Request flow

1. Missing bearer credentials on public `/mcp` receive 401 with a challenge
   pointing to `/.well-known/oauth-protected-resource` on the same origin.
   In the live deployment, Function URLs remap `WWW-Authenticate` to
   `x-amzn-Remapped-www-authenticate`. Clients must use the standard well-known
   fallback: `/.well-known/oauth-protected-resource/mcp`, then the root variant.
   Both are served. MCP 2025-11-25 explicitly supports discovery using either
   the challenge or well-known URI, and requires clients to support both.
2. Resource metadata identifies public `/mcp` as the resource and the Function
   URL origin as the OAuth authorization-server identifier.
3. RFC 8414 metadata at `/.well-known/oauth-authorization-server` advertises
   authorization code, PKCE S256, public-client token authentication, and refresh.
   Authorization, token and revocation endpoints remain the real Cognito endpoints.
4. The client signs in directly at Cognito with its pre-registered public client
   ID and exact callback allowlist. It requests `resource=<public MCP URL>` and
   the tools scope. Cognito resource binding sets that URL as access-token
   audience; OAuth refresh preserves the audience.
5. The adapter forwards JSON MCP requests and the unmodified bearer token to
   Gateway, which validates Cognito issuer/signature, client ID, public MCP
   audience and tools scope before invoking modules.

The adapter publishes **OAuth metadata**, not an OIDC issuer alias. Its OAuth
server identifier and Cognito's JWT token issuer are separate. Gateway uses
Cognito's original OIDC discovery and public keys. The adapter does not expose
OIDC discovery or advertise `openid` scope. Never configure Gateway to validate
tokens against the adapter's OAuth identifier.

Authorization-response issuer identification is not advertised. Register the
exact ChatGPT callback shown by its management UI; do not assume the stable
callback or enable `authorization_response_iss_parameter_supported`.

The public client is pre-registered, without DCR or CIMD. Refresh-token rotation
is enabled with zero grace, and SDK `REFRESH_TOKEN_AUTH` is disabled. OAuth
`refresh_token` grants remain supported. Rotation does not extend the original
session validity window; sign in again after that window expires.

## Transport and access

- Public discovery has no IAM authentication. `/mcp` requires a bearer token;
  missing/malformed credentials are rejected locally. Gateway makes the actual
  authorization decision and remains JWT-protected, including audience checks.
- Stateless POST requests return JSON. GET/DELETE on `/mcp` return 405. Optional
  standalone SSE streams, sampling and elicitation are not provided.
- Upstream `Accept` is `application/json`. RPC bodies, protocol/session headers
  and safe response headers are preserved. Cookies and caller routing headers
  are dropped. 401/403 challenges point to public adapter metadata.
- Maximum input is 1 MiB; maximum upstream response is 4 MiB. Upstream timeout
  is 40 seconds and adapter Lambda timeout is 60 seconds. Keep tools within
  existing module timeouts. Redirects are never followed.
- Gateway URL configuration lives in the private schemas bucket at
  `connection/gateway.json`. The adapter reads only that object and caches it
  for 60 seconds. This avoids a circular Terraform URL/audience dependency.
  This configuration contains no secret.
- Public origin comes from AWS Function URL request context, not Host or
  forwarded headers. Upstream URLs are restricted to regional AWS Gateway
  hostnames. Bodies, tokens and exception strings are never logged by adapter code.
- A valid token for a different audience must be rejected by Gateway, even when
  issuer, client and scope otherwise match. Include this in live tests.

The extra Lambda is invoked for discovery and every MCP HTTP request. It uses
128 MiB, no provisioned concurrency, no VPC/NAT and no API Gateway. Normal
Lambda, S3 and log charges apply; rejected public requests also consume resources.

## Verification limits

Unit tests cover discovery, trusted origin, transport, challenge rewriting,
request bounds, safe errors and restricted deployment permissions. Preflight
checks public discovery and the separate Cognito token issuer.

Authorization-code redemption, negative PKCE checks, resource audience, refresh
rotation, browser client acceptance and authenticated tools require live tests.
Do not describe ChatGPT compatibility as tested until those pass.

Sources:

- [OpenAI MCP authentication](https://developers.openai.com/plugins/build/auth)
- [MCP protected-resource discovery](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#protected-resource-metadata-discovery-requirements)
- [Cognito PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html)
- [Cognito resource binding](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html)
- [Cognito refresh rotation](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-refresh-token.html)
- [AgentCore JWT validation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [AgentCore JSON and streaming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-mcp-streaming.html)
- [Function URL permissions](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html)
