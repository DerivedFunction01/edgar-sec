# S9a — Target-Plan Acquisition Adapter

## Owner and status

- Owning stage in [S9](S9_acquisition.md): acquisition work-order boundary.
- Status: typed adapter contract; no network or body storage.
- Depends on: S6 target-plan schema, S5 snapshot reader for bundle metadata.

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
    selector: str
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
    *,
    inventory_reader: InventorySnapshotReader | None = None,
) -> AcquisitionWorkOrder
```

The loader verifies the target-plan manifest, target table digest, source artifact IDs, and schema versions. It selects only `status="matched"` rows with `direct_url` or `bundle_sequence`; other outcomes are retained in `skipped` and cause no HTTP request. A constructed package candidate is not executable in S9 without explicit S0 authorization.

For an inventory-index direct target, `fetch_url` is the target row's observed URL. For a catalog-direct target, it is the catalog-derived URL already pinned in the plan. For a bundle target, the pinned inventory snapshot resolves the accession's advertised `bundle_url`; the target row supplies an exact sequence. Catalog-direct bundle extraction is not part of v1.

`document_path` is the URL path relative to the accession's archive directory, not the full URL path. This preserves the route distinction in `domain.document.route`: an XSL rendering path contains a subdirectory, while a root file is flat. Bundle extraction uses the selected `<FILENAME>` with `content_route()` instead.

For a successful direct fetch, S9 sets `selected_filename` from the validated document-path basename. For a bundle target, it uses the actual selected SGML header filename; the expected inventory filename is only a consistency check.

URLs must use HTTPS, belong to the SEC archive host policy, and resolve beneath the target accession's archive directory. Validate parsed URL components; never use raw prefix checks or target text as a filesystem path. Direct-target size is advisory; the observed response size remains authoritative.

## Tests

- Inventory-index and catalog-direct rows with `direct_url` produce the same work shape and retain distinct `source_origin` values.
- Bundle work resolves `bundle_url` from the pinned snapshot and requires a positive sequence.
- Missing or mismatched pinned artifacts, digest failures, unsafe URLs, and dangling entry references are refused before network work.
- Non-matched and unauthorized candidate rows are skipped without broker calls.
- The target plan and its source artifacts remain unchanged.

## Acceptance criteria

Each work order is reproducible from a validated target-plan bundle and its pinned sources. No target selector is re-evaluated, no missing sequence is guessed, and catalog-direct provenance never becomes an `InventoryEntry`.
