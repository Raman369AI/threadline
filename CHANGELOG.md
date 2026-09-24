# Changelog

## Unreleased

## 0.2.0b3 — 2026-09-24

- Resolve common constructor-injected, inherited, dotted-module, and constructed-object method candidates conservatively; correct lexical shadowing, explicit receiver bindings, and nested call identity.
- Keep Python 3.12 lazy type-alias value calls distinct from class-definition execution.
- Preserve expression guards, unreachable source, deferred execution context, and construction-time limits across workflow views.
- Separate rename-only records and edits outside callable bodies; improve snapshot identity and before/after symbol pairing while keeping uncertain impact explicit.
- Add snapshot-pinned structured CLI queries for diagnostics, symbols, methods, workflows, branches, source evidence, and paged changes, with completeness and schema metadata.
- Expand the independent semantic corpus and browser/CLI regressions.
- Add typed response contracts and a scoped mypy gate for the schema, workflow projection, and structured CLI.
- Show the tests linked to the selected method, and the methods a selected test exercises, with that source beside the method.
- Open each method with a plain-language summary and Steps, Tests, and Callers tabs with counts; label calls Calls, Probably calls, Library, or Can't tell; add a path bar, a reading guide, keyboard shortcuts, and larger text.
- Trace data through each method, including inputs, assignments, mutations, added values, outputs, and linked template uses; show complete indexed model definitions beside the flow.
- Show only the selected method in a resizable Code pane with expandable related tests, and let the sidebar collapse to free space for the review.
- Start the browser review only after every deferred script has run.

## 0.2.0b2 — 2026-09-18

- Fix documentation and image links in the PyPI description with absolute URLs.
- Lead with PyPI installation and module-first usage, and show the actual review interface.
- Keep contributor checks in the contributor guide and document where the source example is available.
- Check packaged README links during release validation.

## 0.2.0b1 — 2026-09-18

- Separate Endpoints, Commands & tasks, and Modules & methods pages; filter endpoints by HTTP verb and pick a module before browsing its methods.
- Open a selected method and its cross-file workflow in one click, with persistent search and no automatic initial method.
- Pick a module before choosing a method, and label source-supported calls between modules.
- Add PyPI Trusted Publishing and a release guide; mark this release as beta.


- Load workflows progressively with bounded generation caching, and fetch branch bodies only when expanded.
- Compare retained before/after source in one view, with pagination and explicit handling of added, deleted, renamed, or ambiguous definitions.
- Add a manually authored semantic accuracy corpus, interactive timing measurements, and a ready-to-run human reviewer session kit.

- Open Git reviews in a dedicated, paged Changes view with workflow actions and explicit baseline navigation.
- Retain historical caller and call-site evidence for changed or deleted definitions, separately from current callers and possible impact.
- Show visible, accessible loading errors with retry actions; preserve the prior review after a failed refresh and follow same-page method links.

- Verify all six Linux/macOS Python matrix jobs, native Safari, Chrome accessibility, and the seven-repository corpus in CI. Fix macOS temporary-path aliases and remove reverse-DNS startup dependence. Enable private vulnerability reporting.

- Add native Safari and Chrome accessibility CI, correct text contrast and action sizes, and add skip navigation and coverage focus handling.

- Read, hash, and parse the same source bytes; reject symlink traversal and nonregular source files on POSIX.
- Include configuration and source-root options in snapshot identity; distinguish same-line evidence by source columns.
- Publish fully enriched refresh snapshots atomically and keep the prior snapshot after failures.
- Validate loopback Host headers, require session tokens for refresh, and bound HTTP concurrency and responses.
- Page browser definitions, method bodies, diagnostics, and source; preserve continuation and keyboard access.
- Keep shadowed imports, conditional definitions, and dynamic dispatch uncertain; separate confirmed callers from possible impact.
- Compare Git changes from retained source with matching baseline roots/exclusions, pinned revisions, path-safe hunk mapping, and bounded Git operations.
- Add analysis resource budgets, cached evidence lookup, deep-chain truncation, and malformed-metadata handling.
- Expand acceptance to Django, OpenTelemetry namespace packages, and Pants, with isolated time/RSS measurements.
- Add clean-wheel release smoke testing, a Python 3.12–3.14 Linux/macOS CI matrix, and a human-review release checklist.


## 0.2.0a1 — 2026-09-13

- Package Threadline as an installable Python application with bundled browser assets.
- Add versioned snapshots and bounded symbol, method, workflow, and source queries.
- Generate nested cross-file workflows from any selected Python method.
- Suggest framework, script, main-guard, and conventional entrypoints from source/configuration.
- Add Git change review with changed methods, known callers, possible impact, and before/after snapshot IDs.
- Add a documented capability matrix and public-repository validation.
- Simplify the browser's first-read input/output and workflow presentation.
