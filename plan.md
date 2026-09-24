# Plan: remaining work

The method-first Data flow workspace, bounded method Code, paired Data models,
related tests, caller comparison, template links, and no-distraction controls
are implemented. Their behavior, limits, and local validation are recorded in
[the usage guide](docs/USING_THREADLINE.md), [capability matrix](docs/CAPABILITIES.md),
and [validation record](docs/VALIDATION.md). This file tracks unfinished work
only.

## Release validation

- [ ] Rerun the Linux/macOS Python matrix and native Safari on the exact
  candidate revision. Local Chrome, wheel, Python, semantic, and pinned-source
  checks passed on 2026-09-24; they do not substitute for that matrix.
- [ ] Conduct the three uncoached reviewer sessions in
  [the session protocol](docs/REVIEWER_SESSIONS.md), including plain functions
  and OO/service methods. Ask readers to identify an input, new value,
  mutation, model reference, output, and cross-method use. Record wrong turns,
  unsupported conclusions, and UI latency separately.
- [ ] Include human assistive-technology feedback where possible. Automated
  axe, keyboard, reflow, and zoom checks do not establish a screen-reader
  experience or complete accessibility conformance.

## Separate follow-up work

- [ ] Represent condition-only influence separately from value flow. In the
  agent-kanban Dashboard, an `AgentSession` status check decides whether a
  failed-session attention item is added; a value trace must not imply that
  session data is copied into the item.
- [ ] Reduce noisy unbound-read gaps for built-ins and established module
  globals such as `len` and the Dashboard's `templates` object, while keeping
  unresolved bindings explicit.
- [ ] Decide whether stable public bookmarks must survive arbitrary source
  edits; current positional IDs provide snapshot-local navigation and limited
  before/after matching.
- [ ] Broaden Python 3.12 type-parameter annotation-scope coverage beyond the
  currently handled lazy type-alias cases.
- [ ] Repeat Git-baseline startup and public-repository memory measurements
  across representative environments. Optimize measured bottlenecks without
  weakening resource limits.
