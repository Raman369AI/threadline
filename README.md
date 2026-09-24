# Threadline

**Explore Python workflows, from an endpoint or method to the original source.**

[Get started](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md) · [Documentation](https://github.com/Raman369AI/threadline/blob/main/docs/README.md) · [GitHub](https://github.com/Raman369AI/threadline) · [Report a bug](https://github.com/Raman369AI/threadline/issues)

Threadline opens your Python repository in a local browser. Choose an endpoint, command, or module and method to follow its calls across files. See branches, inputs, return values, and the code behind each step together.

It reads source without importing or running the project being reviewed. That project's dependencies do not need to be installed.

## Install and open a repository

Requires **Python 3.12 or later**. In your Python environment:

```bash
python -m pip install --pre threadline-review
threadline review /path/to/your/python-project
```

Your browser opens the review automatically. If it does not, open the local address printed in the terminal. For virtual-environment setup, see the [installation guide](https://github.com/Raman369AI/threadline/blob/main/docs/USING_THREADLINE.md#install-from-pypi).

## Choose where to start

| Page | How to use it |
| --- | --- |
| **Endpoints** | Pick an HTTP verb tab, such as GET or POST, then an endpoint. |
| **Commands & tasks** | Select a CLI command or background task. |
| **Modules & methods** | Pick a module, filter its methods, then select one. |

Search is available across all three pages. Selecting a method opens its workflow and original source; nothing is selected automatically.

![Threadline showing a cross-file order workflow, method steps, and original Python source side by side.](https://raw.githubusercontent.com/Raman369AI/threadline/main/docs/images/workflow-review.png)

Follow calls in the workflow, expand a branch for its local logic, or select a step to highlight its source. Calls into other modules retain their source evidence. Large workflows and branch bodies load progressively.

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

Threadline uses static analysis. Calls are labeled **supported**, **possible**,
**external**, or **unknown** according to the source evidence. Common injected,
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
