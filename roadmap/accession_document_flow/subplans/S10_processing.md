# S10 — Processing Contract, Processor Versions, and Document Review

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S10**.
- Status: deterministic processing interface and route coverage; no durable output schema.
- Depends on: S9 staged selected-body and fixture replay contracts; S7 review artifacts.
- Non-blocking: S11 payload-store decision.

## Objective

Transform acquired filing bodies into deterministic review representations without persisting normalized content in inventory or target-plan artifacts. One input target yields one typed result with its source digest, effective route, processor fingerprint, output digest when applicable, and diagnostics.

## Models and operation

```python
@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    target_id: str
    accession: AccessionNumber
    form: str
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
    representation: Literal["text", "xml_verbatim"]
    output_sha256: str
    output_size: int

@dataclass(frozen=True, slots=True)
class ProcessingResult:
    target_id: str
    source_sha256: str
    route: DocumentRoute
    processor_fingerprint: str
    status: Literal["normalized", "validated_xml", "binary", "unrecognized", "failed"]
    representation: Literal["text", "xml_verbatim", "binary", "none"]
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

The normalized text/XML representation remains in worker memory. The worker returns
only metadata and digests; it writes a staged `ReviewOutputRef` only when
`capture_review=True`. S7 may promote that staged file into its non-empty-refusing
review directory, then removes the staging copy. Binary bodies have no normalized
output or review file.

The worker verifies the staged body against its S9 size/digest before normalization.
Text output is hashed as UTF-8 bytes with `sha256_text`; XML-verbatim output keeps the
source digest. The processor fingerprint covers route-policy and normalization
algorithm IDs, output schema version, and engine implementation version. Identical
source bytes, effective path/form, and fingerprint must yield identical status,
representation, output digest, and diagnostics.

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

## Route contract

Route from the effective archive path, not from a claimed MIME type alone. For a direct archive target, use the path relative to the accession archive directory and `domain.document.route.document_route()`. For a bundle-selected child, use its `<FILENAME>` and `content_route()`; the bundle envelope path is not the child's route.

| Route | Processing behavior | Deliberate boundary |
|---|---|---|
| `MARKUP`, `RENDERED` | Use `engine.forms.normalize.normalize_document()` with form and effective route. This includes the existing `engine.document.unpacking.representation.prepare_input_text()` decoding/ASCII-PRE detection and `engine.document.html.cleaner.clean_html_for_parsing()` path. | iXBRL inline tags are unwrapped for visible-text normalization; this stage does not extract or publish XBRL facts. |
| `TEXT` | Use the same form-aware normalizer; historical UTF-8/CP1252/Latin-1 decoding and `<PRE>` ASCII extraction are covered by the engine input-preparation contract. | Malformed or truncated but decodable HTML is best-effort output; record detectable warnings and preserve the source digest. The processor does not claim to prove the original markup was complete. |
| `XML` | Validate one standalone XML document with external entities/DTD processing disabled; return the exact source bytes as `xml_verbatim` review representation and hash. | No semantic XBRL fact extraction or XML rewriting is performed. XSL-rendered `.xml` paths route as `RENDERED` HTML instead. |
| `BINARY` | Return route, source digest, size, and MIME metadata without text normalization. | PDF/image text extraction is not supported; adding it requires an explicit dependency and design decision. |
| `PAPER` | Use the existing fixed-stub normalizer and record its route/status. | The off-archive document-control reference is not followed here. |
| `UNKNOWN` | Return `unrecognized` with source evidence and a route diagnostic. | No guessed text or MIME conversion. |

The existing `engine.document.html.normalizer.normalize_html_document()` remains available for consumers that explicitly require its HTML-to-text/table projection contract; S10's form-aware text path has one canonical entry point, `normalize_document()`. S10 requests a no-trace mode from the engine normalizer so intermediate `StageRecord` text copies are not materialized in worker memory. If that entry point cannot provide the mode, the implementation must add it in `engine.forms.normalize` before enabling parallel large-body processing. `engine.document.unpacking.unpacker` owns the existing byte-based SGML helper; S9's large-bundle path uses its bounded streaming extraction contract instead of invoking a whole-envelope normalizer here.

## Layer and migration boundary

S10 may depend on `domain.document.route`, `engine.document`, `engine.forms.normalize`, `engine.tables`, `foundation`, and S9/S7 public contracts. It must not import `pipelines.document_storage`. `engine.submissions` is not a document-body normalizer: it maps SEC submissions JSON to `submission_metadata` rows and is not reused for HTML/XML/PDF bodies.

Intermediate DOM/AST structures exist only inside the processing worker and are never returned or persisted. `NormalizationResult.stage_trace` is not materialized by the S10 path. Processing-worker concurrency is derived from the measured input and normalization expansion budget; one large body is processed per worker. These values do not enter inventory, target-plan, or acquisition-case Parquet. S7 may persist selected normalized text or XML only as review evidence. No S10 code creates durable payload parts or links payload fields into S5.

## Review behavior

Review replays only acquisition fixtures. `processing.json` always records target ID, source digest, route, processor fingerprint, status, output digest/size, and diagnostics. `normalized.txt` is written only for text results; XML and binary inputs do not receive a misleading text preview. Source HTML previews use S7's sanitized inert renderer. One document failure does not erase successful sibling cases.

## Tests

- Same fixture body, path, form, and processor fingerprint produce identical result metadata and output digest.
- Fingerprint changes prevent false base/new equality.
- XSL-rendered `.xml` is routed as HTML; flat XML is validated without HTML cleaning or XBRL fact extraction.
- iXBRL hidden/inline tags follow existing visible-text behavior; no fact table is emitted.
- Legacy `<PRE>` ASCII and malformed/unclosed HTML fixtures preserve content without raising false successful-empty results.
- XML with malformed structure or prohibited DTD/entity declarations fails with a typed diagnostic.
- PDF/image routes are `binary` with no normalized text; unknown routes are explicit `unrecognized`.
- Review writes normalized content only for selected fixtures; ordinary results leave no durable text/AST files.
- AST policy tests confirm no import from `pipelines.document_storage` and no payload writes to S5/S6 schemas.

## Acceptance criteria

HTML/text processing reuses the existing engine contract; standalone XML, binary, and unknown routes remain explicit; outputs are deterministic and transient except for selected review evidence. The future payload store remains a separate S11 approval gate.
