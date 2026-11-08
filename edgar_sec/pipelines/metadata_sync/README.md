# metadata_sync

Plans SEC submissions work from a published cohort, fetches and checkpoints
per-CIK results, then publishes immutable Parquet snapshots. Shared cohorts and
official SEC source management are owned by the cohort pipeline and Layer 2 store.
The package also carries a self-contained company-facts leg: the nightly
companyfacts bulk archive is normalized into its own DuckDB facts store and
published through the DAG as a cross-check corpus.

## Contracts

- Plan accepts a published `--cohort` or `--from-archive` as its dataset selector;
  augmentation accepts only `--cohort`. A cohort resolves a published cohort name
  or identifier; the active `universe` and `tickers` aliases resolve through the
  shared source catalog. `--from-archive` plans over the stored submissions bulk
  archive's own membership, with per-CIK fingerprints derived from member CRCs.
- Metadata planning is offline and never refreshes official sources. Use the cohort
  command surface to refresh a source before selecting its active alias.
- A catalog record is adapted only after its relative dataset path resolves through
  `CohortPaths`, its recorded file digest matches, and the dataset passes metadata
  roster schema and row-count validation. The shared CIK-set identity and metadata
  roster identity are separate contracts.
- Interactive planning and augmentation select only published `CohortCatalog`
  entries through the shared runtime picker.
- Company-family assignment publication belongs to the cohort pipeline. Downstream
  policy planning consumes a pre-published active index and never builds one lazily;
  metadata_sync exposes no family-index management item.
- Augmentation computes `requested - base` with shared cohort operations and writes
  its verified delta under metadata transient storage. The plan bundle contains the
  roster it needs; no metadata-local cohort store is created.
- Merge and augment publish durable snapshots to the selected DAG branch (default
  `main`) under a shared CAS guard. `--branch` selects the branch; `--expected-branch-tip`
  pins the branch pointer expected at commit and refuses the publish (without moving the
  pointer) if the branch moved. `--base-snapshot-id` selects the delta parent for
  augmentation; it is not the target branch and never rewinds `main`.
- A run may instead source every CIK from the single submissions bulk archive
  (`run --bulk`): the archive carries full history, historical shards included,
  and each row records its provenance (bulk source, archive digest, per-member
  hash). Bulk normalization is pure-Python work and runs on a spawn process
  pool created once per run and held warm across chunks; the per-CIK fetch
  path keeps its thread pool, being network-bound.
- The bulk archive lands in the shared bulk-archive store before use, and an
  archive plan binds the stored digest: the run reads that archive, never a
  fresher download. `run --carry-from <snapshot>` on an archive plan reuses a
  prior snapshot's rows for CIKs whose member CRCs are unchanged, re-stamping
  only snapshot identity and fetch time; the run summary reports carried versus
  normalized rows. Archive baselines publish as DAG checkpoints carrying the
  archive identity in their manifest metadata, on their own branch — the
  catalog of record adopts one only by a later explicit pointer move.
- Plan identity, chunk coverage, checkpoint validation, merge publication, worker
  distribution, and snapshot verification remain owned by their existing modules.
- A run lock is never taken from a live local owner. `--confirm-stale-lock` attests
  that the recorded holder has stopped, and refuses a lock naming a live process on
  this host even when attested; a lock naming another host cannot be checked locally,
  so the attestation is the only evidence. A lock that cannot be read is not evidence
  of staleness and is refused.
- The company-facts leg is a batch command, not a plan shape. `facts` downloads the
  companyfacts bulk archive through `SecHttpClient.stream_to_file` (byte bound from
  the bulk-archive setting) into the shared bulk-archive store under source id
  `companyfacts_bulk`, or with `--from-store` ingests the newest stored archive
  without downloading. It does not join the plan/run/merge machinery.
- Facts normalization is member-level and never mass-extracts. Members are planned
  from the store's member index and read per CIK through the memory-mapped index;
  a warm spawn pool created once per ingest (worker count from `derive_resources()`)
  maps the shared index in its children, and rows batch into DuckDB-side tables
  keyed by (CIK, taxonomy, tag, unit, end, accession) — never a Python fact list.
  Normalization is pipeline-local, mirroring the client company-facts mapping
  field-for-field, because the layer boundary forbids importing the apps layer.
- Re-ingest carries unchanged members forward by member CRC. A member whose CRC
  fingerprint is unchanged keeps its stored rows untouched, including the archive
  SHA that produced them; a changed member is replaced, and CIKs absent from the
  new archive are removed.
- The facts store publishes as a versioned DAG snapshot with archive lineage. The
  DuckDB store (`company_facts`, `fact_members`, `fact_archives`) is published as
  Parquet parts under a content-addressed snapshot id over the archive SHA, the
  member fingerprint set, and the row count; the manifest carries `archive_sha256`
  and `source_id`. Republishing identical content is a no-op.
- Facts reads are local. `read_facts_for_cik` and `facts_for_concept` serve frozen
  stored-fact rows from the store file with no HTTP, so the client cross-check can
  run at corpus scale against the store. Fact values are stored as DuckDB DOUBLE,
  matching the cross-check's float comparison.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `augment` | add new CIKs to a published snapshot | `--cohort`, `--base-snapshot-id`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--confirm-stale-lock]`, `[--new-snapshot-id]` |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `distrib` | Distributed worker bundle lifecycle | — |
| `facts` | ingest the companyfacts bulk archive into the facts store | `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--from-store]` |
| `merge` | publish a snapshot | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--confirm-stale-lock]` |
| `plan` | generate a deterministic plan | `[--cohort]`, `[--limit]`, `[--from-archive]`, `[--archive-sha]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]` |
| `reconcile` | reconcile the tip against the daily index | `--start-date`, `--end-date`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--confirm-stale-lock]`, `[--new-snapshot-id]` |
| `refresh` | refresh stale CIKs from the current-filings feed | `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--confirm-stale-lock]`, `[--new-snapshot-id]` |
| `run` | execute resumable chunks | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--chunks]`, `[--chunk]`, `[--confirm-stale-lock]`, `[--bulk]`, `[--carry-from]` |
| `status` | report plan progress | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Generate a plan for a cohort
python run.py metadata plan --cohort my-cohort --chunk-size 50 --workers 4

# Check plan status
python run.py metadata status --plan-id 2024-01-15T120000Z

# Run the plan with parallel workers
python run.py metadata run --plan-id 2024-01-15T120000Z --chunks 0-9

# Resume a run whose previous owner stopped, attesting the stale lock
python run.py metadata run --plan-id 2024-01-15T120000Z --confirm-stale-lock

# Export plan work, execute bundles on separate machines, then import them
python run.py metadata distrib commands --work-id 2024-01-15T120000Z --workers 2
python run.py metadata distrib export --work-id 2024-01-15T120000Z --workers 2
python run.py metadata distrib worker --bundle /path/to/worker-00 --threads 4
python run.py metadata distrib import --work-id 2024-01-15T120000Z --source /path/to/worker-00

# Merge results into a snapshot
python run.py metadata merge --plan-id 2024-01-15T120000Z --branch main

# Augment existing snapshot with new CIKs
python run.py metadata augment --cohort new-cohort --base-snapshot-id 2024-01-15T120000Z

# Reconcile the tip against the daily index over a date range
python run.py metadata reconcile --start-date 2026-11-02 --end-date 2026-11-06

# Ingest the companyfacts bulk archive into the facts store and publish it
python run.py metadata facts

# Re-ingest the newest stored companyfacts archive without downloading
python run.py metadata facts --from-store
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── bulk_archives/  # Root of the shared bulk-archive store (all sources, all pipelines).
├── metadata/  # Root of the published metadata dataset.
│   ├── facts/  # Root of the company-facts store and its published snapshots.
│   │   ├── snapshots/  # Root of published facts snapshot directories, and of the pointer.
│   │   │   └── catalog.sqlite  # SQLite DAG catalog database for published facts snapshots.
│   │   └── companyfacts.duckdb  # The DuckDB company-facts store.
│   ├── plans/  # Root of published metadata plan bundles.
│   │   └── {plan_id}/  # Directory holding one immutable plan.
│   │       ├── assignments/  # Directory holding one chunk-to-worker mapping per distribution.
│   │       │   └── {assignment_id}.parquet  # Path of one worker assignment dataset.
│   │       ├── input/
│   │       │   └── input_manifest.json  # Diagnostics about where the selected cohort came from.
│   │       ├── roster/
│   │       │   └── ciks.parquet  # The CIK cohort, stored once for the whole plan.
│   │       ├── fingerprints.parquet  # Per-CIK member-CRC fingerprints for an archive plan.
│   │       ├── plan.json  # Small execution manifest for this plan.
│   │       └── run.lock  # Exclusive run lock for this plan.
│   └── snapshots/  # Root of published snapshot directories.
│       └── {snapshot_id}/  # Directory holding one published snapshot.
│           ├── parts/  # Directory holding the Parquet parts of a multipart snapshot.
│           │   └── {part_name}  # Path of one metadata part within a multipart snapshot.
│           ├── ciks.parquet  # Sorted distinct CIK index published beside one snapshot payload.
│           └── run.lock  # Exclusive run lock for a published snapshot (used by augment).
└── transient/
    └── metadata/
        ├── facts-{run_id}/  # Staging directory for one facts run, never published.
        └── {plan_id}/  # Directory holding one plan's transient chunk checkpoints.
            └── chunk_{chunk_id}.parquet  # Checkpoint path for one chunk.
```
<!-- AUTOGEN:PATHS:END -->

## Deliberate Gaps

- Source refresh, cohort administration, cohort diff, and family-index publication
  are outside this pipeline; use the cohort command surface.
- Delta datasets are transient derivations, not catalog-published cohorts. Their
  plan bundle preserves the selected roster for execution and distribution.
- Augmentation is single-host. Its derived delta is executed and merged within the
  command rather than exported for distributed workers.
- The facts leg has no operator menu entry; it is a batch command only, like the
  datasets import.
- The facts store is a cross-check corpus, not a serving source: no facade answer
  reads it, and a facts serving posture would require a new ruling.
