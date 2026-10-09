# Setup navigation and migration notes

The canonical, agent-guided installation runbook is now the [README](../README.md). It covers an empty AWS account, administrator access, region activation, the exact GitHub OIDC subject, bootstrap permissions, deployment, owner creation, callback registration, client configuration, real calls and diagnostics.

Use its [copyable agent prompt](../README.md#give-this-prompt-to-your-coding-agent) to start. The agent must replace placeholders with actual outputs before handing commands to the user.

| Task | Runbook stage |
| --- | --- |
| AWS account and non-root administrator | [Stage 2](../README.md#2-create-or-reuse-an-aws-account-and-administrator) |
| Region activation and caller identity | [Stage 3](../README.md#3-enable-milan-and-verify-the-account) |
| GitHub OIDC subject | [Stage 4](../README.md#4-obtain-the-exact-github-oidc-subject) |
| Bootstrap create/update | [Stage 5](../README.md#5-bootstrap-the-deploy-role-and-state-storage) |
| Repository variables and deploy | [Stage 6](../README.md#6-set-repository-variables-and-deploy) |
| Cognito owner | [Stage 7](../README.md#7-create-the-cognito-owner) |
| ChatGPT OAuth and callback | [Stage 8](../README.md#8-create-chatgpts-app-with-correct-oauth) |
| Real calls and refresh | [Stage 9](../README.md#9-verify-real-tool-calls-and-refresh) |
| Safe logs and error recovery | [Stage 10](../README.md#10-diagnostics-and-recovery) |
| Remove the deployment | [Stage 12](../README.md#12-updates-and-removal) |

## Upgrading an older installation

Keep its original account, project, region, deployment role and state bucket/key. The README's Milan default is for new installations; it is not an instruction to relocate existing infrastructure.

1. Review/pull the current revision and check CI.
2. In an authorized administrator CloudShell session, update the existing bootstrap using its original region and project. `scripts/bootstrap.py --update` preserves parameters, including the original trust subject and provider. It does not fix an incorrect subject automatically.
3. Review the Terraform plan, then apply with the existing repository variables and state. Investigate unexpected replacement/destruction before applying.
4. Use the current `mcp_url`, client ID and `oauth_scope` from the apply summary. The current scope is the complete public MCP URL followed by `/tools`; the legacy `personal-mcp/tools` is no longer allowed for the app client.
5. Managed Login requires version 2, Essentials and client branding. Current Terraform manages these; the current bootstrap includes all provider branding/client discovery reads.
6. Register the actual callback before login. If ChatGPT's saved OAuth fields are inaccessible, recreate the client app with the current contract, recording its displayed callback before finishing. Compare rather than assuming callback reuse.
7. Perform fresh authorization; an old refresh token preserves its old audience. Verify discovery and actual tools, then report refresh separately until tested.

## Recovery and removal

A preflight failure does not roll back Terraform apply. Inspect the failed step and use the [error table](../README.md#10-diagnostics-and-recovery) before retrying.

Terraform destroy, bootstrap removal, shared OIDC provider decisions and retained versioned-state deletion are separate operations. Follow [the removal sequence](../README.md#deliberate-removal); preserve state until infrastructure removal is verified.
