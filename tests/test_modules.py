import importlib.util
import json
import os
import sys
import types
import zipfile
from pathlib import Path
import pytest
from runtime.gateway import dispatch
from scripts.build import ROOT, load_modules, package, validate_manifest

def handler(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / 'modules' / name / 'handler.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def context(name):
    return types.SimpleNamespace(client_context=types.SimpleNamespace(custom={'bedrockAgentCoreToolName': 'my-target___' + name}))

def test_actual_gateway_contract():
    example = handler('example')
    assert example.lambda_handler({'a': 2, 'b': 3}, context('add')) == {'result': 5}
    assert example.lambda_handler({'message': 'hello'}, context('echo')) == {'message': 'hello'}
    assert 'error' in example.lambda_handler({'arguments': {'a': 2, 'b': 3}}, context('add'))

@pytest.mark.parametrize('arguments', [{'a': True, 'b': 2}, {'a': float('nan'), 'b': 2}, {'a': 1}, {'a': 1, 'b': 2, 'extra': 0}])
def test_invalid_arguments(arguments):
    assert 'error' in handler('example').lambda_handler(arguments, context('add'))

def test_missing_and_unknown_context():
    module = handler('example')
    assert 'error' in module.lambda_handler({}, None)
    assert 'error' in module.lambda_handler({}, context('delete_everything'))

@pytest.mark.parametrize('names', [[], ['../garmin'], ['Example'], ['example', 'example'], [False], 'example'])
def test_invalid_module_config(tmp_path, names):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'enabled': names}))
    with pytest.raises(ValueError):
        load_modules(path)

def test_manifests():
    for name in ('example', 'garmin'):
        validate_manifest(name)

def test_deterministic_standalone_zip(tmp_path):
    output = package('example', tmp_path, Path(os.environ['MCP_WHEELHOUSE']) if os.environ.get('MCP_WHEELHOUSE') else None)
    first = output.read_bytes()
    assert package('example', tmp_path, Path(os.environ['MCP_WHEELHOUSE']) if os.environ.get('MCP_WHEELHOUSE') else None).read_bytes() == first
    with zipfile.ZipFile(output) as archive:
        assert {'handler.py', 'manifest.json', 'runtime/gateway.py'} <= set(archive.namelist())
        archive.extractall(tmp_path / 'unpacked')
    # Simulates Lambda importing from zip root rather than repository modules.
    spec = importlib.util.spec_from_file_location('packed', tmp_path / 'unpacked' / 'handler.py')
    packed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packed)
    assert packed.lambda_handler({'a': 2, 'b': 3}, context('add')) == {'result': 5}

def test_garmin_secret_contract_and_readonly_calls(monkeypatch):
    calls = []
    class Garmin:
        def __init__(self, **kwargs):
            calls.append(('construct', kwargs))
            self.client = types.SimpleNamespace(dumps=lambda: json.dumps({'fake': 'token'}))
        def login(self, tokens):
            assert json.loads(tokens) == {'fake': 'token'}
        def get_stats(self, day):
            return {'steps': 42}
        def get_sleep_data(self, day):
            return {'seconds': 100}
        def get_activities(self, start, limit):
            assert start == 0 and limit == 2
            return []
    class Secrets:
        def get_secret_value(self, **kwargs):
            assert kwargs == {'SecretId': 'test-arn'}
            return {'SecretString': json.dumps({'tokens': {'fake': 'token'}})}
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=Garmin))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda service: Secrets()))
    monkeypatch.setenv('GARMIN_SECRET_ARN', 'test-arn')
    garmin = handler('garmin')
    assert garmin.lambda_handler({'date': '2026-01-02'}, context('daily_stats')) == {'data': {'steps': 42}}
    assert garmin.lambda_handler({'date': '2026-01-02'}, context('sleep')) == {'data': {'seconds': 100}}
    assert garmin.lambda_handler({'limit': 2}, context('activities')) == {'data': []}
    assert 'error' in garmin.lambda_handler({'date': '2026-02-30'}, context('sleep'))
    assert 'error' in garmin.lambda_handler({'limit': 21}, context('activities'))

def test_exception_is_redacted():
    manifest = validate_manifest('example')
    def fail(**kwargs):
        raise RuntimeError('SUPER_SECRET_TOKEN')
    result = dispatch({'message': 'x'}, context('echo'), manifest, {'echo': fail})
    assert 'SUPER_SECRET_TOKEN' not in json.dumps(result)
    assert 'error' in result

def test_refreshed_tokens_are_persisted(monkeypatch):
    garmin = handler('garmin')
    updates = []
    instance = types.SimpleNamespace(get_stats=lambda day: {'steps': 1}, client=types.SimpleNamespace(dumps=lambda: '{"new": "token"}'))
    secrets = types.SimpleNamespace(put_secret_value=lambda **kwargs: updates.append(kwargs))
    monkeypatch.setattr(garmin, 'client', lambda: (instance, {'tokens': {'old': 'token'}, 'is_cn': False}, secrets, 'test-arn'))
    assert garmin.daily_stats('2026-01-01') == {'data': {'steps': 1}}
    assert len(updates) == 1
    assert json.loads(updates[0]['SecretString']) == {'tokens': {'new': 'token'}, 'is_cn': False}

def test_nested_arrays_and_enums():
    schema = {'type': 'object', 'required': ['items'], 'properties': {'items': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'required': ['kind'], 'properties': {'kind': {'enum': ['run', 'walk']}}, 'additionalProperties': False}}}, 'additionalProperties': False}
    manifest = {'tools': [{'name': 'nested', 'inputSchema': schema}]}
    good = {'items': [{'kind': 'run'}]}
    assert dispatch(good, context('nested'), manifest, {'nested': lambda **kwargs: kwargs}) == good
    for bad in ({'items': []}, {'items': [{'kind': 'swim'}]}, {'items': [{'kind': 'run', 'unknown': 1}]}):
        assert 'error' in dispatch(bad, context('nested'), manifest, {'nested': lambda **kwargs: kwargs})

def test_invalid_schema_is_rejected(tmp_path, monkeypatch):
    import scripts.build as build
    module = tmp_path / 'modules' / 'bad'
    module.mkdir(parents=True)
    manifest = {'name': 'bad', 'description': 'Bad schema', 'tools': [{'name': 'bad', 'description': 'Bad', 'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'nonsense'}}, 'additionalProperties': False}}]}
    (module / 'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    from jsonschema.exceptions import SchemaError
    with pytest.raises(SchemaError):
        build.validate_manifest('bad')
    manifest['tools'][0]['inputSchema']['properties']['value'] = {'$ref': 'https://example.com/schema'}
    (module / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='local schema'):
        build.validate_manifest('bad')


def test_output_infinity_is_rejected():
    assert 'error' in handler('example').lambda_handler({'a': 1e308, 'b': 1e308}, context('add'))

def test_login_requires_interactive_terminal(monkeypatch, capsys):
    from scripts import garmin_login
    monkeypatch.setattr(sys, 'argv', ['login', '--secret-arn', 'arn', '--region', 'us-east-1'])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: False))
    assert garmin_login.main() == 1
    assert 'Interactive terminal required' in capsys.readouterr().err

def test_mfa_prompt_uses_original_console(monkeypatch):
    from scripts import garmin_login
    import io
    import logging
    console = io.StringIO()
    prompts = []
    updates = []
    def prompt(message, stream):
        assert stream is console
        prompts.append(message)
        return 'hidden-value'
    class Garmin:
        def __init__(self, **kwargs):
            self.mfa = kwargs.get('prompt_mfa')
            self.client = types.SimpleNamespace(dumps=lambda: '{"fake":"token"}')
        def login(self, *args):
            if self.mfa:
                assert sys.stderr is not console
                assert self.mfa() == 'hidden-value'
    monkeypatch.setattr(sys, 'argv', ['login', '--secret-arn', 'arn', '--region', 'us-east-1'])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(sys, 'stderr', console)
    monkeypatch.setattr(garmin_login.getpass, 'getpass', prompt)
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=Garmin))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda *args, **kwargs: types.SimpleNamespace(put_secret_value=lambda **kwargs: updates.append(kwargs))))
    previous = logging.root.manager.disable
    try:
        assert garmin_login.main() == 0
    finally:
        logging.disable(previous)
    assert prompts == ['Garmin email (hidden): ', 'Garmin password: ', 'Garmin MFA code: ']
    assert len(updates) == 1


@pytest.mark.parametrize('keyword', ['$ref', '$dynamicRef', '$recursiveRef', '$id'])
def test_external_schema_uri_is_rejected(keyword, tmp_path, monkeypatch):
    import scripts.build as build
    folder = tmp_path / 'modules' / 'bad'
    folder.mkdir(parents=True)
    manifest = {'name': 'bad', 'description': 'test', 'tools': [{'name': 'bad', 'description': 'test', 'inputSchema': {'type': 'object', 'properties': {'value': {keyword: 'https://example.com/schema'}}, 'additionalProperties': False}}]}
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='local schema'):
        build.validate_manifest('bad')


@pytest.mark.parametrize('name,arguments,method,expected', [
    ('heart_rates', {'date': '2026-10-09'}, 'get_heart_rates', ('2026-10-09',)),
    ('stress', {'date': '2026-10-09'}, 'get_stress_data', ('2026-10-09',)),
    ('body_battery', {'date': '2026-10-09'}, 'get_body_battery', ('2026-10-09', '2026-10-09')),
    ('hrv', {'date': '2026-10-09'}, 'get_hrv_data', ('2026-10-09',)),
    ('training_readiness', {'date': '2026-10-09'}, 'get_training_readiness', ('2026-10-09',)),
    ('activity', {'activity_id': 123}, 'get_activity', (123,)),
])
def test_garmin_extended_reads(monkeypatch, name, arguments, method, expected):
    garmin = handler('garmin')
    calls = []
    def fetch(*args):
        calls.append(args)
        return {'measurement': 42}
    instance = types.SimpleNamespace(client=types.SimpleNamespace(dumps=lambda: '{"fake":"token"}'))
    setattr(instance, method, fetch)
    secrets = types.SimpleNamespace(put_secret_value=lambda **kwargs: pytest.fail('Unchanged tokens must not be written'))
    monkeypatch.setattr(garmin, 'client', lambda: (instance, {'tokens': {'fake': 'token'}}, secrets, 'test-arn'))
    assert garmin.lambda_handler(arguments, context(name)) == {'data': {'measurement': 42}}
    assert calls == [expected]


@pytest.mark.parametrize('arguments', [{'activity_id': 0}, {'activity_id': True}, {'activity_id': '123'}, {'activity_id': 123, 'extra': 1}])
def test_garmin_invalid_activity_id_does_not_authenticate(monkeypatch, arguments):
    garmin = handler('garmin')
    monkeypatch.setattr(garmin, 'client', lambda: pytest.fail('Invalid input must not authenticate'))
    assert 'error' in garmin.lambda_handler(arguments, context('activity'))


def test_garmin_direct_output_and_exception_are_redacted(monkeypatch, capsys):
    import logging
    garmin = handler('garmin')
    def fail():
        print('PRIVATE_SESSION')
        print('PRIVATE_HEALTH_DATA', file=sys.stderr)
        logging.warning('PRIVATE_PASSWORD')
        raise RuntimeError('PRIVATE_TOKEN')
    monkeypatch.setattr(garmin, 'client', fail)
    previous = logging.root.manager.disable
    result = garmin.lambda_handler({'limit': 1}, context('activities'))
    assert 'error' in result
    assert 'PRIVATE_' not in json.dumps(result)
    output = capsys.readouterr()
    assert 'PRIVATE_' not in output.out + output.err
    assert logging.root.manager.disable == previous


@pytest.mark.parametrize('secret', [[], {'tokens': {}}, {'tokens': {'fake': 'token'}, 'is_cn': 'false'}])
def test_garmin_invalid_secret_is_safe(monkeypatch, secret):
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=lambda **kwargs: pytest.fail('Invalid secret must not login')))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda service: types.SimpleNamespace(get_secret_value=lambda **kwargs: {'SecretString': json.dumps(secret)})))
    monkeypatch.setenv('GARMIN_SECRET_ARN', 'test-arn')
    result = handler('garmin').lambda_handler({'limit': 1}, context('activities'))
    assert result == {'error': 'Garmin token secret is invalid. Renew authentication.'}


def test_garmin_project_secret_resolved_before_credentials(monkeypatch, capsys):
    from scripts import garmin_login
    import logging
    events = []
    def describe(**kwargs):
        assert kwargs == {'SecretId': 'personal-mcp/garmin'}
        events.append('describe')
        raise RuntimeError('PRIVATE_AWS_ERROR')
    def aws_client(service, **kwargs):
        assert service == 'secretsmanager' and kwargs == {'region_name': 'eu-south-1'}
        return types.SimpleNamespace(describe_secret=describe)
    monkeypatch.setattr(sys, 'argv', ['login', '--region', 'eu-south-1', '--project', 'personal-mcp'])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(garmin_login.getpass, 'getpass', lambda *args, **kwargs: pytest.fail('No credentials before secret resolution'))
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=object))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=aws_client))
    previous = logging.root.manager.disable
    try:
        assert garmin_login.main() == 1
    finally:
        logging.disable(previous)
    assert events == ['describe']
    output = capsys.readouterr()
    assert 'not found or inaccessible' in output.err
    assert 'PRIVATE_' not in output.err


@pytest.mark.parametrize('write_fails', [False, True])
def test_garmin_project_login_saves_verified_session_privately(monkeypatch, capsys, write_fails):
    from scripts import garmin_login
    import logging
    writes = []
    class Garmin:
        def __init__(self, **kwargs):
            self.initial = 'email' in kwargs
            self.client = types.SimpleNamespace(dumps=lambda: json.dumps({'session': 'initial' if self.initial else 'verified'}))
        def login(self, *args):
            if not self.initial:
                assert json.loads(args[0]) == {'session': 'initial'}
            print('PRIVATE_LIBRARY_OUTPUT')
    def put(**kwargs):
        writes.append(kwargs)
        if write_fails:
            raise RuntimeError('PRIVATE_AWS_ERROR')
    def aws_client(service, **kwargs):
        assert service == 'secretsmanager' and kwargs == {'region_name': 'eu-south-1'}
        return types.SimpleNamespace(describe_secret=lambda **kwargs: {'ARN': 'test-arn'}, put_secret_value=put)
    monkeypatch.setattr(sys, 'argv', ['login', '--region', 'eu-south-1', '--project', 'personal-mcp', '--china'])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(garmin_login.getpass, 'getpass', lambda *args, **kwargs: 'PRIVATE_CREDENTIAL')
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=Garmin))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=aws_client))
    previous = logging.root.manager.disable
    try:
        assert garmin_login.main() == int(write_fails)
    finally:
        logging.disable(previous)
    assert writes == [{'SecretId': 'test-arn', 'SecretString': json.dumps({'tokens': {'session': 'verified'}, 'is_cn': True})}]
    output = capsys.readouterr()
    assert 'PRIVATE_' not in output.out + output.err
    if not write_fails:
        assert 'Session tokens stored in AWS Secrets Manager' in output.out


@pytest.mark.parametrize('failure_stage', ['account', 'verification', 'update'])
def test_garmin_login_reports_safe_failure_stage(monkeypatch, capsys, failure_stage):
    from scripts import garmin_login
    import logging
    class PrivateError(Exception):
        response = types.SimpleNamespace(status_code=403, text='PRIVATE_RESPONSE')
    class Garmin:
        def __init__(self, **kwargs):
            self.initial = 'email' in kwargs
            self.client = types.SimpleNamespace(dumps=lambda: '{"session":"PRIVATE_TOKEN"}')
        def login(self, *args):
            if failure_stage == ('account' if self.initial else 'verification'):
                raise PrivateError('PRIVATE_PASSWORD')
    def put(**kwargs):
        assert failure_stage == 'update'
        raise PrivateError('PRIVATE_AWS_RESPONSE')
    monkeypatch.setattr(sys, 'argv', ['login', '--region', 'eu-south-1', '--secret-arn', 'test-arn'])
    monkeypatch.setattr(sys, 'stdin', types.SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(garmin_login.getpass, 'getpass', lambda *args, **kwargs: 'PRIVATE_CREDENTIAL')
    monkeypatch.setitem(sys.modules, 'garminconnect', types.SimpleNamespace(Garmin=Garmin))
    monkeypatch.setitem(sys.modules, 'boto3', types.SimpleNamespace(client=lambda *args, **kwargs: types.SimpleNamespace(put_secret_value=put)))
    previous = logging.root.manager.disable
    try:
        assert garmin_login.main() == 1
    finally:
        logging.disable(previous)
    output = capsys.readouterr()
    stage = {'account': 'Garmin account login', 'verification': 'Garmin session verification', 'update': 'AWS Secrets Manager update'}[failure_stage]
    assert stage + ' failed (PrivateError, HTTP 403)' in output.err
    assert 'PRIVATE_' not in output.out + output.err
