# Accessibility and native Safari validation

[Documentation home](README.md) · [Project home](../README.md)

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
