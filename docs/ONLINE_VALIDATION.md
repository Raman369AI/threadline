# Public repository validation

Validated on 2026-09-14 (America/Chicago) with Python 3.12.3. Exact commits, selected
source roots, expected uncertainty states, and resource budgets are pinned in
[the corpus manifest](../tests/online_repositories.json).

| Repository / reviewed method | Commit | Files | Workflow stages | Evidence checks | Analysis |
| --- | --- | ---: | ---: | ---: | ---: |
| [flask](https://github.com/pallets/flask) — `Flask.full_dispatch_request` | `d73fa1cdcbd8` | 24 | 7 | 7 | 0.552 s |
| [requests](https://github.com/psf/requests) — `Session.request` | `dae7ef63b4df` | 20 | 10 | 10 | 0.413 s |
| [fastapi](https://github.com/fastapi/fastapi) — `get_request_handler` | `50113da16fec` | 509 | 8 | 8 | 1.963 s |
| [celery](https://github.com/celery/celery) — `Task.apply_async` | `ea1db4a551a4` | 164 | 19 | 19 | 3.991 s |
| [django](https://github.com/django/django) — `BaseHandler._get_response` | `75c4403f07b8` | 883 | 15 | 15 | 13.796 s |
| [opentelemetry](https://github.com/open-telemetry/opentelemetry-python) — `Tracer.start_span` | `cfad5ebf2277` | 91 | 21 | 21 | 1.082 s |
| [pants](https://github.com/pantsbuild/pants) — `PantsRunner.run` | `24c4ecae0e84` | 1704 | 124 | 124 | 21.678 s |

The corpus covers Flask, Requests, FastAPI, Celery, Django, OpenTelemetry's split namespace
packages, and a 1,704-file Pants monorepo. Each isolated worker verifies source accounting,
selected workflow pages, original evidence for every selected connection, expected
certainty states, and a clean target working tree. A target-import audit hook blocks and
fails attempted target imports. Django additionally checks that middleware callbacks
remain unknown and member dispatch remains possible.

These checks establish evidence consistency and selected semantic expectations. They do
not constitute a complete independent correctness oracle for every supported connection.
Self-contained fixtures supply additional precise binding, dispatch, branch, and Git
regressions. Unknown and explicitly unmodeled calls are retained rather than promoted.

```bash
python tests/online_repo_smoke.py --report artifacts/online-validation.json
```

Use `--cache-dir /tmp/threadline-corpus` to reuse checkouts, and `--offline` to prohibit
fetching missing revisions. CI runs the corpus for pull requests and on a weekly schedule,
and retains the generated report. Targets are never installed or executed.

See [measurements and local verification](VALIDATION.md), [budgets](PERFORMANCE.md), and
[the stable release gates](RELEASE_CHECKLIST.md).
