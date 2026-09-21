# Phase 2.5: Webpage Storage and Temporal Normalized Snapshots

Acquires and stores raw SEC filing documents (HTML, SGML, iXBRL XML) as
content-addressed, zstd-compressed SQLite BLOBs, linked to corporate
occurrences from a finalized Phase 02 target plan. Normalization runs during
acquisition into a separate, versioned normalized artifact (see Normalization
below); parsing, envelope unpacking, and section extraction remain a later
processing track. The phase tests also exercise the downstream `DeepNormalizer`
against small tracked archetype segments; the shared table corpus and converter
goldens live under `defs/tests/fixtures/tables/`.

## Scope boundary

- Consumes a Phase 02 plan bundle (`plan.json`, `targets/form=*/data.parquet`,
  `locator_groups.parquet`, `selection_report.json`); never reads Phase 01
  metadata directly.
- Fetches each unique document locator exactly once; deduplicates by
  `doc_id = sha256(canonical_accession + ":" + document_path)`.
- `document_blobs` stores only the exact fetched source bytes plus their
  SHA-256 digest (`raw_payload_sha256`); processor output never replaces them.
- Provenance rows (`filing_occurrences`) carry `source_cik`, `accession`,
  `document_path`, `form`, `filing_date`, `report_date`, and `doc_id`. Company
  name/family are intentionally absent here and are re-derived downstream by
  joining `source_cik` against Phase 01 metadata.
- Missing (404) and failed document acquisitions are permanently recorded in
  `acquisition_failures`; normalization failures are recorded separately in
  `normalization_failures` without discarding the raw source.

## Command surface

```bash
# Validate inputs and report planned acquisition counts (no network)
.venv/bin/python -m phases.025_webpage_storage.cli preview --plan-dir <phase02-plan>

# Acquire + store production target plan directly (resolves deterministic 10-K production plan)
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --scope deterministic --mode production --workers 8

# Or target a specific plan directory or plan ID:
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-id c2f54ad43d433b03bb597fd2 --mode production --workers 8

# Acquire + store one partition in offline fixture mode with 4 workers
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode fixture --fixtures <fixture_id> \
  --partition-id 1 --partition-count 1 --workers 4

# Monitor live acquisition progress in real-time (terminal UI with live throughput and disk usage):
python scripts/monitor_progress.py --watch

# Fill/update one shared offline fixture from live SEC using machine-local
# fetch threads; omit --workers to use runtime resource defaults
.venv/bin/python -m phases.025_webpage_storage.cli fill-fixture \
  --plan-dir <phase02-plan> --fixture-id <fixture-id> --workers 8

# Append a larger child plan to the same completed fixture cache
.venv/bin/python -m phases.025_webpage_storage.cli fill-fixture \
  --plan-dir <expanded-phase02-plan> --fixture-id <fixture-id> --workers 8

# Root-launcher convenience form of the same append operation
.venv/bin/python run.py append \
  --plan-dir <expanded-phase02-plan> --fixture-id <fixture-id>

# Explicitly retry prior acquisition failures for this plan
.venv/bin/python -m phases.025_webpage_storage.cli fill-fixture \
  --plan-dir <phase02-plan> --fixture-id <fixture-id> --retry-failures

# Manage the same-host production SEC broker used by process workers
.venv/bin/python -m defs.sec_http.broker start
.venv/bin/python -m defs.sec_http.broker status
.venv/bin/python -m defs.sec_http.broker stop

# Merge transient worker chunk DBs into a run-namespaced finalized partition
.venv/bin/python -m phases.025_webpage_storage.cli merge-partition \
  --partition-id 1 --run-id <run-id>

# Report run-level chunk/finalized-partition coverage
.venv/bin/python -m phases.025_webpage_storage.cli status --run-id <run-id>

# Publish all finalized partitions for one run as an immutable normalized snapshot
.venv/bin/python -m phases.025_webpage_storage.cli merge-to-snapshot \
  --run-id <run-id>

# Consolidate selected snapshots with bounded DuckDB memory and quarter workers
.venv/bin/python -m phases.025_webpage_storage.cli vacuum --all \
  --workers 2 --threads 4 --memory-limit 8GB \
  --temp-directory /var/tmp/edgar-sec-duckdb

# Disable terminal progress for automation while preserving final JSON output
.venv/bin/python -m phases.025_webpage_storage.cli merge-to-snapshot \
  --run-id <run-id> --no-progress
```

## Architecture

```
Phase 02 target plan
   │ load_targets()  → unique DocumentLocators + FilingOccurrences
   ▼
ArchiveFetcher  ── fixture (offline SQLite CAS) | production (managed SEC broker)
   │
   ▼
ChunkWorkers (ThreadPoolExecutor, concurrent) → isolated chunk-XXXXX.db
    (document_blobs, filing_occurrences, normalized_documents,
     normalization_failures, acquisition_failures, _committed_chunks)

Fixture fill uses fetch threads with one coordinator SQLite writer. Production
process workers route through one broker-owned SEC client and aggregate limiter.
   │
     ▼
     PartitionMerger → manifests/webpage_storage/partition_artifacts/<run-id>/
     (partition-000XX.sqlite + handoff manifest; chunks remain local)
    │
    ▼
Snapshot publisher → normalized_documents/snapshots/<snapshot-id>/
    index.parquet + payload-000NN.parquet by filing year/quarter
```

All SQLite access goes through `defs.sql` AST nodes + `SqlExecutor`; the phase
never imports `sqlite3`/`duckdb` or issues raw SQL. Merge uses compiled
`Attach`/`Detach` with `INSERT OR IGNORE` for idempotent, resumable assembly.

## Concurrency

Acquisition runs are parallel at two independent levels, and the two levels
never share a writer:

- **Chunk workers** (`--workers`, defaults to `derive_resources().workers`
  (process workers), rejected if < 1) run as a `ProcessPoolExecutor` in
  production mode. Each process owns its own isolated `chunk-XXXXX.db` under
  the run's partition-scoped worker directory; the coordinator is the only
  SQLite writer and merges the published chunks afterward.
- **Fetch threads** inside a single chunk (`fetch_workers`) use a bounded
  in-flight window (`wait(..., FIRST_COMPLETED)`) so at most `fetch_workers`
  live `fetch()` calls overlap. Worker threads never touch SQLite directly —
  they return completed `FetchResult` objects and the coordinator persists
  them one at a time.

`fill-fixture` and `run --mode fixture` share one `SecHttpClient` across all
fetch threads, so pacing, cache, failure ledger, and metrics aggregate through
a single rate limiter instead of one independent limiter per thread. Production
mode replaces that shared client with the managed broker.

`fill-fixture` treats the fixture ID as a reusable raw-document cache. It may
be rerun with a larger child plan after completion: existing blobs are skipped
by `doc_id`, new locators are appended, and the operation remains idempotent.
Known acquisition failures are skipped by default and retried only with
`--retry-failures`. Coverage and plan lineage are atomically recorded in
`fixture.manifest.json` beside the SQLite database. The fixture remains a raw
CAS and does not store filing occurrence rows.

## Managed SEC broker

Production workers never construct their own SEC client. `run_partition`
auto-starts a broker via `ensure_broker()` when `mode=production` and no
client/socket is supplied; workers then submit archive URLs over a
Unix-domain socket (`BrokerPaths.broker_paths().socket_path`) using
length-prefixed JSON frames (protocol version 1, `healthcheck://broker`
sentinel). The broker owns one `SecHttpClient` — single rate limiter, cache,
failure ledger, and metrics — so all live requests share one aggregate pace.

Warm-cache reruns bypass the broker for already-cached documents:

- The broker records the cache directory it uses in its registry; workers
  resolve it with `broker_cache_dir()` and open a read-only
  `SqlCacheReader` (`mode=ro`, fail-open on missing or drifted databases).
- `BrokerArchiveFetcher` probes the local reader for the primary archive URL
  and the full-submission fallback URL before each RPC. A hit is
  byte-identical to the broker's response (cache entries never expire and
  successes clear their ledger entry), so only misses traverse the socket.
- The reader is strictly read-only: cache writes, failure-ledger updates,
  pacing, and retries stay broker-owned. Cache hits also never consume the
  broker's connection slots (the broker serves its own warm hits before
  acquiring a slot), so cached-document throughput does not queue behind
  paced network requests.

Manage the broker directly with `python -m defs.sec_http.broker
{start,stop,status} [--socket PATH]`. `start` is idempotent: an existing
healthy broker is reused, a stale socket is replaced.

## Normalization

Raw acquisition and normalization are separate artifacts:

- `document_blobs` always holds the exact fetched bytes plus `raw_payload_sha256`
  (schema version 2).
- When a processor is configured (the CLI default), its output is stored in
  `normalized_documents` keyed by
  `normalized_artifact_id = sha256(raw_digest:processor_fingerprint:schema_version)`.
  Each row carries the normalized payload, payload digest, byte size, output
  MIME/representation, processor fingerprint, schema version, and the
  processor's stable metadata serialized deterministically (sorted-key JSON).
  Topology evidence is part of that metadata: cover boundary lines, TOC span,
  body-start anchor/confidence/rejection reasons, and the closing region
  (`closing_start_line`, `closing_kind`, `closing_confidence`) detected only
  after a validated body anchor.
- Page artifacts are part of that metadata under the `page_artifacts` key:
  the declared `PageArtifactPolicy` (`strip` by default, `annotate`, or
  `preserve`), the source-identity fingerprint, deduplicated furniture
  templates, and per-artifact coordinates. Under `annotate`, validated page
  furniture is replaced by compact `[[SEC:PAGE_BREAK id=N]]`-style tokens in
  the normalized payload; the id resolves only against metadata whose
  `source_identity` matches. Absent key means legacy `strip` behavior.
- Every supported form runs through a normalizer. Forms without a specialized
  processor use the generic/minimal normalization path.
- Committed chunks record their processor fingerprint and normalized schema
  version. A committed chunk never satisfies a run with a different
  fingerprint; the stale audit row is dropped and the chunk is reprocessed,
  reusing the stored raw blobs without re-fetching.
- A processor failure is recorded in `normalization_failures`; the raw blob,
  occurrences, and the chunk's success status are unaffected.

The boundary is normalization only — parsing and section extraction are later
phases.

## Snapshot contract

Canonical normalized data lives below
`manifests/webpage_storage/normalized_documents/snapshots/`. Each snapshot
manifest resolves lightweight occurrence indexes and payload parts. Index rows
contain the existing occurrence identity plus a snapshot-local artifact path;
payload rows contain only `doc_id` and native UTF-8 `clean_text`.

Incremental merges may inherit immutable payload files, so a newly discovered
CIK can add an occurrence without rewriting the shared document payload.
`SnapshotReader` resolves the effective index and exact payload paths. Queries
that need only metadata never open payload files.

Snapshot publication is a two-pass planner. Pass one selects all occurrence and
normalized metadata except the compressed blob in large batches, resolves
conflicts from stored `payload_sha256` values, and deterministically packs new
documents into payload parts of at most `--target-mb` (a single oversized
document becomes its own part). Pass two fetches only each planned part's
blobs, verifies the decompressed bytes against the planned hash, and writes the
payload part plus one index part per quarter. Part layout therefore depends
only on the source data and `--target-mb` — never on `--batch-size`, which only
bounds metadata read batches and payload fetch chunks. Sparse source batches no
longer produce sparse parts, and `--batch-size 1` still publishes one
well-sized part per quarter. Peak memory is one planned part of decompressed
text plus metadata for the whole publication.

Incremental merges plan only genuinely new documents; occurrences that resolve
to inherited base payloads reuse the base `payload_file` without new parts.
Parquet snapshot joins and vacuum deduplication run through DuckDB with
spill-to-disk settings (`--threads`, `--memory-limit`, and
`--temp-directory`). `vacuum` plans parts from effective-relation metadata and
materializes each part with a doc-range query, in a bounded number of quarter
workers, and can purge a validated dependency closure. Merge and vacuum report
partition/part/quarter progress on stderr; `--no-progress` is available for
automation.

Finalized partition databases are portable handoff artifacts. Machines may
process partitions independently and copy only finalized databases plus their
handoff manifests to a coordinator. Full snapshot publication requires complete
partition coverage; downstream phases should target the published snapshot,
not the Phase 2.5 worker chunks.

- `DeepNormalizer` — coordinates form-specific and generic normalization passes
- **SGML Multi-Document Unpacking** — `defs.sec_documents.sgml` unpacks concatenated submission envelopes (`<DOCUMENT>...</DOCUMENT>`), extracts target primary documents and exhibits (`EX-10`, `EX-21`, `EX-99`), parses filing headers (`<SEC-HEADER>`), and assigns distinct document identifiers.
- Shared cover boundary and healing — `find_cover_boundary_for_profile()` and `heal_cover_text()` are representation-neutral and operate on the normalized text frame; form normalizers expose heading normalization only
- Form-family normalizers — `Form10KNormalizer`, `Form10QNormalizer`, `Form8KNormalizer` route through the shared text-frame coordinator; `GenericFormNormalizer` is the fallback
- `FormRouter` — routes documents to form-specific evaluators and normalizers
- **ASCII Reflow & Table Recognition** — after body-start detection, non-HTML text runs through `defs.text.reflow.reflow_ascii`, with financial statement section bridging and family-owned tail recognition supplied from `defs.taxonomy.components.financials.reflow`:
  - **Prose Unwrapping**: Hard-wrapped text and multi-line bullet/list items (e.g. `(a)`, `(1)`, `•`, `-`) are cleanly reflowed into single logical lines while preserving paragraph boundaries (`is_list_or_bullet_marker`).
  - **Fixed-Width Table Recognition**: Untagged multi-column ASCII tables (with aligned numeric columns and headers) are automatically detected and wrapped in canonical `<TABLE>`/`</TABLE>` tags with row geometry preserved exactly.
  - **Table Protection**: Existing tagged tables are masked and restored byte-for-byte; ambiguous blocks stay preserved and untagged.
  - Everything before the validated body anchor is preserved; with no body anchor the pass is skipped. Decision counts are published in processor metadata (`reflow_unwrap_blocks`, `reflow_preserve_blocks`, `reflow_tag_blocks`).

The processing pipeline is `GenericPreprocessor` → representation-specific page
policy and text-frame rendering → shared cover boundary/healing → form-specific
header normalization → `DeepNormalizer` downstream structure analysis. HTML
documents use `defs.text.html.normalize_html_document()`, which renders tables
to canonical `<TABLE>...</TABLE>` blocks and decomposes HTML as strings. Shared
table processing lives under `defs/tables/`; cover-specific table templates
live under `defs/tables/templates/cover.py`.

### Removed components

- `HybridCoverPreprocessor` and `profile_pipeline.py` have been removed. Cover preprocessing is now handled by the shared text-frame coordinator in `defs.sec_forms.cover`.
- Preprocessing no longer carries page-marker analysis. `GenericPreprocessor`
  performs source cleanup and representation classification only. ASCII analysis
  is created lazily by `apply_text_policy()`; HTML analysis occurs after the
  string-first renderer has produced a valid text coordinate frame.

### Representation-aware cover routing

Cover applicability is decided by both the selected form profile and bounded document evidence, not by form name alone:

- HTML with a qualifying cover, including inline-XBRL HTML: typed cover pass
- HTML without qualifying cover evidence: no-cover scope plus generic normalization only
- Pure XML/structured filings: no-cover scope and no HTML cover pass
- Narrative/no-standardized-cover filings: no-cover scope and generic normalization only

Profiles are immutable and selected by form family from
`defs.sec_forms.cover.profiles` at the normalization boundary. The generic
preprocessor does not consume profiles or branch on form names. Annual-only
anchors (`Documents incorporated by reference`, public float, annual share-count
wording, auditor disclosures) are profile-gated and must never apply to
quarterly, current-report, or no-cover profiles.

### Shared alias registry

Form-family aliases live in `defs.sec_forms.families` (`FORM_FAMILY_ALIASES`, `form_family`, `resolve_alias`). Phase 2.5 consumes them; no phase owns aliases.

## Settings

Phase 2.5 does not participate in the shared settings registry.
`--workers`, `--mode`, and `--zstd-level` are CLI-only options resolved
directly by the phase CLI and pipeline. The process-pool worker count for
acquisition runs is `--workers` and defaults to `derive_resources().workers`;
thread-based paths (fixture fill, vacuum) default to
`derive_resources().threads`. The managed
broker socket path comes from `BrokerPaths.broker_paths()` and is not
a persisted setting.

## Testing

```bash
.venv/bin/pytest phases/025_webpage_storage/tests
```

Normalization goldens under `tests/fixtures/normalization/` may need
regeneration after processor changes. The focused
`tests/test_normalization_goldens.py` suite currently validates the three
archetype segments; document-corpus validation additionally runs through
`test_document_goldens.py` against the promoted document corpus. The expected
goldens still need regeneration once the final tagged-table formatting contract
is finalized.

Generated test evidence uses the shared `.artifacts/test-runs/` root through
`defs.runtime.paths`; acceptance fixture databases remain under
`.artifacts/acceptance/webpage_storage/fixtures/`.

### Document corpus review

The document golden workflow starts from a fixture ID. The phase resolves the
SQLite database and required `fixture.manifest.json` through the shared fixture
path contract; callers do not pass an arbitrary database path. Promotion writes
source bytes and review fields to the tracked corpus at
`tests/fixtures/documents/document_corpus_v1.parquet` and records bounded
lineage in `tests/fixtures/documents/manifest.json`:

```bash
.venv/bin/python -m phases.025_webpage_storage.tools.promote_document_corpus \
  --fixture-id <fixture-id>

.venv/bin/python -m phases.025_webpage_storage.tools.build_document_review_artifacts \
  --fixture-id <fixture-id> --limit 100 \
  --output .artifacts/test-runs/webpage_storage/document-reviews/<run-id>

.venv/bin/python -m phases.025_webpage_storage.tools.chunk_document_reviews \
  .artifacts/test-runs/webpage_storage/document-reviews/<run-id>/review_manifest.jsonl \
  --output .artifacts/test-runs/webpage_storage/document-reviews/<run-id>/batches \
  --limit 100 --size 20
```

Review artifacts contain source, preprocessed text, current normalized output,
sanitized HTML where applicable, and bounded page-marker/debug analysis. Edit
the JSONL batch manifest to classify failures, regenerate into a new run after
code changes, and use `dump_document_review_set.py` for a focused temporary
review file. Accepted expectations are promoted explicitly; deferred behavior
can be recorded with `--status accepted_current_behavior --deferred
paragraph_healing`. Pytest compares accepted rows exactly and writes
divergence reports under `.artifacts/test-runs/`; pending rows remain visible
but do not fail normal development tests.
