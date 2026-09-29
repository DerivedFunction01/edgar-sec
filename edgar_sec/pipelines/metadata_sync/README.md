# metadata_sync — Phase 1

Builds the SEC submissions metadata dataset from a CIK cohort: plan a cohort,
fetch each CIK's submissions document, checkpoint the work, and publish an
immutable Parquet *dataset* — a manifest-described set of parts — that Phase 2
consumes.

## Purpose

The pipeline exists to turn a *roster* — a set of CIKs — into a *snapshot*: an
immutable, verified dataset of one row per registrant. Everything else in
this package is in service of that, and the whole design is arranged so that the
snapshot is reproducible from immutable inputs, resumable after interruption, and
producible by more than one machine.

## The lifecycle

```text
sources refresh          -> metadata/sources/company_tickers/<snapshot_id>/
sources compare --input  -> metadata/registries/<registry_id>/
                            datasets/effective_ciks.parquet   (roster carrier)
                            effective_cik_input.csv           (export)
plan   --input | --roster -> metadata/plans/<plan_id>/
                            plan.json, roster/ciks.parquet, input/
export  --worker-count N  -> <dest>/worker-NN/{plan.json, roster/, assignments/}
worker  --bundle <dir>    -> <dir>/chunks/chunk_NNNN.parquet + receipt.json
import  --source <dir>    -> adopts verified chunks for the merge
run     (single host)     -> same chunk execution, no distribution step
merge                    -> metadata/snapshots/<snapshot_id>/
                            parts/part-NNNNN.parquet, ciks.parquet,
                            metadata.manifest.json
augment                  -> a new snapshot holding base + only the new CIKs
```

`refresh` and `compare` are pure projections over immutable inputs and perform
no network access. `plan` performs no network access. Only `run`, `worker`, and
`augment` fetch.

## Module layout

| Module | Responsibility |
| :--- | :--- |
| `roster.py` | The CIK roster: content-addressed identity, atomic Parquet IO, set operations, the published CIK index. |
| `manifest.py` | CIK CSV ingestion: normalization, deduplication, curated names, the input fingerprint. |
| `planner.py` | `Plan`: chunk layout as ordinal ranges, plan identity, bundle write and validated load. |
| `assignment.py` | Static chunk-to-worker assignment, and the worker receipt that crosses the machine boundary. |
| `distribution.py` | Copy-based multi-machine distribution: export, select, adopt. The import trust boundary. |
| `options.py` | The one typed options model the CLI and the operator both build; bundle path resolution. |
| `paths.py` | `MetadataPaths` / `RunPaths`; the published-vs-transient split, plan bundle, registry, and source locations. |
| `checkpoints.py` | What counts as a *complete* chunk on disk. |
| `worker.py` | Resumable chunk execution over a thread pool; the never-refetch guarantee. |
| `snapshot.py` | Resolve a published snapshot to a verified, ordered Parquet part list; both manifest versions. |
| `merger.py` | Coordinator validation, multipart publication, progress events, CIK index, snapshot manifest, pointer. |
| `augmentation.py` | Delta planning and merge onto a published snapshot without refetching the base. |
| `registry.py` | Curated-versus-source comparison, the effective CIK roster, and the CSV export. |
| `source_registry.py` | Write-once, content-addressed `company_tickers.json` snapshots. |
| `sec_client.py` | One CIK to its submissions document plus every historical file it lists. |
| `cli.py` | The argparse surface; each `cmd_*` is a plain callable the operator also calls. |
| `operator.py` | Interactive wizard; a presentation layer over the same `cmd_*` functions. |
| `smoke_test.py` | Credential-gated live check that never publishes. |

## Contracts this package guarantees

**A roster is stored once and referenced by identity.** `plan.json` records the
roster's identity and the chunk layout; the cohort itself lives once in
`roster/ciks.parquet`. Chunk membership is a range over roster ordinals. A
250,000-CIK plan is under 2 KB of manifest; the previous format embedded the CIK
list three times and produced a 15 MB document.

**Plan identity is the cohort, not the schedule.** A plan id is derived from the
roster identity, the chunk size, the plan kind, and — for a delta — the base
snapshot. It is never derived from an assignment, a worker count, or a timestamp.
Reassigning a cohort therefore keeps the same plan directory and the same
completed checkpoints.

**A bounded plan is a different plan.** `--limit` is applied to the roster
*before* identity is derived. Hashing the raw file and truncating afterwards let
a bounded run and a full run over one file collide on a single plan directory and
a single chunk namespace.

**A delta plan is bound to its base.** The same requested CIK list against two
different base snapshots is two different plans with two different delta rosters.
Augmentation publishes `base_ciks ∪ delta_ciks` and records the parent, the delta
roster, and both digests in the new snapshot's manifest.

**Row-level `snapshot_id` is provenance, not container identity.** Augmentation
copies base rows verbatim, so an augmented snapshot legitimately contains rows
stamped with the base's identity. Rewriting them to the new artifact's id would
misstate where the data came from.

**Every chunk is complete or absent.** A checkpoint counts only when the file
exists, matches the canonical schema, holds exactly the CIKs its plan range
covers, and carries the plan's input fingerprint. Expected CIKs come from the
plan's roster range rather than from a plan document, so the same check applies
to a chunk that arrived from another machine under a copied bundle.

**Published artifacts are immutable and self-describing.** A merge validates every
chunk, then publishes the validated chunks as an ordered set of Parquet parts
under `parts/`, a sorted distinct `ciks.parquet` derived from the published rows,
a manifest listing every part with its digest and row count, and a pointer
advance. The CIK index is a statement about the artifact on disk, not about what
was requested.

**The manifest is the commit record.** A snapshot is read through the part list
its manifest declares, and every listed part is verified against the digest
recorded for it. A part that is listed but absent means the snapshot was not
fully published; a file that is present but unlisted is not part of the snapshot.
The manifest is written before the pointer, so a crash between the two leaves an
unpublished but complete snapshot rather than a pointer naming an unfinished one.

**A returned chunk is proven before it is adopted.** Import checks the plan
identity, the assignment identity, that the receipt only names chunks its
assignment claims, the per-file SHA-256, the canonical schema, the row count, and
the chunk's CIK coverage. A byte-identical re-import is a no-op; a conflicting one
is an error.

**Published input is never implicitly refreshed.** `plan`, `run`, and `augment`
never fetch an external source. A cohort is either a curated CSV or a published
registry roster, and both resolve to the same `Roster`.

## Public surface

| Symbol | Module | Purpose |
| :--- | :--- | :--- |
| `Roster`, `build_roster`, `read_roster`, `write_roster` | `roster` | The content-addressed CIK cohort. |
| `without_ciks`, `union_rosters` | `roster` | Set operations; the basis of delta planning and the published index. |
| `read_cik_index`, `write_cik_index` | `roster` | The sorted distinct CIK index published beside a snapshot. |
| `Plan`, `build_plan`, `load_plan`, `write_plan`, `derive_plan_id` | `planner` | Plan identity, chunk layout, and the written bundle. |
| `Assignment`, `ChunkReceipt`, `divide_chunks`, `write_receipt`, `read_receipt` | `assignment` | Static assignment and the machine-boundary receipt. |
| `export_bundle`, `select_assignment`, `adopt_chunks` | `distribution` | The copy-based distribution contract. |
| `PlanOptions`, `RunOptions`, `BundleRunPaths` | `options` | The one typed options model. |
| `resolve_metadata_paths`, `resolve_run_paths` | `paths` | The published-vs-transient split. |
| `discover_completed_chunks`, `inspect_chunk` | `checkpoints` | Completeness of a chunk on disk. |
| `run_chunk`, `run_chunk_ids` | `worker` | Resumable execution; the never-refetch guarantee. |
| `merge_chunks`, `publish_snapshot`, `publish_parts`, `parts_digest`, `MergeReport` | `merger` | Validation, multipart publication, manifest, pointer. |
| `read_snapshot_parts`, `load_snapshot_manifest`, `SnapshotParts`, `SnapshotLayout`, `SnapshotLayoutError`, `SNAPSHOT_MANIFEST_VERSION` | `snapshot` | Resolve and verify a snapshot's part list. |
| `augment`, `derive_delta_plan`, `snapshot_cik_roster` | `augmentation` | Delta planning and merge. |
| `compare_sources`, `load_registry_roster`, `load_registry_manifest` | `registry` | The curated-versus-source projection. |
| `refresh_company_tickers`, `load_source_snapshot` | `source_registry` | Immutable external source snapshots. |
| `RUNTIME_CHUNK_SIZE` | `foundation.runtime.settings` | Env name for the default chunk size. |

## Command surface

```bash
python run.py metadata plan     --input uploads/cik-sec.csv [--limit N] [--chunk-size N]
python run.py metadata plan     --roster <registry_id>
python run.py metadata status   --plan-id <plan_id>
python run.py metadata run      --plan-id <plan_id> [--chunks 0-3,7]
python run.py metadata merge    --plan-id <plan_id>
python run.py metadata augment  --input uploads/cik-sec-new.csv \
    --base-snapshot-id <id> --new-snapshot-id <id>
python run.py metadata export   --plan-id <plan_id> --worker-count 4 --destination <dir>
python run.py metadata worker   --bundle <dir>/worker-00
python run.py metadata import   --plan-id <plan_id> --source <dir>/worker-00
python run.py metadata sources refresh [--artifacts <dir>]
python run.py metadata sources compare --input uploads/cik-sec.csv \
    --source-manifest <source manifest.json>
```

`status`, `run`, `merge`, and `worker` accept either an explicit `--plan-id`, a
`--bundle` that names its own plan in its manifest, or a cohort reference
(`--input` / `--roster`) to re-derive. There is no persisted configuration: the
effective values follow the environment and the settings registry, and the plan
id follows the effective chunk size. Planning with one chunk size and running with
another therefore resolves a *different* plan, and the command says so rather
than reusing another plan's checkpoints.

The interactive operator (`python run.py metadata` with no command) offers the
same nine actions and builds the same options objects.

## Deliberate gaps

These are decisions, not oversights. Each names the alternative.

- **A published snapshot is no longer globally sorted by CIK.** Parts are byte
  copies of the validated chunk files, so the snapshot is in chunk order and each
  part is in roster order. The previous single file was produced by a
  decompress/sort/recompress of every row; copying the already-validated chunks
  performs the same validation at a fraction of the I/O. The manifest records
  this as `sort_order: chunk_order` so a consumer cannot mistake one for the
  other, and `ciks.parquet` remains the sorted membership index for lookups by
  CIK. Anything that needs globally sorted rows must sort in its own query;
  Phase 2 aggregates, so it does not.
- **Parts are copied, not moved.** Publication copies each validated chunk into
  the snapshot, so a resumed plan still finds its checkpoints and an aborted
  publication leaves the transient tree intact. The cost is that the transient
  and published trees each hold the data. Phase 1 has no snapshot garbage
  collector; that trade is revisited with vacuuming.
- **A multipart manifest deliberately names no single payload.** `output_path`
  and `artifact_sha256` are left empty for a multipart snapshot. Pointing them at
  part zero would let a reader that understands only the legacy shape silently
  ingest a fraction of the dataset, so a reader must honour the part list or
  fail loudly. Snapshots published before the multipart contract keep both fields
  and still resolve as a one-part dataset.
- **No dynamic claiming, leases, or scheduler.** Assignment is static and copied.
  A worker that dies mid-run is not detected or reassigned; the coordinator simply
  re-exports, because a chunk nobody returned is a chunk nobody fetched. A real
  scheduler would need a lease protocol and a heartbeat, which is not justified
  by a four-command pipeline. Roadmap: the multi-machine section of
  `roadmap/refactor_v2/phase_1.md`.
- **No worker-level rate-limit division.** Each worker process constructs its own
  `RateLimiter` from `sec.rate_limit_rps`, so N workers together request N times
  the configured rate. This was already true of `--partition N`. Divide the
  budget with `SEC_RATE_LIMIT_RPS` when distributing across machines.
- **The CSV is an export, not the internal carrier.** `effective_cik_input.csv` is
  still written beside `effective_ciks.parquet` so v1-era scripts keep working,
  and `read_cik_manifest` still parses CIK manifests. Nothing in the fetch path
  parses a CSV to learn which CIKs a run covers.
- **No persisted run configuration.** Options are resolved once, held in memory,
  and recorded in the artifacts they produce. A `project.json` would add a second
  source of truth for values that the settings registry already owns.
- **Snapshots published before the CIK index existed still resolve.** Reading a
  base snapshot's membership falls back to projecting the `cik` column of every
  part its manifest lists, so the index is an addition rather than a migration.
  A base with no manifest is *not* readable: a merge that was never published is
  not a snapshot. A missing base is still an error, because an unreadable base
  must never be read as an empty one.
- **`smoke_test.py` remains credential-gated and excluded from the default
  gate.** Its guards are pure and are covered by `test_smoke_test.py`.
- **No `--limit` in augmentation.** A bounded augmentation would fetch a bounded
  delta, which is legitimate, but the flag is not offered because the requested
  cohort is normally a comparison's output rather than an ad-hoc subset.

## Mirrored tests

- `tests/pipelines/metadata_sync/test_roster.py` — identity, ordering, atomic
  IO, set operations, and a 250,000-CIK derivation/IO budget.
- `tests/pipelines/metadata_sync/test_planner.py` — chunk ranges, identity
  including the limit and delta cases, manifest size, and every staleness and
  version rejection.
- `tests/pipelines/metadata_sync/test_assignment.py` — assignment identity, the
  receipt digest, and receipt tampering.
- `tests/pipelines/metadata_sync/test_distribution.py` — export, worker, import,
  and every import refusal.
- `tests/pipelines/metadata_sync/test_paths.py` — the published-vs-transient
  split, the bundle layout, and bundle-rooted path resolution.
- `tests/pipelines/metadata_sync/test_checkpoints.py` — completeness,
  including a chunk belonging to a different plan.
- `tests/pipelines/metadata_sync/test_worker.py` — per-CIK fan-out and the
  never-refetch guarantee.
- `tests/pipelines/metadata_sync/test_snapshot.py` — part-list resolution and
  verification: legacy single-file manifests, tampered parts, incomplete
  publications, unlisted files, and repeated or digestless part entries.
- `tests/pipelines/metadata_sync/test_merger.py` — every hard failure, the
  duplicate-accession warning, and the published CIK index.
- `tests/pipelines/metadata_sync/test_augmentation.py` — delta identity, base
  preservation, and union semantics.
- `tests/pipelines/metadata_sync/test_registry.py` — the comparison projection
  and the published roster.
- `tests/pipelines/metadata_sync/test_options.py` — the options boundary and
  settings resolution.
- `tests/pipelines/metadata_sync/test_scale.py` — constant-size plans at scale,
  reassignment stability, single-host/distributed convergence, and the Phase 2
  handoff surface.
- `tests/pipelines/metadata_sync/test_cli.py` — the parser, the settings
  regression, and the refresh/compare/plan/merge chain.
- `tests/pipelines/metadata_sync/test_operator.py` — the wizard's action
  bindings and cancellation.
- `tests/pipelines/metadata_sync/test_end_to_end.py` — the full chain over a
  scripted transport.
- `tests/pipelines/metadata_sync/test_manifest.py`, `test_paths.py`,
  `test_sec_client.py`, `test_source_registry.py`, `test_smoke_test.py` — the
  unchanged surfaces.
