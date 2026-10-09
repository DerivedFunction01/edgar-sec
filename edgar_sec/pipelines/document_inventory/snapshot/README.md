# `edgar_sec.pipelines.document_inventory.snapshot`

## Purpose

Own inventory snapshot relations, pre-fetch plan projection, and bounded merge primitives.

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

## Usage examples

None; commands are owned by `document_inventory.cli`.

## Deliberate gaps

- Refreshes mask superseded entry rows from active views, but no snapshot artifact
  records the direct IDs of the entries replaced by a refresh.
