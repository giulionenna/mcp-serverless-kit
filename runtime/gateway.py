"""AgentCore Lambda target adapter (arguments event, tool name in client context)."""
import json
import math

class ToolError(ValueError):
    """Safe, user-facing error; never include secrets or upstream exception text."""

def validate(arguments, schema):
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry
    from referencing.exceptions import NoSuchResource
    def no_remote_resources(uri):
        raise NoSuchResource(ref=uri)
    if not isinstance(arguments, dict):
        raise ToolError('Tool arguments must be an object.')
    if not Draft202012Validator(schema, format_checker=FormatChecker(), registry=Registry(retrieve=no_remote_resources)).is_valid(arguments):
        raise ToolError('Arguments do not match the tool schema.')
    def reject_nonfinite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ToolError('Numbers must be finite.')
        if isinstance(value, dict):
            for item in value.values():
                reject_nonfinite(item)
        if isinstance(value, list):
            for item in value:
                reject_nonfinite(item)
    reject_nonfinite(arguments)

def dispatch(event, context, manifest, tools):
    try:
        custom = context.client_context.custom
        full_name = custom['bedrockAgentCoreToolName']
        if not isinstance(full_name, str) or '___' not in full_name:
            raise ToolError('Missing Gateway tool context.')
        name = full_name.split('___', 1)[1]
        definition = next((t for t in manifest['tools'] if t['name'] == name), None)
        if definition is None or name not in tools:
            raise ToolError('Unknown tool.')
        validate(event, definition['inputSchema'])
        result = tools[name](**event)
        # Gateway requires valid JSON: reject NaN/Infinity, including arithmetic overflow.
        json.dumps(result, allow_nan=False)
        return result
    except ToolError as error:
        return {'error': str(error)}
    except Exception:
        # Libraries can include token/health data in exception messages.
        return {'error': 'Tool unavailable. Check module configuration or renew authentication.'}
