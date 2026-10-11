# `acquisition distrib import`

## Purpose and status

Adopt verified outputs from a completed worker bundle into coordinator-owned work.
The common import CLI and protocol are implemented for metadata sync and inventory;
the S9 import adapter remains unimplemented and in planning.

## Contract

- Accept the coordinator work ID as `--work-id`. Common validation checks pipeline
  affinity, requested work ID, schema-v2 assignment and receipt identity, resolved
  work digest, and every receipt-bound output path, size, and SHA-256 digest before
  calling the adapter.
- After common receipt-affinity and file-integrity checks, the adapter validates
  pipeline-specific output relations, chunk membership, and state-transition rules
  before adoption. Acquisition validates target outcomes, acquisition attempts,
  slot resolutions, and staged source bodies in its adapter; workers do not return S10
  operation results.
  Reject missing, extra-unassigned, path-escaping, altered, or unknown-chunk files.
- Validate imported target outcomes against the pinned work order. A receipt cannot
  convert a skipped target into executable work or turn a direct HTTP 404 into
  `not_filed`.
- Preserve `required_missing` and any versioned lazy-index `TargetSlotResolution` as
  terminal target evidence; never collapse it into `not_filed` or infer a slot from
  worker file names.
- Adopt selected-body files under coordinator-managed paths and retain source-asset,
  digest, and size metadata for S10. Validate a whole chunk before exposing state and
  commit it in one run-state transaction; failed import must not partially adopt it.
- Reassign worker-local attempt ordinals to the coordinator's next per-target attempt
  numbers while preserving each worker attempt ID, worker-local ordinal, assignment ID,
  and worker ID. A stale or superseded assignment receipt cannot update target state.
- If the coordinator already has a valid committed chunk, report it as ignored or
  already committed; never overwrite it with a worker copy.
- Import does not publish a snapshot or capture a fixture. Fixture capture remains
  an explicit separate command.

## Acceptance

Tampered receipts or payloads fail closed. Repeating an import of the same valid
bundle is idempotent and does not duplicate or replace pipeline output. Previous
bundle schemas are unsupported and require re-export using the current protocol.
