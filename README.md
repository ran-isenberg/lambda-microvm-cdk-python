# lambda-microvm-cdk

A reusable **AWS CDK v2 construct (pure Python, 3.11+)** for provisioning
[AWS Lambda MicroVMs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) —
Firecracker-based, VM-isolated, snapshot-fast serverless compute for AI sandboxes,
interactive dev environments, and multi-tenant CI.

> **Status:** early development. See [SPEC.md](SPEC.md) for the full plan, validated API facts, and design.
> Repo: `lambda-microvm-cdk-python` · PyPI package (planned): `lambda-microvm-cdk`.

## What it does

- **`MicrovmImage`** — declarative `AWS::Lambda::MicrovmImage`: zips your `Dockerfile`+app,
  uploads it to S3, creates a least-privilege build role, resolves the base-image version, and
  builds a snapshotted MicroVM image. Emits CloudFormation outputs (image ARN, VM execution role,
  connector ARNs, log group) for launching VMs.
- **Runtime** (run/suspend/terminate a MicroVM) is a runtime API call, so it's driven with **boto3**
  from your app or the E2E test fixture using the stack outputs — no launcher Lambda / API Gateway /
  WAF in the current scope (a thin launcher is a deferred, opt-in add-on).

Everything is parameter-driven with secure defaults (arm64, no extra OS capabilities, CloudWatch
logging) — override any AWS knob, or drop to the underlying L1 resource via an `overrides` escape hatch.

## Quickstart (planned API)

```python
from aws_cdk import Stack
from lambda_microvm_cdk import MicrovmImage, MicrovmSource, Architecture, MicrovmSize

class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)
        MicrovmImage(self, "AgentImage",
            source=MicrovmSource.from_asset("microvm_app"),  # dir with a Dockerfile
            architecture=Architecture.ARM_64,                # only arch the service accepts today
            size=MicrovmSize.MEM_2GB,
            environment={"LOG_LEVEL": "info"},               # never secrets — snapshotted
        )
```

## Sample app

[`sample/`](sample/) is a deployable CDK app whose MicroVM runs an AI-agent worker on **Amazon
Bedrock (Claude Opus 4.8, us-east-1)**. The worker is tiered — a deterministic no-model **echo**
path (what E2E asserts on), a direct **Bedrock** SDK call, and an opt-in **Claude Code headless**
tier — so the library's tests never depend on the agent working.

## Development

Uses [uv](https://docs.astral.sh/uv/) and [ruff](https://docs.astral.sh/ruff/) (see the [Makefile](Makefile)).

```bash
make dev        # uv sync (venv + dev deps)
make lint       # ruff format --check + ruff check + mypy
make unit       # unit tests (no AWS)
make synth      # cdk synth the sample app
```

## License

MIT-0
