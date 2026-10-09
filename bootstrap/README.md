This optional CloudFormation stack creates an encrypted, private, versioned Terraform state bucket and a GitHub OIDC role. Launch `github-oidc.yaml` with the AWS console (acknowledge `CAPABILITY_NAMED_IAM`). No AWS access key is needed in GitHub.

Supply `ProjectName` matching Terraform and `GitHubSubject` matching the **exact** GitHub token subject for the deployment job. New GitHub repository subjects may include immutable organization/repository IDs; older examples such as `repo:owner/repo:ref:refs/heads/main` are not universal. An environment-enabled job has a different subject. Set `ExistingOidcProviderArn` when your AWS account already has the GitHub OIDC provider.

Copy stack outputs into GitHub repository variables: `AWS_ROLE_ARN` from `DeploymentRoleArn`, `TF_STATE_BUCKET` from `StateBucketName`, and `AWS_REGION` from `AWSRegion`. Initialize Terraform with `-backend-config=bucket=... -backend-config=key=terraform.tfstate -backend-config=region=... -backend-config=use_lockfile=true`. Terraform 1.10+ uses S3 lock files without a DynamoDB table.

Review the role policy: it is a practical deployment starter, not a strong isolation boundary. IAM role editing allows privilege escalation through the kit gateway and module execution roles. Cognito and Gateway creation/manage operations are account-wide within the chosen region because AWS assigns resource IDs. Grant repository write access only to people you trust with deployment privileges, protect main, and do not expose this role to untrusted pull request code. For stronger isolation use a dedicated AWS account, an administrator-defined permissions boundary, and further policy refinement after first deployment.

State persists when the bootstrap stack is deleted. Delete retained state only after destroying kit infrastructure and verifying no state is needed. Garmin secret values are populated separately and are never read by the deployment role or Terraform.

The AWS-only OAuth adapter needs Function URL create/read/update/delete and Lambda
permission create/remove operations. These are restricted to the single
`${ProjectName}-oauth-compat` function in this account/region. Public discovery
is intentional; Gateway still validates every tool request's JWT. Existing
installations must update this stack before applying the adapter revision.

Gateway lifecycle operations create and manage a workload identity on the caller's behalf. The deployment role includes `CreateWorkloadIdentity`, `GetWorkloadIdentity`, `UpdateWorkloadIdentity`, and `DeleteWorkloadIdentity` on both the default directory ARN and its child identity ARNs in this account and region. AWS requires both resource types. The service assigns identity names, so this statement is not project-prefix scoped. `SynchronizeGatewayTargets` is scoped to gateways in this account and region and is a dependency of Gateway/target creation and target updates. The policy grants no workload access tokens or credential-provider operations. See [AWS service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html).
