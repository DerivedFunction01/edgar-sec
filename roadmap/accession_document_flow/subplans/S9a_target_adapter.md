# S9a — Target-Plan Acquisition Adapter

## Owner and status

- Owning stage in [S9](S9_acquisition.md): acquisition work-order boundary.
- Status: S6 target-plan production and the S9a bounded Parquet adapter are
  implemented; run projection and network acquisition remain separate.
- Depends on: S6 target-plan schema and S4 broker lifecycle; the target bundle is
  self-contained for acquisition.

## Current tracked-code audit (2026-10-10)

- **Status: S9a projection and S9 acquisition are integrated.** The S6 producer emits bundle schema v2 with declared target-part byte sizes. `plan_projection.target_plan` validates that pinned bundle and streams every target into the Parquet work-order schema; `plan_projection.project` binds it to the immutable run manifest and state database. S9 performs bounded HTTP acquisition and exact bundle-sequence extraction; processing remains the separate S10 stage.
- **Evidence:** [`plan_projection/target_plan.py`](../../../edgar_sec/pipelines/document_acquisition/plan_projection/target_plan.py), [`plan_projection/project.py`](../../../edgar_sec/pipelines/document_acquisition/plan_projection/project.py), [`arrow_schemas.py`](../../../edgar_sec/pipelines/document_acquisition/arrow_schemas.py), and their mirrored tests validate pins, bounded projection, and locator semantics. [`target_runner.py`](../../../edgar_sec/pipelines/document_acquisition/target_runner.py) owns S9 slot acquisition; fixture capture/replay support remains limited to retained direct responses and bodyless failures. The separate [`document_storage/catalog_plan.py`](../../../edgar_sec/pipelines/document_storage/catalog_plan.py) remains legacy.
- **Next step:** complete remaining ungated fixture and historical mismatch coverage. Family-aware HTML evaluation, S10 processing, and S11 publication remain deferred or gated.

## Objective

Validate a pinned target plan and resolve executable target rows into transport-ready work orders. Keep catalog-direct provenance explicit without fabricating inventory entries.

## Models

```python
SourceOrigin = Literal["inventory_index", "catalog_direct"]
RetrievalMode = Literal["direct_url", "bundle_sequence"]

@dataclass(frozen=True, slots=True)
class AcquisitionTargetRef:
    plan_id: str
    target_id: str
    accession: AccessionNumber
    request_id: str
    target_role: str
    target_type: str
    optional: bool
    source_origin: SourceOrigin
    target_status: Literal["matched"]
    inventory_entry_id: str | None
    availability_evidence: str
    target_url: str | None

@dataclass(frozen=True, slots=True)
class DirectUrlWork:
    target: AcquisitionTargetRef
    retrieval_mode: Literal["direct_url"]
    fetch_url: str
    document_path: str
    observed_size: int | None

@dataclass(frozen=True, slots=True)
class BundleSequenceWork:
    target: AcquisitionTargetRef
    retrieval_mode: Literal["bundle_sequence"]
    bundle_url: str
    sequence: int
    expected_filename: str | None
    expected_document_type: str | None
    observed_child_size: int | None

AcquisitionWork = DirectUrlWork | BundleSequenceWork

@dataclass(frozen=True, slots=True)
class SkippedTarget:
    target_id: str
    reason: Literal[
        "target_not_matched", "unsupported_retrieval_mode", "candidate_not_authorized"
    ]

@dataclass(frozen=True, slots=True)
class AcquisitionWorkOrder:
    plan_id: str
    ready: tuple[AcquisitionWork, ...]
    skipped: tuple[SkippedTarget, ...]
```

## Interface

```python
load_acquisition_work_order(
    plan_dir: Path,
    parquet_path: Path,
) -> WorkOrderProjection
```

The implementation returns plan pins, schema versions, row/executable/skipped counts,
and the projected Parquet path. Rows are validated and written in bounded batches;
they are not returned as an in-memory target list.

The loader verifies the target-plan manifest, target-part digests, required
`catalog_plan_id`/digest, nullable `inventory_snapshot_id`/digest, profile and
schema versions. It does not open or revalidate the original catalog plan or
inventory snapshot: the S6 bundle is self-contained. A null inventory pin is valid
only for catalog-only primary plans. It selects only `status="matched"` rows with
`direct_url` or `bundle_sequence`; other outcomes, including
`accession_not_indexed`, are retained in `skipped` and cause no HTTP request. A
constructed package candidate is not executable in S9 without explicit S0
authorization.

For an `inventory_index` direct target, `fetch_url` is the observed URL in
`target_url`. For a `catalog_direct` target, it is the catalog-derived URL
already pinned in the plan. For a bundle target, `target_url` contains the
accession's advertised bundle URL and the target row supplies an exact sequence.
S6 sets `source_origin="inventory_index"` for every row whenever an inventory
snapshot is selected; there is no catalog-path fallback for a missing indexed
accession. The plan is self-contained for acquisition. Catalog-direct bundle
extraction is not part of v1.

`document_path` is the URL path relative to the accession's archive directory, not the full URL path. This preserves the route distinction in `domain.document.route`: an XSL rendering path contains a subdirectory, while a root file is flat. Bundle extraction uses the selected `<FILENAME>` with `content_route()` instead.

For a successful direct fetch, S9 sets `selected_filename` from the validated document-path basename. For a bundle target, it uses the actual selected SGML header filename; the expected inventory filename is only a consistency check.

Every direct or bundle URL must satisfy the S6 archive-locator contract: HTTPS, exact
host `www.sec.gov`, no user information/port/query/fragment, and a path under
`/Archives/edgar/data/{filing_cik}/{accession_without_hyphens}/` for the same target
accession. `filing_cik` is the unpadded numeric CIK encoded by the accession prefix.
The bundle URL must be the canonical hyphenated-accession `.txt` file at that directory;
direct documents may be nested beneath it. Reject dot segments, encoded separators,
backslashes, and paths outside the accession directory. Use parsed URL components and
the shared SEC archive URL parser; never use raw prefix checks or target text as a
filesystem path. Redirects must remain on `www.sec.gov` and inside the same accession
directory. Direct-target size is advisory; the observed response size remains
authoritative.

## Tests

- Plans with both source pins and plans with a null inventory pin validate without
  reopening either upstream source; a null snapshot pin is limited to catalog-only
  primary plans.
- Inventory-index and catalog-direct rows with `direct_url` produce the same work shape and retain distinct `source_origin` values.
- `accession_not_indexed` is not a matched acquisition target and is skipped without
  broker calls.
- Bundle work uses the target row's pinned `target_url` and requires a positive sequence.
- Missing target-plan parts, digest failures, unsafe URLs, and invalid source provenance are refused before network work.
- Non-matched and unauthorized candidate rows are skipped without broker calls.
- The target plan and its source artifacts remain unchanged.

## Acceptance criteria

Each work order is reproducible from a validated target-plan bundle. The source identity and digest remain provenance fields, not runtime reads. No target selector is re-evaluated, no missing sequence is guessed, and catalog-direct provenance never becomes an `InventoryEntry`.
