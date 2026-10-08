#!/usr/bin/env python3
"""Interactively bootstrap Garmin token secret; run outside Terraform.
Requires garminconnect==0.3.17 and boto3 in a local virtual environment.
Existing secret ARN only: create an empty secret separately with AWS CLI.
"""
import argparse
import contextlib
import getpass
import io
import json
import logging
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secret-arn', required=True)
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
    email = getpass.getpass('Garmin email (hidden): ', stream=console)
    password = getpass.getpass('Garmin password: ', stream=console)
    def mfa():
        return getpass.getpass('Garmin MFA code: ', stream=console)
    try:
        # Suppress library stdout/stderr; never print raw upstream exceptions.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            client = Garmin(email=email, password=password, is_cn=args.china, prompt_mfa=mfa)
            client.login()
            tokens = json.loads(client.client.dumps())
            check = Garmin(is_cn=args.china)
            check.login(json.dumps(tokens))
            boto3.client('secretsmanager', region_name=args.region).put_secret_value(
                SecretId=args.secret_arn,
                SecretString=json.dumps({'tokens': tokens, 'is_cn': args.china}),
            )
    except Exception:
        print('Authentication or secret update failed. Check account, MFA and AWS permissions.', file=sys.stderr)
        return 1
    print('Token secret updated. No credentials were stored.')
    return 0
if __name__ == '__main__':
    sys.exit(main())
