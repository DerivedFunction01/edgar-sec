# `edgar_sec.pipelines.document_inventory.snapshot`

## Purpose

Own inventory snapshot relations, pre-fetch plan projection, and bounded merge primitives.

## Module layout

| Module | Responsibility |
|---|---|
| `anti_join.py` | Stage candidate relations incrementally and classify them in DuckDB. |
| `errors.py` | Snapshot validation and stale-parent failures. |
| `models.py` | Snapshot metadata, lookup descriptors, and publication results. |
| `projection.py` | Validate the published cohort projection, produce normalized relations, and write the pre-fetch work order. |
| `projection_inputs.py` | Validate catalog-plan bundles and resolve pinned base-snapshot accession parts. |
| `reader.py` | Range-pruned point queries for active accessions, entries, and source CIKs; every query accepts an immutable `snapshot_id` pin or falls back to the active branch tip. |
| `schema.py` | Versioned Arrow schemas for persisted snapshot relations. |
| `specs.py` | Declarative `RelationSpec` contracts (`accessions`, `entries`, `accession_sources`). |
| `validation.py` | Check all declared Parquet files, digests, relations, and lookup parity. |
| `writer.py` | Merge validated committed S4 attempts and publish immutable snapshots. |

## Contracts

- Candidate and current accession/source relations remain in Parquet or DuckDB; the
  anti-join emits Parquet relations instead of materializing whole keys in Python.
- Snapshot data is immutable after publication; the current pointer is advanced only
  after the complete snapshot has been validated and installed under a publication
  lock after a stale-parent check.
- Unchanged annual relation parts are inherited by manifest reference; snapshot files
  and pointers are owned by `document_inventory.paths`.
- Filing-CIK identity and catalog source-CIK associations use distinct relations.
- Catalog plans are projected before S4; normalized cohort facts and source edges are
  retained separately, and only missing accession pages enter the work order.

## Public surface

Call [`project_catalog_plan`](projection.py) to create a run pinned to the selected
branch tip, then run its pending work and call
[`publish_committed_chunks`](writer.py) to publish validated committed attempts.
[`validate_snapshot`](validation.py) checks a published or staged snapshot.
[`get_active_accession`](reader.py), [`get_active_entries`](reader.py),
[`get_accessions_by_cik`](reader.py), [`get_accessions_by_source_cik`](reader.py),
[`query_accessions`](reader.py), and [`get_accession_bundle`](reader.py) query active snapshot state.
Each accepts `snapshot_id` to pin an immutable snapshot tip; without it, the
active branch pointer is resolved once per call.

The approved command lifecycle exposes `inventory project`, `inventory run`,
`inventory status`, and `inventory publish`. Project and Publish are offline;
Status is read-only; Run is the only lifecycle operation that requests SEC pages.
Publish requires the selected branch's current tip to equal the run's pinned base.
Publication consumes validated persisted runs and never invokes projection or S4.

## Command surface

None; commands are owned by `document_inventory.cli`.

## Mirrored tests

`tests/pipelines/document_inventory/snapshot/`.

## Deliberate gaps

- Refreshes mask superseded entry rows from active views, but no snapshot artifact
  records the direct IDs of the entries replaced by a refresh.
