# `edgar_sec/apps/client` — Layer 5: convenience client and relational dataframes

## Purpose

This package provides a pythonic convenience facade (`Edgar`) and relational DataFrame
models (`FilingsResult`) that give analysts and developers fast, expressive access to SEC
filings without managing intermediate pipeline states.

It presents acquired targets as zero-copy Arrow, Pandas, or DuckDB relations, and supports
lazy row-level polymorphic report projection (`as_report()`).

The facade also exposes the SEC's pre-extracted company facts for one company
(`Edgar.company_facts(cik)`), strictly as an oracle: SEC-reported values are
compared against the parser's own output, never served as answers.

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
- **Company facts are cross-check only**: `Edgar.company_facts(cik)` fetches one CIK's companyfacts document through the shared `SecHttpClient` — rate limiter, identity, response cache, and failure ledger unchanged — and maps it to typed rows carrying taxonomy, tag, unit, value, period, accession, form, filed, and frame where served. The endpoint is an oracle against the parser's own output, not a serving source, and its rows are never re-shaped into a per-filing facts store at this layer.
- **Facts comparison reports four outcome classes**: The cross-check consumer joins company-facts rows to instance-parsed values on (taxonomy, tag, unit, start, end), taking each key's facts side from its latest-filed point because amendment vintages coexist in the document, and reports agree / diverge / facts-only / parsed-only. A parsed absence is facts-only, never a divergence.
- **Operator session and registry**: `run.py fetch` fronts a session-and-registry operator (`operator.py` and its sibling row modules). One in-process `ClientSession` holds named working sets, a current-filing position, and a read context (mode, snapshot position). Every capability is a registry row with typed options, a closed effect / requires / result-kind vocabulary, and a closed error-code vocabulary; the hosts — the interactive menu, the `--op` argv host, the `--config` host — only gather, dispatch, and render, so a result is the same object in text and JSON (JSON is always offered, and an error result's JSON carries its message). Discovery is generated from the registry itself (`--list-operations`, per-operation help); this README deliberately does not enumerate the operations.
- **Run records for external work only**: operations with external effect write one canonical JSON record per run under the artifacts root's operator-runs area, listed and inspected through the operator's own past-runs rows; read-only operations write nothing.
- **Config files are the only persistence**: the non-interactive full flow is a versioned JSON config (`format_version` "1.0") declaring session defaults, named sets, and an operations sequence, validated whole before anything executes. Session-field precedence is host > config > session > settings, and every config run reports each field's source. Sessions themselves are never persisted.
- **Agent-use posture**: the fetch CLI's primary user is an agent executing commissioned work, so operations must be discoverable and invocable from the CLI's own surfaces alone, refusals are coded and self-explaining, and absence is rendered honestly — an incapable action or an unheld datum says so — rather than back-filled.

## Deliberate gaps

- **No result-side state caching**: `FilingsResult` pointers reference published pipeline artifacts rather than client memory; caching lives in the bounded facade LRU and the SQLite document cache, not in the result model.
- **No network code in data models**: `FilingsResult` and `FilingAggregate` issue no requests themselves; the fetch closures injected into an aggregate fetch live, lazily, when its payload is read.
- **No company-facts serving leg**: Company facts have no answer path in this package; corpus-scale cross-check reads come from the bulk facts store published by `metadata_sync`, and a serving posture would require a new ruling.
- **No MCP or AI server**: the operator is a CLI by ruling; edgartools' MCP surface informed behaviour only, and no server is built or planned.
- **Store-shaped rows, no adapters**: `seed_snapshot` takes CIKs — the snapshot query's own vocabulary — not tickers, with the company operation as the name-to-CIK bridge; the dataset stores (BDC / N-MFP / MFRR) arrive as bulk-archive source ids by data, with no dataset-specific operations.
- **`save_bundle` declares its own absence**: the filing aggregate exposes no public attachment-content shape, so the bundle row returns an honest `absent`; only the primary-document payload is saveable until a facade accessor exists.
