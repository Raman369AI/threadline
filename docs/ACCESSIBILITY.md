# Accessibility and native Safari validation

[Documentation home](README.md) · [Project home](../README.md)

## Redesigned catalog pages and sidebar drawer — 2026-09-30

Chrome 153 on Linux passed 92 keyboard, reflow, zoom, and accessibility checks with zero
axe violations across 25 audited states in each theme. The new checks cover arrow-key
movement through the sidebar tree (Right opens a folder, Left closes it) and opening and
closing the narrow-window sidebar drawer with the keyboard; the open drawer is audited at
390 pixels. Native Safari, Firefox, VS Code's own webview, and human assistive-technology
review have not been run. The VS Code styling was checked in Chrome using the colors of the
installed Dark Modern and Light Modern themes, not in VS Code itself.

## Dark mode — 2026-09-26

The review is dark by default; **Theme** in the header switches between Dark, Light, and
System (which follows the system setting) and is remembered in that browser. Every audited state
below is now checked by axe in both light and dark themes: Chrome 153 on Linux passed
84 checks with zero axe violations across 24 states in each theme, including resizing the code pane from the keyboard and moving focus into and out of the Instructions panel. Native Safari has not
been rerun with dark mode.

## Current local candidate — 2026-09-24

Chrome 153 on Linux passed 56 keyboard, reflow, zoom, and accessibility checks
with zero axe violations across 23 audited states. The candidate checks include
the method code review, keyboard name highlighting, opening a call beside the
code, Escape order, sidebar collapse, exact change evidence, 720- and 390-pixel
widths, and 200% zoom. These are
local results for the current checkout. Native Safari, the cross-platform
matrix, and human assistive-technology review have not been rerun for this
candidate.

The earlier CI-backed release evidence follows.

[CI run 34922515651](https://github.com/Raman369AI/threadline/actions/runs/34922515651) passed for application/test commit `8c9d088`.
Reports and screenshots are retained in the `accessibility-ubuntu-latest` and
`accessibility-macos-latest` artifacts.

| Browser | Platform | Checks passed | Axe violations |
| --- | --- | ---: | ---: |
| Chrome 152.0.7977.82 | Linux | 20 | 0 |
| Native Safari 26.6.2 | macOS | 17 | 0 |

Six states were audited: workflow, expanded method, coverage, 720-pixel reflow,
390-pixel reflow, and 200% layout zoom. Both browsers reported actual 720- and
390-pixel inner widths. Keyboard checks cover search, source selection, branch
collapse/expansion, call controls, visible focus, and coverage focus return.
Chrome additionally checks browser accessibility-tree landmarks, source/search
names, and live announcements. The native Safari screenshot was visually reviewed.

## Fixes made

- Darken low-contrast labels and source syntax while preserving the existing palette.
- Give review actions a minimum 24-pixel target height.
- Add a keyboard skip link and explicit input/output and source region roles.
- Move focus into Coverage when opened and restore it on Escape.
- Keep the source scroll region within narrow layout bounds.
- Use native WebDriver key actions through select controls.

Safari uses [Apple's Option-Tab navigation](https://support.apple.com/en-au/guide/safari/cpsh003/mac)
for clickable controls. The test does not use JavaScript to jump keyboard focus.
SafariDriver runs the actual macOS Safari application, not a Linux WebKit substitute.

## Scope of the evidence

Axe's incomplete entries remain in the reports: decorative glyphs and source text
partly clipped by scroll regions require review rather than being counted as violations
or silently discarded. No prohibited-ARIA-role findings remain. Automated checks and
accessibility-tree inspection do not claim a human VoiceOver/NVDA session or complete
WCAG conformance. Assistive-technology feedback belongs in the maintainer-owned reviewer
sessions.

## Reproduce

```bash
python -m pip install '.[browser-test]'
npm ci --prefix tests/browser-tools --ignore-scripts
python tests/browser_accessibility.py --browser chrome
# On macOS, enable Safari automation first:
safaridriver --enable
python tests/browser_accessibility.py --browser safari
```
