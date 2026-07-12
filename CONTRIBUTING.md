<!-- markdownlint-disable MD043 MD041 -->
# Contributing Guidelines <!-- omit in toc -->

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs/Feature Requests](#reporting-bugsfeature-requests)
- [Contributing via Pull Requests](#contributing-via-pull-requests)
  - [Dev setup](#dev-setup)
- [Security issue notifications](#security-issue-notifications)
- [Licensing](#licensing)

Thank you for your interest in contributing to **lambda-microvm-cdk**. Whether it's a bug report, new
feature, correction, or additional documentation, we greatly value feedback and contributions from
our community.

## Code of Conduct

This project has adopted a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected
to uphold it. Please report unacceptable behavior to the contact listed there.

Please read through this document before submitting any issues or pull requests to ensure we have all
the necessary information to effectively respond to your bug report or contribution.

## Reporting Bugs/Feature Requests

We welcome you to use the GitHub [issue tracker](https://github.com/ran-isenberg/lambda-microvm-cdk-python/issues)
to report bugs, suggest features, or documentation improvements.

When filing an issue, please check existing open, or recently closed, issues to make sure somebody
else hasn't already reported the issue. Please try to include as much information as you can, such as:

- A reproducible test case or series of steps.
- The version of the library, Python, and AWS CDK you are using.
- Anything unusual about your environment or deployment.

## Contributing via Pull Requests

Contributions via pull requests are much appreciated. Before sending us a pull request, please ensure that:

1. You are working against the latest source on the **main** branch.
2. You check existing open, and recently merged, pull requests to make sure someone else hasn't
   addressed the problem already.
3. You open an [issue](https://github.com/ran-isenberg/lambda-microvm-cdk-python/issues) before you
   begin any significant implementation. We value your time and bandwidth — a PR against a
   non-triaged issue might not be successful.

### Dev setup

Firstly, [fork the repository](https://github.com/ran-isenberg/lambda-microvm-cdk-python/fork).

This project uses [uv](https://docs.astral.sh/uv/) and the AWS CDK CLI via `npx`. Run `make dev`
inside your clone to create the virtual environment and install all dependencies. The
[Contributing guide in the docs](https://ran-isenberg.github.io/lambda-microvm-cdk-python/contributing/)
covers prerequisites and the full development loop.

To send us a pull request, please follow these steps:

1. Create a branch focused on the specific change you are contributing, e.g. `feature/network-connector`.
2. Make your change. **Every change to the construct or sample must ship with a test** under
   `tests/unit/` (see [the testing conventions](https://ran-isenberg.github.io/lambda-microvm-cdk-python/contributing/)).
3. Run the full pre-merge gate locally: `make pr` (format + lint + unit tests + `cdk synth` incl.
   cdk-nag). The same checks run in CI.
4. Commit using clear messages. **Commit messages and PR titles use the `feature | fix | docs | chore`
   prefix** (e.g. `feature: add NetworkConnector construct`) — this is validated in CI and drives the
   PR labeler and release notes.
5. Push to your fork and open a pull request; then wait for feedback. We aim to respond within a few
   days — please be patient.

GitHub provides additional documentation on [forking a repository](https://help.github.com/articles/fork-a-repo/)
and [creating a pull request](https://help.github.com/articles/creating-a-pull-request/).

## Security issue notifications

If you discover a potential security issue, please **do not** open a public issue. Instead, report it
privately by emailing [ran.isenberg@ranthebuilder.cloud](mailto:ran.isenberg@ranthebuilder.cloud) so
the issue can be addressed before it is publicly disclosed.

## Licensing

This project is licensed under the [MIT-0 License](LICENSE). By contributing, you agree that your
contributions will be licensed under the same terms.
