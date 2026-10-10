# `acquisition distrib export`

## Purpose and status

Create worker bundles for validated pending acquisition work. This command is
design-only; no S9 export adapter exists in tracked code.

## Contract

- Resolve and validate the acquisition run and its S6 plan pins before export.
- Partition only pending eligible work; do not assign acquired, terminal, skipped,
  or non-retryable failed targets. Explicitly requested retry work follows the
  acquisition run contract.
- Each bundle includes the run/work-order manifest and assigned target descriptors,
  but not upstream catalog/inventory sources or SEC credentials.
- Bundle identity binds pipeline, run, plan digest, worker ID, and assigned chunk
  IDs. A conflicting or partially written export is refused or safely rebuilt; it
  must not appear as a valid worker bundle.
- Provide a stable default destination and an explicit destination override. Bundle
  paths are generated and validated; input IDs never become unchecked path segments.

## Acceptance

Export is offline, repeatable for the same assignment, and cannot include work outside
the pinned run. The generated manifest is sufficient for a worker to validate its
assignment without reopening upstream plans.
