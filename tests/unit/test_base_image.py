"""Base-image version lookup internals — response parsing and version ordering. No AWS calls."""

from __future__ import annotations

# Bind the real functions at import time (the autouse fixture patches the module attributes afterwards).
from lambda_microvm_cdk._impl.base_image import _extract_versions, _version_sort_key


def test_extract_versions_from_realistic_response() -> None:
    response = {'managedMicrovmImageVersions': [{'imageVersion': '0', 'state': 'ACTIVE'}], 'nextToken': None}
    assert _extract_versions(response) == ['0']


def test_extract_versions_skips_failed_states() -> None:
    response = {'versions': [{'imageVersion': '1.0', 'state': 'ACTIVE'}, {'imageVersion': '2.0', 'state': 'CREATE_FAILED'}]}
    assert _extract_versions(response) == ['1.0']


def test_extract_versions_handles_alternate_keys_and_missing_state() -> None:
    assert _extract_versions({'items': [{'version': '3'}]}) == ['3']
    assert _extract_versions({'items': []}) == []
    assert _extract_versions({}) == []


def test_version_sort_key_orders_dotted_versions_numerically() -> None:
    versions = ['1.9', '1.10', '0', '1.2']
    assert max(versions, key=_version_sort_key) == '1.10'
