# Validation record

[Documentation home](README.md) · [Project home](../README.md)

The record below describes the 2026-09-14 validation of commit `8c9d088`, not the
current checkout. [That CI run](https://github.com/Raman369AI/threadline/actions/runs/34922515651) passed. The current candidate has local checks recorded below; its cross-platform matrix and three first-time reviewer sessions remain pending.

## Implementation candidate — 2026-09-23

The implementation candidate passed 109 Python tests, the standalone 23-case curated
semantic corpus (zero false-supported cases, ten unresolved), both browser JavaScript
syntax checks, normal and Git-change Chromium smoke suites, Chrome accessibility
automation, and a clean-wheel install/CLI/server/assets smoke. The semantic counts
describe only the curated fixtures. A repeatable synthetic memory profile is recorded
in [performance and resource budgets](PERFORMANCE.md).
The scoped mypy check for the schema, workflow projection, and structured CLI also
passed locally.

All seven pinned public-source cases passed their local time/RSS budgets with no target
imports or target working-tree changes. Their candidate measurements appear in
[performance and resource budgets](PERFORMANCE.md). The Linux/macOS Python matrix,
native Safari, and three uncoached reviewer sessions have not been rerun for this
implementation candidate. No stable release claim follows from these local checks.

## Historical self-contained verification — commit `8c9d088`

- 51 tests passed in each Linux/macOS × Python 3.12/3.13/3.14 matrix job.
- Both browser JavaScript syntax checks passed.
- All 18 Chromium browser checks passed: source and workflow review, deep links,
  responsive widths, bounded requests, paged search/methods, keyboard search,
  refresh authorization, named buttons, and no reported browser exceptions.
- Clean-wheel installation passed outside the checkout in all six matrix jobs, including
  the CLI workflow, loopback server, and bundled assets.
- Chrome passed 20 accessibility checks; native Safari 26.6.2 passed 17. Both reported
  zero axe violations across the six audited states. See [accessibility validation](ACCESSIBILITY.md).
- macOS temporary-directory alias handling and DNS-independent loopback startup have
  focused regression coverage. Private vulnerability reporting is enabled.
- The seven pinned public-source cases passed their time and peak-memory budgets.

The suite covers single-read source evidence, same-line call columns, configuration-only
snapshots, concurrent and failed refresh, Host/token checks, HTTP response/concurrency
bounds, namespace imports, conservative dispatch, Git baseline scope and rename handling,
quoted filenames, edits during change review, and workflow continuation/depth limits.

## Historical public corpus measurements — commit `8c9d088`

Each repository ran in an isolated process. Analysis excludes Git fetch; peak RSS covers
the validation worker. Budgets are provisional engineering limits, not reviewer-derived
expectations. Values are single-run observations, not statistical latency guarantees.

| Repository | Files | Definitions | Analysis | Query sequence | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| flask | 24 | 400 | 0.552 s | 0.023 s | 38.8 MiB |
| requests | 20 | 268 | 0.413 s | 0.018 s | 35.4 MiB |
| fastapi | 509 | 1,049 | 1.963 s | 0.067 s | 87.7 MiB |
| celery | 164 | 3,074 | 3.991 s | 0.161 s | 150.4 MiB |
| django | 883 | 9,411 | 13.796 s | 0.545 s | 479.2 MiB |
| opentelemetry | 91 | 955 | 1.082 s | 0.047 s | 60.1 MiB |
| pants | 1,704 | 10,203 | 21.678 s | 0.821 s | 692.3 MiB |

Targets were read as source only. No target dependencies were installed and no target
source was imported or executed. Git working trees remained clean. See
[the public corpus](ONLINE_VALIDATION.md) and [resource budgets](PERFORMANCE.md).

## Release sign-off

Three uncoached reviewer sessions remain pending under
[the documented protocol](REVIEWER_SESSIONS.md). Performance budgets remain provisional
until reviewed against that feedback.

Linux/macOS, Safari, keyboard operation, reflow/zoom, accessibility semantics,
installation, and corpus checks were verified for the historical commit above. The
current package is beta version `0.2.0b2`; stable release sign-off remains pending.

See [the release checklist](RELEASE_CHECKLIST.md). Automated evidence checks do not prove
runtime correctness or constitute a human screen-reader session.
