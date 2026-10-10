# S9 — Target-Plan Acquisition and Source Fixtures

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S9**.
- Status: S9 has an implemented S6 v2 projection/project service, run-state and
  fixture stores, file-backed HTTP/broker transport, and exact-sequence engine
  extractor. The acquisition runner and lazy-index/cover-screen integration remain
  unimplemented. Command contracts are indexed in
  [document_acquisition](document_acquisition/cli_inventory.md); the older S9a–S9d
  decomposition is retained as background design, not the active command index.
- Depends on: validated S6 target-plan bundles and S4 broker lifecycle. The ordinary
  inventory-backed path does not read S5 or catalog source artifacts; catalog-direct
  `exact_form_with_lazy_index` may fetch and parse an index page under its explicit
  recovery policy.
- Non-blocking: S10 processing uses the staged selected-body reference and fixture replay API.

## Current tracked-code audit (2026-10-10)

- **Status: foundation is implemented; end-to-end acquisition is not.** S6 emits v2 bundles, S9 projects validated plans into transient runs, and lower layers provide file-backed HTTP/broker transfer and exact-sequence extraction. No S9 runner yet composes acquisition attempts, type screens, lazy-index recovery, fixture replay, and target-slot resolution.
- **Evidence:** [`document_acquisition/project.py`](../../../edgar_sec/pipelines/document_acquisition/project.py), [`target_plan.py`](../../../edgar_sec/pipelines/document_acquisition/target_plan.py), [`infra/sec_http/streaming.py`](../../../edgar_sec/infra/sec_http/streaming.py), [`infra/broker/sec_broker.py`](../../../edgar_sec/infra/broker/sec_broker.py), and [`engine/document/unpacking/streaming.py`](../../../edgar_sec/engine/document/unpacking/streaming.py) own tested foundations. No `runner.py` or `S10` processor exists.
- **Next step:** implement the S9 runner and index/cover evidence branch against these lower-layer contracts; do not fall back to buffered transport or legacy `document_storage` selection.

## Objective

Acquire only executable targets from immutable target plans, retain source provenance, select legacy bundle bodies by exact sequence, and make representative acquisition evidence replayable without network access. S9 may resolve a catalog-direct primary to a different physical slot only when the pinned selector explicitly authorizes lazy index recovery. Durable slot/payload/type relations remain gated by S11. S9 does not import `pipelines.document_storage`.

## Target and result boundary

S9 validates the target-plan bundle and reads its target rows. Each plan requires a
catalog plan ID/digest and may carry an inventory snapshot ID/digest; a null snapshot
pin is valid only for catalog-only primary plans. Pinned source IDs/digests remain
provenance fields; acquisition never opens the upstream inventory snapshot or catalog
plan. `source_origin` selects a resolver, not a separate downstream data shape:

- `inventory_index` direct targets fetch their observed URL.
- `inventory_index` bundle targets use the accession bundle URL in `target_url` and require the observed sequence; S9 does not reopen the inventory snapshot.
- `catalog_direct` targets fetch the direct URL emitted by the S6 catalog adapter. They do not create or require a synthetic S5 inventory entry. Their `catalog_direct_selection` is carried into the work order and controls only the post-fetch screen/recovery behavior.

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

An HTTP 404, including a direct-target 404, is a transport failure with `error_code="http_not_found"` and acquisition status `failed`; it does not itself trigger index lookup or fallback. In the catalog-direct `exact_form_with_lazy_index` mode, a successfully fetched sequence-1 body whose ASCII SGML `<TYPE>` mismatches or cannot verify the accession form, or whose HTML cover evaluation fails to verify that form, triggers one bounded index lookup. The recognized index's observed row type selects the physical slot; a unique match is acquired from its direct locator or exact bundle sequence, and all observed slot type rows are retained as metadata evidence. A complete recognized index with no form-matching row is `not_filed` for an optional target or `required_missing` for a required target; duplicate matches are `ambiguous`; failed lookup/parse remains `failed`. These outcomes are distinct from an absent child sequence in a fully parsed bundle. A successful local HTML cover evaluation avoids the lookup but remains heuristic, not an exact-type proof. `submitted_primary` skips this screen and lookup. A fixture replay that succeeds has source `fixture_replay`—replay provenance is not an outcome status. `selected_body` is present only for `acquired` results and is the S10 input; it is a managed transient path, not a payload value in the case row.

## Command contract index

| Command | Contract |
|---|---|
| [`acquisition project`](document_acquisition/project.md) | Validate a self-contained S6 target plan and persist executable work without network access. |
| [`acquisition status`](document_acquisition/status.md) | Inspect and validate resumable work state without mutation. |
| [`acquisition run`](document_acquisition/run/index.md) | Execute bounded acquisition, exact bundle selection, cancellation, and explicit retry. |
| [`acquisition distrib`](document_acquisition/distribution/index.md) | Planned S9 adapter over the implemented pipeline-neutral distribution layer; the acquisition adapter remains unimplemented. SEC rate limits are host-local; cross-host coordination and checks are out of scope. |
| [`acquisition fixture`](document_acquisition/fixtures/index.md) | Explicitly capture and verify append-only evidence for zero-network replay. |

The former S9a–S9d documents remain available as earlier technical notes while this
command design is reviewed. S10 consumes S9's selected-body and fixture replay
contracts; it does not reach into S9 storage internals. S9 does not normalize bodies
or publish a durable payload snapshot.

## Shared invariants

- One SEC broker per run owns pacing, retries, and the failure ledger for all acquisition URLs.
- Response byte limits are enforced while streaming; oversize bodies are aborted and never truncated into successful targets.
- The broker streams to managed local staging. Process workers receive path handles and return typed metadata/digests; raw response bytes never cross process IPC. Explicit fixture capture streams from the staged path.
- A selected bundle child is staged separately from its full source envelope. Both digests and sizes are recorded; the child is never selected by a guessed sequence.
- Catalog-direct selection records the initial sequence-1 attempt even when a later
  index row selects another slot. Persisting both slot payloads beyond S9/S10 is
  conditional on S11 approval. The target-to-slot assignment and each physical slot's
  payload identity are separate from the target request; a single target's S10 input
  is the selected slot only.
- When the durable relations are approved, index discovery may enrich physical slot/type metadata without re-fetching or reprocessing already acquired payloads. S5 remains an immutable metadata snapshot owner; its facts are consumed by a downstream reconciliation, not written into S5 by S9.
- Transient source and selected-body files are removed after downstream processing unless the capture policy commits the source response to the fixture store.
- Fixture bodies are compressed replay evidence, not published document payloads. S11's Parquet snapshot contract owns durable payload publication.

## Acceptance criteria

- Inventory-index and catalog-direct target rows produce the same acquisition request/result shapes while retaining `source_origin` and pinned input provenance.
- Non-executable target statuses cause no HTTP request.
- Large responses stream to disk within a configured byte budget; no whole-body broker buffer or payload IPC is required in normal mode.
- Bundle extraction returns the exact requested sequence or a typed failure; it never falls back to sequence one.
- `submitted_primary` performs no local type evaluation or index request; `exact_form_with_lazy_index` invokes lookup only after the specified identity suspicion, and selects only from recognized index `document_type` rows.
- Lazy-index lookup records the response/parser evidence and preserves both the catalog-anchored sequence-1 slot and any replacement slot. A 404 or transient failure alone never initiates recovery.
- Direct-target and bundle HTTP 404 responses are `failed` with `http_not_found`; only a successfully parsed full bundle without the requested sequence is `not_filed`.
- Fixture replay verifies content digest and performs zero HTTP requests.
- No S9 module imports `pipelines.document_storage`; the pipeline's removal is a separate post-S12 milestone after S11 payload-store implementation, parity, and consumer/artifact migration.

## Verification

Mirrored offline tests cover target-plan validation, both source origins, bounded streaming, direct and legacy bundle acquisition, corruption/ambiguity cases, fixture append/replay, process serialization of handles, and cleanup. Network fakes are injected at the broker transport seam; a separate explicitly authorized live SEC smoke test is not part of the default quality gate.
