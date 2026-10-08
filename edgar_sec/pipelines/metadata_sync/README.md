# metadata_sync

Plans SEC submissions work from a published cohort, fetches and checkpoints
per-CIK results, then publishes immutable Parquet snapshots. Shared cohorts and
official SEC source management are owned by the cohort pipeline and Layer 2 store.

## Module Layout

| Module | Responsibility |
| :--- | :--- |
| `roster.py` | Metadata roster schema, identity, ordinal reads, Parquet publication, and verified cohort adaptation. |
| `options.py` | Plan, run, and augmentation options; resolve published cohort selections. |
| `planner.py` | Plan identity, chunk layout, plan bundle write and validated load. |
| `augmentation.py` | Preflight a requested roster against a published CIK index and write a verified transient delta. |
| `assignment.py` | Divide plan chunks into worker assignments and persist the assignment manifest. |
| `checkpoints.py` | Discover and validate completed chunk checkpoints. |
| `worker.py` | Fetch submissions and checkpoint chunk results. |
| `validation.py` | Validate plan inputs and worker results before merge. |
| `merger.py` | Merge validated chunks and publish immutable snapshots. |
| `snapshot.py` | Load and validate published snapshot manifests and parts. |
| `distribution.py`, `distribution_adapter.py` | Export/import worker bundles through the distribution boundary. |
| `sec_client.py`, `commands/client.py` | Build the SEC submissions client and its cache. |
| `progress.py`, `run_lock.py` | Render execution progress and serialize snapshot writes. |
| `specs.py` | Declare metadata relations for DAG lifecycle operations. |
| `paths.py` | Metadata plan, snapshot, and transient locations. |
| `discovery.py` | Discover plans and published snapshots. |
| `operator.py`, `augment_flow.py` | Interactive cohort selection, lifecycle orchestration, and network consent. |
| `cli.py`, `commands/` | Parse and dispatch public metadata commands. |
| `smoke_test.py` | Run a bounded live fetch into a preview artifact root. |
| `__init__.py`, `commands/__init__.py` | Package markers. |

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
- Plan identity, chunk coverage, checkpoint validation, merge publication, worker
  distribution, and snapshot verification remain owned by their existing modules.

## Public Surface

| Entry point | Owner | Caller |
| :--- | :--- | :--- |
| `python run.py metadata <command>` | `cli` | Shell, automation, and operator wizard |
| `python run.py metadata` | `operator` | Interactive operator |
| `read_snapshot_parts` and snapshot manifest loading | `snapshot` | Snapshot consumers |
| `MetadataPaths`, `resolve_metadata_paths` | `paths` | Metadata pipeline and downstream readers |
| `parts_digest` | `merger` | Dataset identity consumers |

## Command Surface

```text
metadata plan     --cohort <id-or-name>
metadata status   <plan reference>
metadata run      <plan reference> [--chunks 0-3,7] [--chunk N]
metadata merge    <plan reference>
metadata worker   <plan reference> [--worker <id>]
metadata export   <plan reference> --worker-count N --destination <dir>
metadata import   <plan reference> --source <dir>
metadata augment  --cohort <id-or-name>
                  --base-snapshot-id <id> [--new-snapshot-id <id>]
```

Plan references for status, run, merge, worker, export, and import accept a plan id,
a plan bundle, or `--cohort <id-or-name>`. `--artifacts` selects a non-default
artifact root. Source and family-index management remain outside metadata_sync.

## Deliberate Gaps

- Source refresh, cohort administration, cohort diff, and family-index publication
  are outside this pipeline; use the cohort command surface.
- Delta datasets are transient derivations, not catalog-published cohorts. Their
  plan bundle preserves the selected roster for execution and distribution.
- Augmentation is single-host. Its derived delta is executed and merged within the
  command rather than exported for distributed workers.

## Mirrored Tests

`tests/pipelines/metadata_sync/` mirrors the package modules. The tests use scripted
transports and temporary artifacts; no default test requires SEC network access.
