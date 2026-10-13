# S10 — Processing Contract, Processor Versions, and Document Review

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S10**.
- Status: S6 v4 declarative operation/source-input planning and S9's acquisition-owned
  resolved work order v3/run state are implemented. The `process --run-id` parser, operator
  action, run-level coordinator, per-target engine dispatch, operation-scoped retry, and
  atomic run-relative result manifest are wired. Offline CLI integration covers raw-only
  and test-budgeted TEXT processing; combined targeted package tests pass. Raw remains a staged-file
  reference. Generic `normalize_document` execution requires a versioned route/handler
  budget; the production budget registry is empty, so text normalization fails closed
  before body read/hash and writes no receipt. No representative production input, output,
  or working-set envelopes exist. Form 4 XML remains unsupported: its output contract and
  handler are absent.
  The retired `document_storage.FilingProcessor` is not a current runtime owner. Exhibit
  packs are not an active evaluator or holdout evidence.
- A processing-review artifact writer is exercised by captured S9 fixture replay and is
  wired to shared review generate/compare for the limited S9/S10 fixture slice. Reviewer
  labels, exhibit assessment, and full transform coverage remain incomplete; S10 runtime
  does not depend on review. See [`review_artifacts/builder.py`](../../../edgar_sec/pipelines/document_acquisition/review_artifacts/builder.py),
  [`commands/review.py`](../../../edgar_sec/pipelines/document_acquisition/commands/review.py),
  and [`review_artifacts/test_builder.py`](../../../tests/pipelines/document_acquisition/review_artifacts/test_builder.py).
- S11 publication consumes S10 outputs after its fixture-driven gate; see the
  [acquisition lifecycle plan](document_acquisition/lifecycle.md). Publication and cleanup
  remain approval-gated.
- Production gates remain: measured route-budget evidence, a Form 4 XML output
  contract/handler, reviewed family lazy-index triggers, serialization/effect of the
  already-defined plan-scoped supersession selector in a new immutable snapshot, and S11
  publication/cleanup approval. No supersession pruning occurs.
- Per-operation IDs, results, attempts, and payload relations are defined in the
  [representation materialization contract](document_acquisition/representation_materialization_contract.md).
- Exhibit assessment proposal: [S10 taxonomy and evidence-pack design](S10_exhibit_assessment.md).
- Legacy behavior audit: [document_storage processing trace](S10_legacy_processing_trace.md).

## Current tracked-code audit (2026-10-12)

- **Status:** S9 work-order v3 resolves operation support/handler pins and stores operation
  state/attempts. Its nullable lazy-trigger ID/version fields are currently null because no
  reviewed trigger patterns exist; no lazy-index request is authorized. The legacy S6
  `catalog_direct_selection` field is not runtime trigger authority. The process CLI,
  operator, coordinator, per-target engine dispatch, validated operation retry, and
  per-target result manifest are implemented. The coordinator reads the validated work
  order without reopening S6 or making HTTP requests.
- **Processing boundary:** `process_target` dispatches to the engine under a versioned
  route/handler budget. Raw is a file reference. The production route-budget registry is
  empty, so generic normalization refuses before body read/hash and writes no receipt.
  This is implemented fail-closed behavior, not enabled production text processing.
- **Result artifact:** an atomic JSON manifest is written at
  `staging/processing/<target_id>.json` relative to the run; operation attempts/state are
  persisted separately in run state. Operation-scoped retry reuses only validated prior
  results. S11 publication and cleanup approval remain gated.
- **Evidence:** S9 projection/validation and operation resolution are in [`plan_projection/target_plan.py`](../../../edgar_sec/pipelines/document_acquisition/plan_projection/target_plan.py), [`plan_projection/operation_resolution.py`](../../../edgar_sec/pipelines/document_acquisition/plan_projection/operation_resolution.py), [`run_validation.py`](../../../edgar_sec/pipelines/document_acquisition/run_validation.py), and [`schemas.py`](../../../edgar_sec/pipelines/document_acquisition/schemas.py); [`test_project.py`](../../../tests/pipelines/document_acquisition/plan_projection/test_project.py) pins work-order v3 and [`test_schemas.py`](../../../tests/pipelines/document_acquisition/test_schemas.py) asserts schema version 3. [`target_plan.py`](../../../edgar_sec/pipelines/document_acquisition/plan_projection/target_plan.py) emits null trigger ID/version pins, [`test_arrow_schemas.py`](../../../tests/pipelines/document_acquisition/test_arrow_schemas.py) covers their nullable schema, and [`test_runner.py`](../../../tests/pipelines/document_acquisition/test_runner.py) covers the no-trigger path. [`target_runner.py`](../../../edgar_sec/pipelines/document_acquisition/target_runner.py) authorizes lazy lookup only from a paired trigger ID/version.
- **Evidence:** Run coordination, operation state/retry, CLI/operator routing, and atomic result manifests are in [`processing/run.py`](../../../edgar_sec/pipelines/document_acquisition/processing/run.py), [`run_state/operations.py`](../../../edgar_sec/pipelines/document_acquisition/run_state/operations.py), [`commands/process.py`](../../../edgar_sec/pipelines/document_acquisition/commands/process.py), [`cli.py`](../../../edgar_sec/pipelines/document_acquisition/cli.py), and [`operator.py`](../../../edgar_sec/pipelines/document_acquisition/operator.py). [`test_process_cli_integration.py`](../../../tests/pipelines/document_acquisition/test_process_cli_integration.py) covers offline raw-only and test-budgeted TEXT CLI paths; [`processing/test_run.py`](../../../tests/pipelines/document_acquisition/processing/test_run.py) covers coordinator/retry behavior.
- **Evidence:** Engine dispatch and admission are in [`processing/worker.py`](../../../edgar_sec/pipelines/document_acquisition/processing/worker.py), [`processing/io.py`](../../../edgar_sec/pipelines/document_acquisition/processing/io.py), and [`engine/document_processing/processor.py`](../../../edgar_sec/engine/document_processing/processor.py). The empty production budget registry is asserted by [`processing/test_io.py`](../../../tests/pipelines/document_acquisition/processing/test_io.py); pre-body refusal/no-receipt behavior is covered by [`processing/test_worker.py`](../../../tests/pipelines/document_acquisition/processing/test_worker.py); engine handler behavior is covered by [`engine/document_processing/test_processor.py`](../../../tests/engine/document_processing/test_processor.py). The combined targeted S6/S9/S10 suite and policy scanners pass.

## Objective

Materialize each requested supported S6 operation as its own deterministic result. For
`render_to_txt` and `render_to_xml`, choose a family/route-specific handler before any
evidence-backed generic handler. The engine normalizer is the generic `render_to_txt`
fallback. Raw source bytes are always preserved independently of rendered output. This
is the dispatch contract. The run-level coordinator and engine dispatch are implemented,
but the empty production route-budget registry blocks text normalization before body
access; no production text transform is enabled.

S10 processes the source selected by one S6 target and S9 acquisition result. It does
not query the filing catalog or inventory, fetch an index page, discover another
document, or revise the target's identity. `source_origin="catalog_direct"` means the
catalog supplied the locator; processing does not upgrade it to an index-verified
statutory document type.

S9 work-order v3 carries nullable lazy-trigger ID/version pins. They are currently null
because no family has a reviewed trigger pattern, so no lazy-index request is authorized.
The pre-existing S6 `catalog_direct_selection` field is not runtime trigger authority and
must not revive `exact_form_with_lazy_index`. S10 consumes only the final work-order
assignment and never performs index lookup. A successful HTML cover screen is not an
exact-type assertion.

## Implemented semantics and enablement gates

- Every acquired source has a mandatory exact `raw` identity, represented as a staged-file
  reference. Unknown-route, paper, binary, PDF, XML, XSD, ZIP, and other non-text inputs
  have no text export; PDF extraction is not available.
- S6 marks `raw` as the mandatory baseline for every matched target. Explicit operation
  policy controls only additional derived representations; a renderer failure never
  removes raw.
- The engine dispatches family/route-specific handlers before generic fallbacks. For
  eligible text/HTML, `normalize_document` is the generic text fallback in engine tests;
  production execution remains disabled because no versioned route/handler budget is
  registered. The refusal occurs before body read/hash and creates no receipt.
- No Form 4 XML output contract or handler exists; Form 4 XML is unsupported. More
  generally, a transform requires resolved support and an admitted route/handler budget.
  Flat XML/XSD, ZIP, PDF, paper, binary, and unknown routes have no generic text render.
- Lazy-index trigger IDs/versions remain nullable and all current S9 work orders leave
  them null. No reviewed family trigger exists, so no lazy index request is authorized;
  Form 4 has no trigger.
- Processor version changes do not automatically invalidate older results. The
  plan-scoped selector semantics are defined in the [representation materialization
  contract](document_acquisition/representation_materialization_contract.md), scoped by
  form/family, operation, prior processor ID/version, and the plan's selected logical
  documents. Plan serialization and snapshot effect remain unimplemented; no pruning
  occurs now. Existing snapshots remain immutable.
- Production activation remains gated on reviewed route-budget evidence, a Form 4 XML
  contract/handler, reviewed family trigger patterns, selector serialization/snapshot
  effect, and S11 publication/cleanup approval. Combined targeted S6/S9/S10 tests and all
  registered scanners pass. Offline CLI integration covers raw-only and test-budgeted TXT;
  the production route-budget registry remains empty.

## Current processing interface and persisted results

The run-level coordinator consumes the validated S9 work-order v3, including resolved
operation support/handler pins, and the run-state operation relation. It does not reopen
S6/S5 artifacts or perform acquisition. The `process --run-id` CLI and interactive
operator use this coordinator. Operation-scoped retries validate prior result manifests
before reusing terminal results; each attempt is recorded in run state.

The per-target `ProcessingRequest`, operation/result models, and engine adapter are owned
by [`processing/models.py`](../../../edgar_sec/pipelines/document_acquisition/processing/models.py),
[`processing/worker.py`](../../../edgar_sec/pipelines/document_acquisition/processing/worker.py), and
[`engine/document_processing/processor.py`](../../../edgar_sec/engine/document_processing/processor.py).
S10 invokes the engine only after a versioned route/handler budget admits that operation.
Raw is a staged-file reference, not an additional materialized copy. Derived outputs are
written beneath run staging. The atomic result manifest is
`staging/processing/<target_id>.json` relative to the run; it contains operation outcomes,
digests, and safe relative staged-output references.

`ProcessingResult.source_sha256` is the selected-body digest. The full response-envelope
digest remains S9 provenance; S10 does not normalize or rewrite that envelope. Operation
fingerprints include source identity, effective path, capability/handler/options versions,
and output schema. `target_type` remains request provenance, not proof of selected SGML
type.

An admitted body read records the versioned `BodyConsumptionReceipt`, including when an
export fails. Budget refusal before body access or input identity failure writes no receipt.
The receipt proves consumption, not permission to delete a body required by S11. Cleanup
still requires the separate S11/publication or explicit-discard approval gate.

## Current run-level processing flow

The implemented coordinator reads the validated S9 work-order v3 and run state. It submits
the resolved operation set for acquired targets; terminal target failures block requested
operations. It never opens a S5/S6 source artifact or makes an HTTP request.

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
4. Apply the S9 resolved-operation rows. Return `not_requested`, `unsupported`, or
   `blocked` without invoking a handler; execute each selected, supported operation
   independently.
5. Keep `raw` as a reference to the acquired staged file. For derived operations, select
   the versioned route/handler budget before body access. The production budget registry
   is empty, so normalization fails closed before reading or hashing the body.
6. Under an admitted budget, dispatch to the engine, verify output size/digest, and stage
   derived output. Record each operation result and append-only attempt; failed operations
   do not erase successful siblings.
7. Atomically write `staging/processing/<target_id>.json` relative to the run. Store only
   safe relative staged-output references, never absolute paths or body bytes.
8. Record the S9 `BodyConsumptionReceipt` only after admitted body consumption, including
   when an export failed. Budget refusal before body access has no receipt. S11 publication
   and cleanup approval remain separate gates.

Operation failures are isolated; a failed export does not discard the source or sibling
results. Every operation fingerprint pins its handler/capability/options and output
schema versions. The separate diagnostic fingerprint pins the normalizer/evaluator,
evidence-pack, and taxonomy versions when those diagnostics are enabled.

### Working-set admission

The acquisition byte ceiling bounds a response, not the S10 working set. Every derived
handler requires a versioned route/handler budget covering input, output, and working set.
The production registry is empty; no representative envelopes exist, so no derived route
is production-enabled. The generic `normalize_document` path reads whole text/HTML input
and is exercised only by engine tests under an injected budget. S10 checks admission
before body read/hash; refusal preserves the raw file reference and writes no receipt.
Do not infer safe parallelism from the acquisition ceiling or invent expansion factors.

For engine tests, a primary uses its filing-form profile and a standalone exhibit uses
the generic no-cover profile. A registered family/route renderer takes precedence over
the generic normalizer fallback. This dispatch behavior does not enable production text
processing without a route budget.

## Route dispatch and production enablement

Resolve handlers from the effective source path and S9 capability pins, not claimed MIME
type alone. A direct target uses its validated accession-relative path; a bundle child
uses its selected `<FILENAME>` and `content_route()`, not the bundle envelope path.
`target_type` does not override the content route or assert the SGML header value. These
are engine dispatch semantics; production derived processing remains blocked by the empty
route-budget registry.

| Route | Engine/operation behavior | Production boundary |
|---|---|---|
| `MARKUP`, `RENDERED` | `raw` remains the source file reference. Engine dispatch prefers a registered family/route handler; `normalize_document` is the generic `render_to_txt` fallback for eligible text/HTML. | Engine behavior is unit-tested, but production rendering is blocked before body access until a budget is registered. No XBRL facts are extracted. |
| `TEXT` | Raw source remains a file reference. Engine tests cover generic text normalization and family/route precedence. | No production text transform is enabled without a versioned route/handler budget. |
| `XML` | Raw source is retained. No generic `render_to_xml` handler is registered; transforms require an explicit resolved handler over declared input. | Form 4 XML is unsupported because its output contract and handler are absent. Flat XML/XSD remain raw-only. |
| `BINARY`, `PAPER`, `UNKNOWN` | Raw source/state only; no generic derived renderer. | No PDF extraction, off-archive reference following, or guessed MIME conversion. |

`normalize_document` runs only when S9/S10 resolves the handler and a matching versioned
budget admits it. Current tests exercise it with an injected budget; the production budget
registry has no entries. Any future XML transform must consume a declared input and have
an explicit handler/output contract. S9's large-bundle path continues to use its bounded
streaming extractor rather than a whole-envelope normalizer.

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
  Lazy-index requests require an S9 work-order trigger ID/version from a reviewed family
  pattern. Current pins are null, so no target is authorized for lazy lookup. The S6
  `catalog_direct_selection` field does not grant this authority, and S10 never fetches an
  index or attaches new evidence to immutable S5/S6 artifacts.
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

Review replays only acquisition fixtures. The run-relative
`staging/processing/<target_id>.json` manifest records target ID, operation results,
source/input/output digests, handler fingerprints, and diagnostics; it is not an S11
published relation. `representation.txt` is a separate review copy, not a durable output.
An operation whose output digest aliases another payload writes no duplicate payload
file. Unsupported PDF/binary handlers have no derived output. Source HTML previews use
S7's sanitized inert renderer and never replace source evidence. One operation failure
does not erase successful sibling results.

## Tests

The focused contracts below do not imply that the combined package suite currently passes.
One raw-only offline CLI integration test passes; combined package tests are being corrected
and re-run. Production derived processing remains disabled until route budgets are approved.

- Same fixture body, path, target role, operation, and handler/options fingerprint
  produce identical result metadata and output digest.
- An index-backed exhibit target uses the generic no-cover profile independently of
  the filing-form primary; the target type is retained as provenance.
- A catalog-direct primary with no required cover boundary records
  `cover_boundary_not_detected` but does not change role/profile, fetch an index, or
  schedule replacement acquisition; generic-profile exhibits do not get that warning.
- Fingerprint changes prevent false base/new equality.
- `.txt` `render_to_txt` uses a family-specific handler or the generic normalizer fallback; preserve a distinct representation row even when output digest aliases raw.
- HTML engine tests retain raw and text identities and cover specific-handler precedence. No `render_to_xml` handler is registered in the current default engine catalog; no XML sibling is probed or fetched.
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

Raw is mandatory and remains a file reference; each enabled derived operation has an
independent deterministic outcome. Processor-version changes do not prune prior results.
The plan-scoped selector semantics are defined in the representation materialization
contract; plan serialization and snapshot effect are not implemented. Processing outputs
remain transient pending S11 publication approval. Cleanup also remains gated. Derived
production routes and large-body parallel work require reviewed route-budget envelopes.
Form 4 XML requires its own output contract and handler; lazy-index requests require
reviewed family triggers, currently none. The combined targeted S6/S9/S10 suite passes.
