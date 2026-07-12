# lambda-microvm-cdk — Reusable AWS CDK Construct for Lambda MicroVMs

**Status:** Draft v3 (blockers validated against live API) · **Owner:** @isenberg.ran · **Date:** 2026-07-11
**Authored on:** Python 3.14 · **Supports:** Python **3.11+** · **Framework:** AWS CDK v2 (`aws-cdk-lib`, `constructs`) · **Distribution:** PyPI (pure-Python wheel)
**PyPI name:** `lambda-microvm-cdk` · **Module:** `lambda_microvm_cdk`

---

## 0. Validated assumptions (verified 2026-07-11 against the live API in `us-east-1`)

All four original blockers were checked against boto3 `1.43.46` and the CloudFormation type registry with real credentials. Results:

| # | Question | Result | Evidence |
|---|----------|--------|----------|
| 1 | Does boto3 expose the MicroVM API? | ✅ **Yes.** `boto3.client("lambda-microvms")` and `boto3.client("lambda-core")` both exist (API version `2025-09-09`). | `get_available_services()` lists both; ops enumerated below. |
| 2 | Do running MicroVMs get AWS credentials inside the VM (for Bedrock)? | ✅ **Yes.** `RunMicrovm` accepts `executionRoleArn` — "the IAM role assumed by the MicroVM during execution." | RunMicrovm API ref + `run-microvm --execution-role-arn`. |
| 3 | Can VPC egress connectors be created declaratively? | ✅ **Yes — better than expected.** `AWS::Lambda::NetworkConnector` is a **LIVE / PUBLIC** CFN resource (`required=['Configuration']`, plus `OperatorRole`). No runtime-only custom resource needed. | `cloudformation describe_type`. |
| 4 | Is `AWS::Lambda::MicrovmImage` GA / not account-gated? | ✅ **Yes.** `LIVE / PUBLIC / FULLY_MUTABLE`. Required props match §3. | `cloudformation describe_type`. |
| — | Is the *running* MicroVM a CFN resource? | ❌ **No.** `AWS::Lambda::Microvm` does not exist → running VMs are **runtime-API only** (driven by boto3 from app/test code, §4.2), not CloudFormation. | `describe_type` TypeNotFound. |
| — | Base-image + version lookup (§7)? | ✅ `ListManagedMicrovmImages` → one image today: `arn:aws:lambda:us-east-1:aws:microvm-image:al2023-1`. `ListManagedMicrovmImageVersions(imageIdentifier=...)` → only version **`"0"`**. | live calls. |
| — | Which CPU architectures are valid? | ⚠️ **`ARM_64` only.** The `CreateMicrovmImage` service model pins `cpuConfigurations[].architecture` to `enum=['ARM_64']` — **X86_64 is not currently accepted by the API.** arm64 is the only valid value today, not just the default. | boto3 service-model enum. |
| — | Bedrock models for the sample? | ✅ **Default: Amazon Nova 2 Lite** — `amazon.nova-2-lite-v1:0` is **`INFERENCE_PROFILE`-only**; profile **`us.amazon.nova-2-lite-v1:0`** `ACTIVE` in `us-east-1` (fans out to us-east-1/2 + us-west-2). **Opt-in: Claude Opus 4.8** — profiles `us.`/`global.anthropic.claude-opus-4-8` `ACTIVE` (needs model access). | `bedrock list-foundation-models` / `get-inference-profile`. |

**`lambda-microvms` operations:** `CreateMicrovmImage`, `UpdateMicrovmImage`, `DeleteMicrovmImage`, `GetMicrovmImage`, `GetMicrovmImageBuild`, `ListMicrovmImageBuilds`, `ListMicrovmImages`, `ListManagedMicrovmImages`, `ListManagedMicrovmImageVersions`, `ListMicrovmImageVersions`, `GetMicrovmImageVersion`, `UpdateMicrovmImageVersion`, `DeleteMicrovmImageVersion`, `RunMicrovm`, `GetMicrovm`, `ListMicrovms`, `SuspendMicrovm`, `ResumeMicrovm`, `TerminateMicrovm`, `CreateMicrovmAuthToken`, `CreateMicrovmShellAuthToken`, `Tag/UntagResource`, `ListTags`.
**`lambda-core` operations:** `CreateNetworkConnector`, `GetNetworkConnector`, `ListNetworkConnectors`, `UpdateNetworkConnector`, `DeleteNetworkConnector`.

Networking (§5.5), monitoring/logging (§5.6), and the AWS best-practices guidance (§5.8) have been read and folded into the construct's defaults and inputs.

### Phase-2.0 spike — run end-to-end 2026-07-11 (raw boto3, then torn down)

Hand-built a real image + ran a real VM in `us-east-1` to convert "should work" into observed fact:

| Step | Result |
|------|--------|
| Image build (base `al2023-1` + `FROM public.ecr.aws/docker/library/python:3.13-slim` + `pip install boto3`) | ✅ `CREATED` in **~165s**; user image version starts at **`"1.0"`** (distinct from base version `"0"`) |
| `RunMicrovm` → `RUNNING` | ✅ ~15s |
| Auth token → ingress → endpoint | ✅ token map key is exactly **`X-aws-proxy-auth`**; `/health` 200 **without** implementing the `/run` hook (hooks disabled ⇒ traffic flows immediately) |
| **`/echo` deterministic assertion** | ✅ **PASSED** — full path build→run→auth→ingress→app proven |
| **`/bedrock` (in-VM execution-role → Bedrock)** | ✅ **Diagnosed + fixed 2026-07-11.** The E2E diagnostic tier captured the real error: `403 bedrock-mantle:CreateInference` denied — the `AnthropicBedrockMantle` client authorizes on the Mantle **project**, not `bedrock:InvokeModel` on a model ARN. Execution-role grant corrected (§5.1). |

**Other confirmed facts:** `environmentVariables` key **`AWS_REGION` is reserved** — `CreateMicrovmImage` rejects it (the runtime injects region); set only non-reserved keys. `DeleteMicrovmImage` fails while a MicroVM is running (`Cannot delete microvm image with running microvms`) → **terminate before deleting the image** (matters for the CR delete ordering, §8, and any teardown). All spike resources were deleted; no zombies.

**Remaining unknowns (not blockers):** regional availability outside `us-east-1`; whether `aws_ec2_alpha` VpcV2 API is stable enough to pin; exact `AWS::Lambda::MicrovmImage` nested-property casing for `Hooks` (top-level props registry-confirmed). See §14.

**Net effect on confidence:** the **core library path is PROVEN** — the deploy-backed E2E (2026-07-11) built a real image, ran a real VM, and passed the deterministic `/echo` assertion end-to-end (build → run → auth → ingress → app). The **in-VM Bedrock 500 is now root-caused** (wrong IAM action — `bedrock:InvokeModel` where the Mantle client needs `bedrock-mantle:CreateInference`) and **fixed in code** (§5.1); a redeploy + E2E re-run confirms the sample's "Claude on Bedrock" tier. So: **library buildability ~9.5/10; sample Bedrock tier fix applied, pending redeploy verification.**

---

## 1. Goal

Ship a **generic, reusable, parameter-driven, security-first CDK construct** that provisions AWS [Lambda MicroVM](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) infrastructure. Authored on Python 3.14, supports **3.11+**, published to **PyPI** as `lambda-microvm-cdk` so any Python CDK app can `pip install lambda-microvm-cdk` and drop a MicroVM into its stack.

The repo also ships a **deployable sample CDK app** whose MicroVM runs a **model worker** on **Amazon Bedrock** (`us-east-1`): **Amazon Nova 2 Lite by default** (via the boto3 Converse API), with **Claude Opus 4.8 as an opt-in** (via the Anthropic SDK, `MODEL_PROVIDER=anthropic`). This sample is the target for **E2E tests**: launch the MicroVM, send a prompt, assert a result.

Two-stage delivery:
- **Stage 1 (build):** image construct + VM execution role + sample app + unit/E2E tests (E2E drives `run_microvm` via boto3 from stack outputs) + docs, deployable to AWS.
- **Stage 2 (publish):** harden, finalize docs, tag, publish the wheel to PyPI.

---

## 2. Background — how Lambda MicroVMs work

Firecracker-based serverless compute with VM-level isolation, full OS capabilities, snapshot-fast start, configurable ingress/egress networking, and suspend/resume for idle cost control. Use cases: AI code sandboxes, interactive dev environments, multi-tenant CI, security scanning.

### Two planes (validated)

| Plane | What | CFN resource? | In this library |
|-------|------|---------------|-----------------|
| **Image** | `Dockerfile`+app → zip → S3 → build & snapshot a fully-initialized image | ✅ `AWS::Lambda::MicrovmImage` | `MicrovmImage` (Phase 1) |
| **Network connector** | VPC egress (or reuse AWS-managed ingress/internet ARNs) | ✅ `AWS::Lambda::NetworkConnector` | `VpcEgress` helper (Phase 3) |
| **Running instance** | `RunMicrovm`/`Suspend`/`Resume`/`Terminate`/`CreateMicrovmAuthToken` | ❌ none — runtime API only | driven by app/test **boto3** using stack outputs; E2E fixture (§12) — no launcher/API-GW/WAF for now |

**Key implication:** images and connectors are declarative CloudFormation; *running* a MicroVM is a runtime API call, so it's driven via boto3 from app/test code (the E2E fixture, §12), not CloudFormation.

### Image build flow (Phase 1)
1. Bundle `Dockerfile`+app → zip → S3 (CDK asset).
2. Create a least-privilege IAM **build role** the Lambda MicroVM service assumes to pull the artifact from S3 and write CloudWatch build logs.
3. Emit `AWS::Lambda::MicrovmImage` referencing the S3 artifact + managed **base image** ARN + resolved `BaseImageVersion` (§7).
4. Build is async: `CREATING → CREATED` (or `CREATE_FAILED`). Optional build hooks `/ready`, `/validate`.

### Run flow (driven by app/test boto3, using stack outputs)
`RunMicrovm` params (validated): `imageIdentifier` (req), `imageVersion`, **`executionRoleArn`**, `idlePolicy`, `ingressNetworkConnectors`, `egressNetworkConnectors`, `logging`, **`maximumDurationInSeconds`** (1–28,800 — hard TTL), `runHookPayload` (≤16 KB), `clientToken` (idempotency). Access requires a JWE token from `CreateMicrovmAuthToken` (`allowedPorts` = `{port}` / `{range}` / `{allPorts}`, `expirationInMinutes`) in the `X-aws-proxy-auth` header; port via `X-aws-proxy-port` (default 8080).
**Runtime lifecycle hooks** the app exposes at `/aws/lambda-microvms/runtime/v1/<hook>`: `/run` (traffic starts only after it returns 200), `/resume`, `/suspend`, `/terminate`.

---

## 3. `AWS::Lambda::MicrovmImage` — resource contract

Wrapped via the generated L1 `aws_lambda.CfnMicrovmImage` (no higher-level L2 in `aws-cdk-lib` yet) — its typed props/structs/attrs are the source of truth and are passed through directly (`Hooks` uses the typed `HooksProperty`, so jsii serialises exact CFN casing). Only the un-modeled `overrides` escape hatch goes through `add_property_override` (verbatim, no jsii coercion). **Registry-confirmed required props:** `Name`, `Description`, `BaseImageArn`, `BaseImageVersion`, `BuildRoleArn`, `CodeArtifact`, `CpuConfigurations`, `Resources`, `AdditionalOsCapabilities`, `EgressNetworkConnectors`, `EnvironmentVariables`, `Hooks`, `Logging`. `Tags` optional.

| Property | Type | Notes |
|----------|------|-------|
| `Name` | String | `^[a-zA-Z0-9-_]+$`, 1–64. **Replacement** on change. |
| `Description` | String | Required (may be `""`). |
| `BaseImageArn` | String | `arn:aws:lambda:<region>:aws:microvm-image:al2023-1` (only managed image today). |
| `BaseImageVersion` | String | `"0"` today; resolved via boto3 lookup (§7). |
| `BuildRoleArn` | String | IAM role the service assumes to build. |
| `CodeArtifact` | `{ Uri: s3://… }` | The zip on S3. |
| `CpuConfigurations` | `[{ Architecture: ARM_64 }]` | **`ARM_64` only today** — service enum rejects `X86_64` (see §0). |
| `Resources` | `[{ MinimumMemoryInMiB: int }]` | max 1; baseline tier — only `512 \| 1024 \| 2048 \| 4096 \| 8192` MiB supported (docs "MicroVM sizing"; API/CFN schema is an open int, so the construct enforces the set). Default `2048`. |
| `AdditionalOsCapabilities` | `[String]` | allowed `ALL`. Default `[]` (least privilege). |
| `EgressNetworkConnectors` | `[String]` | ARNs, max 10. Default `[]`. |
| `EnvironmentVariables` | `[{ Key, Value }]` | max 50. **Registry-confirmed `Key`/`Value`** (not `Name`/`Value`; the boto3 API uses a map). Key ≤256 chars no whitespace, value ≤4096. **Snapshotted — never secrets (§5).** |
| `Hooks` | `{ Port, MicrovmHooks{Run,Resume,Suspend,Terminate = ENABLED\|DISABLED + <Hook>TimeoutInSeconds 1–60}, MicrovmImageHooks{Ready,Validate = ENABLED\|DISABLED + <Hook>TimeoutInSeconds 1–3600} }` | modeled by `LifecycleHooks`; may be `{}`. **Registry-confirmed 2026-07-11** (PascalCase nested casing dumped from `describe_type`). |
| `Logging` | `{ CloudWatch: { LogGroup?, LogStream? } }` \| `{ Disabled: true }` | exactly one. **`enable_logging=True` pins `CloudWatch.LogGroup` to `/aws/lambda/microvms/<name>`** — an *empty* `CloudWatch: {}` reads as **disabled** by the service (console + deployed-image verified 2026-07-11; no build/runtime streams), despite the API doc calling it "enable". `Disabled` is a boolean. |
| `Tags` | `[{Key,Value}]` | optional. |

**Attributes** (`Fn::GetAtt`): `ImageArn`, `State`, `LatestActiveImageVersion`, `LatestFailedImageVersion`, `CreatedAt`, `UpdatedAt`. `Ref` → image ARN. `FULLY_MUTABLE` (only `Name` change forces replacement).

---

## 4. Construct API (public surface)

Module `lambda_microvm_cdk`. **The public API is the single `LambdaMicroVM` construct**, exported from the package root; supporting internals are private under `_impl/` (§6). Inputs reuse standard CDK types (`aws_lambda.Architecture`, `aws_logs.RetentionDays`, `aws_s3_assets.Asset`) instead of duplicating them. Secure defaults, every AWS knob overridable, plus an escape hatch.

### 4.1 `LambdaMicroVM` (Phase 1, core)

```python
from aws_cdk import Stack
from lambda_microvm_cdk import LambdaMicroVM

class MyStack(Stack):
    def __init__(self, scope, id, **kw):
        super().__init__(scope, id, **kw)

        vm = LambdaMicroVM(self, "Agent",
            source="sample/microvm_app",                # dir w/ Dockerfile -> zip -> S3 (also: .zip path or s3_assets.Asset)
            name=None,                                  # optional -> stable derived name (§4.4)
            description="Claude headless agent VM",
            base_image="al2023-1",                      # short alias OR full ARN
            base_image_version=None,                    # None -> boto3 lookup (§7); or pin "0"
            # architecture=aws_lambda.Architecture.ARM_64,  # default; only value accepted today (§0)
            memory_mib=2048,                            # -> MinimumMemoryInMiB; tier 512|1024|2048|4096|8192; default 2048
            os_capabilities=[],                         # DEFAULT [] (ALL is a privilege escalation)
            environment={"LOG_LEVEL": "info"},          # NEVER secrets — snapshotted (§5)
            egress_connectors=[],                       # default []
            enable_logging=True,                        # default CloudWatch; False -> {'Disabled': true}
            hooks=None,                                 # typed CfnMicrovmImage.HooksProperty; default None -> {} = disabled
            build_role=None,                            # optional BYO least-priv role
            execution_role=None,                        # optional BYO VM execution role
            tags={"project": "lambda-microvm-cdk"},
            overrides={},                               # escape hatch, verbatim CFN props (§4.3)
        )

        vm.image_arn         # Fn::GetAtt ImageArn (token)
        vm.state
        vm.build_role        # iam.IRole actually used
        vm.execution_role    # least-priv VM execution role (logs-only; add workload perms on top)
        vm.grant_run(principal)   # attach least-priv lambda:RunMicrovm* to a runtime-caller principal
```

Responsibilities: zip+upload asset; create least-privilege build + VM execution roles (scoped to the exact asset key / log group) unless supplied; resolve `base_image` alias → region ARN; resolve `base_image_version` via boto3 lookup (§7); fill secure defaults; validate inputs (name regex, arch, env vars, memory, capabilities) with clear errors.

### 4.2 Runtime access — driven by app/test code, not a launcher (for now)

**No launcher Lambda, no API Gateway, no WAF in scope right now.** Running a MicroVM is a runtime API call, so it's driven directly with **boto3** (`RunMicrovm` / `CreateMicrovmAuthToken` / `TerminateMicrovm`) from the consumer's own code — and, in this repo, from the **E2E pytest fixture** (§12) reading the CloudFormation stack outputs (§4.5).

The construct's job on the runtime side is to make that call **safe and one-line to assemble**: it provisions and outputs a least-privilege **VM execution role** and resolves the connector ARNs + idle policy, so the fixture/consumer just wires stack outputs into `run_microvm`:

```python
# what the CDK stack provides (via CfnOutputs, §4.5):
#   MicrovmImageArn, MicrovmExecutionRoleArn, IngressConnectorArn,
#   EgressConnectorArn, MicrovmLogGroupName
import boto3
mv = boto3.client("lambda-microvms", region_name="us-east-1")
run = mv.run_microvm(
    imageIdentifier=outputs["MicrovmImageArn"],
    executionRoleArn=outputs["MicrovmExecutionRoleArn"],
    ingressNetworkConnectors=[outputs["IngressConnectorArn"]],
    egressNetworkConnectors=[outputs["EgressConnectorArn"]],
    idlePolicy={"autoResumeEnabled": True, "maxIdleDurationSeconds": 900, "suspendedDurationSeconds": 300},
    maximumDurationInSeconds=3600,     # hard TTL / cost backstop
)
```

Typed helpers `IngressConnector`/`EgressConnector`/`IdlePolicy` (§4.4) build those ARNs/dicts for consumers who assemble the call in CDK-adjacent code. A **thin launcher Lambda** (and, separately, an API-Gateway/WAF front door) can be added later as an opt-in — deferred, **not** in the near-term scope.

> **Custom resource (boot-a-VM-at-deploy): also NOT included.** See §8. Nothing boots on deploy; the E2E fixture launches, tests, and terminates.

### 4.3 Escape hatch (generic, un-modeled props)

Both constructs accept `overrides: dict[str, Any]` merged **verbatim** into the underlying L1 `Properties` — keys are exact CloudFormation names (e.g. `{"Hooks": {...}}`), **no auto-casing** (avoids acronym/collision bugs). Applied as top-level `add_property_override`s on the L1 `CfnMicrovmImage` (also reachable directly via `construct.node.default_child`). This guarantees users are never blocked on an un-modeled field.

### 4.4 Typed helpers + naming

**No duplicate types — the construct reuses CDK's own:** `architecture` takes `aws_lambda.Architecture` (**`ARM_64` is the default and currently the only value the service accepts**, §0 — anything else is rejected with a clear error so users never synth a template the API would reject); `log_retention` takes `aws_logs.RetentionDays`; `source` takes a path or an `aws_s3_assets.Asset`. Memory is a plain `memory_mib: int` validated against the five documented baseline tiers (§3); logging a plain `enable_logging: bool`; `hooks` a verbatim CFN dict (registry-confirmed casing, §3). The AWS-managed connector ARNs are exposed as partition/region-aware properties (`ingress_connector_arn` = `ALL_INGRESS`, `egress_connector_arn` = `INTERNET_EGRESS`); idle policy / max-duration are plain dict/int inputs to `run_microvm` assembled by the caller (§4.2, §12).

**Naming/versioning strategy:** default `Name` is **stable** (derived from construct path, sanitized to the regex), *not* asset-hash — so a code change updates `CodeArtifact` in place (`FULLY_MUTABLE` → new image **version**, `LatestActiveImageVersion` advances) rather than replacing the image and orphaning it. Users may pass an explicit `name`. Changing `name` is documented as forcing replacement.

### 4.5 CloudFormation outputs

The **construct does not emit `CfnOutput`s** — a reusable construct exposes typed **properties** (`image_arn`, `state`, `execution_role`, `ingress_connector_arn` / `egress_connector_arn`, `log_group_name`) and lets the **consuming stack** decide what to surface, so it never pollutes a consumer's template or collides with the consumer's own outputs. The **sample stack** (`sample_stack.py`) emits the clean output keys the E2E fixture reads (§12). **A running MicroVM is not a CFN resource (§0), so its `microvmId`/`endpoint` are runtime values — deploy-time outputs only via the boot custom resource (§8), deferred.** What the sample stack surfaces:

| Output (sample stack) | Backing property | Source |
|--------|------|--------|
| `MicrovmImageArn` | `image_arn` | `Fn::GetAtt ImageArn` |
| `MicrovmImageName` | `image_name` | resolved `Name` |
| `MicrovmExecutionRoleArn` | `execution_role.role_arn` | the least-priv VM execution role the construct provisions (§5.1) |
| `IngressConnectorArn` / `EgressConnectorArn` | `ingress_/egress_connector_arn` | resolved AWS-managed / VPC connector ARNs (§5.5) |
| `MicrovmLogGroupName` | `log_group_name` | derived name `/aws/lambda/microvms/<image-name>` (service-owned; §5.6) |
| `MicrovmId`, `MicrovmEndpoint` | — | **only via boot CR (§8, deferred)** — runtime values |

These deploy-time outputs are exactly the inputs the **E2E fixture** feeds into `run_microvm` (§4.2, §12). `microvmId`/`endpoint` are runtime values the fixture obtains from the `RunMicrovm` response; per-running-MicroVM logs are a **log stream named by `microvmId`** inside `MicrovmLogGroupName` (§5.6), so the deploy-time log-group output already points at the right place.

---

## 5. Security (first-class)

### 5.1 Least privilege on every generated role
- **Build role:** trust `lambda.amazonaws.com` (`sts:AssumeRole`+`sts:TagSession`); permissions limited to `s3:GetObject` on the **exact asset key** (not `bucket/*`) + scoped `logs:*` on the image's log group only. Private-ECR perms added **only if** the source opts in.
- **Runtime-caller grant (`image.grant_run(principal)`):** attaches `lambda:RunMicrovm`, `SuspendMicrovm`, `ResumeMicrovm`, `TerminateMicrovm`, `CreateMicrovmAuthToken`, `GetMicrovm`, `ListMicrovms` scoped to the **specific image ARN** where the API supports resource-level, plus `iam:PassRole` limited to the VM execution role — for whoever drives the runtime (a consumer app, or a future launcher Lambda). No `*`. (The repo's E2E uses developer SSO creds, so it needs these on the principal, not a construct-created role.)
- **VM execution role (sample):** grants BOTH worker providers so `MODEL_PROVIDER` can flip without an IAM change. **Nova (default)**: `bedrock:InvokeModel[WithResponseStream]` on the inference-profile ARN `arn:aws:bedrock:<region>:<acct>:inference-profile/us.amazon.nova-2-lite-v1:0` **and** the region-wildcard foundation-model ARN it fans out to (`arn:aws:bedrock:*::foundation-model/amazon.nova-2-lite-v1:0`) — Nova 2 Lite is `INFERENCE_PROFILE`-only. **Opus (opt-in)**: `bedrock-mantle:CreateInference` on `arn:aws:bedrock-mantle:<region>:<acct>:project/default` — the Mantle Messages-API endpoint, **not** classic InvokeModel (E2E-confirmed 2026-07-11: the wrong action was the spike's uncaptured 500, §0). Plus `logs:CreateLogGroup/CreateLogStream/PutLogEvents` on the image's log group (§5.6). No long-lived credentials in the image.

### 5.2 Secure defaults & parameter hardening
- `os_capabilities` defaults `[]`; `ALL` must be explicit (documented privilege escalation). *(Note: the sample worker installs packages at build time, not run time, so it does not need `ALL`; if a consumer mounts filesystems at runtime they opt in.)*
- `logging` defaults CloudWatch (auditable).
- Auth tokens: short expiry + tight `allowedPorts` (sample: only 8080).
- `maximumDurationInSeconds` set on every launch as a hard TTL backstop.
- Validation rejects malformed/out-of-range inputs early.

### 5.3 Secrets — never in the image
`EnvironmentVariables` are **baked into the snapshot** and shared across every VM from that image → **never put secrets there.** Pattern (matches the aws-samples repo): pass secret *references* per-VM via `runHookPayload` (≤16 KB) or fetch from SSM Parameter Store / Secrets Manager at runtime inside the `/run` (or `/resume`) hook using the VM execution role. The construct documents this and the sample demonstrates the Parameter Store path.

### 5.4 VPC egress (opt-in, `vpc_v2`, 2 AZs) — now declarative
Confirmed `AWS::Lambda::NetworkConnector` is a CFN resource, so VPC egress is **pure CDK** (no runtime custom resource). Mirrors [`aws-lambda-handler-cookbook/.../lambda_managed_instance_construct.py`](https://github.com/ran-isenberg/aws-lambda-handler-cookbook/blob/main/cdk/service/lambda_managed_instance_construct.py):
- **`aws_ec2_alpha` VpcV2**, `10.0.0.0/16`, **exactly 2 AZs**, `PRIVATE_WITH_EGRESS` subnets (NAT), `/24` each.
- VPC **flow logs** (reject traffic, short retention); interface/gateway endpoints where useful; endpoint SG restricts ingress to the workload SG (no `0.0.0.0/0`).
- `AWS::Lambda::NetworkConnector` with `Configuration` (VPC egress: subnets, SGs, protocol) + least-priv `OperatorRole` (`ec2:CreateNetworkInterface` on scoped ARNs + `ec2:CreateTags` with the `network-connectors.lambda.amazonaws.com` operator condition).
- **Off by default** — default egress is internet. Enabled via `EgressConnector.vpc(...)`.

### 5.5 Networking (from the [networking guide](https://docs.aws.amazon.com/lambda/latest/dg/microvms-networking.html))

Connectors are chosen at **run** time (in the `run_microvm` call), not baked into the image.

- **Ingress** (AWS-managed ARNs): `IngressConnector.all_ingress()` → `…:network-connector:aws-network-connector:ALL_INGRESS`; `IngressConnector.no_ingress()` → `NO_INGRESS`. Each VM gets a unique HTTPS endpoint `<microvmId>.lambda-microvm.<region>.on.aws`; TLS is always terminated by Lambda (the app may serve plain HTTP internally).
- **Egress**: `EgressConnector.internet()` → `INTERNET_EGRESS` (default); `EgressConnector.vpc(connector)` → the `AWS::Lambda::NetworkConnector` from §5.4.
- **Protocols**: HTTP/1.1, HTTP/2 (ALPN-negotiated), WebSockets, gRPC, SSE.
- **Auth & port routing**: every request needs a JWE token in `X-aws-proxy-auth` (from `CreateMicrovmAuthToken`); target port via `X-aws-proxy-port` (default **8080**), and the port must be inside the token's `allowedPorts` (`{port}` / `{range}` / `{allPorts}`) or the endpoint returns 403. `X-aws-proxy-*` headers are stripped before reaching the app.
- **Bandwidth** scales with size: 0.5 GB→1 MB/s, 1 GB→2, 2 GB→4, 4 GB→8, 8 GB→16 MB/s (applies to both directions).
- **Endpoint error codes** (from the proxy, not your app): 400 malformed/bad port, 403 bad/expired token or disallowed port, 429 rate limit, 502 app not responding / resume failed.
- **Construct defaults**: ingress `ALL_INGRESS`, egress `INTERNET`, port 8080; the E2E fixture / consumer app mints tokens with a short expiry (§5.8) and `allowedPorts=[8080]`.

### 5.6 Monitoring & logging (from the [monitoring guide](https://docs.aws.amazon.com/lambda/latest/dg/microvms-monitoring.html))

- **Log model**: build logs (via build role) and runtime stdout/stderr (via execution role) both stream to the default group **`/aws/lambda/microvms/<image-name>`**, with the **log stream defaulting to the `microvmId`**. **Runtime logs require the execution role to have `logs:CreateLogGroup/CreateLogStream/PutLogEvents`** — no exec role → no runtime logs.
- **Construct behavior**: build + runtime logs go to `/aws/lambda/microvms/<image-name>`. Enabling logging requires **pinning `Logging.CloudWatch.LogGroup`** to that name — an empty `CloudWatch: {}` is silently treated as *disabled* (verified 2026-07-11 against a deployed image: console "logging disabled", zero streams). So the construct (a) sets `CloudWatch.LogGroup = /aws/lambda/microvms/<name>` when `enable_logging=True`, (b) **grants** the build + VM exec roles `logs:CreateLogGroup/CreateLogStream/PutLogEvents` scoped to that group ARN, (c) sets **retention** via an `aws_logs.LogRetention` helper (which also creates the group if absent — no ownership clash, since the service writes streams into an existing group; `log_retention` default two weeks), and (d) exposes the **derived name** via the `log_group_name` property, which the consuming stack can output (§4.5). Per-`id` granularity is the **log stream** (= `microvmId`) inside that group.
- **Build logs vs runtime logs are configured separately (verified 2026-07-11).** The image's `Logging` config governs only **build-time** logs (the snapshot-build VMs). **Runtime** logs from a *running* VM are configured **per-launch** on the `RunMicrovm` call — `logging.cloudWatch.logGroup`. Without it, a running VM writes **no CloudWatch stream at all** (image logging alone is not enough). So a runtime caller must pass the group (the construct's `log_group_name` property) to `run_microvm(logging={'cloudWatch': {'logGroup': …}})`; the E2E fixture does this (§12).
- **CloudTrail**: management events (`CreateMicrovmImage`, …) logged by default; **data events** (`RunMicrovm`, `TerminateMicrovm`, `CreateMicrovmAuthToken`, …) are **opt-in** (resource type `AWS::Lambda::MicrovmImage`). The construct documents the advanced event selector; enabling it is account-trail config, left to the consumer (optional helper later).
- **Failure triage**: `GetMicrovm.stateReason` explains unexpected termination — the caller / E2E fixture surfaces it.

### 5.7 Exposed inputs vs built-in secure defaults

Every AWS knob is reachable, but the construct ships opinionated, secure defaults so a minimal call is safe. What's a first-class typed input vs. what's defaulted:

| Concern | Exposed input | Built-in default |
|---------|:-------------:|------------------|
| Architecture | ✅ `architecture` | `ARM_64` (only valid today) |
| Baseline size | ✅ `size` | `MEM_1GB` |
| Idle policy | ✅ `idle_policy` | `auto_resume=True, max_idle=900s, suspended=300s` |
| Max TTL | ✅ `max_duration_seconds` | `3600` (hard cost backstop, always set) |
| OS capabilities | ✅ `os_capabilities` | `[]` (no `ALL`) |
| Logging | ✅ `logging`, `log_retention` | CloudWatch, retention 1 month |
| Ingress / egress | ✅ `ingress` / `egress` | `ALL_INGRESS` / `INTERNET` |
| Auth token expiry / ports | ✅ (fixture/consumer) | 30 min / `allowedPorts=[8080]` |
| Lifecycle hooks | ✅ `hooks` | disabled (`{}`) |
| Build / VM exec roles | ✅ BYO | least-privilege roles created |
| Env vars | ✅ `environment` | `{}` — **secrets rejected** (§5.3) |
| Tags | ✅ `tags` | `{}` (cost-allocation friendly) |
| Un-modeled props | ✅ `overrides` | `{}` |

### 5.8 AWS best-practices ([guide](https://docs.aws.amazon.com/lambda/latest/dg/microvms-best-practices.html)) → how we honor them

- **Snapshot re-use**: sample worker generates UUIDs/secrets in the `/run` hook with a CSPRNG, never at build (§11). **Design for resume**: `/resume` hook validates connections.
- **Right-size / minimize snapshot**: `size` default `MEM_1GB`; sample `Dockerfile` strips build-time deps before snapshot.
- **Security**: short-lived tokens (30 min default) scoped to `allowedPorts=[8080]`; VPC egress for sensitive traffic (§5.4); **separate** build vs execution roles, least-privilege (§5.1).
- **Cost**: idle policy + `maximumDurationInSeconds` always set; `suspendedDurationSeconds` auto-terminates; tags for cost allocation; docs recommend deleting stale image versions.
- **Monitoring**: exec role has logs perms by default; the caller surfaces `stateReason`.

### 5.9 cdk-nag — AWS-recommended checks at synth

Every synth is validated against AWS security best practices with the cdk-nag **`AwsSolutionsChecks`**
pack (the AWS-recommended rule set), applied as a CDK Aspect on the app:

```python
from aws_cdk import App, Aspects
from cdk_nag import AwsSolutionsChecks

app = App()
# ... add stacks ...
Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
```

- **Runs at synth** → `make synth` and the unit tests **fail on any `AwsSolutions-*` finding**, so
  misconfigurations are caught *before* `cdk deploy` — that's how we know a deployment is compliant.
- A unit test asserts **no unsuppressed** `AwsSolutions-*` errors (via
  `Annotations.from_stack(stack).find_error(...)`).
- Any exception uses `NagSuppressions.add_resource_suppressions(...)` with an explicit **id + written
  justification**; suppressions are reviewed, never blanket.
- `cdk-nag` is a **dev/app** dependency (used by the sample app + tests), **not** a runtime dependency
  of the published construct — consumers apply their own nag packs. Stricter packs (HIPAA/NIST/PCI)
  can be layered by consumers; the repo standard is `AwsSolutionsChecks`.

---

## 6. Repository layout

Public API at the package root; **all implementation/helpers under `_impl/` (private)**.

```
microvm/                                  # repo root
├── SPEC.md · README.md · LICENSE (MIT-0)
├── Makefile                              # dev + pipeline (§9)
├── pyproject.toml                        # uv + hatchling + ruff/mypy; deps incl. boto3
├── uv.lock · .python-version (3.14) · .gitignore
├── zensical.toml · .markdownlint.yaml
├── src/lambda_microvm_cdk/
│   ├── __init__.py                       # EXPORTS ONLY LambdaMicroVM
│   ├── microvm.py                        # LambdaMicroVM — the public construct (validation, overrides merge, typed properties)
│   ├── py.typed
│   └── _impl/                            # PRIVATE
│       ├── security.py                   # least-priv build + VM execution role builders, grant_run
│       ├── base_image.py                 # alias->ARN + boto3 version lookup (§7)
│       ├── networking.py                 # PHASE 3 — NetworkConnector + VpcV2 (2 AZ) egress
│       └── launcher.py                   # DEFERRED (Phase 5) — thin run_microvm Lambda; no API GW/WAF
├── sample/
│   ├── app.py · cdk.json · requirements.txt · sample_stack.py
│   ├── scripts/build_image.py            # zips microvm_app -> artifact (make build)
│   └── microvm_app/
│       ├── Dockerfile                    # AL2023 app layers; Claude Code CLI + worker
│       └── worker/worker.py              # :8080; /run hook; agent (Bedrock Opus 4.8) + echo mode
├── docs/                                 # zensical / GitHub Pages
│   ├── index.md · getting_started.md · api.md · security.md · pipeline.md · changelog.md
│   └── media/
├── tests/
│   ├── unit/                             # cdk.assertions Template matchers (boto3 lookup mocked)
│   │   ├── test_image.py · test_security.py · test_synth_stack.py
│   └── e2e/                              # boto3 run_microvm from stack outputs + prompt + assert + terminate
│       ├── conftest.py                   # running_microvm fixture (§12)
│       └── test_agent_prompt.py
└── .github/
    ├── FUNDING.yml · dependabot.yml · release.yml (notes) · semantic.yml
    └── workflows/
        ├── ci.yml                        # make lint + complex + unit + synth (cdk-nag); no AWS
        ├── e2e.yml                       # make deploy -> make e2e -> make destroy (gated, OIDC)
        ├── docs.yml                      # make publish-docs -> GitHub Pages
        ├── release.yml                   # tag v* -> wheel -> PyPI Trusted Publishing (OIDC) + GH release
        ├── pr-labeler.yml                # label PRs from commit prefixes
        └── comment_issues.yml            # auto-acknowledge new issues
```

---

## 7. Base image version lookup (boto3, live)

`base_image_version` resolution, in `_impl/base_image.py`:
1. If `base_image_version` is passed → use verbatim (pin/override).
2. Else resolve via boto3 `lambda-microvms.list_managed_microvm_image_versions(imageIdentifier=<resolved base ARN>)` and pick the latest active version (**today the only value is `"0"`**).
3. On failure (no creds / offline / API error) → **fall back to `"0"`** + a CDK warning annotation; synth never hard-fails.

**No `cdk.context.json` caching.** Every synth without a pin does a live lookup (or the `"0"` fallback) — the construct never reads or writes `cdk.context.json`. For deterministic, offline CI, **pin `base_image_version`**. `boto3` is a real dependency. Unit tests mock the lookup. Region from `Stack.of(self).region`.

---

## 8. Custom resource — deferred (design captured)

A deploy-time "boot one MicroVM" CR is deferred. The update-semantics problem to solve first:
- **Update:** on prop change (image version, size, idle policy) decide terminate-and-relaunch vs in-place, and manage `PhysicalResourceId` (changing it triggers `Delete` of the old). Use `clientToken` (validated: `RunMicrovm` supports it) for idempotent launches.
- **Image change:** key off the resolved `ImageArn`/version so a new version forces a new VM.
- **Delete:** reliably `TerminateMicrovm` (handle not-found / already-terminated) to avoid orphaned billable VMs.
- **Async:** `RunMicrovm` returns `PENDING`; poll to `RUNNING` (Provider framework `onEvent`/`isComplete`), handle timeouts.

**Decision:** no CR yet, nothing boots on deploy. E2E launches via the boto3 fixture (§12). Revisit as Phase 4.

---

## 9. Makefile (dev + pipeline)

uv-based, mirrors [aws-lambda-handler-cookbook/Makefile](https://github.com/ran-isenberg/aws-lambda-handler-cookbook/blob/main/Makefile). Pipelines call these same targets:

| Target | Purpose |
|--------|---------|
| `dev` | `uv sync` (venv + dev deps) |
| `lint` | `ruff format --check` + `ruff check` + `mypy` |
| `format` | `ruff check --fix` + `ruff format` |
| `unit` | unit tests + coverage (no AWS; boto3 mocked) |
| `build` | `python sample/scripts/build_image.py` (zip artifact) |
| `synth` | `cdk synth` sample app |
| `deploy` / `destroy` | `cdk deploy --require-approval never` / `cdk destroy --force` (pipeline) |
| `e2e` | launch VM, send prompt, assert, **terminate in teardown** |
| `docs` / `publish-docs` | `zensical serve` / `zensical build` |
| `pr` | `format + lint + unit + synth` gate |

---

## 10. Documentation (GitHub Pages via zensical)

`docs/` served/built by **zensical** (`zensical.toml`), published via `docs.yml`. Mirrors [cookbook zensical.toml](https://github.com/ran-isenberg/aws-lambda-handler-cookbook/blob/main/zensical.toml): metadata, nav (Home, Getting Started, API, Security, Pipeline, Changelog), Material theme, admonitions/tabs/mermaid/highlight. `make docs` local; `make publish-docs` in CI.

---

## 11. Sample app — model worker on Bedrock (Nova 2 Lite default / Opus 4.8 opt-in, us-east-1)

**Inside the MicroVM** (`sample/microvm_app/`):
- `Dockerfile`: AL2023-compatible app layers; install Claude Code CLI (headless) + Python worker at **build** time (no `ALL` OS capability needed). `EXPOSE 8080`, `CMD worker.py`.
- `worker.py`: HTTP server on `:8080` implementing the **`/run` lifecycle hook** (returns 200 to admit traffic; reads secret refs from `runHookPayload`/Parameter Store). It exposes **three tiers**, chosen by request field / env, so the risky pieces are isolated and never gate the library:
  1. **`echo` (deterministic, no model)** — fixed transform of the input. **This is what E2E asserts on.** Zero model dependency → the library's correctness never rides on Bedrock or the agent working.
  2. **`bedrock` (one model call — provider chosen by `MODEL_PROVIDER`)** — **default `bedrock`: Amazon Nova 2 Lite via the model-agnostic boto3 Bedrock Converse API** (Nova 2 Lite is `INFERENCE_PROFILE`-only, so the profile id is used). **Opt-in `anthropic`: Claude Opus 4.8 via the `AnthropicBedrockMantle` SDK** (needs Bedrock model access). Credentials come from the VM execution role. Minimal moving parts (one HTTPS call) → high first-try success:

     ```python
     # default — Amazon Nova 2 Lite (boto3 Converse; works for any Bedrock model)
     import boto3
     r = boto3.client("bedrock-runtime", region_name=AWS_REGION).converse(
         modelId="us.amazon.nova-2-lite-v1:0",
         messages=[{"role": "user", "content": [{"text": prompt}]}],
         inferenceConfig={"maxTokens": 1024},
     )
     text = r["output"]["message"]["content"][0]["text"]

     # opt-in — Claude Opus 4.8 (Anthropic SDK; MODEL_PROVIDER=anthropic, MODEL_ID=us.anthropic.claude-opus-4-8)
     from anthropic import AnthropicBedrockMantle
     msg = AnthropicBedrockMantle(aws_region=AWS_REGION).messages.create(
         model=MODEL_ID, max_tokens=1024, messages=[{"role": "user", "content": prompt}],
     )
     ```
  3. **`agent` (Claude Code headless — opt-in enhancement)** — `claude -p "<prompt>" --output-format json` in the sandbox. This is the piece with real first-try risk (Node runtime, permission prompts, autoupdater), so it is **layered on top of, not required by**, the deployable sample. Headless-hardening env (all non-secret, set as image `EnvironmentVariables`):

     ```
     CLAUDE_CODE_USE_BEDROCK=1
     # AWS_REGION is a RESERVED image env key (CreateMicrovmImage rejects it, §0) — the runtime
     # injects it (= the region run_microvm was called in). Do NOT set it as an image env var.
     ANTHROPIC_MODEL=us.anthropic.claude-opus-4-8               # main model — inference profile (validated ACTIVE)
     ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-opus-4-8    # Opus 4.8 for the background/small slot too (no Haiku)
     CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096
     DISABLE_AUTOUPDATER=1
     DISABLE_TELEMETRY=1
     DISABLE_ERROR_REPORTING=1
     IS_SANDBOX=1                       # allow --dangerously-skip-permissions inside the isolated VM
     HOME=/workspace                    # writable Claude Code config/workspace dir
     # ANTHROPIC_API_KEY must be UNSET so requests route to Bedrock, not the Anthropic API
     ```

- **Dockerfile (concrete):** AL2023-compatible base with Python 3.14 (tiers 1–2) and, for tier 3 only, Node 22 + `npm i -g @anthropic-ai/claude-code`; strip build caches before snapshot; `EXPOSE 8080`; `CMD` starts `worker.py`.
- **Bedrock model access** is confirmed enabled (profiles `ACTIVE`, §0) — the usual first-deploy footgun is already cleared.
- **De-risking summary:** the *library* E2E depends only on tier 1; tier 2 proves "a model on Bedrock" with one API call (Nova by default; Opus opt-in); tier 3 (the CLI agent) is the only unproven piece and it is opt-in. CSPRNG for generated ids (snapshot uniqueness).

**Stack** (`sample_stack.py`): `MicrovmImage` from `microvm_app/` (`MEM_2GB`, `ARM_64`, Bedrock env) + the least-priv **VM execution role** (Bedrock + logs) + `CfnOutput`s (§4.5) the E2E fixture consumes. No launcher / API Gateway / WAF.

---

## 12. Testing strategy

1. **Unit (fast, no AWS):** `aws_cdk.assertions.Template.from_stack()` — assert `AWS::Lambda::MicrovmImage` present with all required props, `BaseImageVersion` resolved (boto3 **mocked**), least-priv build-role scoped to the asset key (not `*`), `CodeArtifact.Uri` wired, secure defaults (`os_capabilities=[]`, CloudWatch), and that validation errors raise. `test_synth_stack.py` synths a minimal internal stack (Phase 1 exit gate — independent of the sample). Dedicated `test_security.py`.
2. **Synth smoke + cdk-nag:** `make synth` in CI (cached context / `"0"` fallback); the
   `AwsSolutionsChecks` aspect (§5.9) runs at synth and **fails on any `AwsSolutions-*` finding**, and
   a unit test asserts none are unsuppressed.
3. **E2E (gated, real AWS) — pytest fixture drives the runtime via boto3:** `make deploy` → the fixture reads the **CloudFormation stack outputs** (`MicrovmImageArn`, `MicrovmExecutionRoleArn`, `IngressConnectorArn`, `EgressConnectorArn`) → polls image `CREATED` → `run_microvm(... maximumDurationInSeconds=<low backstop>)` → polls `RUNNING` → `create_microvm_auth_token(allowedPorts=[{port:8080}], expirationInMinutes=…)` → `requests.get(endpoint, headers={"X-aws-proxy-auth": token})` with a **prompt, asserts the result** (deterministic echo tier, §11) → **`terminate_microvm` in the fixture teardown / `try-finally`** (running VMs are runtime resources, *not* in the CFN stack, so `cdk destroy` alone won't terminate them) → `make destroy`. No launcher Lambda / API Gateway / WAF involved — just the deployed image + boto3. Gated behind an env flag + AWS creds. E2E is the only real-AWS tier (renamed from "integration").

```python
# tests/e2e/conftest.py — sketch
# `stack_outputs` is a fixture that reads the deployed stack via
# boto3 cloudformation.describe_stacks(...)["Stacks"][0]["Outputs"].
@pytest.fixture
def running_microvm(stack_outputs):
    mv = boto3.client("lambda-microvms", region_name="us-east-1")
    run = mv.run_microvm(imageIdentifier=stack_outputs["MicrovmImageArn"],
                         executionRoleArn=stack_outputs["MicrovmExecutionRoleArn"],
                         ingressNetworkConnectors=[stack_outputs["IngressConnectorArn"]],
                         egressNetworkConnectors=[stack_outputs["EgressConnectorArn"]],
                         idlePolicy={"autoResumeEnabled": True, "maxIdleDurationSeconds": 900, "suspendedDurationSeconds": 300},
                         maximumDurationInSeconds=900)
    mid = run["microvmId"]
    try:
        _wait_running(mv, mid)
        yield run  # endpoint + id
    finally:
        mv.terminate_microvm(microvmIdentifier=mid)   # guaranteed cleanup
```

---

## 13. Packaging & PyPI (Stage 2)

- **Name:** `lambda-microvm-cdk` (module `lambda_microvm_cdk`). **Pure Python.** `requires-python = ">=3.11"` (authored on 3.14). Deps: `aws-cdk-lib`, `constructs`, `boto3`.
- **Tooling:** uv (`uv.lock`), ruff (line-length 150, single quotes, `E,W,F,I,C,B`), mypy strict, hatchling — matching [aws-lambda-env-modeler](https://github.com/ran-isenberg/aws-lambda-env-modeler). `cdk-nag` is a **dev** dependency (not a runtime dep of the published wheel; §5.9). **License MIT-0.**
- **Publish:** `release.yml` on tag `v*` → sdist+wheel → **PyPI Trusted Publishing (OIDC)**; TestPyPI dry-run first. SemVer, `0.x` during Stage 1.

---

## 14. Open questions / assumptions (remaining — none are blockers)

- **Regional availability:** MicroVMs verified in `us-east-1`; confirm before targeting other regions.
- ~~**`Hooks` nested casing**~~ ✅ **resolved 2026-07-11:** full CFN schema dumped via `describe_type` — `Hooks{Port, MicrovmHooks{Run/Resume/Suspend/Terminate + <Hook>TimeoutInSeconds 1–60}, MicrovmImageHooks{Ready/Validate + <Hook>TimeoutInSeconds 1–3600}}`, states `ENABLED|DISABLED`. Also confirmed: env vars are `{Key,Value}`, `Logging.Disabled` is boolean, `Name` is the only create-only prop.
- **VpcV2 module:** `aws_ec2_alpha` is alpha — pin a version, isolate behind `_impl/networking.py`.
- **Resource-level IAM granularity:** confirm which `lambda:*Microvm*` actions support resource-level ARNs vs require `*` (fallback: condition keys / tag scoping).

---

## 15. Delivery phases

- **Phase 0 — Bootstrap** ✅: git, SPEC, README, LICENSE (MIT-0), pyproject (uv/ruff/boto3), package skeleton.
- **Phase 1 — Image construct:** `MicrovmImage`, `MicrovmSource`, least-priv build role, boto3 version lookup, `types/props`, `overrides` escape hatch; unit + security tests; minimal synth test stack green; Makefile; docs skeleton + zensical.
- **Phase 2 — Sample image + boto3-driven E2E:**
  - **2.0 De-risking spike** ✅ **done 2026-07-11** (§0): build→run→auth→ingress→`/echo` proven end-to-end on real AWS; **in-VM Bedrock `/bedrock` returned 500 and is still unproven** (diagnostic re-run deferred). Resources torn down, no zombies.
  - **2.1** least-priv VM execution role + connector/idle helpers + `CfnOutput`s; `microvm_app/` (Dockerfile + `/run`-hook worker: echo + Bedrock tiers; CLI tier opt-in); `sample_stack.py`; **E2E pytest fixture drives `run_microvm` via boto3 from stack outputs** → prompt (echo) with guaranteed terminate; `make deploy` / `make e2e` / `make destroy`.
- **Phase 3 — VPC egress + hardening:** `AWS::Lambda::NetworkConnector` + `aws_ec2_alpha` VpcV2 (2 AZ) behind `EgressConnector.vpc(...)`; security tests.
- **Phase 4 — Custom resource (maybe):** resolve §8 update semantics; add boot-a-VM CR (would also make `MicrovmId`/`MicrovmEndpoint` deploy-time outputs, §4.5).
- **Phase 5 — Optional launcher (deferred):** thin `run_microvm` Lambda, and separately an API-Gateway/WAF front door, only if a hosted control surface is wanted.
- **Phase 6 — Publish:** finalize docs, CI + release workflow, GitHub Pages, tag → (Test)PyPI.
  - **Scaffolded:** CI (`ci.yml`: lint/complex/unit/synth, no AWS), gated E2E (`e2e.yml`, OIDC), docs →
    Pages (`docs.yml`, zensical), release (`release.yml`: tag `v*` → wheel → PyPI Trusted Publishing +
    GH release), plus community automation (PR labeler, semantic PR title, issue comment, Dependabot,
    FUNDING, release-notes). Makefile drives the CDK CLI via `npx aws-cdk`; docs pages complete
    (Home/Getting Started/Construct/Contributing/Pipeline/Security).
  - **Remaining:** PyPI Trusted-Publisher registration + version bump/tag; TestPyPI dry-run.

---

## 16. Key references

- Lambda MicroVMs guide — https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html
- Getting started — https://docs.aws.amazon.com/lambda/latest/dg/microvms-getting-started.html
- Running/using MicroVMs (hooks, run params) — https://docs.aws.amazon.com/lambda/latest/dg/microvms-launching.html
- Networking — https://docs.aws.amazon.com/lambda/latest/dg/microvms-networking.html
- RunMicrovm API — https://docs.aws.amazon.com/lambda/latest/microvm-api/API_RunMicrovm.html
- `AWS::Lambda::MicrovmImage` — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-lambda-microvmimage.html
- SAM/TypeScript sample — https://github.com/aws-samples/sample-lambda-microvm-claude-managed-agents
- Cookbook Makefile / zensical / VpcV2 construct — https://github.com/ran-isenberg/aws-lambda-handler-cookbook
- PyPI Trusted Publishing — https://docs.pypi.org/trusted-publishers/
