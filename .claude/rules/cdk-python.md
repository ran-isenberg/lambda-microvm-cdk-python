# AWS CDK (Python) best practices

Per [ranthebuilder — CDK best practices from the trenches](https://ranthebuilder.cloud/blog/aws-cdk-best-practices-from-the-trenches/):

- **Compose with constructs, not extra stacks.** Model constructs around a domain (image, networking,
  runtime role). New stack only for a genuinely separate concern.
- **Separate infra from app code.** CDK in `src/`+`sample/`; the in-VM worker in `sample/microvm_app/`.
- **Least-privilege IAM, explicit and resource-scoped.** Prefer hand-written policy documents over
  broad `grant_*` when it clarifies intent; scope `Resource` to specific ARNs, never `*`. Each role is
  purpose-built (build role ≠ VM execution role).
- **Stateful resources:** set `RemovalPolicy` deliberately (`DESTROY` in dev/sample, `RETAIN` for
  must-survive); **never change a stateful resource's logical ID** (forces replacement).
- **Security-first defaults;** validate `AwsSolutionsChecks` at synth (see testing rule).
- **No hardcoded account/region** — resolve via `Stack.of(self)`. No hardcoded secrets.
- **Balanced abstraction** — readability over clever factories; minor duplication is fine in infra.
- **Config in code** — stage/account differences via config + conditionals, not copy-paste stacks.
- **Tag resources** for cost allocation.
- **Confirm L1 property shapes** against the CFN registry / boto3 service model before wiring
  — the MicroVM resources are new and not all L2-modeled.
