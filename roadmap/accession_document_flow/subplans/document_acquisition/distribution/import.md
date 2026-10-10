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
  pipeline-specific output schemas, chunk membership, and state-transition rules
  before adoption. Acquisition must validate its target outcomes and staged document
  bodies in its own adapter.
  Reject missing, extra-unassigned, path-escaping, altered, or unknown-chunk files.
- Validate imported target outcomes against the pinned work order. A receipt cannot
  convert a skipped target into executable work or turn a direct HTTP 404 into
  `not_filed`.
- Preserve `required_missing` and any versioned lazy-index `TargetSlotResolution` as
  terminal target evidence; never collapse it into `not_filed` or infer a slot from
  worker file names.
- Adopt selected-body files under coordinator-managed paths and retain their digest
  and size in result metadata for S10. Stage all validation before exposing adopted
  state; failed import must not leave a partially adopted chunk.
- If the coordinator already has a valid committed chunk, report it as ignored or
  already committed; never overwrite it with a worker copy.
- Import does not publish a snapshot or capture a fixture. Fixture capture remains
  an explicit separate command.

## Acceptance

Tampered receipts or payloads fail closed. Repeating an import of the same valid
bundle is idempotent and does not duplicate or replace pipeline output. Previous
bundle schemas are unsupported and require re-export using the current protocol.
