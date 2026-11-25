# `edgar_sec.pipelines.document_inventory.snapshot.publication`

## Purpose

Own snapshot publication: validation and staging of a run's committed
attempts, candidate staging and accession anti-joins, validation of the
complete staged snapshot, installation, and bounded merge with pointer-last
publication of validated attempts.

## Contracts

- **The current pointer advances only after the complete snapshot has been
  validated and installed**, under a publication lock after a stale-parent
  check.
- **Candidate and current relations remain in Parquet or DuckDB**; the
  anti-join emits Parquet relations instead of materializing whole keys in
  Python.

## Deliberate gaps

None.
