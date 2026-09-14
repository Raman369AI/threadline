# Using Threadline

Threadline is a standalone visual reviewer. Give it a local directory containing Python source; it parses the files without installing, importing, or running the target project.

## Install from a source checkout

Python 3.12 or later is required.

```bash
cd /path/to/threadline
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/threadline review /path/to/python-repository
```

The last command prints and opens a local address, normally <http://127.0.0.1:4173/>. Search for a function or choose a suggested workflow. Select a step to open the exact source while the surrounding flow remains visible.

## Share this alpha

Until Threadline is published, build a wheel and give the resulting file to another reviewer:

```bash
python3 -m pip wheel . --no-deps --wheel-dir dist
```

They install and run it locally:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install threadline_review-0.2.0a1-py3-none-any.whl
.venv/bin/threadline review /path/to/python-repository
```

No target-project installation or configuration is needed.

## Review a change

From a Git working tree, compare Python changes with an explicit baseline:

```bash
threadline review /path/to/git-repository --base HEAD
```

Threadline shows changed methods, known source-linked callers, possible impact, and before/after evidence without checking out or executing either version.

## Use structured commands

The browser is the primary interface. These commands are available for scripts and CI:

```bash
threadline inspect /path/to/python-repository --query create_order
threadline inspect /path/to/python-repository --entrypoint package.module:create_order
threadline changes /path/to/git-repository --base HEAD
```

Use `--source-root` for an application source directory and repeat `--exclude` for generated, vendored, or irrelevant trees.

## Validate public repositories

The maintained corpus pins Flask, Requests, FastAPI, and Celery commits. The runner clones source into a temporary directory and checks parsing, statement and call accounting, method inputs and outputs, branches, workflow pagination, uncertainty labels, original evidence retrieval, absence of target imports, and an unchanged Git working tree.

```bash
python tests/online_repo_smoke.py
python tests/online_repo_smoke.py --repo fastapi
python tests/online_repo_smoke.py \
  --cache-dir /tmp/threadline-online \
  --report artifacts/online-validation.json
```

After the first cached run, use `--offline` to prove the check does not need the network. The scheduled GitHub Actions workflow stores the JSON report as an artifact.

These checks validate static source representation. They do not observe runtime dispatch or prove program correctness.
