"""Sample stack — a MicroVM image running the tiered model worker (Nova default / Opus opt-in; SPEC.md §11).

Provides everything the E2E fixture needs as clean stack-level CfnOutputs; the running
VM itself is launched by the fixture/consumer via boto3 (runtime API, not CloudFormation).
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Stack, Tags
from aws_cdk import aws_iam as iam
from cdk_nag import NagSuppressions
from constructs import Construct, IConstruct

from lambda_microvm_cdk import LambdaMicroVM

# Default worker model: Amazon Nova 2 Lite. It is INFERENCE_PROFILE-only, so it must be invoked via the
# cross-region profile — which fans out to us-east-1/2 + us-west-2, so the grant needs the profile ARN
# AND the underlying foundation-model ARN (region-wildcarded, model id pinned). Both validated §0.
NOVA_INFERENCE_PROFILE_ID = 'us.amazon.nova-2-lite-v1:0'
NOVA_FOUNDATION_MODEL_ID = 'amazon.nova-2-lite-v1:0'
MICROVM_APP_DIR = Path(__file__).parent / 'microvm_app'


class SampleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

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
            # NEVER secrets here — image env is snapshotted and shared (§5.3). Model routing env
            # lives in the Dockerfile; AWS_REGION is reserved (the runtime injects it, §0).
            environment={'LOG_LEVEL': 'info'},
            tags={'project': 'lambda-microvm-cdk', 'component': 'sample'},
        )
        self._grant_bedrock_invoke(image)
        self._apply_nag_suppressions(image)
        Tags.of(self).add('project', 'lambda-microvm-cdk')

        # Clean stack-level output keys — exactly what the E2E fixture feeds into run_microvm (§4.5, §12).
        CfnOutput(self, 'MicrovmImageArn', value=image.image_arn)
        CfnOutput(self, 'MicrovmImageName', value=image.image_name)
        CfnOutput(self, 'MicrovmExecutionRoleArn', value=image.execution_role.role_arn)
        CfnOutput(self, 'IngressConnectorArn', value=image.ingress_connector_arn)
        CfnOutput(self, 'EgressConnectorArn', value=image.egress_connector_arn)
        CfnOutput(self, 'MicrovmLogGroupName', value=image.log_group_name)

    def _grant_bedrock_invoke(self, image: LambdaMicroVM) -> None:
        """Grant the VM execution role model access for BOTH worker providers (selected at runtime by
        ``MODEL_PROVIDER``), so flipping the env needs no IAM change.

        - **Nova (default)** via the boto3 Bedrock **Converse** API authorizes with ``bedrock:InvokeModel``
          on the inference-profile ARN + the underlying foundation-model ARN it fans out to (region
          wildcard, model id pinned — Nova 2 Lite is INFERENCE_PROFILE-only, §0).
        - **Opus (opt-in)** via ``AnthropicBedrockMantle`` authorizes with ``bedrock-mantle:CreateInference``
          on the account's default project — the Messages-API endpoint, NOT classic InvokeModel (the wrong
          action was the spike's uncaptured 500, confirmed by E2E; §0).
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

    def _apply_nag_suppressions(self, image: LambdaMicroVM) -> None:
        """Targeted, justified suppressions only — never blanket (SPEC.md §5.9)."""
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
