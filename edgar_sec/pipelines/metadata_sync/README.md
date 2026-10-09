# metadata_sync

Plans SEC submissions work from a published cohort, fetches and checkpoints
per-CIK results, then publishes immutable Parquet snapshots. Shared cohorts and
official SEC source management are owned by the cohort pipeline and Layer 2 store.

## Contracts

- Plan and augmentation commands accept only `--cohort` as their dataset selector.
  It resolves a published cohort name or identifier; the active `universe` and
  `tickers` aliases resolve through the shared source catalog.
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
- Plan identity, chunk coverage, checkpoint validation, merge publication, worker
  distribution, and snapshot verification remain owned by their existing modules.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `augment` | add new CIKs to a published snapshot | `--cohort`, `--base-snapshot-id`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]`, `[--new-snapshot-id]` |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `distrib` | Distributed worker bundle lifecycle | `[--artifacts]` |
| `merge` | publish a snapshot | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--branch]`, `[--expected-branch-tip]` |
| `plan` | generate a deterministic plan | `--cohort`, `[--limit]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]` |
| `run` | execute resumable chunks | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]`, `[--chunks]`, `[--chunk]` |
| `status` | report plan progress | `[--plan-id]`, `[--bundle]`, `[--cohort]`, `[--artifacts]`, `[--chunk-size]`, `[--workers]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```text
metadata plan     --cohort <id-or-name>
metadata status   <plan reference>
metadata run      <plan reference> [--chunks 0-3,7] [--chunk N]
metadata merge    <plan reference> [--branch <name>]
                  [--expected-branch-tip <snapshot-id>]
metadata worker   <plan reference> [--worker <id>]
metadata export   <plan reference> --worker-count N --destination <dir>
metadata import   <plan reference> --source <dir>
metadata augment  --cohort <id-or-name> --base-snapshot-id <id>
                  [--branch <name>] [--new-snapshot-id <id>]
```

Plan references for status, run, merge, worker, export, and import accept a plan id,
a plan bundle, or `--cohort <id-or-name>`. `--artifacts` selects a non-default
artifact root. Source and family-index management remain outside metadata_sync.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── metadata/  # Root of the published metadata dataset.
│   ├── plans/  # Root of published metadata plan bundles.
│   │   └── {plan_id}/  # Directory holding one immutable plan.
│   │       ├── assignments/  # Directory holding one chunk-to-worker mapping per distribution.
│   │       │   └── {assignment_id}.parquet  # Path of one worker assignment dataset.
│   │       ├── input/
│   │       │   └── input_manifest.json  # Diagnostics about where the selected cohort came from.
│   │       ├── roster/
│   │       │   └── ciks.parquet  # The CIK cohort, stored once for the whole plan.
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
