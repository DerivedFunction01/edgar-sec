# Phase 2.5: Webpage Storage (Raw Document Acquisition)

Acquires and stores raw SEC filing documents (HTML, SGML, iXBRL XML) as
content-addressed, zstd-compressed SQLite BLOBs, linked to corporate
occurrences from a finalized Phase 02 target plan. This is the **storage-only**
boundary: no parsing, envelope unpacking, or tag stripping happens here (those
are a later parallel track built on `document_blobs`).

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

## Command surface

```bash
# Validate inputs and report planned acquisition counts (no network)
.venv/bin/python -m phases.025_webpage_storage.cli preview --plan-dir <phase02-plan>

# Acquire + store one partition in offline fixture mode
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode fixture --fixtures <fixture_id> \
  --partition-id 1 --partition-count 1

# Acquire in production mode (live SEC archive, 4 RPS pacing, failure ledger)
.venv/bin/python -m phases.025_webpage_storage.cli run \
  --plan-dir <phase02-plan> --mode production

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
ArchiveFetcher  ── fixture (offline SQLite CAS) | production (SecHttpClient.get_bytes)
   │
   ▼
ChunkWorker  → isolated chunk-XXXXX.db (zstd-compressed blobs + occurrences)
   │
   ▼
PartitionMerger → single atomic merge into partition-000XX.sqlite
   (document_blobs, filing_occurrences, _committed_chunks, indexes)
```

All SQLite access goes through `defs.sql` AST nodes + `SqlExecutor`; the phase
never imports `sqlite3`/`duckdb` or issues raw SQL. Merge uses compiled
`Attach`/`Detach` with `INSERT OR IGNORE` for idempotent, resumable assembly.

## Settings

Declared in `settings.py` under `webpage_storage.*`
(`WEBPAGE_STORAGE_ZSTD_LEVEL`, `WEBPAGE_STORAGE_MODE`); resolved from the shared
settings registry.

## Testing

```bash
.venv/bin/pytest phases/025_webpage_storage/tests
```
