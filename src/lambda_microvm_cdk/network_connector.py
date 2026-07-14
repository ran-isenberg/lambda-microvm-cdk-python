"""MicrovmNetworkConnector — VPC egress for Lambda MicroVMs. Emits ``AWS::Lambda::NetworkConnector``."""

from __future__ import annotations

import re
from typing import Any, Literal

from aws_cdk import CfnTag, Names, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from lambda_microvm_cdk._impl import security

_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9-_]{1,64}$')
_MICROVM_COMPUTE_RESOURCE_TYPE = 'MicroVm'  # registry: only MicroVm is supported today
_VALID_NETWORK_PROTOCOLS = frozenset({'IPv4', 'DualStack'})
# Registry-confirmed VpcEgressConfiguration subnet limits (the construct attaches a single security group).
_MIN_SUBNETS = 1
_MAX_SUBNETS = 16


class MicrovmNetworkConnector(Construct):
    """Provisions a VPC **egress** network connector for Lambda MicroVMs (``AWS::Lambda::NetworkConnector``).

    A MicroVM reaches customer/VPC-routed networks through a connector. This construct is **BYO-VPC**:
    you pass the ``ec2.IVpc`` the ENIs attach to (it deliberately does not build one — VPC topology, and
    especially whether it has internet egress, is a decision the consumer owns; see ``sample/`` for a
    ``VpcV2`` + NAT example). It creates a security group whose rules **are** the egress policy (deny-all
    by default — opt in with CDK-native ``ec2.Peer``/``ec2.Port`` via ``.security_group.add_egress_rule``),
    a least-privilege ENI operator role, and the connector itself. Feed ``connector_arn`` into
    ``LambdaMicroVM(egress_connectors=[...])`` (build-time egress) or select it per-launch in ``run_microvm``.

    Note: ``AWS::Lambda::NetworkConnector`` is **egress-only** — inbound to a VM is the AWS-managed
    ``ALL_INGRESS`` TLS endpoint (``LambdaMicroVM.ingress_connector_arn``), not a VPC connector.

    Args:
        vpc: The VPC the connector ENIs attach to (required; ``VpcV2`` or classic ``ec2.Vpc``). For image
            builds routed through this connector, the VPC must reach what the build needs (public base
            image + package repos → a NAT gateway, or private mirrors + endpoints).
        vpc_subnets: Which subnets to place ENIs in. Default: ``PRIVATE_WITH_EGRESS``.
        security_group: BYO security group. Default: one created on the VPC with ``allow_all_outbound``.
        allow_all_outbound: Egress posture of the *created* security group. Default ``False``
            (deny-all, least privilege) — add explicit egress rules to open traffic.
        network_protocol: ``'IPv4'`` (default) or ``'DualStack'`` (IPv4 + IPv6).
        operator_role: BYO role Lambda assumes to manage the connector ENIs. Default: a
            least-privilege ENI-creation role (the AWS-documented operator policy).
        name: Explicit connector name (``^[a-zA-Z0-9-_]{1,64}$``). Default: a stable path-derived name.
        removal_policy: Applied to the connector.
        tags: Resource tags for cost allocation.
        overrides: Escape hatch merged verbatim into the L1 ``Properties`` (exact CFN casing).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        vpc_subnets: ec2.SubnetSelection | None = None,
        security_group: ec2.ISecurityGroup | None = None,
        allow_all_outbound: bool = False,
        network_protocol: Literal['IPv4', 'DualStack'] = 'IPv4',
        operator_role: iam.IRole | None = None,
        name: str | None = None,
        removal_policy: RemovalPolicy = RemovalPolicy.DESTROY,
        tags: dict[str, str] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        if network_protocol not in _VALID_NETWORK_PROTOCOLS:
            raise ValueError(f'network_protocol must be one of {sorted(_VALID_NETWORK_PROTOCOLS)}, got {network_protocol!r}')

        self._vpc = vpc
        self._subnets = self._select_subnets(vpc, vpc_subnets)
        subnet_ids = [subnet.subnet_id for subnet in self._subnets]
        if not (_MIN_SUBNETS <= len(subnet_ids) <= _MAX_SUBNETS):
            raise ValueError(f'a connector needs {_MIN_SUBNETS}-{_MAX_SUBNETS} subnets (all in one VPC), resolved {len(subnet_ids)}')

        self._security_group = security_group or ec2.SecurityGroup(
            self,
            'SecurityGroup',
            vpc=vpc,
            description='MicroVM egress connector security group (rules ARE the egress policy)',
            allow_all_outbound=allow_all_outbound,
        )
        self._operator_role = operator_role or security.build_connector_operator_role(self, 'OperatorRole')

        self._name = self._resolve_name(name)
        self._resource = lambda_.CfnNetworkConnector(
            self,
            'Resource',
            name=self._name,
            operator_role=self._operator_role.role_arn,
            configuration=lambda_.CfnNetworkConnector.ConfigProperty(
                vpc_egress_configuration=lambda_.CfnNetworkConnector.VpcEgressConfigurationProperty(
                    associated_compute_resource_types=[_MICROVM_COMPUTE_RESOURCE_TYPE],
                    subnet_ids=subnet_ids,
                    security_group_ids=[self._security_group.security_group_id],
                    network_protocol=network_protocol,
                )
            ),
            tags=[CfnTag(key=key, value=value) for key, value in tags.items()] if tags else None,
        )
        for key, value in (overrides or {}).items():
            self._resource.add_property_override(key, value)
        self._resource.apply_removal_policy(removal_policy)
        self._resource.node.add_dependency(self._operator_role)

    # --- public surface -------------------------------------------------------

    @property
    def connector_arn(self) -> str:
        """``Fn::GetAtt Arn`` — feed into ``LambdaMicroVM(egress_connectors=[...])`` or ``run_microvm``."""
        return self._resource.attr_arn

    @property
    def state(self) -> str:
        """``Fn::GetAtt State`` (deploy-time token)."""
        return self._resource.attr_state

    @property
    def connector_name(self) -> str:
        """The resolved connector ``Name`` (stable across synths)."""
        return self._name

    @property
    def vpc(self) -> ec2.IVpc:
        """The (BYO) VPC the connector ENIs attach to."""
        return self._vpc

    @property
    def subnets(self) -> list[ec2.ISubnet]:
        """The subnets the connector ENIs live in — e.g. for placing VPC interface endpoints alongside them."""
        return list(self._subnets)

    @property
    def security_group(self) -> ec2.ISecurityGroup:
        """The connector security group — define egress with ``add_egress_rule(ec2.Peer..., ec2.Port...)``."""
        return self._security_group

    @property
    def operator_role(self) -> iam.IRole:
        """The ENI-management role actually used (created least-privilege unless supplied)."""
        return self._operator_role

    # --- private helpers ------------------------------------------------------

    @staticmethod
    def _select_subnets(vpc: ec2.IVpc, vpc_subnets: ec2.SubnetSelection | None) -> list[ec2.ISubnet]:
        selection = vpc_subnets or ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
        selected = vpc.select_subnets(
            availability_zones=selection.availability_zones,
            one_per_az=selection.one_per_az,
            subnet_filters=selection.subnet_filters,
            subnet_group_name=selection.subnet_group_name,
            subnets=selection.subnets,
            subnet_type=selection.subnet_type,
        )
        return list(selected.subnets)

    def _resolve_name(self, name: str | None) -> str:
        if name is None:
            return Names.unique_resource_name(self, max_length=64, allowed_special_characters='-_')
        if not _NAME_PATTERN.match(name):
            raise ValueError(f'name must match ^[a-zA-Z0-9-_]{{1,64}}$, got: {name!r}')
        return name
