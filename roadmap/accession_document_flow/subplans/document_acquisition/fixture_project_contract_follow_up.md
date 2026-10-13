# Fixture-Sourced Acquisition Project Follow-up

**Status:** Deferred contract question. No `project --fixture` behavior is implemented or implied by this note.

## Current behavior

`acquisition project` creates a run from a pinned S6 plan. Fixture commands create, fill, list, and replay captured cases; replay writes selected bytes to a caller-specified local path. The current run manifest has no fixture source mode or fixture ID, and a replayed case does not itself create a projected run.

The acquisition lifecycle proposal mentions fixture-based projection, but does not define how fixture cases become run targets. Implementing it now would require guessing persisted provenance and matching semantics.

## Decisions required before implementation

1. Decide whether fixture projection creates a fixture-sourced acquisition run or only seeds an ordinary run with replayed responses.
2. Define a stable mapping from fixture cases to planned targets, including accessions, target/source origin, inventory entry, request/role, and selected operation pins.
3. Define behavior for missing, ambiguous, duplicate, optional, and stale fixture cases.
4. Define the run-manifest source-mode/fixture-ID fields and schema-version change, including fixture and source digest provenance.
5. Define how replayed responses enter attempt history and selected-body staging without making an unverified case appear as a live SEC acquisition.

Until those decisions are recorded in a versioned contract, keep fixture capture/replay separate from run projection and do not add a `project --fixture` option.
