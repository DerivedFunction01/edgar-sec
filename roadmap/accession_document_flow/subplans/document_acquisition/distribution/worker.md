# `acquisition distrib worker`

## Purpose and status

Execute one assigned bundle on a worker host. The common worker command and protocol
are implemented for metadata sync and inventory; no acquisition worker adapter exists
in tracked code.

## Contract

- The common worker accepts a bundle path, not `--work-id`. It accepts schema-v2
  assignments only and validates pipeline affinity, work ID/digest, worker and
  assignment identity, and assigned chunks before adapter execution. The acquisition
  adapter validates the complete S9 work relation set and any reused-source payloads
  before opening an SEC client.
- Use the same acquisition request, redirect, streaming, retry, and exact-sequence
  rules as [`acquisition run`](../run.md). The worker executes only assigned
  targets; it does not project plans, select a different snapshot, or publish a
  snapshot.
- Persist committed per-target acquisition outcomes so interruption can resume the
  same bundle. A completed target is not fetched again on worker restart unless it is
  explicitly selected for retry under the run contract. Operations are carried in the
  assignment to determine source inputs but are not executed by the acquisition worker.
- Write response/selected-body files and per-chunk target outcomes under the bundle
  root. A source reused from the pinned base snapshot is delivered by verified digest;
  it is not fetched again. The schema-v2 receipt binds work ID/digest and assignment
  ID, and records each returned path, size, and SHA-256 digest. Do not place payload
  bytes in receipt JSON.
- Cancellation stops new targets, cleans partial bodies, preserves committed target
  outcomes, and emits a receipt only for validated committed work.

## Acceptance

A worker cannot execute an unassigned target or return a receipt for files outside
its bundle. A target and all its operation/source/input rows remain in one chunk; a
chunk receipt is imported atomically. The common protocol rejects old bundle schemas;
they must be exported again. Acquisition-specific assignment and SEC input validation
remain planned.
