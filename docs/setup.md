# Browser-only setup

Use this from a fork in your own GitHub account and your own AWS account. No code needs to run on your computer. The current preview has not yet been deployed or connected to ChatGPT/Claude; follow the verification gates below rather than assuming success.

## Prerequisites

- AWS IAM user/role with permission for the initial CloudFormation stack, IAM OIDC provider/role, and S3 bucket. The stack template defines the narrower subsequent deployment role. Do not use root.
- The CloudShell identity also needs `cognito-idp:AdminCreateUser` and `cognito-idp:AdminSetUserPassword` for the deployed pool to configure its owner. These are not granted to the GitHub deployment role. Garmin login additionally needs `secretsmanager:PutSecretValue` for its secret.
- GitHub Actions enabled on your fork; `main` is the deployment branch.
- Access to custom remote MCP connections in the client you intend to use. Client availability and UI labels depend on account/workspace settings.
- An AWS region supporting AgentCore Gateway. The examples use `eu-west-1`; check [current service availability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html).

## 1. Find your exact OIDC subject

Open **Actions → Show AWS OIDC subject → Run workflow**, choose `main`, and copy `GitHubSubject` from its summary. The workflow prints only the subject claim, never the OIDC token.

New repositories can use immutable IDs in their subject. Do not copy an old `repo:owner/name:ref:refs/heads/main` example unless it exactly matches your workflow. Deploy jobs use the main branch, with no GitHub environment. Changing that changes the subject and requires updating the AWS trust policy.

## 2. Bootstrap AWS in CloudShell

Sign in to AWS as your IAM user/role. Open CloudShell from the console and paste these commands with **your fork URL**:

```bash
git clone https://github.com/YOUR-USERNAME/mcp-serverless-kit.git
cd mcp-serverless-kit
python3 scripts/bootstrap.py --region eu-west-1
```

The helper prints the AWS account and region, asks for the exact GitHub subject, detects an existing account-wide GitHub OIDC provider, and creates `personal-mcp-bootstrap`. AWS credentials are inherited from your CloudShell session.

CloudShell normally includes Boto3. If it does not, install it in a virtual environment and run the helper there. You may also upload `bootstrap/github-oidc.yaml` directly to CloudFormation, acknowledge creation of named IAM resources, and provide the same parameters. [Bootstrap policy details](../bootstrap/README.md).

If the stack already exists, inspect its outputs instead of recreating it. If creation fails, use the CloudFormation Events tab to find the failing resource. Do not delete an account-wide OIDC provider used by other projects.

### Update bootstrap permissions

If a deployment reports a missing permission, update the bootstrap from the same
IAM CloudShell session after pulling the reviewed fix:

```bash
git pull --ff-only
python3 scripts/bootstrap.py --region eu-west-1 --update
```

Use your original bootstrap region. The helper preserves all CloudFormation
parameter values, including the exact GitHub subject and shared OIDC provider.
It updates the existing stack without deleting the Terraform state bucket. The
first live deployment found that the pinned provider also reads
`cognito-idp:GetUserPoolMfaConfig`; this permission is included in the bootstrap.
Gateway creation also creates an AgentCore workload identity on the caller's
behalf. The bootstrap includes its create/read/update/delete lifecycle actions,
limited to the default workload identity directory and its child identities in
this account and region. AWS evaluates these actions against both resource
types; a policy covering only child identities fails. Gateway target
synchronization is also permitted for gateways in this account and region,
as required by the Gateway create/target create/target update APIs. See the
[AWS service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html).
It grants no workload-token or credential-provider access. See
[AWS Gateway permissions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html).
After the update completes, rerun the failed `apply` so Terraform resumes from
its saved state. The pinned provider retains and taints a Gateway that fails
during creation, allowing Terraform to remove it before retrying.

## 3. Set GitHub repository variables

Open **Settings → Secrets and variables → Actions → Variables** in your fork.

| Variable | Value |
| --- | --- |
| `AWS_ROLE_ARN` | Bootstrap `DeploymentRoleArn` |
| `TF_STATE_BUCKET` | Bootstrap `StateBucketName` |
| `AWS_REGION` | Bootstrap region, e.g. `eu-west-1` |
| `MCP_PROJECT_NAME` | `personal-mcp`, matching the bootstrap parameter |
| `MCP_CALLBACK_URLS` | Optional JSON array of exact client callbacks |
| `GARMIN_RESERVED_CONCURRENCY` | Optional `1` if account quota permits; default `-1` |

These values are identifiers/configuration, not passwords. Do not add AWS access keys or Garmin credentials.

Without `MCP_CALLBACK_URLS`, the workflow allows the documented Claude callback URLs `https://claude.ai/api/mcp/auth_callback` and `https://claude.com/api/mcp/auth_callback`. For ChatGPT, copy the **exact** redirect URI from its MCP management page; the URI may be per-connection. Add it to the JSON list and reapply. Never use `{callback_id}` literally or allow a wildcard.

## 4. Deploy

Open **Actions → Deploy AWS MCP**, select `main`, and run operation `plan`. Review the resources and IAM changes in the run. Run it again with `apply`.

Deployment is manual: a fork or ordinary push does not create AWS charges. Both operations build selected module packages and validate configuration before assuming the AWS role. The same private S3 backend and lockfile are used for updates and removal.

The apply summary lists the endpoint, client ID, scope, user pool ID, and authorization/token endpoints. Those are public connection identifiers; no token or password is printed.

The final preflight reads live metadata. If it fails, resources may already exist: **a failed preflight does not roll back Terraform apply**. Inspect the failure, resolve it, or run `destroy` while investigating. If Cognito omits PKCE `S256` discovery metadata, do not disable authentication to get around the problem. A different authorization-server configuration or a tested compatibility layer is required; this preview does not ship such a layer.

## 5. Create your owner

In the same CloudShell checkout, use the pool ID from the apply summary:

```bash
python3 scripts/create_owner.py --region eu-west-1 --pool-id YOUR-POOL-ID
```

The helper prompts for email and a hidden password, creates a single owner, and sends no email. It will not overwrite an existing owner's password. Keep signup disabled: all authorized users of this deployment access the same modules and data.

If the user was created but password configuration failed, fix the IAM/password issue and rerun the same command with `--reset-password`. That flag explicitly replaces an existing owner's password; the ordinary command will not.

## 6. Connect a client

### ChatGPT

Create a custom remote MCP connection in the available developer/plugin settings. Use the apply summary's MCP URL and OAuth authentication with the preconfigured client ID. The kit uses a public client with no client secret; verify that the current setup UI accepts this configuration.

Copy the displayed redirect URI into `MCP_CALLBACK_URLS`, retaining any other callbacks you need, and reapply before completing login. Sign in with the Cognito owner you created. Request the configured scope; Cognito authorization-code grants issue refresh tokens without requesting `offline_access`.

Follow [OpenAI's current MCP setup](https://developers.openai.com/api/docs/guides/custom-mcp-server) and [OAuth requirements](https://developers.openai.com/plugins/build/auth). Do not claim success until a real tool call and refresh work. If your UI insists on a client secret, this public-client path needs adjustment before use.

### Claude

Create a custom connector with the endpoint URL. Use its advanced/static OAuth client configuration for the Cognito client ID. This preview uses no client secret; verify public-client acceptance in the actual interface. Sign in with the owner.

Use the exact callbacks documented in [Claude custom connectors](https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers). Claude.ai connectors and the Claude API's MCP connector have different authentication setup; the API does not automatically perform this browser flow for you.

### Other clients

Use Streamable HTTP, the configured OAuth client ID, authorization-code + PKCE, the custom tools scope, and an explicitly registered HTTPS callback. Cognito does not provide dynamic client registration. This template does not automatically register arbitrary clients.

## Remove the deployment

1. Run **Deploy AWS MCP → destroy** on `main` using the existing role and state bucket configuration. It removes the Gateway, targets, Lambdas, Cognito and schema bucket, and schedules the optional Garmin secret for deletion with a seven-day recovery window.
2. Confirm completion and disconnect client connections. A failed destroy may leave resources; inspect the run rather than assuming costs stopped.
3. Keep the private state until removal is verified. The bootstrap stack and versioned state bucket are separate from Terraform and deliberately retained.
4. When finished, delete the bootstrap stack in CloudFormation. If it created the account-wide GitHub OIDC provider, first check whether other repositories now rely on it. Preserve/shared-provider users should supply its existing ARN when bootstrapping.
5. Delete the retained state bucket only after removing its object versions and deletion markers. This permanently removes recovery history. Also check Secrets Manager after its recovery period.
