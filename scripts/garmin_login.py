#!/usr/bin/env python3
"""Interactively bootstrap Garmin token secret; run outside Terraform.
Requires garminconnect==0.3.17 and boto3 in a local virtual environment.
Uses the existing Terraform secret; does not create infrastructure.
"""
import argparse
import contextlib
import getpass
import json
import logging
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--secret-arn', help='Existing Terraform secret ARN')
    target.add_argument('--project', help='Terraform project name; resolves its existing Garmin secret')
    parser.add_argument('--region', required=True)
    parser.add_argument('--china', action='store_true')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print('Interactive terminal required for hidden credentials and MFA prompts.', file=sys.stderr)
        return 1
    console = sys.stderr
    import boto3
    from garminconnect import Garmin
    logging.disable(logging.CRITICAL)
    secrets = boto3.client('secretsmanager', region_name=args.region)
    try:
        arn = args.secret_arn or secrets.describe_secret(SecretId=args.project + '/garmin')['ARN']
    except Exception:
        print('Existing Garmin secret not found or inaccessible. Enable and deploy the module first.', file=console)
        return 1
    email = getpass.getpass('Garmin email (hidden): ', stream=console)
    password = getpass.getpass('Garmin password: ', stream=console)
    def mfa():
        return getpass.getpass('Garmin MFA code: ', stream=console)
    stage = 'Garmin account login'
    try:
        # Suppress library stdout/stderr; never print raw upstream exceptions.
        # Discard dependency output instead of keeping sensitive text in buffers.
        with open('/dev/null', 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            client = Garmin(email=email, password=password, is_cn=args.china, prompt_mfa=mfa)
            client.login()
            stage = 'Garmin session serialization'
            tokens = json.loads(client.client.dumps())
            stage = 'Garmin session verification'
            check = Garmin(is_cn=args.china)
            check.login(json.dumps(tokens))
            tokens = json.loads(check.client.dumps())
            stage = 'AWS Secrets Manager update'
            secrets.put_secret_value(
                SecretId=arn,
                SecretString=json.dumps({'tokens': tokens, 'is_cn': args.china}),
            )
    except Exception as error:
        # Exception class and bounded HTTP status are useful; exception text,
        # response bodies and arbitrary AWS error codes can contain secrets.
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        detail = type(error).__name__
        if type(status) is int and 100 <= status <= 599:
            detail += f', HTTP {status}'
        print(f'{stage} failed ({detail}). No credentials or response body were printed.', file=console)
        if stage == 'AWS Secrets Manager update':
            print('Check secretsmanager:PutSecretValue permission for the existing Garmin secret.', file=console)
        else:
            print('Check Garmin account/MFA and connectivity. The AWS secret was not updated.', file=console)
        return 1
    print('Session tokens stored in AWS Secrets Manager. No password or local token file was saved.')
    return 0
if __name__ == '__main__':
    sys.exit(main())
