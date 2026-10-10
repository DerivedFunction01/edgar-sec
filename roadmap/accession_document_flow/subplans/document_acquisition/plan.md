# S9 Document Acquisition: Implementation Plan

This plan tracks the local S9 acquisition implementation and its remaining lifecycle
gates. S9 projection, bounded transport, exact bundle extraction, run state, and the
live acquisition runner now exist; S10 processing and S11 durable publication remain
unimplemented. Acquisition distribution and legacy package removal remain separate.

## 1. Implementation checklist

Status markers are maintained against tracked code and focused offline tests:
`[x]` complete, `[~]` partially complete, `[ ]` not complete or gated.

- [x] **M0 — API seams:** shared transport, parser, and pipeline ownership contracts
  are established.
- [x] **M1 — S9 contracts/configuration:** paths, schemas, models, work-order
  contracts, and the finite `acquisition.max_response_bytes` setting are registered;
  run and fixture capture accept CLI overrides above environment/config/defaults.
- [x] **M2A — SEC streaming:** file-backed HTTP and body-free broker streaming are
  implemented and tested.
- [x] **M2B — SGML extraction:** bounded exact-sequence extraction is implemented and
  tested.
- [x] **M2C — Projection/run state:** validated work-order projection, append-only
  attempts, target state, and locking are implemented.
- [x] **M2D — Fixture substrate:** compressed append-only storage, validated read-only
  discovery, direct/bodyless-failure capture, retained bundle/lazy-index response-group
  capture, and verified local replay are implemented. Raw response evidence retention
  is opt-in and defaults off; bundle/lazy-index capture requires it.
- [ ] **M2E — Trace opt-out:** S10's `capture_stage_trace=False` normalizer option is
  not implemented.
- [~] **M3 — Acquisition runner:** direct and bundle acquisition, exact-form lazy-index
  selection, multi-request provenance, and the CLI `run` path are implemented. The
  catalog-direct exact-form selector compares primary bundle `<TYPE>` to the pinned
  form using strict ASCII equality; mismatch or unverifiable type enters lazy index
  recovery. Other selectors do not screen the submitted primary. The direct catalog
  screen remains unverifiable, and family-aware HTML evaluation is deferred.
- [x] **M4 — Fixture/interactive surfaces:** CLI `project`, `status`, `run`, and
  fixture `create`, `capture`, `list`, and `replay` are wired; the operator delegates
  these actions and confirms live acquisition, evidence capture, and replay output.
  An integrated lazy-index fixture round trip and exact-attempt retry refusal are
  tested. Bundle and lazy-index groups require opt-in `--retain-response-evidence`.
  Processing, review, and snapshot tracks remain gated or incomplete.
- [x] **M5 — Offline S9 acceptance:** a pinned-plan fixture replay commits run state;
  status inspects it, and a fake consumer verifies the selected-body reference and
  immutable receipt. Runner cleanup retains the body; receipts do not authorize cleanup.
- [ ] **M6 — S10 processing:** per-target normalization, processing results, and
  body-consumption receipts are not implemented.
- [ ] **M7 — S9/S10 fixture integration:** end-to-end fixture-driven processing is not
  implemented.
- [ ] **M8 — Evidence/identity follow-up:** the historical mismatch fixtures are
  documented in [historical mismatch cases](historical_mismatch_cases.md), but fixture
  execution and family-aware cover diagnostics remain deferred and must reuse existing
  family evidence rather than add duplicate vocabularies. No tracked sanitized pre-2011
  fixture joins submission metadata, envelope/index evidence, and cover text; do not
  fabricate a corpus-backed claim from the partial existing fixtures.
- [ ] **M9 — S11 publication:** durable snapshot publication remains gated on
  representative S9/S10 evidence and explicit approval.

## 2. Readiness and parallelization

The current S9 runner is local and serial; SEC rate limits remain host-local, and
cross-host coordination is out of scope. S9 accepts a validated S6 bundle, but a full
S5-to-S6-to-S9 vertical claim remains separate from the pinned-plan tests. S10's trace
opt-out and processing service are prerequisites for the planned S9-to-S10 integration.
The approval-gated Parquet/DAG publication contract is specified in
[the acquisition lifecycle](lifecycle.md), but no S11 publisher exists. S0 historical
parser acceptance and live operational rollout gates remain in force.

### Dependency graph

```mermaid
flowchart TD
    M0["M0: Freeze shared API seams and ownership"]
    M1["M1: S9 paths, schemas, models, settings"]
    HTTP["Track A: SEC file streaming in sec_http + broker"]
    SGML["Track B: Bounded SGML sequence extraction in engine"]
    PROJECT["Track C1: Validate S6 bundle + project immutable work order"]
    STATE["Track C2: SQLite state, attempts, locks, status"]
    FIXSTORE["Track D1: Fixture storage and read-only listing"]
    RUN["M3: Local runner integrates work order, state, HTTP, SGML"]
    FIX["M4: Capture/replay integrates staged run bodies"]
    CLI["M4: CLI, operator, launcher and package docs"]
    NTRACE["Track E: S10 no-stage-trace normalizer option"]
    PROCESS["M6: S10 process_target and receipt-gated output"]
    S9GATE["M5: Offline S9 lifecycle verification"]
    GATE["M7: Offline S9-to-S10 fixture integration"]
    TAXON["M8: Evidence corpus and diagnostic exhibit assessment"]
    PUB["M9: Acquisition Parquet snapshot publication"]
    UPSTREAM["S5/S6 contracts implemented for inventory-backed vertical run"]

    M0 --> M1
    M0 --> HTTP
    M0 --> SGML
    M1 --> PROJECT
    M1 --> STATE
    M1 --> FIXSTORE
    M1 --> PROCESS
    NTRACE --> PROCESS
    PROJECT --> RUN
    STATE --> RUN
    HTTP --> RUN
    SGML --> RUN
    FIXSTORE --> FIX
    RUN --> FIX
    PROCESS --> GATE
    RUN --> S9GATE
    FIX --> S9GATE
    PROJECT --> CLI
    STATE --> CLI
    RUN --> CLI
    FIX --> CLI
    CLI --> GATE
    RUN --> GATE
    FIX --> GATE
    FIX --> TAXON
    PROCESS --> TAXON
    GATE --> PUB
    TAXON -. "processing versions pinned; diagnostics remain non-authoritative" .-> PUB
    UPSTREAM -. "needed for full inventory-backed vertical run" .-> GATE
```

### Delegation boundaries

1. **Track A and Track B can start independently after M0.** Track A owns SEC transport
   and broker RPC changes only. Track B owns bounded envelope parsing only. Neither
   imports or depends on the S9 pipeline package.
2. **M1 is a single-owner integration contract.** One implementer establishes S9
   `paths.py`, `schemas.py`, `models.py`, `arrow_schemas.py`, and setting registration
   before command-service work is delegated. This prevents divergent handoff and
   persisted-row definitions.
3. **Projector, state persistence, and fixture storage can proceed concurrently after
   M1.** Projector owns S6 bundle validation and immutable work-order creation; state
   owns SQLite transitions and locks; fixture storage owns fixture manifest/SQLite
   BLOB persistence. Each consumes M1's records and paths rather than defining local
   copies.
4. **The live/local runner is an integration track.** It starts after the projector
   and state contracts are available and integrates the merged Track A and Track B
   APIs. Fixture replay uses the same extraction boundary without opening HTTP.
5. **The S10 no-trace normalizer change is independently delegatable.** It belongs to
   `engine.forms.normalize`, not S9; it can proceed from the S10 contract and its own
   tests while S9 services are being built.
6. **CLI/operator work follows service contracts.** It delegates to the same project,
   status, run, and fixture services; it does not duplicate planning, retry, or fixture
   behavior.
7. **The S10 body-processing service can start after M1 and M2E.** It processes
   fixture-backed `StagedBodyRef` values without waiting for the live S9 runner. The
   end-to-end fixture gate waits for both services; taxonomy rules wait for a labeled
   corpus.

## 3. Milestone breakdown

### M0: Freeze transport and parser seams

**Goal:** Resolve only the cross-layer interface details needed for independent
implementation; do not reopen settled S9 behavior.

#### Decisions to pin

- Add a file-backed SEC operation alongside, not in place of, `get_bytes()`. Preserve
  shared pacing, retry/failure-ledger policy, injected `session_factory`, and typed
  transport failures. Streamed bodies bypass the current byte-returning cache until a
  file-backed cache exists.
- Define how the broker request identifies a destination without accepting an
  unconfined worker-supplied path. The S9 runner owns generated staging paths; the
  broker boundary returns path/metadata handles and never sends body bytes over IPC.
- Keep every redirect check in the shared HTTP path and validate HTTPS, SEC archive
  host, and accession-directory scope before following it.
- Put `extract_bundle_sequence(source_path, destination, selector, ...)` in the engine
  unpacking package. It accepts primitive selectors and paths, returns typed metadata
  or failure, and imports no S9 models.

#### Exit criteria

- The `StreamedResponse`/typed failure shape, cancellation and cleanup behavior, broker
  staging ownership, and parser result/failure mapping are agreed against
  [bounded transport](run/transport.md) and [exact extraction](run/extraction.md).
- No changes weaken the existing byte-fetch API or the shared SEC rate limiter.

### M1: Shared S9 contracts and configuration (`Layer 4`)

**Goal:** Create the one source of truth all command and fixture services consume.

#### Target modules

- `edgar_sec/pipelines/document_acquisition/__init__.py`
- `edgar_sec/pipelines/document_acquisition/paths.py`
- `edgar_sec/pipelines/document_acquisition/schemas.py`
- `edgar_sec/pipelines/document_acquisition/models.py`
- `edgar_sec/pipelines/document_acquisition/arrow_schemas.py`
- S9-specific entry in `edgar_sec/foundation/runtime/settings/`
- `edgar_sec/pipelines/document_acquisition/README.md`
- Mirrored source and test package `__init__.py` files and focused tests under
  `tests/pipelines/document_acquisition/`

#### Contract owners

- `paths.py` owns validated run, staging, fixture, and review paths and delegates
  fixture layout to the shared fixture resolver.
- `schemas.py` owns lightweight run manifests, `StagedBodyRef`, and
  `BodyConsumptionReceipt`; `arrow_schemas.py` owns target/work-order Parquet schemas
  and imports S6's leaf schema directly.
- `models.py` owns immutable target, attempt, outcome, policy, lock, and report values.
- Settings register the finite response ceiling through the modular settings registry;
  worker requests remain optional upper bounds below the derived resource ceiling.

#### Verification criteria

- Safe-ID, digest, containment, symlink, and wrong-file-kind cases refuse without
  creating run or fixture state.
- S9 accepts only the pinned S6 schema versions and the documented catalog-direct
  null-inventory primary case.
- JSON/Arrow schema versions and target nullability match the published S6 contract;
  no `__init__.py` re-exports child symbols.

### M2A: Bounded SEC response streaming (`Layer 2`, Track A)

**Goal:** Add the shared brokered file-stream operation required by S9 without
materializing an HTTP response or changing existing byte consumers.

#### Target modules

- `edgar_sec/infra/sec_http/client.py` and, if needed, a focused sibling module
- `edgar_sec/infra/broker/sec_broker.py` and its client/daemon seam
- `edgar_sec/infra/sec_http/README.md` and `edgar_sec/infra/broker/README.md`
- Mirrored tests under `tests/infra/sec_http/` and `tests/infra/broker/`

#### Verification criteria

- Incremental response decoding, byte counting, and hashing honor the finite ceiling;
  partial, empty, oversized, failed, or cancelled transfers leave no adopted file.
- Redirects are rejected before an out-of-scope request is sent. Direct 404 remains
  `http_not_found`, not `not_filed`.
- Cache hits do not route through the buffered cache API; file-backed cache support is
  not required for this milestone.
- The shared broker still owns pacing, retry classification, and failure accounting;
  body bytes never enter broker RPC frames.
- Tests cover chunked/gzip responses, exact and exceeded bounds, `Retry-After`, timeout,
  redirect scope, cancellation cleanup, and digest parity using injected sessions.

### M2B: Bounded SGML sequence extraction (`Layer 3`, Track B)

**Goal:** Extract one S6-pinned sequence from a large legacy submission while preserving
the selected source bytes exactly.

#### Target modules

- A focused implementation in `edgar_sec/engine/document/unpacking/` (proposed
  `streaming.py`)
- `edgar_sec/engine/document/unpacking/README.md` and, if required, its parent package
  README layout
- `tests/engine/document/unpacking/test_streaming.py`

#### Verification criteria

- Chunk boundaries may split any delimiter or header field; the scanner stays bounded
  and does not materialize unselected document spans.
- One exact positive sequence is selected. A complete valid envelope without it maps
  to `sequence_not_found`; duplicate matches, malformed structure, invalid lengths,
  truncation, and source digest mismatch return typed failures and no adopted output.
- `<TEXT>` bytes are not decoded, trimmed, newline-normalized, or inferred from target
  type/filename. Small fixtures match the existing bytes parser where their contracts
  overlap.

### M2C: Projector and run-state substrate (`Layer 4`, Track C)

**Goal:** Implement offline plan projection and mutable state independently of HTTP.

#### Target modules

- `work_order.py` and `projector.py`
- `run_state.py` and `run_persistence.py`
- `commands/project.py` and `commands/status.py`
- Mirrored `tests/pipelines/document_acquisition/` tests for work-order validation,
  projection, SQLite persistence, locking, and status

#### Verification criteria

- Projection validates the complete S6 bundle, each declared part, digest, row count,
  schema, locator, and source-pin relationship before writing a deterministic run.
- Every S6 row remains in the work order. Only matched supported locators execute;
  skipped rows have stable reasons and cannot be scheduled.
- Identical projection reuses a validated run; corrupted or divergent prior state
  fails closed without overwrite.
- SQLite writes use bound values and transactions. Attempt history is append-only;
  each committed target outcome agrees with verified body files and typed retry data.
- Run locks are token-owned; status is read-only and derives progress from validated
  artifacts and state.

### M2D: Fixture store substrate (`Layer 4`, Track D)

**Goal:** Establish append-only fixture evidence storage while runner implementation
proceeds, using M1 schemas and paths.

#### Target modules

- `fixtures/` package for SQLite schema, BLOB lifecycle, fixture manifests, and models
- Fixture storage tests under `tests/pipelines/document_acquisition/fixtures/`
- `edgar_sec/pipelines/document_acquisition/fixtures/README.md` if implemented as a
  separate package under repository package documentation rules

#### Verification criteria

- Exact source response bytes are stored as SQLite BLOBs with verified digest and size;
  metadata/manifests remain descriptors, not body copies.
- Captures append and preserve earlier evidence; fixture paths are confined and schema
  versions agree between manifest and SQLite.
- Listing is read-only and does not hash every stored body. Replay verifies integrity
  before returning a managed staged-body reference.

### M2E: S10 no-stage-trace normalizer option (`Layer 3`)

**Owner:** S10 / `engine.forms.normalize`, not the S9 pipeline. This work can proceed
in parallel but is not a prerequisite for the S9 runner.

**Goal:** Add the contract's opt-out for stage-trace copies so downstream processing
does not retain repeated full-text representations unnecessarily.

#### Target modules

- `edgar_sec/engine/forms/normalize.py`
- Its mirrored normalizer tests under `tests/engine/forms/`
- `edgar_sec/engine/forms/README.md` if the package contract/layout changes

#### Verification criteria

- Existing callers keep the current trace behavior by default.
- `capture_stage_trace=False` returns equivalent normalization output and an empty
  trace; mirrored tests cover both modes and guard processor-visible results.

### M3: Local acquisition runner and lifecycle integration

**Dependencies:** M1, M2A, M2B, and M2C.

**Goal:** Run only projected executable targets through one local SEC broker, commit
each outcome safely, and support restart after interruption.

#### Target modules

- `runner.py`, `commands/run.py`, and common transport/extraction adapters in
  `edgar_sec/pipelines/document_acquisition/`
- Resource-bounded target scheduling, run locking, cancellation, and selected-body
  handoff to the S10 contract
- Mirrored runner and command tests under `tests/pipelines/document_acquisition/`

#### Verification criteria

- No-work runs create no network client. Only pending targets and explicitly selected
  retryable failures are scheduled; skipped and terminal targets make no request.
- Direct 404 is failed; `not_filed` is reserved for a complete valid bundle lacking
  the exact requested sequence or an optional target whose selector-authorized lazy
  lookup finds no expected-form row. A required target in that latter case is
  `required_missing`; duplicates are ambiguous.
- `submitted_primary` performs no type screen/index request. Lazy recovery tests cover
  ASCII `<TYPE>` mismatch, HTML cover-unverifiable trigger, positive-cover no-lookup,
  unique/no/duplicate type rows, failed index fetch/parse, and exact direct/bundle
  acquisition of the selected slot. Every recovery records the versioned resolution
  and keeps the original sequence-1 attempt separate from the S10 body assignment.
- Worker and in-flight body counts are resource-derived and bounded. Workers exchange
  paths and typed metadata, never full payload bytes.
- Completed target commits survive interruption; partial files are cleaned; resume
  validates prior state and never repeats an acquired target.
- A verified selected-body path/digest/size is exposed through `StagedBodyRef`.
  S10's matching `BodyConsumptionReceipt` proves consumption but cleanup also waits
  for S11 payload-Parquet adoption or an explicit discard; tests use a fake consumer
  until S10/S11 are implemented.

#### Historical form-mismatch fixtures

Keep these identity edge cases in pre-2011 fixtures. Distinguish outer submission and
document metadata disagreements from cover text that contradicts otherwise matching
metadata. The implemented SGML check compares extracted `<TYPE>` with the pinned form
and allows lazy index recovery only for the exact-form catalog-direct selector. There
is no family-aware HTML/cover evaluator; cover evidence must not replace the pinned S6
form or exact index `document_type`. Detailed future cases are in
[historical mismatch cases](historical_mismatch_cases.md).

- Cover an old catalog-direct 8-K whose outer submission declares 8-K but whose
  sequence-1 primary in the SGML `.txt` envelope declares `<TYPE>10-K`, with a unique
  exact 8-K index row at another direct or bundle slot. Screening triggers one lookup
  and selects only that indexed 8-K row.
- Cover a text-only inversion where submission metadata, `<TYPE>`, and the index identify
  an 8-K but the HTML or flat `.txt` cover says 10-K. Keep this separate from SGML
  metadata screening; a future cover diagnostic must not relabel the body or claim that
  index selection reconciled the visible-text discrepancy.
- Cover an entirely misfiled annual report: the pinned form and index identify an 8-K,
  no 10-K index row exists, but the body contains annual-report wording or annual-family
  checkmarks. A future family-aware screen should recognize the likely content mismatch
  using existing annual evidence; generic cover-boundary detection is not form evidence.
  S9 must not invent a 10-K slot: retain the index-evidenced missing outcome for the
  pinned target until an explicitly approved identity-evaluator follow-up defines more.
- Do not add post-2011 metadata-mismatch checks as a required S9 path: modern EDGAR
  submission validation is expected to reject the outer-form/primary-`<TYPE>` mismatch.
  The historical fixtures exercise compatibility with accepted old filings, not a
  second form taxonomy or a new cover vocabulary.

#### Deferred identity-evaluator follow-up

The current family taxonomies and evidence may distinguish an annual report from an
8-K shell even when index metadata has no 10-K row. A future evaluator must reuse that
existing evidence and vocabularies rather than add parallel phrase/checkmark lists. It
must remain a diagnostic unless a separately approved resolution contract explains
how an absent exact-form index row may be handled; cover-boundary location alone cannot
establish statutory form or choose a replacement slot.

Until that evaluator exists, S9 trusts the pinned S6 form for the request and observed
index `document_type` for slot selection. If S6 asks for an 8-K and the index has an
8-K row, the annual-report body can still be acquired as that row; S9 does not infer a
10-K from its text. If S6 asks for a required 10-K and no exact 10-K index row exists,
the result remains `required_missing` rather than selecting an 8-K row by content.

The approval-gated S11 snapshot should retain a sparse, versioned content-identity
finding separately from `slot_types`: bind the S6 expected form and selected physical
slot to the body digest, suspected content family/form, evidence references, and
evaluator fingerprint. This records a diagnostic, not a statutory-type assertion, and
must not overwrite catalog or index metadata. A later plan for the same accession will
repeat the current metadata-based selection unless a future explicit planning/review
contract surfaces the prior finding; the finding alone must not silently rewrite S6.

### M4: Fixture capture, replay, and local CLI/operator

**Dependencies:** M2C, M2D, and M3; fixture replay also requires M2B for bundle cases.
CLI service wiring can be prepared in parallel with M3 only after stable service
signatures are available; final operator tests require the merged services.

#### Target modules

- Fixture capture/list/replay services and `commands/fixture.py`
- `cli.py`, `operator.py`, command registration in `run.py`
- `edgar_sec/pipelines/document_acquisition/README.md`, pipeline/layer README tables,
  and mirrored tests under `tests/pipelines/document_acquisition/`

#### Verification criteria

- Fixture replay makes zero HTTP calls and returns bytes/digests identical to captured
  source or re-derived selected sequence.
- Capture is explicit promotion of an already acquired staged response, never a network
  operation. It does not publish payload snapshots.
- CLI and operator call the same service functions. Interactive run asks for separate,
  default-no network and retry confirmations; cancelled actions make no request.
- The launcher replaces the legacy `document_storage` route with the new S9 surface
  only when the local commands pass their focused tests. The legacy package itself is
  not deleted here.
- No distribution command/menu is registered in this local milestone.

### M5: Offline S9 acceptance gate

**Dependencies:** M3 and M4. A full inventory-backed vertical case also requires the
S5 relation-schema owner move and the S6 profile/target-plan implementation; neither
blocks S9 unit tests or use of a valid pinned S6 plan fixture. Full S10 processing is a
separate M6 implementation gate; a fake consumer may verify the S9 staged-body/receipt
boundary until `process_target` is implemented.

#### Verification criteria

- An offline fixture path exercises plan projection, fixture replay, run-state commit,
  status inspection, and the staged-body handoff without an HTTP request. A test
  consumer validates S9 receipt and cleanup refusal before publication/discard without
  claiming S10 processing.
- Keep the S9-consumer test against a pinned S6 contract fixture separate from the
  S5/S6 integration case. Do not describe a fixture-only run as end-to-end inventory
  planning until the upstream S5/S6 gates above pass.
- S9 package imports do not depend on `pipelines.document_storage`; S9 exposes only
  leaf path/schema contracts for a later S10 consumer.
- Focused tests and `check.py` smart/fast gates pass. The full unconditional repository
  suite is not part of this plan unless separately requested.

### M6: S10 per-target processing service

**Dependencies:** M1's S9 `StagedBodyRef`/receipt contracts and M2E's trace opt-out.
This service can be implemented against temporary fixture bodies while the S9 live
runner proceeds independently.

**Goal:** Process one already-acquired target into a deterministic, metadata-only
result, preserve route/role distinctions, and acknowledge consumption through S9's
receipt contract. Design details are in [S10 processing](../S10_processing.md).

#### Target modules

- `processing_models.py`, `processing.py`, and the S10 per-run coordinator under
  `edgar_sec/pipelines/document_acquisition/`
- `edgar_sec/engine/forms/normalize.py` for `capture_stage_trace=False`
- Mirrored tests under `tests/pipelines/document_acquisition/` and
  `tests/engine/forms/`
- Processing-review integration through the S7-owned review path only

#### Verification criteria

- `process_target` accepts only a `StagedBodyRef` matching the immutable S9 work-order
  row; no acquisition, index lookup, or target repair is reachable from S10.
- Tests cover each route, the role-selected profile, malformed XML, diagnostics,
  deterministic fingerprints, and independent per-target failures.
- The selected body is verified and processed from the same opened file/bytes. A
  matching receipt precedes cleanup; integrity failures and pre-read budget refusals
  leave the acquired body staged without a receipt.
- The normalizer's no-trace option preserves the existing output for current callers
  and avoids S10's intermediate full-text trace records.
- Route-specific working-set envelopes are measured before a route is enabled for
  parallel large-body processing. Until then, unsupported input is refused with a
  typed budget diagnostic rather than admitted on an unmeasured guess.
- Exhibit assessment remains disabled or `insufficient_evidence` until M8 passes its
  independent review gate; no `REFETCH_SUB_DOC` action is carried forward.

### M7: Offline S9-to-S10 fixture integration

**Dependencies:** M3, M4, and M6. S5/S6 inventory-backed planning is not required for
this fixture-only test, but its completion is required before claiming a full live
inventory-to-processing vertical path.

#### Verification criteria

- A pinned S6 plan fixture is projected, fixture-replayed, acquired into staging,
  processed by S10, acknowledged with the matching receipt, and cleaned up with no HTTP.
- Verify direct ASCII, direct HTML, a bundle-selected child with an effective route
  different from the envelope, binary, unrecognized, processing failure, and retry
  without reacquiring the body.
- Processing review contains metadata and only selected derived text; no S5/S6 schema
  or durable payload output is written.
- A valid selected body is not lost when an unrelated fixture sibling fails.

### M8: Exhibit taxonomy evidence and diagnostic shadow pass

**Dependencies:** M4 fixture capture and M6's stable result boundary. M8 can proceed
independently of M7's vertical integration.

**Goal:** Turn the proposed concepts in
[S10 exhibit assessment](../S10_exhibit_assessment.md) into a reviewed, versioned
diagnostic pack only after corpus and holdout evidence exist.

#### Verification criteria

- Curate exact response fixtures and labels across supported forms, issuers, document
  routes, positive exhibit bodies, real primary reports, ambiguous cases, and negatives.
- Verify legal codes and effective dates; split by issuer/accession to avoid near-copy
  leakage; report per-family and per-form false-positive/negative counts.
- Include evaluator/taxonomy/pack versions in fingerprints and review artifacts.
- Begin in diagnostic shadow mode. Do not allow findings to alter planned targets,
  processing status, or acquisition. Enabling any families requires a recorded
  acceptance decision; upload examples alone do not pass this gate.

### M9: Durable acquisition snapshot publication

**Dependencies:** M7's fixture-driven S9-to-S10 gate, the shared DAG kernel, and S11
review of the [lifecycle publication contract](lifecycle.md). This work is now planned;
the prior deferral of the durable-store design is replaced by the specific Parquet/DAG
proposal in that contract. Durable writes remain disabled until the representative
S9/S10 cases pass the S11 approval checklist.

**Goal:** Publish completed S9/S10 run evidence and selected payloads as immutable,
queryable acquisition snapshots without changing S5 or S6.

#### Target modules

- Acquisition-owned DAG `RelationSpec`s, deterministic relation writer/query adapter,
  and S5 metadata-only reconciliation adapter.
- Separate binary-route and text-route Parquet payload relations, joined to target and
  slot evidence by digest; retain only reachable DAG parts.
- `acquisition publish` and read-only snapshot query/management command/operator
  actions, plus publication receipts and run cleanup.
- Mirrored tests for relation identity, payload-part adoption, publication atomicity, recovery,
  queries, and cleanup.

#### Verification criteria

- A fully validated run produces deterministic append-only evidence rows; re-publishing
  the same run is idempotent, while changed run/schema identity creates a distinct node.
- Every successfully acquired physical-slot body and distinct derived representation
  is a digest-verified row in
  separate binary/text Parquet relations; identical bytes deduplicate without
  collapsing physical-slot, target, or run links.
- Index-only S5 reconciliation adds acquisition-owned evidence without document fetch,
  S10 processing, or S5 mutation.
- A stale parent, corrupt part, missing payload row, changed digest, or interrupted
  install never advances the branch pointer. Retry publishes from run artifacts without
  repeating network requests.
- Incomplete/error publication requires explicit consent and is marked
  `complete_with_errors`; no pending target is represented as success.
- Transient cleanup refuses until the publication receipt proves payload-part adoption
  or an explicit discard operation is recorded. DAG retention respects snapshot,
  fixture, and review reachability.

## 4. Execution order and delegation

| Order | Workstream | Dependencies | Primary deliverables |
|---:|---|---|---|
| 0 | M0 interface freeze | Existing contracts | Broker staging/RPC and parser seams pinned |
| 1 | M1 shared S9 types/paths | M0 | Stable schemas, paths, settings, models |
| 2a | M2A SEC streaming | M0 | Additive brokered stream with bounded file output |
| 2b | M2B SGML extraction | M0 | Bounded exact-sequence engine API |
| 2c | M2C projection/state | M1 | Offline work order, SQLite state, project/status |
| 2d | M2D fixture store | M1 | SQLite BLOB evidence substrate |
| 2e | M2E S10 no-trace mode | S10 contract | Opt-out from retaining normalization stage traces |
| 3 | M3 local runner | M1, M2A–M2C | Resumable local SEC acquisition |
| 4 | M4 fixtures/CLI/operator | M2B, M2C, M2D, M3 | Local user surface and replay |
| 5 | M5 offline S9 gate | M3, M4 | Fixture-driven acquisition lifecycle verification |
| 6 | M6 S10 processing | M1, M2E | Typed per-target processing and S9 receipt integration |
| 7 | M7 offline vertical gate | M3, M4, M6 | Fixture-driven S9-to-S10 lifecycle verification |
| 8 | M8 exhibit assessment | M4, M6 | Holdout-evaluated, diagnostic-only taxonomy rules |
| 9 | M9 durable snapshot publication | M7, DAG kernel, S11 review | Binary/text Parquet payload relations in immutable acquisition DAG snapshots |

Parallel assignments should keep the shared S9 schema/path owner separate from
service implementers, and assign each lower-layer track to one owner per package. The
runner and CLI are integration assignments, not independent implementations of the
same command behavior.

## 5. Explicitly deferred work

- **Acquisition distribution:** the S9 adapter and worker integration remain
  unimplemented. SEC request pacing follows each host's configured settings and
  environment; cross-host coordination and checks are out of scope, so no aggregate
  cross-host rate guarantee is made.
- **PDF text extraction and constructed XBRL execution:** outside S9; availability is
  governed by S0/S11 decisions.
- **Historical parser acceptance and production rollout:** retain S0's evidence and
  operational gates; no live smoke test substitutes for them.
- **General large-body processing:** M6 must establish route-specific working-set
  evidence before enabling parallel processing above measured route envelopes. A
  finite acquisition limit alone is not a processing-memory guarantee.
- **S9-to-S10 inventory-backed vertical:** M7's fixture gate is separate from
  completing S5 relation-schema ownership and S6 profile/target-plan source adapters.
  The M6 S10 service consumes the pinned S6 artifact and does not implement those
  upstream APIs.
- **Enabled exhibit evaluator:** M8 is research and diagnostic shadow work; no rules
  are active until exact fixture evidence and a recorded acceptance decision exist.
- **Legacy `document_storage` deletion and full S12 vertical integration:** require
  separate acceptance after replacement APIs and artifact migration are proven.
