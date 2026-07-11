"""lambda-microvm-cdk — reusable AWS CDK constructs for AWS Lambda MicroVMs.

Only constructs and their public prop/enum types are exported from this package
root. All implementation and helper modules are private under ``_impl`` and are
not part of the supported public API. See SPEC.md for the full surface.

Public API (implemented incrementally per phases):
    Phase 1: MicrovmImage, MicrovmSource, Architecture, MicrovmSize,
             LoggingConfig, OsCapability
    Phase 3: MicrovmLauncher, IngressConnector, EgressConnector, IdlePolicy
"""

__version__ = "0.0.0"

# Public exports are re-exported from _impl as each phase lands, e.g.:
#     from lambda_microvm_cdk._impl.image import MicrovmImage
# Keep this list as the single source of truth for the public API.
__all__: list[str] = []
