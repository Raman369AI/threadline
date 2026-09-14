# Public repository validation

Validated on 2026-09-13 (America/Chicago) with Python 3.12.3. A machine-readable report can be generated with the command below. Repositories are pinned in [tests/online_repositories.json](../tests/online_repositories.json).

| Repository and reviewed method | Revision | Parsed files | Definitions | Branches | Workflow stages | Evidence checks | Time |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [Flask](https://github.com/pallets/flask) — `Flask.full_dispatch_request` | `d73fa1c` | 24 | 400 | 7 | 7 | 7 | 0.548 s |
| [Requests](https://github.com/psf/requests) — `Session.request` | `dae7ef63` | 20 | 268 | 7 | 10 | 10 | 0.426 s |
| [FastAPI](https://github.com/fastapi/fastapi) — `get_request_handler` | `50113da1` | 509 | 1,049 | 7 | 8 across 2 files | 8 | 2.732 s |
| [Celery](https://github.com/celery/celery) — `Task.apply_async` | `ea1db4a5` | 164 | 3,074 | 26 | 19 | 19 | 8.226 s |

Each check clones the pinned commit, analyzes source, resolves the selected method and every workflow page, retrieves the original source for every connection, and confirms the Git working tree is still clean. A Python audit hook fails the run if Threadline attempts to import the target package. The target packages are not installed or executed.

The corpus exercises a WSGI framework, an HTTP client, an async API framework with a cross-file workflow, and a queue/task framework. It confirms that supported, possible, external, and unknown targets stay visible where applicable. FastAPI contains 15 calls that the current AST model records as explicitly unmodeled; the report preserves this gap rather than counting those calls as resolved.

Run the same validation with:

```bash
python tests/online_repo_smoke.py --report artifacts/online-validation.json
```

The test demonstrates static representation at these exact revisions. It does not claim observed execution or correctness.
