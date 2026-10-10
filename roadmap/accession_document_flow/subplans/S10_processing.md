# S10 — Processing Contract, Processor Versions, and Document Review

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S10**.
- Status: S10 transient result/review contract is design-only; legacy route-aware
  processing is available but persists a different result shape.
- Depends on: S9 staged selected-body and fixture replay contracts; S7 review artifacts.
- Non-blocking: S11 payload-store decision.

## Current tracked-code audit (2026-10-08)

- **Status: processing foundations exist in the legacy pipeline; the S10 transient processing contract is not implemented.** `FilingProcessor` normalizes acquired bytes and exposes a fingerprint, but its result carries payload bytes for legacy persistence. The engine normalizer has no no-stage-trace switch, and no `process_target` result/review-staging API is present.
- **Evidence:** [`document_storage/processor.py`](../../../edgar_sec/edgar_sec/pipelines/document_storage/processor.py) returns `ProcessedDocument.payload`; [`engine/forms/normalize.py`](../../../edgar_sec/edgar_sec/engine/forms/normalize.py) always appends stage records; [`test_processor.py`](../../../tests/pipelines/document_storage/test_processor.py) covers legacy routes and fingerprint behavior.
- **Next step:** implement the S9 staged-body input and typed metadata-only result boundary, add the no-trace normalizer mode, then test route outcomes, XML refusal/validation, stable fingerprints, and review-output staging without durable payload writes.

## Objective

Transform acquired filing bodies into deterministic review representations without persisting normalized content in inventory or target-plan artifacts. One input target yields one typed result with its source digest, effective route, processor fingerprint, output digest when applicable, and diagnostics.

S10 processes the body selected by one S6 target and S9 acquisition result. It does
not query the filing catalog or inventory, fetch an index page, discover another
document, or revise the target's identity. `source_origin="catalog_direct"` means
the catalog supplied the locator; processing does not upgrade it to an
index-verified statutory document type.

## Models and operation

```python
from typing import Literal

from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef

@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    target_id: str
    accession: AccessionNumber
    form: str
    target_role: Literal["primary", "exhibit", "data_file", "graphic", "package"]
    target_type: str
    document_path: str | None
    selected_filename: str | None
    source_origin: Literal["inventory_index", "catalog_direct"]
    body: StagedBodyRef

@dataclass(frozen=True, slots=True)
class ProcessingDiagnostic:
    code: str
    detail: str

@dataclass(frozen=True, slots=True)
class ReviewOutputRef:
    staging_id: str
    path: Path
    representation: Literal["text", "text_verbatim"]
    output_sha256: str
    output_size: int

@dataclass(frozen=True, slots=True)
class ProcessingResult:
    target_id: str
    source_sha256: str
    route: DocumentRoute
    processor_fingerprint: str
    status: Literal["passthrough_text", "normalized", "validated_xml", "binary", "unrecognized", "failed"]
    representation: Literal["text_verbatim", "text", "xml_verbatim", "binary", "none"]
    output_sha256: str | None
    output_size: int | None
    diagnostics: tuple[ProcessingDiagnostic, ...]
    review_output: ReviewOutputRef | None

process_target(
    request: ProcessingRequest,
    *,
    capture_review: bool = False,
    review_staging: ManagedReviewStaging | None = None,
) -> ProcessingResult
```

The S10 coordinator joins an acquired body to its validated S9 work-order row by
`target_id` and copies the planned form/role/type into `ProcessingRequest`. It does
not reopen the S6 plan or S5 snapshot; failed or skipped acquisitions produce no
processing request.

Derived text remains in worker memory. The worker returns only metadata and digests;
it writes a staged `ReviewOutputRef` only when `capture_review=True`. S7 may promote
that staged file into its non-empty-refusing review directory, then removes the
staging copy. Byte-identical representations alias the source digest and are not
written as a second payload. An explicitly requested review may materialize a
byte-identical review copy for readability; binary bodies have no derived output or
review file.

After S10 has consumed an acquired body, its coordinator writes the versioned
[`BodyConsumptionReceipt`](document_acquisition/schemas.md) through the S9 path
contract before removing the staged selected body and any remaining bundle envelope.
This receipt is independent of processing success: an unrecognized or failed
normalization may still have fully consumed the input bytes. S10 imports only the S9
path/schema contracts, not acquisition services.

`ProcessingResult.source_sha256` is the selected-body digest in `StagedBodyRef.sha256`.
The full response-envelope digest remains S9 provenance in
`StagedBodyRef.source_response_sha256` and the acquisition attempt; S10 does not
normalize or rewrite that envelope.

The worker verifies the staged body against its S9 size/digest before processing.
Derived text output is hashed as UTF-8 bytes with `sha256_text`; verbatim text and
XML outputs keep the source digest. The processor fingerprint covers route-policy
and role-to-normalization-profile versions, normalization algorithm IDs, output
schema version, and engine implementation version. Identical source bytes, effective
path, filing form, target role, and fingerprint must yield identical status,
representation, output digest, and diagnostics. `target_type` is retained as request
provenance, not treated as the selected SGML header's type.

The reused form-aware engine entry point is extended with an explicit trace switch:

```python
normalize_document(
    raw_bytes: bytes,
    *,
    form: str | None = None,
    document_path: str | None = None,
    content_route: DocumentRoute | None = None,
    capture_stage_trace: bool = True,
) -> NormalizationResult
```

Existing callers retain the current default; S10 passes `capture_stage_trace=False`, yielding an empty `stage_trace` and avoiding repeated full-text copies. The normalizer's mirrored tests cover both modes.

For a primary, S10 passes the catalog filing form to this normalizer. For a
standalone exhibit, it passes no form so the generic no-cover profile is selected;
the filing form remains request provenance. This profile choice is deterministic from
the planned role and does not inspect or reinterpret the body.

## Route contract

Route from the effective archive path, not from a claimed MIME type alone. For a
direct archive target, use the path relative to the accession archive directory and
`domain.document.route.document_route()`. For a bundle-selected child, use its
`<FILENAME>` and `content_route()`; the bundle envelope path is not the child's
route. Select normalization context separately: a `primary` uses the filing-form
profile, while a standalone `exhibit` uses the generic no-cover profile. `target_type`
does not override the content route or assert the SGML header value.

| Route | Processing behavior | Deliberate boundary |
|---|---|---|
| `MARKUP`, `RENDERED` | Preserve the exact selected HTML bytes as S9 source evidence and use `engine.forms.normalize.normalize_document()` with the role-selected profile and effective route to derive visible text. | The raw HTML digest remains distinct from the normalized-text digest; iXBRL inline tags are unwrapped, but no XBRL facts are extracted or published. |
| `TEXT` | Flat `.txt` content consisting only of ASCII bytes is `text_verbatim`: do not invoke the normalizer; output digest and size equal the selected-body digest and size. Other text uses the role-selected profile and existing decoding/ASCII-PRE contract. | Verbatim text is an identity representation, not a claim that normalization ran. Non-ASCII text records detectable best-effort warnings. |
| `XML` | Validate one standalone XML document with external entities/DTD processing disabled; represent it as `xml_verbatim` with the exact source bytes and digest. | Raw and validated representations are aliases; do not write a second payload. No semantic XBRL fact extraction or XML rewriting is performed. XSL-rendered `.xml` paths route as `RENDERED` HTML instead. |
| `BINARY` | Return route, source digest, size, and MIME metadata without text processing. | PDF/image bytes remain raw source evidence; PDF text extraction is deferred and produces no derived representation. |
| `PAPER` | Use the existing fixed-stub normalizer and record its route/status. | The off-archive document-control reference is not followed here. |
| `UNKNOWN` | Return `unrecognized` with source evidence and a route diagnostic. | No guessed text or MIME conversion. |

The existing `engine.document.html.normalizer.normalize_html_document()` remains available for consumers that explicitly require its HTML-to-text/table projection contract; S10's derived-text path has one canonical entry point, `normalize_document()`. The ASCII `.txt` identity branch bypasses that normalizer. S10 requests a no-trace mode so intermediate `StageRecord` text copies are not materialized in worker memory. If that entry point cannot provide the mode, the implementation must add it in `engine.forms.normalize` before enabling parallel large-body processing. `engine.document.unpacking.unpacker` owns the existing byte-based SGML helper; S9's large-bundle path uses its bounded streaming extraction contract instead of invoking a whole-envelope normalizer here.

## Target identity and cover handling

- `target_role`, `target_type`, and filing form are copied from the S6 target row.
  The role selects the normalization context: `primary` uses the filing-form profile;
  `exhibit` uses the generic no-cover profile. The effective selected-body route/path
  still selects byte handling. These values do not re-resolve the target or verify a
  selected SGML `<TYPE>`.
- A catalog-direct plan is primary-only, so S10 uses the filing-form profile for its
  catalog-supplied body. If that profile requires a cover boundary and reports none,
  emit the non-fatal `cover_boundary_not_detected` diagnostic; do not fall back to the
  generic profile. If the body is actually an exhibit, this finding is not evidence to
  reclassify the target or fetch another primary. It is not proof that the catalog
  locator was correct either; only index-backed planning can select by an observed
  document type.
- A catalog-direct body is processed as the catalog-selected target, with its weaker
  provenance intact. S10 may report normalizer findings as diagnostics, but may not
  reinterpret the target, use a date/filename heuristic, or call an inventory helper
  to recover it. A no-cover or incorporation-by-reference finding never emits a
  `REFETCH_SUB_DOC` action or schedules S9 work.
- Multi-target profiles plan companions such as EX-13 up front. Each matched target
  has its own S9 acquisition and S10 result; an absent optional target remains the
  S6 `not_filed` outcome and has no S10 processing request. If retained, delegation
  phrase analysis is diagnostic evidence only and cannot create a target.
- If correct statutory identity or a companion target is required, publish the S5
  inventory snapshot and re-plan in S6 before acquisition. An index fetched during
  S10 is out of contract: it cannot be attached to the immutable target plan or
  written into S5/S6 by the processing owner.
- A valid catalog-direct target still receives an ordinary S10 result with its
  catalog provenance intact and may be considered by the future S11 store. The
  prohibition is on persisting an index-discovered replacement or companion that has
  no pinned S6 target row.

## Layer and migration boundary

S10 may depend on `domain.document.route`, `engine.document`, `engine.forms.normalize`, `engine.tables`, `foundation`, and S9/S7 public contracts. It must not import `pipelines.document_storage`. `engine.submissions` is not a document-body normalizer: it maps SEC submissions JSON to `submission_metadata` rows and is not reused for HTML/XML/PDF bodies.

Intermediate DOM/AST structures exist only inside the processing worker and are never returned or persisted. `NormalizationResult.stage_trace` is not materialized by the S10 path. Processing-worker concurrency is derived from the measured input and normalization expansion budget; one large body is processed per worker. These values do not enter inventory, target-plan, or acquisition-case Parquet. S7 may persist selected derived text only as review evidence. Raw source bytes remain in the S9 fixture BLOB or transient acquisition staging; `source.inert.html` is a sanitized preview, not a raw-byte archive. No S10 code creates durable payload parts or links payload fields into S5.

## Review behavior

Review replays only acquisition fixtures. `processing.json` always records target ID, source digest, route, processor fingerprint, status, representation, output digest/size, and diagnostics. `representation.txt` is written only when selected text output is explicitly captured; for `text_verbatim` it is a review copy of the source, not a distinct payload. XML aliases the source bytes and does not get a duplicate payload file. PDF/binary inputs have no derived output. Source HTML previews use S7's sanitized inert renderer and never replace the exact source evidence. One document failure does not erase successful sibling cases.

## Tests

- Same fixture body, path, form, target role, and processor fingerprint produce
  identical result metadata and output digest.
- An index-backed exhibit target uses the generic no-cover profile independently of
  the filing-form primary; the target type is retained as provenance.
- A catalog-direct primary with no required cover boundary records
  `cover_boundary_not_detected` but does not change role/profile, fetch an index, or
  schedule replacement acquisition; generic-profile exhibits do not get that warning.
- Fingerprint changes prevent false base/new equality.
- Flat ASCII `.txt` inputs bypass normalization and return the source digest/size as a `text_verbatim` representation.
- HTML inputs retain distinct raw-source and derived-text digests; XML validation preserves byte identity; PDFs produce no extracted representation.
- XSL-rendered `.xml` is routed as HTML; flat XML is validated without HTML cleaning or XBRL fact extraction.
- iXBRL hidden/inline tags follow existing visible-text behavior; no fact table is emitted.
- ASCII `.txt` bytes, including literal markup text, remain byte-identical; malformed/unclosed HTML fixtures produce best-effort text without false successful-empty results.
- XML with malformed structure or prohibited DTD/entity declarations fails with a typed diagnostic.
- PDF/image routes are `binary` with no derived text; unknown routes are explicit `unrecognized`.
- Review writes a text representation only for selected fixtures; ordinary results leave no durable text/AST files.
- AST policy tests confirm no import from `pipelines.document_storage` and no payload writes to S5/S6 schemas.

## Acceptance criteria

HTML and non-ASCII text processing reuse the existing engine contract; ASCII text
passthrough, standalone XML, binary, and unknown routes remain explicit. Outputs are
deterministic and transient except for selected review evidence. The future payload
store remains a separate S11 approval gate.
