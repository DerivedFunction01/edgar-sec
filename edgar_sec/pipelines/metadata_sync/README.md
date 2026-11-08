# metadata_sync

Plans SEC submissions work from a published cohort, fetches and checkpoints
per-CIK results, then publishes immutable Parquet snapshots. Shared cohorts and
official SEC source management are owned by the cohort pipeline and Layer 2 store.

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

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `augment` | add new CIKs to a published snapshot | `--cohort`, `--base-snapshot-id`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--confirm-stale-lock]`, `[--new-snapshot-id]` |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `distrib` | Distributed worker bundle lifecycle | — |
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
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── bulk_archives/  # Root of the shared bulk-archive store (all sources, all pipelines).
├── metadata/  # Root of the published metadata dataset.
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
