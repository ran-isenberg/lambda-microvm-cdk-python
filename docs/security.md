# Security

Security is a first-class design goal, not a bolt-on. Every generated role is least-privilege,
every AWS knob has a secure default, and every synth is validated against AWS best practices with
cdk-nag. This page summarizes the guarantees the construct provides.

## Least-privilege IAM

`LambdaMicroVM` provisions two purpose-built roles (or accepts your own via `build_role` /
`execution_role`):

- **Build role** — trusts `lambda.amazonaws.com`; may `s3:GetObject` the **exact asset key** (not
  `bucket/*`) and write to the image's log group only. No `*` resources.
- **VM execution role** — the identity a *running* MicroVM assumes. Created with logs-only
  permissions scoped to the image's log group; the consumer (or the sample) layers workload
  permissions on top (the sample grants Bedrock on the specific inference-profile / model ARNs).
- **`grant_run(principal)`** — lets a runtime caller (launcher Lambda / ECS task / CI role) **launch and
  operate a VM from this image, nothing broader**: `lambda:RunMicrovm` scoped to the specific image ARN;
  the VM lifecycle + auth-token actions (`SuspendMicrovm`, `ResumeMicrovm`, `TerminateMicrovm`,
  `CreateMicrovmAuthToken`, `GetMicrovm`, `ListMicrovms`) scoped to this account+region; and `iam:PassRole`
  limited to the VM execution role. No image-build/CloudFormation perms, no `*`. See the
  [MicroVM Image](construct.md) page for the full breakdown.

## Secrets — never in the image

`EnvironmentVariables` are **baked into the snapshot** and shared by every VM launched from that
image, so **secrets must never go there**. This can't be enforced (a secret value under an innocent
key is undetectable), so it's guidance: pass secret *references* per-VM via `runHookPayload`, or fetch
from SSM Parameter Store / Secrets Manager at runtime inside the `/run` hook using the VM execution role.

## Secure defaults

| Concern | Default |
|---------|---------|
| Architecture | `ARM_64` (the only value the service accepts today; anything else raises) |
| OS capabilities | `[]` — `ALL` is a documented privilege escalation you must opt into |
| Logging | CloudWatch enabled, group pinned to `/aws/lambda/microvms/<name>`, retention 2 weeks |
| Egress | internet by default; opt-in VPC egress via `MicrovmNetworkConnector` (BYO-VPC) |
| Auth tokens | short expiry, `allowedPorts=[{"port": 8080}]` (minted by the caller/E2E fixture) |
| Max TTL | `maximumDurationInSeconds` always set at launch as a hard cost/lifetime backstop |
| Env vars | `{}` — snapshotted & shared across every VM; **never put secrets here** (not enforceable — fetch them at runtime from SSM/Secrets Manager, or pass per-VM via `runHookPayload`) |

Invalid or out-of-range inputs (name regex, architecture, memory tier, env keys, connector count)
**raise at synth**, so a template the API would reject is never produced.

## cdk-nag at synth

The sample app applies the cdk-nag **`AwsSolutionsChecks`** pack as a CDK Aspect, so
`make synth` (and CI) **fail on any `AwsSolutions-*` finding** — misconfigurations are caught before
`cdk deploy`. A unit test asserts there are no unsuppressed findings. Any suppression carries an
explicit id + written justification. cdk-nag is a **dev** dependency only — it is not a runtime
dependency of the published wheel, so consumers apply their own nag packs.

## Reporting a vulnerability

Please open a [GitHub issue](https://github.com/ran-isenberg/lambda-microvm-cdk-python/issues) (or,
for sensitive reports, use GitHub's private security advisory flow on the repository).
