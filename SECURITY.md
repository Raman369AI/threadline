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
