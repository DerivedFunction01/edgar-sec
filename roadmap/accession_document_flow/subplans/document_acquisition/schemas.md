# S9 persisted and handoff schemas

## Purpose and status

This is the shared S9 schema owner. It is design-only; lightweight JSON and
cross-stage contracts belong in `edgar_sec/pipelines/document_acquisition/schemas.py`;
the Parquet target/work-order fields belong in `arrow_schemas.py`. Both owners must
exist before command implementations begin. Command-specific state transitions are in
[run persistence](run/state.md) and [fixture persistence](fixtures/storage.md).

## Input contract

The S6 bundle pins target-plan schema `1.3` and target relation schema version `1`.
The persisted row fields are the S6 `document_planning.schemas.TARGET_SCHEMA` contract:

| Column | Physical type | Required | Use in S9 |
|---|---|---:|---|
| `target_id`, `accession`, `form`, `filing_date`, `request_id`, `target_role`, `target_type` | string | yes | Identity and source provenance. |
| `optional` | bool | yes | Retain for target intent; it does not change transport behavior. |
| `inventory_entry_id` | string | no | Provenance only; never reopen the inventory snapshot. |
| `status`, `source_origin`, `retrieval_mode`, `availability_evidence` | string | yes | Preserve S6 decision and select the S9 retrieval adapter. |
| `status_reason`, `target_url`, `sequence`, `byte_size` | string, string, int32, int64 | no | S6 explanation, validated locator, exact bundle selector, advisory observed size. |
| `catalog_direct_selection` | string | nullable | Catalog-direct primary policy copied from S6: `submitted_primary` or `exact_form_with_lazy_index`; null on inventory-backed rows. |

S9 imports this schema and its version directly from the S6 `schemas.py` owner, then
validates the copied bundle without calling S6 planner or discovery services. Booleans
are not accepted as integer sequences or sizes. An executable bundle sequence must
be positive. The observed response/selected-body size is authoritative over S6's
advisory `byte_size`.

The run manifest's source-pin relationship must agree with every row: a null
inventory snapshot pin is valid only when all rows are `catalog_direct` primary
targets; a non-null inventory pin requires `source_origin="inventory_index"` for all
rows. Catalog plan ID/digest are always required. These checks verify the S6 bundle's
declared contract; they do not reopen source artifacts.

## Work-order schema

`WORK_ORDER_SCHEMA_VERSION = "1"` is the proposed first S9 work-order format. Persist
one row for every S6 target, including targets that S9 will skip. Preserve the S6
columns above and append:

| Column | Physical type | Required | Meaning |
|---|---|---:|---|
| `executable` | bool | yes | True only for `status="matched"` and a validated `direct_url` or `bundle_sequence`. |
| `skip_reason` | string | no | Stable code for non-matched or unsupported targets; null iff executable. |
| `catalog_direct_selection` | string | nullable | Preserve the S6 selector; it cannot be supplied or changed by the S9 caller. |

The work-order part is Parquet with the S6 field nullability unchanged. The manifest
lists each part's relative path, row count, byte size, and SHA-256. Parts are read and
written in bounded row groups. `fetch_url` is not a second locator column: S9 stores
the validated S6 `target_url` and interprets it according to `retrieval_mode`.

- `direct_url` means `target_url` is the selected document locator; derive its
  `document_path` from the validated archive path, not from `target_type`.
- `bundle_sequence` means `target_url` is the accession bundle locator; `sequence`
  is the exact positive child selector. `target_type` is not an expected SGML
  `<TYPE>` value, and `inventory_entry_id` is not reopened to recover a filename.
- A catalog-direct primary's physical anchor is sequence 1. `target_role=primary` is
  processing intent; the expected statutory type is the pinned catalog `form`. The
  SEC index primary designation, physical sequence, and body type are distinct facts.
  `exact_form_with_lazy_index` may add a versioned S9 resolution record assigning the
  target to a different observed slot; it does not rewrite the S6 plan.
- Every other S6 row remains in the work order with `executable=false` and a stable
  skip reason. An unsupported candidate cannot be made executable by retry or
  worker input.

## Run manifest

The immutable `run.json` contains:

```python
from typing import TypedDict

class PartDescriptor(TypedDict):
    path: str
    row_count: int
    byte_size: int
    sha256: str

class AcquisitionRunManifest(TypedDict):
    run_id: str
    run_schema_version: str
    acquisition_contract_version: str
    target_plan_id: str
    target_plan_digest: str
    target_plan_schema_version: str
    target_schema_version: int
    catalog_plan_id: str
    catalog_plan_digest: str
    inventory_snapshot_id: str | None
    inventory_snapshot_digest: str | None
    work_order_schema_version: str
    work_order_parts: list[PartDescriptor]
    target_row_count: int
    executable_count: int
    skipped_count: int
    run_digest: str
```

Relative paths must remain inside the run directory. The run digest is
the canonical hash of the manifest without `run_digest`. A run ID is derived from
the target-plan ID/digest and S9 contract version; transport retries and worker
settings are attempt provenance and do not rewrite the manifest.

## Runtime outcomes and body handoff

The public S10 handoff records live in lightweight `schemas.py`, so S10 imports only
the permitted S9 schema leaf and does not load S9 services or Arrow dependencies:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

@dataclass(frozen=True, slots=True)
class StagedBodyRef:
    run_id: str
    target_id: str
    path: Path
    sha256: str
    byte_size: int
    selected_filename: str | None
    source_response_path: Path
    source_response_sha256: str
    source_response_byte_size: int

class BodyConsumptionReceipt(TypedDict):
    receipt_schema_version: str
    run_id: str
    target_id: str
    source_response_sha256: str
    selected_sha256: str
    processing_run_id: str
    consumed_at_utc: str
```

`models.py` owns mutable-run value records:

```python
from collections.abc import Mapping
from typing import Literal

SourceOrigin = Literal["inventory_index", "catalog_direct"]
RetrievalMode = Literal["direct_url", "bundle_sequence"]
AcquisitionSource = Literal["live_sec", "fixture_replay"]
AttemptKind = Literal["document_body", "lazy_index"]
AcquisitionStatus = Literal["pending", "acquired", "not_filed", "required_missing", "ambiguous", "failed", "skipped"]
RunStatus = Literal[
    "ready", "running", "interrupted", "complete", "needs_retry",
    "complete_with_errors", "invalid",
]
BodyLifecycle = Literal["staged", "consumed"]

@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    max_response_bytes: int
    requested_workers: int | None = None

@dataclass(frozen=True, slots=True)
class AcquisitionAttempt:
    attempt_id: str
    target_id: str
    attempt_number: int
    attempt_kind: AttemptKind
    source: AcquisitionSource
    outcome: Literal["acquired", "not_filed", "required_missing", "ambiguous", "failed"]
    retryable: bool
    error_code: str | None
    http_status: int | None
    final_url: str | None
    started_at_utc: str
    finished_at_utc: str
    source_sha256: str | None
    source_byte_size: int | None
    source_body_relative_path: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    selected_body_relative_path: str | None

@dataclass(frozen=True, slots=True)
class TargetSlotResolution:
    resolution_schema_version: str
    resolution_id: str
    run_id: str
    target_id: str
    selector: Literal["submitted_primary", "exact_form_with_lazy_index"]
    expected_statutory_type: str
    initial_sequence: int
    screen_kind: Literal["none", "sgml_type", "html_cover"]
    screen_result: Literal["not_run", "form_match", "type_mismatch", "unverifiable"]
    evaluator_version: str | None
    initial_body_sha256: str
    index_attempt_id: str | None
    index_response_sha256: str | None
    index_parser_version: str | None
    matching_entry_ids: tuple[str, ...]
    selected_sequence: int | None
    selected_retrieval_mode: RetrievalMode | None
    selected_url: str | None
    result: Literal["accepted_sequence_1", "recovered", "not_filed", "required_missing", "ambiguous", "failed"]

@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    target_id: str
    source: AcquisitionSource | None
    status: AcquisitionStatus
    attempt_count: int
    last_attempt_id: str | None
    error_code: str | None
    retryable: bool
    source_sha256: str | None
    source_byte_size: int | None
    source_body_relative_path: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    body_lifecycle: BodyLifecycle | None
    selected_body_relative_path: str | None

@dataclass(frozen=True, slots=True)
class AcquisitionStatusCounts:
    target_counts: Mapping[AcquisitionStatus, int]
    retryable_failure_count: int
    non_retryable_failure_count: int

@dataclass(frozen=True, slots=True)
class RunLockInfo:
    host: str
    pid: int
    started_at_utc: str
    owner_token: str

@dataclass(frozen=True, slots=True)
class ProjectedAcquisitionRun:
    run_id: str
    manifest: AcquisitionRunManifest
    executable_count: int
    skipped_count: int
    work_order_sha256: str
    reused: bool

@dataclass(frozen=True, slots=True)
class AcquisitionStatusReport:
    run_id: str
    state: RunStatus
    target_counts: Mapping[AcquisitionStatus, int]
    retryable_failure_count: int
    non_retryable_failure_count: int
    active_lock: RunLockInfo | None
    invalid_reason: str | None

@dataclass(frozen=True, slots=True)
class AcquisitionRunReport:
    run_id: str
    state: RunStatus
    target_counts: Mapping[AcquisitionStatus, int]
    attempted_count: int
    retryable_failure_count: int
    non_retryable_failure_count: int
    cancelled: bool
```

In-memory `StagedBodyRef` paths are owned transient paths and are never serialized as
absolute paths or transferred through IPC. Persist only run-relative paths. For a
direct URL, source and selected digests/paths are equal and refer to one staged file.
For a bundle, source and selected digests/paths differ; the source envelope remains
staged until extraction and any explicit fixture capture. The selected body remains
staged until snapshot publication writes its Parquet payload row or the run is explicitly
discarded. `body_lifecycle` describes only S10 consumption; fixture retention of a
source envelope is tracked by the fixture capture record.

S10 acknowledges verified consumption with a small S9-owned receipt. S10 imports only
the S9 `paths.py` and `schemas.py` contracts (not S9 services) and writes the receipt
atomically. A receipt is not permission to remove bytes needed by the publisher.

S9 derives `body_lifecycle="consumed"` only when that receipt matches the run,
target, source-response and selected digests, and supported schema. A missing file
without a valid receipt is corrupt state; an acquired result remains valid after a
matching receipt. Parquet payload publication is recorded separately by the snapshot publication
receipt.

`not_filed` is valid only after a complete bundle was parsed and the pinned sequence
was absent. HTTP 404, a malformed bundle, or an incomplete response is not
`not_filed`. Cancellation and interruption are run states, not acquisition outcomes.
For catalog-direct lazy recovery, a successfully fetched and recognized index with no
row whose observed `document_type` matches the expected filing form yields `not_filed`
for an optional target or `required_missing` for a required target. Preserve the
outcome's evidence source so this cannot be conflated with a missing bundle child. A
selector-driven replacement also records the original slot-1 attempt,
the index response/parser identity, selected row/sequence, resolved locator, and final
target-to-slot assignment.

`TargetSlotResolution` is the versioned decision record for catalog-direct policies,
separate from the immutable S6 target and ordinary document-body outcome. The lazy
index HTTP response has its own append-only `AcquisitionAttempt` with
`attempt_kind="lazy_index"`; its digest and parser version are referenced from the
resolution. `matching_entry_ids` retains all form-matching rows, including duplicates.
The selected sequence/locator is populated only for a unique selected slot. Failed
lookup, recognized absence, ambiguity, and successful resolution therefore remain
distinguishable without overloading a body digest or rewriting the work order.

## Physical-slot and type-evidence model

S9's per-run staging and attempt ledger remain distinct from the durable relational
store. The S11 relation grains, Parquet model, publication protocol, and reconciliation
boundary are specified in the [acquisition lifecycle plan](lifecycle.md). The durable
physical-slot key remains `(accession, sequence)`; versioned evidence identifies which
observation supplied that slot's metadata. Sparse `slot_types` contains only observed
index/SGML type evidence. Index-only reconciliation can add acquisition-owned slot
metadata without fetching document bodies or invoking S10.

## Explicit non-fields

- No profile-level `raw` boolean or normalization mode. S9 always acquires source
  bytes; S10 independently chooses text, XML-verbatim, binary, or other processing.
- No payload bytes or normalized text in transient run-state Parquet, JSON, or SQLite;
  durable payload columns are owned only by the S11 snapshot relations. Never persist
  SQL text, absolute local paths, SEC credentials, or whole HTTP header maps.
- No inferred filename, sequence, role, or route. A direct filename comes from its
  validated archive path; a bundle filename comes from the selected SGML header.

## Acceptance

S9 can validate and replay its work from the target-plan pin and run bundle alone.
Schema changes are versioned; hashes cover canonical metadata and exact streamed
bytes, not decoded or normalized content.
