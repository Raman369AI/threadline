# Threadline

[Documentation](docs/README.md) · [Getting started](docs/USING_THREADLINE.md) · [Capabilities](docs/CAPABILITIES.md) · [Contributing](CONTRIBUTING.md)

Threadline is a visual Python code reviewer for understanding a workflow before running it.

Select any function or method. Threadline shows its inputs and outputs, local control flow, calls into other files, return destinations, effects, and unresolved targets. Select any step to inspect the exact original source while keeping the surrounding workflow visible.

Threadline parses source. It does not import or execute the project being reviewed.

## What you see

```text
Request
  │ request fields
  ▼
Validate
  ├─ invalid → early return
  │ validated items + coupon
  ▼
Calculate total
  │ subtotal − discount + tax
  ▼
Save order
  │ persisted order
  ▼
Response
```

The interface provides three levels without sending you to another page:

- **Workflow:** the flow starting from the selected method.
- **Focused step:** branches, calls, transformations, effects, and returns at that point.
- **Source:** the exact code supporting the selected operation.

Calls stay nested under their call site. Loops appear once, recursion is marked, and possible or unknown targets remain visibly uncertain.

## Requirements

- Python 3.12 or later
- A local directory containing Python source
- A modern browser

The target project does not need to be installed and its dependencies do not need to be available.

## Install

From a source checkout:

```bash
git clone https://github.com/Raman369AI/threadline.git
cd threadline
python3 -m venv .venv
.venv/bin/python -m pip install .
```

If you have a locally built or shared release wheel:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install threadline_review-0.2.0a1-py3-none-any.whl
```

## Review a repository

```bash
.venv/bin/threadline review /path/to/python-repository
```

Threadline prints and opens a local URL, normally <http://127.0.0.1:4173/>. Use `--port 4180` if that port is occupied.

In the browser:

1. Open **Find a method** and search for any function or method.
2. Select it to see its complete local logic and original source.
3. Choose **Trace this method across files** to follow resolvable calls from that point.
4. Expand branches or calls in place; use **Back to caller** to resume where you left off.
5. Open **Coverage** to see parse failures, excluded paths, and unmodeled call syntax.

Try the bundled example:

```bash
.venv/bin/threadline review example
```

## Review a Git change

Run Threadline from the working tree and provide the Git baseline:

```bash
.venv/bin/threadline review /path/to/git-repository --base HEAD
```

Change review distinguishes modified methods, deleted methods, known source-linked callers, and possible impact. It reads Git objects without checking out or executing either version.

## Structured output

The browser is the primary interface. JSON commands are available for scripts and CI:

```bash
threadline inspect /path/to/repository --query create_order
threadline inspect /path/to/repository --entrypoint package.module:create_order
threadline changes /path/to/repository --base HEAD
```

Use `--source-root path` to select an application source directory. Repeat `--exclude path` for generated, vendored, or irrelevant directories.

## What static analysis can establish

Threadline labels call relationships according to their evidence:

- **Supported:** the source resolves one local target.
- **Possible:** the source identifies one or more candidates but runtime dispatch remains uncertain.
- **External:** the target belongs outside the analyzed source.
- **Unknown:** the source does not identify a target.

These labels describe source structure. They do not represent an observed execution or prove that the code is correct.

See the [capability matrix](docs/CAPABILITIES.md), [usage guide](docs/USING_THREADLINE.md), and [validation record](docs/VALIDATION.md) for details.

## Documentation

Start with the **[documentation hub](docs/README.md)** for installation, everyday review, analysis limits, and project maintenance.

| I want to… | Read |
| --- | --- |
| Review a repository or Git change | [Usage guide](docs/USING_THREADLINE.md) |
| Understand supported syntax and uncertain calls | [Capability matrix](docs/CAPABILITIES.md) |
| Check test results and platform coverage | [Validation record](docs/VALIDATION.md) |
| Understand keyboard access and browser checks | [Accessibility](docs/ACCESSIBILITY.md) |
| Check resource limits for a larger repository | [Performance and resource budgets](docs/PERFORMANCE.md) |
| Report a vulnerability privately | [Security policy](SECURITY.md) |

## Validation

The self-contained suite covers source non-execution, exact statement and call accounting, branches, exceptions, loops, recursion, cross-file calls, snapshot evidence, Git changes, HTTP restrictions, packaging, and browser behavior.

A separate acceptance corpus tests pinned versions of [Flask](https://github.com/pallets/flask), [Requests](https://github.com/psf/requests), [FastAPI](https://github.com/fastapi/fastapi), [Celery](https://github.com/celery/celery), [Django](https://github.com/django/django), [OpenTelemetry](https://github.com/open-telemetry/opentelemetry-python), and [Pants](https://github.com/pantsbuild/pants). See [public repository validation](docs/ONLINE_VALIDATION.md).

```bash
python3 -m unittest discover -v
node --check threadline/static/app.js
node --check threadline/static/workflow.js
python3 tests/browser_smoke.py
python3 tests/online_repo_smoke.py --report artifacts/online-validation.json
python3 -m pip wheel . --no-deps -w dist
python3 tests/release_smoke.py dist/*.whl
```

## Project status

Threadline is a developer alpha. The standalone application and wheel are usable now. The expanded corpus, performance budgets, Linux/macOS matrix, native Safari, accessibility checks, and clean-wheel installs pass. The maintainer owns the three first-time reviewer sessions and final release sign-off. See the [release checklist](docs/RELEASE_CHECKLIST.md) and [resource budgets](docs/PERFORMANCE.md).

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md), and the [MIT License](LICENSE).
