# `edgar_sec/apps/client` — Layer 5: convenience client and relational dataframes

## Purpose

This package provides a pythonic convenience facade (`Edgar`) and relational DataFrame
models (`FilingsResult`) that give analysts and developers fast, expressive access to SEC
filings without managing intermediate pipeline states.

It presents acquired targets as zero-copy Arrow, Pandas, or DuckDB relations, and supports
lazy row-level polymorphic report projection (`as_report()`).

## Contracts

- **Relational by default**: Filings cohorts are queried and exported as DataFrames rather than eager object graphs.
- **Bounded facade cache**: `Edgar.xbrl()` revisits return the identical live facade from an LRU cache whose capacity derives from `derive_resources()`; eviction drops the whole kernel and the next miss re-parses the filing.
- **Bounded content cache**: Filing text and parsed section/note sequences share one byte-bounded LRU per `Edgar` instance, its budget a settings fraction of one worker memory share; derivations over the RAM admission cap or evicted from RAM spill to a bounded disk tier instead of being dropped, and text is capped to a small share because it re-reads from the document cache beneath the facade.
- **Corpus coordinate index**: Ingest projects each facade's display records into the DuckDB corpus index verbatim; corpus search and comparison screening filter the index and materialize only surviving filings, ranking with the same ladder as per-facade search.
- **Batch streaming**: Batch runs stream one outcome per filing under `apps.client.batch`: at most one facade live per worker, nothing accumulated by the runner, and a filing's failure — including its worker's death — is recorded as that filing's named error in the run's result.
- **Lazy row projection**: `FilingAggregate` models are hydrated on demand when indexing specific rows.
- **Zero-copy analytical query**: DuckDB queries run directly over Parquet partitions in the artifact store.
- **Local-first submissions fallback**: When the fast path must fall back to submissions data, CIKs covered by the latest published submissions snapshot are materialized locally from it; only uncovered CIKs go to the live per-CIK fetch.
- **Concept lookups serve reported values**: `Company.concept()` returns SEC-reported values exactly as reported, one row per data point with its provenance; it is a lookup and cross-check surface that never feeds the financial statements machinery.

## Deliberate gaps

- **No result-side state caching**: `FilingsResult` pointers reference published pipeline artifacts rather than client memory; caching lives in the bounded facade LRU and the SQLite document cache, not in the result model.
- **No network code in data models**: `FilingsResult` and `FilingAggregate` issue no requests themselves; the fetch closures injected into an aggregate fetch live, lazily, when its payload is read.
