# metadata_sync

Plans SEC submissions work from a CIK roster, fetches and checkpoints per-CIK
results, then publishes immutable Parquet snapshots. Shared cohorts and official
SEC sources are owned by `infra.storage.cohort`; metadata_sync consumes them and
publishes its plans, registry rosters, and snapshots under `metadata/`.

## Module Layout

| Module | Responsibility |
| :--- | :--- |
| `cohort_adapter.py` | Verify shared cohort datasets and load metadata roster handles. |
| `manifest.py` | Register curated CIK files through shared cohort ingestion; count candidate input rows. |
| `roster.py` | Metadata roster schema, identity, ordinal reads, and Parquet publication. |
| `options.py` | Plan, run, and augmentation options; resolve input, registry, cohort, and universe selections. |
| `planner.py` | Plan identity, chunk layout, plan bundle write and validated load. |
| `augmentation.py` | Preflight a requested roster against a published CIK index and write a verified transient delta. |
| `source_registry.py` | Delegate SEC source refresh to `cohort.sources`; expose the active universe identity. |
| `universe.py` | Resolve the active `cik_lookup` cohort and optionally bound it for a plan. |
| `registry.py` | Compare a curated input with a published `company_tickers` cohort and publish a registry roster. |
| `family_index.py` | Build and verify the company-family assignment from the active universe cohort. |
| `paths.py` | Metadata plan, registry, snapshot, and transient locations. |
| `discovery.py` | Discover plans, snapshots, registry rosters, and curated CSV candidates. |
| `operator.py`, `augment_flow.py` | Interactive plan/source selection, lifecycle orchestration, and network consent. |
| `cli.py`, `commands/` | Command parser and implementations. |
| Remaining modules | Worker execution, checkpointing, merging, distribution, SEC transport, and snapshot validation. |

## Contracts

- `--input`, `--roster`, `--cohort`, and `--universe` are mutually exclusive plan
  sources. Curated inputs are registered with shared cohort ingestion; `--cohort`
  resolves a published shared cohort by name or identifier; `--roster` continues to
  address a published metadata registry roster.
- `--universe` resolves the active `cik_lookup` source through the shared catalog.
  Planning does not refresh SEC data. `sources refresh --source cik_lookup` publishes
  the source cohort first.
- A catalog record is adapted only after its relative dataset path resolves through
  `CohortPaths`, its recorded file digest matches, and the dataset passes metadata
  roster schema and row-count validation. The shared CIK-set identity and metadata
  roster identity are separate contracts.
- The interactive plan/augmentation picker pages through published `CohortCatalog`
  entries. Curated CSV and published registry roster references remain available as
  separate choices.
- `sources compare` requires a published `company_tickers` source cohort. Its raw
  payload digest is verified before comparison; effective roster datasets remain
  published in the metadata registry layout.
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
metadata plan     --input <csv> | --roster <registry_id> | --cohort <id-or-name> | --universe
metadata status   <plan reference>
metadata run      <plan reference> [--chunks 0-3,7] [--chunk N]
metadata merge    <plan reference>
metadata worker   <plan reference> [--worker <id>]
metadata export   <plan reference> --worker-count N --destination <dir>
metadata import   <plan reference> --source <dir>
metadata augment  --input <csv> | --roster <registry_id> | --cohort <id-or-name> | --universe
                  --base-snapshot-id <id> [--new-snapshot-id <id>]
metadata sources refresh  [--artifacts <dir>] [--source company_tickers|cik_lookup]
metadata sources compare  --input <csv> --source-cohort <cohort_id>
```

Plan references for status, run, merge, worker, export, and import accept a plan id,
a plan bundle, or one of the four plan sources above. `--artifacts` selects a
non-default artifact root. The command table is the command surface; metadata_sync
does not expose cohort catalog management commands.

## Deliberate Gaps

- Shared cohort lifecycle and catalog administration are outside this pipeline; use
  the shared cohort API/command surface rather than metadata-specific cohort paths.
- Delta datasets are transient derivations, not catalog-published cohorts. Their
  plan bundle preserves the selected roster for execution and distribution.
- Registry comparison preserves listing details by parsing the verified source
  payload in memory; the published shared cohort dataset contains the canonical CIK
  roster, not every ticker observation.
- Augmentation is single-host. Its derived delta is executed and merged within the
  command rather than exported for distributed workers.

## Mirrored Tests

`tests/pipelines/metadata_sync/` mirrors the package modules. The tests use scripted
transports and temporary artifacts; no default test requires SEC network access.
