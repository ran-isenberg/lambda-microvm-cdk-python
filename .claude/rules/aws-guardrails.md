# AWS deploy / destroy guardrails (non-negotiable)

When anything creates or destroys cloud resources: if in doubt, **stop and ask**.

1. **Infrastructure is created ONLY via AWS CDK / CloudFormation.** Never create AWS infra (IAM, S3,
   log groups, MicroVM images, network connectors, …) with ad-hoc `boto3`, `aws` CLI, or the console.
   If it should exist, it belongs in a CDK construct/stack in this repo.
2. **Only deploy or destroy resources defined by THIS repo's CDK stacks.** `cdk deploy`/`cdk destroy`
   (via `make deploy`/`make destroy`) target this repo's stack(s) only. Never target another stack,
   account resource, or unrelated infra. Never run `aws … delete-*`/`create-*`/`put-*` on arbitrary
   resources. Never delete anything you did not create here — if outside cleanup seems needed, ask
   first and list what and why.
3. **Sanctioned runtime exception — launching/terminating MicroVMs** (a running VM is runtime API,
   not CloudFormation). Allowed only: from the E2E fixture / clearly-scoped consumer code, against an
   image from this repo's stack, with a `maximumDurationInSeconds` cap, and with guaranteed
   `terminate_microvm` in `try/finally`/teardown. Never leave a VM running. Terminate the VM **before**
   deleting its image (the API blocks image deletion while a VM runs).
4. **Ask before every deploy, destroy, or irreversible cloud action.** Approval for one is not
   approval for the next. State exactly which stack/resources will change.
5. **After AWS work, verify no zombie/billable resources remain** (read-only `list_*`/`describe_*` is
   always fine) and report it.
6. **No secrets in CDK code, image `EnvironmentVariables`, or handlers** (image env is snapshotted +
   shared). Use SSM / Secrets Manager at runtime, or per-VM `runHookPayload`.
