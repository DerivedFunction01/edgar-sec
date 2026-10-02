# `edgar_sec/domain/document/` — Document identity, acquisition records, and block streams

## Purpose

Record shapes for two questions: *which document is this* and *what came back when we asked for it*.
Nothing here reads, writes, or requests anything. Fetching is
`pipelines/document_storage/fetching.py`, payload storage is
`infra/storage/document_parquet.py`, normalization is `engine/`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | `DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`, `DocumentKind`, and the key-derivation functions |
| `acquisition.py` | `FetchResult`, `AcquisitionFailure`, `FetchStatus`, `is_stub_document_path()` |
| `blocks.py` | `BlockKind`, `DocumentBlock`, `BlockStream` — the flat 1D typed block stream |

## Contracts

- `DocumentLocator.document_locator_key` is derived, never supplied.
  `from_parts()` always computes it, so a locator cannot disagree with its own key.
- Both digests are content-addressed and reduce the accession to its **unhyphenated**
  form first, via `canonical_accession_part()`. `derive_document_locator_key()` hashes
  `"<accession>:<document_path>"` and `derive_occurrence_id()` hashes
  `"<source_cik>:<accession>:<document_path>"` — the same shapes
  `infra/storage/duckdb_catalog.py` computes in SQL over its `replace(accession_number, '-', '')`
  column. `tests/foundation/test_hashing.py` pins the Python/DuckDB equality.
- A `DocumentLocator` is usable offline. `archive_url`, `form`, `source_cik`, and
  `document_type` are all optional; replaying from a fixture needs only the key.
- Acquisition reports are separate from storage decisions. `FetchResult` says what
  came back; only a pipeline decides a document is good enough to keep.
- A complete submission bundle is never a stub. `is_stub_document_path()` tests the
  full-bundle pattern `\d{10}-\d{2}-\d{6}\.txt$` *before* the `0000.txt`/`0001.txt`
  sequence-suffix test, because every bundle name also ends in a stub sequence suffix.
- All four record types provide `to_row()`. `RawDocumentBlob` and `FilingOccurrence`
  also provide `from_row()`, and `FilingOccurrence.to_row()` renders `source_cik`
  through `Cik.to_10digit()`.

**Obligations on callers.**

- Build locators through `DocumentLocator.from_parts()`, not the positional constructor,
  unless restoring a row that already carries its key.
- Use `FetchResult.ok`, not `.status`, as the success predicate: `ok` requires
  `status == "ok"` *and* a non-`None` payload.
- Treat `FetchResult.source_payload` as populated only when the payload was selected
  *from* an envelope; it is `None` for an already-plain document.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `DocumentKind` (`HTML`, `ASCII_TXT`, `XML`) | `models.py` |
| `canonical_accession_part`, `derive_document_locator_key`, `derive_occurrence_id` | `models.py` |
| `DocumentLocator` (`from_parts()`, `is_stub_path`), `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`, `FilingOccurrence` | `models.py` |
| `FetchStatus`, `FetchResult`, `AcquisitionFailure`, `is_stub_document_path` | `acquisition.py` |
| `BlockKind`, `DocumentBlock`, `BlockStream` | `blocks.py` |

No command surface.

## Tests

```text
tests/domain/document/test_models.py
tests/domain/document/test_acquisition.py
tests/domain/document/test_blocks.py
```

## Deliberate gaps

- **Four declared record types have no production consumer.**
  `NormalizedDocument` and `NormalizationFailure` are referenced nowhere outside this
  package; they are the declared shapes for the Phase 2.5 storage contract
  (`roadmap/refactor_v2/phase_2_5.md`), not evidence that the pipeline already writes them.
- **`BlockStream` has no production consumer either.** `BlockKind`, `DocumentBlock`, and
  `BlockStream` are referenced only by their own test. `phase_2_5.md` calls the flat 1D
  block stream a model explicitly decoupled from the TOC spine, so the type exists ahead
  of its normalizer. (`engine/tables/hybrid/masker.py` declares its own unrelated
  `PreBlockKind`.)
- **`DocumentKind` and `DocumentLocator.is_stub_path` are exercised only by tests.**
  `is_stub_path` reaches `acquisition.is_stub_document_path` through a function-local
  import, because `acquisition.py` already imports `DocumentLocator` at module scope;
  hoisting it would close a cycle inside this package.
- **No MIME detection, no fetching, no persistence, no retry policy.** Detecting a type
  from a suffix, issuing the request, deciding whether to keep the bytes, and writing
  them are all outside this package by design.
- **`DocumentKind` is declared but unassigned.** Nothing populates a blob's MIME type
  from it; `RawDocumentBlob.mime_type` is a plain `str` field. v1's MIME policy lived in
  `.v1/phases/025_webpage_storage/core/schemas.py` (`detect_mime`, `MIME_*` constants) and
  has no v2 home here.
- **The v1 record module's key formulas survived; its schema did not.** v1's
  `phases/025_webpage_storage/core/records.py` (187 lines) carried the same seven record
  dataclasses plus v1-specific helpers; the two key formulas that mattered are already
  present here and in SQL. The physical table schema is Phase 2.5 work, and the v1 → v2
  relocation matrix that recorded its status (`roadmap/refactor_v2/parity_inventory.csv`)
  is no longer in the tree, so there is no current per-file status to point at.