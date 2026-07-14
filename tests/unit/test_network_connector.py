"""MicrovmNetworkConnector unit tests — resource shape, BYO-VPC wiring, egress rules, defaults, validation. No AWS calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from aws_cdk import Aspects, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks, NagSuppressions

from lambda_microvm_cdk import MicrovmNetworkConnector

CONNECTOR_TYPE = 'AWS::Lambda::NetworkConnector'
OPERATOR_ROLE_DESCRIPTION = 'Least-privilege operator role Lambda assumes to manage the MicroVM connector ENIs'


def _vpc(stack: Stack, *, flow_logs: bool = False) -> ec2.Vpc:
    """A BYO VPC with PRIVATE_WITH_EGRESS subnets. flow_logs=True keeps a cdk-nag run clean (VPC7)."""
    vpc = ec2.Vpc(stack, 'Vpc', max_azs=2)
    if flow_logs:
        group = logs.LogGroup(stack, 'FlowLogGroup', removal_policy=RemovalPolicy.DESTROY)
        ec2.FlowLog(
            stack, 'FlowLog', resource_type=ec2.FlowLogResourceType.from_vpc(vpc), destination=ec2.FlowLogDestination.to_cloud_watch_logs(group)
        )
    return vpc


def _egress_config(template: Template) -> dict[str, Any]:
    connectors = template.find_resources(CONNECTOR_TYPE)
    assert len(connectors) == 1
    props: dict[str, Any] = next(iter(connectors.values()))['Properties']
    config: dict[str, Any] = props['Configuration']['VpcEgressConfiguration']
    return config


def test_connector_created_with_registry_confirmed_props(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack))
    config = _egress_config(Template.from_stack(stack))
    assert config['AssociatedComputeResourceTypes'] == ['MicroVm']
    assert config['NetworkProtocol'] == 'IPv4'
    assert isinstance(config['SubnetIds'], list) and len(config['SubnetIds']) == 2  # 2 PRIVATE_WITH_EGRESS subnets
    assert isinstance(config['SecurityGroupIds'], list) and len(config['SecurityGroupIds']) == 1


def test_vpc_is_required_and_not_auto_created(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    with pytest.raises(TypeError):
        MicrovmNetworkConnector(stack, 'Egress')  # type: ignore[call-arg]  # vpc is a required keyword arg


def test_dualstack_protocol(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack), network_protocol='DualStack')
    assert _egress_config(Template.from_stack(stack))['NetworkProtocol'] == 'DualStack'


def test_default_security_group_denies_all_egress(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    connector = MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack))
    template = Template.from_stack(stack)
    groups = template.find_resources(
        'AWS::EC2::SecurityGroup', {'Properties': {'GroupDescription': Match.string_like_regexp('.*MicroVM egress connector.*')}}
    )
    assert len(groups) == 1
    props = next(iter(groups.values()))['Properties']
    # allow_all_outbound=False -> CDK emits the "disallow all" 255.255.255.255/32 placeholder egress rule.
    assert '255.255.255.255/32' in json.dumps(props.get('SecurityGroupEgress', [])), 'default SG must not allow open egress'
    assert connector.security_group is not None


def test_egress_rules_added_via_native_cdk_helpers(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    connector = MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack))
    connector.security_group.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'HTTPS egress')
    Template.from_stack(stack).has_resource_properties(
        'AWS::EC2::SecurityGroup',
        {'SecurityGroupEgress': Match.array_with([Match.object_like({'CidrIp': '0.0.0.0/0', 'FromPort': 443, 'ToPort': 443, 'IpProtocol': 'tcp'})])},
    )


def test_byo_subnets_selection_is_honored(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    vpc = _vpc(stack)
    one_subnet = [vpc.private_subnets[0]]
    MicrovmNetworkConnector(stack, 'Egress', vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnets=one_subnet))
    assert len(_egress_config(Template.from_stack(stack))['SubnetIds']) == 1


def test_byo_security_group_and_operator_role_respected(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    vpc = _vpc(stack)
    byo_sg = ec2.SecurityGroup(stack, 'ByoSg', vpc=vpc, allow_all_outbound=False)
    byo_role = iam.Role(stack, 'ByoOp', assumed_by=iam.ServicePrincipal('lambda.amazonaws.com'), description='byo op')
    connector = MicrovmNetworkConnector(stack, 'Egress', vpc=vpc, security_group=byo_sg, operator_role=byo_role)
    assert connector.security_group is byo_sg
    assert connector.operator_role is byo_role
    template = Template.from_stack(stack)
    assert not template.find_resources('AWS::IAM::Role', {'Properties': {'Description': OPERATOR_ROLE_DESCRIPTION}})


@pytest.mark.parametrize('protocol', ['ipv4', 'IPV4', 'dual', ''])
def test_invalid_network_protocol_raises(stack_factory: Callable[[], Stack], protocol: str) -> None:
    stack = stack_factory()
    with pytest.raises(ValueError, match='network_protocol'):
        MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack), network_protocol=protocol)  # type: ignore[arg-type]


def test_invalid_name_raises(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    with pytest.raises(ValueError, match='name must match'):
        MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack), name='has spaces!')


def _apply_connector_nag_suppressions(connector: MicrovmNetworkConnector) -> None:
    NagSuppressions.add_resource_suppressions(
        connector.operator_role,
        [
            {
                'id': 'AwsSolutions-IAM5',
                'reason': 'Verbatim AWS-documented NetworkConnector operator policy: ec2:CreateNetworkInterface + '
                'ec2:CreateTags on ec2:*:*:network-interface/subnet/security-group ARNs (region/account wildcarded per the '
                'doc so Lambda can create the ENIs in its own context; ids dynamic). No Describe/Delete; CreateTags is '
                'conditioned on the connector managed operator.',
            }
        ],
        apply_to_children=True,
    )


def test_no_unsuppressed_aws_solutions_errors(stack_factory: Callable[[], Stack]) -> None:
    stack = stack_factory()
    connector = MicrovmNetworkConnector(stack, 'Egress', vpc=_vpc(stack, flow_logs=True))
    connector.security_group.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'HTTPS egress')
    Aspects.of(stack).add(AwsSolutionsChecks(verbose=True))
    _apply_connector_nag_suppressions(connector)
    Annotations.from_stack(stack).has_no_error('*', Match.string_like_regexp('AwsSolutions-.*'))
