# Phase 2.5: Webpage Storage (Raw Document Acquisition)

Acquires and stores raw SEC filing documents (HTML, SGML, iXBRL XML) as
content-addressed, zstd-compressed SQLite BLOBs, linked to corporate
occurrences from a finalized Phase 02 target plan. Normalization runs during
acquisition (see Normalization below); parsing, envelope unpacking, and section
extraction remain a later processing track built on `document_blobs`. The phase
tests also exercise the downstream `DeepNormalizer` against small tracked
archetype segments; the shared table corpus and converter goldens live under
`defs/tests/fixtures/tables/`.

## Scope boundary

- Consumes a Phase 02 plan bundle (`plan.json`, `targets/form=*/data.parquet`,
  `locator_groups.parquet`, `selection_report.json`); never reads Phase 01
  metadata directly.
- Fetches each unique document locator exactly once; deduplicates by
  `doc_id = sha256(accession + "/" + document_path)`.
- Provenance rows (`filing_occurrences`) carry `source_cik`, `accession`,
  `document_path`, `form`, `filing_date`, `report_date`, and `doc_id`. Company
  name/family are intentionally absent here and are re-derived downstream by
  joining `source_cik` against Phase 01 metadata.
- Missing (404) and failed document acquisitions are permanently recorded in
  `acquisition_failures` for auditability and queryability.

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
    (document_blobs, filing_occurrences, acquisition_failures, _committed_chunks)

Fixture fill uses fetch threads with one coordinator SQLite writer. Production
process workers route through one broker-owned SEC client and aggregate limiter.
   │
   ▼
PartitionMerger → single atomic merge into partition-000XX.sqlite
    (document_blobs, filing_occurrences, acquisition_failures, _committed_chunks, indexes)
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

Normalization is **on by default** during acquisition. Each fetched document
flows through `GenericPreprocessor` → `FormRouter` → form-specific normalizer →
`DeepNormalizer`, and the normalized text is what gets stored as the payload.
Pass `--no-normalize` to store raw payloads instead. The boundary is
normalization only — parsing and section extraction are later phases.

- `DeepNormalizer` — coordinates form-specific and generic normalization passes
- `HybridCoverPreprocessor` — in-place DOM cover preprocessor driven by a typed form-family cover profile. It preserves organic filing prose while decomposing layout tables and healing split phrases (checkbox normalization, phrase-sequence healing, date fragment healing). Behavior is profile-gated: annual-only anchors never apply to quarterly, current-report, or no-cover profiles.
- Form-family normalizers — `Form10KNormalizer`, `Form10QNormalizer`, `Form8KNormalizer` route through `HybridCoverPreprocessor` with their profile; `GenericFormNormalizer` is the fallback
- `FormRouter` — routes documents to form-specific evaluators and normalizers

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
