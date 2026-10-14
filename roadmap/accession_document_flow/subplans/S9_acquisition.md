# S9 — Target-Plan Acquisition and Source Fixtures

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S9**.
- Status: S6 bundle v4, S9 work-order v3, run state, fixture storage, file-backed
  HTTP/broker transport, exact-sequence extraction, and the serial acquisition runner are
  implemented. The exposed `acquisition run` command acquires targets and processes each
  acquired checkpoint under the same run lock. A catalog-direct selector field remains
  in the contract, but current projections emit no family-trigger IDs/versions and the
  runner refuses lazy recovery without them; supported live locators are direct URLs and
  exact bundle sequences. The acquisition fixture/review console supports
  create/fill/list and review generate/compare/analyze; fixture-body verification is
  internal, not a separate user-facing replay/export action. Bundle/lazy response-group
  retention requires the default-off `--retain-response-evidence` option. Production
  derived renderers remain disabled because the route/handler budget registry is empty.
  M7b runner/retry/isolation coverage is complete; cleanup and S11 remain gated. Command
  contracts are indexed in
  [document_acquisition](document_acquisition/cli_inventory.md); the older S9a–S9d
  decomposition is retained as background design, not the active command index.

- Depends on: validated S6 target-plan bundles and S4 broker lifecycle. The ordinary
  inventory-backed path does not read S5 or catalog source artifacts; catalog-direct
  lazy recovery is refused until a future S6 plan pins a reviewed family trigger.
- Requested next policy (not implemented): replace the dormant uniform catalog-direct
  selector with S6-pinned family-specific text triggers. S9 owns any bounded trigger
  scan and index request; S10 outputs/diagnostics do not feed back into acquisition.
  Form 4 has no designed lazy-index trigger.
- Gated: production derived processing and S11 publication. Fixture-body verification
  used by review generation is internal; this surface has no user-facing raw-body export.

## Current tracked-code audit (2026-10-13)

- **Status: S9 acquisition, run inspection, and the supported fixture/review CLI family are integrated; cover evidence and later stages remain incomplete.** The serial runner composes bounded transfer, exact-sequence extraction, target outcomes, run-state commits, and per-target S10 processing. Current projections emit no family-trigger IDs/versions, so catalog-direct lazy-index recovery is refused; ordinary direct failures do not switch modes. There is no HTML/cover evaluator. Fixture create/fill/list and review generate/compare/analyze cover the limited S9/S10 slice; the review generator verifies fixture bodies internally. Bundle/lazy response-group evidence is available only when `--retain-response-evidence` was enabled for acquisition. The production route/handler budget registry is empty, so derived normalization fails closed. M7b runner/retry/isolation coverage is complete; cleanup and S11 remain gated.
- **Evidence:** [`runner.py`](../../../edgar_sec/pipelines/document_acquisition/runner.py), [`target_runner.py`](../../../edgar_sec/pipelines/document_acquisition/target_runner.py), [`index_selection.py`](../../../edgar_sec/pipelines/document_acquisition/index_selection.py), [`fixture_store/capture.py`](../../../edgar_sec/pipelines/document_acquisition/fixture_store/capture.py), [`commands/review.py`](../../../edgar_sec/pipelines/document_acquisition/commands/review.py), [`processing/worker.py`](../../../edgar_sec/pipelines/document_acquisition/processing/worker.py), and [`cli.py`](../../../edgar_sec/pipelines/document_acquisition/cli.py) own the current code paths. Offline coverage includes [`test_runner.py`](../../../tests/pipelines/document_acquisition/test_runner.py), [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py), [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py), and [`commands/test_review.py`](../../../tests/pipelines/document_acquisition/commands/test_review.py).
- **Next step:** add only reviewed, versioned family-trigger pins if lazy-index recovery is still required. No current target plan enables that branch. Keep historical mismatch fixture coverage as a separate S9 acceptance task. Do not fall back to buffered transport or legacy `document_storage` selection.

## Objective

Acquire only executable targets from immutable target plans and retain source provenance. S9 executes the S6-selected source and exact observed sequence; it does not compare advertised sizes, group target requests into one bundle fetch, or switch an ordinary failed direct request to the bundle. The catalog-direct lazy selector remains dormant until a plan carries reviewed family-trigger pins; it is not ordinary direct-failure fallback. Durable slot/payload/type relations remain part of the separate S11 design. S9 does not import `pipelines.document_storage`.

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
- `catalog_direct` targets fetch the direct URL emitted by the S6 catalog adapter. They do not create or require a synthetic S5 inventory entry. The retained `catalog_direct_selection` field is not itself runtime authorization for a post-fetch screen or recovery; current plans contain no family-trigger pins and the runner refuses lazy recovery without them.

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

An HTTP 404, including a direct-target 404, is a transport failure with
`error_code="http_not_found"` and acquisition status `failed`; it does not trigger index
lookup or fallback. Current target-plan projections do not emit family-trigger pins, and
the runner refuses the retained `exact_form_with_lazy_index` branch without them. If a
future S6 policy enables it, the selector will use a bounded, provenance-recorded check;
it still will not treat a transport failure as an index trigger. `submitted_primary`
never authorizes recovery. Fixture fill can retain direct responses and bodyless failures;
complete bundle/lazy response groups require `--retain-response-evidence` at acquisition.
The review generator verifies fixture bytes internally and produces processing-review
artifacts; no user-facing replay/export command exists. The exposed `acquisition run`
performs per-target processing inline with the run lifecycle.

## Command contract index

| Command | Contract |
|---|---|
| [`acquisition project`](document_acquisition/project.md) | Validate a self-contained S6 target plan and persist executable work without network access. |
| [`acquisition status`](document_acquisition/status.md) | Inspect and validate resumable work state without mutation. |
| [`acquisition run`](document_acquisition/run/index.md) | Execute bounded acquisition, process each acquired checkpoint under one run lock, and report both outcomes with explicit retry. |
| [`acquisition distrib`](document_acquisition/distribution/index.md) | Planned S9 adapter over the implemented pipeline-neutral distribution layer; the acquisition adapter remains unimplemented. SEC rate limits are host-local; cross-host coordination and checks are out of scope. |
| [`acquisition fixture`](document_acquisition/fixtures/index.md) | Create/fill/list and review generate/compare/analyze are wired. Complete bundle/lazy response-group capture requires opt-in `--retain-response-evidence`; body verification is internal to review generation, not a public export command. See [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/test_capture.py) and [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py). |

The former S9a–S9d documents remain available as earlier technical notes; current CLI
and operator flows are implemented for supported S9 operations. S10 consumes S9's
selected-body/work-order contract through the combined run path; it does not reach into
S9 storage internals. Production-derived normalization and durable payload publication
remain unavailable.

## Shared invariants

- One SEC broker per run owns pacing, retries, and the failure ledger for all acquisition URLs.
- Response byte limits are enforced while streaming; oversize bodies are aborted and never truncated into successful targets.
- The broker streams to managed local staging; the current runner executes serially and records typed metadata/digests without sending response bodies through process IPC. Fixture capture promotes an exact attempt from local staging. The runner can retain bundle and lazy-index response-group members with opt-in `--retain-response-evidence`; fixture fill can capture and replay complete retained groups, and refuses groups with missing members. See [`fixture_store/test_capture.py`](../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py).
- A selected bundle child is staged separately from its full source envelope. Both digests and sizes are recorded; the child is never selected by a guessed sequence.
- If a future pinned trigger selects a different slot, retain the initial sequence-1
  attempt and separate target-to-slot assignment from each physical slot's payload
  identity. Persisting both slot payloads beyond S9/S10 is conditional on S11. Current
  target plans do not enable that lazy-recovery branch; a target's S10 input is the
  locator-selected body.
- When the durable relations are approved, index discovery may enrich physical slot/type metadata without re-fetching or reprocessing already acquired payloads. S5 remains an immutable metadata snapshot owner; its facts are consumed by a downstream reconciliation, not written into S5 by S9.
- The runner removes unreferenced partial staging files and retains acquired selected-body files. Full source/index/selected response-group retention is opt-in and supports fixture fill/replay when enabled. M7b runner/retry/isolation coverage is complete; neither a processing receipt nor a rerun authorizes staged-body deletion. Cleanup remains gated on explicit discard or publication adoption; see [`test_offline_acceptance.py`](../../../tests/pipelines/document_acquisition/test_offline_acceptance.py).
- Fixture bodies are compressed replay evidence, not published document payloads. S11's Parquet snapshot contract owns durable payload publication.

## Remaining acceptance criteria

- Inventory-index and catalog-direct target rows produce the same acquisition request/result shapes while retaining `source_origin` and pinned input provenance.
- Non-executable target statuses cause no HTTP request.
- Large responses stream to disk within a configured byte budget; no whole-body broker buffer or payload IPC is required in normal mode.
- Bundle extraction returns the exact requested sequence or a typed failure; it never falls back to sequence one.
- `submitted_primary` performs no mismatch-triggered index request. HTML evaluation is absent. The catalog-direct lazy selector is refused unless an S6 version supplies family-trigger pins; current projects do not.
- If lazy-index recovery is re-enabled, record response/parser evidence and preserve the sequence-1 and replacement slots. A 404 or transient failure alone must never initiate recovery.
- Strict primary bundle `<TYPE>` checks and family-specific mismatch triggers are not current production behavior; retain them as acceptance criteria only for a future pinned selector.
- Direct-target and bundle HTTP 404 responses are `failed` with `http_not_found`; only a successfully parsed full bundle without the requested sequence is `not_filed`.
- Project/status/run and fixture create/fill/list plus review generate/compare/analyze are wired. Fill supports successful direct responses, bodyless failures, and complete bundle/lazy response groups when `--retain-response-evidence` was enabled. Listing streams metadata without reading body BLOBs; review generation verifies fixture evidence internally. The combined run invokes per-target processing after each acquired checkpoint; raw identity works and TEXT identity is test-budgeted, while the production route/handler budget registry is empty. M7b runner/retry/isolation coverage is complete; cleanup and S11 remain gated.
- No S9 module imports `pipelines.document_storage`; the legacy runtime package and tests are retired. Durable payload storage remains a separate S11 design and implementation gate.

## Verification

Mirrored offline tests cover target-plan validation, both source origins, bounded streaming, direct and legacy bundle acquisition, corruption/ambiguity cases, fixture append/replay, process serialization of handles, and cleanup. Network fakes are injected at the broker transport seam; a separate explicitly authorized live SEC smoke test is not part of the default quality gate.
