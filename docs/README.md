# Threadline documentation

[Project home](../README.md) · [Get started](USING_THREADLINE.md) · [Capabilities](CAPABILITIES.md)

Threadline helps you review Python source in a local browser before running it. It shows control flow, calls, return destinations, and source evidence. Analysis reads source and Git objects without importing, installing, or executing the target project.

## Start here

You need Python 3.12 or later, a modern browser, and a local Python repository. The target repository's dependencies are not required.

```bash
git clone https://github.com/Raman369AI/threadline.git
cd threadline
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/threadline review example
```

Open the local URL printed by Threadline. Choose **Find a method**, select a function, and inspect its steps and original source. Choose **Trace this method across files** to follow resolvable calls.

To review your own repository:

```bash
.venv/bin/threadline review /path/to/python-repository
```

Continue with the [usage guide](USING_THREADLINE.md) for Git change review, source roots, exclusions, and structured output.

## Review code

| Guide | What it covers |
| --- | --- |
| [Using Threadline](USING_THREADLINE.md) | Installation, local review, Git baselines, and CLI commands. |
| [Capabilities and limits](CAPABILITIES.md) | Supported Python structures, evidence, and unresolved behavior. |
| [Accessibility](ACCESSIBILITY.md) | Keyboard navigation, browser checks, and remaining manual checks. |
| [Performance and resource budgets](PERFORMANCE.md) | Analysis limits, measured repository sizes, and provisional budgets. |

Call labels describe static evidence: **supported**, **possible**, **external**, or **unknown**. They do not establish observed execution or prove correctness. Check **Coverage** in the browser for parse failures, exclusions, and unmodeled syntax.

## Check validation and release readiness

Threadline is currently a developer alpha. These records explain what has been checked and what still needs maintainer sign-off.

| Record | What it covers |
| --- | --- |
| [Validation](VALIDATION.md) | Self-contained tests, browser checks, platform coverage, and installation checks. |
| [Public repository validation](ONLINE_VALIDATION.md) | The pinned source-only corpus and how to reproduce acceptance checks. |
| [Release checklist](RELEASE_CHECKLIST.md) | Engineering release gates and maintainer responsibilities. |
| [First-time reviewer sessions](REVIEWER_SESSIONS.md) | The protocol for the three maintainer-owned usability sessions. |

## Contribute and get support

- [Contributing](../CONTRIBUTING.md): development setup, checks, and contribution scope.
- [Issue tracker](https://github.com/Raman369AI/threadline/issues): bugs and feature requests. Include your Threadline version and a minimal source example when possible.
- [Security policy](../SECURITY.md): private vulnerability reporting and the source-only safety boundary.
- [Changelog](../CHANGELOG.md): changes by version.
- [MIT License](../LICENSE): reuse and distribution terms.

These documentation files live with the code. When reviewing an older version, select that tag or commit on GitHub to read its matching documentation.
