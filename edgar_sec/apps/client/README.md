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

The facade also exposes SEC frames (`Edgar.frames(taxonomy, tag, unit,
period)`): cross-company aggregates for one concept and period, served with
their frame identity as provenance and joined to parsed per-filing facts
only as a comparison.

One filing's earnings exhibit is extracted through
`Edgar.earnings_exhibit(filing)`, serving the exhibit's typed tables and
headline figures as printed, with unextractable structure accounted as
review signals.

One filing's attachments are served as an object collection
(`Edgar.attachments(filing)`) with typed selectors, an acquisition-state
accessor, and explicit payload accessors.

The financials surface also derives trailing-twelve-month (TTM) values for the
flow metrics it serves — within one filing, and across filings over the stitched
series — and composes the same derivation from company-facts points strictly as
a comparison leg.

The facade also resolves fund series and classes from the published
series/class reference relation — series and class lookups, classes of a
series, series of a registrant, class by ticker, and N-MFP series resolution —
and the operator carries one fund row that refreshes that relation by command.

## Contracts

- **Relational by default**: Filings cohorts are queried and exported as DataFrames rather than eager object graphs.
- **Bounded facade cache**: `Edgar.xbrl()` revisits return the identical live facade from an LRU cache whose capacity derives from `derive_resources()`; eviction drops the whole kernel and the next miss re-parses the filing.
- **Bounded content cache**: Filing text and parsed section/note sequences share one byte-bounded LRU per `Edgar` instance, its budget a settings fraction of one worker memory share; derivations over the RAM admission cap or evicted from RAM spill to a bounded disk tier instead of being dropped, and text is capped to a small share because it re-reads from the document cache beneath the facade.
- **Corpus coordinate index**: Ingest projects each facade's display records into the DuckDB corpus index verbatim; corpus search and comparison screening filter the index and materialize only surviving filings, ranking with the same ladder as per-facade search.
- **Batch streaming**: Batch runs stream one outcome per filing under `apps.client.batch`: at most one facade live per worker, nothing accumulated by the runner, and a filing's failure — including its worker's death — is recorded as that filing's named error in the run's result.
- **Lazy row projection**: `FilingAggregate` models are hydrated on demand when indexing specific rows.
- **One aggregate per accession, attachments retained**: Plan-backed iteration groups a filing's target rows into one aggregate; acquired non-primary targets — planned or run-ephemeral — ride it as attachments, so exhibits and linkbases surface on the aggregate instead of as sibling pseudo-filings.
- **Zero-copy analytical query**: DuckDB queries run directly over Parquet partitions in the artifact store.
- **Local-first submissions fallback**: When the fast path must fall back to submissions data, CIKs covered by the latest published submissions snapshot are materialized locally from it; only uncovered CIKs go to the live per-CIK fetch.
- **Concept lookups serve reported values**: `Company.concept()` returns SEC-reported values exactly as reported, one row per data point with its provenance; it is a lookup and cross-check surface that never feeds the financial statements machinery.
- **Company facts are cross-check only**: `Edgar.company_facts(cik)` fetches one CIK's companyfacts document through the shared `SecHttpClient` — rate limiter, identity, response cache, and failure ledger unchanged — and maps it to typed rows carrying taxonomy, tag, unit, value, period, accession, form, filed, and frame where served. The endpoint is an oracle against the parser's own output, not a serving source, and its rows are never re-shaped into a per-filing facts store at this layer.
- **Facts comparison reports four outcome classes**: The cross-check consumer joins company-facts rows to instance-parsed values on (taxonomy, tag, unit, start, end), taking each key's facts side from its latest-filed point because amendment vintages coexist in the document, and reports agree / diverge / facts-only / parsed-only. A parsed absence is facts-only, never a divergence.
- **Frames are SEC aggregates, never per-filing facts**: `Edgar.frames(...)` fetches one frame through the shared `SecHttpClient` and serves its rows as SEC aggregates whose provenance is the frame identity (taxonomy, tag, unit, period); the comparison to parsed facts is the only join, and a frame value is never served as a filing's fact.
- **Operator session and registry**: `run.py fetch` fronts a session-and-registry operator (`operator.py` and its sibling row modules). One in-process `ClientSession` holds named working sets, a current-filing position, and a read context (mode, snapshot position). Every capability is a registry row with typed options, a closed effect / requires / result-kind vocabulary, and a closed error-code vocabulary; the hosts — the interactive menu, the `--op` argv host, the `--config` host — only gather, dispatch, and render, so a result is the same object in text and JSON (JSON is always offered, and an error result's JSON carries its message). Discovery is generated from the registry itself (`--list-operations`, per-operation help); this README deliberately does not enumerate the operations.
- **Run records for external work only**: operations with external effect write one canonical JSON record per run under the artifacts root's operator-runs area, listed and inspected through the operator's own past-runs rows; read-only operations write nothing.
- **Config files are the only persistence**: the non-interactive full flow is a versioned JSON config (`format_version` "1.0") declaring session defaults, named sets, and an operations sequence, validated whole before anything executes. Session-field precedence is host > config > session > settings, and every config run reports each field's source. Sessions themselves are never persisted.
- **Agent-use posture**: the fetch CLI's primary user is an agent executing commissioned work, so operations must be discoverable and invocable from the CLI's own surfaces alone, refusals are coded and self-explaining, and absence is rendered honestly — an incapable action or an unheld datum says so — rather than back-filled.
- **One canonical attachment row**: Both loaders' attachment objects, the cross-filing index/exhibits/linkbases tables, and the snapshot SQL views all project from the canonical attachment row; identity is the inventory `entry_id` end to end and sequence is a typed field, never recovered from a string. Role and is-exhibit each have exactly one Python derivation, and their SQL translations are pinned against the Python forms by tests.
- **Attachment storage tiers**: Per-filing object graphs live in memory only and hold no payload bytes beyond a single accessor call; cross-filing attachment facts are DuckDB/PyArrow projections over the published DAG relations; payload bytes stay content-addressed by sha256 in the acquisition snapshot, and the SQLite document cache is a mutable fetch cache, never a query surface.
- **Explicit-accessor fetch**: Enumerating or selecting attachments never fetches, and the state accessor reports store presence (snapshot payload index; document-cache row) without retrieval. Calling `content()` or `rendered_text()` is the caller's explicit act and may fetch and cache.
- **Bundle saves fall back to the filing's documents**: `save_bundle` writes the EDGAR full-submission bundle where its fetcher is held; on an aggregate without that vehicle (snapshot-built) it writes a zip of the filing's documents from the attachment graph — payloads byte as filed via `content()`, the save act itself the fetch — reporting the documents written and any payload that could not be obtained. With neither vehicle nor an obtainable payload it returns `absent`.
- **Two text semantics, distinctly named**: `text()` is the plain decode existing consumers observe; `rendered_text()` rides the injected renderer, with PDF payloads converted through the PDF text-layer route.
- **Two role vocabularies, never merged**: The observed role (primary, exhibit, data_file, graphic, package) and the body-assessed role (primary, exhibit, schedule) are different facts about a document and are named distinctly at every surface they meet.
- **Earnings exhibits serve values as printed**: `Edgar.earnings_exhibit(filing)` returns the engine extractor's result — the selected exhibit, its typed tables, and the headline figures those tables carry, values exactly as printed — and every table the extractor cannot structure rides the result as a named review signal rather than a best-effort parse; exhibit selection and extraction semantics are owned by `engine/forms/earnings`.
- **Stitched series surface**: `Company.stitched_series()` and `Company.stitched_financials()` assemble one filer's filings — CIK + form family + date range, or an explicit accession list — into exact-period values with per-value provenance; the selected set is recorded on the result, and no value serves without a source accession.
- **Derived quarters on the stitched surface**: `StitchedFinancials` adds derived discrete quarters to the reported winners only where the selected set reports no quarter for the span; each derived value is status DERIVED with its filed legs named, and a chain that cannot close surfaces as a recorded refusal with its reason, not a silent absence.
- **TTM status is always DERIVED**: `XbrlFinancials.ttm(metric)`, its per-metric accessors, and `Company.ttm(...)` over the stitched series return a statused result carrying its legs and period end; a TTM is never REPORTED, however reported its legs are.
- **Four quarters, completely accounted**: A TTM value exists only when all four quarters of its window are accounted for — reported quarters stand as filed, and a missing quarter is derived only from exact cumulative-span chaining with its inputs named. A window that cannot close serves UNAVAILABLE naming the missing quarter(s), never a partial sum, and where two closing routes exist they must agree or the result is UNAVAILABLE naming the disagreement.
- **Per-share TTM is a derived ratio, never a sum**: EPS TTM is the same run's TTM net income divided by its TTM weighted-average shares at the same period end; weighted shares are a day-weighted derivation from cumulative spans, and filed EPS is never served as a TTM value.
- **Duration flows only, breaks respected**: Instant concepts gain no TTM variant and a stitched series has no instant read at all; CUMULATIVE spans never serve as legs; a cross-filing window may not cross a recorded series break and is refused with the break named.
- **Series/class reads are local, absence honest**: The series/class lookups and the N-MFP resolution read only the published relation's snapshot tip; a miss — an unknown id, a missing tip — answers with absence (None, empty, or `found=False`), and no read path ever fetches a browse page live.
- **Merged layers, one row per listing**: Lookup answers merge the relation's two layers per (series, class) listing — names come from the browse layer only, and the ticker file's symbol wins where both layers carry the listing — so series and ticker listings serve every listing of a cross-listed class, while one class id still yields exactly one `fund_class` answer: its first listing by series id.
- **N-MFP conflicts are reported, not resolved**: `resolve_nmfp_series` cross-checks the document's series name and registrant CIK against the relation and reports disagreements as named conflicts; neither side is overridden.
- **Fund refresh is one operator row**: `fund_series_class` carries an action discriminator (refresh / reconcile / status) rather than one row per action; only refresh writes a run record, matching the registry's external-only record scope.

## Deliberate gaps

- **No result-side state caching**: `FilingsResult` pointers reference published pipeline artifacts rather than client memory; caching lives in the bounded facade LRU and the SQLite document cache, not in the result model.
- **No network code in data models**: `FilingsResult` and `FilingAggregate` issue no requests themselves; the fetch closures injected into an aggregate fetch live, lazily, when its payload is read.
- **No company-facts serving leg**: Company facts have no answer path in this package; corpus-scale cross-check reads come from the bulk facts store published by `metadata_sync`, and a serving posture would require a new ruling.
- **No MCP or AI server**: the operator is a CLI by ruling; edgartools' MCP surface informed behaviour only, and no server is built or planned.
- **Store-shaped rows, no adapters**: `seed_snapshot` takes CIKs — the snapshot query's own vocabulary — not tickers, with the company operation as the name-to-CIK bridge; the dataset stores (BDC / N-MFP / MFRR) arrive as bulk-archive source ids by data, with no dataset-specific operations.
- **Snapshot attachment identity is honestly absent**: No published acquisition relation carries `entry_id`, `table_kind`, or `description`, so snapshot-hydrated attachments serve those fields as `None`; closing the gap needs a published-relation change, not a client-side derivation.
- **Snapshot role never fires data_file**: The snapshot views have no `table_kind` source, so the data_file branch of the single role derivation never fires there; a selector or matcher rule depending on a sometimes-absent field names that dependence rather than matching differently per vehicle in silence.
- **Payload duration is unrecorded**: Neither mode's store records fetch duration for attachment payloads, so payload tables serve `duration_ms` 0 (none recorded); fast-mode attempt counts are likewise 0 because that mode keeps no attempt records.
- **Attachments are single-filing only**: `Edgar.attachments(filing)` serves one filing's collection; an object-level counterpart over a `FilingsResult` is deferred until a consumer appears. The attachment surface has no markdown accessor, no query DSL, and no HTTP serve.
- **No stitched statements**: The client serves the stitched financials series only; statement rendering stays per-filing until the question of which filing's arcs govern a stitched statement is ruled.
- **No split adjustment**: TTM values are served on the as-reported basis, named on every result; no split-detection or adjustment machinery exists, monetary flows are unaffected by splits, and building that machinery is a separate item if ever wanted.
- **Facts-side TTM serves nothing**: The TTM composed from company-facts points exists only as the comparison leg beside the parsed-side result, under the same four outcome classes; no facts-derived TTM is an answer anywhere.
- **Cross-filing scope bounded by the stitched series**: Stitched TTM serves exactly the metric classes the stitched series serves, inheriting its breaks and per-leg provenance; no stitching is built or widened at this layer.
- **No calc-ancestor yield over a series**: Net income over a stitched series reads its filter ladder directly; the within-filing calc-ancestor yield has no series analogue, so a concept reachable only through that yield is absent cross-filing.
- **No unit adjudication over a series**: Same-concept spans reported in multiple units keep the first series-ordered value rather than an adjudicated one.
- **Series LEI is unverified**: Neither relation layer carries an LEI, so an N-MFP document's `series_lei` rides its resolution unverified; adding LEI to the relation is a schema decision, not a client derivation.
- **Relation coverage is the refresh's, not the lookup's**: Until a refresh covers a registrant, its series and classes are absent from lookup answers; class counts are not cross-checked against documents, because coverage is partial by design.
- **No other funds family joins**: N-PORT, N-CEN, and N-PX carry no series or class ID to join on, so they gain no resolution here.
