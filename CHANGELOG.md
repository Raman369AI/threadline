# Changelog

## 0.2.0b7 — 2026-09-30

- Keep the view tabs on screen above the page on a narrow window or panel, with the rest of the
  sidebar in the drawer, and size the method heading for narrow columns.

## 0.2.0b6 — 2026-09-30

- Restyle the review with a tonal dark design: icon buttons and search in the header, a
  256px sidebar of view tabs with counts and a status line, and a header card with filters on
  each start page. Endpoints are grouped by the file that declares them, with verb, async, and
  effect badges; commands and tasks are cards; modules are cards that open to their methods,
  each row showing async, routes, parameters, calls, and effects. The method view has a
  toolbar with the file position, colored summary pills, a code gutter with the definition line
  marked, and a full-height drawer for tests, callers, and models. Dark is now the default
  theme; Light and System stay one click away. Geist and JetBrains Mono are used when
  installed; no font or icon is downloaded.
- Count a method's project calls once, from the analyzer's own list (including calls inside
  generators and comprehensions), so the row count, the Calls menu, and the CALLS chips agree.
  Fix `signature` for decorated functions and classes, and show parameters exactly as declared
  (keeping `/`, bare `*`, and annotated `*args` and `**kwargs`). Say when a catalog page is
  capped, and load catalog pages with their requests in parallel.
  Folders in the sidebar filter the module cards; catalog pages get sort, group-by, and a
  hover preview; the sidebar is a drawer on narrow windows and arrow keys move through its tree.
- Show modules as a directory tree in the sidebar that opens level by level, with folder
  filters above the module cards.
- Return async, parameters, call count, effects, and routes with `/api/starts` and
  `/api/modules` rows, in the live server, the VS Code transport, and saved HTML.
- Add a review bar: previous and next method in the file (also `[` and `]`), a link to the
  method that led here or its first caller, and Called by and Calls dropdowns.
- Add a desktop VS Code extension preview with function-at-cursor, workspace, and
  Git-change review; source navigation, stale-snapshot notices, refresh, and HTML
  export. Bundle the analyzer and run it through an isolated Python stdio bridge.
  Source jumps preserve historical evidence when the current file has changed.
  Published on the Visual Studio Marketplace as `Raman369AI.threadline-review`.
- Share read-only review queries between the local server and VS Code transport.
- Add a GitHub Pages generator: paste a public repository URL, analyze its Python
  source in a browser worker, preview the review, and download standalone HTML.
  Includes optional branch and source-folder selection, pinned source verification,
  cancellation, bounded downloads, and a Pages deployment workflow.
- Add review links to the GitHub Pages generator: `?repo=owner/name&ref=…&folder=…`
  fills the form and starts the review in the visitor's browser. After a review,
  copy the link or an "Explore in Threadline" README badge.
- Allow saved HTML reviews to navigate inside a sandboxed browser preview when
  the browser restricts changes to its URL.

## 0.2.0b5 — 2026-09-26

- Infer a factory's result without a return annotation when every return constructs a class (`return Repo()`, `return build()`), and resolve a name assigned once from a function (`alias = clean`) as a probable alias.
- Name the Python that parsed a file in syntax errors, and suggest running Threadline with a newer Python when the file may use newer syntax.
- Add an *Effects* row to the method summary: DB, network, and file reads and writes, processes, and logging from known library calls, propagated through resolved project calls with their path ("DB write via `update_user`"). *Raises* also lists exceptions from called project functions. `threadline method` returns the records as `effects`.
- Type receivers bound by `with X() as y:` and by dotted library factories such as `logging.getLogger(__name__)`, and record the library target of every external call.
- Cross-check supported call targets against pyright in CI, on this repository and on flask and requests; any disagreement fails the build.
- Render a method once when it is opened; building its call map selected it again and redrew the view, briefly showing "Loading code…" and fetching it twice.
- Resolve names bound at module level (`FEE = 2`, including inside top-level `if`/`try` blocks) as module globals with their value, instead of unknown names with an "unbound read" gap.
- Stop reporting an argument as possibly changed when the callee only calls read-only methods on it (`count`, `index`, `get`, `keys`, `startswith`, …).
- Record `self.items.append(item)` and similar calls as a change to `self.items`; the summary shows `self` and `cls` changes with their attribute.
- Type a receiver from a factory's return annotation: after `repo = make_repo()` with `-> Repo` or `-> Optional[Repo]`, `repo.get()` probably calls `Repo.get`.
- Bind `except ... as exc` inside its handler, and unbind it afterwards as Python does.
- Keep comprehension and lambda variables inside their expression, so `assert all(row["id"] for row in rows)` no longer reads `row` as an unknown name; bind tuple targets such as `for key, value in rows`.
- Label builtins used as values, such as `key=str`, as builtins instead of unknown names; a module-level definition with the same name still wins.
- Resolve names a nested function or lambda reads from its enclosing function as closure variables, following Python's lookup order: an enclosing name wins over a module global, and class bodies are not enclosing scopes.
- Index imports inside `if`/`try`/`with` blocks, such as `try: import mcp.types as mcp_types`, and treat `__file__`, `__name__`, and other implicit module attributes as module globals. On agent-kanban-pm, unknown-name gaps in method data flow fall from 763 to 0.
- Extend the semantic corpus with `changes` and `name` data-flow checks, and add these nine cases, each with a contrasting check, as a regression gate.
- Stop reporting a caller's argument as changed when the callee only calls methods on a parameter annotated as an immutable type such as `str`, `int | None`, or `tuple[int, ...]`.
- Show a change that a called function only *might* make as a dashed chip with its source in the tooltip, instead of as a definite change. The reading guide now explains dashed items.
- Resolve construction of an imported `@dataclass` or `@total_ordering` class as a direct call instead of *probably*.
- Rank search results by name: an exact method name first, then name prefixes; project code before tests and lambdas.
- List methods called on objects the method receives, such as `db.commit()` or `repository.save(order)`, under *Calls*; selecting one highlights its line. These are often a method's real side effects. They are dashed when their target cannot be told from source; library methods on a typed receiver name the library method in the tooltip.
- Add *Raises* to the method summary when the method raises an exception.
- Move test modules with a main guard out of *CLI commands* into a collapsed "Test modules you can run" group.
- Name the selected call-map step above the method ("Selected in the call map: …") and hide that box when it adds nothing; method cards in a module list show their line instead of repeating the file; module-level commands no longer show `<module>`.
- Explain Coverage call counts in one sentence and fold the static-analysis caveats behind "Limits of reading source without running it".
- Replace the **Hide sidebar** button with a ☰ menu button at the left of the header, and move *Source only · not executed* to a button in the bottom-right corner that opens the reading guide above it. The guide now fits narrow windows.
- Make the code pane resizable: drag the divider between the code and the side pane, or use the arrow keys on it; double-click or Enter resets it, and the width is remembered.
- Rename the corner button **Instructions** and move **Coverage** into it as a second section, removing the header button. The analysis-issues badge opens that section directly.
- Add dark mode. The review follows the system setting, and **Theme** in the header switches between System, Light, and Dark; the choice is remembered in that browser, including in a saved HTML review. Every color is now a named token, so light mode is unchanged, and the accessibility checks run axe in both themes.
- `threadline review`: print errors as plain text instead of JSON, name the bad `--base` revision, check the `--output` folder before analysis, warn when no Python files are found, stop logging every request, use a free port when 4173 is busy (unless `--port` is given), and describe every option in `--help`.

## 0.2.0b4 — 2026-09-25

- Export the interactive viewer and retained source as one standalone HTML file with `threadline review PROJECT --output review.html`; browse without a server or network connection.
- Make the `threadline-review` PyPI package name prominent and expand Python code review, call graph, and data flow search metadata.
- Link tests in `unittest.TestCase` subclasses of any name, such as `OrderTests`, not only `Test*` classes.
- List console scripts that re-export their function (`pkg.cli:main` defined in `pkg.commands`) and `python -m pkg` for packages with `__main__.py`; project commands and modules now list before test modules.
- Replace the tabbed method view (Data flow, Steps, Code, Tests, Callers, the separate code pane, caller comparison, No-distraction mode) with one code review: the method's code under an In / Calls / Changes / Returns summary. Names highlight their uses; project calls, tests, and callers open beside the code; referenced models show as declaration source. **Back** restores the prior method, highlight, and side code.
- Give every call-map step the same form: name, uniform tags (*if*, *later*, *probably*, *can't tell*, *new object*, *unreachable*), and the line that calls it. Library and untraced calls fold behind one toggle.
- Mark a step *later* only when a coroutine or generator is left unawaited, not for every awaited call under an async endpoint.
- Name object joins in data flow after their value instead of internal ids such as `o2`.
- Stop listing a package `__init__.py` main guard as `python -m pkg`; that command runs `__main__.py`.
- Hide empty Endpoints and Commands pages; keep the reading-guide button visible on narrow windows and give it a Close button.

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
