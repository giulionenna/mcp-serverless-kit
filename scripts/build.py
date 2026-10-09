#!/usr/bin/env python3
"""Validate configuration and produce deterministic Lambda ZIPs for Python 3.12 x86_64."""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'^[a-z][a-z0-9_]{0,31}$')

def load_modules(config):
    value = json.loads(Path(config).read_text())
    if not isinstance(value, dict) or set(value) != {'enabled'} or not isinstance(value['enabled'], list):
        raise ValueError('Config must contain only an enabled array.')
    names = value['enabled']
    if not names:
        raise ValueError('At least one module must be enabled.')
    if any(not isinstance(n, str) or not NAME.fullmatch(n) for n in names) or len(names) != len(set(names)):
        raise ValueError('Module names must be unique lowercase identifiers (1-32 characters).')
    return names

def validate_manifest(name):
    from jsonschema import Draft202012Validator
    folder = ROOT / 'modules' / name
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Unknown module: ' + name)
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('name') != name or not isinstance(manifest.get('description'), str) or not manifest['description'].strip():
        raise ValueError('Invalid module metadata: ' + name)
    tools = manifest.get('tools')
    if not isinstance(tools, list) or not tools:
        raise ValueError('Module needs tools.')
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get('name'), str) or not NAME.fullmatch(tool['name']) or tool['name'] in seen:
            raise ValueError('Invalid or duplicate tool name.')
        seen.add(tool['name'])
        if not isinstance(tool.get('description'), str) or not tool['description'].strip():
            raise ValueError('Tool description required.')
        schema = tool.get('inputSchema')
        if not isinstance(schema, dict) or schema.get('type') != 'object' or not isinstance(schema.get('properties'), dict) or schema.get('additionalProperties') is not False:
            raise ValueError('Input schema must be a closed object.')
        def check_refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('$ref', '$dynamicRef', '$recursiveRef', '$id') and (not isinstance(item, str) or not item.startswith('#')):
                        raise ValueError('Only local schema references are supported.')
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)
        check_refs(schema)
        Draft202012Validator.check_schema(schema)
        if set(schema.get('required', [])) - set(schema['properties']):
            raise ValueError('Required property is undefined.')
        if 'outputSchema' in tool:
            check_refs(tool['outputSchema'])
            if tool['outputSchema'].get('type') != 'object':
                raise ValueError('Output schema must be an object.')
            Draft202012Validator.check_schema(tool['outputSchema'])
    if not (folder / 'handler.py').is_file() or not (folder / 'requirements.lock').is_file():
        raise ValueError('Missing handler or dependency lock.')
    return manifest

def package(name, destination, wheelhouse=None):
    validate_manifest(name)
    folder = ROOT / 'modules' / name
    locks = [ROOT / 'runtime' / 'requirements.lock', folder / 'requirements.lock']
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        lock = stage / 'combined-requirements.txt'
        lock.write_text('\n'.join(p.read_text() for p in locks))
        if lock.read_text().strip():
            command = [sys.executable, '-m', 'pip', 'install', '--require-hashes', '--no-compile', '--only-binary=:all:', '--platform', 'manylinux2014_x86_64', '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312', '--target', str(stage), '-r', str(lock)]
            if wheelhouse:
                command.extend(['--no-index', '--find-links', str(wheelhouse)])
            subprocess.run(command, check=True)
        lock.unlink()
        shutil.copy2(folder / 'handler.py', stage / 'handler.py')
        shutil.copy2(folder / 'manifest.json', stage / 'manifest.json')
        shutil.copytree(ROOT / 'runtime', stage / 'runtime', ignore=shutil.ignore_patterns('__pycache__'))
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / (name + '.zip')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks are forbidden in packages.')
                if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                    info = zipfile.ZipInfo(path.relative_to(stage).as_posix(), (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    archive.writestr(info, path.read_bytes(), compresslevel=9)
        return output

def main():
    from jsonschema.exceptions import SchemaError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/modules.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--wheelhouse', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        names = load_modules(args.config)
        for name in names:
            validate_manifest(name)
        for name in names:
            if not args.validate_only:
                print(package(name, args.output, args.wheelhouse))
        if not args.validate_only:
            print(package_oauth_compat(args.output))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, SchemaError) as error:
        parser.exit(1, 'Build failed: ' + str(error) + '\n')
def package_oauth_compat(destination):
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / 'oauth-compat.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        info = zipfile.ZipInfo('oauth_compat.py', (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, (ROOT / 'runtime/oauth_compat.py').read_bytes(), compresslevel=9)
    return output

if __name__ == '__main__':
    main()
