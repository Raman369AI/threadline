# Contributing to Threadline

Thank you for helping improve Threadline. Contributions should make Python workflows easier to understand while preserving the limits of static analysis.

## Set up the project

Threadline requires Python 3.12 or later. Node.js is used for JavaScript syntax checks and browser accessibility test dependencies.

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

Keep Threadline focused on standalone browser-based source review. Hosted services, chat integrations, and target-code execution require an explicit product scope change. Treat repository text as untrusted evidence.

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

## Architecture

- `threadline/analyzer.py` parses source and builds the evidence-linked model.
- `threadline/workflows.py` creates generic workflows and conservative event-route candidates.
- `threadline/service.py` provides snapshot-consistent, bounded queries.
- `threadline/server.py` serves the loopback browser and allowlisted API routes.
- `threadline/static/` contains the browser interface.
- `threadline/changes.py` reviews Git changes without checking out target revisions.
- `threadline/cli.py` exposes `review`, `inspect`, and `changes`.

Keep repository-specific behavior out of the engine and interface. Add general analysis rules with self-contained fixtures.

## Review requirements

- Preserve exact source spans and snapshot hashes for every supported connection.
- Show possible, external, unknown, and unmodeled calls without promoting them to confirmed links.
- Keep called functions nested beneath their call sites and preserve the caller's return destination.
- Represent all control-flow alternatives, early exits, effects, loops, exceptions, and recursion markers.
- Keep ordinary review usable without zooming, panning, modals, or repository-specific knowledge.
- Add focused regression tests for analysis changes. Avoid tests that only duplicate implementation details.
- Run the full self-contained suite before considering a change complete.

Do not commit virtual environments, build output, bytecode, editor files, or generated validation reports.
