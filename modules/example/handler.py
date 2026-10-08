import json
from pathlib import Path
from runtime.gateway import dispatch
MANIFEST = json.loads(Path(__file__).with_name('manifest.json').read_text())
TOOLS = {'echo': lambda message: {'message': message}, 'add': lambda a, b: {'result': a + b}}
def lambda_handler(event, context):
    return dispatch(event, context, MANIFEST, TOOLS)
