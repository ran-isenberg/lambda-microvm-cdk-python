# Repo conventions

- **Tooling:** `uv` + `ruff` (line-length 150, single quotes, `E,W,F,I,C,B`) + `mypy --strict` +
  `hatchling`. Drive everything through the **Makefile**:
  `make dev|lint|format|unit|synth|deploy|destroy|e2e|docs`.
- **Layout:** public API is re-exported from the package root; **all implementation lives under
  `src/lambda_microvm_cdk/_impl/` (private)** and must not be imported directly by consumers.
- **Genericity:** every AWS knob is a typed input with a secure default, plus an `overrides: dict`
  escape hatch merged verbatim into the L1 `Properties` (exact CFN casing, no auto-casing).
- **Validated facts to honor** (`SPEC.md` §0): `ARM_64` is the only accepted architecture today;
  `AWS_REGION` is a **reserved** image env key (don't set it); user image versions start at `"1.0"`;
  terminate a MicroVM before deleting its image.
- **Git:** commit or push **only when asked**. Branch off `main`. End commit messages with the
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer. Keep
  `SPEC.md`/`ARCH.md` in sync with code.
- **Definition of done:** code + passing `make unit` + `make lint` clean + `make synth` green (incl.
  cdk-nag) + `SPEC.md`/`ARCH.md` updated if behavior changed.
