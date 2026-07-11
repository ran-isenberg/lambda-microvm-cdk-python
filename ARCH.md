# Architecture — lambda-microvm-cdk

> What this repo is, how it's structured, how it's built and tested, and the conventions it follows.
> For the full, API-validated design and phase plan see [SPEC.md](SPEC.md); for working rules see
> [CLAUDE.md](CLAUDE.md).

## 1. What this repo does

`lambda-microvm-cdk` is a **reusable, pure-Python AWS CDK v2 construct library** for provisioning
[AWS Lambda MicroVMs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) —
Firecracker-based, VM-isolated, snapshot-fast serverless compute (AI sandboxes, interactive dev
environments, multi-tenant CI).

- **Package:** `lambda-microvm-cdk` · **Module:** `lambda_microvm_cdk` · **Repo:** `lambda-microvm-cdk-python`
- **Distribution:** a pure-Python wheel published to PyPI (Stage 2) — consumable by any Python CDK app.
- **Also ships:** a deployable **sample CDK app** whose MicroVM runs a worker calling **Amazon
  Bedrock (Nova 2 Lite by default; Opus 4.8 opt-in via `MODEL_PROVIDER`, us-east-1)**, used as the end-to-end test target.

## 2. Core model — two planes

Lambda MicroVMs split cleanly into two planes, which is the central design fact of this repo
(validated against the live API — see [SPEC.md](SPEC.md) §0):

| Plane | What | CloudFormation? | Where it lives here |
|-------|------|-----------------|---------------------|
| **Image** | `Dockerfile`+app → zip → S3 → build & snapshot | ✅ `AWS::Lambda::MicrovmImage` | the `MicrovmImage` construct |
| **Network connector** | VPC egress (or AWS-managed ingress/internet ARNs) | ✅ `AWS::Lambda::NetworkConnector` | networking helpers (Phase 3) |
| **Running instance** | `RunMicrovm`/`Suspend`/`Resume`/`Terminate`/auth token | ❌ runtime API only | boto3 from app/test code (E2E fixture) |

**Implication:** images and connectors are declarative CDK; *running* a MicroVM is a runtime API
call, driven by boto3 — in this repo, from the E2E pytest fixture using the stack's CloudFormation
outputs. There is intentionally **no launcher Lambda / API Gateway / WAF** in the current scope (a
thin launcher is a deferred, opt-in add-on).

## 3. Public API (surface)

The public API is the single **`LambdaMicroVM`** construct, exported from the package root;
supporting internals are private under `_impl/`.

- **`LambdaMicroVM`** — zips a source (dir with `Dockerfile`, `.zip`, or an `s3_assets.Asset`),
  uploads to S3, creates least-privilege build + VM-execution roles, resolves the base-image
  version (boto3 live lookup), emits `AWS::Lambda::MicrovmImage`, and exposes typed **properties**
  (image ARN, VM execution role, connector ARNs, log group name) that the runtime caller/E2E fixture
  feeds into `run_microvm`. It emits **no `CfnOutput`s** — the consuming stack (see `sample_stack.py`)
  owns those, so the construct never pollutes a consumer's template.
- **No duplicate types** — inputs reuse CDK's own: `aws_lambda.Architecture` (`ARM_64` only
  today), `aws_logs.RetentionDays`, `aws_s3_assets.Asset`; memory is a plain `memory_mib` int,
  `hooks` a verbatim CFN dict.
- **Escape hatch** — `overrides: dict` merged verbatim into the L1 `Properties`, so no consumer
  is ever blocked on an un-modeled field.

See [SPEC.md](SPEC.md) §4 for the full signatures.

## 4. Repository layout

```
├── SPEC.md · ARCH.md · CLAUDE.md · README.md · LICENSE (MIT-0)
├── Makefile                      # dev + pipeline entrypoints
├── pyproject.toml · uv.lock      # uv + hatchling + ruff/mypy; deps incl. boto3
├── zensical.toml + docs/         # GitHub Pages docs
├── src/lambda_microvm_cdk/
│   ├── __init__.py               # public exports only
│   └── _impl/                    # PRIVATE implementation (image, networking, security, base_image, types, props)
├── sample/                       # deployable sample CDK app (E2E target)
│   ├── app.py · sample_stack.py
│   └── microvm_app/              # what runs INSIDE the VM (Dockerfile + tiered worker)
└── tests/
    ├── unit/                     # cdk.assertions Template matchers (no AWS)
    └── e2e/                      # boto3 run_microvm from stack outputs + assert + guaranteed terminate
```

## 5. Security model

Security is a first-class design goal (details in [SPEC.md](SPEC.md) §5):

- **Least privilege on every role.** Build role scoped to the exact S3 asset key + its log group; VM
  execution role scoped to the specific Bedrock inference-profile + foundation-model ARNs and its log
  group; runtime-caller grant scoped to the specific image ARN. No `*`.
- **Secure defaults.** arm64; `os_capabilities=[]` (no `ALL`); CloudWatch logging; short-lived auth
  tokens scoped to `allowedPorts=[8080]`; a `maximumDurationInSeconds` cost cap on every launch.
- **No secrets in images.** Image `EnvironmentVariables` are snapshotted and shared — secrets come
  from SSM/Secrets Manager at runtime or the per-VM `runHookPayload`.
- **VPC egress** (opt-in) via `AWS::Lambda::NetworkConnector` backed by a 2-AZ VpcV2.

## 6. The sample worker (tiered, to isolate risk)

`sample/microvm_app/worker.py` serves `:8080` with three tiers so the library's tests never depend on
the agent working:

1. **`echo`** — deterministic no-model transform. **This is what E2E asserts on.**
2. **`bedrock`** — one Bedrock **Converse** call to Nova 2 Lite (default) or an `AnthropicBedrockMantle` call to Opus 4.8 (opt-in).
3. **`agent`** — opt-in Claude Code headless (`claude -p`). Highest first-try risk; gates nothing.

Spike status (2026-07-11): tiers "build → run → auth → ingress → echo" are **proven end-to-end** on
real AWS; the in-VM Bedrock call returned a 500 and is **still unproven** (diagnosis deferred). See
[SPEC.md](SPEC.md) §0.

## 7. Testing strategy

- **Unit (fast, no AWS)** — `aws_cdk.assertions.Template.from_stack()` asserts resource presence,
  critical props, least-privilege IAM, secure defaults, and that validation errors raise. A dedicated
  `test_security.py`. **Every CDK change ships with a unit test** (see [CLAUDE.md](CLAUDE.md)).
- **cdk-nag `AwsSolutionsChecks`** (AWS-recommended pack) applied as an app Aspect; runs at synth so
  `make synth`/unit tests fail on any `AwsSolutions-*` finding — suppress only with a written reason
  (`SPEC.md` §5.9).
- **Synth smoke** — `make synth` in CI.
- **E2E (gated, real AWS)** — a pytest fixture reads stack outputs → `run_microvm` (with a TTL cap) →
  polls `RUNNING` → mints a scoped auth token → hits the endpoint and asserts (echo tier) →
  **`terminate_microvm` in teardown**. Only runs when explicitly requested; always leaves the account
  clean.

## 8. Build, deploy & tooling

`uv` + `ruff` + `mypy --strict` + `hatchling`, all driven through the **Makefile**:

| Command | Does |
|---------|------|
| `make dev` | `uv sync` (venv + dev deps) |
| `make lint` / `make format` | ruff check/format + mypy / auto-fix |
| `make unit` | unit tests + coverage (no AWS) |
| `make synth` | `cdk synth` the sample app |
| `make deploy` / `make destroy` | `cdk deploy`/`destroy` **this repo's stack only** |
| `make e2e` | deploy-backed E2E (real AWS, gated) |
| `make docs` / `make publish-docs` | zensical serve / build (GitHub Pages) |

Deployment is **CDK-only**, scoped to this repo's stacks — see the guardrails in [CLAUDE.md](CLAUDE.md).

## 9. Best practices this repo follows

Per [ranthebuilder — CDK best practices](https://ranthebuilder.cloud/blog/aws-cdk-best-practices-from-the-trenches/):
construct-based composition over extra stacks; infra separated from app code; explicit
resource-scoped least-privilege IAM; deliberate `RemovalPolicy` and stable logical IDs for stateful
resources; security-first defaults; no hardcoded account/region/secrets; synthesis tests + cdk-nag;
config-in-code for stage differences; tagging; balanced abstraction (readability over clever
factories).

## 10. Roadmap

Phase 0 (bootstrap), the Phase-2.0 spike, **Phase 1** (the `MicrovmImage` construct + typed helpers +
unit/security/nag tests) and **Phase 2.1 code** (sample app + tiered worker + boto3 E2E fixture) are
done — the sample synthesizes green with cdk-nag; the E2E run against real AWS needs a deploy +
creds (`make deploy`, then `make e2e`). Next: Phase 3 (VPC egress), Phase 4 (optional boot custom resource),
Phase 5 (optional launcher), Phase 6 (publish to PyPI). Full detail in [SPEC.md](SPEC.md) §15.
