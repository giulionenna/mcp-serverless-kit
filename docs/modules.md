# Add a module

Each enabled module becomes a Lambda target in the same Gateway. Add a folder under `modules/` with these files:

```text
modules/my_module/
  manifest.json
  handler.py
  requirements.lock
```

## Manifest

Use a unique lowercase module name, matching its folder. Tool names are lowercase identifiers; Gateway prefixes them with the target name. The runtime validates JSON Schema draft 2020-12, including nested objects, arrays, and enums. Use schemas supported by AgentCore's tool definition API; a successful local schema check does not establish support for every advanced keyword at the service boundary. External schema references and identifiers are rejected so validation cannot fetch remote documents.

```json
{
  "name": "my_module",
  "description": "Tools for my personal service",
  "tools": [
    {
      "name": "greet",
      "description": "Return a greeting.",
      "inputSchema": {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 100}},
        "required": ["name"],
        "additionalProperties": false
      }
    }
  ]
}
```

Terraform stores the manifest's tools array in private S3 and registers it with the Gateway. Schema keys are content-addressed to trigger reimport when definitions change.

## Handler

```python
import json
from pathlib import Path
from runtime.gateway import dispatch

MANIFEST = json.loads(Path(__file__).with_name("manifest.json").read_text())

def greet(name):
    return {"greeting": f"Hello, {name}!"}

def lambda_handler(event, context):
    return dispatch(event, context, MANIFEST, {"greet": greet})
```

AgentCore passes tool arguments directly as `event`. The selected tool is in `context.client_context.custom['bedrockAgentCoreToolName']`, such as `my_module___greet`. The shared dispatcher validates arguments, blocks nonfinite JSON, and returns safe errors without raw exception text. It returns JSON for AgentCore to translate into the MCP response; do not wrap an API Gateway HTTP response.

A module's callable argument names must match its schema. Do not silently invent missing/default argument values unless the handler and description specify them. The dispatcher does not apply schema defaults.

## Dependencies and packaging

Use an empty `requirements.lock` when no module-specific packages are needed. Shared validation dependencies are added automatically from `runtime/requirements.lock`. For additional dependencies, include exact pins and SHA-256 hashes for every transitive dependency. Target **Python 3.12, manylinux2014 x86_64** and binary wheels. For example, a package lock line has this form:

```text
package-name==1.2.3 --hash=sha256:ACTUAL-WHEEL-SHA256
```

The hash must come from the actual supported wheel, not this placeholder. Download packages with `pip download --only-binary=:all: --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --abi cp312`; collect and review all versions and hashes. Runtime and module lockfiles must not introduce conflicting versions. Native dependencies targeting another architecture will not work.

`python scripts/build.py` validates enabled manifests and builds `dist/<module>.zip`, with fixed ZIP timestamps and sorted entries. An optional `--wheelhouse PATH` builds from predownloaded verified wheels without accessing an index. Source-only packages are deliberately unsupported in this version.

## Enable and deploy

Add your module to `config/modules.json`, commit it on your fork, and run the deploy workflow. The default is:

```json
{"enabled": ["example"]}
```

Enabled names must be unique; at least one is required. Removing a module from this list and reapplying removes its Lambda/target and associated Terraform-managed resources. Removing Garmin schedules its secret for deletion; readding it during the recovery window can require restoring or importing that secret.

## Secrets and permissions

The generic contract covers tools and packages. Module-specific AWS resources, environment settings, and secrets currently require an explicit Terraform extension, following the Garmin example. **The manifest is not an IAM permission grant mechanism.** A new module without those additions receives its own log permissions only.

Secrets belong in a private store populated outside Terraform, not the manifest, source, action variables, or tool arguments. Scope read/write permissions to the exact required resource. Add meaningful tests for service calls, safe failures, and argument validation before enabling a module.

[AWS Lambda target contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html).
