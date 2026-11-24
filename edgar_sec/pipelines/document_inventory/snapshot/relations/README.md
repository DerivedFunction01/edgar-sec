# `edgar_sec.pipelines.document_inventory.snapshot.relations`

## Purpose

Own the merge-relation machinery of snapshot publication: the relation
schema map and DuckDB merge-relation construction, and relation part
descriptors and part writing.

## Contracts

- **Part descriptors are read from the written Parquet itself** — row
  counts, key bounds, and schema are verified against the part on disk,
  never taken from caller claims.
- **Merge relations are constructed in DuckDB** over staged Parquet
  relations, keyed by the relation map defined here.

## Deliberate gaps

None.
