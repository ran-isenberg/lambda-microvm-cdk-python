"""Shared unit-test fixtures. Unit tests make NO AWS calls — the boto3 base-image-version lookup is mocked."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from aws_cdk import App, Environment, Stack

from lambda_microvm_cdk._impl import base_image

sys.path.insert(0, str(Path(__file__).parents[2] / 'sample'))  # make `sample_stack` importable for the sample-stack tests

TEST_ENV = Environment(account='123456789012', region='us-east-1')


@pytest.fixture(autouse=True)
def no_aws_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block the real boto3 lookup in every unit test."""

    def _blocked(region: str, base_image_arn: str) -> str:
        raise RuntimeError('unit tests must not call AWS — mock _fetch_latest_version explicitly')

    monkeypatch.setattr(base_image, '_fetch_latest_version', _blocked)


@pytest.fixture
def mock_version_lookup(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Make the (mocked) boto3 version lookup return a fixed value."""

    def _set(version: str) -> None:
        monkeypatch.setattr(base_image, '_fetch_latest_version', lambda region, arn: version)

    return _set


@pytest.fixture
def app_source_dir(tmp_path: Path) -> str:
    """A minimal MicroVM app source directory (Dockerfile + worker) for asset bundling."""
    app_dir = tmp_path / 'microvm_app'
    app_dir.mkdir()
    (app_dir / 'Dockerfile').write_text('FROM public.ecr.aws/docker/library/python:3.13-slim\nCMD ["python", "worker.py"]\n')
    (app_dir / 'worker.py').write_text('print("hello")\n')
    return str(app_dir)


@pytest.fixture
def stack_factory(tmp_path: Path) -> Iterator[Callable[[], Stack]]:
    """Fresh App+Stack pairs with a concrete env (so the region is resolvable at synth)."""
    counter = 0

    def _make() -> Stack:
        nonlocal counter
        counter += 1
        app = App(outdir=str(tmp_path / f'cdk.out{counter}'))
        return Stack(app, 'TestStack', env=TEST_ENV)

    yield _make
