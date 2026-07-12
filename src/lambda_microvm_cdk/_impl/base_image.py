"""Base image alias→ARN resolution and the boto3 base-image-version lookup.

Resolution order for ``base_image_version``:
1. Explicit pin passed by the user → used verbatim.
2. Live boto3 ``list_managed_microvm_image_versions`` lookup (latest active version).
3. On any failure (no creds / offline / unresolved region) → fall back to ``"0"`` with a
   CDK warning annotation. Synth never hard-fails.

No ``cdk.context.json`` caching — every synth without a pin does a live lookup (or falls back).
Pin ``base_image_version`` for deterministic, offline CI.
"""

from __future__ import annotations

from typing import Any

import boto3
from aws_cdk import Annotations, Stack, Token
from constructs import Construct

FALLBACK_BASE_IMAGE_VERSION = '0'


def resolve_base_image_arn(scope: Construct, base_image: str) -> str:
    """Resolve a short alias (e.g. ``al2023-1``) to the AWS-managed base image ARN; full ARNs pass through.

    Uses the partition *token* so the template stays partition-portable.
    """
    if base_image.startswith('arn:'):
        return base_image
    stack = Stack.of(scope)
    return f'arn:{stack.partition}:lambda:{stack.region}:aws:microvm-image:{base_image}'


def _partition_for_region(region: str) -> str:
    """Concrete partition for a concrete region (the token partition can't be used in a boto3 call)."""
    if region.startswith('us-gov-'):
        return 'aws-us-gov'
    if region.startswith('cn-'):
        return 'aws-cn'
    return 'aws'


def resolve_base_image_version(scope: Construct, base_image: str, pinned: str | None) -> str:
    """Resolve the base image version (pin → boto3 → ``"0"`` fallback).

    *base_image* is the raw user input (alias or full ARN) — a concrete lookup ARN is derived
    from it, independent of the token-bearing ARN wired into the template.
    """
    if pinned is not None:
        return pinned

    stack = Stack.of(scope)
    region = stack.region
    if Token.is_unresolved(region) or Token.is_unresolved(base_image):
        Annotations.of(scope).add_warning(
            f'Base image version lookup skipped (region/base image unresolved at synth); falling back to "{FALLBACK_BASE_IMAGE_VERSION}". '
            'Set an explicit env on the Stack or pin base_image_version.'
        )
        return FALLBACK_BASE_IMAGE_VERSION

    if base_image.startswith('arn:'):
        lookup_arn = base_image
    else:
        lookup_arn = f'arn:{_partition_for_region(region)}:lambda:{region}:aws:microvm-image:{base_image}'

    try:
        return _fetch_latest_version(region, lookup_arn)
    except Exception as exc:  # noqa: B902 — deliberate broad catch: synth must never hard-fail on lookup
        Annotations.of(scope).add_warning(
            f'Base image version lookup failed ({exc.__class__.__name__}: {exc}); falling back to "{FALLBACK_BASE_IMAGE_VERSION}". '
            'Pin base_image_version to silence this.'
        )
        return FALLBACK_BASE_IMAGE_VERSION


def _fetch_latest_version(region: str, base_image_arn: str) -> str:
    """Fetch the latest active managed base-image version via boto3 (today the only value is ``"0"``)."""
    client = boto3.client('lambda-microvms', region_name=region)
    response: dict[str, Any] = client.list_managed_microvm_image_versions(imageIdentifier=base_image_arn)
    versions = _extract_versions(response)
    if not versions:
        return FALLBACK_BASE_IMAGE_VERSION
    return max(versions, key=_version_sort_key)


def _extract_versions(response: dict[str, Any]) -> list[str]:
    """Pull version strings out of the list response, defensively (prefer ACTIVE entries when state is present)."""
    items: list[dict[str, Any]] = []
    for value in response.values():
        if isinstance(value, list):
            items = [item for item in value if isinstance(item, dict)]
            break
    versions: list[str] = []
    for item in items:
        state = item.get('state')
        if isinstance(state, str) and state not in ('ACTIVE', 'CREATED'):
            continue
        for key in ('imageVersion', 'version', 'baseImageVersion'):
            version = item.get(key)
            if isinstance(version, str) and version:
                versions.append(version)
                break
    return versions


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Sort dotted numeric versions sensibly; non-numeric parts sort as 0."""
    return tuple(int(part) if part.isdigit() else 0 for part in version.split('.'))
