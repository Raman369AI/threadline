# Alpha validation record

Date: 2026-09-13

Machine: Linux x86_64, AMD Ryzen 5 8645HS (12 logical CPUs), 30 GiB RAM, Python 3.12.3. Measurements are single cold `SnapshotStore.summary()` runs and are indicative rather than performance budgets.

| Repository | Shape | Parsed files | Definitions | Parse errors | Suggested starts | Time | Peak RSS |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bundled order example | Small cross-file API/service/repository | 5 | 6 | 0 | 3 | 0.009 s | 17.2 MiB |
| Flask | WSGI framework, `src/` layout | 24 | 400 | 0 | 262 | 0.548 s | Not recorded |
| Requests | HTTP library, `src/` layout | 20 | 268 | 0 | 146 | 0.426 s | Not recorded |
| FastAPI | Async API framework, large package | 509 | 1,049 | 0 | 798 | 2.732 s | Not recorded |
| Celery | Task queue and worker framework | 164 | 3,074 | 0 | 1,819 | 8.226 s | Not recorded |

Automated verification covers source non-execution, exact statement and call accounting, import and call binding, nested cross-file workflow structure, uncertainty, bounded queries, retained snapshots, Git changes, HTTP route restrictions, installed-wheel use, and headless browser behavior at desktop, tablet, and phone widths.

The [public repository corpus](ONLINE_VALIDATION.md) pins exact Flask, Requests, FastAPI, and Celery commits. It checks every selected workflow connection against original source, blocks target-package imports, and verifies that analysis leaves each checkout clean.

Still required for a stable public release:

- Three uncoached first-time reviewer sessions using the same input → branch → cross-file call → output task.
- Django, namespace-package, and larger monorepo corpus cases.
- Performance budgets selected from real reviewer expectations.
