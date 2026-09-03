# Phase 2.5: Webpage Storage (Raw Document Acquisition)

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
  `doc_id = sha256(accession + "/" + document_path)`.
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

# Acquire + store one partition in offline fixture mode with 4 workers
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode fixture --fixtures <fixture_id> \
  --partition-id 1 --partition-count 1 --workers 4

# Same run but store raw payloads without normalization
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode fixture --fixtures <fixture_id> \
  --partition-id 1 --partition-count 1 --workers 4 --no-normalize

# Acquire in production mode (live SEC archive, 4 RPS pacing, failure ledger)
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode production --workers 8

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

# Merge transient worker chunk DBs into the published partition database
.venv/bin/python -m phases.025_webpage_storage.cli merge-partition \
  --partition-id 1 --run-id <run-id> --output-dir <dir>

# Report partition database integrity
.venv/bin/python -m phases.025_webpage_storage.cli status --database <partition.sqlite>
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
PartitionMerger → single atomic merge into partition-000XX.sqlite
    (all chunk tables copied verbatim, then indexes)
```

All SQLite access goes through `defs.sql` AST nodes + `SqlExecutor`; the phase
never imports `sqlite3`/`duckdb` or issues raw SQL. Merge uses compiled
`Attach`/`Detach` with `INSERT OR IGNORE` for idempotent, resumable assembly.

## Concurrency

Acquisition runs are parallel at two independent levels, and the two levels
never share a writer:

- **Chunk workers** (`--workers`, defaults to `derive_resources().threads`,
  rejected if < 1) run as a `ProcessPoolExecutor` in production mode. Each
  process owns its own isolated `chunk-XXXXX.db`; the coordinator is the only
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
- `--no-normalize` runs raw-only acquisition: no normalized rows are written,
  and `_committed_chunks` records the `raw-only` processor fingerprint.
- Committed chunks record their processor fingerprint and normalized schema
  version. A committed chunk never satisfies a run with a different
  fingerprint; the stale audit row is dropped and the chunk is reprocessed,
  reusing the stored raw blobs without re-fetching.
- A processor failure is recorded in `normalization_failures`; the raw blob,
  occurrences, and the chunk's success status are unaffected.

The boundary is normalization only — parsing and section extraction are later
phases.

- `DeepNormalizer` — coordinates form-specific and generic normalization passes
- `HybridCoverPreprocessor` — in-place DOM cover preprocessor driven by a typed form-family cover profile. It preserves organic filing prose while decomposing layout tables and healing split phrases (checkbox normalization, phrase-sequence healing, date fragment healing). Behavior is profile-gated: annual-only anchors never apply to quarterly, current-report, or no-cover profiles.
- Form-family normalizers — `Form10KNormalizer`, `Form10QNormalizer`, `Form8KNormalizer` route through `HybridCoverPreprocessor` with their profile; `GenericFormNormalizer` is the fallback
- `FormRouter` — routes documents to form-specific evaluators and normalizers
- ASCII span/action pass — after body-start detection, non-HTML text runs through
  `defs.text.reflow.reflow_ascii`: hard-wrapped prose is unwrapped, untagged
  fixed-width tables are wrapped in `<TABLE>`/`</TABLE>` with rows preserved
  exactly, and every ambiguous block stays preserved and untagged. Existing
  tagged tables are masked and restored byte-for-byte. Everything before the
  validated body anchor is preserved; with no body anchor the pass is skipped.
  Decision counts are published in processor metadata (`reflow_unwrap_blocks`,
  `reflow_preserve_blocks`, `reflow_tag_blocks`).

The processing pipeline: `GenericPreprocessor` → `FormRouter` → form-specific normalizer → `DeepNormalizer`. Shared table processing lives under `defs/tables/`; cover-specific table templates live under `defs/tables/templates/cover.py`.

### Representation-aware cover routing

Cover applicability is decided by both the selected form profile and bounded document evidence, not by form name alone:

- HTML with a qualifying cover, including inline-XBRL HTML: typed cover pass
- HTML without qualifying cover evidence: no-cover scope plus generic normalization only
- Pure XML/structured filings: no-cover scope and no HTML cover pass
- Narrative/no-standardized-cover filings: no-cover scope and generic normalization only

Profiles are immutable and selected by form family from `defs.sec_forms.cover.profiles`. The preprocessor consumes a profile; it does not branch on form names. Annual-only anchors (`Documents incorporated by reference`, public float, annual share-count wording, auditor disclosures) are profile-gated and must never apply to quarterly, current-report, or no-cover profiles.

### Shared alias registry

Form-family aliases live in `defs.sec_forms.families` (`FORM_FAMILY_ALIASES`, `form_family`, `resolve_alias`). Phase 2.5 consumes them; no phase owns aliases.

## Settings

Declared in `settings.py` under `webpage_storage.*`
(`WEBPAGE_STORAGE_ZSTD_LEVEL`, `WEBPAGE_STORAGE_MODE`, `WEBPAGE_STORAGE_WORKERS`);
resolved from the shared settings registry. `WEBPAGE_STORAGE_WORKERS` is the
process-pool worker count; the fetch-thread count inside a chunk is the
`--workers` CLI flag, which defaults to `derive_resources().threads`. The
managed broker socket path comes from `BrokerPaths.broker_paths()` and is not
a persisted setting.

## Testing

```bash
.venv/bin/pytest phases/025_webpage_storage/tests
.venv/bin/pytest phases/025_webpage_storage/tests/test_normalization_goldens.py
```

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
