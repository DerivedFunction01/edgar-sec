# `edgar_sec/domain/document/` — Document identity, acquisition records, and block streams

## Purpose

Record shapes for two questions: *which document is this* and *what came back when we asked for it*.
Nothing here reads, writes, or requests anything. Fetching is
`pipelines/document_storage/fetching.py`, payload storage is
`pipelines/document_storage/checkpoint.py`, normalization is `engine/`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | `DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`, `DocumentKind`, and the key-derivation functions |
| `acquisition.py` | `FetchResult`, `AcquiredDocument`, `AcquisitionSource`, `SgmlEnvelopeResolution`, `SgmlSubDocumentHeader`, `AcquisitionFailure`, `FetchStatus`, `is_stub_document_path()` |
| `blocks.py` | `BlockKind`, `DocumentBlock`, `BlockStream` — the flat 1D typed block stream |
| `route.py` | `DocumentRoute`, `document_route()`, `content_route()`, `is_markup_document_path()`, `mime_type_for_suffix()`, `archive_root_candidate()`, and the representation names — the acquisition and normalization routes one document path selects |

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
- **A requested link, an acquired source, and a content route are three separate
  things.** `FetchResult.acquired` keeps all three apart: the locator that was asked
  for, the `AcquisitionSource` that actually answered, and the `DocumentRoute` of the
  bytes. They disagree whenever a rendered link is served from the archive root, or an
  `<accession>.txt` bundle delivers a child named `.xml`. A caller that collapses them
  either misreports where its bytes came from or reads an XML primary as a text bundle.
- **The requested locator is the only identity.** Neither the acquired source nor a
  selected sub-document's filename may change `document_path` or
  `document_locator_key`; the catalog derives both in SQL from the filed path.
- **`AcquiredDocument` carries no source envelope.** An SGML submission spans far more
  than the selected sub-document, so the headers are kept and the bytes are not. A
  sibling is a `SgmlSubDocumentHeader` — sequence, `<TYPE>`, filename, description — and
  a header asserts nothing about role: it is not evidence that the selected document is
  a filing's primary, or that a sibling is an exhibit.
- **A slash outranks the suffix for a path, and not for a filename.**
  `document_route()` classifies a path containing `/` as `RENDERED` before consulting
  the extension, because EDGAR publishes an XSL rendering of an XML submission under an
  `xsl<Form>X01/` directory and names it `.xml` while serving HTML. `content_route()`
  ignores directories, because an SGML `<FILENAME>` is a basename whose slash is never an
  XSL directory. Using `document_route()` on a sub-document filename reports an XML
  primary as a rendering, and using `content_route()` on a requested path reports a
  rendering as XML.
- `archive_root_candidate()` returns a candidate, not a guarantee. EDGAR may publish
  the original under a different name at the archive root, so a caller must retain the
  rendered path as a fallback.
- **One suffix vocabulary, one MIME table.** `MARKUP_SUFFIXES` and `MIME_BY_SUFFIX`
  agree by construction: a suffix that routes to markup is named `text/html`. A caller
  classifying on its own table will disagree on `.xhtml`, which EDGAR serves as markup.
- **`is_markup_document_path()` is the only markup test.** It answers for the rendering
  case as well as the flat one, so a caller keying on `MARKUP_SUFFIXES` alone wrongly
  reports an XSL rendering — served as HTML — as non-markup.
- `RawDocumentBlob` and `FilingOccurrence` round-trip through `to_row()` and
  `from_row()`; `FilingOccurrence.to_row()` renders `source_cik` through
  `Cik.to_10digit()`.

**Obligations on callers.**

- Build locators through `DocumentLocator.from_parts()`, not the positional constructor,
  unless restoring a row that already carries its key.
- Use `FetchResult.ok`, not `.status`, as the success predicate: `ok` requires
  `status == "ok"` *and* a non-`None` payload.
- Use `FetchResult.acquired` rather than reading `.payload` with `.locator` when
  handing a document onward. It resolves the content route for you and is `None` for a
  fetch that did not succeed, which a bare payload read cannot express.
- Pass an SGML `<FILENAME>` to `content_route()`, never to `document_route()`.

## Public surface

- `DocumentLocator` and its `from_parts()` constructor, plus the blob, occurrence,
  normalization, and failure records — `models.py`.
- `canonical_accession_part()`, `derive_document_locator_key()`,
  `derive_occurrence_id()`, and `DocumentKind` — `models.py`.
- `FetchResult`, `AcquiredDocument`, `AcquisitionSource`, `AcquisitionSourceKind`,
  `SgmlEnvelopeResolution`, `SgmlSubDocumentHeader`, `AcquisitionFailure`, `FetchStatus`,
  and `is_stub_document_path()` — `acquisition.py`.
- `BlockKind`, `DocumentBlock`, `BlockStream` — `blocks.py`.
- `DocumentRoute`, `document_route()`, `content_route()`, `is_rendered_document_path()`,
  `is_markup_document_path()`, `archive_root_candidate()`, `mime_type_for_suffix()`,
  and the `REPRESENTATION_*` names — `route.py`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/document/`.

## Deliberate gaps

- **No fetching, persistence, MIME detection, or retry policy.** Those capabilities
  belong to the infrastructure and pipeline layers. In particular, a caller arriving
  with bytes gets no way to learn their format from this package: `DocumentKind` is a
  declared vocabulary, not a detector, so format classification is the fetching and
  storage layers' responsibility.
- **A route classifies a name, never the payload.** `document_route()` and
  `content_route()` read only a path or filename, so a caller holding bytes alone still
  has no route. `UNKNOWN` covers the flat suffixes with no established rule, and those
  are treated as text.
- **No filing-level aggregate.** A filing spans a primary document, its exhibits, and
  optionally an XBRL package, and this package models one acquired document at a time.
  A sub-document's `<TYPE>` and sequence are recorded as observed facts with no
  primary/exhibit role, so a caller needing a filing-scoped view must build it. Roles,
  inversion recovery, and exhibit promotion are not decided here.
- **Acquisition provenance is not persisted.** `AcquiredDocument.source` and its
  envelope headers are in-memory records; the snapshot schema carries neither, so a
  stored row does not record which URL served it.
- **No form-aware XML validity.** A flat `.xml` is a valid primary document recorded
    with `representation: "xml"`, and the route does not consult the filing's form: it
    does not distinguish an XML-native form's own markup from an XBRL linkbase, and it
    does not filter `.xml` out of a narrative filing.
- **The catalog's `reported_size` is not a content signal.** It derives from
  `CIK****.json` and describes the original filed document; for a `.paper` row it
  reports a median near 1,700 bytes while the archive serves a stub of roughly 300.
  Route selection must never be driven by it.
