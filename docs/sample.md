# Sample app

The [`sample/`](https://github.com/ran-isenberg/lambda-microvm-cdk-python/tree/main/sample) app
deploys a MicroVM that runs a model worker on **Amazon Bedrock (us-east-1)** — Nova 2 Lite by
default, Claude Opus 4.8 opt-in. It is the target of the E2E suite (`make e2e`), which boots **one**
VM, runs **two tests** against it, and terminates it in teardown:

- **`echo`** — a deterministic round-trip (build → run → auth → ingress → app), no model in the loop.
  This is the library's gate.
- **`bedrock`** — a real model round-trip: it asks the model to add **two random numbers** and asserts
  the reply contains their sum (non-deterministic; on failure the captured error body is surfaced).

```bash
make deploy   # npx aws-cdk deploy the sample
make e2e      # launch the MicroVM, prompt, assert, terminate in teardown
make destroy  # tear down
```

## Choosing the model: Nova vs Opus

The `/bedrock` tier calls **one** model, selected by the `MODEL_PROVIDER` / `MODEL_ID` env vars. The
deterministic `/echo` tier calls no model — it's the gate that never depends on a model (the
`/bedrock` E2E test does, and asserts the model's answer).

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

## The image (`Dockerfile`)

Everything is installed at **build** time and snapshotted, so no `ALL` OS capability is needed at
runtime. `boto3` drives the default Nova/Converse path; `anthropic` drives the opt-in Opus path.
Model routing is set via non-secret env vars (`AWS_REGION` is injected by the runtime — never set it).

```dockerfile
--8<-- "sample/microvm_app/Dockerfile"
```

## The worker (`worker.py`)

An HTTP server on `:8080` with three isolated tiers: `/echo` (deterministic — the E2E gate),
`/bedrock` (one model call — the E2E model test asks for the sum of two random numbers and checks it),
and an opt-in `agent` tier. It also exposes the runtime lifecycle hooks under `/aws/lambda-microvms/runtime/v1/*` and
`/health`. Secrets are **never** read from image env — per-VM data arrives via the `/run` hook
payload or SSM at runtime.

??? example "worker.py (full source)"

    ```python
    --8<-- "sample/microvm_app/worker/worker.py"
    ```
