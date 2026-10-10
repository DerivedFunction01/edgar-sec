# `acquisition distrib export`

## Purpose and status

Create worker bundles for validated pending acquisition work. The common export CLI
and protocol are implemented for metadata sync and inventory; this acquisition
adapter remains unimplemented and in planning.

## Contract

- The common CLI receives the opaque work identity as `--work-id`; the acquisition
  adapter will resolve and validate the S9 run and its S6 plan pins before export.
- Partition only pending eligible work; do not assign acquired, terminal, skipped,
  or non-retryable failed targets. Explicitly requested retry work follows the
  acquisition run contract.
- Each bundle includes the run/work-order manifest and assigned target descriptors,
  but not upstream catalog/inventory sources or SEC credentials.
- Schema-v2 bundle assignment identity binds pipeline, work ID and digest, worker ID,
  assigned chunk IDs, and assignment ID. The common protocol does not read or project
  upstream pipeline plans. A conflicting or partial export must not appear as a valid
  worker bundle.
- Provide a stable default destination and an explicit destination override. Bundle
  paths are generated and validated; input IDs never become unchecked path segments.

## Acceptance

Shared metadata and inventory export/worker/import flows have offline end-to-end test
coverage. Acquisition export remains planned. An acquisition manifest will be
sufficient for a worker to validate its assignment without reopening upstream plans.
