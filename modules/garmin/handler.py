"""Optional unofficial Garmin integration. No account writes are exposed."""
import json
import logging
import os
from pathlib import Path
from runtime.gateway import dispatch, ToolError
MANIFEST = json.loads(Path(__file__).with_name('manifest.json').read_text())

def client():
    import boto3
    from garminconnect import Garmin
    # Disable third-party logs: neither tokens nor response bodies belong in logs.
    for name in ('garminconnect', 'garminconnect.client', 'garth', 'curl_cffi', 'urllib3', 'botocore', 'boto3'):
        logging.getLogger(name).disabled = True
    arn = os.environ.get('GARMIN_SECRET_ARN')
    if not arn:
        raise ToolError('Garmin authentication is not configured.')
    secret = json.loads(boto3.client('secretsmanager').get_secret_value(SecretId=arn)['SecretString'])
    tokens = secret.get('tokens')
    if not isinstance(tokens, dict) or not tokens:
        raise ToolError('Garmin token secret is invalid. Renew authentication.')
    instance = Garmin(is_cn=secret.get('is_cn', False))
    instance.login(json.dumps(tokens))
    return instance, secret, boto3.client('secretsmanager'), arn

def read(method, *args):
    instance, secret, secrets, arn = client()
    result = getattr(instance, method)(*args)
    refreshed = json.loads(instance.client.dumps())
    if refreshed != secret['tokens']:
        secret['tokens'] = refreshed
        secrets.put_secret_value(SecretId=arn, SecretString=json.dumps(secret))
    return {'data': result}

def daily_stats(date):
    return read('get_stats', date)
def sleep(date):
    return read('get_sleep_data', date)
def activities(limit):
    return read('get_activities', 0, limit)
def lambda_handler(event, context):
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return dispatch(event, context, MANIFEST, {'daily_stats': daily_stats, 'sleep': sleep, 'activities': activities})
    finally:
        logging.disable(previous)
