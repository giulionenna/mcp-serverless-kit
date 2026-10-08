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
