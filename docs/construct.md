# MicroVM image — `LambdaMicroVM`

The library exposes two CDK constructs from the package root: **`LambdaMicroVM`** (this page) and
**`MicrovmNetworkConnector`** (opt-in VPC egress — see [Network Connector](custom_egress.md)).
Supporting internals live under `_impl/` and are not part of the supported surface.

`LambdaMicroVM` provisions `AWS::Lambda::MicrovmImage` from a source asset with least-privilege build +
VM-execution roles, a resolved base-image version, secure defaults, input validation, and an
`overrides` escape hatch. All keyword arguments are keyword-only.

## Inputs

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
| `egress_connectors` | `list[str \| MicrovmNetworkConnector] \| None` | `[]` | max 10; **build-time** egress ([Network Connector](custom_egress.md)) |
| `enable_logging` | `bool` | `True` | CloudWatch group pinned; `False` → `Disabled` |
| `hooks` | `CfnMicrovmImage.HooksProperty \| None` | `None` (`{}` = disabled) | typed L1 struct |
| `build_role` | `iam.IRole \| None` | created | bring-your-own least-priv |
| `execution_role` | `iam.IRole \| None` | created | bring-your-own least-priv |
| `log_retention` | `aws_logs.RetentionDays \| None` | `TWO_WEEKS` | `None` leaves retention unmanaged |
| `removal_policy` | `RemovalPolicy` | `DESTROY` | |
| `tags` | `dict[str, str] \| None` | `{}` | cost-allocation friendly |
| `overrides` | `dict[str, Any] \| None` | `{}` | merged verbatim into L1 `Properties` |

## Properties

- **`image_arn`** — `Fn::GetAtt ImageArn` (deploy-time token); the id you pass to `run_microvm`.
- **`state`** — `Fn::GetAtt State` (deploy-time token).
- **`latest_active_image_version`** — `Fn::GetAtt LatestActiveImageVersion` (deploy-time token).
- **`image_name`** — the resolved `Name` (stable across synths; changing it forces replacement).
- **`log_group_name`** — the service-owned log group, `/aws/lambda/microvms/<image-name>`.
- **`build_role`** — the IAM role used to build the image (created least-privilege unless supplied).
- **`execution_role`** — the IAM role the running VM assumes (created least-privilege unless supplied).
- **`ingress_connector_arn`** — AWS-managed `ALL_INGRESS` connector ARN (each VM gets a unique TLS endpoint).
- **`egress_connector_arn`** — AWS-managed `INTERNET_EGRESS` connector ARN (the default public egress).

## Methods

- **`grant_run(grantee)`** — gives a principal (a launcher Lambda, ECS task, or CI role) least-privilege
  permission to launch and operate a MicroVM from **this** image: `lambda:RunMicrovm` on the image, the VM
  lifecycle + auth-token actions, and `iam:PassRole` on the VM execution role. The only public method.

## Runtime (boto3, not CloudFormation)

Running a MicroVM is a runtime API call — see [Getting Started](getting_started.md#launching-a-vm-runtime-boto3).

## VPC egress

To route a VM's outbound traffic through your own VPC, pair it with **`MicrovmNetworkConnector`** —
see [Network Connector](custom_egress.md).
