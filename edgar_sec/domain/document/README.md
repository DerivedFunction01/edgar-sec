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

- `DocumentLocator.document_locator_key` is derived, never supplied: `from_parts()`
  always computes it, so a locator cannot disagree with its own key.
- Both digests are content-addressed and reduce the accession to its unhyphenated
  form first, so the hyphenated and unhyphenated spellings of one EDGAR accession are
  one document rather than two. The Python derivation and the catalog's SQL derivation
  must stay byte-identical, and a cross-layer contract test pins them; `models.py`
  documents the required spelling.
- A `DocumentLocator` is usable offline. `archive_url`, `form`, `source_cik`, and
  `document_type` are all optional; replaying from a fixture needs only the key.
- Acquisition reports are separate from storage decisions. `FetchResult` says what
  came back; only a pipeline decides a document is good enough to keep.
- `RawDocumentBlob` and `FilingOccurrence` round-trip through `to_row()` and
  `from_row()`; `FilingOccurrence.to_row()` renders `source_cik` through
  `Cik.to_10digit()`.

**Obligations on callers.**

- Build locators through `DocumentLocator.from_parts()`, not the positional constructor,
  unless restoring a row that already carries its key.
- Use `FetchResult.ok`, not `.status`, as the success predicate: `ok` requires
  `status == "ok"` *and* a non-`None` payload.

## Public surface

- `DocumentLocator` and its `from_parts()` constructor, plus the blob, occurrence,
  normalization, and failure records — `models.py`.
- `canonical_accession_part()`, `derive_document_locator_key()`,
  `derive_occurrence_id()`, and `DocumentKind` — `models.py`.
- `FetchResult`, `AcquisitionFailure`, `FetchStatus`, and `is_stub_document_path()` —
  `acquisition.py`.
- `BlockKind`, `DocumentBlock`, `BlockStream` — `blocks.py`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/document/`.

## Deliberate gaps

- **No fetching, persistence, MIME detection, or retry policy.** Those capabilities
  belong to the infrastructure and pipeline layers. In particular, a caller arriving
  with bytes gets no way to learn their format from this package: `DocumentKind` is a
  declared vocabulary, not a detector, so format classification is the fetching and
  storage layers' responsibility.
