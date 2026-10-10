# Verification status

Evidence for one installation does not automatically prove compatibility for every fork, client or external account. Follow the [README's setup gates](../README.md#installation-map) for each new installation.

## Current evidence, 2026-10-10

| Check | Evidence/status |
| --- | --- |
| Python regression checks, including bootstrap resource/region scoping | 122 tests passed in login-diagnostics CI; 119 tests passed in the Garmin apply workflow |
| Build, Terraform formatting/provider schema validation | Passed in CI with Terraform 1.13.4 and AWS provider 6.54.0 |
| AWS deployment/update | Garmin activation completed in `eu-south-1`: 8 added, 2 changed, 0 destroyed |
| Public OAuth/protected-resource metadata, PKCE S256 advertisement, missing-token 401 | Final workflow preflight passed |
| URL-bound scope with resource and registered callback | Credential-free authorization probe redirected to Cognito login without OAuth error; this alone is not a login or tool test |
| ChatGPT OAuth, discovery and example tools | Owner reported everything working after creating/configuring Personal MCP v2; user-reported live result, not an independently captured authenticated trace |
| Adapter CloudWatch diagnostics through GitHub OIDC | Snapshot workflows succeeded; empty windows are not OAuth-success evidence |
| Refresh after access-token expiry | Pending live verification |
| Claude or other client authorization/tools | Pending live verification |
| Real Garmin account reads | Recent-activities read succeeded through Lambda; owner confirmed discovery and successful tool use from a fresh ChatGPT conversation on 2026-10-10 |
| Garmin session renewal/concurrent renewal | Pending live verification |
| Complete destroy and retained-resource cleanup | Pending live verification |

- [Validate run 37950293793](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/37950293793): 94 tests and build/provider checks succeeded.
- [Apply run 37951962703](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/37951962703): bootstrap branding permissions were complete; resource server/client/Gateway/adapter configuration updated; connection summary and final preflight succeeded.
- [Diagnostics run 37952691958](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/37952691958): scoped adapter-log read succeeded.
- The owner confirmed the working ChatGPT setup on 2026-10-09 after these changes. No password, token or personal tool-result body is included in this evidence.

## Garmin integration checks, 2026-10-10

- Garmin activation [PR #9](https://github.com/giulionenna/mcp-serverless-kit/pull/9) enables `example` and `garmin`. The deployment workflow now uses GitHub web identity without external Actions, respecting the repository's owner-only Actions policy.
- [Main validation run 38050624165](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/38050624165) passed 119 tests, hash-verified builds, login dependency checks and Terraform 1.13.4 / AWS provider validation. The login-diagnostics [PR #10 validation run 38052021574](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/38052021574) subsequently passed 122 tests and the same checks.
- [Plan run 38050693672](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/38050693672) and [apply run 38050799414](https://github.com/giulionenna/mcp-serverless-kit/actions/runs/38050799414) succeeded: 8 resources added, 2 changed, 0 destroyed. The apply's OAuth preflight passed. Actual connected-client `echo` and `add(2, 3)` calls still succeeded after deployment.
- The owner completed the private interactive Garmin login. A Secrets Manager metadata read confirmed that a session version exists; no secret value was printed. An independent synchronous invocation of the deployed Garmin Lambda with `activities(limit=1)` returned a valid activity list. Only success status was recorded, without health data.
- The owner then confirmed Garmin tools are visible and work from a fresh ordinary ChatGPT conversation. This is user-reported MCP client evidence; individual per-tool results were not independently captured. The Lambda read above is a separate independently observed account-read check.
- The owner reported large returned payloads. Size measurements and optimization are deferred in [issue #11](https://github.com/giulionenna/mcp-serverless-kit/issues/11); no transport-limit failure has been established.
- Garmin renewal/concurrency and OAuth refresh after expiry remain pending. Follow [the Garmin runbook](garmin.md) for each personal account; one successful installation does not establish universal account/device/client compatibility.

## What earlier failures established

The first direct-Cognito discovery lacked PKCE S256 metadata. Adding the public adapter resolved that metadata contract. Function URLs remapped `WWW-Authenticate`, so the preflight/client path uses standard well-known discovery fallback. Successful infrastructure apply did not automatically imply a successful client flow.

An access token accepted as the right kind/issuer/client/scope could still fail Gateway audience validation. Managed Login v2, Essentials and client branding were needed for resource binding. The legacy `personal-mcp/tools` scope belonged to the project-name resource server, not the requested public MCP URL; the corrected scope belongs to the URL resource. Old refresh tokens required fresh authorization. Current bootstrap includes provider reads such as `ListUserPoolClients` and `DescribeManagedLoginBrandingByClient` that were missing during migration.

These were setup/deployment failures, not reasons to weaken JWT verification, PKCE or callback restrictions. The [README recovery table](../README.md#symptom-to-next-action) records the corresponding actions.

## CI gate

`Validate` uses no AWS credentials. It runs tests, builds enabled modules, checks Terraform formatting and initializes/validates with the committed provider lock. Investigate provider/package checksum failures; never disable verification to get a green run.

## Deployed-service gate

The deploy workflow prints allowlisted public connection identifiers and runs `scripts/preflight.py`. It checks unauthenticated rejection, public resource/server metadata, the exact MCP resource and custom scope, PKCE S256, public-client authentication `none`, actual Cognito OAuth endpoints and the separate token issuer/JWKS metadata.

A failed preflight may leave applied infrastructure. Diagnose or intentionally remove it; do not assume rollback. Reaching a Cognito login redirect with a synthetic state/PKCE challenge is only a pre-login contract check, not code redemption, a refresh test or a real client connection.

## Client and lifecycle checklist

For each intended client, record actual evidence for:

1. Static public-client configuration accepted by the UI.
2. Exact callback registered before login; authorization uses PKCE S256.
3. Owner login and Gateway acceptance of the access token.
4. Discovery includes `example___echo` and `example___add`.
5. Actual calls return the requested echo and correct sum.
6. A call after access-token expiry renews access without another owner login.
7. Missing/expired/wrong-client/wrong-scope/wrong-audience tokens are rejected.
8. If Garmin is enabled, real read-only access and token-renewal persistence.
9. Schema updates and module disablement produce the intended deployed changes.
10. Destroy completes and deliberately retained resources are identified.

Report checks as passed, failed or pending separately. Record date, region, client and run references without uploading private credentials, state or personal health data to public logs/issues/artifacts.
