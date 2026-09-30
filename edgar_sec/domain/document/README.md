# `edgar_sec/domain/document/` — Document identity, acquisition records, and block streams

Three modules that together answer two questions: *which document is this* and
*what came back when we asked for it*. They declare the record shapes; they
never read, write, or request anything.

## Purpose

`edgar_sec/domain/document/` owns the content-addressed identity of a filing
document, the provenance link from a corporate CIK to that document, the typed
records an acquisition attempt produces, and the flat block representation a
normalizer emits. It is not the fetcher (that is
`pipelines/document_storage/fetching.py`), not the payload store (that is
`infra/storage/document_parquet.py`), and not the normalization logic (that is
`engine/`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | `DocumentLocator` (a document plus how to acquire it), `FilingOccurrence` (CIK → stored blob), `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`, `DocumentKind`, and the two key derivations |
| `acquisition.py` | `FetchResult`, `AcquisitionFailure`, `FetchStatus`, and `is_stub_document_path()` |
| `blocks.py` | `BlockKind`, `DocumentBlock`, `BlockStream` — the flat 1D typed block stream |

## Contracts

**Guarantees this package makes.**

- `DocumentLocator.document_locator_key` is derived, never supplied.
  `DocumentLocator.from_parts()` (`models.py:53-79`) always computes it via
  `derive_document_locator_key(accession, document_path)`. The docstring is
  explicit about why: the payload store, the fetchers, and the Parquet snapshot
  all key on it, so a locator that disagreed with its own key would silently
  split one document across two identities.
- Identity is content-addressed and stable. `derive_document_locator_key()` is
  `sha256_text(f"{accession.strip()}:{document_path.strip()}")`
  (`models.py:21-23`), matching the SQL
  `sha256(accession || ':' || document_path)` in
  `infra/storage/duckdb_catalog.py:155`.
- A `DocumentLocator` is usable offline. `archive_url`, `form`, `source_cik`, and
  `document_type` are all optional; replaying from a fixture needs only the key.
- Acquisition reports are separated from storage decisions. `FetchResult` says
  what came back; only a pipeline decides a document is good enough to keep
  (`acquisition.py:8-10`).
- A complete submission bundle is never a stub. `is_stub_document_path()` tests
  the full-bundle pattern `\d{10}-\d{2}-\d{6}\.txt$` *before* the
  `0000.txt`/`0001.txt` sequence-suffix test, because every bundle name also
  ends in a stub sequence suffix and a suffix comparison would classify every
  bundle as a stub (`acquisition.py:23-44`).
- Records round-trip. `RawDocumentBlob`, `FilingOccurrence`, and
  `NormalizedDocument` each provide `to_row()`; `RawDocumentBlob` and
  `FilingOccurrence` also provide `from_row()`, and
  `FilingOccurrence.to_row()` renders `source_cik` through
  `Cik.to_10digit()` so a persisted row is always 10-digit padded.

**Obligations callers place on this package.**

- Construct locators through `DocumentLocator.from_parts()`, not the positional
  constructor, unless you are restoring a row that already carries its key.
- Treat `FetchResult.ok` as the success predicate, not `status`: `ok` is
  `True` only when `status == "ok"` *and* `payload is not None`
  (`acquisition.py:63-65`).
- `FetchResult.source_payload` carries the PEM-stripped SGML bundle only when
  the payload was selected *from* an envelope; it is `None` when the payload was
  already a plain document (`acquisition.py:50-54`).

## Public surface

- `DocumentKind` — `StrEnum` of `HTML`, `ASCII_TXT`, `XML`; `models.py:13-18`.
- `derive_document_locator_key(accession, document_path)` — `sha256_text` of
  `"<accession>:<document_path>"`, where the accession is reduced to its
  **unhyphenated** form first; `models.py:38`.
- `canonical_accession_part(accession)` — the hyphen-free accession used inside
  every content-addressed digest; `models.py:21`.
- `derive_occurrence_id(source_cik, accession, document_path)` — `sha256_text` of
  `"<source_cik>:<accession>:<document_path>"`, accession likewise unhyphenated;
  `models.py:57`. Read the deliberate gaps before using it.
- `DocumentLocator` — frozen dataclass with `accession`, `document_path`,
  `document_locator_key`, optional `archive_url`, `form`, `source_cik`,
  `document_type`; classmethod `from_parts()`; property `is_stub_path`;
  `models.py:31-86`.
- `RawDocumentBlob` — `doc_id`, `accession`, `document_path`, `byte_size`,
  `mime_type`, `raw_payload_sha256`; `to_row()` / `from_row()`; `models.py:89-112`.
  Consumed by `infra/storage/document_parquet.py:13`.
- `NormalizedDocument` — `normalized_artifact_id`, `source_doc_id`, `byte_size`,
  `normalized_payload`, `payload_sha256`, `mime_type`, `representation`,
  `processor_fingerprint`, `schema_version`, `processor_metadata`; `models.py:115-131`.
- `NormalizationFailure` — `source_doc_id`, `processor_fingerprint`,
  `schema_version`, `error_message`, `attempted_at`; `models.py:134-145`.
- `FilingOccurrence` — `occurrence_id`, `source_cik`, `accession`,
  `document_path`, `form`, `filing_date`, `report_date`, `doc_id`; `to_row()` /
  `from_row()`; `models.py:148-185`.
- `FetchStatus` — `Literal["ok", "missing", "failed"]`; `acquisition.py:21`.
- `FetchResult` — `locator`, `payload`, `status`, `error`, `source_payload`;
  properties `ok` and `byte_size`; `acquisition.py:47-69`.
- `AcquisitionFailure` — `document_locator_key`, `accession`, `document_path`,
  `error`, `status`, `metadata`; `acquisition.py:72-81`.
- `is_stub_document_path(document_path)` — `acquisition.py:32`.
- `BlockKind` — `StrEnum` of `PARAGRAPH`, `TABLE`, `PRESERVED`, `PAGE_BREAK`;
  `blocks.py:10-16`.
- `DocumentBlock` — `block_index`, `kind`, `text`, `raw_lines`, `char_start`,
  `char_end`; properties `line_count`, `is_table`; `blocks.py:19-36`.
- `BlockStream` — immutable tuple of blocks with `__len__`, `__iter__`,
  `__getitem__`, `filter_kind()`, properties `tables` and `paragraphs`, and
  `to_full_text(block_separator="\n\n")`; `blocks.py:39-68`.

## Tests

```text
tests/domain/document/test_models.py         3 test functions, 59 lines
tests/domain/document/test_acquisition.py    9 test functions, 90 lines
tests/domain/document/test_blocks.py         2 test functions, 50 lines
```

## Deliberate gaps
- **Both content-addressed digests normalize the accession to its unhyphenated
  form, and this was a real divergence before it was fixed.** An earlier
  revision of `derive_occurrence_id` hashed the locator key (a hash of a hash)
  while `infra/storage/duckdb_catalog.py:167-169` hashes three raw parts; the
  two therefore disagreed for every document. Separately, the catalog
  materialises `accession` as `replace(accession_number, '-', '')`
  (`duckdb_catalog.py:116`) and hashes *that* column, so a Python caller holding
  the hyphenated EDGAR spelling produced a different digest from the row already
  on disk — a locator join against a published snapshot, and a replay against a
  committed Phase 2.5 fixture, matched nothing and failed silently. Both
  functions now reduce the accession through `canonical_accession_part` first,
  `DocumentLocator.from_parts` accepts either spelling via
  `AccessionNumber.from_any`, and the cross-boundary test in
  `tests/foundation/test_hashing.py` pins the SQL/Python equality using the
  *same* normalization the catalog query performs. `roadmap/refactor_v2/phase_2.md:1006`
  presented the two `occurrence_id` forms as one key; they now are one.
- **`NormalizedDocument` and `NormalizationFailure` have no consumer.** Neither
  symbol is referenced anywhere in `edgar_sec/` or `tests/` outside this
  package. They are the declared record shapes for the Phase 2.5 storage
  contract (`roadmap/refactor_v2/phase_2_5/01_foundation_and_domain.md`), so
  their absence of callers is expected — not evidence that the pipeline already
  writes them.
- **`BlockStream` and its block types have no production consumer.** `BlockKind`,
  `DocumentBlock`, and `BlockStream` are referenced only by
  `tests/domain/document/test_blocks.py`. The roadmap calls the flat 1D block
  stream a Track 2 model explicitly decoupled from the Phase 03 TOC spine
  (`phase_2_5/01_foundation_and_domain.md:29`), so the type exists ahead of its
  normalizer.
- **`DocumentKind` and `DocumentLocator.is_stub_path` are exercised only by
  tests.** Neither has a caller in `edgar_sec/`. `is_stub_path` delegates to
  `acquisition.is_stub_document_path` through a function-local import at
  `models.py:84`, which exists because `acquisition.py:19` already imports
  `DocumentLocator` at module scope; hoisting it would close a cycle inside this
  package.
- **No MIME detection, no fetching, no persistence, no retry policy.** Detecting
  a type from a suffix, issuing the request, deciding whether to keep the bytes,
  and writing them are all outside this package by design
  (`acquisition.py:8-10`).
- **v1's `phases/025_webpage_storage/core/records.py` (466 lines) has no v2
  counterpart.** It carried `doc_id()`, `normalized_artifact_id()`, `detect_mime()`,
  MIME constants, and the six-table DDL. `roadmap/refactor_v2/parity_inventory.csv:486`
  records it `NOT_STARTED`. The two key formulas that mattered are already
  present here or in SQL; the MIME policy and the physical schema are Phase 2.5
  work named in that same row.
