# API

> Generated docs will expand as constructs land. This page tracks the intended public surface
> (see [SPEC.md](https://github.com/ran-isenberg/lambda-microvm-cdk-python/blob/main/SPEC.md) §4).

## `MicrovmImage` (Phase 1)

Provisions `AWS::Lambda::MicrovmImage` from a source asset with a least-privilege build role.

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `source` | `MicrovmSource` | — | `from_asset(dir)` / `from_asset_zip(path)` / `from_s3(bucket, key)` |
| `name` | `str \| None` | derived | `^[a-zA-Z0-9-_]+$`, 1–64 |
| `description` | `str` | `""` | |
| `base_image` | `str` | `"al2023-1"` | short alias or full ARN |
| `base_image_version` | `str \| None` | boto3 lookup → `"0"` | pin to override |
| `architecture` | `Architecture` | `ARM_64` | |
| `size` | `MicrovmSize` | `MEM_1GB` | → `MinimumMemoryInMiB` |
| `os_capabilities` | `list[OsCapability]` | `[]` | `ALL` is a privilege escalation |
| `environment` | `dict[str, str]` | `{}` | |
| `egress_connectors` | `list[str]` | `[]` | |
| `logging` | `LoggingConfig` | `cloud_watch()` | or `disabled()` |
| `build_role` | `iam.IRole \| None` | created | bring-your-own least-priv |
| `tags` | `dict[str, str]` | `{}` | |
| `**extra_properties` | | | merged into L1 `Properties` |

**Attributes:** `image_arn`, `state`, `build_role`. **Methods:** `grant_run(principal)`.

## `MicrovmLauncher` (Phase 3)

Lambda + **API Gateway + WAF** (default) to run/suspend/resume/terminate MicroVMs.
Key input: `idle_policy: IdlePolicy(auto_resume, max_idle_seconds, suspended_seconds)`.

## Enums / helpers

`Architecture`, `MicrovmSize`, `LoggingConfig`, `OsCapability`, `MicrovmSource`,
`IngressConnector`, `EgressConnector`, `IdlePolicy`.
