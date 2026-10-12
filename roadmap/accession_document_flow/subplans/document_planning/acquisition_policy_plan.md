# S6 Acquisition-Policy Extension Plan

**Status: S6 relation schemas v1 and S9 work/run schemas v2/v3 designed; serialization,
tests, and implementation pending.** The profile request and plan-relation contract is specified in
[S6 `specs.md`](specs.md). The current target-plan bundle does not yet serialize the
operation/source relations described there.

## Goal

For each logical target, let the profile request one or more supported operations over the
acquired file: preserve it raw, render it to text, or produce an XML representation where
that operation is supported. Shared path facts and filing-family capability decide
which operations exist. Explicitly requesting multiple operations means producing each
supported result. S6/S9 v1 binds all supported operations to one target body request.

Document planning remains offline and body-blind. It pins operations, the one primary
body source request, and the operation-to-source link. S9 acquires that input. A separate
processing/engine owner executes supported renderers and stores each result under the
logical document. A handler needing another source or multiple inputs is unsupported
until a versioned S6/S9 source-input extension. XML parsing remains in a separate
form-specific pipeline.

Operation policy controls processing outputs, not retrieval cost or transport mode.
It does not compare child/index, complete-submission, or S1-reported sizes, and it
does not authorize grouping targets into one bundle request. Review-run and fixture
evidence establishes that positive numbered children map to accession-prefixed archive
leaves; an observed inventory link or exact catalog `primaryDocument` can support direct
retrieval. `0001` is not inherently a placeholder. Exact primary `0000.txt`/`.htm` names
remain placeholders and require an observed positive sequence plus pinned bundle URL;
catalog-only targets remain unresolved. An indexed `0001.txt`/`.htm` primary without a
usable prefixed link may use its observed bundle sequence. Other S6 locator selection remains governed by
[`S6_target_plans.md`](../S6_target_plans.md).

## Operation contract

Treat operation names as a closed, versioned vocabulary:

| Operation | Meaning |
|---|---|
| `raw` | Preserve the selected source bytes as a stored representation. The acquisition body remains available for integrity/replay even when this output operation is not selected. |
| `render_to_txt` | Produce a visible-text representation using the file-route renderer, such as HTML cleanup/table projection or PDF text extraction when implemented. |
| `render_to_xml` | Produce an XML representation from the primary `edgar.htm` input only where a family/path-facts capability registers a transform. It does not fetch or pass through an archive-root `.xml` sibling, and it does not perform semantic XML/XBRL parsing. |

The operation capability is resolved for `(filing family, target role/type, path facts)`.
A form family may implement different operations for the same suffix; an extension alone
does not select a statutory family or guarantee that an operation is accurate.

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

The order in the list is not preference order. Execute every listed operation that is
implemented for the selected family and path facts. If an operation is not implemented,
ignore it for execution and record it as unsupported/not applicable; that does not
invalidate the logical target or the other requested operations.

When a target omits `acquisition_policy`, choose the first implemented operation in this
default priority:

```text
render_to_xml > render_to_txt > raw
```

"Implemented" means registered for the resolved family, target role, and path-facts
combination. It does not mean the operation is guaranteed to succeed on a particular body.
At execution time, a fetch or transform failure is recorded against that operation; it does
not silently fall through to a different URL or operation. A profile can explicitly
request multiple operations when it wants raw and rendered representations together.

Keep target `optional` separate from operation support and outcome. It answers whether the
logical document may be absent; it does not mean an unsupported render operation is a
missing document. If all explicitly requested operations are unsupported, S6 records that
status without invalidating the logical target; acquisition and output retention happen in
their owning stages.

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
its existing local disposition (normalize, preserve, or defer); document acquisition maps
them to operations and source strategies. Acquisition can classify `.fil`, `.zip`, `.eis`,
and image suffixes as opaque/raw-only without forcing the current document-storage
processor to change how it treats an unknown suffix.

For an XSL-style `.../*.xml` path, the facts are `archive path + nested + .xml`. The
document-storage policy may continue treating that nested path as rendered markup; the
acquisition capability catalog may expose raw HTML and generic HTML-to-text. A
family-specific XML transform uses the primary `edgar.htm` input when registered; it does
not use a separate archive-root XML source. For flat `.xml`/`.xsd`, the same policy catalog exposes only raw.
No classifier value should encode the set of operations that a form supports. New suffix
facts such as `.zip` or `.fil` must not silently change document-storage behavior.

Do not make `DocumentStorageRoute` and `DocumentAcquisitionRoute` subclasses of one
populated enum. Python enums cannot be extended that way, and one classification may
produce several operation results. Use shared path facts and separate policy mappings:
the historical document-storage pipeline mapped facts to normalize/store decisions;
that pipeline is retired. Acquisition maps facts plus family and target intent to
supported operations and source requests. This keeps the acquisition matrix independent
without duplicating file suffix parsing.

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
not choose operation support. Resolve capabilities from `(family, target role/type,
path_shape, suffix_class, operation)`; each capability declares its source-input strategy,
handler/version, and output kind. Keep `REPRESENTATION_*` as existing engine/storage output
labels, distinct from acquisition operation names.

## Path-facts operation matrix

Capability resolution consumes the shared path facts, not a copy of the suffix table. The
combination `nested + .xml` is distinct from `flat + .xml`; neither the generic facts nor
the policy may infer that every nested path is a valid XSL source without checking the
S6 locator rule.

| Path facts / policy case | Outputs and operations |
|---|---|
| Image, `.fil`, `.zip`, `.eis`, `.paper` | `raw` only; ignore rendered operations. A paper stub remains raw source, not a text-rendering request. |
| PDF | `raw`, or `render_to_txt` when a PDF text extractor is registered for the family/role. Both results may be requested together. |
| Flat `.xml` or `.xsd` | Acquisition preserves bytes as `raw` only and ignores rendered operations. S10 retains its standalone XML well-formedness and DTD/external-entity checks before returning byte-identical `xml_verbatim`; semantic XML/XBRL parsing remains form-pipeline work. |
| Validated XSL-style nested `.xml` | `raw` stores the returned HTML and `render_to_txt` can render it. `render_to_xml` is available only for a registered family transform over the primary `edgar.htm`; it does not fetch a sibling `.xml` source. |
| Other `.htm`, `.html`, `.xhtml` | `raw` and generic `render_to_txt`; a form-specific `render_to_xml` translator is available only when implemented and registered. |
| `.txt` | `raw` and `render_to_txt` when the text renderer is registered. |
| Other/unknown suffix | `raw` only unless an explicit family/role/path capability is registered. Unknown means unclassified, not a renderer category. |

`render_to_xml` is an explicit family-specific transform over the primary `edgar.htm`,
not a source-path shortcut or semantic XML parser. Its handler and output kind are pinned
by the capability catalog. Flat XML/XSD remain raw-only. Unsupported operations are
ignored without changing the raw source outcome.

### Form 4 cases

- If the index path is `xsl*/.../*.xml`, the response is HTML. `raw` can store that HTML
  and `render_to_txt` can produce the generic rendered-text view. `render_to_xml` is
  supported only by an explicitly registered family transform over primary `edgar.htm`.
- Form 4 remains unsupported unless its family registers and validates a `render_to_xml`
  transform. The presence or absence of an XML bundle sibling does not decide support.
- XML/XSD bytes are not parsed by acquisition. Any Form 4 semantic parsing is owned by
  the separate Form 4 pipeline.

## Profile, capability, and plan identity

Add an optional `acquisition_policy.operations` field to each profile target. Absence
means default-priority resolution; an explicit list means multi-select. Validate only the
closed operation vocabulary at profile load, then resolve support from the versioned S6
acquisition capability catalog and the engine's handler metadata. Do not duplicate
file-route/family support tables across
the profile loader, planner, S9, and processing stage.

The S6 acquisition catalog declares, per family/role/path-facts/operation:

- support status and a source-input strategy. Bundle schema v4 supports only the
  target's validated primary source request; a capability requiring another locator is
  not executable until a later, versioned source-input contract exists;
- the handler identity/version (raw uses the built-in identity handler; transformed
  operations use an engine handler);
- which output representation it produces.

An operation counts as implemented only when its source strategy is registered and, when
required, its handler ID/version has a matching engine metadata descriptor. Engine tests
enforce descriptor/runtime-registry parity; S6 reads descriptors, not handler callables.

When default priority is used, the planner resolves it against this catalog and pins the
chosen operation and S6 catalog version. For an explicit set, it pins all requested
operations and records unsupported operations as unsupported, not as successful output.
The bundle's `target_operations` relation has one row per target and closed-vocabulary
operation; `source_requests` identifies the target body's input and `operation_inputs`
links supported requested operations to it. They remain separate Parquet relations, not
columns or rows duplicated onto the target relation. A change to profile operations,
capability resolution, source-path rules, or operation status changes plan identity.

The profile digest includes the canonical operation set (canonical order, since explicit
list order is not preference). The plan identity/manifest pins profile digest, S6 catalog
version, engine capability metadata version, target/operation schema versions, selected
handler/version IDs, and any locator-resolver version.
Version the profile schema and plan bundle when these serialized contracts change; migrate
profiles/plans explicitly rather than silently interpreting an old profile under new
operation defaults.

## Family profiles and processing capabilities

Keep the request, family allowance, path strategy, and implementation declarations distinct:

1. **Family profile data** in `domain/forms/families/*/profiles.py` declares capability
   IDs allowed for that form family. Add a separate frozen, data-only
   `DocumentProcessingProfile` in a domain common module such as
   `domain/forms/common/processing.py`; do not overload `PrimaryReportProfile`, whose
   current contract is statutory-filing recognition. The common module owns the closed
   `AcquisitionOperation` vocabulary and typed capability IDs. Annual, quarterly, and
   current declarations live in their family `profiles.py` modules. Profiles name IDs and
   versions, never Python handler callables. Its minimum fields are family, profile
   version, and allowed capability IDs.
2. **S6 target policy** in `pipelines/document_planning/profiles.py` requests operations
   such as `raw`, `render_to_txt`, or `render_to_xml`. It does not declare that a processor
   implementation exists.
3. **S6 acquisition capability catalog**, proposed in
   `pipelines/document_planning/acquisition_capabilities.py`, resolves family/role/type/path
    facts and requested operation into support status, primary source request, output
    kind, and handler ID/version. A registered `render_to_xml` transform declares the
    primary `edgar.htm` input; the catalog never performs a fetch.
4. **Engine handler metadata/registry** in `engine/document_processing/capabilities.py`
   and `registry.py` declares handler IDs, accepted generic input facts, output kind, and
   implementation version, then binds IDs to code at runtime. Metadata has no handler
   callables or heavy renderer imports, so S6 can resolve it without loading processing
   code. Build and validate the runtime registry explicitly; do not reuse the mutable
   process-global `engine/forms/plugins/registry.py` pattern or separate cover registry.

There is no current family-processing profile aggregator. Add an explicit, immutable
catalog such as `domain/forms/families/processing_profiles.py` to register the annual,
quarterly, and current data declarations. Keep implementation registration separate in
`engine/document_processing/registry.py`.

The planner resolves the S6 catalog entry against the family's allowed capability IDs and
the engine's handler metadata, then pins both catalog and handler versions. The S6 entry
owns family/role/path availability and source selection; the engine descriptor owns only
the transform's accepted input and implementation. Contract tests verify every referenced
handler ID has metadata and a runtime registry entry.

The planner resolves target requests against family-declared IDs, path/source strategies,
and lightweight engine capability descriptors, then pins the result without importing
handler callables. XML export is a registered engine transform over the planned primary
`edgar.htm` source, not an archive-root XML acquisition strategy. This avoids duplicating
support matrices and keeps domain profiles independent of engine imports.

Add `tests/domain/forms/common/test_processing.py` and
`tests/domain/forms/families/test_processing_profiles.py` for the domain processing-profile
model and family catalog; extend
`tests/domain/forms/families/test_profiles.py` to pin family declarations; extend
`tests/pipelines/document_planning/test_profiles.py` to pin requested-operation validation
and add mirrored capability-resolution tests for the S6 acquisition catalog.
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
in-process and never in work/JSON/worker receipts. An XML-export request identifies the
primary `edgar.htm` source through its capability; the engine never fetches a sibling
`.xml` source itself.

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
representation payloads. A durable `render_to_txt` handler must not call
`normalize_document`; existing S10 diagnostic normalization remains separate from the
export representation. Capability handlers are injected through the validated registry,
so tests can use small byte inputs and fake handlers without HTTP, database writes, disk
staging, or global mutable registrations.

The API's input type is owned by the engine or a domain contract module, never by S9.
`AcquisitionProcessRequest` carries verified source bytes only after the pipeline has
admitted the staged file against its configured maximum and verified the digest/size of
the same bytes passed to the processor. It keeps requested locator provenance distinct
from the effective selected filename/path used for route facts. The diagnostic
`normalize_document` helper still accepts `bytes`; export handlers follow their declared
bounded input API, never the filing normalizer by implication.

This concrete signature permits isolated tests for dispatch, raw pass-through,
HTML-to-text, unsupported operations, missing primary `edgar.htm`, and independent
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
not fetch bodies, run transformations, or persist their outputs. The following are proposed
downstream records for the owning acquisition/processing plans, not S6 schemas. M6/M7's
current S10 contract remains metadata-only: normalized text is transient for diagnostics or
explicitly selected review capture, not a durable output payload. Any durable
`StoredRepresentation` contract belongs to a later snapshot/publication phase:

The proposed stable identity, operation-status, source-reuse, representation-to-payload,
and raw-then-render snapshot contract is in
[`representation_materialization_contract.md`](../document_acquisition/representation_materialization_contract.md).
It is separate from this S6 planning schema and requires agreement before lifecycle
implementation.

Every valid target retains its primary source request independently of the `raw` output
operation. `raw` chooses whether the source is also a stored representation; it does not
decide whether the target body is acquired. If requested operations are all unsupported,
S6 still plans the primary source, while recording that no requested output is supported.
S10's XML safety validation is a downstream check, not an acquisition operation or XML
semantic parse.

| Stored concept | Proposed contents |
|---|---|
| `StoredDocument` | Logical accession/index target, form/role/type, pinned policy identity, requested operations, operation outcomes, and aggregate completeness. |
| `AcquiredSource` | One distinct HTTP/bundle source body, with selected locator/path facts, attempts, response/selected digests and sizes, and staged/raw body reference. Multiple operations on the same bytes share this source record. |
| `StoredRepresentation` | A possible later durable model for one operation result: operation ID, output kind, status, source reference(s), output digest/size, handler/version, and stored artifact reference. It is not an M6/M7 S10 artifact contract. |

If `raw` and `render_to_txt` consume the same HTML response, S6 emits one shared source
request dependency. A registered `render_to_xml` handler consumes the planned primary
`edgar.htm` input; it does not imply a second source request. S9 owns source availability.
Any output-byte deduplication and operation provenance belong to the future
processing/storage contract.

The S6 plan should retain one logical target relation and add a deterministic operation
relation (or equivalent child manifest parts). Operations that need distinct source bodies
produce source-request dependencies linked to their operation IDs; the target's primary
source request is always present. Plan counts and manifests reconcile logical targets,
requested operations, ignored operations, and unique source requests separately. This is
planning evidence only; it is not a work-order body receipt or a claim that a source was
fetched.

The current S6 plan and S9 work order store one target with one selected body; current
`StagedBodyRef` and `BodyConsumptionReceipt` are also single-body shaped. S6 versions only
its profile/operation/source-request plan contract. Any later expansion of acquisition
state, handoff receipts, or processing output records belongs to those owning plans. The
acquisition snapshot is distinct from the S5 inventory snapshot and does not authorize S11
publication.

## Phased ownership and rollout

Phase 0 is a compatibility prerequisite, not a feature phase. Phase 1 planning is the
initial feature phase; subsequent phases have separate layer owners and acceptance gates.

### Implementation summary

**Phase 0-2 (Completed):**

- `edgar_sec/domain/document/path_facts.py` - DocumentPathFacts, DocumentPathShape, DocumentSuffixClass
- `edgar_sec/domain/document/route.py` - Updated with backward compatibility
- `edgar_sec/domain/forms/common/processing.py` - AcquisitionOperation enum, DocumentProcessingProfile
- `edgar_sec/domain/forms/families/annual/processing.py` - Annual family profile
- `edgar_sec/domain/forms/families/quarterly/processing.py` - Quarterly family profile
- `edgar_sec/domain/forms/families/current/processing.py` - Current family profile
- `edgar_sec/domain/forms/families/processing_profiles.py` - Family catalog
- `edgar_sec/pipelines/document_planning/acquisition_capabilities.py` - S6 catalog
- `edgar_sec/pipelines/document_planning/profiles.py` - Updated with acquisition_policy field
- `edgar_sec/engine/document_processing/` - AcquisitionProcessor, registry, capabilities
- Test files under `tests/domain/document/`, `tests/domain/forms/`, `tests/pipelines/document_planning/`

**Phase 3-7 (Pending):**

- S9 source acquisition pipeline updates
- S10 processing orchestration integration
- Offline integration tests with fixtures
- Engine handler bindings (registry implementations)
- All DocumentRoute consumers migrated to DocumentPathFacts

| Phase | Owner | Scope and exit contract | Status |
|---|---|---|---|
| 0. Shared path facts | `domain/document` and retained engine consumers | Shared path facts are implemented. The former storage pipeline was retired rather than extended; no storage-only policy or fallback is moved into it. No acquisition operations are implemented here. | ✅ Implemented |
| 1. S6 planning (initial) | `pipelines/document_planning`, domain family profiles, and engine capability metadata | Add family capability IDs, target operation requests, and a lightweight versioned metadata catalog; publish deterministic operation/source-request rows. Planning stays offline/body-blind and imports no handler callables. | ✅ Implemented |
| 2. Engine processor proposal | Retired `engine/document_processing` proposal | The proposed `AcquisitionProcessor` is not a current runtime owner. S10 currently has an initial offline `process_target` in the acquisition pipeline; it does not invoke engine renderers. | Retired proposal |
| 3. S9 source acquisition | `pipelines/document_acquisition` | Direct/bundle acquisition, exact-form lazy-index selection, work-order state, retry, staging, and run CLI are implemented. Family-aware HTML evaluation is deferred; bundle/lazy-index response-group fixture retention is opt-in. | ◐ Partial |
| 4. S10 processing orchestration (M6) | `pipelines/document_acquisition` | An initial offline `process_target` validates work-order/body identity, verifies staged bytes, records an S9 consumption receipt, and returns transient identity results. Engine renderers, full operation-intent execution, review staging, and coordinator remain incomplete. | ◐ Partial |
| 5a. Offline fixture composition (M7a) | `pipelines/document_acquisition` plus local fixtures | Replay a captured direct-TEXT S9 fixture, pass the actual request/result to terminal projection, and verify receipt, coverage, fingerprint, and staged-output integrity without HTTP. Emit a content-addressed processing-review artifact. Do not clean staged bodies based on the receipt alone; no durable representation payload is written. M3/M4 runner integration is not required. | ✅ Implemented |
| 5b. Runner lifecycle integration (M7b) | `pipelines/document_acquisition` | Verify runner orchestration, retry, sibling failure isolation, and cleanup after explicit discard or publication adoption over fixture-backed processing. Review output remains S7-owned. | ⏳ Pending |
| 6a. Fixture/review wiring (M8a) | S10 exhibit-assessment and S7d owners | The shared review console, pipeline artifact writer, and offline fixture handoff are wired; fixture-label workflow and exhibit evaluator remain incomplete. This development work does not require holdout evidence or live SEC access. | ◐ Partial |
| 6b. Holdout acceptance (M8b) | S10 exhibit-assessment owner | Evaluate reviewed, issuer/accession/time-separated fixture labels in diagnostic shadow mode; report per-family errors. This gates accuracy claims; activation additionally requires resolved pack ownership and recorded family acceptance. Neither gates M8a development. | ⏳ Pending |
| 7. Durable acquisition snapshot (M9) | acquisition publication owner | Publish versioned S5/S6/S9/S10 evidence only after its independent acceptance gate. S11 content publication remains separately gated. | ⏳ Pending |

Phase 0 shared path facts are implemented in the retained domain/engine owners. The
former `domain/document/acquisition.py` records and `document_storage` consumers named in
the historical migration audit have been removed with the pipeline. Do not restore their
fetch preference, fallback, or persistence behavior. Retained unpacking and normalization
contracts keep their own mirrored tests; no compatibility shim is required.

Phase 1 adds a separate `DocumentProcessingProfile` data contract and family catalog,
declared in the annual, quarterly, and current `profiles.py` modules. It also adds the S6
catalog in `edgar_sec/pipelines/document_planning/acquisition_capabilities.py` and the
lightweight engine metadata/package in `edgar_sec/engine/document_processing/capabilities.py`.
The proposed [S10 processing
decision tree](../document_acquisition/processing_decision_tree.md) lists 10-K, 10-Q, 8-K,
and 20-F as eligible primary forms; 6-K requires an explicitly registered profile. Reconcile
this set with the S10 normative contract before activation. Engine registration alone does
not activate 40-F, Form 4, or unregistered forms for S10 assessment. The JSON profile loader
in `pipelines/document_planning/profiles.py` validates target operation requests; it is not
the engine capability registry.

Phase 1 adds the lightweight capability metadata and pins its catalog version in S6.
Phase 1 adds the `engine/document_processing` package README and engine layout entry with
its metadata module. Phase 2 adds `models.py`, `registry.py`, and `processor.py`, plus
mirrored `test_models.py`, `test_registry.py`, and `test_processor.py` under
`tests/engine/document_processing/` (with package `__init__.py`); Phase 1 owns the mirrored
`test_capabilities.py` catalog contract test.
`normalize_document` remains the existing form-normalization API for S10 diagnostics; a
durable `render_to_txt` handler is a separate export implementation and must not call it.
Phase 3 fetches and verifies source bodies.
Phase 4 follows the proposed [S10 processing decision tree](../document_acquisition/processing_decision_tree.md)
and active [S9/S10 plan](../document_acquisition/plan.md): M6's `processing_models.py`,
`processing.py`, and per-run coordinator are pipeline adapters that validate S9 state,
admit/verify bodies, construct `AcquisitionProcessRequest`, invoke the engine class, and
own metadata results and receipts. They do not reimplement renderers. A primary uses its
filing-form normalization profile; a standalone exhibit uses the generic no-cover profile;
data, graphics, and packages stay on route-specific handling. `target_type` is provenance,
not a content-route override. The S10 coordinator may run enabled exhibit-role diagnostics
on the transient text result, but cannot change the S6 target or S9 state. M6/M7 remain
subject to their existing approval gates.

Before implementation, reconcile the proposed multi-operation/source-request model with
the normative [S10 processing contract](../S10_processing.md), which currently describes
single-body processing and flat-XML validation. Preserve route-specific memory admission,
same-bytes digest verification, metadata-only results, receipt timing, and S7 review
ownership unless their owner versions a change. The proposed processing decision tree's
opaque XML pass-through and the normative flat-XML validation step must be resolved rather
than silently mixed.

## S6 planning acceptance tests

- Explicit `operations=[raw, render_to_txt, render_to_xml]` plans every supported
  operation for the selected form/role/path-facts combination and records unsupported ones
  as ignored without invalidating other operations or the target.
- An omitted operation policy selects the highest-priority implemented operation in the
  order `render_to_xml`, `render_to_txt`, `raw`; the selected capability version is pinned.
- The matrix distinguishes flat `.xml`/`.xsd` raw-only from a validated nested XSL `.xml`.
  `render_to_xml` is planned only for a registered family transform over the primary
  `edgar.htm`, never by constructing an archive-root XML sibling request. No body is
  fetched and no output is produced by S6.
- For HTML-only Form 4 targets, the plan does not fabricate an XML source. It records XML
  translation as unsupported until a form-specific capability is registered; it does not
  execute or validate a translator.
- If every requested operation is unsupported, the logical target and its primary source
  request remain planned while the unsupported operation statuses are retained.
- Raw, text, and XML-export operations share the primary source request when the family
  capability identifies that source. S6 validates locators but does not fetch them.
- `.fil`, `.zip`, `.eis`, images, and `.paper` are raw-only; flat `.xml`/`.xsd` are raw-only;
  PDF may additionally produce extracted text. Unsupported renders do not suppress raw.
- Phase 0 path facts preserve domain, engine, and document-storage outcomes. Phase 1
  capability resolution can plan multiple outputs for one source class without overloading
  the shared classifier with operation support.
- Operation rows do not add logical targets. Existing `target_id` derivation includes
  `plan_id`, so a profile/policy change creates a new plan and corresponding target IDs;
  operation/source-request IDs are deterministic and separately counted within each plan.
  Optionality describes document absence only; S6 does not record runtime operation
  failures.
- S6 planning is offline and deterministic, validates same-accession locators, and never
  probes whether a constructed alternate URL exists.

## Deferred acquisition and processing acceptance

These checks belong to S9 acquisition and the engine/processing owner, not S6 planning:

- S9 fetches or reuses each eligible source request, verifies response/selected hashes
  and sizes, replays the recorded body, and records per-source outcomes. Acquisition
  failure does not trigger an unplanned URL/operation fallback.
- The engine processor tests generic HTML-to-text and PDF extraction on admitted byte
  inputs, including output digest/size, handler-version fingerprints, and independent
  per-operation failures. Output-fidelity corpus tests belong to the engine/renderer gate.
- A Form 4 HTML-to-XML translator requires separate implementation and validation. XML/XSD
  parsing and semantic extraction remain form-pipeline behavior, not acquisition behavior.
- M6/M7 verify metadata-only results and optional S7 review capture; they do not persist
  derived payloads. Only a separately approved M9 schema may add durable
  `StoredRepresentation` byte-alias/deduplication/provenance tests.

## Non-goals

- XML/XSD parsing or ownership fact extraction in acquisition.
- Implementing or validating a Form 4 HTML-to-XML translator.
- Treating raw, text, and XML operation outputs as duplicate logical SEC documents.
- Arbitrary URL templates, filename guessing, body inspection during S6, or implicit
  network-dependent fallback.
- Fetching acquisition sources or executing renderers/translators from the S6 planner.
- Replacing S5 inventory evidence, enabling S10 content assessment, publishing S11
  artifacts, or reviving `document_storage`.
