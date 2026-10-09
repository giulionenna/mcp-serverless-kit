# Instructions for coding agents

## Start here

This repository deploys a personal, single-owner MCP service using AWS
Bedrock AgentCore Gateway, Lambda, Cognito, S3 and GitHub Actions OIDC.
Use this file for development and review. Use [README.md](README.md) as the
step-by-step installation runbook, including AWS account/admin setup,
bootstrap, OAuth client configuration, diagnostics and recovery.

Before changing anything:

1. Inspect the current checkout, branch, working-tree changes and relevant files.
   Preserve user changes; do not assume the deployment matches this checkout.
2. Read the README and the focused documentation for the requested task.
3. Determine whether the task is code development, installation or live diagnosis.
   Repository access alone grants neither AWS access nor client-settings access.
4. Reuse existing stacks, state and client configuration. Resolve identifiers from
   actual outputs instead of guessing or copying another installation's values.

Keep implementation and documentation in English, following repository style.
Explain results to the user in their preferred language. Make routine technical
choices yourself and give the user one concrete step at a time when their action
is necessary. Report missing access or tools precisely rather than pretending a
verification succeeded.

## Repository map

| Path | Responsibility |
| --- | --- |
| `config/modules.json` | Enabled modules; starts with `example` |
| `modules/<name>/manifest.json` | Tool names, descriptions and JSON Schema contract |
| `modules/<name>/handler.py` | Module implementations and Lambda entry point |
| `modules/<name>/requirements.lock` | Module dependencies, pinned with hashes |
| `runtime/gateway.py` | Shared argument validation and safe tool dispatch |
| `runtime/oauth_compat.py` | Public OAuth metadata and MCP compatibility proxy |
| `runtime/requirements.lock` | Shared module runtime dependencies |
| `infra/` | Terraform deployment and committed provider lockfile |
| `bootstrap/github-oidc.yaml` | CloudFormation deployment role and state bucket |
| `scripts/` | Build, bootstrap, owner setup, preflight and connection helpers |
| `.github/workflows/` | Validation, manual deployment, OIDC subject and diagnostics |
| `tests/` | Runtime, module, setup and bootstrap policy tests |

Consult [modules](docs/modules.md), [OAuth adapter](docs/oauth-compat.md),
[security](docs/security.md), [Garmin](docs/garmin.md) and
[verification](docs/verification.md) as appropriate.

## Development and checks

Use Python 3.12 and Terraform 1.13.4 to match CI. Lambda packages target
Python 3.12 on x86_64, with `manylinux2014_x86_64` binary wheels.
From the repository root, CI's validation sequence is:

```bash
python -m pip install pytest==8.3.5 jsonschema==4.23.0 PyYAML==6.0.2
python -m pytest -q
python scripts/build.py
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra validate
```

Use an isolated Python environment when needed. Terraform initialization above
disables the backend and requires no deployment credentials; it still needs
provider downloads or an appropriate cache. Build needs verified wheels or
`--wheelhouse PATH`. Do not bypass checksums to work around network restrictions.
Report checks that could not run and their reason.

- Run focused tests while iterating and the relevant CI checks before publishing
  runtime, infrastructure, dependency or workflow changes.
- For documentation-only changes, verify paths, commands and Markdown against
  the source. Do not add tests that merely assert documentation text.
- Add meaningful regression tests for changed behavior and failure paths. Mock
  service calls in unit tests; do not require real accounts or credentials.
- Keep dependencies exactly pinned with SHA-256 hashes, including transitive
  packages. Preserve `infra/.terraform.lock.hcl`; update it intentionally when
  changing providers. Do not use `init -upgrade` as a routine repair.
- Generated ZIPs belong in ignored `dist/`; do not commit them or runtime caches.

## Tool contract and modules

The manifest is the tool contract. Use unique lowercase module/tool identifiers
and closed object input schemas (`additionalProperties: false`). Match callable
argument names to the schema. Only local schema references are supported;
the dispatcher does not inject JSON Schema defaults.

AgentCore passes arguments directly as the Lambda event. The selected tool is
in `context.client_context.custom['bedrockAgentCoreToolName']`, with names such
as `example___echo`. Use `runtime.gateway.dispatch`; do not return an API Gateway
HTTP envelope from module handlers. Preserve safe errors and nonfinite JSON
rejection. Check the service's schema support as well as local validation.

New modules require a manifest, handler and lockfile. Module-specific secrets,
resources and IAM need explicit Terraform changes; manifests do not grant IAM.
Keep optional modules disabled until their setup and validation are complete.
Removing an enabled module can delete its deployed resources, including a
scheduled Garmin secret deletion. Review that impact before changing the list.

Separate client-facing MCP apps under one Gateway are a planned extension in
[issue #5](https://github.com/giulionenna/mcp-serverless-kit/issues/5), not current
behavior. Do not claim filtered endpoints or per-module authorization already
exist. Implement that scope only when requested.

## AWS and OAuth invariants

- The installation default is `eu-south-1` (Milan), project `personal-mcp`.
  Derive the actual installation values and always pass the selected region
  explicitly. Bootstrap and Terraform have different fallback regions.
- Keep one account, project, state bucket and `terraform.tfstate` key consistent.
  Schema storage and Terraform state storage are different buckets. Never
  force-unlock, delete or replace state as a routine error recovery step.
- The public compatibility Lambda exposes `/mcp`. Cognito issues tokens;
  AgentCore Gateway validates them. Use the public MCP URL in clients, not the
  upstream Gateway URL. Preserve the adapter's supported protocol/discovery paths.
- The exact public `mcp_url` is the OAuth resource, access-token audience and
  Cognito resource-server identifier. The custom scope is `mcp_url + /tools`.
  Do not revert to the legacy `personal-mcp/tools` scope or accept unbound tokens.
- Preserve Cognito Essentials, Managed Login version 2 and client branding for
  resource binding. Keep authorization code with PKCE S256, static public-client
  registration, no client secret and token endpoint authentication `none`.
  Do not add Dynamic Client Registration or `offline_access` without an explicit
  design change supported by the provider.
- Obtain each client's actual callback before completing app creation. Register
  that exact HTTPS URL, preserve existing required callbacks and deploy the
  configuration before login. No wildcards or guessed callback IDs.
- After scope/audience changes, require fresh authorization; old refresh tokens
  retain their original binding. Never weaken issuer, client, scope, audience or
  signature checks to make discovery succeed.
- Keep public signup disabled. This is single-owner infrastructure: authorized
  users share tools and external data; it is not a tenant-isolated service.

## GitHub and deployment

Use a task branch and pull request for changes. Inspect current repository rules
and respect required reviews/checks; never disable protection, add a bypass or
push directly to `main` to get around a blocked merge. A PR author cannot satisfy
their own required approving review. Do not merge solely because a PR was opened.

`Validate` runs on pushes and PRs with read-only repository permissions and no AWS
credentials. `Deploy AWS MCP` is manually dispatched on `main` with `plan`,
`apply` or `destroy`. Deployment and diagnostics use the OIDC deployment role.
Keep OIDC trust scoped to the actual repository/branch subject and audience
`sts.amazonaws.com`; obtain the subject from the dedicated workflow, never guess
its format or widen trust to forks/untrusted PRs.

Code changes alone do not request a production deployment. For an authorized
deployment, follow the README: check validation, inspect the plan, investigate
unexpected replacements/deletions, then apply and check outputs/preflight.
Apply creates a fresh saved plan; the earlier plan run is only a preview.
Bootstrap updates use an authorized administrator and the current template;
the GitHub role cannot perform owner password administration. Prepare any
necessary fix before asking for missing authorization. Teardown requires explicit
intent to remove the deployment.

## Secrets, diagnostics and evidence

Never commit or paste passwords, AWS keys, bearer/refresh tokens, populated
Terraform variables, state or plan files. Keep installation-specific identifiers
out of generic instructions. Use temporary authorized AWS sessions/OIDC and
private secret storage. Human login/password entry stays in secure interactive
flows, not chat, command arguments or tracked files.

Preserve safe diagnostic events: method, status and boolean token checks.
Do not log raw headers, tokens, claims, upstream exception bodies or personal tool
results. GitHub Actions logs in a public repository are public. Prefer the existing
`MCP diagnostics` snapshot/follow workflow or scoped CloudWatch reads and the
README recovery table over repeated blind retries or expanded logging.

Distinguish tests passed, infrastructure applied, metadata checked, authentication
accepted, tools discovered and tools actually called. Report real `echo`/`add`
results separately from refresh after expiry, Claude and Garmin verification.
Update relevant docs when behavior changes and leave untested scenarios pending.
In the final report, state what changed, checks performed and any remaining
blocker, with a PR link when published.
