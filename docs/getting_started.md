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
# outputs -> MicrovmImageArn, MicrovmExecutionRoleArn, IngressConnectorArn,
#            EgressConnectorArn, MicrovmLogGroupName
```

Then launch, use the endpoint, and terminate:

```python
mv = boto3.client("lambda-microvms", region_name=REGION)
run = mv.run_microvm(
    imageIdentifier=outputs["MicrovmImageArn"],
    executionRoleArn=outputs["MicrovmExecutionRoleArn"],
    ingressNetworkConnectors=[outputs["IngressConnectorArn"]],
    egressNetworkConnectors=[outputs["EgressConnectorArn"]],
    maximumDurationInSeconds=3600,     # hard TTL / cost backstop
)
# ... use run["endpoint"] with an X-aws-proxy-auth token ...
# mv.terminate_microvm(microvmIdentifier=run["microvmId"])  # guaranteed cleanup
```

## Sample app

The [`sample/`](https://github.com/ran-isenberg/lambda-microvm-cdk-python/tree/main/sample) app
deploys a MicroVM that runs a model worker on **Amazon Bedrock (us-east-1)** — Nova 2 Lite by
default, Claude Opus 4.8 opt-in. It is the target of the E2E test (`make e2e`): boot the VM, send a
prompt, assert the deterministic `echo` result, and terminate.

```bash
make deploy   # npx aws-cdk deploy the sample
make e2e      # launch the MicroVM, prompt, assert, terminate in teardown
make destroy  # tear down
```

### Choosing the model: Nova vs Opus

The `/bedrock` tier calls **one** model, selected by the `MODEL_PROVIDER` / `MODEL_ID` env vars. The
deterministic `/echo` tier calls no model, so the library's E2E never depends on either.

| | **Default — Amazon Nova 2 Lite** | **Opt-in — Claude Opus 4.8** |
|---|---|---|
| `MODEL_PROVIDER` | `bedrock` | `anthropic` |
| `MODEL_ID` | `us.amazon.nova-2-lite-v1:0` | `us.anthropic.claude-opus-4-8` |
| SDK / API | boto3 Bedrock **Converse** (model-agnostic) | Anthropic SDK **`AnthropicBedrockMantle`** (Messages) |
| Prerequisite | works out of the box | needs **Bedrock model access** enabled for Opus |
| Why | Nova 2 Lite is inference-profile-only, so the `us.` profile id is used | the Mantle Messages endpoint, not classic `InvokeModel` |

**How to switch.** Set the two env vars — either on the construct (`environment={"MODEL_PROVIDER":
"anthropic", "MODEL_ID": "us.anthropic.claude-opus-4-8"}`) or in the Dockerfile `ENV` — and redeploy.
Env vars are **baked into the snapshot**, so this rebuilds the image to a new version; launch a fresh
VM to pick it up (a running VM keeps the env it booted with). **No IAM change is needed** — the
sample's VM execution role already grants *both* providers (`bedrock:InvokeModel` on the Nova
inference-profile + foundation-model ARNs, and `bedrock-mantle:CreateInference` on the account's
default project), so flipping the provider just works.

### The image (`Dockerfile`)

Everything is installed at **build** time and snapshotted, so no `ALL` OS capability is needed at
runtime. `boto3` drives the default Nova/Converse path; `anthropic` drives the opt-in Opus path.
Model routing is set via non-secret env vars (`AWS_REGION` is injected by the runtime — never set it).

```dockerfile
--8<-- "sample/microvm_app/Dockerfile"
```

### The worker (`worker.py`)

An HTTP server on `:8080` with three isolated tiers so the risky pieces never gate the library:
`/echo` (deterministic — what E2E asserts on), `/bedrock` (one model call), and an opt-in `agent`
tier. It also exposes the runtime lifecycle hooks under `/aws/lambda-microvms/runtime/v1/*` and
`/health`. Secrets are **never** read from image env — per-VM data arrives via the `/run` hook
payload or SSM at runtime.

??? example "worker.py (full source)"

    ```python
    --8<-- "sample/microvm_app/worker/worker.py"
    ```
