# Security policy

## Supported version

Threadline is currently an alpha. Security fixes are applied to the latest source and newest published alpha build.

## Reporting a vulnerability

Please use the repository host's private vulnerability-reporting feature when available. If it is unavailable, contact the maintainer privately before opening a public issue. Include the affected version, reproduction steps, impact, and any suggested mitigation.

Do not include secrets or private repository source in a report.

## Security boundary

Threadline is designed to read target source without importing or executing it. A report is security-sensitive if target code executes, files outside the configured root are exposed, symlink boundaries are bypassed, browser routes serve unapproved files, or a cross-origin request can modify analysis state.
