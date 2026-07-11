"""Tiered MicroVM worker — HTTP server on :8080 (SPEC.md §11).

Tiers (isolated so the risky pieces never gate the library):
  1. ``/echo``    — deterministic, no model. **E2E asserts on this.**
  2. ``/bedrock`` — one model call. Default: Amazon Nova 2 Lite via the boto3 Bedrock Converse API;
                    opt-in Claude Opus 4.8 via the Anthropic SDK (``MODEL_PROVIDER=anthropic``).
                    Credentials come from the VM execution role; errors captured verbatim for diagnosis.
  3. ``agent``    — Claude Code headless; opt-in, NOT installed by default (see Dockerfile).

Also exposes the runtime lifecycle hooks under ``/aws/lambda-microvms/runtime/v1/*``
(the sample runs with hooks disabled, so these are inert but demonstrate the contract)
and ``/health`` for smoke checks. Secrets are NEVER read from image env — per-VM data
arrives via the ``/run`` hook payload (runHookPayload) or SSM at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = int(os.environ.get('PORT', '8080'))
# Model routing for the /bedrock tier (set in the Dockerfile). Default: Amazon Nova 2 Lite via the
# boto3 Bedrock Converse API. Set MODEL_PROVIDER=anthropic + MODEL_ID=us.anthropic.claude-opus-4-8
# to call Claude Opus 4.8 via the Anthropic SDK instead (needs Bedrock model access). SPEC.md §11.
MODEL_PROVIDER = os.environ.get('MODEL_PROVIDER', 'bedrock')
MODEL_ID = os.environ.get('MODEL_ID', 'us.amazon.nova-2-lite-v1:0')
MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '1024'))
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')  # runtime-injected (reserved key, §0)
HOOK_PREFIX = '/aws/lambda-microvms/runtime/v1/'

logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO').upper(), format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('claude-agent')


def echo_transform(prompt: str) -> str:
    """Deterministic, model-free transform — the stable target for E2E assertions."""
    return f'ECHO[{prompt}]'


def model_completion(prompt: str) -> str:
    """Tier 2 — one model call; region + credentials come from the VM execution role at runtime.

    Default provider ``bedrock`` calls Amazon Nova via the model-agnostic Bedrock Converse API;
    ``anthropic`` calls Claude via the Anthropic SDK (opt-in — needs Bedrock model access).
    """
    if MODEL_PROVIDER == 'anthropic':
        return _opus_completion(prompt)
    return _nova_completion(prompt)


def _nova_completion(prompt: str) -> str:
    """Amazon Bedrock Converse API (boto3) — model-agnostic; the default for any Bedrock model."""
    import boto3  # imported lazily so tier 1 never depends on it

    client = boto3.client('bedrock-runtime', region_name=AWS_REGION)
    response = client.converse(
        modelId=MODEL_ID,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': MAX_TOKENS},
    )
    return ''.join(block['text'] for block in response['output']['message']['content'] if 'text' in block)


def _opus_completion(prompt: str) -> str:
    """Anthropic SDK on Bedrock (AnthropicBedrockMantle) — Claude only; opt-in via MODEL_PROVIDER=anthropic."""
    from anthropic import AnthropicBedrockMantle  # imported lazily so the default path never needs anthropic

    client = AnthropicBedrockMantle(aws_region=AWS_REGION)
    message = client.messages.create(model=MODEL_ID, max_tokens=MAX_TOKENS, messages=[{'role': 'user', 'content': prompt}])
    return ''.join(block.text for block in message.content if block.type == 'text')


class WorkerHandler(BaseHTTPRequestHandler):
    server_version = 'microvm-worker/1.0'

    def _send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get('Content-Length', '0'))
        if length == 0:
            return {}
        parsed = json.loads(self.rfile.read(length).decode())
        return parsed if isinstance(parsed, dict) else {}

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler contract
        logger.info('GET %s', self.path)
        if self.path == '/health':
            self._send_json(HTTPStatus.OK, {'status': 'ok'})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {'error': f'unknown path {self.path}'})

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler contract
        logger.info('POST %s', self.path)
        if self.path.startswith(HOOK_PREFIX):
            self._handle_hook(self.path.removeprefix(HOOK_PREFIX))
            return
        try:
            body = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning('POST %s — invalid JSON body: %s', self.path, exc)
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': f'invalid JSON body: {exc}'})
            return
        prompt = str(body.get('prompt', ''))
        logger.info('POST %s — prompt=%r', self.path, prompt)
        if self.path == '/echo':
            result = echo_transform(prompt)
            logger.info('echo — result=%r', result)
            self._send_json(HTTPStatus.OK, {'mode': 'echo', 'result': result})
        elif self.path == '/bedrock':
            self._handle_bedrock(prompt)
        else:
            logger.info('POST %s — unknown path', self.path)
            self._send_json(HTTPStatus.NOT_FOUND, {'error': f'unknown path {self.path}'})

    def _handle_hook(self, hook: str) -> None:
        """Lifecycle hooks: /run admits traffic when it returns HTTP 200; per-VM secrets/refs arrive in its payload.

        UUIDs/secrets must be generated HERE with a CSPRNG (never at build — snapshots are shared, §5.8).
        """
        logger.info('lifecycle hook invoked: %s', hook)
        if hook in ('run', 'resume', 'suspend', 'terminate'):
            self._send_json(HTTPStatus.OK, {'hook': hook, 'status': 'ok'})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {'error': f'unknown hook {hook}'})

    def _handle_bedrock(self, prompt: str) -> None:
        logger.info('bedrock — provider=%s model=%s prompt=%r', MODEL_PROVIDER, MODEL_ID, prompt)
        try:
            result = model_completion(prompt)
            logger.info('bedrock — provider=%s model=%s result=%r', MODEL_PROVIDER, MODEL_ID, result)
            self._send_json(HTTPStatus.OK, {'mode': 'bedrock', 'provider': MODEL_PROVIDER, 'model': MODEL_ID, 'result': result})
        except Exception as exc:  # capture the WHOLE error body — the spike's 500 was undiagnosable without it (§0)
            logger.exception('bedrock tier failed (provider=%s model=%s)', MODEL_PROVIDER, MODEL_ID)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    'mode': 'bedrock',
                    'provider': MODEL_PROVIDER,
                    'model': MODEL_ID,
                    'error': f'{exc.__class__.__name__}: {exc}',
                    'trace': traceback.format_exc(),
                },
            )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — BaseHTTPRequestHandler contract
        logger.info('%s %s', self.address_string(), format % args)


def main() -> None:
    logger.info('worker listening on :%d (model=%s)', PORT, MODEL_ID)
    ThreadingHTTPServer(('0.0.0.0', PORT), WorkerHandler).serve_forever()


if __name__ == '__main__':
    main()
