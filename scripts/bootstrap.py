#!/usr/bin/env python3
"""Create the initial AWS trust/state stack from CloudShell; requires no local coding."""
import argparse
from pathlib import Path
import re
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', default='eu-west-1')
    parser.add_argument('--project', default='personal-mcp')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit('Run bootstrap in interactive AWS CloudShell.')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,24}', args.project):
        raise SystemExit('Invalid project name.')
    import boto3
    from botocore.exceptions import ClientError
    identity = boto3.client('sts', region_name=args.region).get_caller_identity()
    print('AWS account:', identity['Account'])
    print('AWS region:', args.region)
    if identity['Arn'].endswith(':root'):
        raise SystemExit('Sign in to CloudShell as your IAM user or role rather than root.')
    subject = input('Paste GitHubSubject from the Show AWS OIDC subject workflow summary: ').strip()
    if not subject.startswith('repo:') or not subject.endswith(':ref:refs/heads/main') or '*' in subject:
        raise SystemExit('Use the exact main-branch subject printed by the workflow.')
    existing = 'arn:aws:iam::' + identity['Account'] + ':oidc-provider/token.actions.githubusercontent.com'
    iam = boto3.client('iam', region_name=args.region)
    try:
        iam.get_open_id_connect_provider(OpenIDConnectProviderArn=existing)
    except ClientError as error:
        if error.response['Error']['Code'] == 'NoSuchEntity':
            existing = ''
        else:
            raise SystemExit('Cannot check the existing OIDC provider. Verify IAM permissions.')
    cf = boto3.client('cloudformation', region_name=args.region)
    stack = args.project + '-bootstrap'
    template = (Path(__file__).resolve().parents[1] / 'bootstrap/github-oidc.yaml').read_text()
    print('Creating', stack, '(IAM deployment role and private Terraform state bucket).')
    try:
        cf.create_stack(StackName=stack, TemplateBody=template, Parameters=[{'ParameterKey':'ProjectName','ParameterValue':args.project},{'ParameterKey':'GitHubSubject','ParameterValue':subject},{'ParameterKey':'ExistingOidcProviderArn','ParameterValue':existing}], Capabilities=['CAPABILITY_NAMED_IAM'])
        print('Waiting for CloudFormation; usually a few minutes.')
        cf.get_waiter('stack_create_complete').wait(StackName=stack)
    except Exception:
        raise SystemExit('Bootstrap did not complete. Inspect the CloudFormation stack events; if it already exists, use its outputs instead of recreating it.')
    outputs = {x['OutputKey']:x['OutputValue'] for x in cf.describe_stacks(StackName=stack)['Stacks'][0]['Outputs']}
    print('\nAdd these GitHub Actions repository variables (not secrets):')
    for name,key in [('AWS_ROLE_ARN','DeploymentRoleArn'),('TF_STATE_BUCKET','StateBucketName'),('AWS_REGION','AWSRegion')]:
        print(name + '=' + outputs[key])
    print('MCP_PROJECT_NAME=' + args.project)
    print('Next: run Deploy AWS MCP with operation plan, review it, then apply.')

if __name__ == '__main__':
    main()
