"""lambda-microvm-cdk — a reusable AWS CDK construct for AWS Lambda MicroVMs.

The public API is :class:`LambdaMicroVM` (the MicroVM image) and :class:`MicrovmNetworkConnector`
(opt-in VPC egress). They reuse standard CDK types for their inputs (``aws_lambda.Architecture``,
``aws_logs.RetentionDays``, ``aws_s3_assets.Asset``, ``aws_ec2.IVpc``) rather than duplicating them.
Supporting internals live under ``_impl`` and are not a supported API.
"""

from importlib.metadata import PackageNotFoundError, version

from lambda_microvm_cdk.microvm import LambdaMicroVM
from lambda_microvm_cdk.network_connector import MicrovmNetworkConnector

try:
    __version__ = version('lambda-microvm-cdk')
except PackageNotFoundError:  # running from source without an installed distribution
    __version__ = '0.0.0'

__all__ = ['LambdaMicroVM', 'MicrovmNetworkConnector']
