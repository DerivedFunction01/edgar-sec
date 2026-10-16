# fast_query

Layer 5 (`apps/client/fast_query`) package providing sub-50ms catalog querying and lazy on-demand document loading.

## Purpose

`fast_query` executes direct DuckDB scans over catalog Parquet partitions to discover matching SEC filings without invoking the multi-stage document acquisition pipeline. It wires lazy content fetchers, cache-backed document loaders, inverted-primary recovery, and form-family renderers to hydrated `FilingAggregate` instances.

## Contracts

- **Catalog Partition Direct Scan**: Reads catalog targets directly via DuckDB with pushdown predicates on dates and forms.
- **Lazy Content Hydration**: Filing content bytes, attachments, and renderers are instantiated as deferred closures and never fetched eagerly during query resolution.
- **Inversion Recovery**: If primary document screening detects inverted index references, the loader automatically retrieves and parses the `-index.html` page to resolve the true primary document.
- **Zero Barrel Re-exports**: Child symbols (`query_catalog_fast`, `make_document_fetcher`, `make_filing_renderer`) must be imported directly from their owning leaf modules.

## Deliberate gaps

- **Offline Catalog Reliance**: When catalog partitions are absent, falls back to direct SEC submissions JSON API for specified CIKs rather than executing local cohort planning.
