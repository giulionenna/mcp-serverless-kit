# Garmin Connect on your personal AWS MCP server

This optional module adds nine read-only tools to the existing personal MCP endpoint. It follows the Garmin Connect API approach of [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp), reviewed at commit [`cfc5d799ab0f165e837f1188a1d093c65838aaf7`](https://github.com/Taxuspt/garmin_mcp/tree/cfc5d799ab0f165e837f1188a1d093c65838aaf7). That MIT-licensed project runs a FastMCP server; this kit adapts the same underlying `garminconnect` read methods to AgentCore's manifest and Lambda dispatch rather than running a stdio process in Lambda. No upstream source is vendored. The kit retains its own hash-pinned `garminconnect==0.3.17` dependency and does not install upstream's older dependency set.

## Tools

All responses use `{"data": ...}` with Garmin's original JSON. Missing measurements can be empty or null; availability depends on the device and Garmin account. Dates are explicit `YYYY-MM-DD` Garmin calendar dates. No tool changes activities, workouts or account settings.

| Gateway tool | Required arguments | Garmin method |
| --- | --- | --- |
| `garmin___daily_stats` | `date` | `get_stats(date)` |
| `garmin___sleep` | `date` | `get_sleep_data(date)` |
| `garmin___activities` | `limit`, integer 1–20 | `get_activities(0, limit)` |
| `garmin___activity` | `activity_id`, positive integer from activities | `get_activity(activity_id)` |
| `garmin___heart_rates` | `date` | `get_heart_rates(date)` |
| `garmin___stress` | `date` | `get_stress_data(date)` |
| `garmin___body_battery` | `date` | `get_body_battery(date, date)` |
| `garmin___hrv` | `date` | `get_hrv_data(date)` |
| `garmin___training_readiness` | `date` | `get_training_readiness(date)` |

## 1. Clone and install in your own account

Fork this public repository into your GitHub account, then follow [README stages 1–9](../README.md#installation-map) to deploy in your personal AWS account and verify `example___echo` and `example___add`. That runbook covers AWS administrator access, Milan region activation, the GitHub OIDC role, private Terraform state, Cognito owner login and the MCP client's exact callback. Each installation creates its own resources and credentials. No original owner's account identifiers or credentials are needed.

In AWS CloudShell, clone **your fork** using its GitHub Code → HTTPS URL and enter the checkout. For an existing installation, update that checkout to the reviewed revision and reuse its region, project and state; do not bootstrap a second installation. Commands below assume the documented defaults `eu-south-1` and `personal-mcp`; substitute your actual region/project if changed.

## 2. Enable and deploy the optional module

This checkout enables Garmin alongside the example module. For a fork or checkout that has disabled it, edit `config/modules.json` in a task branch:

```json
{"enabled": ["example", "garmin"]}
```

Open a PR, pass **Validate**, review and merge according to your fork's rules. Run **Deploy AWS MCP → plan** on `main`, inspect the changes, then run **apply** as described in the README. Expected additions include the Garmin Lambda/role/log group, tool schema/Gateway target, and an empty Secrets Manager secret. Preserve the existing example and OAuth resources. Before applying an unexpected replacement or deletion, investigate it.

Terraform creates only the secret container and passes its ARN to Lambda; it never receives the password or token values. Keep optional Garmin disabled in the generic checkout until setup is ready. Record `garmin_secret_arn` from the apply summary. If the deploy role lacks the existing Garmin secret permissions, update the current bootstrap stack through the README's administrator flow, then resume the same deployment.

## 3. Login privately from AWS CloudShell

Use an administrator session or a scoped identity with `secretsmanager:DescribeSecret` and `secretsmanager:PutSecretValue` for the deployment's Garmin secret. The Lambda role separately has only `GetSecretValue` and `PutSecretValue` on that exact secret. Do not use root or put AWS keys in GitHub.

From your fork checkout in CloudShell on Amazon Linux 2023:

```bash
sudo dnf install -y python3.12 python3.12-pip
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r scripts/garmin_login.requirements.lock
python scripts/garmin_login.py --region eu-south-1 --project personal-mcp
```

The project option resolves the **existing** `personal-mcp/garmin` secret before asking for credentials. Alternatively, use `--secret-arn` with the actual ARN from apply; that route does not require `DescribeSecret`. Never enter a password or token as a command argument. The helper requires an interactive terminal and prompts for email, password and MFA without echo, verifies the serialized session, then writes it directly to Secrets Manager. For a Garmin China account, add `--china`. Passwords are not saved; session tokens are credentials and are stored privately in AWS.

Expected success: `Session tokens stored in AWS Secrets Manager. No password or local token file was saved.` The helper does not print credential values or raw third-party errors and writes no token files. No token/password belongs in Terraform variables, state, GitHub Actions, source or chat. The session format is maintained by the helper; do not populate secret JSON manually.

System packages outside CloudShell's home may need reinstalling in a future session. [Amazon Linux Python versions](https://docs.aws.amazon.com/linux/al2023/ug/python.html).

## 4. Verify through your connected MCP client

Refresh the client's tool discovery after deploying. The existing MCP URL, Cognito owner and OAuth client stay authoritative; Garmin login is separate from MCP authorization. Use the connected app to make real calls, for example:

```text
Call garmin___activities with limit=1.
Call garmin___daily_stats with date="2026-10-09".
If the returned activity list has an activityId, call garmin___activity with that ID.
```

Choose a date with known synchronized data for your account. Verify actual tool results, not only generated prose. Test device-dependent tools against your device before claiming availability. Record the date, client and pass/fail status without publishing health data. The default CI tests use mocks and prove routing, validation and token persistence; they do not prove Garmin login or real account access. See [verification status](verification.md).

## Renewal and troubleshooting

Every call reloads the latest secret, reads Garmin data and persists changed session tokens. Lambda suppresses third-party logs and direct stdout/stderr; the client receives a safe error rather than upstream exception text. Expired/revoked sessions may require rerunning the same interactive helper. Never print the secret to debug a failure.

| Symptom | Action |
| --- | --- |
| Secret not found/inaccessible before login | Verify module apply completed, region/project and DescribeSecret permission. |
| Authentication or secret update failed | Check Garmin account/MFA and scoped PutSecretValue permission privately; rerun the helper once the cause is resolved. |
| Tool unavailable after deployment | Finish the helper login, verify the Lambda secret ARN/role, then retry a read. |
| Garmin tools absent | Verify module target deployment and refresh discovery in the existing client. |
| Empty HRV/readiness/Body Battery | Verify the device supports that measurement and has synchronized data for that date. |
| Dates/limits rejected | Use a real ISO calendar date, limit 1–20 or a positive integer activity ID. |
| Upstream Garmin login blocked | The unofficial library can be affected by Garmin API changes or AWS-origin restrictions; inspect service status and account login privately. |

Concurrent token renewal has no distributed lock. For personal sequential use, avoid parallel Garmin calls during renewal. If the account has enough concurrency quota, set GitHub variable `GARMIN_RESERVED_CONCURRENCY` to `1` and reapply to serialize calls. The default remains unreserved because AWS requires 100 units to remain unreserved; reserving one needs at least 101 available units. This is a limit, not provisioned concurrency, and carries no capacity fee. [AWS concurrency configuration](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).

All authorized users share the same Garmin account. Results reach the connected MCP client and may enter its model context. See [security](security.md). This uses unofficial Garmin Connect access, not the Garmin Health API partner program; successful login in every account/network cannot be guaranteed.

Secrets Manager has a published $0.40/month storage price plus request charges, separate from Gateway/Lambda costs. Removing Garmin from the enabled list deletes its infrastructure and schedules secret deletion with a seven-day recovery window. Reenabling during that window may require restoring/importing the secret; do not disable/re-enable as a login repair.

References: [upstream health tools](https://github.com/Taxuspt/garmin_mcp/blob/cfc5d799ab0f165e837f1188a1d093c65838aaf7/src/garmin_mcp/health_wellness.py), [upstream activity tools](https://github.com/Taxuspt/garmin_mcp/blob/cfc5d799ab0f165e837f1188a1d093c65838aaf7/src/garmin_mcp/activity_management.py), [python-garminconnect](https://github.com/cyberjunky/python-garminconnect), [Garmin developer program](https://developer.garmin.com/gc-developer-program/overview/).
