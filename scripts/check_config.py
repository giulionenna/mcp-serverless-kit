#!/usr/bin/env python3
"""Validate public GitHub Actions configuration without printing credentials."""
import json
import os
import re

def validate(config):
    required = ['AWS_REGION', 'STATE_BUCKET', 'DEPLOY_ROLE', 'TF_VAR_project_name', 'TF_VAR_callback_urls']
    if any(not config.get(key) for key in required):
        raise ValueError('Missing setup variables: AWS_REGION, TF_STATE_BUCKET, AWS_ROLE_ARN or project/callback configuration.')
    if not re.fullmatch(r'[a-z]{2}-[a-z]+-\d', config['AWS_REGION']):
        raise ValueError('Invalid AWS region.')
    if not re.fullmatch(r'arn:aws:iam::\d{12}:role/[\w+=,.@/-]+', config['DEPLOY_ROLE']):
        raise ValueError('Invalid deployment role ARN; commercial AWS regions are supported.')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,24}', config['TF_VAR_project_name']):
        raise ValueError('Project name must match the bootstrap stack: 3-25 lowercase characters.')
    callbacks = json.loads(config['TF_VAR_callback_urls'])
    if not isinstance(callbacks, list) or not callbacks or any(not isinstance(x, str) or not x.startswith('https://') or '{' in x or '}' in x for x in callbacks):
        raise ValueError('MCP_CALLBACK_URLS must be a JSON array of exact HTTPS redirect URLs.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['STATE_BUCKET']):
        raise ValueError('Invalid state bucket name.')

if __name__ == '__main__':
    try:
        validate(os.environ)
    except (ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error))
    print('Deployment configuration is valid.')
