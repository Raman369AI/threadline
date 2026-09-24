# Performance and resource budgets

[Documentation home](README.md) · [Project home](../README.md)

These are provisional engineering acceptance budgets, not measured reviewer expectations.
Revisit them after the first-time reviewer sessions. Corpus timings exclude Git fetch and
run in isolated processes so peak RSS belongs to one repository.

| Corpus class | Analysis | Query sequence | Peak RSS |
| --- | ---: | ---: | ---: |
| Flask, Requests, FastAPI, Celery, OpenTelemetry | 15 s | 2 s | 1,024 MiB |
| Django | 30 s | 2 s | 1,024 MiB |
| Pants monorepo | 60 s | 3 s | 2,048 MiB |

The query sequence includes symbol lookup, a method query, source evidence, and all
selected workflow stage pages. The remainder of the corpus verifies every connection's
source evidence. `tests/online_repositories.json` is the executable budget specification.
The worker is terminated after 120 seconds. Time limits can vary with CI hardware;
investigate failures before changing a budget.

The 2026-09-23 implementation candidate passed all seven pinned cases. These
single-process observations are diagnostic and not a latency guarantee:

| Repository | Analysis | Query sequence | Peak RSS |
| --- | ---: | ---: | ---: |
| Flask | 0.581 s | 0.024 s | 40.5 MiB |
| Requests | 0.454 s | 0.021 s | 36.6 MiB |
| FastAPI | 2.001 s | 0.073 s | 96.8 MiB |
| Celery | 4.393 s | 0.176 s | 163.4 MiB |
| Django | 15.012 s | 0.593 s | 518.3 MiB |
| OpenTelemetry | 1.161 s | 0.052 s | 63.7 MiB |
| Pants | 26.001 s | 0.876 s | 760.7 MiB |

Git baseline materialization was timed separately on three clean pinned checkouts,
using the same source-root and exclusion options as the corpus. After analysis,
`review_changes(..., base='HEAD')` took 0.722 seconds on Flask, 21.545 seconds on
Django, and 35.949 seconds on Pants; each produced zero changed-file records. These
single runs include Git object loading and comparison, not checkout or analysis time.
The baseline path still issues per-file Git requests, so large-repository change
review has a measurable startup cost even when nothing changed. Keep the existing
60-second aggregate Git budget visible until a measured batch-loading change is ready.

## Application bounds

- Source: 2 MiB per file, 64 MiB total Python source, 10,000 Python files, 2 million AST nodes.
- Analysis: cooperative 60-second checks; unusually expensive individual parser operations
  are not preempted. These bounds are not an OS-level CPU or memory sandbox.
- Git: 30 seconds per operation, 64 MiB captured output; baseline materialization and
  diff collection each check a 60-second aggregate budget between operations.
- HTTP: loopback only, eight concurrent requests, five-second socket I/O timeout,
  maximum 4 MiB JSON response. Oversized responses fail explicitly.
- Browser: 50 search results per page, 20 top-level statements per page, source excerpts
  of up to 80 lines, and explicit continuation controls. Branch bodies load on expansion in pages of 20 immediate statements; nested branches
  remain collapsed until opened. The structured scope API retains its full-body default
  and supports `shallow=1` for the browser. Individual large statements can still exceed
  the response limit; source excerpts remain available.
- Workflows: the browser displays the first 20 records before requesting continuation.
  Generated workflows use a per-store LRU cache capped at 32 entries and 16 MiB of
  serialized workflow data; Python object overhead is additional. Evicted snapshots
  discard their cache entries. Concurrent queries share generation under a lock.
  At most 500 call stages and 100 nested call levels, with explicit truncation; alternatives and uncertainty
  records have continuation cursors. Scope and source reads are tied to a snapshot ID.
- Refresh: only one rebuild at a time. Readers retain the prior complete snapshot until
  publication. A failed rebuild leaves the prior snapshot available.

The browser no longer requests `/api/index`. That legacy endpoint remains available
subject to the same response limit. Reindex returns a summary and requires a session
header obtained from `/api/session`; arbitrary Host headers and mismatched origins are
rejected. No target imports, dependency installation, or source execution are permitted.

## Interactive measurements

`python tests/browser_smoke.py` records `methodAndSourceMs`, `workflowFirstPageMs`,
and `branchFirstPageMs`
in the system temporary directory as `threadline-browser-performance.json`.
The `--changes` variant writes `threadline-changes-performance.json`. These use a
synthetic 65-call workflow and a 55-statement branch; timings include browser rendering
and automation observation overhead. They are diagnostic measurements, not reviewer
acceptance thresholds or representative results for every repository.
`methodAndSourceMs` ends after the selected method and its initial source excerpt are
visible; it does not include symbol search latency. Two local Chromium runs on
2026-09-23 measured 12.7 ms (ordinary smoke) and 14.2 ms (change-review smoke) for
that fixture. These are single diagnostic observations, not latency guarantees.

Comparisons return at most 40 original lines per side in the browser. Source is pinned
to the working and baseline snapshots; pages advance by relative line offset and do
not align moved statements or infer semantic equivalence.

## Current synthetic memory profile

Run `python3 tests/profile_snapshot_memory.py` to regenerate a source-only service
fixture with 40 Python files, 960 definitions, 2,480 calls, and 89,280 source bytes.
The final local run on Linux/Python 3.12.3 measured these phase wall times, process
CPU times, and `tracemalloc` peaks:

| Phase | Wall | CPU | Traced peak |
| --- | ---: | ---: | ---: |
| Discovery and parsing | 0.679 s | 0.678 s | 12.16 MiB |
| Initial refresh | 2.421 s | 2.418 s | 22.60 MiB |
| Catalog rebuild | 0.031 s | 0.031 s | 22.86 MiB |
| Cold workflow generation | 0.003 s | 0.003 s | 13.28 MiB |
| 100 cached workflow responses | 0.043 s | 0.043 s | 13.26 MiB |
| Summary, scope, and source queries | 0.001 s | 0.001 s | 13.27 MiB |
| Workflow response serialization | 0.002 s | 0.002 s | 13.27 MiB |
| 25 pinned reads during refresh | 0.022 s | 0.022 s | 25.37 MiB |
| Refresh retaining prior snapshot | 2.530 s | 2.526 s | 35.68 MiB |
| Git change review | 2.847 s | 2.720 s | 112.64 MiB |
| Retained-model serialization | 0.252 s | 0.252 s | 59.38 MiB |

The pinned reads completed while refresh was still pending. Traced peaks include
already-live shared-process allocations and are not incremental phase costs. Process
high-water RSS before model serialization was 147.81 MiB in this run; earlier runs
varied substantially, so it is not a stable per-request cost. Traced allocations,
serialized JSON, and process RSS measure different things. The model serialized to
5,595,766 bytes, a workflow response to 12,794 bytes, and the workflow cache held
12,565 serialized bytes after the query set. The profiler prints JSON lines for
each phase. This synthetic fixture is diagnostic,
not a population estimate or a replacement for the pinned public corpus.
