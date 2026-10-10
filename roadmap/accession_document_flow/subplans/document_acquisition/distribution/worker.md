# `acquisition distrib worker`

## Purpose and status

Execute one assigned bundle on a worker host. This command is design-only; no S9
worker adapter exists in tracked code.

## Contract

- Validate the bundle manifest, pipeline affinity, run identity, plan digest,
  assignment, and every local input before opening the SEC client.
- Use the same acquisition request, redirect, streaming, retry, and exact-sequence
  rules as [`acquisition run`](../run.md). The worker executes only assigned
  targets; it does not project plans, select a different snapshot, or publish a
  snapshot.
- Persist committed per-target outcomes so interruption can resume the same bundle.
  A completed target is not fetched again on worker restart unless it is explicitly
  selected for retry under the run contract.
- Write selected-body files and metadata under the bundle root. The receipt binds
  run/worker/chunk identity, completed outcomes, row counts, and digests of returned
  files. Do not place payload bytes in receipt JSON.
- Cancellation stops new targets, cleans partial bodies, preserves committed target
  outcomes, and emits a receipt only for validated committed work.

## Acceptance

A worker cannot execute an unassigned target or return a receipt for files outside
its bundle. Invalid assignment or input validation fails before network activity.
