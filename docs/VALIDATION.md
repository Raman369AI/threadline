# Validation record

[Documentation home](README.md) · [Project home](../README.md)

Validated on 2026-09-14 (America/Chicago). [The complete CI run](https://github.com/Raman369AI/threadline/actions/runs/34922515651) passed for application/test commit `8c9d088` (see the run for the full SHA).
The maintainer owns the three first-time reviewer sessions; the remaining engineering gates are complete.

## Self-contained verification

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

## Public corpus measurements

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

Linux/macOS, Safari, keyboard operation, reflow/zoom, accessibility semantics, installation,
and corpus checks are now verified. The application remains at its existing alpha package
version pending release sign-off.

See [the release checklist](RELEASE_CHECKLIST.md). Automated evidence checks do not prove
runtime correctness or constitute a human screen-reader session.
