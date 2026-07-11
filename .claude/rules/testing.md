# Testing rules

- **Every CDK change ships with a Python test.** Any change to `src/lambda_microvm_cdk/**` or
  `sample/*_stack.py` **must** add/update a test in `tests/unit/` using
  `aws_cdk.assertions.Template.from_stack(...)`. No test → not done.
- **Assert the meaningful things:** the resource exists, critical props (`BaseImageVersion`,
  `Architecture: ARM_64`, `CodeArtifact.Uri`), **least-privilege** IAM (scoped resources, never `*`),
  secure defaults, and that invalid inputs **raise**. Keep a dedicated `test_security.py`.
- **Unit tests make no AWS calls** — mock the boto3 base-image-version lookup.
- **cdk-nag `AwsSolutionsChecks`** (AWS-recommended pack) runs at synth on every stack; treat findings
  as failures. A unit test asserts there are **no unsuppressed `AwsSolutions-*` errors**. Any
  `NagSuppressions` entry needs a written justification.
- `make synth` stays green. **E2E (`make e2e`, real AWS)** lives in `tests/e2e/` and needs AWS creds +
  a deployed stack; it is **never part of `make unit`/CI's default gate** (that target only runs
  `tests/unit/`), and always leaves the account clean (see AWS guardrails).
