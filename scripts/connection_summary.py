#!/usr/bin/env python3
"""Print only known public connection outputs; never dump Terraform output indiscriminately."""
import json
import os
import sys
from pathlib import Path
KEYS = ['mcp_url', 'oauth_client_id', 'oauth_scope', 'oauth_issuer', 'oauth_authorization_url', 'oauth_token_url', 'user_pool_id', 'garmin_secret_arn']
def render(outputs):
    lines = ['## MCP connection details', '', 'Create the owner login in AWS CloudShell. See docs/setup.md.', '']
    for key in KEYS:
        value = outputs.get(key, {}).get('value')
        if value is not None:
            if outputs[key].get('sensitive'):
                raise ValueError('Refusing to publish sensitive output: ' + key)
            lines.append('**' + key + '**: `' + str(value) + '`')
    return '\n\n'.join(lines) + '\n'
if __name__ == '__main__':
    summary = render(json.loads(Path(sys.argv[1]).read_text()))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as file:
            file.write(summary)
    print(summary)
