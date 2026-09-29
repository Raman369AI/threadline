# Threadline for VS Code

Review Python methods with their original code, calls, effects, tests, callers,
and models together inside VS Code. Threadline reads source without importing or
executing the project, installing its dependencies, or sending its source to a service.

This is a desktop extension preview, distributed as a VSIX. It is not yet listed
on the Visual Studio Marketplace. It requires VS Code 1.95+ and **Python 3.12+**;
Git is needed only for change reviews. The analyzer is bundled with the extension.

## Install

In VS Code, run **Extensions: Install from VSIX…** and select
`threadline-review-0.1.0.vsix`. Reload if prompted, then open a trusted project folder.

If Python cannot be found, the error offers **Choose Python…**, or run
**Threadline: Choose Python Interpreter…** at any time. It checks the version and
stores the path in the **Threadline: Python Path** user setting. This is an
executable path, not a shell command; arguments and environment activation
commands are not supported.

## Review

Click the Threadline button in the editor title bar, available on every file, or
right-click → **Threadline: Open Review**. In a Python file it saves the file and
selects the function at the cursor. Anywhere else, or outside a function, it opens
the workspace review. While a review is open, it reuses the panel without indexing again.
Select a project call, related test, or caller to read it beside the selected
method; **Open →** follows it within the review. **Open in editor** jumps to source.

The Command Palette also provides:

| Command | What it does |
| --- | --- |
| Threadline: Open Review | Reviews the function at the cursor, or the workspace when there is none. |
| Threadline: Review Workspace | Opens the module and method browser for the active workspace folder. Also available by right-clicking a root folder in the Explorer. |
| Threadline: Review Git Changes | Compares saved files with a Git revision chosen from HEAD, recent branches, and tags, or typed in. `HEAD` includes staged and unstaged edits; untracked files are analyzed too. |
| Threadline: Refresh Review | Reads saved files again, preserving the selected method when it still exists. |
| Threadline: Export Review as HTML | Saves the current workspace review, including its Git baseline when present, as a standalone HTML file. |
| Threadline: Choose Python Interpreter… | Picks and validates the Python 3.12+ executable used for analysis. |
| Threadline: Show Log | Opens the Threadline output channel. |

The status bar shows whether the open review is current, refreshing, stale, or
waiting on unsaved edits; click it to show or refresh the review. Saving a Python
file, or a Python file changing on disk, refreshes the review automatically. Set
`threadline.refreshOnSave` to `false` to refresh manually. Other files never mark
the review stale. Unsaved buffers are not analyzed. A source jump opens the current file only
when its bytes match the evidence; otherwise it opens a read-only `threadline-source:`
document containing the preserved snapshot. Closing the review stops its analyzer.
Only one workspace review is open at a time. In a multi-root workspace, the active
file determines the folder, or a folder picker appears.

The HTML export contains reviewed source, including baseline source when requested.
It works offline and needs neither VS Code nor Python to view.

## Scope and configuration

- `threadline.pythonPath`: trusted Python executable, configured at machine/user level.
- `threadline.sourceRoots`: optional paths relative to the workspace folder, such as `["src", "tests"]`.
- `threadline.exclude`: additional relative paths/globs to exclude from analysis.
- `threadline.refreshOnSave`: refresh the open review after Python files are saved (default `true`).

Changing the first three offers **Reopen Review** to apply them. Narrow the source roots for large
repositories. Analysis requests time out after three minutes; HTML exports after
four minutes. Query responses are capped at 16 MiB. Old snapshots are retained for
the current review within the analyzer's four-snapshot limit.

Analysis is static: dynamic dispatch can remain possible or unknown, and linked
tests are not executed. This preview does not support vscode.dev, github.dev, or
virtual workspaces. Remote extension hosts require Python and Git on that host;
remote environments and Windows/macOS have not yet been validated for this preview.

## Build and test

From this directory, with Node.js 20+ and Python 3.12+ installed:

```bash
npm ci --ignore-scripts
npm run compile
npm test
npm run package
```

The package is written to `dist/threadline-review-0.1.0.vsix`. `npm test` launches
an isolated VS Code extension development host and tests real webview loading,
cursor selection, source jumps, dirty buffers, refresh, Git baselines, export,
and process cleanup. It downloads a test VS Code unless `VSCODE_EXECUTABLE` points
to an existing application executable. Set `THREADLINE_TEST_PYTHON` to choose the
test interpreter. On headless Linux, use `xvfb-run -a npm test`.

From the repository root, `python -m unittest test_vscode_bridge -v` tests the
isolated Python transport, including rejection of arbitrary source paths,
snapshot retention, and preservation of the old review after a failed refresh.
Build assets copy the shared analyzer and review UI; generated files are not
committed. No separately installed Threadline package is needed.
