"""LambdaMicroVM — the public construct of this library. Emits ``AWS::Lambda::MicrovmImage`` (SPEC.md §3, §4)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from aws_cdk import CfnTag, Names, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3_assets as s3_assets
from constructs import Construct

from lambda_microvm_cdk._impl import security
from lambda_microvm_cdk._impl.base_image import resolve_base_image_arn, resolve_base_image_version

_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9-_]{1,64}$')
_VALID_OS_CAPABILITIES = frozenset({'ALL'})
# Documented baseline memory tiers (MiB) — the API/CFN schema types this as an open integer, but
# only these five sizes are supported (2 GB default; docs "MicroVM sizing"). overrides['Resources'] bypasses.
_VALID_MEMORY_MIB = (512, 1024, 2048, 4096, 8192)
_MAX_ENVIRONMENT_VARIABLES = 50
_MAX_ENV_KEY_LENGTH = 256
_MAX_ENV_VALUE_LENGTH = 4096
_MAX_EGRESS_CONNECTORS = 10
_RESERVED_ENV_KEYS = frozenset({'AWS_REGION'})
# Whole-segment matching (split on '_') so legit config like MAX_TOKENS is not flagged.
_SECRET_LIKE_SEGMENTS = frozenset({'SECRET', 'SECRETS', 'TOKEN', 'PASSWORD', 'PASSWD', 'APIKEY', 'CREDENTIAL', 'CREDENTIALS'})
_SECRET_LIKE_SEGMENT_PAIRS = frozenset({('API', 'KEY'), ('PRIVATE', 'KEY'), ('ACCESS', 'KEY'), ('AUTH', 'TOKEN')})


class LambdaMicroVM(Construct):
    """Provisions an AWS Lambda MicroVM image with secure defaults, ready for ``run_microvm``.

    Zips + uploads the source (CDK S3 asset), creates least-privilege build and VM-execution
    roles (unless supplied), resolves the managed base-image version via a cached boto3 lookup,
    and emits the registry-confirmed ``AWS::Lambda::MicrovmImage``. Everything a runtime caller /
    E2E fixture needs is exposed as typed **properties** (``image_arn``, ``execution_role``,
    ``ingress_connector_arn``, …) — the consuming stack decides which to surface as ``CfnOutput``s
    (see ``sample/sample_stack.py``), so the construct never forces outputs onto a consumer's
    template. Running a MicroVM is a runtime API call (not CloudFormation) — wire these properties
    into ``run_microvm`` (SPEC.md §4.2).

    Args:
        source: Where the image code artifact comes from — a path to a directory containing a
            ``Dockerfile`` (zipped automatically), a path to a prebuilt ``.zip``, or an existing
            ``aws_s3_assets.Asset``. For artifacts already in S3, use ``overrides['CodeArtifact']``.
        name: Explicit image name (``^[a-zA-Z0-9-_]{1,64}$``). Default: a stable name derived from
            the construct path — stable so code changes create a new image *version* instead of
            replacing the image. Changing the name forces replacement (it is the only create-only prop).
        description: Human-readable description of the image (CFN requires the property; may be ``''``).
        base_image: AWS-managed base image — a short alias (``'al2023-1'``, the only managed image
            today) or a full base-image ARN.
        base_image_version: Pin for the base image version. Default ``None`` resolves the latest
            active version via a live boto3 lookup on every synth; falls back to ``'0'`` with a
            synth warning when offline. Pin this for deterministic, offline CI (SPEC.md §7).
        architecture: CPU architecture, reusing ``aws_lambda.Architecture``. ``ARM_64`` is the
            default and the only value the service accepts today — anything else raises (SPEC.md §0).
        memory_mib: Baseline memory size in MiB (``Resources[].MinimumMemoryInMiB``); vCPU scales with it
            and it auto-scales up to 4× at peak. One of the five documented tiers ``512 | 1024 | 2048 |
            4096 | 8192`` — anything else raises (the API accepts only these, though the CFN schema types
            it as an open int). Default ``2048`` (2 GB / 1 vCPU, AWS's documented default).
        os_capabilities: Additional OS capabilities. Only ``'ALL'`` exists and it is a documented
            privilege escalation — default is none (least privilege).
        environment: Env vars baked into the image at build time (max 50). **Snapshotted and shared
            across every VM from this image — never secrets**; secret-looking keys raise. ``AWS_REGION``
            is reserved (the runtime injects it) and raises (SPEC.md §5.3, §0).
        egress_connectors: Network-connector ARNs baked into the image (max 10). Usually left empty —
            connectors are normally chosen per-launch in ``run_microvm``.
        enable_logging: ``True`` (default) streams build + runtime logs to CloudWatch; ``False``
            disables logging entirely (not recommended — CloudWatch is the auditable default).
        hooks: Typed lifecycle hooks (``aws_lambda.CfnMicrovmImage.HooksProperty``, nesting
            ``MicrovmHooksProperty`` / ``MicrovmImageHooksProperty``: ``port``, ``run``/``resume``/
            ``suspend``/``terminate``, ``ready``/``validate`` — each ``'ENABLED'``/``'DISABLED'`` plus a
            ``…_timeout_in_seconds``). Default ``None`` → ``{}``: all lifecycle hooks disabled, traffic
            flows immediately. Un-modeled corners stay reachable via ``overrides['Hooks']``.
        build_role: BYO IAM role the MicroVM service assumes to build the image. Default: a
            least-privilege role scoped to the exact S3 asset object + the image's log group.
        execution_role: BYO IAM role assumed by the *running* VM. Default: a least-privilege role
            with runtime-logs permissions only; add workload permissions (e.g. Bedrock) on top.
        log_retention: Retention applied to the service-owned log group (which this construct
            deliberately does not create — the service owns it, SPEC.md §5.6). ``None`` skips the
            retention resource. Default one month.
        removal_policy: What happens to the image when the resource is removed. Default ``DESTROY``
            (dev/sample posture) — set ``RETAIN`` for images that must survive stack deletion.
        tags: Resource tags for cost allocation.
        overrides: Escape hatch — merged verbatim into the L1 ``Properties`` using exact CFN
            casing, so no consumer is ever blocked on an un-modeled field (SPEC.md §4.3).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        source: str | s3_assets.Asset,
        name: str | None = None,
        description: str = '',
        base_image: str = 'al2023-1',
        base_image_version: str | None = None,
        architecture: lambda_.Architecture = lambda_.Architecture.ARM_64,
        memory_mib: int = 2048,
        os_capabilities: list[Literal['ALL']] | None = None,
        environment: dict[str, str] | None = None,
        egress_connectors: list[str] | None = None,
        enable_logging: bool = True,
        hooks: lambda_.CfnMicrovmImage.HooksProperty | None = None,
        build_role: iam.IRole | None = None,
        execution_role: iam.IRole | None = None,
        log_retention: logs.RetentionDays | None = logs.RetentionDays.TWO_WEEKS,
        removal_policy: RemovalPolicy = RemovalPolicy.DESTROY,
        tags: dict[str, str] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        environment = dict(environment or {})
        os_capabilities = list(os_capabilities or [])
        egress_connectors = list(egress_connectors or [])

        self._validate_architecture(architecture)
        self._validate_environment(environment)
        if memory_mib not in _VALID_MEMORY_MIB:
            raise ValueError(
                f'memory_mib must be one of the documented baseline tiers {_VALID_MEMORY_MIB} (MiB), got {memory_mib}. '
                "For an un-listed size, bypass via overrides={'Resources': [{'MinimumMemoryInMiB': ...}]}."
            )
        if invalid := set(os_capabilities) - _VALID_OS_CAPABILITIES:
            raise ValueError(f'unknown os_capabilities {sorted(invalid)} — only {sorted(_VALID_OS_CAPABILITIES)} exist today')
        if len(egress_connectors) > _MAX_EGRESS_CONNECTORS:
            raise ValueError(f'egress_connectors supports at most {_MAX_EGRESS_CONNECTORS} entries, got {len(egress_connectors)}')

        self._name = self._resolve_name(name)
        self._log_group_name = f'/aws/lambda/microvms/{self._name}'
        group_arn = security.log_group_arn(self, self._log_group_name)

        asset = self._resolve_source(source)
        artifact_object_arn = asset.bucket.arn_for_objects(asset.s3_object_key)
        self._build_role = build_role or security.build_image_build_role(
            self, 'BuildRole', artifact_object_arn=artifact_object_arn, group_arn=group_arn
        )
        self._execution_role = execution_role or security.build_vm_execution_role(self, 'ExecutionRole', group_arn=group_arn)

        # Logging: enabled -> CloudWatch with an explicit log group. An *empty* `CloudWatch: {}` is treated
        # as disabled by the service (console shows "logging disabled", no build/runtime streams — verified
        # against a deployed image), so pin the documented group /aws/lambda/microvms/<name> (the same group
        # the build + exec roles are scoped to and LogRetention manages). Disabled -> Disabled: true.
        logging = (
            lambda_.CfnMicrovmImage.LoggingProperty(cloud_watch=lambda_.CfnMicrovmImage.CloudWatchLoggingProperty(log_group=self._log_group_name))
            if enable_logging
            else lambda_.CfnMicrovmImage.LoggingProperty(disabled=True)
        )
        self._resource = lambda_.CfnMicrovmImage(
            self,
            'Resource',
            name=self._name,
            description=description,
            base_image_arn=resolve_base_image_arn(self, base_image),
            base_image_version=resolve_base_image_version(self, base_image, base_image_version),
            build_role_arn=self._build_role.role_arn,
            code_artifact=lambda_.CfnMicrovmImage.CodeArtifactProperty(uri=asset.s3_object_url),
            cpu_configurations=[lambda_.CfnMicrovmImage.CpuConfigurationProperty(architecture='ARM_64')],  # only value the service accepts today
            resources=[lambda_.CfnMicrovmImage.ResourcesProperty(minimum_memory_in_mib=memory_mib)],
            additional_os_capabilities=os_capabilities,
            egress_network_connectors=egress_connectors,
            environment_variables=[lambda_.CfnMicrovmImage.EnvironmentVariableProperty(key=key, value=value) for key, value in environment.items()],
            hooks=hooks or lambda_.CfnMicrovmImage.HooksProperty(),  # default {} = all lifecycle hooks disabled
            logging=logging,
            tags=[CfnTag(key=key, value=value) for key, value in tags.items()] if tags else None,
        )
        # Escape hatch: set/replace top-level L1 Properties verbatim, exact CFN casing (SPEC.md §4.3).
        for key, value in (overrides or {}).items():
            self._resource.add_property_override(key, value)
        self._resource.apply_removal_policy(removal_policy)
        for role in (self._build_role, self._execution_role):
            self._resource.node.add_dependency(role)

        if log_retention is not None:
            # The service creates and OWNS the log group; LogRetention only sets its retention
            # policy without owning it (avoids the "already exists" clash, SPEC.md §5.6).
            logs.LogRetention(self, 'LogRetention', log_group_name=self._log_group_name, retention=log_retention)

    # --- public surface -------------------------------------------------------

    @property
    def image_arn(self) -> str:
        """``Fn::GetAtt ImageArn`` (deploy-time token)."""
        return self._resource.attr_image_arn

    @property
    def state(self) -> str:
        """``Fn::GetAtt State`` (deploy-time token)."""
        return self._resource.attr_state

    @property
    def latest_active_image_version(self) -> str:
        """``Fn::GetAtt LatestActiveImageVersion`` (deploy-time token)."""
        return self._resource.attr_latest_active_image_version

    @property
    def image_name(self) -> str:
        """The resolved ``Name`` (stable across synths; changing it forces replacement)."""
        return self._name

    @property
    def log_group_name(self) -> str:
        """Derived, service-owned log group name (``/aws/lambda/microvms/<image-name>``)."""
        return self._log_group_name

    @property
    def build_role(self) -> iam.IRole:
        """The build role actually used (created least-privilege unless supplied)."""
        return self._build_role

    @property
    def execution_role(self) -> iam.IRole:
        """The VM execution role actually used (created least-privilege unless supplied)."""
        return self._execution_role

    @property
    def ingress_connector_arn(self) -> str:
        """AWS-managed ``ALL_INGRESS`` connector ARN (each VM gets a unique TLS endpoint)."""
        return self._managed_connector_arn('ALL_INGRESS')

    @property
    def egress_connector_arn(self) -> str:
        """AWS-managed ``INTERNET_EGRESS`` connector ARN (the default egress)."""
        return self._managed_connector_arn('INTERNET_EGRESS')

    def grant_run(self, grantee: iam.IGrantable) -> None:
        """Attach least-privilege runtime-caller permissions to *grantee* — ``lambda:RunMicrovm``
        scoped to this image, VM lifecycle + auth-token actions scoped to this account/region,
        and ``iam:PassRole`` limited to the VM execution role (SPEC.md §5.1)."""
        security.grant_run(self, grantee, image_arn=self.image_arn, execution_role=self._execution_role)

    # --- private helpers ------------------------------------------------------

    def _managed_connector_arn(self, connector: str) -> str:
        stack = Stack.of(self)
        return f'arn:{stack.partition}:lambda:{stack.region}:aws:network-connector:aws-network-connector:{connector}'

    def _resolve_source(self, source: str | s3_assets.Asset) -> s3_assets.Asset:
        if isinstance(source, s3_assets.Asset):
            return source
        path = Path(source)
        if path.is_dir():
            if not (path / 'Dockerfile').is_file():
                raise ValueError(f'source directory must contain a Dockerfile: {source}')
        elif not (path.is_file() and path.suffix == '.zip'):
            raise ValueError(f'source must be a directory with a Dockerfile, a .zip file, or an s3_assets.Asset — got: {source}')
        return s3_assets.Asset(self, 'Source', path=str(path))

    def _resolve_name(self, name: str | None) -> str:
        if name is None:
            # Stable, path-derived (NOT asset-hash-derived) so code changes update the image
            # in place (new version) instead of replacing it (SPEC.md §4.4).
            return Names.unique_resource_name(self, max_length=64, allowed_special_characters='-_')
        if not _NAME_PATTERN.match(name):
            raise ValueError(f'name must match ^[a-zA-Z0-9-_]{{1,64}}$ (changing it forces replacement), got: {name!r}')
        return name

    @staticmethod
    def _validate_architecture(architecture: lambda_.Architecture) -> None:
        if architecture.name != lambda_.Architecture.ARM_64.name:
            raise ValueError(
                f'architecture {architecture.name!r} is not accepted by the MicroVM API today — '
                'ARM_64 is the only valid value (the service enum rejects X86_64; SPEC.md §0).'
            )

    @staticmethod
    def _validate_environment(environment: dict[str, str]) -> None:
        if len(environment) > _MAX_ENVIRONMENT_VARIABLES:
            raise ValueError(f'environment supports at most {_MAX_ENVIRONMENT_VARIABLES} variables, got {len(environment)}')
        for key, value in environment.items():
            if key in _RESERVED_ENV_KEYS:
                raise ValueError(f'environment key {key!r} is reserved — the MicroVM runtime injects it (CreateMicrovmImage rejects it; SPEC.md §0)')
            if not key or len(key) > _MAX_ENV_KEY_LENGTH or any(ch.isspace() for ch in key):
                raise ValueError(f'environment key {key!r} must be 1-{_MAX_ENV_KEY_LENGTH} chars with no whitespace')
            if len(value) > _MAX_ENV_VALUE_LENGTH:
                raise ValueError(f'environment value for {key!r} exceeds {_MAX_ENV_VALUE_LENGTH} chars')
            segments = key.upper().split('_')
            adjacent_pairs = set(zip(segments, segments[1:], strict=False))
            if _SECRET_LIKE_SEGMENTS.intersection(segments) or _SECRET_LIKE_SEGMENT_PAIRS.intersection(adjacent_pairs):
                raise ValueError(
                    f'environment key {key!r} looks like a secret — image EnvironmentVariables are snapshotted and shared '
                    'across every VM from this image. Pass secret references via runHookPayload or fetch from SSM/Secrets '
                    'Manager at runtime instead (SPEC.md §5.3).'
                )
