# S9 — Target-Plan Acquisition and Source Fixtures

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S9**.
- Status: S9 has an implemented S6 v3 target-only projection/project service, run-state and
  fixture stores, file-backed HTTP/broker transport, exact-sequence engine extractor,
  and serial acquisition runner. Catalog-direct exact-form selection uses a lazy
  index lookup, but its direct-body screen is recorded as unverifiable. The catalog-direct
  exact-form selector compares a primary bundle's `<TYPE>` with the pinned form using
  strict ASCII equality; mismatch or unverifiable type triggers lazy recovery. Other
  selectors do not screen the submitted primary. HTML/cover screening is absent. The
  fixture CLI/operator support create/fill/list/replay. Bundle and lazy-index response
  groups can be retained and replayed when acquisition's default-off
  `--retain-response-evidence` option is enabled. S10 has a per-target offline worker,
  but the `process --run-id` command, operation-aware coordinator, and requested
  renderers remain unimplemented. M7b runner/retry/isolation coverage is complete;
  cleanup remains explicitly gated. S11 remains gated. Command contracts are indexed in
  [document_acquisition](document_acquisition/cli_inventory.md); the older S9a–S9d
  decomposition is retained as background design, not the active command index.
- Depends on: validated S6 target-plan bundles and S4 broker lifecycle. The ordinary
  inventory-backed path does not read S5 or catalog source artifacts; catalog-direct
  `exact_form_with_lazy_index` may fetch and parse an index page under its explicit
  recovery policy.
- Requested next policy (not implemented): replace the uniform catalog-direct selector
  with S6-pinned family-specific text triggers. S9 owns any bounded trigger scan and
  index request; S10 outputs/diagnostics do not feed back into acquisition. Form 4 has no
  designed lazy-index trigger.
- Gated: complete S10 operation processing/consumption and S11 publication. Fixture
  replay writes to a caller-selected local output path but does not create a managed
  S10 staging reference or consumption receipt.

## Current tracked-code audit (2026-10-12)

- **Status: S9 acquisition, run inspection, and the supported fixture CLI family are integrated; cover evidence and later stages remain incomplete.** The serial runner composes bounded transfer, exact-sequence extraction, target outcomes, run-state commits, and catalog-direct lazy-index selection. The pinned exact-form selector records the direct-body screen and uses strict SGML `<TYPE>`/filing-form equality for bundle bodies and selected bundle candidates; there is no HTML/cover evaluator. Fixture create/fill/list/replay support direct and bodyless-failure cases plus complete bundle/lazy response groups when `--retain-response-evidence` was enabled for acquisition. Review generate/compare cover only the limited S9/S10 fixture slice. `process --run-id` remains unimplemented despite per-target `process_target`; the requested S10 policy and coordinator remain unimplemented. M7b runner/retry/isolation coverage is complete, but cleanup remains explicitly gated; S11 remains gated.
- **Evidence:** [`runner.py`](../../../edgar_sec/pipelines/document_acquisition/runner.py), [`target_runner.py`](../../../edgar_sec/pipelines/document_acquisition/target_runner.py), [`index_selection.py`](../../../edgar_sec/pipelines/document_acquisition/index_selection.py), [`fixture_store/capture.py`](../../../edgar_sec/pipelines/document_acquisition/fixture_store/capture.py), [`commands/review.py`](../../../edgar_sec/pipelines/document_acquisition/commands/review.py), [`processing.py`](../../../edgar_sec/pipelines/document_acquisition/processing.py), and [`cli.py`](../../../edgar_sec/pipelines/document_acquisition/cli.py) own the current code paths. Offline coverage includes [`test_runner.py`](../../../tests/pipelines/document_acquisition/test_runner.py), [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py), [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py), and [`commands/test_review.py`](../../../tests/pipelines/document_acquisition/commands/test_review.py).
- **Next step:** replace the uniform lazy-index selector with the versioned family-specific trigger policy in the S6/S9 decision trees. Trigger scans are limited to families with reviewed rendered-text evidence; Form 4 has none and relies on pinned raw URL/exhibit-link evidence. Keep historical mismatch fixture coverage as a separate S9 acceptance task. Do not fall back to buffered transport or legacy `document_storage` selection.

## Objective

Acquire only executable targets from immutable target plans and retain source provenance. S9 executes the S6-selected source and exact observed sequence; it does not compare advertised sizes, group target requests into one bundle fetch, or switch an ordinary failed direct request to the bundle. The catalog-direct lazy-index behavior remains a distinct, explicitly pinned selector contract, not ordinary direct-failure fallback. Durable slot/payload/type relations remain gated by S11. S9 does not import `pipelines.document_storage`.

Review-run and fixture evidence establishes the mapping from positive numbered child
names to accession-prefixed SEC archive leaves. S6 may pin a validated observed
`<accession>-<num>.<ext>` link, or construct a catalog primary child leaf from exact
`primaryDocument` metadata, as `direct_url`; `0001` is not inherently a placeholder.
Exact primary `0000.txt`/`.htm` names remain placeholders and require an advertised bundle
URL plus observed positive sequence. An indexed `0001.txt`/`.htm` primary without a
usable prefixed child link may use that observed bundle sequence. S9 follows the pinned
S6 target and does not classify paths itself or switch retrieval modes after direct
failure.

## Target and result boundary

S9 validates the target-plan bundle and reads its target rows. Each plan requires a
catalog plan ID/digest and may carry an inventory snapshot ID/digest; a null snapshot
pin is valid only for catalog-only primary plans. Pinned source IDs/digests remain
provenance fields; acquisition never opens the upstream inventory snapshot or catalog
plan. `source_origin` selects a resolver, not a separate downstream data shape:

- `inventory_index` direct targets fetch their observed URL.
- `inventory_index` bundle targets use the accession bundle URL in `target_url` and require the observed sequence; S9 does not reopen the inventory snapshot.
- `catalog_direct` targets fetch the direct URL emitted by the S6 catalog adapter. They do not create or require a synthetic S5 inventory entry. Their `catalog_direct_selection` is carried into the work order and controls only the post-fetch screen/recovery behavior.

Each target is acquired independently. `byte_size` for an indexed child describes that
child; the advertised size of the full-submission bundle and S1's reported catalog size
are separate observations. None is a selector or a basis for changing the pinned S6
retrieval mode.

The S6 `request_id` consumed below is derived by the planner from the profile's
canonical `(role, type)` pair; profile authors do not maintain an ID mapping.

Only `status="matched"` rows with `direct_url` or `bundle_sequence` are executable. Other target outcomes remain in the plan and are counted as skipped; `constructed_candidate` is not fetched unless a later S0 policy explicitly makes it executable. Target plans and inventory snapshots remain immutable. A catalog-direct primary is initially bound to physical sequence 1, the slot anchored by the catalog primary link; sequence 1 is not a type assertion.

```python
AcquisitionStatus = Literal["acquired", "not_filed", "ambiguous", "failed"]
AcquisitionSource = Literal["live_sec", "fixture_replay"]

@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    capture_id: str
    plan_id: str
    target_id: str
    accession: AccessionNumber
    request_id: str
    source_origin: Literal["inventory_index", "catalog_direct"]
    retrieval_mode: Literal["direct_url", "bundle_sequence"]
    document_path: str | None
    selected_filename: str | None
    source_url: str | None
    source_sha256: str | None
    selected_sha256: str | None
    selected_size: int | None
    selected_sequence: int | None
    source: AcquisitionSource
    status: AcquisitionStatus
    error_code: str | None

@dataclass(frozen=True, slots=True)
class AcquisitionExecution:
    result: AcquisitionResult
    selected_body: StagedBodyRef | None
```

An HTTP 404, including a direct-target 404, is a transport failure with `error_code="http_not_found"` and acquisition status `failed`; it does not itself trigger index lookup or fallback. In the catalog-direct direct-body path with `exact_form_with_lazy_index`, a successful sequence-1 fetch is followed by one bounded index fetch; the recorded `html_cover` screen is `unverifiable`. There is no HTML cover evaluator. Under that selector, the runner compares the ASCII-encoded extracted primary `<TYPE>` with the pinned filing form. A mismatch or unverifiable type triggers lazy index lookup, and the selected bundle candidate must pass the same check. Selectors that do not request this screen leave the submitted primary unchanged and do not initiate mismatch-triggered lookup. The recognized index selector checks accession scope and exact `document_type`/filing-form equality, then selects a unique row from its direct URL or exact bundle sequence. A complete recognized index with no form-matching row is `not_filed` for an optional target or `required_missing` for a required target; duplicate matches are `ambiguous`; failed lookup/parse remains `failed`. These outcomes are distinct from an absent child sequence in a fully parsed initial bundle. `submitted_primary` does not authorize lazy recovery. Fixture fill/list/replay can use retained direct responses and bodyless failures; bundle and lazy-index response groups are replayable when the complete source/index evidence was retained through `--retain-response-evidence`, and incomplete groups remain refused. Case-level replay writes to a new explicit local path and does not itself create an S10 handoff. M7a composes a direct-TEXT fixture through per-target processing and terminal projection, with receipt, coverage, and fingerprint checks; run-level `process --run-id` and general operation execution remain incomplete.

## Command contract index

| Command | Contract |
|---|---|
| [`acquisition project`](document_acquisition/project.md) | Validate a self-contained S6 target plan and persist executable work without network access. |
| [`acquisition status`](document_acquisition/status.md) | Inspect and validate resumable work state without mutation. |
| [`acquisition run`](document_acquisition/run/index.md) | Execute bounded acquisition, exact bundle selection, cancellation, and explicit retry. |
| [`acquisition distrib`](document_acquisition/distribution/index.md) | Planned S9 adapter over the implemented pipeline-neutral distribution layer; the acquisition adapter remains unimplemented. SEC rate limits are host-local; cross-host coordination and checks are out of scope. |
| [`acquisition fixture`](document_acquisition/fixtures/index.md) | Create/fill/list/replay are wired. Complete bundle/lazy response-group capture and replay require opt-in `--retain-response-evidence`; direct-TEXT replay composes with per-target S10 processing in offline coverage. Run-level `process --run-id` remains unimplemented. See [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py) and [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py). |

The former S9a–S9d documents remain available as earlier technical notes; current CLI
and operator flows are implemented for supported S9 operations. Gated S10 is intended
to consume S9's selected-body and fixture replay contracts; it will not reach into S9
storage internals. S9 does not normalize bodies or publish a durable payload snapshot.

## Shared invariants

- One SEC broker per run owns pacing, retries, and the failure ledger for all acquisition URLs.
- Response byte limits are enforced while streaming; oversize bodies are aborted and never truncated into successful targets.
- The broker streams to managed local staging; the current runner executes serially and records typed metadata/digests without sending response bodies through process IPC. Fixture capture promotes an exact attempt from local staging. The runner can retain bundle and lazy-index response-group members with opt-in `--retain-response-evidence`; fixture fill can capture and replay complete retained groups, and refuses groups with missing members. See [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py).
- A selected bundle child is staged separately from its full source envelope. Both digests and sizes are recorded; the child is never selected by a guessed sequence.
- Catalog-direct selection records the initial sequence-1 attempt even when a later
  index row selects another slot. Persisting both slot payloads beyond S9/S10 is
  conditional on S11 approval. The target-to-slot assignment and each physical slot's
  payload identity are separate from the target request; a single target's S10 input
  is the selected slot only.
- When the durable relations are approved, index discovery may enrich physical slot/type metadata without re-fetching or reprocessing already acquired payloads. S5 remains an immutable metadata snapshot owner; its facts are consumed by a downstream reconciliation, not written into S5 by S9.
- The runner removes unreferenced partial staging files and retains acquired selected-body files. Full source/index/selected response-group retention is opt-in and supports fixture fill/replay when enabled. M7b runner/retry/isolation coverage is complete; neither a processing receipt nor a rerun authorizes staged-body deletion. Cleanup remains gated on explicit discard or publication adoption; see [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py).
- Fixture bodies are compressed replay evidence, not published document payloads. S11's Parquet snapshot contract owns durable payload publication.

## Remaining acceptance criteria

- Inventory-index and catalog-direct target rows produce the same acquisition request/result shapes while retaining `source_origin` and pinned input provenance.
- Non-executable target statuses cause no HTTP request.
- Large responses stream to disk within a configured byte budget; no whole-body broker buffer or payload IPC is required in normal mode.
- Bundle extraction returns the exact requested sequence or a typed failure; it never falls back to sequence one.
- `submitted_primary` performs no mismatch-triggered index request. HTML evaluation is absent. On the catalog-direct direct-body path with `exact_form_with_lazy_index`, lookup follows a successful sequence-1 fetch unconditionally and uses exact index `document_type` selection.
- Lazy-index lookup records the response/parser evidence and preserves both the catalog-anchored sequence-1 slot and any replacement slot. A 404 or transient failure alone never initiates recovery.
- Primary bundle `<TYPE>` mismatch/unverifiable paths recover only under the exact-form catalog-direct selector; the recovered bundle must pass the strict ASCII comparison, while other selectors leave the submitted primary unchanged without mismatch-triggered index traffic.
- Direct-target and bundle HTTP 404 responses are `failed` with `http_not_found`; only a successfully parsed full bundle without the requested sequence is `not_filed`.
- Project/status/run and fixture create/fill/list/replay are wired; review generate/compare cover only the limited S9/S10 fixture slice. Fill supports successful direct responses, bodyless failures, and complete bundle/lazy response groups when `--retain-response-evidence` was enabled. Listing streams metadata without reading body BLOBs; replay verifies retained evidence and writes only to a new explicit output path without HTTP. `process --run-id` remains not implemented; the available per-target worker provides raw identity and TEXT-route identity passthrough, not the requested rendering policy or a coordinator. M7b runner/retry/isolation coverage is complete; cleanup and S11 remain gated.
- No S9 module imports `pipelines.document_storage`; the legacy runtime package and tests are retired. Durable payload storage remains a separate S11 design and implementation gate.

## Verification

Mirrored offline tests cover target-plan validation, both source origins, bounded streaming, direct and legacy bundle acquisition, corruption/ambiguity cases, fixture append/replay, process serialization of handles, and cleanup. Network fakes are injected at the broker transport seam; a separate explicitly authorized live SEC smoke test is not part of the default quality gate.
