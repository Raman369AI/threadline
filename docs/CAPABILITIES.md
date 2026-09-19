# Capability matrix (alpha)

[Documentation home](README.md) · [Project home](../README.md)

| Pattern | Current behavior | Confidence limit |
| --- | --- | --- |
| Plain Python functions and methods | Local statements, branches, loops, exceptions, calls, returns, source spans | Dynamic dispatch and path feasibility are not proven. |
| Flat and `src/` packages | Recursive parse and common import resolution | Split namespace roots are covered by fixtures and OpenTelemetry; Pants covers a larger monorepo. Specify source roots when import roots are ambiguous. |
| FastAPI-style routes | Recognized decorator starts, declared parameters and response model | Dependency resolution and framework runtime injection are not executed. |
| Standard project scripts | Read `pyproject.toml` script declarations as data | Dynamic registration and `setup.py` execution are unsupported. |
| Publish/subscribe expressions | Possible matching event route with producer/registration evidence | Bus identity and callback execution are unresolved. |
| Async and generators | Deferred execution and known scheduling boundaries labeled | Scheduling outcome and interleaving are not observed. |
| Git changes | Changed definitions, integrated before/after source, current and baseline callers, possible impact, added/deleted files | Diff mapping is syntactic and uses retained source. Rename, quoted-path, and concurrent-edit cases have regression coverage. |
| Flask and queue frameworks | Generic Python review validated on pinned Flask and Celery source | Framework-specific dispatch and task lifecycle links are not modeled. |
| Django | Generic Python review validated on pinned Django source | Middleware callbacks remain unknown; member dispatch remains possible. Framework runtime execution is not modeled. |

The independent [semantic accuracy corpus](SEMANTIC_ACCURACY.md) covers aliases,
inheritance, decorators, and callbacks with manually authored expectations. It reports
incorrect supported classifications separately from unresolved calls.
