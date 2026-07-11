# microvm-cdk — Reusable AWS CDK Construct for Lambda MicroVMs

**Status:** Draft v1 · **Owner:** @isenberg.ran · **Date:** 2026-07-11
**Language:** Python 3.14 · **Framework:** AWS CDK v2 (`aws-cdk-lib`, `constructs`) · **Distribution:** PyPI (pure-Python wheel)

---

## 1. Goal

Ship a **generic, reusable, parameter-driven CDK construct** that provisions an [AWS Lambda MicroVM](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) image (and, optionally, the machinery to launch running MicroVMs). The construct is authored in pure Python 3.14 and published to **PyPI** so any Python CDK app can `pip install microvm-cdk` and drop a MicroVM into its stack.

The repo also contains a **sample CDK app** that consumes the construct and deploys a real, testable MicroVM to AWS. The sample MicroVM runs an **AI-agent worker**: Claude in headless mode using the **Amazon Bedrock** API to do work inside the isolated VM.

Two-stage delivery:
- **Stage 1 (this repo):** Construct + sample app + tests, deployable to AWS.
- **Stage 2:** Harden, document, tag, and publish the construct to PyPI.

---

## 2. Background — how Lambda MicroVMs work

Lambda MicroVMs are serverless, Firecracker-based compute environments giving VM-level isolation with full OS capabilities, snapshot-based fast start, configurable ingress/egress networking, and suspend/resume for idle cost control. Primary use cases: AI code sandboxes, interactive dev environments, multi-tenant CI, security scanning.

### Lifecycle (two planes)

| Plane | What | Managed by | In this construct? |
|---|---|---|---|
| **Build / image** | Package code + `Dockerfile` → zip → S3 → `create-microvm-image` builds & snapshots a fully-initialized image | **CloudFormation** via `AWS::Lambda::MicrovmImage` | ✅ Yes (declarative) |
| **Runtime / instance** | `run-microvm` launches a MicroVM from an image; `suspend`/`resume`/`terminate`; `create-microvm-auth-token` for HTTPS access | **Runtime API / SDK** (not CFN) | ✅ Optional launcher Lambda + custom resource |

**Key implication:** CloudFormation only creates the *image*. Actually *running* a MicroVM is a runtime API call. Therefore the construct is split: an always-present **image** part, and an **optional launcher** part (a Lambda + IAM, and optionally a custom resource that boots one VM at deploy time for smoke tests).

### Image build flow (what the construct automates)

1. Bundle `Dockerfile` + app into a zip → upload to S3 (CDK asset).
2. Create an IAM **build role** Lambda assumes to pull the artifact from S3 and write CloudWatch build logs.
3. Declare `AWS::Lambda::MicrovmImage` referencing the S3 artifact + a Lambda-managed **base image** ARN (e.g. `arn:aws:lambda:<region>:aws:microvm-image:al2023-1`, `BaseImageVersion: "0"`).
4. Image builds asynchronously: `CREATING → CREATED` (or `CREATE_FAILED`).

### Run flow (what the optional launcher automates)

`run-microvm` needs: `image-identifier`, `ingress-network-connectors` (AWS-managed ARN, e.g. `…:network-connector:aws-network-connector:ALL_INGRESS`), `egress-network-connectors` (e.g. `INTERNET_EGRESS`, or a customer VPC connector), and an `idle-policy` (`autoResumeEnabled`, `maxIdleDurationSeconds`, `suspendedDurationSeconds`). Access requires a per-request JWE token from `create-microvm-auth-token` sent in the `X-aws-proxy-auth` header; target port via `X-aws-proxy-port` (default 8080), scoped to `allowedPorts`.

---

## 3. `AWS::Lambda::MicrovmImage` — resource contract

L1 resource shape the construct wraps (all properties **Required** unless noted). No L2 exists in `aws-cdk-lib` yet, so we wrap `CfnResource` (or generated L1 if/when available).

| Property | Type | Notes |
|---|---|---|
| `Name` | String | `^[a-zA-Z0-9-_]+$`, 1–64. **Replacement** on change. |
| `Description` | String | Required (may be empty string). |
| `BaseImageArn` | String | e.g. `arn:aws:lambda:<region>:aws:microvm-image:al2023-1`. |
| `BaseImageVersion` | String | **`"0"` at launch**. |
| `BuildRoleArn` | String | IAM role Lambda assumes to build. |
| `CodeArtifact` | `{ Uri: s3://… }` | The zip on S3. |
| `CpuConfigurations` | `[{ Architecture: ARM_64 \| X86_64 }]` | List. |
| `Resources` | `[{ MinimumMemoryInMiB: int }]` | max 1 entry; baseline size (0.5/1/2/4/8 GB tiers). |
| `AdditionalOsCapabilities` | `[String]` | allowed: `ALL`. |
| `EgressNetworkConnectors` | `[String]` | ARNs, max 10 (may be `[]`). |
| `EnvironmentVariables` | `[{ Name, Value }]` | max 50 (may be `[]`). |
| `Hooks` | object | lifecycle hooks (may be `{}`). |
| `Logging` | `{ CloudWatch: {} }` or `{ Disabled: {} }` | exactly one. |
| `Tags` | `[{Key,Value}]` | optional. |

**Return values:** `Ref` → image ARN; `Fn::GetAtt`: `ImageArn`, `State`, `LatestActiveImageVersion`, `LatestFailedImageVersion`, `CreatedAt`, `UpdatedAt`.

**Build role** trust: `lambda.amazonaws.com` with `sts:AssumeRole` + `sts:TagSession`. Permissions: `s3:GetObject` on the artifact; `logs:CreateLogGroup/CreateLogStream/PutLogEvents`; (+ `ecr:GetAuthorizationToken`, `ecr:BatchGetImage` if the `Dockerfile` pulls from private ECR).

---

## 4. Construct API (public surface)

Package `microvm_cdk`. Designed to be **as generic as possible**: sensible defaults, every AWS knob overridable, typed dataclasses instead of raw dicts.

### 4.1 `MicrovmImage` (core, always used)

```python
from aws_cdk import Stack
from constructs import Construct
from microvm_cdk import (
    MicrovmImage, MicrovmImageProps, Architecture, MicrovmSize,
    LoggingConfig, EnvVar,
)

class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)

        image = MicrovmImage(self, "AgentImage",
            # --- source: pick ONE of the following ---
            source=MicrovmSource.from_asset("sample/microvm_app"),  # dir w/ Dockerfile -> zipped, uploaded
            # source=MicrovmSource.from_s3(bucket, "images/app.zip"),
            # source=MicrovmSource.from_asset_zip("build/app.zip"),

            name="agent-image",                       # optional -> defaults to a stable derived name
            description="Claude headless agent VM",
            base_image="al2023-1",                    # short alias OR full ARN; version defaults "0"
            architecture=Architecture.ARM_64,          # default ARM_64
            size=MicrovmSize.MEM_2GB,                  # -> MinimumMemoryInMiB; default MEM_1GB
            os_capabilities=[OsCapability.ALL],        # default []
            environment={"LOG_LEVEL": "info"},         # dict -> EnvironmentVariables
            egress_connectors=[],                       # default [] (internet egress at run-time)
            logging=LoggingConfig.cloud_watch(),        # default cloud_watch(); or LoggingConfig.disabled()
            hooks=None,                                 # optional lifecycle hooks
            build_role=None,                            # optional: bring-your-own IAM role
            tags={"project": "microvm-cdk"},
        )

        image.image_arn   # token -> Fn::GetAtt ImageArn
        image.state
        image.build_role  # the iam.IRole used (created if not supplied)
```

Responsibilities:
- Zip + upload the source asset (S3) using CDK assets; wire `CodeArtifact.Uri`.
- Create the build role (least-privilege scoped to the asset bucket/key) unless one is passed.
- Resolve `base_image` alias → region-correct ARN; default `BaseImageVersion="0"`.
- Emit the `AWS::Lambda::MicrovmImage` L1 with all defaults filled so consumers set only what they care about.
- Expose typed getters (`image_arn`, `state`, `build_role`) + `grant_run(principal)` helper that attaches `lambda:RunMicrovm`/`lambda:*Microvm*` to a launcher principal.

### 4.2 `MicrovmLauncher` (optional)

Provisions a Lambda that calls `run-microvm` / `suspend` / `resume` / `terminate` / `create-microvm-auth-token`, with an execution role scoped to the image. Optionally exposes a Function URL / API Gateway front door and/or a **CloudFormation custom resource** that boots one MicroVM at deploy time (smoke test).

```python
from microvm_cdk import MicrovmLauncher, IngressConnector, EgressConnector, IdlePolicy

launcher = MicrovmLauncher(self, "Launcher",
    image=image,
    ingress=IngressConnector.all_ingress(),        # AWS-managed ARN helper
    egress=EgressConnector.internet(),             # or EgressConnector.vpc(connector_arn)
    idle_policy=IdlePolicy(auto_resume=True, max_idle_seconds=900, suspended_seconds=300),
    boot_on_deploy=False,                          # True -> custom resource runs one VM as a smoke test
    expose="function_url",                         # None | "function_url" | "api_gateway"
)
launcher.function        # the aws_lambda.Function
launcher.endpoint_url    # if exposed
```

### 4.3 Typed helpers (generic surface)

- `Architecture` (`ARM_64`, `X86_64`), `MicrovmSize` (`MEM_512MB … MEM_8GB` → `MinimumMemoryInMiB`).
- `LoggingConfig.cloud_watch() | .disabled()`.
- `MicrovmSource.from_asset(dir) | .from_asset_zip(path) | .from_s3(bucket, key)`.
- `IngressConnector` / `EgressConnector` ARN builders (region/partition aware).
- `IdlePolicy`, `EnvVar`, `OsCapability`, `LifecycleHooks`.
- All props are `@dataclass`es / kwargs with docstrings so Python IDEs give completion.

**Genericity principles:** (1) every CFN field overridable; (2) `escape_hatch` — expose the underlying `CfnResource` via `.node.default_child` and allow `overrides={}` passthrough for anything not yet modeled; (3) no hard-coded account/region — resolve via `Stack.of(self)`; (4) validation in `__init__` with clear errors (name regex, size tiers, exactly-one logging).

---

## 5. Repository layout

```
microvm/                                 # repo root
├── SPEC.md                              # this file
├── README.md                           # quickstart + API
├── LICENSE                             # MIT-0
├── CHANGELOG.md
├── .gitignore
├── .python-version                     # 3.14
├── pyproject.toml                      # hatchling build; package = microvm_cdk
├── src/
│   └── microvm_cdk/
│       ├── __init__.py                 # public exports
│       ├── image.py                    # MicrovmImage + MicrovmImageProps
│       ├── launcher.py                 # MicrovmLauncher
│       ├── source.py                   # MicrovmSource (asset/s3)
│       ├── networking.py               # Ingress/Egress connector ARN helpers
│       ├── types.py                    # Architecture, MicrovmSize, LoggingConfig, IdlePolicy, EnvVar…
│       ├── build_role.py               # default least-privilege build role
│       └── _lambda/launcher/           # launcher handler source (bundled asset)
│           └── handler.py
├── sample/                              # deployable sample app (the integ test target)
│   ├── app.py                          # CDK app entrypoint
│   ├── cdk.json
│   ├── requirements.txt                # aws-cdk-lib, constructs, -e ../ (local construct)
│   ├── sample_stack.py                 # uses MicrovmImage + MicrovmLauncher
│   └── microvm_app/                    # what runs INSIDE the VM
│       ├── Dockerfile                  # AL2023 base; installs Claude Code CLI + deps
│       └── worker/
│           └── worker.py               # HTTP server on :8080; runs `claude` headless via Bedrock
├── tests/
│   ├── unit/                           # cdk.assertions Template.from_stack(...) matchers
│   │   ├── test_image.py
│   │   └── test_launcher.py
│   └── integ/
│       └── test_deploy.py              # optional: cdk deploy + hit endpoint (gated by env)
└── .github/workflows/
    ├── ci.yml                          # lint (ruff) + type (mypy/pyright) + unit tests + cdk synth
    └── release.yml                     # tag -> build wheel -> PyPI Trusted Publishing (OIDC)
```

---

## 6. Sample app — Claude headless agent on Bedrock

**Inside the MicroVM** (`sample/microvm_app/`):
- `Dockerfile`: start from a compatible base (e.g. AL2023 / `node`+`python`), install the **Claude Code CLI** (headless), Python, and the worker. `EXPOSE 8080`, `CMD` starts `worker.py`. (Base OS/service layer comes from `--base-image-arn`, so this image is just app layers.)
- `worker.py`: minimal HTTP server on `:8080`. On request (or via a `/run` lifecycle-hook payload, mirroring the aws-samples pattern), it invokes Claude in **headless mode** configured to use the **Amazon Bedrock** backend (`CLAUDE_CODE_USE_BEDROCK=1`, region + model id via env), runs the requested task in the isolated VM, and returns the result.
- Credentials: the MicroVM uses its execution role for Bedrock (`bedrock:InvokeModel`); no long-lived keys baked in. CSPRNG note honored for any generated IDs.

**The stack** (`sample/sample_stack.py`): builds the image from `microvm_app/`, sets `size=MEM_2GB`, `architecture=ARM_64`, passes Bedrock env (`AWS_REGION`, model id), and adds a `MicrovmLauncher` with `boot_on_deploy=True` so `cdk deploy` produces a running VM whose endpoint we can curl end-to-end.

**IAM for the agent VM:** execution role with `bedrock:InvokeModel` (+ `bedrock:InvokeModelWithResponseStream`) scoped to the chosen model ARNs; CloudWatch logs.

---

## 7. Packaging & PyPI (Stage 2)

- **Tooling:** [`uv`](https://docs.astral.sh/uv/) for envs/locking (`uv.lock`), [`ruff`](https://docs.astral.sh/ruff/) for lint+format (line-length 150, single quotes, rules `E,W,F,I,C,B`), `mypy` strict — matching [ran-isenberg/aws-lambda-env-modeler](https://github.com/ran-isenberg/aws-lambda-env-modeler).
- **Build backend:** `hatchling`. `pyproject.toml` declares `name = "microvm-cdk"`, `requires-python = ">=3.14"`, deps `aws-cdk-lib>=2`, `constructs>=10`. **License: MIT-0.**
- **Pure Python** (per decision): no jsii/TypeScript. Consumable by Python CDK apps only. (If polyglot is ever needed, the escape path is a separate jsii/projen rewrite — noted, not planned.)
- **Versioning:** SemVer; `0.x` during Stage 1. Keep `CHANGELOG.md`.
- **Publish:** GitHub Actions `release.yml` on tag `v*` → build sdist+wheel → **PyPI Trusted Publishing (OIDC)**, no stored token. TestPyPI dry-run first.
- **Docs:** README with install + copy-paste example; docstrings on all public classes; optional API docs later.

---

## 8. Testing strategy

1. **Unit (fast, no AWS):** `aws_cdk.assertions.Template.from_stack()` — assert the synthesized template has `AWS::Lambda::MicrovmImage` with expected `BaseImageVersion "0"`, build role policy, `CodeArtifact.Uri` wired to the asset, defaults applied, and validation errors raise. Run in CI.
2. **Synth smoke:** `cdk synth` the sample app in CI (no deploy).
3. **Integration (gated, real AWS):** `cdk deploy` the sample stack with `boot_on_deploy=True`; poll image `CREATED`, VM `RUNNING`, mint an auth token, `curl` the endpoint, assert the Claude/Bedrock worker responds; `cdk destroy`. Gated behind an env flag + AWS creds so it doesn't run on every push.

---

## 9. Open questions / assumptions

- **Region availability:** confirm MicroVMs + `AWS::Lambda::MicrovmImage` are available in the target region; default `us-east-1` unless told otherwise.
- **L1 availability:** if `aws-cdk-lib` ships a generated `CfnMicrovmImage`, prefer it; otherwise wrap `CfnResource("AWS::Lambda::MicrovmImage", …)`.
- **Bedrock model:** default Claude model id on Bedrock (e.g. an Anthropic Claude on Bedrock inference profile) — confirm exact id/region for the sample.
- **Boot-on-deploy custom resource:** running VMs cost money and outlive simple stacks; default `False`, opt-in for integ tests, with cleanup on stack delete (terminate-microvm).
- **Base image versions:** `"0"` today; may need a lookup as AWS publishes new base image versions.

---

## 10. Delivery phases

**Phase 0 — Repo bootstrap** (this commit): git init, `SPEC.md`, `README.md`, `LICENSE`, `.gitignore`, `pyproject.toml`, `.python-version`, empty `src/microvm_cdk` package.

**Phase 1 — Core construct:** `MicrovmImage`, `MicrovmSource`, build role, `types.py`; unit tests green; `cdk synth` of a trivial stack works.

**Phase 2 — Sample app:** `microvm_app/` (Dockerfile + Claude/Bedrock `worker.py`), `sample_stack.py`, `app.py`, `cdk.json`; synths clean.

**Phase 3 — Launcher:** `MicrovmLauncher` + launcher handler + optional boot-on-deploy custom resource; grants; unit tests.

**Phase 4 — Deploy & integ:** real `cdk deploy` to AWS, end-to-end curl against the agent VM, fix issues, document.

**Phase 5 — Publish (Stage 2):** finalize README/docstrings, CHANGELOG, CI + release workflow, tag, publish to (Test)PyPI.

---

## 11. Key references

- Lambda MicroVMs guide — https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html
- Getting started — https://docs.aws.amazon.com/lambda/latest/dg/microvms-getting-started.html
- Networking — https://docs.aws.amazon.com/lambda/latest/dg/microvms-networking.html
- `AWS::Lambda::MicrovmImage` — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-lambda-microvmimage.html
- SAM/TypeScript reference sample — https://github.com/aws-samples/sample-lambda-microvm-claude-managed-agents
- CDK MicroVM (Python) walkthrough — https://dev.to/aws-builders/i-made-an-aws-lambda-microvm-publicly-accessible-for-0month-heres-the-full-setup-36fn
- PyPI Trusted Publishing — https://docs.pypi.org/trusted-publishers/
