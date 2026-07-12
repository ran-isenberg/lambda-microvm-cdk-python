# Construct

The library exposes a single CDK construct, **`LambdaMicroVM`**, exported from the package root.
Supporting internals live under `_impl/` and are not part of the supported surface.

## `LambdaMicroVM`

Provisions `AWS::Lambda::MicrovmImage` from a source asset with least-privilege build + VM-execution
roles, a resolved base-image version, secure defaults, input validation, and an `overrides` escape
hatch. All keyword arguments are keyword-only.

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `source` | `str \| s3_assets.Asset` | — | dir with a `Dockerfile`, a `.zip` path, or an `Asset` |
| `name` | `str \| None` | derived (stable) | `^[a-zA-Z0-9-_]+$`, 1–64; changing it forces replacement |
| `description` | `str` | `""` | |
| `base_image` | `str` | `"al2023-1"` | short alias or full ARN |
| `base_image_version` | `str \| None` | boto3 lookup → `"0"` | pin to override |
| `architecture` | `aws_lambda.Architecture` | `ARM_64` | only value the service accepts today |
| `memory_mib` | `int` | `2048` | tier `512 \| 1024 \| 2048 \| 4096 \| 8192` |
| `os_capabilities` | `list[Literal["ALL"]] \| None` | `[]` | `ALL` is a privilege escalation |
| `environment` | `dict[str, str] \| None` | `{}` | never secrets — snapshotted |
| `egress_connectors` | `list[str] \| None` | `[]` | max 10 |
| `enable_logging` | `bool` | `True` | CloudWatch group pinned; `False` → `Disabled` |
| `hooks` | `CfnMicrovmImage.HooksProperty \| None` | `None` (`{}` = disabled) | typed L1 struct |
| `build_role` | `iam.IRole \| None` | created | bring-your-own least-priv |
| `execution_role` | `iam.IRole \| None` | created | bring-your-own least-priv |
| `log_retention` | `aws_logs.RetentionDays \| None` | `TWO_WEEKS` | `None` leaves retention unmanaged |
| `removal_policy` | `RemovalPolicy` | `DESTROY` | |
| `tags` | `dict[str, str] \| None` | `{}` | cost-allocation friendly |
| `overrides` | `dict[str, Any] \| None` | `{}` | merged verbatim into L1 `Properties` |

### Properties

`image_arn`, `state`, `latest_active_image_version`, `image_name`, `log_group_name`, `build_role`,
`execution_role`, `ingress_connector_arn` (`ALL_INGRESS`), `egress_connector_arn`
(`INTERNET_EGRESS`).

### Methods

`grant_run(grantee)` — attaches least-privilege `lambda:RunMicrovm*` (+ `iam:PassRole` on the VM
execution role) to a runtime-caller principal, scoped to this image ARN.

## Runtime (boto3, not CloudFormation)

Running a MicroVM is a runtime API call — see [Getting Started](getting_started.md#launching-a-vm-runtime-boto3).
A thin launcher Lambda (and, separately, an API-Gateway/WAF front door) is a **deferred, opt-in**
add-on, not in the current scope.

## VPC egress (Phase 3)

`AWS::Lambda::NetworkConnector` + `aws_ec2_alpha` VpcV2 (2 AZs) behind an `EgressConnector.vpc(...)`
helper. Off by default (default egress is internet). Not yet implemented.
