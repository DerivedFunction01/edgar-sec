# S6 Declarative Target Plans and S9/S10 Acquisition Policy

**Status:** `document_planning` generates target plans and carries declarative requested
operations and source inputs. S6 bundle v4, target schema v1, and matcher v2 are implemented
as declarative-only; the explicitly mirrored tests passed (106). `document_planning` does
not resolve acquisition/processing support, handler IDs/versions, renderer availability, or
lazy-index trigger policy. S9 resolver/work-order implementation remains in progress; those
runtime resolutions belong to `document_acquisition`'s S9/S10 work-order policy.

## Goal

For each logical target, let declarative profile intent request one or more operations over
the acquired file: preserve it raw, render it to text, or produce an XML representation.
The request does not assert that an operation is supported. Explicitly requesting multiple
operations asks the owning acquisition/processing policy to resolve each independently.
S9/S10 work-order policy resolves source inputs, supported operations, and execution
metadata; S6 does not resolve support or bind a handler.

Document planning remains offline and body-blind. It may carry requested operations and
declared source inputs, but does not resolve acquisition/processing support, handler IDs or
versions, renderer availability, or lazy-index triggers. S9 resolves acquisition inputs
and family-specific lazy-index policy in its work order; S10 resolves processing support
and handler/renderer metadata there. A handler needing another source or multiple inputs
requires an explicit versioned source-input contract. XML parsing remains in a separate
form-specific pipeline.

Operation policy controls processing outputs, not retrieval cost or transport mode.
It does not compare child/index, complete-submission, or S1-reported sizes, and it
does not authorize grouping targets into one bundle request. Review-run and fixture
evidence establishes that positive numbered children map to accession-prefixed archive
leaves; an observed inventory link or exact catalog `primaryDocument` can support direct
retrieval. `0001` is not inherently a placeholder. Exact primary `0000.txt`/`.htm` names
remain placeholders and require an observed positive sequence plus pinned bundle URL;
catalog-only targets remain unresolved. An indexed `0001.txt`/`.htm` primary without a
usable prefixed link may use its observed bundle sequence. Other S6 locator selection
remains governed by [`S6_target_plans.md`](../S6_target_plans.md). These are declarative
source inputs and target-match outcomes; they do not establish acquisition support,
handlers, or lazy-index permission.

## Work-order operation contract (proposed)

The vocabulary may be carried declaratively by S6. The meanings below are proposed
S9/S10 work-order semantics, not operation-support resolution performed during planning.

Treat operation names as a closed, versioned vocabulary:

| Operation | Meaning |
|---|---|
| `raw` | Mandatory baseline representation preserving the selected source bytes for every matched target and route. |
| `render_to_txt` | Produce a text representation using a family/route renderer first, then the generic engine normalizer for eligible text/HTML sources. PDF extraction is unavailable. |
| `render_to_xml` | Produce XML from a declared HTML input using a family-specific transform first, then an evidence-backed generic transform. It does not fetch an XML sibling or perform semantic XML/XBRL parsing. |

The S9/S10 work-order policy resolves operation support for `(filing family, target
role/type, path facts)`. A form family may implement different operations for the same
suffix; an extension alone does not select a statutory family or guarantee that an
operation is accurate. S6 carries requested operations as intent only.

### Explicit operations and default priority

An explicit profile policy is a non-empty multi-select set with unique operation names.
Unknown or duplicate names and an empty explicit list are profile validation errors. For
example:

```json
{
  "role": "primary",
  "type": "primary",
  "optional": false,
  "acquisition_policy": {
    "operations": ["raw", "render_to_txt", "render_to_xml"]
  }
}
```

The order in the list is not preference order. Raw is requested for every matched target
whether or not it appears in the list. Execute every listed derived operation implemented
for the selected family and path facts. If a derived operation is not implemented, record
it as unsupported; that does not invalidate the logical target, raw, or other outputs.

When a target omits `acquisition_policy`, the S9/S10 work-order resolver chooses the first
supported derived renderer in this default priority; raw remains the baseline:

```text
render_to_xml > render_to_txt
```

Support means registered for the resolved family, target role, and path-facts combination
in the S9/S10 work-order policy. It does not mean the operation is guaranteed to succeed
on a particular body. At execution time, a fetch or transform failure is recorded against
that operation; it does not silently fall through to a different URL or operation. A
profile can explicitly request multiple derived operations when it wants more than the
default rendered view.

Keep target `optional` separate from operation support and outcome. It answers whether the
logical document may be absent; it does not mean an unsupported render operation is a
missing document. If all explicitly requested operations are unsupported, the S9/S10 work
order records that status without invalidating the logical target; acquisition and output
retention happen in their owning stages.

## Route-model reuse and ownership

`edgar_sec.domain.document.route` is shared today, but `DocumentRoute` mixes path shape
(`RENDERED`), suffix-derived file classes (`XML`, `BINARY`), and special input cases
(`PAPER`). That is too coarse for acquisition: one nested `.xml` locator can yield three
valid outputs, while flat `.xml` and `.xsd` stay raw-only. Replace the enum as the shared
contract with generic **path facts**, then let each pipeline interpret those facts through
its own policy. The shared classifier must describe the locator, not choose processing.

Proposed `DocumentPathFacts` records independent facts rather than one route enum:

- `path_context`: archive URL path or SGML filename; SGML filenames never acquire URL
  directory semantics.
- `path_shape`: flat or nested locator; nested does not prove an allowed XSL source path
  or claim the body was inspected.
- `suffix` and `suffix_class`: normalized suffix plus markup, text, XML/XSD, PDF, image,
  paper, opaque (`.fil`, `.zip`, `.eis`), or unknown classification.

Use distinct constructors such as `archive_path_facts(path)` and
`sgml_filename_facts(filename)` so callers state which path contract they have. Keep
`archive_root_candidate(path)` as a separate pure basename helper; it does not prove the
candidate exists. URL construction and validation remain outside the domain classifier.

`DocumentPathShape` and `DocumentSuffixClass` are shared classification enums inside that
value object, not parent enums for pipeline-specific enums. `document_storage` maps them to
its existing local disposition (normalize, preserve, or defer); S9/S10 work-order policy
maps them to acquisition/processing decisions. `document_planning` carries declared
operations and source inputs only; it does not resolve support. Acquisition can classify
`.fil`, `.zip`, `.eis`, and image suffixes as opaque/raw-only without forcing the current
document-storage processor to change how it treats an unknown suffix.

For an XSL-style `.../*.xml` path, the facts are `archive path + nested + .xml`. The
selected response remains raw; if its content route is rendered markup,
  S9/S10 work-order policy may resolve `render_to_txt` with a family-specific handler
  before the generic normalizer. A family-specific or evidence-backed generic XML
  transform consumes a declared HTML input; it does not use a separate archive-root XML
  source. Flat `.xml`/`.xsd` remains raw-only.
No classifier value should encode the set of operations that a form supports. New suffix
facts such as `.zip` or `.fil` must not silently change document-storage behavior.

Do not make `DocumentStorageRoute` and `DocumentAcquisitionRoute` subclasses of one
populated enum. Python enums cannot be extended that way, and one classification may
produce several operation results. Use shared path facts and separate policy mappings:
the historical document-storage pipeline mapped facts to normalize/store decisions;
  that pipeline is retired. S9/S10 work-order policy maps facts plus family and target
  intent to source and processing decisions. `document_planning` carries declarative
  requests without resolving them. This keeps the acquisition matrix independent without
  duplicating file suffix parsing.

| Consumer | Current route dependency | Phase-1 migration surface |
|---|---|---|
| Former `domain/document/acquisition.py` | Direct locators used `document_route`; `SubmissionDocument.content_route` stored an explicit SGML-child classification. | Retired records are not an S9 compatibility surface. Keep archive-path and SGML-filename classification distinct in retained unpacking behavior. |
| Former `document_storage/fetching.py` | Historical `archive_root_candidate` URL/fixture preference and requested-path fallback. | Retired; do not restore ordinary direct-failure bundle fallback. URL validation remains in current owners. |
| Former `document_storage/review_artifacts.py` | Historical binary/markup routing and review selection. | Retired with its pipeline; normalization ownership remains in the engine. |
| Former `document_storage/processor.py` | Historical child routing and suffix-MIME persistence. | Retired; shared path/body facts remain distinct and are not a replacement storage pipeline. |
| Former `document_storage/delegation.py` and `candidate_recovery.py` | Historical SGML filename classification and stub-primary recovery. | Retired; external EX-13 evidence may remain, but no runtime action or inferred primary is authorized. |
| Former `document_storage/fixture_operator.py` | Historical suffix MIME fixture metadata. | Retired; suffix-derived MIME remains distinct from body classification. |
| [`engine/document/unpacking/unpacker.py`](../../../../edgar_sec/engine/document/unpacking/unpacker.py) | Markup path predicate contributes to `is_html`; `content_route` populates SGML descriptors. | Preserve the separate path-facts and SGML-filename-facts calls; `is_html` also uses body heuristics. |
| [`engine/forms/normalize.py`](../../../../edgar_sec/engine/forms/normalize.py) | Route values control paper/binary/XML paths; `REPRESENTATION_*` names normalized output. | Map generic facts into the existing engine normalization decisions; do not reuse representation labels as acquisition operations. |

Today, `document_route` classifies every slash-containing path as `RENDERED`, before its
suffix; it does not validate an `xsl*` prefix. `content_route` ignores directories and
classifies SGML filenames by suffix. `mime_type_for_suffix` is also suffix-only: a nested
`.xml` path returns `text/xml` although the SEC rendered response is HTML. These current
semantics are pinned by [`tests/domain/document/test_route.py`](../../../../tests/domain/document/test_route.py).
The path-facts contract retains these distinctions. The retired pipeline's storage and
fetch outcomes are not preserved as runtime behavior. Fetching's root basename is only a
candidate; S6 applies its own allowed-path rule, same-accession URL validation, and
availability/evidence rules.

Suffix MIME is not response MIME or body evidence. The generic classifier likewise does
not choose operation support. S9/S10 work-order policy resolves capabilities from `(family,
target role/type, path_shape, suffix_class, operation)`; each capability declares its
source-input strategy, handler/version, and output kind. Keep `REPRESENTATION_*` as existing engine/storage output
labels, distinct from acquisition operation names.

## Path-facts operation matrix

Capability resolution consumes the shared path facts, not a copy of the suffix table. The
combination `nested + .xml` is distinct from `flat + .xml`; neither the generic facts nor
the policy may infer that every nested path is a valid XSL source without checking the
S6 locator rule.

| Path facts / policy case | Outputs and operations |
|---|---|
| Image, `.fil`, `.zip`, `.eis`, `.paper`, and other binary routes | `raw` only; ignore rendered operations. A paper stub remains raw source, not a text-rendering request. |
| PDF | `raw` only. No PDF text extractor is currently available. |
| Flat `.xml` or `.xsd` | Preserve bytes as `raw` only, without parsing or a render operation. Semantic XML/XBRL parsing remains form-pipeline work. |
| Validated XSL-style nested `.xml` | `raw` preserves the exact selected response. S9/S10 work-order policy may resolve `render_to_txt` for rendered markup. Any `render_to_xml` transform consumes a declared HTML input; it never fetches a sibling `.xml` source. |
| Other `.htm`, `.html`, `.xhtml` | `raw` plus `render_to_txt` when supported by S9/S10 work-order resolution; family/route-specific handlers precede the generic normalizer. |
| `.txt` | `raw` plus `render_to_txt` when supported by S9/S10 work-order resolution; family/route-specific handlers precede the generic normalizer. |
| Other/unknown suffix | `raw` only. Unknown means unclassified, not a renderer category. |

Where approved, `render_to_xml` uses an explicit family-specific transform before an
evidence-backed generic transform over a declared HTML source; it is not a source-path
shortcut or semantic XML parser. S10 work-order resolution owns handler/version and output
availability. Flat XML/XSD remain raw-only. Unsupported operations do not change the raw
source outcome.

### Form 4 boundary

Form 4 has no lazy-index trigger. This plan defines no Form 4 XML output or handler
contract. Any future transform requires a separately reviewed design and implementation;
XML/XSD parsing remains outside acquisition.

## Declarative intent and S9/S10 work-order resolution

Add an optional `acquisition_policy.operations` field to each profile target as declarative
intent. Absence leaves derived-operation selection to the S9/S10 work-order policy; an
explicit list requests those operations. `document_planning` may validate syntax and the
closed operation vocabulary, but must not resolve support, source strategy, handler
IDs/versions, renderer availability, or lazy-index triggers.

The `document_acquisition` work-order policy resolves, per family/role/path-facts/requested
operation:

- acquisition support, source-input strategy, and any family-specific lazy-index trigger
  under S9;
- processing support, renderer availability, handler identity/version, and output kind
  under S10.

An operation counts as supported only after work-order resolution has validated its source
strategy and, when required, its handler ID/version against engine metadata/runtime
registration. S6 intent is not evidence of support or implementation.

The finalized S6 plan bundle is v4, with target relation schema v1 and matcher v2. Its
declarative relations are separately versioned and ordered as follows:

- `target_operations` v1: `(operation_id, target_id, operation, requested, request_mode)`.
  `request_mode` is one of `mandatory_raw`, `profile`, `not_requested`, or
  `default_candidate`.
- `source_requests` v1: `(source_request_id, target_id, source_role, source_origin,
  retrieval_mode, request_url, sequence, canonical_path)`.
- `operation_inputs` v1: `(operation_id, input_ordinal, source_request_id, input_role)`;
  the generic `input_role` is `selected_target_body`.

The manifest carries intent counts named `requested_operation_counts`,
`default_candidate_operation_counts`, `unrequested_operation_counts`, and
`unique_source_request_count`. These relations and counts carry only declarative operation
intent and source-input declarations. They contain no acquisition/processing support,
capability or handler versions, handler IDs, renderer availability, runtime resolutions,
or lazy-trigger policy. S6 intent relations are implemented as declarative-only. S9
work-order resolution owns runtime resolution and may define a distinct
operation schema. A change to declared profile operations or source inputs changes S6 plan
identity; resolution changes are owned and versioned by the S9/S10 work-order policy.

The profile digest includes the canonical requested operation set (canonical order, since
explicit list order is not preference). The S6 plan identity pins declared intent and
source inputs. The S9/S10 work order separately pins locator/resolver policy, processing
policy, and selected handler/version IDs after resolution. The pre-existing
`catalog_direct_selection` plan field is not lazy-trigger authorization; S9 must not use it
to revive `exact_form_with_lazy_index`.
Version the profile schema and plan bundle when these serialized contracts change; migrate
profiles/plans explicitly rather than silently interpreting an old profile under new
operation defaults.

## Family profiles and processing capabilities

Keep the request, family allowance, path strategy, and implementation declarations distinct:

1. **Family/profile intent data** identifies the filing family and declarative operation
   requests. It does not resolve whether acquisition or processing supports a request.
   Keep statutory-filing recognition separate from processing policy. The closed
   `AcquisitionOperation` vocabulary may be shared, but family identity alone does not
   imply renderer availability or a handler binding.
2. **S6 target policy** in `pipelines/document_planning/profiles.py` requests operations
   such as `raw`, `render_to_txt`, or `render_to_xml`. It does not declare that a processor
   implementation exists.
3. **S9/S10 work-order policy** in `pipelines/document_acquisition` resolves requested
   operations against family/role/path facts. S9 owns acquisition support, source inputs,
   and reviewed lazy-index triggers. S10 owns processing support, renderer availability,
   and handler ID/version selection. The S6 intent relations are implemented as
   declarative-only; S9 resolver/work-order implementation remains in progress.
4. **Engine handler metadata/registry** in `engine/document_processing/capabilities.py`
   and `registry.py` declares handler IDs, accepted generic input facts, output kind, and
   implementation version, then binds IDs to code at runtime. S10 work-order resolution
   validates handler metadata and registry parity. Build and validate the runtime registry
   explicitly; do not reuse the mutable
   process-global `engine/forms/plugins/registry.py` pattern or separate cover registry.

Keep any family identity/profile data separate from S9/S10's resolved work-order policy
and from the engine's implementation registry. `document_planning` does not consume engine
handler metadata to resolve support.

### Requested S9/S10 work-order policy

- `raw` is mandatory for every matched target; requested operations add derived
  representations without replacing or suppressing the acquired source.
- `render_to_txt` selects a family/route-specific renderer before the generic
  `engine.forms.normalize.normalize_document` fallback for text and HTML/rendered-markup
  sources. Raw is always preserved. Paper, binary, PDF, flat XML/XSD, ZIP, and unknown
  routes remain raw-only; PDF has no text extractor. Generic XML rendering requires
  separate evidence and registration; a family handler takes precedence. This does not
  specify a Form 4 XML handler or output contract.
- Lazy-index permission is a versioned, form-family-specific trigger in the S9/S10
  work-order policy, based on a reviewed rendered-text pattern. Fail closed when no
  reviewed trigger exists; raw alone is not a trigger. Form 4 has no lazy trigger. This
  policy is not resolved or serialized as support metadata by S6.
- A processor-version bump preserves old results unless the S10 work order explicitly requests
  supersession for selected forms/families, operation, and prior processor/version. The
  new immutable result view retires only matching documents; unrelated forms may retain
  representations produced by the same old version. This selector and selective pruning
  are not implemented.

The S9/S10 work-order policy resolves target requests against family and path facts,
acquisition source strategies, reviewed trigger patterns, and engine handler metadata.
It pins resolved policy/handler versions there, without importing handler callables into
`document_planning`. XML export, if approved, consumes a declared selected HTML input, not
an archive-root XML acquisition strategy. Contract tests verify referenced handler IDs
against metadata and runtime registration at the owning S10 boundary.

Add `tests/domain/forms/common/test_processing.py` and
`tests/domain/forms/families/test_processing_profiles.py` for the domain processing-profile
model and family catalog; extend
`tests/domain/forms/families/test_profiles.py` to pin family declarations; extend
`tests/pipelines/document_planning/test_profiles.py` to pin declarative requested-operation
validation. Add mirrored S9/S10 work-order tests for support, source-input, trigger, and
handler resolution; do not add capability-resolution tests to `document_planning`.
The family modules are `domain/forms/families/annual/profiles.py`,
`quarterly/profiles.py`, and `current/profiles.py`. The proposed [S10 processing decision
tree](../document_acquisition/processing_decision_tree.md) lists 10-K, 10-Q, 8-K, and
20-F as eligible primary forms; 6-K requires an explicitly registered profile. Reconcile
this set with the S10 normative contract before activation. Engine registration alone does
not enable assessment for 40-F, Form 4, or unregistered forms, nor does it authorize S10
assessment or S11 publication.

## Engine processor ownership and API

Put the operation executor in the new package `edgar_sec/engine/document_processing/` as
`AcquisitionProcessor`, separate from the S9 pipeline and the existing
`engine/forms/normalize.py` function. The engine consumes already admitted and verified
source bodies. It does not perform HTTP, resolve SEC URLs, select filing targets, write
pipeline artifacts, or import pipeline work-order/body-reference types. S9/S10 pipeline
coordination owns those responsibilities and calls the engine; this follows the
pure-input/output boundary of `engine/index_pages/parser.py`. The legacy
`document_storage.FilingProcessor` is retired; its selection and persistence behavior are
not reused.

The request must distinguish requested locator, effective selected path/filename, and
verified body identity. It carries target/profile identity, family/role/type,
`DocumentPathFacts`, operation records (request/support state, capability/handler
versions, output kind), and exactly one input per supported requested operation. Every
v1 input links to the target's one shared source request and carries source-asset ID,
locator provenance, selected path, path facts, digest, and size. S10 verifies the
selected file before admitting the shared body to the engine call; raw bytes exist only
in-process and never in work/JSON/worker receipts. An XML-export request identifies its
declared HTML source through its capability; the engine never fetches a sibling `.xml`
source itself.

```python
class AcquisitionProcessor:
    def __init__(self, capabilities: ProcessingCapabilityRegistry) -> None: ...

    def process(
        self,
        request: AcquisitionProcessRequest,
    ) -> AcquisitionProcessResult: ...
```

`AcquisitionProcessResult` is a transient result with one operation outcome per
resolved operation. Raw identity results reference their source input and preserve its
digest/size; export handlers return output digest/size and a staged-output reference,
never a whole output body.
The S10 coordinator performs enabled diagnostics/review separately. The engine processor
does not classify exhibit roles, mutate targets, or issue acquisition actions. The S10
coordinator serializes only metadata results; it does not persist durable
representation payloads. The generic `render_to_txt` path uses
`normalize_document` on eligible text/HTML input, while family-specific handlers override
it. Capability handlers are injected through the validated registry,
so tests can use small byte inputs and fake handlers without HTTP, database writes, disk
staging, or global mutable registrations.

The API's input type is owned by the engine or a domain contract module, never by S9.
`AcquisitionProcessRequest` carries verified source bytes only after the pipeline has
admitted the staged file against its configured maximum and verified the digest/size of
the same bytes passed to the processor. It keeps requested locator provenance distinct
from the effective selected filename/path used for route facts. The generic text-render
path calls `normalize_document` with its bounded input; other handlers follow their
declared input APIs and are never selected by implication.

This concrete signature permits isolated tests for dispatch, raw pass-through,
HTML-to-text, unsupported operations, missing declared HTML inputs, and independent
operation failures. Version 1 has one selected-source input per operation, shared by a
target's handlers; a multi-input handler requires an explicit schema extension. S9
integration tests separately prove that staged bytes were admitted
and that the exact verified bytes passed to this request match the recorded source identity.

The outer S10 API remains pipeline-owned and follows the
[`process_target`](../S10_processing.md) contract:

```python
process_target(
    request: ProcessingRequest,
    *,
    capture_review: bool = False,
    review_staging: ManagedReviewStaging | None = None,
) -> ProcessingResult
```

It validates the request against S9 state, admits/verifies the staged body, builds the
engine request, converts the transient engine result into metadata-only `ProcessingResult`,
and writes the S9 consumption receipt. The current S10 `ProcessingRequest` contains one
`StagedBodyRef`; the multi-source operation model requires an explicit versioned extension.
Do not pass that pipeline-specific ref type into the engine class.

## Logical targets and downstream representations

One S6 target remains one logical document match. Do not create duplicate logical targets
to represent raw, text, and XML variants. S6 plans operations and source requests; it does
not fetch bodies, run transformations, or persist their outputs. The following are
proposed downstream records for the owning acquisition/processing plans, not S6 schemas.
M6/M7 S10 results remain metadata-only; rendered files are transient staged outputs until
a later snapshot/publication phase adopts them. Any durable `StoredRepresentation`
contract belongs to that later phase:

The proposed stable identity, operation-status, source-reuse, representation-to-payload,
and raw-plus-render snapshot contract is in
[`representation_materialization_contract.md`](../document_acquisition/representation_materialization_contract.md).
It is separate from this S6 planning schema and requires agreement before lifecycle
implementation.

Every valid target retains its declared primary source input, and `raw` is the proposed
mandatory baseline representation at the S9/S10 work-order boundary. Requested derived
operations add outputs but never suppress raw. If requested renders are unsupported, S6
still carries the request/source intent and S9/S10 records unsupported resolution. Flat
XML/XSD remains unchanged raw data; any later semantic XML work belongs to a separate form
pipeline.

| Stored concept | Proposed contents |
|---|---|
| `StoredDocument` | Logical accession/index target, form/role/type, pinned policy identity, requested operations, operation outcomes, and aggregate completeness. |
| `AcquiredSource` | One distinct HTTP/bundle source body, with selected locator/path facts, attempts, response/selected digests and sizes, and staged/raw body reference. Multiple operations on the same bytes share this source record. |
| `StoredRepresentation` | A possible later durable model for one operation result: operation ID, output kind, status, source reference(s), output digest/size, handler/version, and stored artifact reference. It is not an M6/M7 S10 artifact contract. |

If `raw` and `render_to_txt` consume the same HTML response, S6 may declare one shared
source-input dependency. S9 work-order resolution determines the actual acquisition
source; S10 binds any approved transform to its declared HTML input. An XML operation does
not imply a second source request.
Any output-byte deduplication and operation provenance belong to the future
processing/storage contract.

The S6 plan should retain one logical target relation and add a deterministic operation
relation (or equivalent child manifest parts). Operations that need distinct source bodies
produce source-request dependencies linked to their operation IDs; the target's primary
source request is always present. Plan counts and manifests reconcile logical targets,
requested operations, ignored operations, and unique source requests separately. This is
planning evidence only; it is not a work-order body receipt or a claim that a source was
fetched.

S6 intent relations are implemented as declarative-only; S9 resolver/work-order
implementation remains in progress. The existing `StagedBodyRef` and
`BodyConsumptionReceipt` are single-body shaped. S6 versions declared profile/operation/
source-input intent only. S9/S10 own acquisition and processing resolution, handoff
receipts, and output records. The
acquisition snapshot is distinct from the S5 inventory snapshot and does not authorize S11
publication.

## Phased ownership and rollout

Phase 0 is a compatibility prerequisite, not a feature phase. Phase 1 planning is the
initial feature phase; subsequent phases have separate layer owners and acceptance gates.

### Implementation summary

**Current status:**

- Shared path facts and target-plan generation exist.
- S6 bundle v4, target schema v1, and matcher v2 are implemented as declarative-only;
  106 explicitly mirrored tests passed.
- S9 resolver/work-order implementation remains in progress. Support, handlers, renderer
  availability, and lazy-index triggers are resolved by `document_acquisition` S9/S10,
  not by `document_planning`.

**Phase 3-7 (Pending):**

- S9 source acquisition pipeline updates
- S10 processing orchestration integration
- Offline integration tests with fixtures
- Engine handler bindings (registry implementations)
- All DocumentRoute consumers migrated to DocumentPathFacts

| Phase | Owner | Scope and exit contract | Status |
|---|---|---|---|
| 0. Shared path facts | `domain/document` and retained engine consumers | Shared path facts are implemented. The former storage pipeline was retired rather than extended; no storage-only policy or fallback is moved into it. No acquisition operations are implemented here. | ✅ Implemented |
| 1. S6 target planning | `pipelines/document_planning` | Generate deterministic target plans and carry declarative requested operations/source inputs. Do not resolve support, handler/version, renderer availability, or lazy-index triggers. Bundle v4, target schema v1, and matcher v2 are implemented as declarative-only; 106 explicitly mirrored tests passed. | ✅ Implemented |
| 2. Engine processing | `engine/document_processing` | Execute only validated S10 work-order inputs. S9/S10 work-order policy resolves support and handler/version metadata before engine dispatch; runtime implementation status is tracked by the S10 plan. | Separate owner |
| 3. S9 source acquisition | `pipelines/document_acquisition` | Existing acquisition baseline remains; resolver/work-order policy implementation is in progress. S9 owns source support and fail-closed family-specific lazy-index triggers, with Form 4 having no trigger. | ◐ In progress |
| 4. S10 processing orchestration (M6) | `pipelines/document_acquisition` | An initial offline `process_target` validates work-order/body identity, verifies staged bytes, records an S9 consumption receipt, and returns transient identity results. Engine renderers, full operation-intent execution, review staging, and coordinator remain incomplete. | ◐ Partial |
| 5a. Offline fixture composition (M7a) | `pipelines/document_acquisition` plus local fixtures | Replay a captured direct-TEXT S9 fixture, pass the actual request/result to terminal projection, and verify receipt, coverage, fingerprint, and staged-output integrity without HTTP. Emit a content-addressed processing-review artifact. Do not clean staged bodies based on the receipt alone; no durable representation payload is written. M3/M4 runner integration is not required. | ✅ Implemented |
| 5b. Runner lifecycle integration (M7b) | `pipelines/document_acquisition` | Verify runner orchestration, retry, sibling failure isolation, and cleanup after explicit discard or publication adoption over fixture-backed processing. Review output remains S7-owned. | ✅ Runner/retry/isolation complete; cleanup remains gated |
| 6a. Fixture/review wiring (M8a) | S10 exhibit-assessment and S7d owners | The shared review console, pipeline artifact writer, and offline fixture handoff are wired; fixture-label workflow and exhibit evaluator remain incomplete. This development work does not require holdout evidence or live SEC access. | ◐ Partial |
| 6b. Holdout acceptance (M8b) | S10 exhibit-assessment owner | Evaluate reviewed, issuer/accession/time-separated fixture labels in diagnostic shadow mode; report per-family errors. This gates accuracy claims; activation additionally requires resolved pack ownership and recorded family acceptance. Neither gates M8a development. | ⏳ Pending |
| 7. Durable acquisition snapshot (M9) | acquisition publication owner | Publish versioned S5/S6/S9/S10 evidence only after its independent acceptance gate. S11 content publication remains separately gated. | ⏳ Pending |

Phase 0 shared path facts are implemented in the retained domain/engine owners. The
former `domain/document/acquisition.py` records and `document_storage` consumers named in
the historical migration audit have been removed with the pipeline. Do not restore their
fetch preference, fallback, or persistence behavior. Retained unpacking and normalization
contracts keep their own mirrored tests; no compatibility shim is required.

S6 target planning generates target plans and carries declarative operation/source-input
requests. It does not resolve family/path support, handler metadata, renderer availability,
or lazy-index triggers; its v4/v1 intent relations are implemented without such resolution
metadata. The S9/S10 work-order policy owns that resolution, and S9 resolver/work-order
implementation remains in progress. Lightweight engine metadata, if used, is consumed by
S10 work-order resolution, not S6. The proposed [S10 processing
decision tree](../document_acquisition/processing_decision_tree.md) lists 10-K, 10-Q, 8-K,
and 20-F as eligible primary forms; 6-K requires an explicitly registered profile. Reconcile
this set with the S10 normative contract before activation. Engine registration alone does
not activate 40-F, Form 4, or unregistered forms for S10 assessment. The JSON profile loader
in `pipelines/document_planning/profiles.py` validates declarative operation requests; it
is not the engine capability registry or a support resolver.

Any lightweight capability metadata is versioned and pinned by the S10 work order after
resolution; do not pin a resolved catalog or selected handler/version in S6. Engine
processing remains separately owned from target planning.
`normalize_document` is the intended generic `render_to_txt` fallback for text and
HTML/rendered-markup sources, with family-specific renderers taking precedence. It is not
an XML, binary, paper, ZIP, or PDF renderer. This export path is not yet wired into S10.
Phase 3 fetches and verifies source bodies.
Phase 4's proposed [S10 processing decision tree](../document_acquisition/processing_decision_tree.md)
and active [S9/S10 plan](../document_acquisition/plan.md) assign `processing_models.py`,
`processing.py`, and eventual coordination to pipeline adapters that validate S9 state,
admit/verify bodies, construct `AcquisitionProcessRequest`, invoke the engine class, and
own metadata results and receipts. They do not reimplement renderers. Proposed S10
work-order resolution uses family/route-specific renderer precedence and the eligible
normalizer fallback; data, graphics, and packages stay on route-specific handling.
`target_type` is provenance, not a content-route override. S10 diagnostics cannot change
the S6 target or S9 state. M6/M7 remain subject to their existing approval gates.

Before implementation, reconcile the proposed multi-operation/source-request model with
the normative [S10 processing contract](../S10_processing.md). The requested policy keeps
flat XML/XSD raw-only without validation, uses the engine normalizer as the generic text
renderer, and applies family-specific handlers before eligible generic ones. Preserve
route-specific memory admission, same-bytes digest verification, metadata-only results,
receipt timing, and S7 review ownership unless their owner versions a change.

## S6 declarative-plan acceptance

- S6 may carry requested operations and declared source inputs; these are intent, not
  resolved support, work orders, handler bindings, or execution outcomes.
- Requested-operation vocabulary and source-input declarations are deterministic and
  canonicalized in plan identity. Explicit list order is not preference.
- Operation/source-input relations do not add logical targets. Existing `target_id`
  derivation includes `plan_id`, so a profile change creates a new plan and corresponding
  target IDs; operation/source-input IDs are deterministic and separately counted.
- Optionality describes document absence only. S6 does not record acquisition or
  processing support/failure, selected handlers, renderer availability, or lazy triggers.
- S6 planning remains offline and deterministic, validates same-accession locators, and
  never probes whether a constructed alternate URL exists.

## Deferred acquisition and processing acceptance

These checks belong to S9/S10 work-order policy, not S6 planning:

- S9 fetches or reuses each eligible source request, verifies response/selected hashes
  and sizes, replays the recorded body, and records per-source outcomes. Acquisition
  failure does not trigger an unplanned URL/operation fallback.
- S10 tests the generic normalizer text path and family-specific overrides on admitted
  bytes, including output digest/size, handler-version fingerprints, and independent
  per-operation failures. PDF extraction remains unavailable; output-fidelity corpus
  tests belong to the renderer gate.
- Lazy-index triggers require a reviewed family-specific pattern and fail closed when no
  pattern is available. Form 4 has no lazy trigger.
- This plan defines no Form 4 XML output or handler contract. Flat XML/XSD remains raw
  input; semantic extraction belongs to a form pipeline.
- Supersession tests prove a plan can retire one form's prior processor version without
  removing another form's result that used the same version. The plan selector and
  selective pruning are not implemented.
- M6/M7 verify metadata-only results and optional S7 review capture; they do not persist
  derived payloads. Only a separately approved M9 schema may add durable
  `StoredRepresentation` byte-alias/deduplication/provenance tests.

## Non-goals

- XML/XSD parsing or ownership fact extraction in acquisition.
- Specifying a Form 4 XML output/handler contract.
- Treating raw, text, and XML operation outputs as duplicate logical SEC documents.
- Arbitrary URL templates, filename guessing, body inspection during S6, or implicit
  network-dependent fallback.
- Fetching acquisition sources or executing renderers/translators from the S6 planner.
- Replacing S5 inventory evidence, enabling S10 content assessment, publishing S11
  artifacts, or reviving `document_storage`.
