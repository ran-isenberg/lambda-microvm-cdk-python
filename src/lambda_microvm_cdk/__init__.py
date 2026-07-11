"""lambda-microvm-cdk — a reusable AWS CDK construct for AWS Lambda MicroVMs.

The public API is the :class:`LambdaMicroVM` construct. It reuses standard CDK types for its
inputs (``aws_lambda.Architecture``, ``aws_logs.RetentionDays``, ``aws_s3_assets.Asset``) rather
than duplicating them. Supporting internals live under ``_impl`` and are not a supported API.
"""

from lambda_microvm_cdk.microvm import LambdaMicroVM

__version__ = '0.0.0'

__all__ = ['LambdaMicroVM']
