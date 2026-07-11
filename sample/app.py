"""Sample CDK app entrypoint — cdk-nag AwsSolutionsChecks runs on every synth (SPEC.md §5.9)."""

from __future__ import annotations

import os

from aws_cdk import App, Aspects, Environment
from cdk_nag import AwsSolutionsChecks
from sample_stack import SampleStack

app = App()
SampleStack(
    app,
    'LambdaMicrovmSampleStack',
    env=Environment(
        account=os.environ.get('CDK_DEFAULT_ACCOUNT'),
        # MicroVMs are verified in us-east-1 only so far (SPEC.md §14).
        region=os.environ.get('CDK_DEFAULT_REGION', 'us-east-1'),
    ),
    description='lambda-microvm-cdk sample: Bedrock-backed MicroVM image (Nova 2 Lite default / Opus opt-in; E2E target)',
)
Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
app.synth()
