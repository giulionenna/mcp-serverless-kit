"""Optional unofficial Garmin integration. No account writes are exposed."""
import json
import contextlib
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
    secrets = boto3.client('secretsmanager')
    secret = json.loads(secrets.get_secret_value(SecretId=arn)['SecretString'])
    if not isinstance(secret, dict) or not isinstance(secret.get('is_cn', False), bool):
        raise ToolError('Garmin token secret is invalid. Renew authentication.')
    tokens = secret.get('tokens')
    if not isinstance(tokens, dict) or not tokens:
        raise ToolError('Garmin token secret is invalid. Renew authentication.')
    instance = Garmin(is_cn=secret.get('is_cn', False))
    instance.login(json.dumps(tokens))
    return instance, secret, secrets, arn

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
def heart_rates(date):
    return read('get_heart_rates', date)
def stress(date):
    return read('get_stress_data', date)
def body_battery(date):
    return read('get_body_battery', date, date)
def hrv(date):
    return read('get_hrv_data', date)
def training_readiness(date):
    return read('get_training_readiness', date)
def activity(activity_id):
    return read('get_activity', activity_id)
def lambda_handler(event, context):
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        # Some dependencies print directly, bypassing the logging configuration.
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            return dispatch(event, context, MANIFEST, {
                'daily_stats': daily_stats, 'sleep': sleep, 'activities': activities,
                'heart_rates': heart_rates, 'stress': stress, 'body_battery': body_battery,
                'hrv': hrv, 'training_readiness': training_readiness, 'activity': activity,
            })
    finally:
        logging.disable(previous)
