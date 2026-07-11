"""Phase 1 exit gate — a minimal internal stack synths green with cdk-nag AwsSolutionsChecks (no AWS calls)."""

from __future__ import annotations

from collections.abc import Callable

from aws_cdk import Aspects, Stack
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks, NagSuppressions
from constructs import IConstruct

from lambda_microvm_cdk import LambdaMicroVM


def apply_standard_nag_suppressions(stack: Stack, image: LambdaMicroVM) -> None:
    """Targeted, justified suppressions for findings inherent to the MicroVM log model — never blanket."""
    NagSuppressions.add_resource_suppressions(
        image.build_role,
        [
            {
                'id': 'AwsSolutions-IAM5',
                'reason': 'Log streams inside the image-scoped log group are created dynamically by the service '
                '(build id / microvmId), so logs:* must target <group-arn>:*. The group itself is exact.',
            }
        ],
        apply_to_children=True,
    )
    NagSuppressions.add_resource_suppressions(
        image.execution_role,
        [
            {
                'id': 'AwsSolutions-IAM5',
                'reason': 'Runtime log streams are named by microvmId at run time — scoped to the image log group only.',
            }
        ],
        apply_to_children=True,
    )
    log_retention_singletons: list[IConstruct] = [child for child in stack.node.children if child.node.id.startswith('LogRetention')]
    for singleton in log_retention_singletons:
        NagSuppressions.add_resource_suppressions(
            singleton,
            [
                {
                    'id': 'AwsSolutions-IAM4',
                    'reason': 'CDK-managed LogRetention singleton provider uses AWSLambdaBasicExecutionRole (framework-owned).',
                },
                {
                    'id': 'AwsSolutions-IAM5',
                    'reason': 'CDK-managed LogRetention provider sets retention on log groups created later (framework-owned).',
                },
            ],
            apply_to_children=True,
        )


def _minimal_stack(stack_factory: Callable[[], Stack], source_dir: str) -> Stack:
    stack = stack_factory()
    image = LambdaMicroVM(
        stack,
        'MinimalImage',
        source=source_dir,
        name='minimal-image',
        description='Phase 1 exit gate — minimal internal stack',
    )
    Aspects.of(stack).add(AwsSolutionsChecks(verbose=True))
    apply_standard_nag_suppressions(stack, image)
    return stack


def test_minimal_stack_synthesizes_with_the_image_resource(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = _minimal_stack(stack_factory, app_source_dir)
    template = Template.from_stack(stack)
    template.resource_count_is('AWS::Lambda::MicrovmImage', 1)
    template.resource_count_is('AWS::IAM::Role', 3)  # build + execution + LogRetention provider


def test_no_unsuppressed_aws_solutions_errors(stack_factory: Callable[[], Stack], app_source_dir: str) -> None:
    stack = _minimal_stack(stack_factory, app_source_dir)
    Annotations.from_stack(stack).has_no_error('*', Match.string_like_regexp('AwsSolutions-.*'))
