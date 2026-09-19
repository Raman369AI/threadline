# Publishing to PyPI

[Documentation home](README.md) · [Release checklist](RELEASE_CHECKLIST.md) · [Publishing workflow](../.github/workflows/pypi.yml)

Threadline publishes the `threadline-review` package through `.github/workflows/pypi.yml`. Publishing a GitHub release triggers the workflow. A push, a tag push alone, or a saved draft does not trigger it. The workflow publishes to production PyPI, including for alpha and beta releases.

## Configure Trusted Publishing once

Commit and push the workflow to `Raman369AI/threadline` before creating the release. The release's tagged commit must contain the workflow and the code you intend to ship.

In the GitHub repository's **Settings → Environments**, create an environment named `pypi`. If you configure deployment restrictions, allow the release tags you intend to publish. Any configured environment approval must complete before the publish job runs.

For a new PyPI project, open your account's [Publishing page](https://pypi.org/manage/account/publishing/) and add a pending GitHub publisher. For an existing project you maintain, open **Manage → Publishing** on that project and add a GitHub publisher. A pending publisher creates the project on its first successful upload; it does not reserve the name. See PyPI's [new project guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [existing project guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

Use these values for this repository:

| PyPI field | Value |
| --- | --- |
| PyPI project name, for a pending publisher | `threadline-review` |
| Repository owner | `Raman369AI` |
| Repository name | `threadline` |
| Workflow filename | `pypi.yml` |
| Environment name | `pypi` |

The workflow field takes the filename only. The environment must match the workflow's `environment.name`. If publishing from another repository, use that repository's actual owner and name.

The publish job uses `id-token: write` and the PyPA publishing action. You do not need a `PYPI_TOKEN` secret. See [PyPI's Trusted Publishing instructions](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Prepare the release version

Set `[project].version` in [pyproject.toml](../pyproject.toml) and `__version__` in [threadline/__init__.py](../threadline/__init__.py), update the [changelog](../CHANGELOG.md), and update version-specific installation examples. Keep the package name `threadline-review`; the command remains `threadline`.

The tag must exactly match the package version, optionally prefixed with `v`:

| Package version | Accepted release tags |
| --- | --- |
| `0.2.0a1` | `v0.2.0a1` or `0.2.0a1` |
| `0.2.0b1` | `v0.2.0b1` or `0.2.0b1` |
| `0.2.0` | `v0.2.0` or `0.2.0` |

Use an unpublished version for the next release. The examples do not establish which versions already exist on PyPI. The GitHub pre-release checkbox does not change the package version; alpha or beta status comes from the version in `pyproject.toml`.

Complete the [release checklist](RELEASE_CHECKLIST.md) for the candidate and check its CI results before publishing. The publishing workflow runs unit and package checks, but it does not wait for the separate CI platform matrix, browser checks, or public-repository corpus.

## Check distributions locally

From the repository root with Python 3.12 or later, use the development virtual environment described in [Contributing](../CONTRIBUTING.md). These commands build and inspect distributions without uploading them. A fresh output directory avoids mixing releases:

```bash
.venv/bin/python -m pip install --upgrade build twine
.venv/bin/python -m unittest discover -v
release_dist_dir=$(mktemp -d)
.venv/bin/python -m build --outdir "$release_dist_dir"
.venv/bin/python -m twine check --strict "$release_dist_dir"/*
.venv/bin/python tests/release_smoke.py "$release_dist_dir"/*.whl
```

The smoke test installs the wheel in a clean environment and checks the CLI, local review server, and bundled HTML, CSS, and JavaScript.

## Publish the GitHub release

1. Commit and push the candidate, including `pyproject.toml`, the changelog, and `.github/workflows/pypi.yml`.
2. Open the repository's **Releases → Draft a new release** page.
3. Choose a matching tag, such as `v0.2.0b1`, targeting the tested candidate commit.
4. Add release notes. For an alpha or beta, mark the GitHub release as a pre-release.
5. Choose **Publish release** when ready to upload to PyPI. Saving a draft does not publish the package.

GitHub documents these controls in its [release creation guide](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).

In **Actions → Publish to PyPI**, the `build` job checks the tag, runs unit tests, builds the wheel and source distribution, checks metadata, and runs the clean-install smoke test. It stores the files in the `pypi-distributions` artifact. The separate `publish` job downloads those files and uploads them through the `pypi` environment using Trusted Publishing.

## Verify the published package

Confirm the workflow succeeded and the expected version and both distribution files appear on the [PyPI project page](https://pypi.org/project/threadline-review/). Then install that exact version in a fresh environment. Replace the example version with the release you just published:

```bash
release_version=0.2.0b1
release_env_dir=$(mktemp -d)
python3 -m venv "$release_env_dir"
"$release_env_dir/bin/python" -m pip install --index-url https://pypi.org/simple "threadline-review==$release_version"
"$release_env_dir/bin/python" -m pip show threadline-review
"$release_env_dir/bin/threadline" --help
"$release_env_dir/bin/threadline" review /path/to/python-repository
```

## Troubleshooting

| Problem | Check |
| --- | --- |
| No publishing run | Publish the GitHub release; verify its tagged commit contains `pypi.yml`. This workflow has no manual dispatch trigger. |
| Release version check fails | Match the tag to `[project].version`, with only an optional leading `v`. |
| `invalid-publisher` or token exchange failure | Compare PyPI's owner, repository, workflow filename, and environment fields with the workflow. Keep `id-token: write` on the publish job. See [PyPI troubleshooting](https://docs.pypi.org/trusted-publishers/troubleshooting/). |
| Publish job is waiting | Check the `pypi` environment's configured approvals and deployment rules. |
| Metadata or installation check fails | Reproduce the local distribution checks above and fix the candidate before publishing. |
| A distribution filename already exists | Inspect PyPI before retrying. PyPI cannot replace or reuse an uploaded filename, even after deletion; changed packages need a new version. See [PyPI's filename rules](https://pypi.org/help/#file-name-reuse). |

For an authentication failure before any upload, correct the publisher configuration and rerun the failed job. If an upload partially succeeded, inspect the files already present before retrying: this workflow does not skip existing files. Avoid deleting releases as a way to reuse a version.
