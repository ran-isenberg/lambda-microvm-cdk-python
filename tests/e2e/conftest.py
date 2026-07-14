"""E2E fixtures — drive the runtime API via boto3 from the deployed stack's outputs.

Requires AWS credentials + a deployed stack (``make deploy``, then ``make e2e``). Not part of the
``make unit``/CI gate — that target only runs ``tests/unit``, so these never fire there.
Guardrails honored: every launched VM has a ``maximumDurationInSeconds`` cap and a
**guaranteed ``terminate_microvm``** in fixture teardown — running VMs are runtime
resources, NOT in the CFN stack, so ``cdk destroy`` alone would never terminate them.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import boto3
import pytest

STACK_NAME = os.environ.get('MICROVM_STACK_NAME', 'LambdaMicrovmSampleStack')
REGION = os.environ.get('MICROVM_REGION', 'us-east-1')
IMAGE_CREATED_TIMEOUT_SECONDS = 20 * 60  # build observed ~165s; leave headroom
VM_RUNNING_TIMEOUT_SECONDS = 5 * 60  # RUNNING observed in ~15s
MAX_VM_DURATION_SECONDS = 900  # hard TTL backstop on every launch


def create_auth_token(client: Any, microvm_id: str, *, allowed_ports: list[dict[str, Any]], expiration_in_minutes: int = 30) -> dict[str, str]:
    """Mint a short-lived JWE token scoped to *allowed_ports* and return the endpoint header map
    (use the value at ``'X-aws-proxy-auth'`` as the header). ``allowedPorts`` entries are the boto3
    ``PortSpecification`` union — e.g. ``{'port': 8080}`` / ``{'range': {'startPort': .., 'endPort': ..}}``."""
    response = client.create_microvm_auth_token(
        microvmIdentifier=microvm_id,
        allowedPorts=allowed_ports,
        expirationInMinutes=expiration_in_minutes,
    )
    return dict(response['authToken'])


@pytest.fixture(scope='session')
def microvm_client() -> Any:
    return boto3.client('lambda-microvms', region_name=REGION)


@pytest.fixture(scope='session')
def stack_outputs() -> dict[str, str]:
    """Read the deployed sample stack's CloudFormation outputs."""
    cloudformation = boto3.client('cloudformation', region_name=REGION)
    stacks = cloudformation.describe_stacks(StackName=STACK_NAME)['Stacks']
    outputs = {entry['OutputKey']: entry['OutputValue'] for entry in stacks[0]['Outputs']}
    required = {'MicrovmImageArn', 'MicrovmExecutionRoleArn', 'IngressConnectorArn', 'VpcEgressConnectorArn', 'MicrovmLogGroupName'}
    missing = required - outputs.keys()
    assert not missing, f'stack {STACK_NAME} is missing outputs: {missing} — deploy with `make deploy` first'
    return outputs


def _wait_for(describe: Any, ready: tuple[str, ...], failed: tuple[str, ...], timeout: int, what: str) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        state_response: dict[str, Any] = describe()
        state = state_response.get('state')
        if state in ready:
            return state_response
        if state in failed:
            raise AssertionError(f'{what} entered {state}: {state_response.get("stateReason", "<no stateReason>")}')
        if time.monotonic() > deadline:
            raise AssertionError(f'{what} did not reach {ready} within {timeout}s (last state: {state})')
        time.sleep(5)


@pytest.fixture(scope='session')
def created_image(microvm_client: Any, stack_outputs: dict[str, str]) -> dict[str, Any]:
    """Poll the image to a runnable state. A fresh image ends at CREATED; a **redeployed** image ends at
    UPDATED (a new active version) — both are runnable, so accept either (the failure states are terminal)."""
    return _wait_for(
        describe=lambda: microvm_client.get_microvm_image(imageIdentifier=stack_outputs['MicrovmImageArn']),
        ready=('CREATED', 'UPDATED'),
        failed=('CREATE_FAILED', 'CREATION_FAILED', 'UPDATE_FAILED', 'DELETE_FAILED', 'DELETION_FAILED', 'DELETED'),
        timeout=IMAGE_CREATED_TIMEOUT_SECONDS,
        what='microvm image build',
    )


@pytest.fixture(scope='session')
def running_microvm(microvm_client: Any, stack_outputs: dict[str, str], created_image: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Launch one MicroVM from stack outputs; ALWAYS terminated in teardown (AWS guardrails)."""
    run = microvm_client.run_microvm(
        imageIdentifier=stack_outputs['MicrovmImageArn'],
        executionRoleArn=stack_outputs['MicrovmExecutionRoleArn'],
        ingressNetworkConnectors=[stack_outputs['IngressConnectorArn']],
        # Route egress through the customer-managed VPC connector (the sample VPC reaches the internet /
        # Bedrock via a NAT gateway), not the AWS-managed INTERNET_EGRESS connector. The image also bakes
        # this connector, so this is the explicit, belt-and-suspenders per-launch selection.
        egressNetworkConnectors=[stack_outputs['VpcEgressConnectorArn']],
        idlePolicy={'autoResumeEnabled': True, 'maxIdleDurationSeconds': 900, 'suspendedDurationSeconds': 300},
        # RUNTIME logs are configured per-launch here (the image's Logging config only covers BUILD logs) —
        # without this, the running VM writes no CloudWatch stream. Stream to the same service-owned group.
        logging={'cloudWatch': {'logGroup': stack_outputs['MicrovmLogGroupName']}},
        maximumDurationInSeconds=MAX_VM_DURATION_SECONDS,
    )
    microvm_id = run['microvmId']
    try:
        ready = _wait_for(
            describe=lambda: microvm_client.get_microvm(microvmIdentifier=microvm_id),
            ready=('RUNNING',),
            failed=('TERMINATED', 'FAILED'),
            timeout=VM_RUNNING_TIMEOUT_SECONDS,
            what=f'microvm {microvm_id}',
        )
        yield ready
    finally:
        microvm_client.terminate_microvm(microvmIdentifier=microvm_id)  # guaranteed cleanup — never leave a VM running


@pytest.fixture()
def auth_headers(microvm_client: Any, running_microvm: dict[str, Any]) -> dict[str, str]:
    """Short-lived JWE token scoped to port 8080 only."""
    return create_auth_token(microvm_client, running_microvm['microvmId'], allowed_ports=[{'port': 8080}])
