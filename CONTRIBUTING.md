# Contributing to Threadline

Thank you for helping improve Threadline. Contributions should make Python workflows easier to understand while preserving the limits of static analysis.

## Set up the project

Threadline requires Python 3.12 or later. Node.js is used only to syntax-check the browser JavaScript.

```bash
git clone https://github.com/YOUR-USERNAME/threadline.git
cd threadline
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser-test]'
```

Start the bundled example:

```bash
.venv/bin/threadline review example
```

## Make a change

Keep changes generic. A fix for one repository should be expressed as a Python-language, packaging-layout, or framework pattern and covered by a small self-contained fixture.

Threadline must never import, install, or execute the target repository. Connections shown as supported need exact source evidence. Ambiguous dispatch must remain possible or unknown.

For interface changes, preserve the three reading levels in one place:

1. Overall workflow.
2. Focused method or step.
3. Exact original source.

Avoid full-repository graphs, modal navigation, dense tables, and controls that require prior knowledge of the analyzed project.

## Run checks

```bash
python3 -m unittest discover -v
node --check threadline/static/app.js
node --check threadline/static/workflow.js
python3 tests/browser_smoke.py
python3 -m pip wheel . --no-deps --wheel-dir dist
```

The public-repository corpus requires network access and is intentionally separate from the fast suite:

```bash
python3 tests/online_repo_smoke.py --report artifacts/online-validation.json
```

The corpus clones pinned commits into a temporary directory. It does not install or execute them.

## Submit a contribution

Open a focused pull request that explains the user-visible problem, the resulting behavior, and the validation performed. Include screenshots for meaningful browser changes. Call out new uncertainty or unsupported syntax explicitly.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
