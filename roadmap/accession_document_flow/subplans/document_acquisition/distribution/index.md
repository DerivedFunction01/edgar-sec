# `acquisition distrib`

## Purpose and status

The pipeline-neutral distribution layer is implemented and used by metadata sync and
document inventory. It delegates work discovery, resolution, and pipeline-specific
bundle/output handling to adapters; each adapter exposes its pipeline-owned work as an
opaque `work_id`. The document-acquisition adapter and S9 worker contract remain
unimplemented and in planning.

SEC request pacing is host-local and follows each machine's configured settings and
environment. There is no cross-host rate coordination or cross-host rate check, and
neither is part of this distribution contract. This does not change the separate S9
implementation status: acquisition distribution remains unimplemented.

The shared CLI uses `--work-id` for `export`, `import`, and `commands`; `worker`
receives its bundle path. The interactive console lets the adapter discover and
describe available work, prompts for a selection when needed, and retains the selected
work for that console session.

Assignment bundle manifests and worker receipts use schema version 2 only. The
assignment binds pipeline, work ID and digest, worker, chunk IDs, and assignment ID.
The receipt binds the same work and assignment identity and records each output path,
size, and SHA-256 digest. Older bundle formats are not import-compatible; export them
again using the current protocol.

Metadata sync and inventory have offline export/worker/import lifecycle coverage in
[`test_distribution_adapter.py`](../../../../../tests/pipelines/metadata_sync/test_distribution_adapter.py)
and [`test_distribution_adapter.py`](../../../../../tests/pipelines/document_inventory/test_distribution_adapter.py).
Inventory discovery offers only valid, unlocked, existing unpublished runs;
resolving a distribution work ID validates that run and never projects a catalog
plan. A catalog plan must first be explicitly projected into an inventory run.

## CLI and operator shape

```text
acquisition distrib list
acquisition distrib export --work-id <work-id> --workers <count>
acquisition distrib worker --bundle <directory>
acquisition distrib import --work-id <work-id> --source <directory>
acquisition distrib commands --work-id <work-id> --workers <count>
```

These spellings illustrate the planned acquisition adapter over the shared
`export`, `worker`, `import`, `list`, and `commands` lifecycle. Acquisition command
integration remains unimplemented; the common CLI uses `--work-id` rather than
pipeline-specific `--run-id` flags.

## Shared contract

- Follow the pipeline-neutral `infra.distribution` adapter protocol. Common code
  validates schema-v2 assignment/receipt identity, work affinity, and receipt-bound
  output paths, sizes, and hashes. Keep acquisition work discovery, bundle contents,
  and output validation in the acquisition adapter.
- Export only validated pending work-order chunks and metadata needed to resolve the
  pinned run. Do not export SEC credentials, mutable upstream plans, or unrelated
  local artifacts.
- A worker validates pipeline/run affinity and assigned chunks before execution.
  It records outcomes and hashes locally; its receipt binds completed chunk files to
  the assignment and run identity.
- Adoption verifies the receipt and every referenced file before changing coordinator
  run state. Unknown chunks, changed plans, missing files, or digest mismatches are
  refused. Already valid coordinator chunks are not overwritten.
- Selected bodies must be available to S10 on the coordinator after import. Returned
  bodies travel as staged files with verified digest/size, not in receipt JSON or
  process IPC. The existing inventory adapter does not transfer document bodies.
- Fixture capture is explicit and separate from distribution. Import does not
  automatically append a fixture case.

## Command details

- [Export work](export.md): choose and validate pending assignments.
- [Execute a worker bundle](worker.md): run assigned work on the worker host.
- [Import worker results](import.md): verify and adopt outputs.
- [Discover bundles and render commands](discovery.md): inspect state and generate
  copyable lifecycle invocations.

## Acceptance

Distributed and local execution produce the same target outcomes for the same
validated inputs. An untrusted or incomplete worker bundle cannot alter run state or
replace verified result files.
