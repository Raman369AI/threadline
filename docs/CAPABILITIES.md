# Capability matrix (beta)

[Documentation home](README.md) · [Project home](../README.md)

| Pattern | Current behavior | Confidence limit |
| --- | --- | --- |
| Plain Python functions and methods | Local statements, branches, loops, exceptions, calls, returns, source spans; common constructor-injected and inherited method candidates | Inferred object-oriented calls remain possible rather than proved. Dynamic dispatch, factory returns, descriptors, and path feasibility are not established. |
| Per-method data flow | Source-backed inputs, name and object-state changes, intermediate values, uses and outputs, with upstream/downstream traces and linked model declarations | A source relationship is not an observed value or executed branch. Aliases, indirect mutation, dynamic calls, and external libraries can stop at explicit gaps. |
| Model reference | Indexed class declarations and their fields, including fields unused by the selected method; method-assigned fields are labeled separately. More than 80 referenced definitions load in snapshot-pinned pages. | Imported definitions outside indexed source remain external. A source declaration is not a runtime schema. Very large individual declarations may require opening their paged source. |
| Literal template context | Context keys in a source-proven `Jinja2Templates.TemplateResponse` call and bounded candidates for directly named template files, with direct template expressions and later literal client-fetch references | A shadowed or unknown `TemplateResponse` provider remains a gap. Dynamic template directories, duplicate names, generated HTML, and browser execution are not resolved. A client fetch is a separate later request. |
| Flat and `src/` packages | Recursive parse and common import resolution | Split namespace roots are covered by fixtures and OpenTelemetry; Pants covers a larger monorepo. Specify source roots when import roots are ambiguous. |
| FastAPI-style routes | Recognized decorator starts, declared parameters and response model | Dependency resolution and framework runtime injection are not executed. |
| Standard project scripts | Read `pyproject.toml` script declarations as data | Dynamic registration and `setup.py` execution are unsupported. |
| Publish/subscribe expressions | Possible matching event route with producer/registration evidence | Bus identity and callback execution are unresolved. |
| Async and generators | Deferred execution and known scheduling boundaries labeled | Scheduling outcome and interleaving are not observed. |
| Python 3.12 type aliases | Calls in `type Alias = ...` values carry a deferred evaluation context | Other type-parameter annotation-scope forms are not fully modeled; no alias value is evaluated by Threadline. |
| Git changes | Changed definitions, rename-only records, files and edits outside definitions, before/after source, current and baseline callers, possible impact | Diff mapping is syntactic and uses retained source. Unassessed edits can affect behavior beyond direct callers. Rename, quoted-path, and concurrent-edit cases have regression coverage. |
| Related tests | Tests that call, reach through up to three calls, or request the route of a method; name-only candidates; methods a test exercises; expandable test-method source beneath code | Links use the same static call resolution. Tests are not run, coverage is not measured, and fixtures, parametrization, and mocks are not modeled. |
| Flask and queue frameworks | Generic Python review validated on pinned Flask and Celery source | Framework-specific dispatch and task lifecycle links are not modeled. |
| Django | Generic Python review validated on pinned Django source | Middleware callbacks remain unknown; member dispatch remains possible. Framework runtime execution is not modeled. |

The independent [semantic accuracy corpus](SEMANTIC_ACCURACY.md) covers aliases,
inheritance, decorators, and callbacks with manually authored expectations. It reports
incorrect supported classifications separately from unresolved calls.

Structured CLI queries expose completeness, source evidence, and snapshot-pinned
continuation. The analyzer reads source only; neither a supported static target nor a
workflow stage proves runtime execution.
