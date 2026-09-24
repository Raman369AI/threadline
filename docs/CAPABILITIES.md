# Capability matrix (beta)

[Documentation home](README.md) · [Project home](../README.md)

| Pattern | Current behavior | Confidence limit |
| --- | --- | --- |
| Plain Python functions and methods | Local statements, branches, loops, exceptions, calls, returns, source spans; common constructor-injected and inherited method candidates | Inferred object-oriented calls remain possible rather than proved. Dynamic dispatch, factory returns, descriptors, and path feasibility are not established. |
| Flat and `src/` packages | Recursive parse and common import resolution | Split namespace roots are covered by fixtures and OpenTelemetry; Pants covers a larger monorepo. Specify source roots when import roots are ambiguous. |
| FastAPI-style routes | Recognized decorator starts, declared parameters and response model | Dependency resolution and framework runtime injection are not executed. |
| Standard project scripts | Read `pyproject.toml` script declarations as data | Dynamic registration and `setup.py` execution are unsupported. |
| Publish/subscribe expressions | Possible matching event route with producer/registration evidence | Bus identity and callback execution are unresolved. |
| Async and generators | Deferred execution and known scheduling boundaries labeled | Scheduling outcome and interleaving are not observed. |
| Python 3.12 type aliases | Calls in `type Alias = ...` values carry a deferred evaluation context | Other type-parameter annotation-scope forms are not fully modeled; no alias value is evaluated by Threadline. |
| Git changes | Changed definitions, rename-only records, files and edits outside definitions, before/after source, current and baseline callers, possible impact | Diff mapping is syntactic and uses retained source. Unassessed edits can affect behavior beyond direct callers. Rename, quoted-path, and concurrent-edit cases have regression coverage. |
| Flask and queue frameworks | Generic Python review validated on pinned Flask and Celery source | Framework-specific dispatch and task lifecycle links are not modeled. |
| Django | Generic Python review validated on pinned Django source | Middleware callbacks remain unknown; member dispatch remains possible. Framework runtime execution is not modeled. |

The independent [semantic accuracy corpus](SEMANTIC_ACCURACY.md) covers aliases,
inheritance, decorators, and callbacks with manually authored expectations. It reports
incorrect supported classifications separately from unresolved calls.

Structured CLI queries expose completeness, source evidence, and snapshot-pinned
continuation. The analyzer reads source only; neither a supported static target nor a
workflow stage proves runtime execution.
