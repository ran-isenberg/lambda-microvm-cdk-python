"""Sample stack unit tests — outputs contract, Bedrock least-privilege, cdk-nag clean. No AWS calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aws_cdk import App, Aspects, Environment
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks
from sample_stack import SampleStack

TEST_ENV = Environment(account='123456789012', region='us-east-1')


def _synth(tmp_path: Path, *, with_nag: bool = False) -> Template:
    app = App(outdir=str(tmp_path / 'cdk.out'))
    stack = SampleStack(app, 'LambdaMicrovmSampleStack', env=TEST_ENV)
    if with_nag:
        Aspects.of(stack).add(AwsSolutionsChecks(verbose=True))
        Annotations.from_stack(stack).has_no_error('*', Match.string_like_regexp('AwsSolutions-.*'))
    return Template.from_stack(stack)


def test_sample_image_props(tmp_path: Path) -> None:
    template = _synth(tmp_path)
    template.resource_count_is('AWS::Lambda::MicrovmImage', 1)
    template.has_resource_properties(
        'AWS::Lambda::MicrovmImage',
        {
            'Name': 'lambda-microvm-cdk-sample',
            'Resources': [{'MinimumMemoryInMiB': 2048}],
            'CpuConfigurations': [{'Architecture': 'ARM_64'}],
            'AdditionalOsCapabilities': [],  # the sample installs at build time — no ALL needed
            'EnvironmentVariables': Match.array_with([{'Key': 'LOG_LEVEL', 'Value': 'info'}]),  # model env lives in the Dockerfile
            'Logging': {'CloudWatch': {}},
        },
    )


def test_stack_outputs_use_the_exact_keys_the_e2e_fixture_reads(tmp_path: Path) -> None:
    outputs = _synth(tmp_path).to_json().get('Outputs', {})
    for key in ('MicrovmImageArn', 'MicrovmImageName', 'MicrovmExecutionRoleArn', 'IngressConnectorArn', 'EgressConnectorArn', 'MicrovmLogGroupName'):
        assert key in outputs, f'missing stack output {key} (E2E fixture contract)'


def test_execution_role_grants_both_model_providers_scoped(tmp_path: Path) -> None:
    # Default Nova path -> bedrock:InvokeModel on the profile + region-wildcard foundation model
    # (INFERENCE_PROFILE-only); opt-in Opus path -> bedrock-mantle:CreateInference on the project.
    template = _synth(tmp_path)
    roles = template.find_resources(
        'AWS::IAM::Role', {'Properties': {'Description': 'Least-privilege execution role assumed by the running MicroVM'}}
    )
    assert len(roles) == 1
    statements: list[dict[str, Any]] = []
    for policy in template.find_resources('AWS::IAM::Policy').values():
        statements.extend(policy['Properties']['PolicyDocument']['Statement'])

    nova = next(s for s in statements if 'bedrock:InvokeModel' in json.dumps(s['Action']))
    nova_res = json.dumps(nova['Resource'])
    assert 'inference-profile/us.amazon.nova-2-lite-v1:0' in nova_res
    assert 'foundation-model/amazon.nova-2-lite-v1:0' in nova_res
    resources = nova['Resource'] if isinstance(nova['Resource'], list) else [nova['Resource']]
    assert all(r != '*' for r in resources), 'no wildcard-only Bedrock access'

    opus = next(s for s in statements if 'bedrock-mantle:CreateInference' in json.dumps(s['Action']))
    opus_res = json.dumps(opus['Resource'])
    assert 'bedrock-mantle' in opus_res and 'project/default' in opus_res and '*' not in opus_res


def test_no_unsuppressed_aws_solutions_errors_on_the_sample_stack(tmp_path: Path) -> None:
    _synth(tmp_path, with_nag=True)
