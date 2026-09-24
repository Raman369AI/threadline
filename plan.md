# Threadline: comprehensive review and improvement plan

## Status and scope

- Review date: 2026-09-23.
- Reviewed revision: `955806d366d07e7b3cd31bca1a7c00e79e0d3131`.
- Package version: `0.2.0b2` (`threadline-review`).
- Audiences: a user with working Python knowledge but no familiarity with the repository; a maintainer extending Threadline; an agent consuming its structured output.
- Scope: pre-implementation findings, acceptance criteria, implementation status, remaining limits, and release gates for users, maintainers, and structured-query clients.
- Findings below describe the reviewed revision. The implementation update records the later behavior; unchecked criteria remain open.

## Implementation update — 2026-09-23

This implementation is a beta candidate, not a stable release. Source analysis, service queries,
CLI, browser, tests, and documentation were changed together. The original observations
below describe the reviewed revision; read this update for the candidate's current
behavior. Static candidates still do not prove runtime execution.

| Finding | Candidate disposition | Evidence and remaining boundary |
| --- | --- | --- |
| F01 | Implemented | Constructor assignments and annotations provide cross-method instance candidates with retrievable source provenance; conflicts stay `possible`. Dynamic initialization and path feasibility remain unresolved. |
| F02 | Implemented for known hierarchies | Inherited `self` and `super` calls follow C3 order when bases are fully known and undecorated; unresolved bases, metaclasses, and dynamic dispatch remain `possible`. Calling a `@property` result stays unknown rather than naming its getter as the direct target. Arbitrary descriptors are not modeled. |
| F03 | Implemented | Dotted imports and constructed receivers expose method candidates; nested calls have distinct IDs. Arbitrary factory returns remain unknown. |
| F04 | Implemented for reproduced cases | Method bodies and class-comprehension bodies no longer resolve bare names through class namespaces. Global and enclosing-function lookups remain intact; lazy `type Alias = ...` values carry a separate deferred annotation context. Other PEP 695 type-parameter forms need broader coverage. |
| F05 | Implemented for reproduced cases | Loop, `with`, walrus, unpacking, comprehension, and other local binders shadow globals conservatively; calls before local imports or definitions are not promoted to supported. Arbitrary dataflow remains unresolved. |
| F06 | Implemented for reproduced cases | Unbound method and module-function arguments map without a fabricated receiver; classmethod calls distinguish implicit class receivers from instances; uncertain unpacking remains explicitly uncertain. |
| F07 | Implemented | Complete-span call IDs distinguish nested occurrences; workflow stage IDs also distinguish repeated context expansions. |
| F08 | Scoped improvement | Snapshot-local IDs remain positional. Unique symbol matching and `symbolKey` pair line-shifted counterparts, including unchanged methods in edited files; ambiguous duplicates stay unpaired. Stable public bookmarks across arbitrary edits remain open. |
| F09 | Implemented for modeled syntax | Expression alternatives, guards, short-circuit and comprehension context reach workflow stages. General path feasibility is not claimed. |
| F10 | Implemented | Syntactically unreachable calls are labeled in the workflow and excluded from known caller/impact relationships. |
| F11 | Implemented | Construction no longer expands class-body source; initializer candidates are offered with uncertainty and class definition source remains inspectable. |
| F12 | Implemented for modeled boundaries | Deferred context is explicit and inherited into nested stages, including context-specific re-expansion. Scheduling and completion remain unobserved. |
| F13 | Implemented | Pure rename records are separate from source-overlap edits and retain before/after comparison. |
| F14 | Implemented as visible unassessed change | Python module-level and `pyproject.toml` edits, additions, and deletions remain visible with source evidence where readable. No transitive data-dependency analysis is claimed. |
| F15 | Implemented | Possible impact intersects candidate scope IDs, not bare method names. |
| F16 | Implemented | Discovery and configuration manifests affect snapshot identity; parse and configuration read failures refresh diagnostics while retained snapshots stay fixed. |
| F17 | Implemented | Effect hints match structural name tokens; `fingerprint` and `address` no longer trigger accidental hints. Hints remain heuristic. |
| F18 | Implemented | Unused evidence helper and eager workflow were removed; entrypoint/catalog derivation uses one owner and router prefixes are collected during analysis. |
| F19 | Partially addressed | Query results are detached and ownership is documented. A repeatable synthetic profile measures refresh, queries, and Git review; broader public-repository and process-memory optimization remains open. |
| F20 | Implemented | Versioned CLI envelopes expose completeness, diagnostics, source evidence, bounded queries, structured errors, and strict-completeness exit behavior. |
| F21 | Implemented | Saved JSON sessions pin source and baseline evidence; live continuation and evidence queries require explicit snapshot selection, while later Git change pages require a saved session. Mismatches fail explicitly. Session files contain reviewed source and require local protection. |
| F22 | Implemented | Compact and reference-detail output preserve evidence IDs, proof labels, and uncertainty; the reference workflow is 32,002 bytes versus 41,280 bytes for compact full output on `example` in the current candidate. |
| F23 | Partially addressed | The independent corpus has 23 annotated calls, zero false-supported results, ten unresolved calls, and three of four direct targets resolved. These are curated-case counts, not general accuracy. Three uncoached reviewer sessions and cross-platform release validation remain open. |

Local candidate validation: 109 Python tests; standalone 23-case semantic corpus;
normal and change-review Chromium smoke suites; browser accessibility automation;
both browser JavaScript syntax checks; and clean-wheel install/CLI/server/assets
smoke. All seven pinned public-source corpus cases passed their local budgets;
`tests/online_repo_smoke.py` reproduces that check. The clean-wheel smoke was
updated for the versioned CLI response. The profile in
`tests/profile_snapshot_memory.py` uses 40 synthetic files, 960 definitions, and 2,480
calls: the staged run measured 22.60 MiB peak traced allocations at initial refresh,
35.68 MiB after one-file refresh, and 112.64 MiB for Git change review. These are local
single-fixture observations; see `docs/PERFORMANCE.md`. The Linux/macOS matrix, native
Safari, and human reviewer sessions have not been rerun for this candidate.

Remaining engineering work includes a broader type-checked semantic model, reducing
dense legacy control flow, repeated performance sampling and Git baseline optimization,
and human comprehension testing. Dynamic factories, arbitrary descriptors and aliases,
dynamic MRO, runtime registration, path feasibility, and transitive data impact remain outside
the current static model; uncertain calls and unassessed edits must stay visible.

## Overall assessment

At the reviewed revision, Threadline offered useful source navigation but common object-oriented paths stopped early. Workflow summaries lost semantic context, argument mappings could overclaim, and change-impact results were incomplete or noisy. The implementation status above records the changes since that baseline.

The foundations have useful properties: no target imports or dependency installation, source-backed evidence, explicit uncertainty, snapshot-aware queries, a local browser, and bounded resource handling. These operational properties do not establish semantic correctness or successful user comprehension.

| Perspective | Assessment at reviewed revision | Main need |
| --- | --- | --- |
| User with working Python knowledge | Helpful for straightforward function exploration; substantial source checking is needed for OO workflows and changes | Complete common journeys without misleading the reader |
| Maintainer | Clear module boundaries, but implicit semantic and data contracts make extensions risky | Consistent binding, execution, identity, and ownership models |
| Agent | Useful evidence provider, but the CLI is incomplete for reliable unattended review | Completeness disclosure, evidence retrieval, and snapshot-pinned continuation |

Do not describe the project as a dependable correctness checker, complete impact analyzer, or execution trace. Static review does not observe execution or prove correctness.

## Research method and confidence boundaries

The baseline review covered source, tests, documentation, CI, and the browser interface.
It used 18 independent source-only resolution and control-flow fixtures, plus focused
Git-change, class-construction, binding, and refresh cases. Local HTTP queries and
the official Python language reference informed the interpretation. The target
programs were never imported or executed.

Fixture results establish the listed behaviors, not their prevalence across Python
projects. Source-derived UI concerns are not human usability findings. The current
automated results appear in the implementation update and validation record; three
uncoached reviewer sessions remain an open release gate. Reviews should cover an
ordinary service/repository journey and common edits, then distinguish operational
checks, semantic accuracy, resolution usefulness, and human comprehension.

## Strengths to preserve

- **Clear top-level architecture:** parsing, workflow generation, bounded snapshot queries, Git comparison, HTTP serving, and browser rendering have distinct modules.
- **Shared engine:** CLI and browser use the same underlying analysis and service concepts.
- **Source-only operation:** target dependencies are unnecessary, and the reviewed project is not imported or executed.
- **Evidence:** retained source, hashes, exact spans including columns, and evidence identifiers allow findings to be inspected.
- **Historical separation:** baseline callers are separated from current callers and uncertain impact.
- **Local safeguards:** loopback serving, Host checks, refresh tokens, origin checks, allowlisted assets, CSP, symlink-aware file access, bounded responses, and concurrency limits.
- **Progressive reading:** paged workflows, method statements, branch bodies, source excerpts, and comparisons.
- **Recovery:** refresh publication preserves a previous usable snapshot when rebuilding fails; browser error paths offer retries.
- **Useful reading layout:** overall workflow, focused method, and source remain nearby, with caller-return navigation.
- **Existing candidate access:** possible targets can already be opened in the method view. Do not describe this as entirely absent.
- **Validation infrastructure:** self-contained fixtures, semantic checks, browser smoke tests, accessibility automation, clean-wheel installation checks, platform matrices, and pinned public-source checks.
- **Honest documentation:** the project states beta status, static-analysis limitations, and the absence of completed human reviewer sessions.

These properties must remain intact while improving semantic behavior.

## User perspective: working Python knowledge

### Expected journey

A user should be able to:

1. Open a repository without installing its dependencies.
2. Find a relevant endpoint, command, function, or method.
3. Identify its inputs and outputs.
4. Explain validation failures, branches, early exits, and cleanup.
5. Follow a call into another file, understand argument mapping, and return to the caller.
6. Recognize when a relationship is uncertain and continue investigating it.
7. Compare a change and distinguish current, historical, possible, and unassessed impact.
8. Notice incomplete analysis and know what was skipped.

### What worked at the reviewed revision

An order-service fixture contained plain-function and OO endpoints with an unavailable FastAPI import. Threadline identified both endpoint declarations and the router prefix without installing FastAPI. Direct imported function calls resolved correctly. The API returned method structure and original evidence. The browser supported source selection, branch expansion, inline call inspection, candidate access, and returning to a pinned caller. Learnability and comprehension still require reviewer sessions.

### Baseline gaps that could mislead users

- Ordinary injected dependencies and inherited methods remain unknown.
- Equivalent Python expressions can produce different navigation quality, such as a module alias versus a dotted module receiver, or a named instance versus a constructor chain.
- Unknown calls have generic explanations that do not explain the particular missing analysis capability or suggest the next investigation.
- The method view contains distinctions that the numbered workflow overview loses.
- A supported target can be mistaken for a call that definitely executes.
- Effects are keyword heuristics, so labels can be noisy.
- Parse errors require opening Coverage; there is no prominent always-visible parse-failure count in the header.
- A behavior-changing edit outside a function can leave every method/caller category empty.
- Rename-only edits create noisy changed-method results.
- Before/after comparison shows retained source in relative-line pages; it does not align moved statements or establish semantic equivalence.
- Navigation uses position-based IDs and `history.replaceState`; stable bookmarks and browser-history expectations need explicit user testing. This is a source-derived design concern, not a reproduced interactive failure.

### User-facing improvements

- [x] Show analysis problems beside the repository name, including parse-failure and omission counts.
- [x] Explain the difference between represented syntax, resolved targets, possible targets, and observed execution in plain language.
- [x] Give unknown calls specific reason codes and readable explanations, such as an instance attribute initialized in another method.
- [x] Preserve existing manual candidate opening and add deliberate candidate expansion in the workflow overview without upgrading certainty.
- [x] Preserve conditions, unreachable markers, deferred execution, and definition-time distinctions in every reading level.
- [x] Surface changed files and changes outside callable definitions even when all method lists are empty.
- [x] Keep source evidence and a clear return-to-caller path available during uncertain investigation.
- [ ] Evaluate terminology, information density, branch controls, source paging, and comparison navigation with real users.

## Findings register

Priority meanings: **P0** protects correctness or prevents hidden incompleteness; **P1** enables important user/agent journeys; **P2** improves maintainability, efficiency, or polish. These are implementation priorities, not security severity labels.

### F01 — Constructor-initialized instance attributes are unavailable across methods

- Priority: P1; central usability gap.
- Evidence: reproduced with both injected and explicitly annotated attributes.
- Examples: `self.repo = repo` with parameter `repo: Repo`, and `self.repo: Repo = Repo()` in `__init__`, followed by `self.repo.get()` in a sibling method.
- Observed result: `unknown`.
- Cause: `collect_bindings` stores instance information against the assigning scope. `instance_type` searches the current scope and its lexical parents, not sibling `__init__` bindings. The unannotated forwarding assignment also does not propagate the annotated parameter type.
- Source: `threadline/analyzer.py:301`, `:317`, `:326`.
- Plan: build class-associated attribute candidate information with provenance, support annotation/assignment forwarding where source warrants it, and retain uncertainty for reassignment, missing initialization, subclassing, descriptors, and runtime injection.
- [x] Acceptance: both fixtures expose the appropriate candidate with evidence and conservative certainty.
- [x] Acceptance: conflicting assignments do not become one supported target.

### F02 — Inherited method lookup is absent

- Priority: P1.
- Evidence: reproduced `self.helper()` where `helper` is defined on a base class.
- Observed result: `unknown`.
- Cause: member resolution inspects the immediate class's symbols without traversing bases.
- Source: `threadline/analyzer.py:348`.
- Plan: resolve statically identifiable bases, respect lookup order where established, retain ambiguity for unresolved bases and dynamic dispatch, and cover overrides and multiple inheritance. Consider `super()` explicitly rather than treating it as equivalent to ordinary `self` lookup.
- [x] Acceptance: ordinary inherited methods become navigable candidates.
- [x] Acceptance: overrides, ambiguous bases, and unsupported hierarchy cases never become falsely supported.

### F03 — Chained constructors and dotted module receivers are unresolved

- Priority: P1; F07 must also be addressed for chain identity.
- Evidence: reproduced `Repo().get()` and `import pkg.repo; pkg.repo.get()` as unknown; direct module aliases resolve.
- User fixture also reported `pkg.repo.Repo().get()` and `r.Repo().get()` as unknown.
- Control: `x = Repo(); x.get()` produces a possible candidate, and `import repo as r; r.get()` resolves as supported.
- Cause: receiver resolution handles limited name/import shapes and does not recursively interpret receiver expressions.
- Source: `threadline/analyzer.py:340`.
- Plan: separate module-path resolution from instance-receiver inference, recursively resolve supported expression shapes, and avoid treating arbitrary factory calls as guaranteed constructors.
- [x] Acceptance: equivalent import styles and receiver forms yield equivalent candidate sets where their source evidence is equivalent.
- [x] Acceptance: chained calls retain distinct occurrences and evidence.

### F04 — Class lexical lookup can invent a supported call

- Priority: P0.
- Evidence: reproduced a bare `method()` inside `Example.entry`, incorrectly resolving to sibling `Example.method`.
- Observed result: supported target and workflow expansion; a synthetic implicit receiver was also shown.
- Cause: lexical lookup walks through class namespaces as ordinary enclosing method scopes.
- Source: `threadline/analyzer.py:253`.
- Plan: model Python lexical scope rules, including the difference between method bodies and class bodies; do not resolve a bare method-body name through sibling class attributes.
- [x] Acceptance: the sibling method is not reported as a supported target for that bare-name call.
- [x] Acceptance: valid global and enclosing-function bindings still resolve, with annotation-scope behavior handled separately where relevant.

### F05 — Local bindings can leave falsely supported global targets

- Priority: P0.
- Evidence: reproduced loop, `with`, walrus, and tuple-unpacking shadowing across the review.
- Examples: `for helper in callbacks: helper()`, `with ctx as helper: helper()`, `if helper := callback: helper()`, and `helper, other = callbacks; helper()` in a module that defines global `helper`.
- Observed result: global `helper` marked supported.
- Cause: binding collection handles only selected assignment forms and records destructuring targets as whole expressions.
- Source: `threadline/analyzer.py:317`, `:375`, `:647`.
- Impact: incorrect relationships propagate into the supported-caller index and change review.
- Plan: systematically cover all binding constructs, including parameters, assignment and unpacking, loops, context-manager targets, exception targets, pattern captures, assignment expressions, imports, `global`, `nonlocal`, deletion, and comprehension scope rules.
- [x] Acceptance: no affected local call is falsely promoted to a global supported target.
- [x] Acceptance: test expectations follow Python's binding rules, not current analyzer output.

### F06 — Receiver and argument binding is wrong for valid call forms

- Priority: P0.
- Evidence: reproduced `Repo.get(Repo(), 4)` for `get(self, k)` and `models.plain('receiver', 4)` for a module function `plain(self, k)`.
- Observed mappings: `Repo → self`, `Repo() → k`; or `models → self`, `'receiver' → k`. The trailing `4` becomes unresolved while its row still says `syntax`.
- Cause: attribute syntax or a method target plus a parameter named `self`/`cls` is treated as enough evidence for implicit receiver binding.
- Source: `threadline/analyzer.py:391`, especially `:398`.
- Plan: distinguish construction, bound instance access, explicit unbound calls, class methods, static methods, and ordinary module functions. Keep receiver certainty separate from positional argument certainty. Handle unpacking, variadics, keyword-only and positional-only parameters without claiming unsupported mappings.
- [x] Acceptance: explicit instance arguments are not shifted or discarded.
- [x] Acceptance: module attributes do not create an implicit receiver merely because a parameter is named `self`.
- [x] Acceptance: unresolved mappings are not presented as exact syntax-derived bindings.

### F07 — Nested or chained calls can share IDs

- Priority: P0.
- Evidence: reproduced in Threadline's own `Analyzer(...).run()` and the `Repo().get()` fixture.
- Cause: `ident` uses file, start line, start column, and node type. Nested calls can share all of these.
- Source: `threadline/analyzer.py:123`; stage IDs inherit the call ID at `threadline/workflows.py:197`.
- Impact: stages and links collide; browser selection uses the first matching ID at `threadline/static/workflow.js:137`. The wrong call can be selected. Coverage accounting also uses sets/dictionaries keyed by these IDs and can collapse distinct calls.
- Plan: use an occurrence identity that distinguishes complete source spans and, if needed, a deterministic AST discriminator. Check downstream caches, evidence, links, DOM references, pagination, and accounting.
- [x] Acceptance: all distinct call AST occurrences have distinct IDs, including chained and same-start calls.
- [x] Acceptance: selecting each stage retrieves its own source and relationship.
- [x] Acceptance: coverage counts distinct call occurrences rather than merely agreeing over colliding IDs.

### F08 — Position-based scope IDs are unstable across edits

- Priority: P1/P2 depending on navigation requirements.
- Evidence: source-derived design limitation, already acknowledged in change-review comments.
- Adding a line can change every later scope ID; renames also change IDs.
- Source: `threadline/analyzer.py:123`; `threadline/changes.py:72`.
- Plan: retain precise snapshot-local occurrence IDs and introduce a separate symbol-matching mechanism for comparisons and navigation continuity. Use qualified identity, file/rename hints, and appropriate structural evidence; preserve ambiguity for duplicate definitions.
- [x] Acceptance: insertion of unrelated lines does not prevent unique before/after symbol matching.
- [x] Acceptance: uncertain matches remain explicit rather than silently selecting a counterpart.

### F09 — Workflow projection drops expression control-flow context

- Priority: P0.
- Evidence: `return yes() if flag else no()` produced two supported ordinary-call stages and zero workflow alternatives.
- Cause: expression decisions and call conditional metadata exist in the analyzer but are not consistently projected into the workflow.
- Source: `threadline/analyzer.py:433`, `:464`; `threadline/workflows.py:187`.
- Plan: carry expression conditions, short-circuit behavior, and deferred/comprehension context into workflow records, including their evidence.
- [x] Acceptance: both calls remain inspectable, but the workflow makes their mutually exclusive conditions explicit.
- [x] Acceptance: Boolean short-circuit and comprehension/generator cases preserve their execution context.

### F10 — Workflow projection loses unreachable markers

- Priority: P0.
- Evidence: `return 0` followed by `dangerous()` still produced an ordinary workflow call stage.
- The detailed statement model marks the call's operation unreachable, and the method UI displays that marker.
- Source: `threadline/analyzer.py:488`; `threadline/static/app.js:301`; `threadline/workflows.py:187`.
- Plan: preserve known syntactic unreachability in the overview and downstream relationship semantics. Distinguish a source occurrence from a feasible execution step; do not imply general path-feasibility analysis.
- [x] Acceptance: the overview explicitly marks the post-return call unreachable or places it in an explicitly excluded/unreachable section.
- [x] Acceptance: caller/impact consumers can distinguish that occurrence from an ordinary call.

### F11 — Class construction expands class-definition-time calls

- Priority: P0.
- Evidence: a class with `value = register()` and an entrypoint returning `Repo()` yielded `entry → Repo → register` as ordinary workflow calls.
- Cause: a supported class target is expanded through its class-body flow as if that body were the construction-time callee.
- Source: `threadline/workflows.py:199`, `:223`.
- Existing method UI already explains that class body source is definition-time and that construction may dispatch `__new__`, `__init__`, and metaclass hooks (`threadline/static/app.js:409`). The workflow must agree with that explanation.
- Plan: distinguish class definition from object construction and expose constructor candidates with appropriate uncertainty.
- [x] Acceptance: `register()` is not presented as running because `Repo()` is called.
- [x] Acceptance: definition-time operations remain accessible as such.

### F12 — Deferred execution context needs consistent propagation

- Priority: P1, with F09–F11.
- Evidence: a coroutine-producing call was labeled deferred, while its nested body call was expanded and labeled ordinary. This observation alone does not prove the display claims immediate execution; the parent label supplies some context.
- Plan: make inherited execution context explicit for agents and users, including coroutines, generators, scheduling boundaries, and nested calls. Preserve the existing deferred labels and avoid representing body inspection as observed execution.
- [x] Acceptance: consumers can distinguish creating a deferred object from executing its body without reconstructing context from prose alone.

### F13 — Pure renames mark every method as changed source

- Priority: P1.
- Evidence: reproduced a content-identical rename; `save_order` and `Repo.save` appeared as changed source overlaps.
- Cause: an empty hunk list is interpreted as whole-file change in `_affected`.
- Source: `threadline/changes.py:172`, `:200`.
- Qualification: renamed definitions should remain available for comparison. A changed location is meaningful; the inaccurate part is labeling unchanged bodies as source-content changes.
- Existing rename comparison test expects methods in `changedMethods`; changing this behavior requires revising the contract and test, not just the condition.
- Plan: distinguish rename/move, add/delete, content overlap, and unavailable hunk information.
- [x] Acceptance: pure renames remain reviewable without implying body edits.
- [x] Acceptance: rename-plus-edit, quoted filenames, Unicode paths, and ambiguous counterpart cases retain correct behavior.

### F14 — Module-level behavior changes have no method impact records

- Priority: P1; high user/agent completeness importance.
- Evidence: changing only `FEE = 1.05` to `FEE = 1.08` reported the changed file but empty changed-method, known-caller, and possible-impact lists.
- Source: `threadline/changes.py:200` excludes module/class scopes; browser change categories at `threadline/static/app.js:563` omit changed-file records.
- Plan: first expose changes outside callable definitions and explicitly label unassessed impact. Subsequently evaluate conservative dependency candidates for constants, imports, class attributes, and configuration. Do not invent complete dataflow analysis.
- [x] Acceptance: a user and agent see the changed constant even if no function body overlaps a hunk.
- [x] Acceptance: empty callable impact lists do not imply absence of behavioral impact.
- [x] Acceptance: document that current known-caller results are direct source relationships, not a complete transitive blast-radius analysis.

### F15 — Possible impact conflates unrelated methods with the same name

- Priority: P0.
- Evidence: changing `A.get` caused a function calling `b.get()` with `b: B` to appear under possible impact, although its candidate was `B.get`.
- Cause: candidate target names are compared with changed names, rather than comparing target identities.
- Source: `threadline/changes.py:95`.
- Plan: match resolved candidate identities within a snapshot. Use explicit cross-snapshot matching only where necessary and retain its uncertainty.
- [x] Acceptance: callers whose candidates do not intersect changed targets are not included merely because a method name matches.

### F16 — Parse-error-only edits retain stale snapshots and diagnostics

- Priority: P0.
- Evidence: reproduced through the baseline viewer's HTTP refresh API. Adding `new_bad.py` containing invalid syntax left snapshot ID `c32f53f3b8334bbdef47` and the old one-error list unchanged.
- Cause: snapshot hashing includes successfully parsed file hashes, configuration, and options but omits failed-file identity/content; refresh reuses an existing model for the same ID.
- Source: `threadline/service.py:36`, `:88`; failed reads/parses at `threadline/analyzer.py:147`.
- Plan: retain a discovery manifest that accounts for parsed and failed files, their content identity where available, and relevant diagnostic state. Define behavior for unreadable or disappearing files. Include this state in snapshot identity.
- [x] Acceptance: adding, editing, removing, fixing, or newly breaking a file updates diagnostics and snapshot identity when analysis state changes.
- [x] Acceptance: failed rebuilds still preserve the prior usable review, and retained snapshots do not silently change.

### F17 — Side-effect labels use noisy substring matching

- Priority: P2.
- Evidence: reproduced false matches. `fingerprint` contains `print`; `x.address()` contains `.add`.
- Source: `threadline/analyzer.py:598`.
- Plan: match structural name segments or explicitly supported APIs, retain the word possible where appropriate, and separate heuristic effect hints from established effects. Calls not matching a keyword must not imply absence of effects.
- [x] Acceptance: those accidental substring examples do not generate effect hints solely from their spelling.

### F18 — Duplicate work and unused code

- Priority: P2.
- Confirmed: `_find_evidence` has no callers; suggested entrypoints are computed in both `analyze()` and refresh; `analyze()` eagerly constructs one `generatedWorkflows` entry while the query path independently builds/caches workflows; the catalog reparses source.
- Source: `threadline/service.py:422`, `:96`, `:224`; `threadline/analyzer.py:670`; `threadline/workflows.py:111`.
- Qualification: the browser also uses a field named `generatedWorkflows` as its client-side cache. That does not mean it consumes the eagerly generated server entry in the current summary-based loading path. Audit public consumers before deleting a returned field.
- Plan: establish one owner for each derived structure, generate workflows on demand, remove verified dead code, and avoid redundant parsing where practical.
- [x] Acceptance: public contracts remain explicit and initialization performs no unnecessary duplicate derivation.

### F19 — Model ownership and memory contracts are inconsistent

- Priority: P1 for ownership; P2 for optimization.
- Evidence: source-derived. `get_workflow()` deep-copies its result, while scope pages and metadata retain shared nested objects. `retain()` stores the supplied model directly. `current`/`model` expose mutable dictionaries.
- Source: `threadline/service.py:105`, `:224`, `:267`; refresh copy at `threadline/server.py:129`.
- Corrections to the earlier memory claim: `retain()` does not deep-copy; evidence decoration is not performed by every endpoint; deep-copying containers does not necessarily duplicate immutable source strings. Returned models do not retain the parser's AST in `files`, although ASTs contribute to analysis-time memory.
- Plan: choose and document ownership rules for the public Python API, enforce read-only snapshots or detached query DTOs consistently, then profile analysis peak memory, retained snapshots, refresh overlap, caches, and response decoration.
- [x] Acceptance: mutating a documented detached query result cannot alter a retained snapshot.
- [x] Acceptance: memory recommendations are supported by measurements, not inferred from source-byte limits alone.

### F20 — CLI omits capabilities and diagnostics needed by agents

- Priority: P0 for completeness disclosure; P1 for command coverage.
- Evidence: reproduced a valid entrypoint alongside a malformed file. `inspect` exited zero and returned workflow JSON without parse diagnostics. The command computes a summary and discards it from output.
- Source: `threadline/cli.py:34`.
- Missing CLI operations include direct method/branch inspection, evidence/source retrieval, diagnostics, and summary output that are available in the HTTP service.
- Workflow and search outputs omit `schemaVersion`; argparse errors are plain text; `changes` emits the complete result without pagination and lacks the source-root/exclusion flags supported by `review`/`inspect`.
- Plan: use a consistent response envelope and expose the evidence/completeness operations through the same interface an agent uses to discover workflows.
- [x] Acceptance: every successful result declares completeness and diagnostic counts, including partial analysis.
- [x] Acceptance: evidence identifiers can be resolved through the same documented agent interface.
- [x] Acceptance: errors are machine-readable in JSON mode, with documented exit semantics.
- [x] Acceptance: response schema version and omission/truncation state are explicit.

### F21 — CLI pagination is not pinned to a retained snapshot

- Priority: P1.
- Evidence: source-derived. Each `inspect` invocation creates a new store and analyzes the repository; the CLI has no snapshot-selection/session option.
- Source: `threadline/cli.py:22`, `:35`.
- Impact: repeated pages repeat indexing and can describe different source if files change between commands. HTTP already supports querying retained snapshot IDs.
- Plan: provide a persistent local session or saved analysis artifact with explicit snapshot selection; reject mismatches rather than silently mixing pages.
- [x] Acceptance: continued pages and evidence retrieval remain tied to the selected snapshot even if the working tree changes.

### F22 — Agent output is verbose relative to its useful content

- Priority: P2.
- Evidence: the two-call direct-function fixture produced about 6.6 KB of pretty-printed workflow JSON, repeating spans/evidence across stages and links.
- Plan: support compact serialization, shared evidence references, and detail selection without deleting uncertainty, control context, or provenance. Measure representative bytes and useful facts per query.
- [x] Acceptance: a compact result is meaningfully smaller while every claim remains traceable.

### F23 — Validation measures infrastructure more strongly than usefulness

- Priority: P1.
- Evidence: 63 test methods, 14 independently annotated semantic cases, 11 cases permitting `unknown`, and four direct-target annotations in the reviewed checkout.
- Qualification: permitting unknown is correct for some cases and protects against overclaiming; it does not itself demonstrate adequate resolution coverage.
- Public corpus checks establish parsing/accounting, evidence availability, budgets, installation, and some specific certainty expectations, not complete semantic accuracy or successful user comprehension.
- The corpus workflow pagination loop follows the stage cursor; verify continuation of alternatives and uncertainties separately when extending this coverage.
- Source: `test_semantic_accuracy.py:24`; `tests/online_repo_smoke.py:109`, `:145`; `tests/semantic_cases.json`.
- Plan: measure false-supported relationships, candidate recall for resolvable cases, argument-binding accuracy, preserved execution context, navigation continuity, and task completion separately.
- [x] Acceptance: operational pass rates are never presented as semantic accuracy percentages.
- [x] Acceptance: candidate-resolution regressions fail even where returning unknown would remain conservative but unnecessarily unhelpful.

## Maintainability architecture plan

### Preserve module boundaries; make semantic phases explicit

The existing separation is worth keeping. Refactor incrementally around these conceptual phases:

1. Discovery and source manifest: file bytes, exclusions, failures, configuration, language/version context.
2. Syntax and lexical binding: scopes, all name-binding constructs, imports, declarations, unique occurrences.
3. Candidate resolution: functions, modules, classes, receivers, attributes, inheritance, and uncertainty provenance.
4. Argument binding and execution context: distinguish target identity from how and when a call can execute.
5. Canonical semantic records: typed scopes, calls, spans, bindings, diagnostics, and relationships.
6. Projections: method view, workflow overview, callers/changes, and agent responses preserve canonical facts.
7. Delivery: snapshot queries, HTTP, CLI, and browser presentation.

Do not make the workflow layer rediscover Python semantics independently. A rule established in the method model must survive projection, or its omission must be explicit.

### Typed data contracts

- [x] Introduce `TypedDict` definitions or small dataclasses for spans, symbols, call occurrences, target candidates, argument bindings, execution contexts, diagnostics, snapshots, and paged responses.
- [x] Separate target certainty, receiver certainty, argument-binding certainty, execution context, and analysis completeness.
- [x] Define closed status/reason values while allowing documented extension; recursive expansion is not the same category as target-resolution certainty.
- [x] Decide internal naming and serialization conventions; do not let mixed Python/JSON naming obscure ownership or semantics.
- [x] Type-check module boundaries and enforce response contract tests.
- [x] Add schema/version changes deliberately when public response semantics change.

### Code health

- [x] Expand dense semicolon-heavy statements in `cli.py`, `changes.py`, `workflows.py`, and related paths into reviewable control flow as those areas are changed.
- [x] Extract named helpers for binding rules and certainty decisions instead of lengthening one resolver conditional.
- [x] Consolidate or clearly document test layout: root `test_*.py` files and `tests/` support/integration files currently split the suite.
- [x] Keep behavior changes separate from broad mechanical reformatting where practical.
- [x] Remove unused helpers only after checking public or indirect consumers.
- [x] Keep release docs consistent with the package's beta status. Some capability/validation prose still describes an alpha state or older revision; retain historical records but label their applicability.

### Performance and resource work

- [x] Profile before optimizing: analysis CPU, parser/catalog work, source/model memory, retained snapshots, overlapping refresh, workflow generation, serialization, and response copying.
- [x] Remove duplicate startup work and eager derived data before changing resource budgets.
- [x] Preserve cache bounds, explicit truncation, snapshot eviction, and one-refresh-at-a-time publication.
- [x] Measure Python object overhead separately from serialized JSON size.
- [x] Evaluate Git baseline materialization cost, which currently performs per-file size/blob operations, on representative repositories before changing its architecture.
- [x] Measure time to first useful method and source excerpt, not only total analysis time.
- [x] Treat analysis time checks as cooperative, not an OS-level CPU/memory sandbox.

## Agent interface plan

### Required investigation loop

An agent should be able to discover a symbol, inspect its method and workflow, resolve candidates, retrieve exact evidence, check completeness, and continue against the same snapshot. It should not have to infer missing analysis state from an empty list or switch to undocumented HTTP routes to satisfy the source-review workflow.

### Proposed capabilities

Expose consistent operations for:

- Summary and analysis diagnostics.
- Symbol discovery and exact selection.
- Method, scope, and branch structure.
- Compact workflow with preserved execution context.
- Candidate-target inspection.
- Source retrieval by evidence ID or bounded file span.
- Change records, changed files, before/after source, current callers, baseline callers, and possible/unassessed impact.
- Session/snapshot selection and continuation.

These are interface requirements, not a commitment to particular command names, a hosted service, or an MCP integration. A small CLI/session interface can satisfy them while retaining the local source-only product scope.

### Response contract

Every response should include or unambiguously reference:

- Schema version and operation identity.
- Snapshot identity and relevant analysis options.
- Completeness state, parse-failure count, and skipped/unmodeled counts.
- Pagination cursors, totals, truncation, and omitted-record information.
- Target certainty and machine-readable reason codes.
- Execution context where relevant.
- Retrievable evidence references.
- Structured error information and documented exit semantics.

Exit zero can mean a query succeeded despite incomplete analysis, but incompleteness must be visible. Consider an explicit strict-completeness mode for CI rather than silently redefining all partial analyses as fatal errors.

### Agent-specific acceptance checks

- [x] An agent can identify and disclose a malformed file from its initial query response.
- [x] An agent can retrieve original source for every cited evidence ID without importing the target.
- [x] An agent cannot accidentally combine pages from different snapshots without an explicit mismatch.
- [x] Unknown-result reasons guide a next step, such as inspecting an initializer, base class, import, or unavailable source.
- [x] Sparse changed-method lists do not conceal file-level changes or unassessed impact.
- [x] Compact output retains all uncertainty and execution-context information necessary to avoid unsupported conclusions.
- [x] Repository text is always treated as evidence, never agent instructions. Hashes establish content identity, not truth or authority.

## Implementation order and release criteria

### Phase 0 — Freeze evidence and expectations

- [x] Convert the independent reproductions below into small regression fixtures with expectations written from Python semantics and intended product behavior.
- [x] Record supported versus possible versus unknown expectations separately from expected candidate identities.
- [x] Add invariant checks for unique occurrences and consistent projections.
- [x] Keep known limitations visible while fixes are in progress.

### Phase 1 — Correct misleading results and hidden incompleteness

Address F04–F07, F09–F11, F15–F16, and the diagnostic disclosure portion of F20.

- [x] Eliminate reproduced false-supported lexical/binding relationships.
- [x] Correct explicit versus implicit receiver mapping.
- [x] Eliminate call/stage identity collisions.
- [x] Preserve branch conditions and known unreachable markers in workflows.
- [x] Separate definition-time class operations from construction.
- [x] Match impact by candidate identity.
- [x] Refresh diagnostics when failed-source state changes.
- [x] Make partial CLI analysis visible.

Gate: none of the reproduced misleading-result fixtures may regress, and all returned claims remain source-traceable. These fixes protect trust before expanding the analyzer's reach.

### Phase 2 — Complete common OO journeys

Address F01–F03 and candidate-navigation requirements.

- [x] Infer class-associated attribute candidates from annotations and constructor assignments.
- [x] Follow statically identifiable base-class methods conservatively.
- [x] Resolve dotted module and chained receiver forms.
- [x] Preserve existing inline possible-target opening and add explicit overview expansion where useful.
- [x] Keep overrides, descriptors, factories, multiple inheritance, reassignment, and unresolved initialization conservative.

Gate: a reviewer can navigate endpoint → service → repository on the representative fixture, explain remaining uncertainty, and return to the caller. Do not promote dynamic dispatch to supported merely to make the graph longer.

### Phase 3 — Make change review complete about its limits

Address F08, F13–F14, plus continuity and comparison behavior.

- [x] Distinguish rename-only records from body edits.
- [x] Expose changed files and changes outside definitions.
- [x] Preserve current/baseline/possible relationships as separate categories.
- [x] Improve symbol continuity without hiding ambiguous matches.
- [x] Document direct-call coverage and unassessed/transitive/data-dependency limitations.

Gate: pure renames, constant edits, additions, deletions, renamed edits, duplicate names, parse failures, and concurrent working-tree changes all produce honest, navigable results.

### Phase 4 — Make agent queries consistent and complete

Address the remaining F20–F22 items and the agent interface contract.

- [x] Expose summary, diagnostics, method/branch inspection, source, and bounded changes.
- [x] Version every response envelope and structure errors.
- [x] Implement snapshot-pinned continuation through a persistent session or saved artifact.
- [x] Add compact output without deleting evidence or uncertainty.

Gate: an agent can complete discovery → inspection → evidence → completeness disclosure using one documented interface and one retained snapshot.

### Phase 5 — Reduce maintenance and resource cost

Address F17–F19, typed models, duplicate parsing/derivation, dead code, and code readability. Begin types and ownership work earlier where required by semantic fixes; avoid making a wholesale rewrite a prerequisite.

Gate: public ownership is documented and tested, changed modules are easier to review, and performance changes have representative measurements.

### Phase 6 — Validate comprehension before stable release

Address F23 and the existing human-review protocol.

- [ ] Complete the three documented uncoached reviewer sessions; include assistive-technology feedback where possible.
- [ ] Include the plain-function and OO journeys rather than only a favorable example.
- [ ] Ask participants to explain inputs, validation failures, a cross-file mapping, return destination, final output, and one uncertain relationship using source evidence.
- [ ] Ask them to distinguish a rename, body edit, constant edit, deleted helper, and historical caller.
- [ ] Check branch expansion, continuation, comparison, and recovery of caller position.
- [ ] Record pauses, assistance, wrong turns, unsupported conclusions, and completion independently from UI latency.
- [ ] Do not invent pass/fail speed thresholds before observing representative sessions.
- [x] Repeat local automated semantic, service, server, Chromium, Chrome accessibility, and wheel checks on this implementation candidate; the cross-platform release matrix remains a separate open gate.

Gate: human observations exist, comprehension failures are addressed or explicitly scoped, and validation claims identify the candidate revision and their actual scope.

## Regression fixture specification

### Eighteen fresh source scenarios

These scenarios were parsed through the baseline CLI. Results describe the reviewed revision, not current behavior.

| Fixture | Observed calls/results | Required interpretation |
| --- | --- | --- |
| `direct` | `clean`: supported; `x.strip`: unknown | Direct cross-file navigation works; arbitrary receiver inference remains limited |
| `injected` | `self.repo.get`: unknown | Constructor-injected dependency candidate missing |
| `annotated_attr` | `self.repo.get`: unknown | Explicit attribute annotation does not bridge methods |
| `inherited` | `self.helper`: unknown | Base-class lookup missing |
| `local_instance` | `Repo`: supported; `x.get`: possible | Useful conservative candidate control |
| `chained` | `Repo`: supported; `Repo().get`: unknown; one duplicate ID | Receiver inference and occurrence identity defects |
| `dotted` | `pkg.repo.get`: unknown | Dotted module path resolution gap |
| `alias_module` | `r.get`: supported | Equivalent alias control resolves |
| `shadow_loop` | `helper`: supported global target | Incorrect certainty after loop binding |
| `shadow_with` | `helper`: supported global target | Incorrect certainty after context target binding |
| `shadow_walrus` | `helper`: supported global target | Incorrect certainty after assignment expression |
| `class_scope` | bare `helper`: supported sibling method | Incorrect lexical lookup |
| `branch_only` | `ValueError`: external; two alternatives; empty `outcomes` | Workflow is call-focused; local method/source still needed for return behavior |
| `unreachable` | `dangerous`: supported ordinary call | Known unreachable context omitted from overview |
| `conditional_expr` | `yes`, `no`: supported ordinary calls; zero alternatives | Expression branch context omitted |
| `deferred` | `task`: deferred coroutine; nested `dangerous`: ordinary | Parent timing label exists; inherited context should be explicit |
| `unbound` | `Repo.get`: supported, incorrect argument mapping | Correct target identity does not establish correct binding |
| `parse_failure` | Exit zero; valid entry workflow; no parse diagnostics | Successful query conceals incomplete analysis |

### Essential self-contained reproductions

The following snippets must be stored as source fixtures and not imported or executed by source-review tests.

#### Constructor dependency and annotation

```python
class Repo:
    def get(self, key):
        return key

class Service:
    def __init__(self, repo: Repo):
        self.repo = repo

    def entry(self, key):
        return self.repo.get(key)
```

Also cover `self.repo: Repo = Repo()` in `__init__`, reassignment, and conflicting candidates.

#### Inherited method

```python
class Base:
    def helper(self):
        return 1

class Service(Base):
    def entry(self):
        return self.helper()
```

#### Class namespace is not a method's enclosing lexical namespace

```python
class Example:
    def method(self):
        return 1

    def entry(self):
        return method()
```

The bare name must not be resolved to the sibling method on this source alone.

#### Shadowing

```python
def helper():
    return 1

def loop_shadow(callbacks):
    for helper in callbacks:
        helper()

def with_shadow(ctx):
    with ctx as helper:
        helper()

def walrus_shadow(callback):
    if helper := callback:
        helper()

def unpack_shadow(callbacks):
    helper, other = callbacks
    return helper()
```

#### Explicit receiver binding

```python
# repo.py
class Repo:
    def get(self, k):
        return k

def plain(self, k):
    return k

# app.py
import repo
from repo import Repo

def entry():
    return Repo.get(Repo(), 4)

def module_call():
    return repo.plain('receiver', 4)
```

Expected explicit mappings are `Repo() → self`, `4 → k`, and `'receiver' → self`, `4 → k`. Neither class/module spelling is an implicit receiver in these examples.

#### Call identity and execution context

```python
def yes():
    return 1

def no():
    return 0

def conditional(flag):
    return yes() if flag else no()

def unreachable():
    return 0
    yes()

class Repo:
    def get(self):
        return 1

def chained():
    return Repo().get()
```

#### Definition-time class body

```python
def register():
    return 1

class Repo:
    value = register()

def entry():
    return Repo()
```

The workflow must not attribute `register()` to invoking `Repo()`.

#### Same-name impact

```python
class A:
    def get(self):
        return 1

class B:
    def get(self):
        return 10

def caller(b: B):
    return b.get()
```

Commit a baseline, change only `A.get` to return `2`, and compare. `caller` must not be included just because `B.get` shares the name `get`.

#### Change and refresh cases

- Commit a file containing multiple definitions, rename it without content edits, and compare: preserve rename navigation without body-change labels.
- Commit `FEE = 1.05` used by a function; change only that assignment to `1.08`: show the file-level edit and unassessed/dependency impact honestly.
- Start a viewer with one invalid file, add a second invalid file, and refresh: the new diagnostic and new analysis identity must appear.
- Query a valid entrypoint beside an invalid file through the CLI: disclose partial analysis in the response.

## Existing validation and resource context

These values come from repository documentation inspected during the review. They are not new audit measurements or guarantees for the current working environment.

### Historical validation record

`docs/VALIDATION.md` records validation on 2026-09-14 for application/test commit `8c9d088`, including:

- 51 tests in each Linux/macOS × Python 3.12/3.13/3.14 matrix job at that revision.
- JavaScript syntax checks and 18 Chromium browser checks.
- Clean-wheel installation outside the checkout in six matrix jobs.
- 20 Chrome and 17 native Safari accessibility checks, with zero reported axe violations in six audited states.
- Seven pinned public-source cases within documented time and peak-memory budgets.

The 51-test result belongs to the historical commit. The current implementation passed 109 local Python tests; its cross-platform matrix is still pending.

### Historical public-corpus measurements

| Repository | Files | Definitions | Analysis | Query sequence | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flask | 24 | 400 | 0.552 s | 0.023 s | 38.8 MiB |
| Requests | 20 | 268 | 0.413 s | 0.018 s | 35.4 MiB |
| FastAPI | 509 | 1,049 | 1.963 s | 0.067 s | 87.7 MiB |
| Celery | 164 | 3,074 | 3.991 s | 0.161 s | 150.4 MiB |
| Django | 883 | 9,411 | 13.796 s | 0.545 s | 479.2 MiB |
| OpenTelemetry | 91 | 955 | 1.082 s | 0.047 s | 60.1 MiB |
| Pants | 1,704 | 10,203 | 21.678 s | 0.821 s | 692.3 MiB |

The documented observations are single runs, exclude Git fetch from analysis timings, and are not statistical latency guarantees or semantic accuracy measurements.

### Existing application bounds

- Source: 2 MiB per file, 64 MiB total source, 10,000 Python files, two million AST nodes.
- Analysis: cooperative 60-second checks; expensive individual parser operations are not preempted.
- Git: 30 seconds per operation, 64 MiB captured-output bound, and aggregate time checks between baseline/diff operations.
- HTTP: IPv4 loopback, eight concurrent requests, five-second socket I/O timeout, 4 MiB response maximum.
- Workflows: up to 500 stages and 100 nested call levels, with explicit truncation.
- Workflow cache: 32 entries and 16 MiB serialized data per store; Python object overhead is additional.
- Browser: explicit continuation for workflow records, statements, branches, and bounded source excerpts; comparisons page retained lines and do not align moved statements.
- Refresh: one rebuild at a time, publication after successful rebuild, and prior snapshot availability on failure.

Do not weaken these bounds to mask performance regressions. Revisit provisional budgets using measurements and human feedback.

## Evidence inventory

### Repository sources

- `threadline/analyzer.py`: discovery, scopes, imports, bindings, resolution, argument mapping, statement/expression modeling, coverage, and eager derived data.
- `threadline/workflows.py`: entrypoints, catalogs, event candidates, and workflow projection.
- `threadline/service.py`: snapshot identity/retention, query contracts, caching, evidence, diagnostics, and comparisons.
- `threadline/changes.py`: baseline materialization, hunks, changed definitions, callers, and possible impact.
- `threadline/cli.py`: available commands, JSON output, rebuilding, and error handling.
- `threadline/server.py`: local serving, refresh publication, and bounds.
- `threadline/static/app.js` and `workflow.js`: detailed-method and overview differences, source navigation, candidate opening, coverage, changes, and refresh UI.
- `test_analyzer.py`, `test_changes.py`, `test_service.py`, `test_server.py`, `test_workflows.py`, `test_semantic_accuracy.py`, `test_online_repo_smoke.py`: baseline and expanded regression coverage.
- `tests/semantic_cases.json`, `tests/online_repo_smoke.py`, `tests/online_repositories.json`: semantic expectations and public-corpus scope.
- `.github/workflows/ci.yml`: configured platform, browser, accessibility, semantic, corpus, and wheel gates.
- `docs/USING_THREADLINE.md`, `CAPABILITIES.md`, `SEMANTIC_ACCURACY.md`, `VALIDATION.md`, `PERFORMANCE.md`, `ACCESSIBILITY.md`, `REVIEWER_SESSION_KIT.md`, `REVIEWER_RESULTS.md`, and `CONTRIBUTING.md`: user journeys, limitations, validation records, and contribution expectations.

Line references in this plan refer to the reviewed revision and will move as changes are implemented.

### Fixture context

One baseline API fixture parsed three of four discovered files and represented
30/30 statements and 13/13 call sites while leaving a dependency unresolved and
reporting a parse failure. Representation counts alone do not establish semantic
accuracy or complete repository coverage. Focused versions of the reproduced cases
now live in the regression suite.

### External primary references

- [Python execution model](https://docs.python.org/3/reference/executionmodel.html): name-binding constructs, local/global/nonlocal rules, class scope, and definition execution.
- [Python descriptor guide](https://docs.python.org/3.14/howto/descriptor.html): instance versus class access and method binding.
- [Python compiler symbol tables](https://docs.python.org/3/library/symtable.html): potential support for lexical-scope analysis, not a replacement for receiver inference.
- [Python AST documentation](https://docs.python.org/3/library/ast.html): source positions and UTF-8 byte offsets; preserve exact evidence when changing identifiers.

## Completion checklist

- [x] Every finding F01–F23 has a disposition: fixed with evidence, intentionally scoped with visible limitations, or deferred with rationale.
- [x] All reproduced correctness and hidden-incompleteness issues have regression coverage.
- [x] Common OO and plain-function user journeys are both validated.
- [x] Method, workflow, changes, and agent representations agree on semantic context.
- [x] Snapshot identity and ownership contracts are enforced.
- [x] Agent results expose completeness and retrievable evidence within a documented, versioned interface.
- [x] Rename, module-level edit, deletion, parse-failure, and unrelated-name impact scenarios are covered.
- [ ] Required automated checks run against the actual candidate; historical records remain clearly labeled.
- [ ] Real reviewer sessions are completed and recorded without invented observations.
- [x] Documentation states remaining limits accurately and does not imply runtime proof, full impact coverage, or general semantic accuracy from infrastructure checks.
