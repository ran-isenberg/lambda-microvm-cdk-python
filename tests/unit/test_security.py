"""Security-focused unit tests — least-privilege IAM on every generated role, no `*` resources. No AWS calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk.assertions import Template

from lambda_microvm_cdk import LambdaMicroVM, MicrovmNetworkConnector

BUILD_ROLE_DESCRIPTION = 'Least-privilege build role for the Lambda MicroVM image build'
EXECUTION_ROLE_DESCRIPTION = 'Least-privilege execution role assumed by the running MicroVM'
OPERATOR_ROLE_DESCRIPTION = 'Least-privilege operator role Lambda assumes to manage the MicroVM connector ENIs'


def _image(stack: Stack, source_dir: str) -> LambdaMicroVM:
    return LambdaMicroVM(stack, 'AgentImage', source=source_dir, name='agent-image')


def _find_role(template: Template, description: str) -> dict[str, Any]:
    roles = template.find_resources('AWS::IAM::Role', {'Properties': {'Description': description}})
    assert len(roles) == 1, f'expected exactly one role with description {description!r}'
    properties: dict[str, Any] = next(iter(roles.values()))['Properties']
    return properties


def _statements(role_properties: dict[str, Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for policy in role_properties.get('Policies', []):
        statements.extend(policy['PolicyDocument']['Statement'])
    return statements


def _assert_no_star_resources(statements: list[dict[str, Any]]) -> None:
    for statement in statements:
        resources = statement.get('Resource')
        resource_list = resources if isinstance(resources, list) else [resources]
        for resource in resource_list:
            assert resource != '*', f'wildcard-only resource in statement: {statement}'


def test_build_role_trusts_microvm_service_with_assume_and_tag_session(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _image(stack, app_source_dir)
    role = _find_role(Template.from_stack(stack), BUILD_ROLE_DESCRIPTION)
    trust = json.dumps(role['AssumeRolePolicyDocument'])
    assert 'lambda.amazonaws.com' in trust
    assert 'sts:AssumeRole' in trust
    assert 'sts:TagSession' in trust


def test_build_role_scoped_to_exact_asset_object_not_bucket_wildcard(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _image(stack, app_source_dir)
    role = _find_role(Template.from_stack(stack), BUILD_ROLE_DESCRIPTION)
    statements = _statements(role)

    s3_statements = [s for s in statements if 's3:GetObject' in json.dumps(s)]
    assert len(s3_statements) == 1
    rendered = json.dumps(s3_statements[0])
    assert '.zip' in rendered, 's3:GetObject must be scoped to the exact asset key (the zip object), not the bucket'
    assert json.dumps(s3_statements[0]['Action']) == '"s3:GetObject"', 'no extra S3 actions'
    _assert_no_star_resources(s3_statements)


def test_build_role_logs_scoped_to_the_image_log_group_only(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _image(stack, app_source_dir)
    role = _find_role(Template.from_stack(stack), BUILD_ROLE_DESCRIPTION)
    logs_statements = [s for s in _statements(role) if 'logs:PutLogEvents' in json.dumps(s)]
    assert len(logs_statements) == 1
    assert '/aws/lambda/microvms/agent-image' in json.dumps(logs_statements[0])


def test_execution_role_grants_runtime_logs_only_by_default(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _image(stack, app_source_dir)
    role = _find_role(Template.from_stack(stack), EXECUTION_ROLE_DESCRIPTION)
    statements = _statements(role)
    assert len(statements) == 1, 'default execution role must carry runtime-logs permissions only'
    rendered = json.dumps(statements[0])
    assert 'logs:CreateLogGroup' in rendered and 'logs:PutLogEvents' in rendered
    assert '/aws/lambda/microvms/agent-image' in rendered
    _assert_no_star_resources(statements)


def test_generated_roles_have_no_wildcard_only_resources(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _image(stack, app_source_dir)
    template = Template.from_stack(stack)
    for description in (BUILD_ROLE_DESCRIPTION, EXECUTION_ROLE_DESCRIPTION):
        _assert_no_star_resources(_statements(_find_role(template, description)))


def test_byo_build_and_execution_roles_are_respected(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    byo_build = iam.Role(stack, 'ByoBuild', assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'), description='byo build')
    byo_exec = iam.Role(stack, 'ByoExec', assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'), description='byo exec')
    image = LambdaMicroVM(stack, 'AgentImage', source=app_source_dir, name='agent-image', build_role=byo_build, execution_role=byo_exec)
    assert image.build_role is byo_build
    assert image.execution_role is byo_exec
    template = Template.from_stack(stack)
    assert not template.find_resources('AWS::IAM::Role', {'Properties': {'Description': BUILD_ROLE_DESCRIPTION}})
    assert not template.find_resources('AWS::IAM::Role', {'Properties': {'Description': EXECUTION_ROLE_DESCRIPTION}})


def test_connector_operator_role_matches_documented_least_privilege(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    MicrovmNetworkConnector(stack, 'Egress', vpc=ec2.Vpc(stack, 'Vpc', max_azs=2))
    role = _find_role(Template.from_stack(stack), OPERATOR_ROLE_DESCRIPTION)
    statements = _statements(role)

    # No global '*' resource anywhere, and no Describe/Delete — Lambda does those as the managed operator.
    _assert_no_star_resources(statements)
    actions = json.dumps([s['Action'] for s in statements])
    assert 'ec2:DescribeNetworkInterfaces' not in actions and 'ec2:DeleteNetworkInterface' not in actions

    create = next(s for s in statements if 'ec2:CreateNetworkInterface' in json.dumps(s['Action']))
    rendered = json.dumps(create['Resource'])
    assert 'network-interface/*' in rendered and 'subnet/*' in rendered and 'security-group/*' in rendered

    tag = next(s for s in statements if 'ec2:CreateTags' in json.dumps(s['Action']))
    assert 'network-interface/*' in json.dumps(tag['Resource'])
    assert tag['Condition'] == {'StringEquals': {'ec2:ManagedResourceOperator': 'network-connectors.lambda.amazonaws.com'}}


def test_connector_operator_role_trusts_microvm_service(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    MicrovmNetworkConnector(stack, 'Egress', vpc=ec2.Vpc(stack, 'Vpc', max_azs=2))
    role = _find_role(Template.from_stack(stack), OPERATOR_ROLE_DESCRIPTION)
    trust = json.dumps(role['AssumeRolePolicyDocument'])
    assert 'lambda.amazonaws.com' in trust and 'sts:AssumeRole' in trust


def test_grant_run_scopes_run_to_image_and_passrole_to_execution_role(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    image = _image(stack, app_source_dir)
    caller = iam.Role(stack, 'RuntimeCaller', assumed_by=iam.AccountRootPrincipal(), description='runtime caller')
    image.grant_run(caller)

    template = Template.from_stack(stack)
    policies = template.find_resources('AWS::IAM::Policy')
    caller_policies = [p for p in policies.values() if 'RunMicrovm' in json.dumps(p)]
    assert len(caller_policies) == 1
    statements: list[dict[str, Any]] = caller_policies[0]['Properties']['PolicyDocument']['Statement']

    run_statement = next(s for s in statements if 'lambda:RunMicrovm' in json.dumps(s['Action']))
    assert 'Fn::GetAtt' in json.dumps(run_statement['Resource']), 'RunMicrovm must be scoped to the specific image ARN'
    _assert_no_star_resources([run_statement])

    lifecycle_statement = next(s for s in statements if 'lambda:TerminateMicrovm' in json.dumps(s['Action']))
    assert ':microvm:*' in json.dumps(lifecycle_statement['Resource']), 'VM lifecycle actions scoped to this account/region microvms'
    assert '"*"' not in json.dumps(lifecycle_statement['Resource'])

    pass_role = next(s for s in statements if 'iam:PassRole' in json.dumps(s['Action']))
    assert 'Fn::GetAtt' in json.dumps(pass_role['Resource']), 'PassRole must be limited to the VM execution role'
    assert pass_role['Condition'] == {'StringEquals': {'iam:PassedToService': 'lambda.amazonaws.com'}}
