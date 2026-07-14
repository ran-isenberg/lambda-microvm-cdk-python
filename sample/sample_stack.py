"""Sample stack — a MicroVM image running the tiered model worker (Nova default / Opus opt-in).

Provides everything the E2E fixture needs as clean stack-level CfnOutputs; the running
VM itself is launched by the fixture/consumer via boto3 (runtime API, not CloudFormation).
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, RemovalPolicy, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk.aws_ec2_alpha import IpAddresses, IpCidr, NatConnectivityType, Route, RouteTargetType, SubnetV2, VpcV2
from cdk_nag import NagSuppressions
from constructs import Construct, IConstruct

from lambda_microvm_cdk import LambdaMicroVM, MicrovmNetworkConnector

# Default worker model: Amazon Nova 2 Lite. It is INFERENCE_PROFILE-only, so it must be invoked via the
# cross-region profile — which fans out to us-east-1/2 + us-west-2, so the grant needs the profile ARN
# AND the underlying foundation-model ARN (region-wildcarded, model id pinned). Both validated.
NOVA_INFERENCE_PROFILE_ID = 'us.amazon.nova-2-lite-v1:0'
NOVA_FOUNDATION_MODEL_ID = 'amazon.nova-2-lite-v1:0'
MICROVM_APP_DIR = Path(__file__).parent / 'microvm_app'


class SampleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        # Build the VPC egress connector first so it can be baked into the image as its egress path.
        # egress_connectors is BUILD-time egress (the build runs the Dockerfile in a MicroVM), so the
        # VPC MUST reach public.ecr.aws + PyPI — hence the NAT gateway in _build_egress_vpc.
        connector = self._build_vpc_egress()
        image = LambdaMicroVM(
            self,
            'AgentImage',
            source=str(MICROVM_APP_DIR),
            name='lambda-microvm-cdk-sample',
            description='MicroVM sample: echo + Bedrock model tiers (Nova 2 Lite default / Opus 4.8 opt-in)',
            memory_mib=2048,
            # Stream build + runtime stdout/stderr to the service-owned CloudWatch log group
            # /aws/lambda/microvms/lambda-microvm-cdk-sample (streams named by microvmId). Default is
            # already True — set explicitly so it's obvious the sample is observable.
            enable_logging=True,
            # NEVER secrets here — image env is snapshotted and shared. Model routing env
            # lives in the Dockerfile; AWS_REGION is reserved (the runtime injects it).
            environment={'LOG_LEVEL': 'info'},
            # Route ALL egress (build + runtime default) through our VPC connector — the connector object
            # is accepted directly (coerced to its ARN). The VPC's NAT gateway lets the build reach the
            # internet; Bedrock is reachable the same way at runtime.
            egress_connectors=[connector],
            tags={'project': 'lambda-microvm-cdk', 'component': 'sample'},
        )
        self._grant_bedrock_invoke(image)
        self._apply_nag_suppressions(image, connector)
        Tags.of(self).add('project', 'lambda-microvm-cdk')

        # Clean stack-level output keys — exactly what the E2E fixture feeds into run_microvm.
        CfnOutput(self, 'MicrovmImageArn', value=image.image_arn)
        CfnOutput(self, 'MicrovmImageName', value=image.image_name)
        CfnOutput(self, 'MicrovmExecutionRoleArn', value=image.execution_role.role_arn)
        CfnOutput(self, 'IngressConnectorArn', value=image.ingress_connector_arn)
        CfnOutput(self, 'EgressConnectorArn', value=image.egress_connector_arn)
        CfnOutput(self, 'VpcEgressConnectorArn', value=connector.connector_arn)
        CfnOutput(self, 'MicrovmLogGroupName', value=image.log_group_name)

    def _grant_bedrock_invoke(self, image: LambdaMicroVM) -> None:
        """Grant the VM execution role model access for BOTH worker providers (selected at runtime by
        ``MODEL_PROVIDER``), so flipping the env needs no IAM change.

        - **Nova (default)** via the boto3 Bedrock **Converse** API authorizes with ``bedrock:InvokeModel``
          on the inference-profile ARN + the underlying foundation-model ARN it fans out to (region
          wildcard, model id pinned — Nova 2 Lite is INFERENCE_PROFILE-only).
        - **Opus (opt-in)** via ``AnthropicBedrockMantle`` authorizes with ``bedrock-mantle:CreateInference``
          on the account's default project — the Messages-API endpoint, NOT classic InvokeModel (using the
          wrong action returns a 500).
        """
        image.execution_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid='InvokeNovaOnBedrock',
                actions=['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
                resources=[
                    f'arn:{self.partition}:bedrock:{self.region}:{self.account}:inference-profile/{NOVA_INFERENCE_PROFILE_ID}',
                    f'arn:{self.partition}:bedrock:*::foundation-model/{NOVA_FOUNDATION_MODEL_ID}',
                ],
            )
        )
        image.execution_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid='InvokeClaudeOnBedrockMantle',
                actions=['bedrock-mantle:CreateInference'],
                resources=[f'arn:{self.partition}:bedrock-mantle:{self.region}:{self.account}:project/default'],
            )
        )

    def _build_vpc_egress(self) -> MicrovmNetworkConnector:
        """Customer-managed VPC egress the image both builds and runs through. The connector is BYO-VPC,
        so the stack builds a 2-AZ ``VpcV2`` **with a NAT gateway** (see ``_build_egress_vpc``) — the
        image build routes ``public.ecr.aws`` + PyPI over the NAT, and the running VM reaches Bedrock the
        same way. The security group is deny-all by default; we open 443 egress to the internet.
        """
        vpc, private_subnets, connectivity = self._build_egress_vpc()
        connector = MicrovmNetworkConnector(
            self,
            'Egress',
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=private_subnets),
            tags={'project': 'lambda-microvm-cdk', 'component': 'sample'},
        )
        connector.security_group.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), 'HTTPS egress for image build (ECR Public/PyPI) + Bedrock')
        # VpcV2's hand-wired IGW/NAT/routes don't establish the internet-connectivity dependency that
        # classic ec2.Vpc does, so the image build (which depends on the connector) could start before the
        # egress path exists. Make the connector wait for the IGW + NAT + private routes explicitly.
        for dependency in connectivity:
            connector.node.add_dependency(dependency)
        return connector

    def _build_egress_vpc(self) -> tuple[VpcV2, list[ec2.ISubnet], list[IConstruct]]:
        """A 2-AZ ``VpcV2`` with internet egress via a NAT gateway (BYO-VPC for the connector). Public
        subnets hold the IGW route + the NAT; the connector's private (``PRIVATE_WITH_EGRESS``) subnets
        default-route to the NAT so the image build can pull from the public internet. REJECT flow logs
        satisfy cdk-nag VPC7.
        """
        vpc = VpcV2(
            self,
            'EgressVpc',
            primary_address_block=IpAddresses.ipv4('10.0.0.0/16', cidr_block_name='Primary'),
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )
        azs = self.availability_zones[:2]
        public_subnets = [
            SubnetV2(
                self, f'PublicSubnet{i}', vpc=vpc, availability_zone=az, ipv4_cidr_block=IpCidr(f'10.0.{i}.0/24'), subnet_type=ec2.SubnetType.PUBLIC
            )
            for i, az in enumerate(azs)
        ]
        private_subnets: list[ec2.ISubnet] = [
            SubnetV2(
                self,
                f'PrivateSubnet{i}',
                vpc=vpc,
                availability_zone=az,
                ipv4_cidr_block=IpCidr(f'10.0.{i + 10}.0/24'),
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            )
            for i, az in enumerate(azs)
        ]
        igw = vpc.add_internet_gateway(subnets=[ec2.SubnetSelection(subnets=public_subnets)])
        nat = vpc.add_nat_gateway(subnet=public_subnets[0], connectivity_type=NatConnectivityType.PUBLIC)
        routes = [
            Route(self, f'PrivateEgressRoute{i}', route_table=subnet.route_table, destination='0.0.0.0/0', target=RouteTargetType(gateway=nat))
            for i, subnet in enumerate(private_subnets)
        ]
        log_group = logs.LogGroup(self, 'EgressVpcFlowLogGroup', retention=logs.RetentionDays.THREE_DAYS, removal_policy=RemovalPolicy.DESTROY)
        ec2.FlowLog(
            self,
            'EgressVpcFlowLog',
            resource_type=ec2.FlowLogResourceType.from_vpc(vpc),
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(log_group),
            traffic_type=ec2.FlowLogTrafficType.REJECT,
        )
        return vpc, private_subnets, [igw, nat, *routes]

    def _apply_nag_suppressions(self, image: LambdaMicroVM, connector: MicrovmNetworkConnector) -> None:
        """Targeted, justified suppressions only — never blanket."""
        NagSuppressions.add_resource_suppressions(
            image.build_role,
            [
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Build log streams inside the image-scoped log group are created dynamically by the service; '
                    'logs:* must target <group-arn>:*. The s3:GetObject grant is scoped to the exact asset key.',
                }
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            image.execution_role,
            [
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Runtime log streams are named by microvmId at run time, so the runtime-logs grant targets '
                    '<image-log-group-arn>:*. The Nova path uses a region-wildcard foundation-model ARN because the '
                    'cross-region inference profile fans out to us-east-1/2 + us-west-2 (model id pinned); the Mantle grant has no wildcard.',
                }
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            connector.operator_role,
            [
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'Verbatim AWS-documented NetworkConnector operator policy: ec2:CreateNetworkInterface + '
                    'ec2:CreateTags on ec2:*:*:network-interface/subnet/security-group ARNs (region/account wildcarded per the '
                    'doc so Lambda can create the ENIs in its own context; ENI ids dynamic). No Describe/Delete, no bare "*" '
                    'resource; CreateTags is conditioned on the connector managed operator.',
                }
            ],
            apply_to_children=True,
        )
        log_retention_singletons: list[IConstruct] = [child for child in self.node.children if child.node.id.startswith('LogRetention')]
        for singleton in log_retention_singletons:
            NagSuppressions.add_resource_suppressions(
                singleton,
                [
                    {'id': 'AwsSolutions-IAM4', 'reason': 'CDK-managed LogRetention singleton provider uses AWSLambdaBasicExecutionRole.'},
                    {'id': 'AwsSolutions-IAM5', 'reason': 'CDK-managed LogRetention provider sets retention on log groups created later.'},
                ],
                apply_to_children=True,
            )
