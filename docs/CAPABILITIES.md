# Capability matrix (alpha)

| Pattern | Current behavior | Confidence limit |
| --- | --- | --- |
| Plain Python functions and methods | Local statements, branches, loops, exceptions, calls, returns, source spans | Dynamic dispatch and path feasibility are not proven. |
| Flat and `src/` packages | Recursive parse and common import resolution | Complex namespace/monorepo import paths may need manual entrypoint selection. |
| FastAPI-style routes | Recognized decorator starts, declared parameters and response model | Dependency resolution and framework runtime injection are not executed. |
| Standard project scripts | Read `pyproject.toml` script declarations as data | Dynamic registration and `setup.py` execution are unsupported. |
| Publish/subscribe expressions | Possible matching event route with producer/registration evidence | Bus identity and callback execution are unresolved. |
| Async and generators | Deferred execution and known scheduling boundaries labeled | Scheduling outcome and interleaving are not observed. |
| Git changes | Changed definitions, known callers, possible impact, added/deleted files | Diff mapping is syntactic; rename/line handling needs broader corpus validation. |
| Flask and queue frameworks | Generic Python review validated on pinned Flask and Celery source | Framework-specific dispatch and task lifecycle links are not modeled. |
| Django | Generic Python review | No dedicated corpus case or framework lifecycle model yet. |
