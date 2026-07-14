"""Least-privilege IAM role builders. Build role ≠ VM execution role — each is purpose-built."""

from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

_MICROVM_SERVICE_PRINCIPAL = 'lambda.amazonaws.com'

CONNECTOR_OPERATOR_ROLE_DESCRIPTION = 'Least-privilege operator role Lambda assumes to manage the MicroVM connector ENIs'
# The managed-resource operator that creates the connector's ENIs — the value CreateTags is conditioned on.
_CONNECTOR_MANAGED_RESOURCE_OPERATOR = 'network-connectors.lambda.amazonaws.com'


def _microvm_service_trust(role: iam.Role) -> None:
    """Add ``sts:TagSession`` to the trust policy (the service assumes with session tags)."""
    assume_role_policy = role.assume_role_policy
    if assume_role_policy is not None:
        assume_role_policy.add_statements(
            iam.PolicyStatement(
                actions=['sts:TagSession'],
                principals=[iam.ServicePrincipal(_MICROVM_SERVICE_PRINCIPAL)],
            )
        )


def log_group_arn(scope: Construct, log_group_name: str) -> str:
    """ARN of the service-owned image log group (``/aws/lambda/microvms/<image-name>``)."""
    stack = Stack.of(scope)
    return f'arn:{stack.partition}:logs:{stack.region}:{stack.account}:log-group:{log_group_name}'


def build_image_build_role(scope: Construct, construct_id: str, *, artifact_object_arn: str, group_arn: str) -> iam.Role:
    """The role the MicroVM service assumes to build the image.

    Scoped to the **exact S3 asset object** (never ``bucket/*``) plus build logs on the
    image's own log group only.
    """
    role = iam.Role(
        scope,
        construct_id,
        assumed_by=iam.ServicePrincipal(_MICROVM_SERVICE_PRINCIPAL),
        description='Least-privilege build role for the Lambda MicroVM image build',
        inline_policies={
            'MicrovmImageBuild': iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid='ReadExactCodeArtifact',
                        actions=['s3:GetObject'],
                        resources=[artifact_object_arn],
                    ),
                    iam.PolicyStatement(
                        sid='WriteBuildLogs',
                        actions=['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
                        resources=[group_arn, f'{group_arn}:*'],
                    ),
                ]
            )
        },
    )
    _microvm_service_trust(role)
    return role


def build_vm_execution_role(scope: Construct, construct_id: str, *, group_arn: str) -> iam.Role:
    """The role assumed by the MicroVM during execution.

    Default grants are runtime-logs only (no logs perms → no runtime logs);
    consumers add workload permissions (e.g. Bedrock in the sample) on top.
    """
    role = iam.Role(
        scope,
        construct_id,
        assumed_by=iam.ServicePrincipal(_MICROVM_SERVICE_PRINCIPAL),
        description='Least-privilege execution role assumed by the running MicroVM',
        inline_policies={
            'MicrovmRuntimeLogs': iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid='WriteRuntimeLogs',
                        actions=['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
                        resources=[group_arn, f'{group_arn}:*'],
                    ),
                ]
            )
        },
    )
    _microvm_service_trust(role)
    return role


def build_connector_operator_role(scope: Construct, construct_id: str) -> iam.Role:
    """The role Lambda assumes to create the connector's elastic network interfaces.

    Reproduces **verbatim** the policy AWS documents for a ``NetworkConnector`` operator role (Lambda
    MicroVM *Networking* guide): ``ec2:CreateNetworkInterface`` on ``ec2:*:*:network-interface|subnet|
    security-group/*`` (region/account are wildcards — Lambda creates the ENIs in its own context, so
    pinning them would deny ``CreateNetworkInterface`` and the connector would never become ACTIVE), plus
    ``ec2:CreateTags`` on ENIs conditioned on the connector operator
    (``network-connectors.lambda.amazonaws.com``) so the grant can't tag arbitrary interfaces. Lambda
    performs Describe/Delete itself, so the role needs neither. Trust: ``lambda.amazonaws.com`` assumes it
    via ``sts:AssumeRole`` (no session tags), matching the documented operator-role trust policy. Only the
    partition is resolved from ``Stack.of`` (portability); it renders to the documented ``arn:aws:…``. Pass
    a BYO ``operator_role`` to override.
    """
    # region/account intentionally wildcarded to match the AWS-documented operator policy exactly.
    ec2_scope = f'arn:{Stack.of(scope).partition}:ec2:*:*'
    return iam.Role(
        scope,
        construct_id,
        assumed_by=iam.ServicePrincipal(_MICROVM_SERVICE_PRINCIPAL),
        description=CONNECTOR_OPERATOR_ROLE_DESCRIPTION,
        inline_policies={
            'MicrovmConnectorEnis': iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid='CreateENI',
                        actions=['ec2:CreateNetworkInterface'],
                        resources=[
                            f'{ec2_scope}:network-interface/*',
                            f'{ec2_scope}:subnet/*',
                            f'{ec2_scope}:security-group/*',
                        ],
                    ),
                    iam.PolicyStatement(
                        sid='TagENI',
                        actions=['ec2:CreateTags'],
                        resources=[f'{ec2_scope}:network-interface/*'],
                        conditions={'StringEquals': {'ec2:ManagedResourceOperator': _CONNECTOR_MANAGED_RESOURCE_OPERATOR}},
                    ),
                ]
            )
        },
    )


def grant_run(scope: Construct, grantee: iam.IGrantable, *, image_arn: str, execution_role: iam.IRole | None) -> None:
    """Attach least-privilege runtime-caller permissions to *grantee*.

    ``RunMicrovm`` is scoped to the specific image (and its versions); the VM lifecycle /
    auth-token actions target the account's MicroVM ARNs (running VMs are runtime resources
    whose ids are unknowable at synth — scoped to this account+region, never global ``*``).
    ``iam:PassRole`` is limited to the exact VM execution role.
    """
    stack = Stack.of(scope)
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            sid='RunMicrovmOnImage',
            actions=['lambda:RunMicrovm'],
            resources=[image_arn, f'{image_arn}:*'],
        )
    )
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            sid='ManageRunningMicrovms',
            actions=[
                'lambda:GetMicrovm',
                'lambda:ListMicrovms',
                'lambda:SuspendMicrovm',
                'lambda:ResumeMicrovm',
                'lambda:TerminateMicrovm',
                'lambda:CreateMicrovmAuthToken',
            ],
            resources=[f'arn:{stack.partition}:lambda:{stack.region}:{stack.account}:microvm:*'],
        )
    )
    if execution_role is not None:
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                sid='PassOnlyTheVmExecutionRole',
                actions=['iam:PassRole'],
                resources=[execution_role.role_arn],
                conditions={'StringEquals': {'iam:PassedToService': _MICROVM_SERVICE_PRINCIPAL}},
            )
        )
