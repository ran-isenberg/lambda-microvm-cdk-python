# microvm-cdk

A reusable **AWS CDK v2 construct (pure Python 3.14)** for provisioning
[AWS Lambda MicroVMs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) —
Firecracker-based, VM-isolated, snapshot-fast serverless compute for AI sandboxes,
interactive dev environments, and multi-tenant CI.

> **Status:** early development. See [SPEC.md](SPEC.md) for the full plan and API design.

## What it does

- **`MicrovmImage`** — declarative `AWS::Lambda::MicrovmImage`: zips your `Dockerfile`+app,
  uploads it to S3, creates a least-privilege build role, and builds a snapshotted MicroVM image.
- **`MicrovmLauncher`** *(optional)* — a Lambda + IAM that launches/suspends/resumes/terminates
  running MicroVMs via the runtime API, with an optional boot-on-deploy smoke test.

Everything is parameter-driven with sensible defaults — override any AWS knob, or drop to the
underlying L1 resource via an escape hatch.

## Quickstart (planned API)

```python
from aws_cdk import Stack
from microvm_cdk import MicrovmImage, MicrovmSource, Architecture, MicrovmSize

class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)
        MicrovmImage(self, "AgentImage",
            source=MicrovmSource.from_asset("microvm_app"),
            architecture=Architecture.ARM_64,
            size=MicrovmSize.MEM_2GB,
            environment={"LOG_LEVEL": "info"},
        )
```

## Sample app

[`sample/`](sample/) is a deployable CDK app whose MicroVM runs **Claude in headless mode
against the Amazon Bedrock API** — a self-contained AI-agent worker used as the end-to-end
deploy test.

## Development

Uses [uv](https://docs.astral.sh/uv/) and [ruff](https://docs.astral.sh/ruff/).

```bash
uv sync                 # create venv + install deps (incl. dev group)
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run pytest
```

## License

MIT-0
