"""Regression checks for resource types required by AWS AgentCore authorization.

These check template ARN/action/region matching; they are not an AWS IAM simulator.
"""
from fnmatch import fnmatchcase
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).parents[1]
ACCOUNT = '138410486348'
REGION = 'eu-south-1'
DIRECTORY = f'arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:workload-identity-directory/default'
IDENTITY = DIRECTORY + '/workload-identity/service-generated-gateway-identity'
VALUES = {'AWS::Partition': 'aws', 'AWS::AccountId': ACCOUNT, 'AWS::Region': REGION}


class CloudFormationLoader(yaml.SafeLoader):
    pass


CloudFormationLoader.add_multi_constructor(
    '!', lambda loader, tag, node: {tag: loader.construct_scalar(node)}
    if isinstance(node, yaml.ScalarNode) else {tag: loader.construct_sequence(node)}
)


def resolve(value):
    if isinstance(value, dict) and 'Sub' in value:
        result = value['Sub']
        for key, replacement in VALUES.items():
            result = result.replace('${' + key + '}', replacement)
        return result
    if isinstance(value, dict) and 'Ref' in value:
        return VALUES[value['Ref']]
    return value


def statements():
    template = yaml.load((ROOT / 'bootstrap/github-oidc.yaml').read_text(), Loader=CloudFormationLoader)
    return template['Resources']['DeploymentRole']['Properties']['Policies'][0]['PolicyDocument']['Statement']


def matches(action, resource, region=REGION):
    for statement in statements():
        actions = statement['Action']
        resources = statement['Resource']
        actions = actions if isinstance(actions, list) else [actions]
        resources = resources if isinstance(resources, list) else [resources]
        conditions = statement.get('Condition', {}).get('StringEquals', {})
        required_region = conditions.get('aws:RequestedRegion')
        if required_region and resolve(required_region) != region:
            continue
        if statement['Effect'] == 'Allow' and any(fnmatchcase(action, a) for a in actions) and any(fnmatchcase(resource, resolve(r)) for r in resources):
            return True
    return False


@pytest.mark.parametrize('operation', ['Create', 'Get', 'Update', 'Delete'])
def test_workload_lifecycle_covers_both_required_resource_types(operation):
    # Each resource marked with * in AWS's service authorization table must match.
    action = f'bedrock-agentcore:{operation}WorkloadIdentity'
    assert matches(action, DIRECTORY)
    assert matches(action, IDENTITY)


def test_workload_permissions_remain_in_account_and_region():
    action = 'bedrock-agentcore:CreateWorkloadIdentity'
    assert not matches(action, IDENTITY.replace(ACCOUNT, '999999999999'))
    assert not matches(action, IDENTITY.replace(REGION, 'eu-north-1'), 'eu-north-1')
    assert not matches(action, IDENTITY, 'eu-north-1')
    assert not matches(action, DIRECTORY.replace('/default', '/another-directory'))


def test_deployer_cannot_obtain_workload_tokens_or_provider_credentials():
    assert not matches('bedrock-agentcore:GetWorkloadAccessToken', IDENTITY)
    assert not matches('bedrock-agentcore:GetResourceOauth2Token', IDENTITY)


def test_gateway_synchronization_dependency_is_region_scoped():
    resource = f'arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/service-generated-id'
    action = 'bedrock-agentcore:SynchronizeGatewayTargets'
    assert matches(action, resource)
    assert not matches(action, resource.replace(ACCOUNT, '999999999999'))
    assert not matches(action, resource.replace(REGION, 'eu-north-1'), 'eu-north-1')
