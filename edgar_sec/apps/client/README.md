# `edgar_sec/apps/client` — Layer 5: convenience client and relational dataframes

## Purpose

This package provides a pythonic convenience facade (`Edgar`) and relational DataFrame
models (`FilingsResult`) that give analysts and developers fast, expressive access to SEC
filings without managing intermediate pipeline states.

It presents acquired targets as zero-copy Arrow, Pandas, or DuckDB relations, and supports
lazy row-level polymorphic report projection (`as_report()`).

## Contracts

- **Relational by default**: Filings cohorts are queried and exported as DataFrames rather than eager object graphs.
- **Lazy row projection**: `FilingAggregate` models are hydrated on demand when indexing specific rows.
- **Zero-copy analytical query**: DuckDB queries run directly over Parquet partitions in the artifact store.

## Deliberate gaps

- **No client-side state caching**: Pointers reference published pipeline artifacts rather than client memory.
- **No live network fetches in data models**: `FilingsResult` and `FilingAggregate` perform no network I/O.
