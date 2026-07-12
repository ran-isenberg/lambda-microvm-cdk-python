.PHONY: dev lint format format-fix mypy-lint unit build synth deploy destroy e2e \
        docs docs-serve publish-docs lint-docs complex package pr help

PYTHON := uv run
# CDK CLI comes from npm via npx (no global install); the app itself is Python (see sample/cdk.json).
CDK    := npx --yes aws-cdk@2
SAMPLE := sample

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## --- Setup ------------------------------------------------------------------
dev:  ## Create venv and install deps (incl. dev group)
	uv sync

update-deps:  ## Update the uv lockfile
	uv lock --upgrade

## --- Quality ----------------------------------------------------------------
format:  ## Auto-fix lint issues and format
	$(PYTHON) ruff check --fix .
	$(PYTHON) ruff format .

format-fix: format  ## Alias for format

lint:  ## Check formatting, lint, and types (CI-safe, no writes)
	$(PYTHON) ruff format --check .
	$(PYTHON) ruff check .
	$(MAKE) mypy-lint

mypy-lint:  ## Static type check
	$(PYTHON) mypy src sample tests

complex:  ## Report code complexity
	$(PYTHON) radon cc -e "tests/*,cdk.out/*" src sample
	$(PYTHON) xenon --max-absolute C --max-modules B --max-average A -e "tests/*,cdk.out/*" src

## --- Tests ------------------------------------------------------------------
unit:  ## Unit tests (no AWS) with coverage
	$(PYTHON) pytest tests/unit --cov=lambda_microvm_cdk --cov-report=term-missing

e2e:  ## Deploy-backed E2E: invoke MicroVM with a prompt, assert result (needs AWS creds)
	$(PYTHON) pytest tests/e2e -v

## --- Build / Infra (also used by the pipeline) ------------------------------
build:  ## Package the sample MicroVM artifact (Dockerfile + worker -> zip)
	$(PYTHON) python sample/scripts/build_image.py

synth:  ## cdk synth the sample app
	cd $(SAMPLE) && $(CDK) synth

deploy:  ## cdk deploy the sample app (pipeline)
	cd $(SAMPLE) && $(CDK) deploy --require-approval never --all

destroy:  ## cdk destroy the sample app (pipeline)
	cd $(SAMPLE) && $(CDK) destroy --force --all

## --- Packaging --------------------------------------------------------------
package:  ## Build the sdist + wheel (published to PyPI by the release workflow)
	uv build

## --- Docs (GitHub Pages via zensical) ---------------------------------------
docs: docs-serve  ## Alias: serve docs locally

docs-serve:  ## Serve docs locally
	$(PYTHON) zensical serve

publish-docs:  ## Build docs for GitHub Pages
	$(PYTHON) zensical build

lint-docs:  ## Fix markdown formatting
	npx --yes markdownlint-cli --fix "docs/**/*.md" "*.md"

## --- Aggregate --------------------------------------------------------------
pr:  ## Pre-merge gate: format + lint + complexity + unit + synth
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) complex
	$(MAKE) unit
	$(MAKE) synth
