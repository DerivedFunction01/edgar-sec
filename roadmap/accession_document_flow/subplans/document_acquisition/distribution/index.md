# `acquisition distrib`

## Purpose and status

Export S9 work for remote execution and verify returned results on the coordinator.
This is design-only. The shared distribution CLI and protocol exist, but there is no
document-acquisition adapter or S9 worker contract in tracked code.

Live remote SEC work is not part of the first S9 implementation: each host would own
an independent broker and the current SEC rate setting is machine-local. Do not
enable remote live workers until the cross-host limit is shared or a per-host budget
is enforced. The paths below specify only where the shared adapter would place bundles.

## CLI and operator shape

```text
acquisition distrib list
acquisition distrib export --run-id <run-id> --workers <count>
acquisition distrib worker --bundle <directory>
acquisition distrib import --run-id <run-id> --source <directory>
acquisition distrib commands --run-id <run-id> --workers <count>
```

These spellings illustrate the shared `export`, `worker`, `import`, `list`, and
`commands` lifecycle; exact flags remain provisional because live remote work is
deferred. The initial operator does not expose a `d` console.

## Shared contract

- Follow the `infra.distribution` adapter protocol for pipeline affinity, bundle
  manifests, chunk assignments, receipt digests, and import validation. Keep
  acquisition-specific bundle contents and run validation in the acquisition
  adapter, not in generic distribution code.
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
