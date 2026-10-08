#!/usr/bin/env python3
"""Create a single Cognito owner interactively in AWS CloudShell, without sending email."""
import argparse
import getpass
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool-id', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--reset-password', action='store_true', help='Explicitly set a new password for an existing owner, including a partially created owner.')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit('Use an interactive terminal so the password cannot be echoed.')
    import boto3
    from botocore.exceptions import ClientError
    email = input('Owner email: ').strip()
    password = getpass.getpass('Choose a password (at least 14 characters, upper/lowercase, number and symbol): ')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords differ; nothing was changed.')
    if not (14 <= len(password) <= 256 and any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password) and any(not c.isalnum() and not c.isspace() for c in password)):
        raise SystemExit('Password does not meet the configured policy; nothing was changed.')
    client = boto3.client('cognito-idp', region_name=args.region)
    try:
        if not args.reset_password:
            client.admin_create_user(UserPoolId=args.pool_id, Username=email, MessageAction='SUPPRESS', UserAttributes=[{'Name':'email','Value':email},{'Name':'email_verified','Value':'true'}])
        client.admin_set_user_password(UserPoolId=args.pool_id, Username=email, Password=password, Permanent=True)
    except ClientError as error:
        code = error.response['Error']['Code']
        if code == 'UsernameExistsException':
            raise SystemExit('Owner already exists; no password was changed. Rerun with --reset-password only if you intend to replace its password.')
        raise SystemExit('Owner setup failed (' + code + '). Check AWS permissions and password policy. If creation succeeded but password setup failed, retry with --reset-password.')
    print('Owner login configured. Use it in the MCP client OAuth window. No email was sent.')

if __name__ == '__main__':
    main()
