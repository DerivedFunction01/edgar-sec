# `edgar_sec/domain/document/` — Document identity, acquisition records, and block streams

## Purpose

Record shapes for two questions: *which document is this* and *what came back when we asked for it*.
Nothing here reads, writes, or requests anything. Fetching is
`pipelines/document_storage/fetching.py`, payload storage is
`pipelines/document_storage/checkpoint.py`, normalization is `engine/`.

## Contracts

- **Immutability**: Document locator keys are derived, never supplied; `from_parts()` always computes them.
- **Zero I/O**: Nothing here reads, writes, or requests anything; fetching, storage, and normalization belong to pipeline and engine layers.
- **Deterministic keys**: Both digests reduce the accession to its unhyphenated form first; Python and SQL derivations are pinned by cross-layer tests.
- **Document identity**: The requested locator is the only identity; neither acquired source nor sub-document filename may change `document_path` or `document_locator_key`.
- **Separation of concerns**: Acquisition reports are separate from storage decisions; `FetchResult` reports what came back, pipeline decides what to keep.
- **Route classification**: Document routes classify paths by slash/suffix rules; content routes classify basenames without directory semantics.

**Obligations on callers.**

- Build locators through `DocumentLocator.from_parts()`, not the positional constructor,
  unless restoring a row that already carries its key.
- Use `FetchResult.ok`, not `.status`, as the success predicate: `ok` requires
  `status == "ok"` *and* an acquired submission, which the constructor enforces.
- Read the body as `acquired.selected_payload` and its route as
  `acquired.selected_document.content_route`. A bare payload read cannot express which
  document was selected, and reading the route off the requested locator gets it wrong
  for every rendered link and SGML child.
- Pass an SGML `<FILENAME>` to `content_route()`, never to `document_route()`.
- Keep `FetchResult.source_payload` as transport data. It is the only place a complete
  envelope is held, and it exists for fixture seeding and delegated exhibits.

## Deliberate gaps

- **No fetching, persistence, MIME detection, or retry policy**: Those capabilities belong to infrastructure and pipeline layers.
- **Route classifies a name, not the payload**: `document_route()` and `content_route()` read only paths or filenames.
- **No filing-level aggregate**: `AcquiredSubmission` scopes one acquisition to one accession, not a merged filing view.
- **Acquisition provenance is not persisted**: `AcquiredSubmission.source` and descriptors are in-memory records.
- **No form-aware XML validity**: The route does not consult the filing's form to distinguish markup from linkbases.
- **`reported_size` is not a content signal**: It derives from CIK.json and describes original filed document, not archive content.
