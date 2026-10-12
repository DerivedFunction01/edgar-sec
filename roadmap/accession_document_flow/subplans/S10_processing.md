# S10 — Processing Contract, Processor Versions, and Document Review

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S10**.
- Status: transient processing request/result models, offline `process_target`, and
  in-memory terminal-result projection are implemented. The worker supports raw identity
  and explicitly pinned direct-TEXT passthrough, validates form-family operation
  permissions, and preserves unsupported placeholders. Durable operation-result and
  payload schemas, general export handlers, and coordinator wiring remain incomplete.
  The retired `document_storage.FilingProcessor` is not a current runtime owner. The
  engine normalizer is not yet wired as an export handler. Exhibit packs are not an active
  evaluator or holdout evidence.
- A processing-review artifact writer is exercised by captured S9 direct-TEXT fixture
  replay and is wired to the shared review console. Reviewer labels, exhibit assessment,
  and full transform coverage remain incomplete; S10 runtime does not depend on review.
- S11 publication consumes S10 outputs after the fixture-driven S9/S10 gate; see the
  [acquisition lifecycle plan](document_acquisition/lifecycle.md).
- Per-operation IDs, results, attempts, and payload relations are defined in the
  [representation materialization contract](document_acquisition/representation_materialization_contract.md).
- Exhibit assessment proposal: [S10 taxonomy and evidence-pack design](S10_exhibit_assessment.md).
- Legacy behavior audit: [document_storage processing trace](S10_legacy_processing_trace.md).

## Current tracked-code audit (2026-10-12)

- **Status: M6 has an initial offline `process_target` worker.** It validates the v1 work-order identity, selected body, and S9 attempt evidence; returns deterministic raw identity results and text identity on the `TEXT` route; and records the existing receipt. M7b now persists and verifies bundle-child filename evidence. Real renderers, review staging, and the coordinator remain unavailable. The operation-aware persisted relations remain design-only.
- **Result projection:** `result_projection.project_terminal_results` validates explicit request/result batches, terminal operation coverage, and staged-output references into a deterministic in-memory view. It does not query processor liveness or persist S11 relations. Completeness is relative to supplied requests because the current v1 work order has no operation-intent relation.
- **Evidence:** [`processing.py`](../../../edgar_sec/pipelines/document_acquisition/processing.py), [`result_projection.py`](../../../edgar_sec/pipelines/document_acquisition/review_artifacts/result_projection.py), their mirrored tests, and [`engine/forms/normalize.py`](../../../edgar_sec/engine/forms/normalize.py); the normalizer supports `capture_stage_trace=False` but is not an export handler.
- **Next step:** version the family/route handler precedence, family-specific lazy-index
  triggers, operation intent, and explicit processor-supersession selectors; then wire a
  coordinator to execute the pinned operations. Do not infer bundle selection or publish
  durable output from this preflight.

## Objective

Materialize each requested supported S6 operation as its own deterministic result. For
`render_to_txt` and `render_to_xml`, choose a family/route-specific handler before any
evidence-backed generic handler. The engine normalizer is the generic `render_to_txt`
fallback. Raw source bytes are always preserved independently of rendered output.

S10 processes the source selected by one S6 target and S9 acquisition result. It does
not query the filing catalog or inventory, fetch an index page, discover another
document, or revise the target's identity. `source_origin="catalog_direct"` means the
catalog supplied the locator; processing does not upgrade it to an index-verified
statutory document type.

For catalog-direct primaries, S9's pinned selector is resolved before S10 receives a
body. The current implementation exposes a uniform `exact_form_with_lazy_index` selector;
the requested future policy replaces it with form-family-specific text triggers. A family
without a designed trigger, initially including Form 4, must not perform lazy index
selection. S10 processes only the final target-to-slot assignment and never runs that
lookup itself. A successful HTML cover screen is not an exact-type assertion.

## Requested policy delta (not yet implemented)

- Every acquired source remains an exact `raw` representation, regardless of form or
  route. Paper, binary, PDF, XML, XSD, ZIP, and other non-text inputs have no text export;
  PDF extraction is not available.
- S6 marks `raw` as the mandatory baseline for every matched target. Explicit operation
  policy controls only additional derived representations; a renderer failure never
  removes raw.
- `render_to_txt` resolves a form-family/route-specific renderer first. If none is
  registered, the engine `normalize_document` path is the generic fallback for text and
  HTML/rendered-markup sources, with primary cover-aware and exhibit no-cover contexts.
- A Form 4-specific `render_to_xml` transform may consume its declared `.htm` input. It
  does not generalize to other forms or turn selected XML/XSD/ZIP sources into rendered
  output. Other forms need their own evidence-backed capability or a reviewed generic
  transform; the Form 4 handler continues to override a generic handler.
- Raw-only families cannot use text scanning as a lazy-index trigger. Each family must
  pin its own trigger; Form 4 has none designed. Its raw target must use the pinned URL
  and observed exhibit-like link evidence for its era.
- Processor version changes do not automatically invalidate older results. A plan-scoped
  supersession selector must identify form/family, operation, and prior processor/version;
  it may retire only matching representations in the new snapshot. Existing snapshots
  remain immutable, and unrelated families sharing a renderer version remain retained.

## Models and operation

```python
from typing import Literal

from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef

@dataclass(frozen=True, slots=True)
class OperationRequest:
    operation_id: str
    operation: Literal["raw", "render_to_txt", "render_to_xml"]
    requested: bool
    support_status: Literal["supported", "unsupported", "not_evaluated"]
    source_request_id: str | None
    capability_id: str | None
    capability_version: str | None
    handler_id: str | None
    handler_version: str | None
    output_kind: str | None

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
    operations: tuple[OperationRequest, ...]

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
class OperationResult:
    operation_id: str
    status: Literal["not_requested", "unsupported", "blocked", "available", "failed"]
    representation_id: str | None
    output_sha256: str | None
    output_size: int | None
    handler_id: str | None
    handler_version: str | None
    diagnostics: tuple[ProcessingDiagnostic, ...]
    review_output: ReviewOutputRef | None

@dataclass(frozen=True, slots=True)
class ProcessingResult:
    target_id: str
    source_sha256: str
    source_asset_id: str
    route: DocumentRoute
    operation_results: tuple[OperationResult, ...]
    exhibit_assessment: DocumentRoleAssessment | None

process_target(
    request: ProcessingRequest,
    *,
    capture_review: bool = False,
    review_staging: ManagedReviewStaging | None = None,
) -> ProcessingResult
```

The S10 coordinator joins an acquired body to its validated `work_targets` row and
the target's `work_operations` rows by `target_id`. It copies the pinned operation,
capability, handler, source-input, form, role, and type fields into `ProcessingRequest`.
It does not reopen the S6 plan or S5 snapshot; failed or skipped acquisitions produce
blocked operation results without invoking a handler.

Each successful non-identity operation writes its own output to managed transient
staging even when review capture is disabled; S11 needs that file to adopt the output
payload. The worker returns metadata and digest/path references, never the body bytes.
Diagnostic normalized text remains transient in memory and is not a stored operation
output. Optional `ReviewOutputRef` files are separate copies owned by S7 and cannot
replace the operation output. Identity and representation-reuse results alias an
existing digest and do not write duplicate payload files.

After S10 has consumed the acquired body for the target's operation set, its coordinator writes the versioned
[`BodyConsumptionReceipt`](document_acquisition/schemas.md) through the S9 path
contract. This receipt proves consumption, not permission to delete bytes required by
S11 publication. S9 retains the selected body until Parquet publication or explicit run
discard; a bundle envelope may be removed after extraction unless fixture capture
retained it. The receipt is independent of operation success: a failed export may still
have fully consumed the input bytes. S10 imports only the S9 path/schema contracts, not
acquisition services.

`ProcessingResult.source_sha256` is the selected-body digest in `StagedBodyRef.sha256`.
The full response-envelope digest remains S9 provenance in
`StagedBodyRef.source_response_sha256` and the acquisition attempt; S10 does not
normalize or rewrite that envelope.

The worker verifies the staged body against its S9 size/digest before processing.
Each operation fingerprint covers its exact source digest/asset, effective path,
capability/handler/options versions, and output schema. Identical pinned inputs must
yield the same result metadata and output digest. Diagnostic-normalizer and evaluator
fingerprints are recorded separately from export handler versions. `target_type` is
retained as request provenance, not treated as the selected SGML header's type.

## `process_target` execution sequence

The S10 coordinator reads only the validated S9 run/work relations. It submits one
operation set per acquired target; terminal target failures block requested operations,
while `not_requested` and `unsupported` rows need no handler call. It never opens an
S5/S6 source artifact or makes an HTTP request.

1. Validate the `ProcessingRequest` against the S9 work-order row by `target_id`.
   Form, role, type, accession, path and source origin must match that immutable row.
2. Open the staged selected body as a regular file beneath the run's owned staging
   root, refusing symlinks and path escapes. Enforce the S9 recorded size and finite
   response bound. Verify the selected-body digest over the same bytes that will be
   processed; do not hash one pathname and later process a second open of it.
3. Resolve the effective route. A direct target uses its validated accession-relative
   path. A bundle child uses its selected SGML filename with `content_route()`; its
   containing `.txt` envelope does not decide the child route. S9's envelope digest
   remains provenance, not S10 input identity.
4. For each operation, apply its pinned S6 disposition. Return `not_requested`,
   `unsupported`, or `blocked` without invoking a handler; execute each requested,
   supported operation independently.
5. `raw` creates an identity representation over the selected source digest.
   `render_to_txt` chooses a family/route handler before the generic normalizer fallback
   for eligible text/HTML input. `render_to_xml` chooses a family-specific transform
   before an evidence-backed generic transform over a declared HTML input; no `.xml`
   sibling is opened or fetched. There is no operation fallback.
6. Optionally run the separate diagnostic normalizer/evaluator on a bounded view. Its
   text and findings do not become a render output and cannot alter operation status,
   route, selected body, or S9 state.
7. Hash every export output, verify size, and write it to managed operation staging.
   Record one result and append-only attempt per operation; optional review copies
   remain S7-owned and do not publish payloads.
8. After the target's requested operation set has consumed the verified body, write
   one S9 `BodyConsumptionReceipt`, including when an export failed. Admission refusal
   before reading or digest/size mismatch has no receipt; retain the source for retry.
   S9 cleanup additionally requires publisher adoption or explicit run discard.

Operation failures are isolated; a failed export does not discard the source or sibling
results. Every operation fingerprint pins its handler/capability/options and output
schema versions. The separate diagnostic fingerprint pins the normalizer/evaluator,
evidence-pack, and taxonomy versions when those diagnostics are enabled.

### Working-set admission

The acquisition byte ceiling bounds a response, not the S10 working set. Export
handlers declare their own bounded route policy. The separate diagnostic normalizer
accepts a whole `bytes` body, decodes it, and builds whole-text/HTML structures;
disabling stage traces removes repeated text records but does not make diagnostics
streaming. Until route-specific estimates are validated, the implementation must not
claim safe parallel processing for every body under the acquisition ceiling.

Before dispatch, S10 derives available memory using the repository resource helper and
admits each handler only when its versioned route policy reserves the working set.
Worker count and in-flight bodies are resource-derived. Use streaming handlers where
available; diagnostics requiring whole-body normalization receive a separate budget
admission. Do not invent a universal expansion factor or hardcode worker/memory limits.
A refusal before reading returns `processing_budget_exceeded`, retains the S9 source,
and writes no body-consumption receipt. Establish route envelopes from captured cases
before enabling large-body parallel work.

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

Existing callers retain the current default. The requested generic `render_to_txt`
fallback uses this normalizer on eligible text/HTML sources. Diagnostic/review callers
may also use it; S10 passes `capture_stage_trace=False` to avoid repeated full-text
copies.

For generic normalization, a primary uses its filing-form profile and a standalone
exhibit uses the generic no-cover profile. A registered family/route renderer takes
precedence over this fallback.

## Route contract

Route export handlers from the effective source path, not claimed MIME type alone. A
direct target uses its validated accession-relative path; a bundle child uses its
selected `<FILENAME>` and `content_route()`, not the bundle envelope path. A family/route
specific text renderer overrides the generic normalizer fallback. `target_type` does not
override the content route or assert the SGML header value.

| Route | Operation behavior | Deliberate boundary |
|---|---|---|
| `MARKUP`, `RENDERED` | `raw` keeps exact selected bytes. `render_to_txt` uses a family-specific handler first, then generic `normalize_document`; `render_to_xml` uses a family-specific handler or an evidence-backed generic transform. Form 4's handler is specific to its declared HTML path. | HTML/iXBRL output is an export view; no XBRL facts are extracted. |
| `TEXT` | `raw` preserves source bytes. `render_to_txt` uses a form-specific handler or generic normalizer fallback; byte-identical output may share the payload digest but has its own representation row. | The normalizer is an export path, not an implicit request to emit diagnostic stage traces. |
| `XML` | `raw` preserves standalone XML. `render_to_xml` is supported only for a registered form-specific or evidence-backed generic transform over a declared HTML input; flat XML does not become its own render output. | No archive-root sibling fetch or semantic XBRL extraction. |
| `BINARY` | `raw` preserves exact bytes. No text handler is currently supported; PDF extraction remains unavailable. | Binary source bytes remain independently available. |
| `PAPER`, `UNKNOWN` | `raw` preserves the available selected source/state; no derived renderer is enabled for these routes. | No off-archive reference following or guessed MIME conversion. |

The generic `render_to_txt` fallback is `engine.forms.normalize.normalize_document()`
over eligible text/HTML inputs with the pinned primary or no-cover profile. A registered
family-specific handler takes precedence. The export registry pins the selected handler
and processor version. An XML transform follows the same specific-over-generic rule only
when generic capability has reviewed evidence. S9's large-bundle path continues to use
its bounded streaming extractor rather than a whole-envelope normalizer.

## Target identity and cover handling

- `target_role`, `target_type`, and filing form are copied from the S6 target row.
  For generic text rendering and optional diagnostics, the role selects normalization
  context: `primary` uses the filing-form profile and `exhibit` uses the generic no-cover
  profile. A registered family/route renderer overrides that fallback. These values do
  not re-resolve the target or verify a selected SGML `<TYPE>`.
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
- The provisional [exhibit assessment](S10_exhibit_assessment.md) may report that a
  catalog-direct primary looks exhibit-like. This is an explicitly uncertain
  diagnostic, not proof of a bad catalog locator and not permission to fetch a
  replacement.
- Multi-target profiles plan companions such as EX-13 up front. Each matched target
  has its own S9 acquisition and S10 result; an absent optional target remains the
  S6 `not_filed` outcome and has no S10 processing request. If retained, delegation
  phrase analysis is diagnostic evidence only and cannot create a target.
- If a caller requires published, reusable statutory identity evidence, or a companion
  target, publish the S5 inventory snapshot and re-plan in S6 before acquisition.
  Catalog-direct `exact_form_with_lazy_index` is the separately authorized S9-only
  exception; an index fetched during S10 is out of contract and cannot be attached to
  the immutable target plan or written into S5/S6 by the processing owner.
- A valid catalog-direct target still receives an ordinary S10 result with its
  catalog provenance intact and may be considered by the future S11 store. The
  prohibition is on persisting an index-discovered replacement or companion that has
  no pinned S6 target row.

## Layer and migration boundary

S10 may depend on `domain.document.route` and the registered export handlers. The
`document_storage` runtime is retired. `engine.submissions` maps submissions JSON to
metadata and is not reused for body rendering.

Intermediate DOM/AST/text structures used by renderers or diagnostics stay inside the
processing worker. Diagnostic `NormalizationResult.stage_trace` is never materialized.
Handler concurrency is resource-derived and bounded by each route's admission policy.
Export outputs are staged per operation for S11; S7 may separately retain selected
review output. Raw source bytes remain in the S9 fixture BLOB or transient staging;
`source.inert.html` is a sanitized preview, not a raw-byte archive. No S10 code creates
durable payload parts or links payload fields into S5/S6.

## Review behavior

Review replays only acquisition fixtures. `processing.json` records target ID, operation
results, source/input/output digests, handler fingerprints, and diagnostics; it may also
record the versioned exhibit assessment. `representation.txt` is a separate review copy,
not a durable output. An operation whose output digest aliases another payload writes no
duplicate payload file. Unsupported PDF/binary handlers have no derived output. Source
HTML previews use S7's sanitized inert renderer and never replace source evidence. One
operation failure does not erase successful sibling results.

## Tests

- Same fixture body, path, target role, operation, and handler/options fingerprint
  produce identical result metadata and output digest.
- An index-backed exhibit target uses the generic no-cover profile independently of
  the filing-form primary; the target type is retained as provenance.
- A catalog-direct primary with no required cover boundary records
  `cover_boundary_not_detected` but does not change role/profile, fetch an index, or
  schedule replacement acquisition; generic-profile exhibits do not get that warning.
- Fingerprint changes prevent false base/new equality.
- `.txt` `render_to_txt` uses a family-specific handler or the generic normalizer fallback; preserve a distinct representation row even when output digest aliases raw.
- HTML export retains raw and text representations; specific handlers override generic fallbacks. Form-specific or evidence-backed generic `render_to_xml` consumes declared HTML input and never probes for an XML sibling.
- Flat XML/XSD, ZIP, paper, binary, and PDF remain raw-only. PDF has no text handler.
- iXBRL hidden/inline tags follow existing visible-text behavior; no fact table is emitted.
- Family-specific `render_to_txt` overrides the generic `normalize_document` fallback; both produce deterministic versioned outputs. Raw source bytes remain unchanged.
- Body and request identity mismatches refuse processing; a typed working-set admission refusal preserves the acquired body without a consumption receipt.
- A completed read followed by an export failure still writes a matching consumption receipt; unreadable or digest-mismatched input does not. The receipt alone never permits cleanup before publication adoption or explicit discard.
- Exhibit assessment is absent for unsupported representations/forms; when enabled it can only append a diagnostic and cannot change the target, profile, or acquisition state.
- PDF/image routes are `binary` with no derived text; unknown routes are explicit `unrecognized`.
- Review writes a text representation only for selected fixtures; ordinary results leave no durable text/AST files.
- AST policy tests confirm no import from `pipelines.document_storage` and no payload writes to S5/S6 schemas.

## Acceptance criteria

Raw is mandatory and every additional supported operation has an independent deterministic
outcome; raw and exports retain separate identities. A processor version change does not retire other
families' representations without an explicit plan-scoped supersession selector. Processing outputs are transient until S11
publication adopts selected representations into Parquet payload relations, except for
separately selected review evidence. The publication contract is specified in the
acquisition lifecycle plan and remains behind S11 approval. Large-body parallel processing remains gated on measured route
working-set envelopes. Private diagnostic development is not gated on a holdout;
authoritative exhibit-family activation is gated on reviewed, holdout-tested evidence
packs and an explicit acceptance decision.
