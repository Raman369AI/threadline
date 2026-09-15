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

## Application bounds

- Source: 2 MiB per file, 64 MiB total Python source, 10,000 Python files, 2 million AST nodes.
- Analysis: cooperative 60-second checks; unusually expensive individual parser operations
  are not preempted. These bounds are not an OS-level CPU or memory sandbox.
- Git: 30 seconds per operation, 64 MiB captured output; baseline materialization and
  diff collection each check a 60-second aggregate budget between operations.
- HTTP: loopback only, eight concurrent requests, five-second socket I/O timeout,
  maximum 4 MiB JSON response. Oversized responses fail explicitly.
- Browser: 50 search results per page, 20 top-level statements per page, source excerpts
  of up to 80 lines, and explicit continuation controls. Branch bodies remain attached
  to their statements. Very large nested statements may require narrowing the review
  or inspecting source if the response budget is exceeded.
- Workflows: at most 500 call stages and 100 nested call levels, with explicit truncation; alternatives and uncertainty
  records have continuation cursors. Scope and source reads are tied to a snapshot ID.
- Refresh: only one rebuild at a time. Readers retain the prior complete snapshot until
  publication. A failed rebuild leaves the prior snapshot available.

The browser no longer requests `/api/index`. That legacy endpoint remains available
subject to the same response limit. Reindex returns a summary and requires a session
header obtained from `/api/session`; arbitrary Host headers and mismatched origins are
rejected. No target imports, dependency installation, or source execution are permitted.
