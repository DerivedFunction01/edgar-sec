# `acquisition distrib import`

## Purpose and status

Adopt verified outputs from a completed worker bundle into the coordinator run. This
command is design-only; no S9 import adapter exists in tracked code.

## Contract

- Resolve the coordinator run and validate the returned bundle's pipeline, run,
  plan digest, worker assignment, receipt schema, and completed chunk IDs.
- Verify every receipt-bound file digest and size before changing coordinator state.
  Reject missing, extra-unassigned, path-escaping, altered, or unknown-chunk files.
- Validate imported target outcomes against the pinned work order. A receipt cannot
  convert a skipped target into executable work or turn a direct HTTP 404 into
  `not_filed`.
- Adopt selected-body files under coordinator-managed paths and retain their digest
  and size in result metadata for S10. Stage all validation before exposing adopted
  state; failed import must not leave a partially adopted chunk.
- If the coordinator already has a valid committed chunk, report it as ignored or
  already committed; never overwrite it with a worker copy.
- Import does not publish a snapshot or capture a fixture. Fixture capture remains
  an explicit separate command.

## Acceptance

Tampered receipts or payloads fail closed. Repeating an import of the same valid
bundle is idempotent and does not duplicate or replace acquired content.
