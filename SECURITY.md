# Security policy

## Supported version

Threadline is currently an alpha. Security fixes are applied to the latest source and newest published alpha build.

## Reporting a vulnerability

Report vulnerabilities through [GitHub’s private reporting form](https://github.com/Raman369AI/threadline/security/advisories/new). Private vulnerability reporting is enabled for this repository. Include the affected version, reproduction steps, impact, and any suggested mitigation.

Do not include secrets or private repository source in a report.

## Security boundary

Threadline is designed to read target source without importing or executing it. A report is security-sensitive if target code executes, files outside the configured root are exposed, symlink boundaries are bypassed, browser routes serve unapproved files, or a cross-origin request can modify analysis state.


## Local server controls

The CLI binds to `127.0.0.1`. Requests must name the actual loopback host and port;
refresh also requires an unpredictable session header and rejects mismatched origins.
The server sends a restrictive content security policy and serves only allowlisted
assets and snapshot APIs. This is a local application, not an authenticated shared or
remotely hosted service.

On POSIX, source reads pin directory descriptors, reject symlinks at every component,
and accept only regular files. Parsing and hashing use a single bounded byte read.
See [resource budgets](docs/PERFORMANCE.md) for limits and their scope. The Windows
fallback does not provide the same directory-descriptor guarantees and is experimental.

## Static GitHub Pages generator

The `pages/` frontend fetches public repository source directly from GitHub and
runs Threadline in a browser worker. It does not run a remote Python service.
Downloads are pinned to one commit and checked against Git blob hashes, with
file-count and byte limits. Target files are never imported or executed, and
their directory is not on Python's import path. Symbolic links and submodules
are not followed. The worker can be terminated with Cancel and has a five-minute
page deadline.

Generated reviews are previewed in a sandboxed iframe and can be downloaded as
self-contained HTML containing the reviewed source. Repository content must stay
inert in both forms. See [the Pages guide](docs/GITHUB_PAGES.md) for scope and limits.

## Desktop VS Code extension

The extension runs only in trusted filesystem workspaces. A machine/user setting
selects the Python executable. It starts the bundled analyzer with `-I -S -u`,
without a shell, from the extension directory. The target is not added to Python's
import path; startup hooks and environment-based Python path changes are disabled.
The interpreter itself must be trusted.

Review queries use a bounded JSON-lines stdio bridge, with no listening HTTP port.
The webview has a restrictive content security policy, nonce-authorized scripts,
no network connection permission, and access only to bundled review assets.
Editor jumps validate snapshot membership and file content; changed or missing
files open as read-only snapshot documents. HTML destinations are selected by the
extension's native save dialog, never by repository content or a webview path.
Closing the panel or cancelling initial analysis stops the Python process.
