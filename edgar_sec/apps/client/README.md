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

The financials surface also derives trailing-twelve-month (TTM) values for the
flow metrics it serves — within one filing, and across filings over the stitched
series — and composes the same derivation from company-facts points strictly as
a comparison leg.

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
- **TTM status is always DERIVED**: `XbrlFinancials.ttm(metric)`, its per-metric accessors, and `Company.ttm(...)` over the stitched series return a statused result carrying its legs and period end; a TTM is never REPORTED, however reported its legs are.
- **Four quarters, completely accounted**: A TTM value exists only when all four quarters of its window are accounted for — reported quarters stand as filed, and a missing quarter is derived only from exact cumulative-span chaining with its inputs named. A window that cannot close serves UNAVAILABLE naming the missing quarter(s), never a partial sum, and where two closing routes exist they must agree or the result is UNAVAILABLE naming the disagreement.
- **Per-share TTM is a derived ratio, never a sum**: EPS TTM is the same run's TTM net income divided by its TTM weighted-average shares at the same period end; weighted shares are a day-weighted derivation from cumulative spans, and filed EPS is never served as a TTM value.
- **Duration flows only, breaks respected**: Instant concepts gain no TTM variant and a stitched series has no instant read at all; CUMULATIVE spans never serve as legs; a cross-filing window may not cross a recorded series break and is refused with the break named.

## Deliberate gaps

- **No result-side state caching**: `FilingsResult` pointers reference published pipeline artifacts rather than client memory; caching lives in the bounded facade LRU and the SQLite document cache, not in the result model.
- **No network code in data models**: `FilingsResult` and `FilingAggregate` issue no requests themselves; the fetch closures injected into an aggregate fetch live, lazily, when its payload is read.
- **No company-facts serving leg**: Company facts have no answer path in this package; corpus-scale cross-check reads come from the bulk facts store published by `metadata_sync`, and a serving posture would require a new ruling.
- **No split adjustment**: TTM values are served on the as-reported basis, named on every result; no split-detection or adjustment machinery exists, monetary flows are unaffected by splits, and building that machinery is a separate item if ever wanted.
- **Facts-side TTM serves nothing**: The TTM composed from company-facts points exists only as the comparison leg beside the parsed-side result, under the same four outcome classes; no facts-derived TTM is an answer anywhere.
- **Cross-filing scope bounded by the stitched series**: Stitched TTM serves exactly the metric classes the stitched series serves, inheriting its breaks and per-leg provenance; no stitching is built or widened at this layer.
- **No calc-ancestor yield over a series**: Net income over a stitched series reads its filter ladder directly; the within-filing calc-ancestor yield has no series analogue, so a concept reachable only through that yield is absent cross-filing.
- **No unit adjudication over a series**: Same-concept spans reported in multiple units keep the first series-ordered value rather than an adjudicated one.
