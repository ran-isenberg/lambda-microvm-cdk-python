# lambda-microvm-cdk

<a href="https://ranthebuilder.cloud/"><img src="media/banner.png" alt="banner" width="1086"></a>

A reusable **AWS CDK v2 construct (pure Python, 3.11+)** for provisioning
[AWS Lambda MicroVMs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) —
Firecracker-based, VM-isolated, snapshot-fast serverless compute for AI sandboxes,
interactive dev environments, and multi-tenant CI.

## Install

```bash
pip install lambda-microvm-cdk
```

## What you get

- **`LambdaMicroVM`** — declarative `AWS::Lambda::MicrovmImage`: zip your `Dockerfile`+app,
  upload to S3, create least-privilege build + VM-execution roles, resolve the base-image version,
  and build a snapshotted image. Exposes typed properties (`image_arn`, `execution_role`,
  `ingress_connector_arn` / `egress_connector_arn`, `log_group_name`) and `grant_run(principal)`.
- **Runtime** (run/suspend/terminate) is a boto3 call driven from your app or the E2E fixture, wired
  from those properties — there is no launcher Lambda / API Gateway / WAF in the current scope.

Parameter-driven with secure defaults (arm64, no extra OS capabilities, CloudWatch logging),
every AWS knob overridable, plus an `overrides` escape hatch for anything not yet modeled.

See [Getting Started](getting_started.md), [Security](security.md), and [Pipeline](pipeline.md).
