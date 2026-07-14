# Getting Started

## Install

```bash
pip install lambda-microvm-cdk
```

## Minimal image

```python
from aws_cdk import Stack
from lambda_microvm_cdk import LambdaMicroVM


class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)
        LambdaMicroVM(self, "AgentImage",
            source="microvm_app",              # dir with a Dockerfile (also: .zip path or s3_assets.Asset)
            memory_mib=2048,                   # tier: 512|1024|2048|4096|8192
            environment={"LOG_LEVEL": "info"}, # NEVER secrets — baked into the snapshot
            # architecture defaults to ARM_64 (only value the service accepts today)
        )
```

Inputs reuse standard CDK types — `architecture` takes `aws_lambda.Architecture`, `log_retention`
takes `aws_logs.RetentionDays`, and `source` accepts a directory path, a `.zip` path, or an
`aws_s3_assets.Asset`.

## Escape hatch for un-modeled properties

`overrides` is merged **verbatim** into the underlying `AWS::Lambda::MicrovmImage` `Properties`
(exact CloudFormation casing, no auto-casing), so you are never blocked waiting for a release:

```python
LambdaMicroVM(self, "Img",
    source="microvm_app",
    overrides={"SomeBrandNewProperty": {"foo": "bar"}},   # passed through verbatim
)
```

## Launching a VM (runtime, boto3)

Running a MicroVM is a runtime API call, not CloudFormation. Wire the construct's typed properties
(surfaced by your stack as `CfnOutput`s) into `run_microvm`, and **always** terminate in teardown.

First read the deploy-time outputs your stack exposed (this is exactly what the E2E fixture does):

```python
import boto3

REGION, STACK = "us-east-1", "LambdaMicrovmSampleStack"

cfn = boto3.client("cloudformation", region_name=REGION)
stack = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
# outputs -> MicrovmImageArn, MicrovmImageName, MicrovmExecutionRoleArn, IngressConnectorArn,
#            EgressConnectorArn (AWS-managed INTERNET_EGRESS), VpcEgressConnectorArn (custom VPC),
#            MicrovmLogGroupName
```

Then launch, use the endpoint, and terminate:

```python
mv = boto3.client("lambda-microvms", region_name=REGION)
run = mv.run_microvm(
    imageIdentifier=outputs["MicrovmImageArn"],
    executionRoleArn=outputs["MicrovmExecutionRoleArn"],
    ingressNetworkConnectors=[outputs["IngressConnectorArn"]],
    # Egress: the AWS-managed internet connector, or outputs["VpcEgressConnectorArn"] for VPC egress.
    egressNetworkConnectors=[outputs["EgressConnectorArn"]],
    # RUNTIME logs are configured per-launch — the image's logging config covers BUILD logs only, so
    # without this the running VM writes no CloudWatch stream. Stream to the same service-owned group.
    logging={"cloudWatch": {"logGroup": outputs["MicrovmLogGroupName"]}},
    maximumDurationInSeconds=3600,     # hard TTL / cost backstop
)
# ... use run["endpoint"] with an X-aws-proxy-auth token ...
# mv.terminate_microvm(microvmIdentifier=run["microvmId"])  # guaranteed cleanup
```

See the [Sample App](sample.md) page for a full deployable example (the Bedrock model worker + E2E).
