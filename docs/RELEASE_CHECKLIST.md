# Stable release gate

[Documentation home](README.md) · [Project home](../README.md)

The engineering gates below passed in [CI run 34922515651](https://github.com/Raman369AI/threadline/actions/runs/34922515651) for commit `8c9d088`.
The maintainer owns reviewer-session results and the final release decision. The existing
alpha version remains unchanged until that decision.

## Supported release target

The release matrix targets Python 3.12–3.14 on Linux and macOS. CI must pass on both
before claiming support for a candidate. Browser automation covers Chromium on Linux
and native Safari on macOS through SafariDriver. Windows is experimental: its fallback
file-opening path does not provide the POSIX directory-descriptor guarantees.
New Python minor versions require a matrix run before being advertised as supported.

## Automated candidate checks

1. Run the full self-contained suite on every OS/Python matrix entry.
2. Check both JavaScript files and run the browser smoke test. It exercises ordinary
   review, source evidence, nested workflows, deep links, pagination, keyboard search,
   refresh authorization, named buttons, and responsive widths.
3. Build a wheel and run `python tests/release_smoke.py dist/*.whl`. This installs only
   Threadline into a clean virtual environment and runs the CLI and packaged server
   outside the checkout against inert source fixtures.
4. Run the seven pinned public-source corpus cases, including the declared time and
   memory budgets. Preserve the generated JSON report as a CI artifact.
5. Review changes for source non-execution, containment, exact evidence, and conservative
   certainty. The corpus checks source accounting and evidence; it is not a complete
   independent semantic oracle for every connection in every repository.
6. Check the changelog, install commands, capability matrix, and security contact.

CI runs the platform matrix and the public corpus on pushes and pull requests. Candidate
wheel artifacts are retained. It does not publish a package or create a stable release.

## Reviewer sessions — handled by the maintainer

The maintainer has taken responsibility for the three first-time reviewer sessions.
Use [REVIEWER_SESSIONS.md](REVIEWER_SESSIONS.md) to record their results. This engineering
work proceeds independently; it does not invent participant observations.

The executable accessibility gate is `tests/browser_accessibility.py`: keyboard search,
source selection, branches, calls, focus visibility/return, reflow, 200% layout zoom,
axe rules, and Chrome accessibility-tree labels/live announcements. CI runs this in
Chrome and native Safari. Reports include actual viewport widths and axe checks needing
human review. These tests do not claim a human VoiceOver/NVDA session or complete WCAG
conformance; include assistive-technology users in the maintainer-owned sessions.

The maintainer signs off these results for the same candidate commit before changing
alpha status, creating a stable tag, or publishing release artifacts.
