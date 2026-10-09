# Verification status

This development preview distinguishes local tests from a deployed service and client compatibility. Update this file only with evidence from an actual run.

| Check | Current status |
| --- | --- |
| Gateway Lambda event/context adapter | Unit-tested using the documented AWS contract |
| Input schemas, invalid arguments, safe errors and nonfinite results | Unit-tested |
| Garmin token load/refresh persistence and hidden MFA prompt routing | Mock-tested |
| Example package reproducibility | Tested with fixed ZIP entries and the same wheel inputs |
| Garmin ZIP build and dependency imports | Tested on Python 3.12 Linux x86_64 |
| Terraform formatting | Passed |
| Terraform provider schema validation | Original revision passed GitHub CI; adapter revision must pass CI before deployment |
| Actual AWS apply / update / destroy | Original apply completed in eu-south-1; adapter update and destroy pending |
| Live Gateway JWT rejection / metadata / authenticated tool calls | Original unauthenticated rejection and resource metadata passed; authenticated calls pending |
| AWS-only OAuth adapter | Unit-tested; live deployment/discovery and browser OAuth pending |
| Cognito browser authorization, PKCE and refresh | Pending |
| ChatGPT / Claude real connection | Pending |
| Real Garmin account read | Pending |

The original 39-test revision passed GitHub CI on 2026-10-09. Adapter regression
coverage adds public OAuth discovery, trusted origin, request forwarding,
challenge rewriting, body limits, safe exceptions, upstream host restrictions,
deterministic packaging and scoped Function URL deployment permissions. Automated
results for the adapter must be checked in its `Validate` workflow.

## Live evidence: original deployment, 2026-10-09

- Region: `eu-south-1`; Terraform 1.13.4, AWS provider 6.54.0.
- Original [CI run 37917097645](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/37917097645) passed all 39 tests, build, formatting and provider validation.
- [Apply run 37917455561](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/37917455561), job 113777014801, completed Terraform apply, creating the Gateway and example target.
- Its final metadata preflight failed because the actual Cognito OIDC document
  did not advertise PKCE S256. Infrastructure was not rolled back.
- No owner login, token refresh, authenticated tool call or ChatGPT/Claude
  connection has been verified. The adapter revision still requires bootstrap
  permission update, deployment and live verification.

## GitHub CI gate

The `Validate` workflow installs the pinned Terraform provider with its committed lockfile, runs formatting/schema validation and Python tests, and builds enabled modules. It uses no AWS credentials. CI success is required before deploying.

If provider initialization fails a checksum verification, investigate the lock and signed package source; do not disable checksum verification as a workaround.

## Deployed-service gate

The apply workflow reads Terraform outputs into an ignored local file, publishes only allowlisted nonsensitive connection identifiers, and runs `scripts/preflight.py`. The preflight checks:

- An unauthenticated MCP initialize request gets 401 with OAuth resource metadata.
- Public protected-resource metadata advertises the configured OAuth server and resource identifier.
- RFC 8414 OAuth metadata (preferred) or OIDC discovery contains secure endpoints and `code_challenge_methods_supported` with `S256`.
- Requested scopes and public-client token authentication are advertised.
- Adapter authorization/token endpoints match the actual configured Cognito endpoints.
- The separate Cognito token issuer and public-key endpoint are consistent.

A failed preflight leaves applied resources in place. It does not imply Terraform rolled back. Diagnose or destroy them. Cognito may support PKCE while omitting the discovery field; this is a real interoperability gate, not a reason to skip authentication.

## Client gate

For each intended client, verify:

1. The preconfigured public OAuth client is accepted in its UI.
2. Its exact redirect URI is allowed; authorization uses PKCE S256.
3. Owner login completes and the access token is accepted by Gateway.
4. `tools/list` includes `example___echo` and `example___add`.
5. `tools/call` returns the requested echo and a correct sum.
6. Token refresh works after access-token expiry.
7. Missing/expired/wrong-client/wrong-scope/wrong-audience tokens are rejected.
8. If Garmin is enabled, a real readonly call succeeds and token renewal persists.
9. Updating a schema and disabling a module produces the expected deployed changes.
10. Destroy completes and expected retained resources are identified.

Record run URLs, dates, region, Terraform/provider versions and client/account configuration when these pass. Avoid uploading response bodies containing personal health data or tokens as public CI artifacts.
