# Costs

This template uses pay-per-request AWS services, but it does not have a guaranteed $0 or fixed monthly bill. The figures below are published AWS rates and simple arithmetic, not a live estimate. Check the current pricing pages for your region and account before deploying.

## Main usage charges

- **AgentCore Gateway:** AWS lists API invocations (including tool listing and invocation) at **$0.005 per 1,000**. At that rate, **10,000 gateway operations cost $0.05**. This is arithmetic for gateway operations only, not an all-in monthly estimate. Search API and tool indexing have separate rates if enabled; they are not configured in this template. Standard network transfer charges may apply. [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- **Optional Garmin secret:** When the Garmin module is enabled, Terraform creates one Secrets Manager secret. AWS lists **$0.40 per secret per month** plus API calls; **10,000 Secrets Manager API calls cost $0.05** at the published rate. The current handler reads the secret on each Lambda invocation and writes it back when the Garmin library refreshes tokens, so invocation and refresh volume affect request charges. The secret is created empty and must be populated separately. [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/)
- **Lambda and logs:** Each tool call invokes a Lambda function. Charges depend on request count, configured memory and runtime, and log ingestion/storage. The functions are configured with 256 MB and a 30-second timeout by default; actual execution duration and log volume vary. [Lambda pricing](https://aws.amazon.com/lambda/pricing/) [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/)
- **Cognito:** User-pool pricing depends on feature plan and monthly active users. This template uses authorization-code OAuth; client-credentials M2M pricing does not describe this flow. Consult the regional pricing page for the selected user-pool plan. [Cognito pricing](https://aws.amazon.com/cognito/pricing/)
- **Other metered services:** S3 stores tool schemas; data transfer and other account-level charges may apply. S3's baseline SSE-S3 encryption has no additional charge. [S3 pricing](https://aws.amazon.com/s3/pricing/) [S3 default encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html)

The template does not deploy a continuously running compute instance. At very low usage, Gateway invocation charges are small, but Cognito, the optional secret, Lambda, logs, storage, and transfer still determine the bill. Enable AWS Budgets or billing alerts before sharing a live deployment.

## What Terraform creates

When Garmin is enabled, Terraform additionally creates a Secrets Manager secret; the secret has a seven-day recovery window on deletion. The schema bucket is encrypted and private, but it is an S3 schema bucket, not a Terraform state backend. The optional bootstrap CloudFormation stack creates a separate encrypted, private, versioned state bucket and a GitHub OIDC deployment role; configure Terraform with that bucket to use remote state. S3 storage and requests for state incur their own usage charges.

There is no cost total here because the eventual amount depends on region, Cognito plan and users, Gateway and Lambda calls, execution time, CloudWatch usage, optional Garmin secret reads, and network transfer. Use the AWS Pricing Calculator with your expected usage to estimate a deployment. [AWS Pricing Calculator](https://calculator.aws/)
