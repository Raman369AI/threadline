# First-time reviewer session kit

[Acceptance protocol](REVIEWER_SESSIONS.md) · [Session records](REVIEWER_RESULTS.md)

This kit is ready for three real participants. No sessions have been completed or
simulated. Automated browser checks do not replace the human acceptance protocol.

## Facilitator preparation

Build and install the candidate wheel in a clean environment. Record its SHA-256,
source commit and any uncommitted diff, OS, Python, browser, and viewport. Use the same
candidate for all three sessions. Assign anonymous participant codes R1, R2, and R3.
Include someone who uses assistive technology when possible.

Create a fresh, local fixture for each participant:

```bash
python tests/reviewer_fixture.py /tmp/threadline-review-r1
threadline review /tmp/threadline-review-r1 --base HEAD
```

The setup copies the bundled example and creates a Git baseline with a changed fee
calculation and a deleted helper. It never imports or runs the fixture. Existing
destination directories are rejected rather than overwritten. Use a different path
for each participant.

Ask permission before recording. Observe without demonstrating controls. Record where
participants pause, take a wrong turn, or make an unsupported inference. Stop when a
participant wishes to stop. Any assistance makes that attempt coached.

## Participant task card

1. Find the order-submission method. Explain its inputs, what happens when validation
   fails, one cross-file call, where its result goes, and the final output. Show source
   evidence for each answer. Explain one uncertain relationship, then return to the
   caller you were reading.
2. Review the pricing changes. Explain the fee calculation before and after the edit.
   Identify the deleted helper and a previous caller. Explain whether the source still
   establishes that the caller can resolve its target today.
3. Open a branch, inspect its original source, and recover your previous reading
   position. Explain any loading or continuation controls you encounter.

## Facilitator evidence key — do not show during the task

The order-submission example and its source are the reference for task one; use the
acceptance protocol's individual criteria. For task two, `service_fee` changes from
`amount * 1.05` to `amount * 1.08`. `legacy_discount` is deleted while `quoted_total`
still calls it. Its baseline call has source evidence, but the working snapshot does
not resolve a local target. Do not credit “the call definitely succeeds” or a claim
that the tool observed execution.

Record elapsed time for the complete task and major pauses. Do not invent a pass/fail
speed threshold. Keep comprehension failures separate from interface delays.

## Follow-up

Copy the session form in the results file for each participant. Describe observed
problems as concrete steps and outcomes, prioritize blockers, and attach each resulting
fix and retest. Complete the original protocol for all three participants before
stable release sign-off. Report incomplete sessions as incomplete.
