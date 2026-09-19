# First-time reviewer acceptance protocol

[Documentation home](README.md) · [Project home](../README.md)

Use the [session kit](REVIEWER_SESSION_KIT.md) to prepare the fixture and task card, and record real observations in [reviewer results](REVIEWER_RESULTS.md).

Status: **pending maintainer validation.** Record three completed sessions before stable release sign-off.

Recruit three people who have not used Threadline. Do not send repository source to
third parties without its owner's permission. The bundled example is suitable for
this exercise. Record observations locally using the session table below.

## Setup

Install the candidate wheel in a clean environment and open `threadline review example`.
Record the candidate commit, wheel hash, OS, Python version, browser/version, viewport,
and whether the participant uses keyboard navigation or assistive technology.
Use participant codes rather than personal names. Ask permission before recording.

## Task given to each participant

“Find the order-submission method. Explain what comes in, what happens when validation
fails, which function is called in another file, where its return value goes, and what
comes out. Show the original source supporting each answer. Explain one relationship
whose runtime target is uncertain, then return to the caller.”

Do not demonstrate the interface or explain its controls. Observe silently. A participant
may stop at any time. Assistance means that attempt is not an uncoached completion.

## Record per session

| Field | Record |
| --- | --- |
| Participant code / date | Pending |
| Candidate commit / wheel SHA-256 | Pending |
| Environment / assistive technology | Pending |
| Input identified with source | Pass / fail and observation |
| Validation alternative identified | Pass / fail and observation |
| Cross-file call located | Pass / fail and observation |
| Return destination and final output explained | Pass / fail and observation |
| Uncertainty interpreted correctly | Pass / fail and observation |
| Caller position recovered | Pass / fail and observation |
| Completion without coaching / elapsed time | Pending |
| Navigation problems / unsupported assumptions | Verbatim observations, anonymized |
| Follow-up fix / retest | Issue or change reference |

## Acceptance

All three participants complete every task without coaching and without confusing a
possible/unknown relationship for observed or confirmed execution. Record elapsed time
as evidence for refining the provisional performance budgets; do not invent a time
threshold before observing reviewers. Resolve blocking usability issues before sign-off.

Also conduct a keyboard-only and screen-reader pass through search, branch controls,
call expansion, source paging, coverage, and return-to-caller. Verify source remains
readable at 200% zoom and at narrow viewport widths.
