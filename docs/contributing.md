# Contributing

Contributions are welcome. This project uses **[uv](https://docs.astral.sh/uv/)** for environment and
dependency management and targets **Python 3.11+**. This page covers the prerequisites and environment
setup; the [Pipeline](pipeline.md) page describes what CI runs, and [Security](security.md) the
guarantees to keep intact.

## Prerequisites

| Tool | Why | Notes |
|------|-----|-------|
| **Python 3.11+** | the library + tests | **3.11 is the minimum** (`requires-python = ">=3.11"`); authored/tested on 3.14, which CI runs (`uv python install 3.14`) |
| **[uv](https://docs.astral.sh/uv/)** | venv + dependency management | **required** — drives every Makefile target (`make dev` runs `uv sync`) |
| **Node.js** | the AWS CDK CLI via `npx aws-cdk` | CI uses Node 24; no global `cdk` install needed |
| **git** | version control | |
| **AWS account + credentials** | **only** for `make deploy` / `make e2e` | not needed for lint, unit tests, or synth |

Linting, unit tests, and `cdk synth` run **fully offline** — the base-image lookup falls back to
`"0"` and boto3 is mocked. You only need AWS credentials to deploy the sample or run E2E.

## Environment setup

```bash
git clone https://github.com/ran-isenberg/lambda-microvm-cdk-python.git
cd lambda-microvm-cdk-python
make dev          # uv sync — creates the venv and installs all dev dependencies
```

`make dev` installs the runtime deps (`aws-cdk-lib`, `constructs`, `boto3`) plus the dev group
(`pytest`, `pytest-cov`, `ruff`, `mypy`, `cdk-nag`, `anthropic[bedrock]`, `zensical`).

## Development loop

| Command | What it does |
|---------|--------------|
| `make format` | auto-fix lint issues + format (`ruff`) |
| `make lint` | `ruff format --check` + `ruff check` + `mypy --strict` |
| `make unit` | unit tests + coverage (no AWS; boto3 mocked) |
| `make complex` | complexity gate (`radon` / `xenon`) |
| `make synth` | `npx aws-cdk synth` the sample app (runs cdk-nag `AwsSolutionsChecks`) |
| `make pr` | the full pre-merge gate: `format + lint + unit + synth` |

Real-AWS targets (need credentials, and always clean up after themselves):

```bash
make deploy    # npx aws-cdk deploy the sample stack
make e2e       # launch a MicroVM, prompt, assert, terminate in teardown
make destroy   # tear down the stack
```

Docs are built with zensical:

```bash
make docs          # serve locally with live reload
make publish-docs  # build the static site into ./site
```

## Conventions

- **Every change to the construct or sample ships with a test** under `tests/unit/` using
  `aws_cdk.assertions` — no test, not done.
- **Least-privilege IAM, secure defaults, and a green cdk-nag** are non-negotiable; any
  `NagSuppressions` entry needs a written justification.
- **PR titles and commits** use the `feature | fix | docs | chore` prefix (validated in CI by the
  semantic PR-title check, and used by the PR labeler).
- Run `make pr` before opening a pull request.
