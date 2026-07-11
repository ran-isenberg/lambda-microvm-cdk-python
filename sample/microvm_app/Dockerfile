# Sample MicroVM app image — tiers 1 (echo) + 2 (a model call on Bedrock).
# Layered on the AWS-managed al2023-1 base image (SPEC.md §11). Same base the Phase-2.0
# spike proved end-to-end (build -> run -> auth -> ingress -> /echo).
FROM public.ecr.aws/docker/library/python:3.14-slim

# Everything is installed at BUILD time (snapshotted) — no ALL os-capability needed at runtime.
# boto3 drives the default Nova/Converse path; anthropic drives the opt-in Opus path.
# --no-cache-dir keeps the snapshot small (§5.8: minimize snapshot).
RUN pip install --no-cache-dir boto3 anthropic

# --- Model routing for the /bedrock worker tier (non-secret; SPEC.md §11) ---------------------
# Default: Amazon Nova 2 Lite via the boto3 Bedrock Converse API (INFERENCE_PROFILE-only; the
# us. profile is ACTIVE in us-east-1, §0). To use Claude Opus 4.8 via the Anthropic SDK instead
# (needs Bedrock model access), override at build/run time:
#     MODEL_PROVIDER=anthropic  MODEL_ID=us.anthropic.claude-opus-4-8
# NOTE: AWS_REGION must NOT be set here — the MicroVM runtime injects it (reserved key, §0).
ENV MODEL_PROVIDER=bedrock \
    MODEL_ID=us.amazon.nova-2-lite-v1:0

# --- Opt-in tier 3 (Claude Code headless CLI, Claude-only; harmless if the CLI isn't installed) ---
# ANTHROPIC_API_KEY must stay UNSET so the CLI routes to Bedrock, not the Anthropic API.
ENV CLAUDE_CODE_USE_BEDROCK=1 \
    ANTHROPIC_MODEL=us.anthropic.claude-opus-4-8 \
    ANTHROPIC_SMALL_FAST_MODEL=us.anthropic.claude-opus-4-8 \
    CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096 \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    DISABLE_ERROR_REPORTING=1 \
    IS_SANDBOX=1 \
    HOME=/workspace
RUN mkdir -p /workspace

WORKDIR /app
COPY worker/worker.py /app/worker.py

# --- Tier 3 (opt-in, NOT installed by default): Claude Code headless agent ---
# Uncomment to layer the CLI agent on top (Node 22 + the CLI; the ENV block above already
# configures it for Bedrock — IS_SANDBOX=1 allows --dangerously-skip-permissions in the VM):
#   RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
#       && npm install -g @anthropic-ai/claude-code \
#       && apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 8080
CMD ["python", "/app/worker.py"]
