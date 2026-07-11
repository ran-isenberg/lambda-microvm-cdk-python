# lambda-microvm-cdk

A reusable **AWS CDK v2 construct (pure Python, 3.11+)** for provisioning
[AWS Lambda MicroVMs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-microvms-guide.html) —
Firecracker-based, VM-isolated, snapshot-fast serverless compute for AI sandboxes,
interactive dev environments, and multi-tenant CI.

!!! warning "Early development"
    APIs are being implemented per [the spec](https://github.com/ran-isenberg/lambda-microvm-cdk-python/blob/main/SPEC.md). Phase 1 (the `MicrovmImage` construct) is in progress.

## Install

```bash
pip install lambda-microvm-cdk
```

## What you get

- **`MicrovmImage`** — declarative `AWS::Lambda::MicrovmImage`: zip your `Dockerfile`+app,
  upload to S3, create a least-privilege build role, build a snapshotted image.
- **`MicrovmLauncher`** *(Phase 3)* — a Lambda + API Gateway (WAF) that launches/suspends/
  resumes/terminates running MicroVMs, with a configurable `IdlePolicy`.

Parameter-driven with secure defaults (arm64, no extra OS capabilities, CloudWatch logging),
every AWS knob overridable, plus a `**extra_properties` escape hatch for anything not yet modeled.

See [Getting Started](getting_started.md) and [Security](security.md).
