# `edgar_sec.pipelines.document_inventory.snapshot`

## Purpose

Own the immutable inventory snapshot format and bounded publication/query primitives.

## Module layout

| Module | Responsibility |
|---|---|
| `anti_join.py` | Stage candidate relations incrementally and classify them in DuckDB. |
| `errors.py` | Publication and query refusal types. |
| `models.py` | Snapshot metadata, lookup descriptors, and publication results. |
| `paths.py` | Resolve immutable snapshot and per-run publication paths. |
| `schema.py` | Versioned Arrow schemas for persisted snapshot relations. |

## Contracts

- Candidate and current accession/source relations remain in Parquet or DuckDB; the
  anti-join emits Parquet relations instead of materializing whole keys in Python.
- Snapshot data is immutable after publication; the current pointer is advanced only
  after the complete snapshot has been validated.
- Filing-CIK identity and catalog source-CIK associations use distinct relations.

## Public surface

Import publication primitives from their owning modules, especially
[`anti_join.py`](anti_join.py) and [`models.py`](models.py).

## Command surface

None; commands are owned by `document_inventory.cli`.

## Mirrored tests

`tests/pipelines/document_inventory/snapshot/`.

## Deliberate gaps

- The full snapshot writer, reader query API, validation suite, and pointer-last publisher
  are not implemented yet; only bounded staging and anti-join primitives are present.
