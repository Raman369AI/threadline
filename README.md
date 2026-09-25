# Threadline — Python code review and data flow visualization

**Review Python methods as code: what comes in, what it calls and changes, what it returns — with tests, callers, and models beside it.**

[PyPI: threadline-review](https://pypi.org/project/threadline-review/) · [Get started](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md) · [Documentation](https://github.com/Raman369AI/threadline/blob/main/docs/README.md) · [GitHub](https://github.com/Raman369AI/threadline) · [Report a bug](https://github.com/Raman369AI/threadline/issues)

Threadline opens your Python repository in a local browser, or writes it to one
HTML file. Choose an endpoint, command, or method to read its code under a
one-line summary of its inputs, the project functions it calls, what it changes,
and what it returns. Called functions, related tests, callers, and model
declarations open beside the code; the call map shows everything it reaches.

It reads source without importing or running the project being reviewed. That project's dependencies do not need to be installed.

## Install and open a repository

Requires **Python 3.12 or later**. In your Python environment:

The PyPI package is **`threadline-review`**; the installed command is **`threadline`**.
Use `--pre` for the current beta releases.

```bash
python -m pip install --pre threadline-review
threadline review /path/to/your/python-project
```

Your browser opens the review automatically. If it does not, open the local address printed in the terminal. For virtual-environment setup, see the [installation guide](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md#install-from-pypi).

### Generate a standalone HTML review

```bash
threadline review /path/to/your/python-project --output review.html
```

This writes a single HTML file, opens it, and exits. It needs no server, internet
connection, or Python installation to view. Search, the call map, method code,
tests, callers, models, and Git comparisons work from the embedded snapshot. Add `--base HEAD`
to include changes or `--no-open` to generate the file without opening a browser.
Regenerate the file after editing source; omit `--output` for a local server with
**Refresh source**. The HTML contains the reviewed source, including a baseline
when requested. Large exports take longer to prepare and are capped at 256 MiB; use
`--source-root` or `--exclude` to narrow them, or use the local server for very
large codebases.

## Read a method

| Part | What it shows |
| --- | --- |
| **Summary** | *In*, *Calls*, *Changes*, and *Returns*. Select an item to highlight it in the code or open the call. |
| **Code** | Only the selected method. Select a name to highlight every use; underlined calls open beside the code. |
| **Beside the code** | The opened call, test, or caller with its calling line marked, then **Tests**, **Callers**, and **Models** as source. |
| **Call map** | Project functions the method reaches, each with the line that calls it and tags such as *if*, *later*, or *probably*. |

**Open →** moves into a method; **Back** returns with your highlight and side code intact.

## Choose where to start

| Page | How to use it |
| --- | --- |
| **Endpoints** | Pick an HTTP verb tab, such as GET or POST, then an endpoint. |
| **Commands & tasks** | Select a CLI command or background task. |
| **Modules & methods** | Pick a module, filter its methods, then select one. |

Search is available across all three pages. Each link points to source evidence. Unresolved sources and effects remain
visible as gaps rather than invented values. The [usage guide](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md)
explains model references, navigation, and the limits of static data flow.

## Review a change

Compare a working tree with a Git baseline:

```bash
threadline review /path/to/your/python-project --base HEAD
```

Open **Changes** to select a changed method or compare its before/after source. Changed
files, rename-only records, and edits outside methods remain visible when no callable
body changes. Current callers, historical callers, and possible impact are shown
separately. These are direct source relationships, not a complete impact analysis.

For source roots, exclusions, snapshot-pinned JSON queries, and evidence retrieval, see
the [usage guide](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md).

## Understand the limits

Threadline uses static analysis. A call either resolves to one project function, is
tagged *probably* (a likely target), is a *library* call, or is tagged *can't tell*
(decided at runtime) — `supported`, `possible`, `external`, and `unknown` in JSON
output. Name highlighting matches names within a method; it is not a runtime value trace. Common injected,
inherited, and constructed receivers can have possible source candidates. Dynamic
dispatch can remain unresolved; the view does not establish what happened at runtime.
The header shows analysis problems, and **Coverage** lists parse failures and unmodeled
syntax.

This is a **beta**. Linux and macOS are tested with Python 3.12–3.14; Windows is experimental. Human reviewer sessions remain pending before a stable release.

- [Capabilities and limits](https://github.com/Raman369AI/threadline/blob/main/docs/CAPABILITIES.md)
- [Validation and platform coverage](https://github.com/Raman369AI/threadline/blob/main/docs/VALIDATION.md)
- [Keyboard access and accessibility](https://github.com/Raman369AI/threadline/blob/main/docs/ACCESSIBILITY.md)
- [Changelog](https://github.com/Raman369AI/threadline/blob/main/CHANGELOG.md)

## Contribute

See the [contributor guide](https://github.com/Raman369AI/threadline/blob/main/CONTRIBUTING.md) for development and testing, and the [publishing guide](https://github.com/Raman369AI/threadline/blob/main/docs/PUBLISHING.md) for releases.

[MIT License](https://github.com/Raman369AI/threadline/blob/main/LICENSE) · [Security policy](https://github.com/Raman369AI/threadline/blob/main/SECURITY.md)
