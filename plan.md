# Threadline: standalone visual Python review

Status: developer alpha 0.2.0a1. Public-beta validation items remain below.

## Decision

Threadline is a standalone visual code-reading product. A reviewer supplies a local Python repository and opens a browser view. The product does not require an agent integration or target-project installation.

| Component | Responsibility |
| --- | --- |
| Analysis engine | Read Python source, resolve supported relationships, preserve control structure and original evidence. |
| Browser | Let a person follow a workflow and inspect code without losing their place. |
| CLI | Start visual review, inspect one workflow as JSON, or compare a Git change. |
| Local HTTP layer | Serve the packaged browser and bounded source queries on loopback. |

## Current baseline

The installable `threadline` package bundles the analyzer and browser. It accepts any local Python directory, parses files without importing the target, indexes every definition and local statement, and builds nested call workflows beside original source.

The first screen shows the selected method's input and output and a readable workflow. Branches, early exits, loops, effects, possible calls, external calls, unknown targets, and recursion remain visible. Selecting an operation focuses its exact original source. Entering a called method preserves the caller and return destination.

Git change review compares an explicit baseline with the working tree without checking out or executing either version. Versioned snapshots keep workflows and source evidence consistent.

## Milestone 1 — Portable package and snapshot API ✅

- Installable Python package and `threadline` console command.
- Bundled browser assets with no development-folder dependency.
- Flat, `src/`, and explicit source-root discovery.
- Versioned snapshots, content hashes, source spans, diagnostics, exclusions, and bounded query pages.
- No target imports, setup scripts, plugins, or application execution.

## Milestone 2 — Complete readable workflows ✅

- Sequence, branches, calls, returns, loops, exceptions, cleanup regions, async handoffs, and recursion markers.
- Nested called methods with argument-to-parameter mapping and return destinations.
- Supported, possible, external, unknown, and unmodeled calls distinguished at the source location.
- Selected workflow and source remain visible together.
- Simple declared input/output summary without fabricated payload examples.

## Milestone 3 — Change review and real-repository coverage ◐

Implemented:

- Changed definitions, deleted methods, known callers, possible impact, and retained before/after evidence.
- FastAPI-style route starts, declared parameters, response models, project scripts, main guards, and conventional starts.
- Pinned public-source tests for Flask, Requests, FastAPI, and Celery.
- Automated evidence checks, target-import blocking, clean-working-tree checks, installed-wheel verification, and browser smoke tests.

Remaining:

- Completed: pinned Django, split OpenTelemetry namespace packages, and Pants monorepo cases.
- Completed: rename/quoted-path, decorated registration, shadowed import, and uncertain-dispatch regressions.
- Continue expanding independent semantic expectations for framework dispatch as new patterns are supported.
- Provisional time and memory budgets are enforced; refine them using real reviewer expectations.
- Complete the human and platform gates in [the release checklist](docs/RELEASE_CHECKLIST.md).

## Public beta gate

- At least three first-time reviewers complete the same input → branch → cross-file call → output task without coaching.
- Record navigation problems and unsupported assumptions.
- No false confirmed connections in the maintained corpus. Unknowns remain acceptable when visibly labeled.
- Installation and review work from a clean environment using the built wheel.

## Commands

```bash
threadline review /path/to/repo
threadline review /path/to/git-repo --base HEAD
threadline inspect /path/to/repo --entrypoint package.module:function
threadline changes /path/to/git-repo --base HEAD
```

## Product boundary

Threadline performs static source inspection. It does not observe execution, prove correctness, or claim that dynamic dispatch occurred. Remote hosting, automatic execution, chat inside the browser, and framework-specific runtime emulation are outside the alpha.
