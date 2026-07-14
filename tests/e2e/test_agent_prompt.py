"""E2E — send a prompt to the running MicroVM and assert the result.

Two tests run against one VM: the deterministic **echo tier is the library's gate** (zero model
dependency), and a **bedrock** test that asks the model to add two random numbers and asserts the
reply. On failure the bedrock test surfaces the full captured error body for diagnosis.
"""

from __future__ import annotations

import json
import random
import re
import urllib.request
from http import HTTPStatus
from typing import Any

PORT_HEADER = {'X-aws-proxy-port': '8080'}


def _post(endpoint: str, path: str, headers: dict[str, str], payload: dict[str, Any], timeout: int = 120) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f'https://{endpoint}{path}',
        data=body,
        headers={**headers, **PORT_HEADER, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:  # read the error body — never discard diagnostics
        return error.code, json.loads(error.read().decode() or '{}')


def test_echo_prompt_round_trip(running_microvm: dict[str, Any], auth_headers: dict[str, str]) -> None:
    """Deterministic assertion: build -> run -> auth -> ingress -> app, no model in the loop."""
    prompt = 'hello microvm'
    status, body = _post(running_microvm['endpoint'], '/echo', auth_headers, {'prompt': prompt})
    assert status == HTTPStatus.OK, f'echo tier failed: {body}'
    assert body['result'] == f'ECHO[{prompt}]'
    assert body['mode'] == 'echo'


def test_bedrock_prompt_sums_two_random_numbers(running_microvm: dict[str, Any], auth_headers: dict[str, str]) -> None:
    """Model tier via the VM execution role: ask the model to add two fresh random numbers and assert the
    reply contains their sum (a real, non-deterministic model round-trip — not an echo). On failure, surface
    the captured error body."""
    x, y = random.randint(1, 99), random.randint(1, 99)
    expected = x + y
    prompt = f'What is {x} + {y}? Reply with just the sum as a single number, nothing else.'
    status, body = _post(running_microvm['endpoint'], '/bedrock', auth_headers, {'prompt': prompt})
    if status != HTTPStatus.OK:
        raise AssertionError(f'bedrock tier returned {status} for prompt {prompt!r} — captured diagnostics: {json.dumps(body, indent=2)}')
    result = str(body['result'])
    # Word-boundary match so e.g. sum 42 isn't spuriously found inside "1428".
    assert re.search(rf'(?<!\d){expected}(?!\d)', result), f'expected sum {expected} for {x}+{y}, got model reply: {result!r}'
