#!/usr/bin/env python3
"""Configure AWS web identity on a GitHub runner without external Actions.

Requires the job's id-token: write permission. Only the existing deployment role
is selected; AWS STS still enforces its repository/branch/audience trust policy.
The short-lived GitHub JWT is written to a private runner file, never printed.
AWS SDKs/CLI and Terraform exchange it for temporary credentials as needed.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def configure(environ):
    role = environ['DEPLOY_ROLE']
    if not re.fullmatch(r'arn:aws:iam::\d{12}:role/[\w+=,.@/-]+', role):
        raise ValueError('Invalid deployment role.')
    url = environ['ACTIONS_ID_TOKEN_REQUEST_URL']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.actions.githubusercontent.com'):
        raise ValueError('Invalid GitHub OIDC endpoint.')
    request = Request(
        url + ('&' if '?' in url else '?') + urlencode({'audience': 'sts.amazonaws.com'}),
        headers={'Authorization': 'Bearer ' + environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']},
    )
    with urlopen(request, timeout=15) as response:
        token = json.load(response)['value']
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Invalid GitHub OIDC response.')
    token_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='aws-web-identity-', suffix='.jwt', dir=environ['RUNNER_TEMP'], delete=False) as stream:
            token_path = Path(stream.name)
            stream.write(token)
        # NamedTemporaryFile creates mode 0600. Export selectors, not credentials.
        with open(environ['GITHUB_ENV'], 'a') as stream:
            stream.write(f'\nAWS_ROLE_ARN={role}\nAWS_WEB_IDENTITY_TOKEN_FILE={token_path}\nAWS_ROLE_SESSION_NAME=mcp-kit-deploy\n')
    except Exception:
        if token_path is not None:
            token_path.unlink(missing_ok=True)
        raise


def main():
    try:
        configure(os.environ)
    except Exception:
        print('GitHub OIDC setup failed. Check id-token permission and deployment role configuration.', file=sys.stderr)
        return 1
    print('AWS web identity configured. No token or temporary credentials were printed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
