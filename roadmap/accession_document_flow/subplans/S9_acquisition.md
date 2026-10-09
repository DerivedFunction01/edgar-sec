# S9 — Target-Plan Acquisition and Source Fixtures

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S9**.
- Status: replacement acquisition remains design-only; legacy byte-oriented
  acquisition components do not satisfy the staged S9 contracts.
- Depends on: validated S6 target-plan bundles and S4 broker lifecycle. S9 does not read
  S5 or catalog source artifacts.
- Non-blocking: S10 processing uses the staged selected-body reference and fixture replay API.

## Current tracked-code audit (2026-10-08)

- **Status: replacement acquisition is not implemented.** Existing SEC HTTP and `document_storage` paths fetch and pass full response bytes; the old acquisition, fixture, and processing models do not satisfy the staged S9 contracts.
- **Evidence:** [`infra/sec_http/client.py`](../../../edgar_sec/infra/sec_http/client.py) reads `response.content`; [`infra/broker/sec_broker.py`](../../../edgar_sec/infra/broker/sec_broker.py) returns payload bytes through its broker protocol. [`document_storage_disposition.md`](../document_storage_disposition.md) explicitly marks the old fetcher, fixture store, and work order as inspiration or non-reusable legacy contracts.
- **Next step:** start with S9a after the S6 profile target-plan contract exists; then implement staged streaming, exact-sequence extraction, and the separate S9d fixture store in dependency order.

## Objective

Acquire only executable targets from immutable target plans, retain source provenance, select legacy bundle bodies by exact sequence, and make representative acquisition evidence replayable without network access. Acquisition does not publish a durable payload store and does not import `pipelines.document_storage`.

## Target and result boundary

S9 validates the target-plan bundle and reads its target rows. Each plan requires a
catalog plan ID/digest and may carry an inventory snapshot ID/digest; a null snapshot
pin is valid only for catalog-only primary plans. Pinned source IDs/digests remain
provenance fields; acquisition never opens the upstream inventory snapshot or catalog
plan. `source_origin` selects a resolver, not a separate downstream data shape:

- `inventory_index` direct targets fetch their observed URL.
- `inventory_index` bundle targets use the accession bundle URL in `target_url` and require the observed sequence; S9 does not reopen the inventory snapshot.
- `catalog_direct` targets fetch the direct URL emitted by the S6 catalog adapter. They do not create or require a synthetic inventory entry.

The S6 `request_id` consumed below is derived by the planner from the profile's
canonical `(role, type)` pair; profile authors do not maintain an ID mapping.

Only `status="matched"` rows with `direct_url` or `bundle_sequence` are executable. Other target outcomes remain in the plan and are counted as skipped; `constructed_candidate` is not fetched unless a later S0 policy explicitly makes it executable. Target plans and inventory snapshots remain immutable.

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

An HTTP 404, including a direct-target 404, is a transport failure with `error_code="http_not_found"` and acquisition status `failed`; it is never `not_filed`. `not_filed` means a complete bundle was fetched and parsed successfully but contained no document at the requested sequence. Duplicate sequence matches are `ambiguous`; malformed bundles and parse failures are `failed`. A fixture replay that succeeds has status `acquired` and source `fixture_replay`—replay provenance is not an outcome status. `selected_body` is present only for `acquired` results and is the S10 input; it is a managed transient path, not a payload value in the case row.

## Subplan decomposition

| Subplan | Contract |
|---|---|
| [S9a — Target adapter](S9a_target_adapter.md) | Validate S6 target plans and resolve eligible rows to acquisition work orders. |
| [S9b — Streaming transport](S9b_stream_transport.md) | Stream broker responses to bounded transient files; return metadata handles, not payload bytes over IPC. |
| [S9c — SGML bundle extraction](S9c_sgml_extraction.md) | Extract exactly one bundle sequence to a staged file with bounded memory and typed structural failures. |
| [S9d — Acquisition fixtures](S9d_acquisition_fixtures.md) | Append-only SQLite case index plus content-addressed fixture bodies and verified offline replay. |

Implement the interfaces in order: target adapter, transport and extraction, then fixture capture/replay. S10 consumes S9's staged selected-body and fixture replay contracts; it does not reach into S9 storage internals.

## Shared invariants

- One SEC broker per run owns pacing, retries, and the failure ledger for all acquisition URLs.
- Response byte limits are enforced while streaming; oversize bodies are aborted and never truncated into successful targets.
- The broker streams to managed local staging. Process workers receive path handles and return typed metadata/digests; raw response bytes never cross process IPC. Explicit fixture capture streams from the staged path.
- A selected bundle child is staged separately from its full source envelope. Both digests and sizes are recorded; the child is never selected by a guessed sequence.
- Transient source and selected-body files are removed after downstream processing unless the capture policy commits the source response to the fixture store.
- Fixture bodies are test/review evidence, not the future durable payload store. S11 owns that design gate.

## Acceptance criteria

- Inventory-index and catalog-direct target rows produce the same acquisition request/result shapes while retaining `source_origin` and pinned input provenance.
- Non-executable target statuses cause no HTTP request.
- Large responses stream to disk within a configured byte budget; no whole-body broker buffer or payload IPC is required in normal mode.
- Bundle extraction returns the exact requested sequence or a typed failure; it never falls back to sequence one.
- Direct-target and bundle HTTP 404 responses are `failed` with `http_not_found`; only a successfully parsed full bundle without the requested sequence is `not_filed`.
- Fixture replay verifies content digest and performs zero HTTP requests.
- No S9 module imports `pipelines.document_storage`; the pipeline's removal is a separate post-S12 milestone after S11 payload-store implementation, parity, and consumer/artifact migration.

## Verification

Mirrored offline tests cover target-plan validation, both source origins, bounded streaming, direct and legacy bundle acquisition, corruption/ambiguity cases, fixture append/replay, process serialization of handles, and cleanup. Network fakes are injected at the broker transport seam; a separate explicitly authorized live SEC smoke test is not part of the default quality gate.
