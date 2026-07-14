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
- **`MicrovmNetworkConnector`** — opt-in **VPC egress**: bring your own VPC and it wires up the rest —
  the `AWS::Lambda::NetworkConnector`, a security group that **is** the egress policy (deny-all by
  default), and a least-privilege ENI operator role. Pass it straight to
  `LambdaMicroVM(egress_connectors=[...])`. See [MicroVM Image](construct.md) and [Network Connector](custom_egress.md).

Parameter-driven with secure defaults (arm64, no extra OS capabilities, CloudWatch logging),
every AWS knob overridable, plus an `overrides` escape hatch for anything not yet modeled.

See [Getting Started](getting_started.md), [Security](security.md), and [Pipeline](pipeline.md).
