# Getting Started

## Install

```bash
pip install lambda-microvm-cdk
```

## Minimal image

```python
from aws_cdk import Stack
from lambda_microvm_cdk import MicrovmImage, MicrovmSource, Architecture, MicrovmSize


class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)
        MicrovmImage(self, "AgentImage",
            source=MicrovmSource.from_asset("microvm_app"),  # dir with a Dockerfile
            architecture=Architecture.ARM_64,                # default
            size=MicrovmSize.MEM_2GB,
            environment={"LOG_LEVEL": "info"},
        )
```

## Escape hatch for un-modeled properties

Any keyword argument not matched by a typed prop is merged into the underlying
`AWS::Lambda::MicrovmImage` properties, so you are never blocked waiting for a release:

```python
MicrovmImage(self, "Img",
    source=MicrovmSource.from_asset("microvm_app"),
    SomeBrandNewProperty={"foo": "bar"},   # passed through verbatim
)
```

## Sample app

The [`sample/`](https://github.com/ran-isenberg/lambda-microvm-cdk-python/tree/main/sample) app deploys a
MicroVM that runs **Claude headless on Amazon Bedrock (Opus 4.8, us-east-1)**. It is the target of
the E2E test (`make e2e`): boot the VM, send a prompt, assert the result.

```bash
make deploy   # cdk deploy the sample
make e2e      # invoke the MicroVM with a prompt and assert
make destroy  # tear down
```
