"""LambdaMicroVM unit tests — resource shape, defaults, version resolution, validation errors. No AWS calls."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from aws_cdk import Stack
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk.assertions import Annotations, Match, Template

from lambda_microvm_cdk import LambdaMicroVM

MICROVM_IMAGE_TYPE = 'AWS::Lambda::MicrovmImage'


def _vm(stack: Stack, source_dir: str, **kwargs: object) -> LambdaMicroVM:
    return LambdaMicroVM(stack, 'Agent', source=source_dir, **kwargs)  # type: ignore[arg-type]


def test_image_resource_created_with_registry_confirmed_props(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, description='test image')
    template = Template.from_stack(stack)

    template.resource_count_is(MICROVM_IMAGE_TYPE, 1)
    template.has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {
            'Description': 'test image',
            'BaseImageVersion': '0',  # blocked lookup -> deterministic fallback
            'CpuConfigurations': [{'Architecture': 'ARM_64'}],
            'Resources': [{'MinimumMemoryInMiB': 2048}],  # default memory_mib (AWS default 2 GB tier)
            'AdditionalOsCapabilities': [],  # least privilege
            'EgressNetworkConnectors': [],
            'EnvironmentVariables': [],
            'Hooks': {},
            # enabled -> CloudWatch pinned to the documented group (empty CloudWatch reads as disabled).
            'Logging': {'CloudWatch': {'LogGroup': Match.string_like_regexp(r'^/aws/lambda/microvms/.+')}},
        },
    )
    # BaseImageArn is partition-token aware (Fn::Join over AWS::Partition) — assert its shape flattened.
    props = next(iter(template.find_resources(MICROVM_IMAGE_TYPE).values()))['Properties']
    base_image_arn = str(props['BaseImageArn'])
    assert 'lambda:us-east-1:aws:microvm-image:al2023-1' in base_image_arn
    assert 'AWS::Partition' in base_image_arn
    # CodeArtifact.Uri points at the zipped S3 asset
    assert 's3://' in str(props['CodeArtifact']['Uri'])
    assert '.zip' in str(props['CodeArtifact']['Uri'])


def test_environment_rendered_as_key_value_pairs(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, environment={'LOG_LEVEL': 'info'})
    Template.from_stack(stack).has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {'EnvironmentVariables': [{'Key': 'LOG_LEVEL', 'Value': 'info'}]},  # registry-confirmed Key/Value (not Name/Value)
    )


def test_memory_capabilities_and_tags(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, memory_mib=2048, os_capabilities=['ALL'], tags={'project': 'lambda-microvm-cdk'})
    Template.from_stack(stack).has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {
            'Resources': [{'MinimumMemoryInMiB': 2048}],
            'AdditionalOsCapabilities': ['ALL'],
            'Tags': [{'Key': 'project', 'Value': 'lambda-microvm-cdk'}],
        },
    )


def test_logging_disabled_variant_is_boolean(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, enable_logging=False)
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'Logging': {'Disabled': True}})


def test_hooks_typed_struct_renders_registry_confirmed_casing(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    hooks = lambda_.CfnMicrovmImage.HooksProperty(
        port=8080,
        microvm_hooks=lambda_.CfnMicrovmImage.MicrovmHooksProperty(run='ENABLED', run_timeout_in_seconds=30),
        microvm_image_hooks=lambda_.CfnMicrovmImage.MicrovmImageHooksProperty(ready='ENABLED'),
    )
    _vm(stack, app_source_dir, hooks=hooks)
    # jsii serialises the typed struct to exact CFN PascalCase (registry-confirmed).
    Template.from_stack(stack).has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {'Hooks': {'Port': 8080, 'MicrovmHooks': {'Run': 'ENABLED', 'RunTimeoutInSeconds': 30}, 'MicrovmImageHooks': {'Ready': 'ENABLED'}}},
    )


def test_pinned_base_image_version_used_verbatim(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, base_image_version='42')
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'BaseImageVersion': '42'})


def test_base_image_version_resolved_via_boto3_lookup(
    stack_factory: Callable[[], Stack], app_source_dir: str, mock_version_lookup: Callable[[str], None]
) -> None:
    mock_version_lookup('7')
    stack = stack_factory()
    _vm(stack, app_source_dir)
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'BaseImageVersion': '7'})


def test_lookup_failure_falls_back_to_zero_with_warning(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir)  # autouse fixture makes the lookup raise
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'BaseImageVersion': '0'})
    Annotations.from_stack(stack).has_warning('*', Match.string_like_regexp('.*Base image version lookup failed.*'))


def test_full_base_image_arn_passes_through(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    custom_arn = 'arn:aws:lambda:us-east-1:aws:microvm-image:custom-base'
    _vm(stack, app_source_dir, base_image=custom_arn, base_image_version='0')
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'BaseImageArn': custom_arn})


def test_derived_name_is_stable_across_synths_and_matches_regex(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    names = [_vm(stack_factory(), app_source_dir).image_name for _ in range(2)]
    assert names[0] == names[1], 'derived Name must be stable (replacement-safe)'
    assert re.match(r'^[a-zA-Z0-9-_]{1,64}$', names[0])


def test_explicit_name_used_and_invalid_name_raises(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, name='my-agent_image')
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'Name': 'my-agent_image'})

    with pytest.raises(ValueError, match='name must match'):
        _vm(stack_factory(), app_source_dir, name='bad name!')


def test_overrides_merge_verbatim_including_unmodeled_props(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, overrides={'Description': 'overridden', 'FutureUnmodeledProp': {'Exact': 'Casing'}})
    Template.from_stack(stack).has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {'Description': 'overridden', 'FutureUnmodeledProp': {'Exact': 'Casing'}},
    )


def test_construct_emits_no_cfn_outputs(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    # A reusable construct exposes typed properties and leaves outputs to the consuming stack — it must
    # not force CfnOutputs onto a consumer's template (the sample stack owns its outputs).
    stack = stack_factory()
    vm = _vm(stack, app_source_dir)
    assert Template.from_stack(stack).to_json().get('Outputs', {}) == {}
    # …the caller still gets everything it needs via properties:
    assert vm.image_arn and vm.execution_role and vm.ingress_connector_arn and vm.log_group_name


def test_connector_properties_use_aws_managed_arns(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    vm = _vm(stack, app_source_dir)
    # partition is a deploy-time token — assert the resolvable parts of the managed connector ARNs
    assert vm.ingress_connector_arn.endswith(':lambda:us-east-1:aws:network-connector:aws-network-connector:ALL_INGRESS')
    assert vm.egress_connector_arn.endswith(':lambda:us-east-1:aws:network-connector:aws-network-connector:INTERNET_EGRESS')


def test_log_group_name_derived_from_image_name(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    vm = _vm(stack, app_source_dir, name='agent-image')
    assert vm.log_group_name == '/aws/lambda/microvms/agent-image'


def test_prezipped_and_prebuilt_asset_sources(stack_factory: Callable[[], Stack], tmp_path: Path) -> None:
    zip_path = tmp_path / 'artifact.zip'
    zip_path.write_bytes(b'PK\x05\x06' + b'\x00' * 18)  # minimal empty zip
    stack = stack_factory()
    LambdaMicroVM(stack, 'FromZip', source=str(zip_path), name='from-zip')

    asset = s3_assets.Asset(stack, 'Prebuilt', path=str(zip_path))
    LambdaMicroVM(stack, 'FromAsset', source=asset, name='from-asset')
    Template.from_stack(stack).resource_count_is(MICROVM_IMAGE_TYPE, 2)


# --- validation errors --------------------------------------------------------


def test_x86_64_rejected_with_clear_error(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    with pytest.raises(ValueError, match='ARM_64 is the only valid value'):
        _vm(stack_factory(), app_source_dir, architecture=lambda_.Architecture.X86_64)


def test_reserved_aws_region_env_key_rejected(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    with pytest.raises(ValueError, match='reserved'):
        _vm(stack_factory(), app_source_dir, environment={'AWS_REGION': 'us-east-1'})


def test_env_keys_are_not_secret_filtered(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    # No secret-name heuristic — any valid key is accepted (can't detect secrets reliably; it's guidance only).
    stack = stack_factory()
    _vm(stack, app_source_dir, environment={'MY_API_KEY': 'x', 'MAX_TOKENS': '1024'})
    Template.from_stack(stack).has_resource_properties(
        MICROVM_IMAGE_TYPE,
        {'EnvironmentVariables': Match.array_with([{'Key': 'MY_API_KEY', 'Value': 'x'}])},
    )


def test_too_many_env_vars_rejected(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    with pytest.raises(ValueError, match='at most 50'):
        _vm(stack_factory(), app_source_dir, environment={f'KEY_{i}': 'v' for i in range(51)})


def test_too_many_egress_connectors_rejected(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    with pytest.raises(ValueError, match='at most 10'):
        _vm(stack_factory(), app_source_dir, egress_connectors=[f'arn:aws:lambda:us-east-1:111122223333:network-connector:c{i}' for i in range(11)])


def test_literal_egress_connector_arns_validated_and_rendered(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = stack_factory()
    arns = [
        'arn:aws:lambda:us-east-1:111122223333:network-connector:nc-af10c36f-8bc1-4ecf-98fb-1726926ae577',  # customer
        'arn:aws:lambda:us-east-1:aws:network-connector:aws-network-connector:INTERNET_EGRESS',  # managed
    ]
    _vm(stack, app_source_dir, egress_connectors=arns)
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'EgressNetworkConnectors': arns})


@pytest.mark.parametrize(
    'bad',
    [
        'nc-af10c36f',
        'arn:aws:s3:::bucket/obj',
        'arn:aws:lambda:us-east-1:111122223333:function:foo',
        'arn:aws:lambda:us-east-1:111122223333:function:my-network-connector-fn',  # 'network-connector' in the name, not the resource type
    ],
)
def test_invalid_literal_egress_connector_arn_rejected(stack_factory: Callable[[], Stack], app_source_dir: str, bad: str) -> None:
    with pytest.raises(ValueError, match='not a Lambda network-connector ARN'):
        _vm(stack_factory(), app_source_dir, egress_connectors=[bad])


def test_deploy_time_token_egress_connector_arn_is_not_validated(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    from aws_cdk import Fn

    stack = stack_factory()
    # A deploy-time token (e.g. MicrovmNetworkConnector.connector_arn is an Fn::GetAtt) has no value at
    # synth, so validation skips it — synth must succeed rather than reject the unresolved string.
    _vm(stack, app_source_dir, egress_connectors=[Fn.import_value('SomeConnectorArn')])
    Template.from_stack(stack).resource_count_is(MICROVM_IMAGE_TYPE, 1)


def test_egress_connectors_accepts_connector_object(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    from aws_cdk import aws_ec2 as ec2

    from lambda_microvm_cdk import MicrovmNetworkConnector

    stack = stack_factory()
    connector = MicrovmNetworkConnector(stack, 'Egress', vpc=ec2.Vpc(stack, 'Vpc', max_azs=2))
    _vm(stack, app_source_dir, egress_connectors=[connector])  # object, not ARN string
    image = next(iter(Template.from_stack(stack).find_resources(MICROVM_IMAGE_TYPE).values()))
    assert 'Fn::GetAtt' in str(image['Properties']['EgressNetworkConnectors']), 'connector object must coerce to its ARN token'


def test_invalid_memory_and_capabilities_rejected(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    with pytest.raises(ValueError, match='documented baseline tiers'):
        _vm(stack_factory(), app_source_dir, memory_mib=0)
    with pytest.raises(ValueError, match='documented baseline tiers'):
        _vm(stack_factory(), app_source_dir, memory_mib=3000)  # between valid tiers — API would reject at deploy
    with pytest.raises(ValueError, match='unknown os_capabilities'):
        _vm(stack_factory(), app_source_dir, os_capabilities=['ROOT'])


@pytest.mark.parametrize('mib', [512, 1024, 2048, 4096, 8192])
def test_all_documented_memory_tiers_accepted(stack_factory: Callable[[], Stack], app_source_dir: str, mib: int) -> None:
    stack = stack_factory()
    _vm(stack, app_source_dir, memory_mib=mib)
    Template.from_stack(stack).has_resource_properties(MICROVM_IMAGE_TYPE, {'Resources': [{'MinimumMemoryInMiB': mib}]})


def test_source_without_dockerfile_or_zip_rejected(stack_factory: Callable[[], Stack], tmp_path: Path) -> None:
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(ValueError, match='must contain a Dockerfile'):
        LambdaMicroVM(stack_factory(), 'NoDockerfile', source=str(empty))
    not_zip = tmp_path / 'artifact.tar'
    not_zip.write_text('x')
    with pytest.raises(ValueError, match='directory with a Dockerfile'):
        LambdaMicroVM(stack_factory(), 'NotZip', source=str(not_zip))
