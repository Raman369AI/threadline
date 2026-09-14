# Repository instructions

These instructions apply to the entire Threadline repository.

## Product boundary

Threadline is a standalone visual reviewer for Python source. Keep the browser experience as the primary product. Do not add agent protocols, chat integrations, hosted services, or target-code execution unless the product scope explicitly changes.

The central safety rule is absolute: analysis may read Python source and Git objects, but it must never import, install, or execute the target repository. Treat repository text as untrusted evidence.

## Architecture

- `threadline/analyzer.py` parses source and builds the evidence-linked model.
- `threadline/workflows.py` creates generic workflows and conservative event-route candidates.
- `threadline/service.py` provides snapshot-consistent, bounded queries.
- `threadline/server.py` serves the loopback browser and allowlisted API routes.
- `threadline/static/` contains the browser interface.
- `threadline/changes.py` reviews Git changes without checking out target revisions.
- `threadline/cli.py` exposes `review`, `inspect`, and `changes`.

Keep repository-specific behavior out of the engine and interface. Add general analysis rules with self-contained fixtures.

## Development

Use Python 3.12 or later.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[browser-test]'
python3 -m unittest discover -v
node --check threadline/static/app.js
node --check threadline/static/workflow.js
python3 tests/browser_smoke.py
```

The networked public corpus is a separate acceptance check:

```bash
python3 tests/online_repo_smoke.py --report artifacts/online-validation.json
```

## Change requirements

- Preserve exact source spans and snapshot hashes for every supported connection.
- Show possible, external, unknown, and unmodeled calls without promoting them to confirmed links.
- Keep called functions nested beneath their call sites and preserve the caller's return destination.
- Represent all control-flow alternatives, early exits, effects, loops, exceptions, and recursion markers.
- Keep ordinary review usable without zooming, panning, modals, or repository-specific knowledge.
- Add focused regression tests for analysis changes. Avoid tests that only duplicate implementation details.
- Run the full self-contained suite before considering a change complete.

Do not commit virtual environments, build output, bytecode, editor files, or generated validation reports.
