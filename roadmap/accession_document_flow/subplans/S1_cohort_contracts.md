# S1 — Cohort Projection and Inventory-Domain Contracts

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S1**.
- Status: implemented. Shared records and the durable entry schema live in
  `edgar_sec.domain.document_inventory`; catalog readers and projection remain in the
  pipeline.
- Depends on: the existing `filing_catalog` bundle interface and accession identity
  rules; S0 later audits the resulting URL and source-page assumptions.
- Enables: S2 raw-page capture and S0 audit sampling.
- Non-blocking: S3 parser, S5 snapshot, S6 target planning.

## Acceptance evidence

- `edgar_sec/pipelines/document_inventory/cohort.py` implements catalog snapshot/plan
  validation, row conversion, accession grouping, conflict refusal, and index-URL
  construction.
- `edgar_sec/domain/document_inventory/models.py` and `schemas.py` own the shared
  immutable records and versioned entry schema.
- Offline contract coverage is in `tests/pipelines/document_inventory/test_cohort.py`,
  `tests/domain/document_inventory/test_models.py`, and
  `tests/domain/document_inventory/test_schemas.py`.

No S1 implementation blocker is identified by the current code/test surface. The
separate S0 historical-source audit remains open and does not invalidate these
cohort-contract tests.

## Objective

Specify the inventory-domain model and a narrow cohort reader that projects a filing
cohort to physical work by accession. Deduplicate physical work at the accession grain,
retain CIK associations as unique relation rows, require agreement on form/filing date
and any present report dates, construct the `-index.html` URL from accession identity,
and ignore document-path locators.

## Inputs

- Published `filing_catalog` snapshot: `snapshot.manifest.json` and validated
  `filing_targets/part-*.parquet` parts. S0 uses the broad snapshot as its survey
  frame.
- Published `filing_catalog` target plan: `plan.json` and validated
  `targets/form=.../part-*.parquet` parts. Inventory builds may use a selected cohort
  plan, but it is not presumed to cover S0's strata.
- A small dedicated inventory cohort fixture authored with S1's offline adapter tests;
  it is produced by the S1 implementation, not a pre-existing prerequisite.
- The S1 cohort model below; exact row grains and refusal rules are fixed here.

## Typed models

The published catalog is a row-oriented input. The inventory boundary converts its
string dates and identities into validated values before grouping:

```python
@dataclass(frozen=True, slots=True)
class CohortObservation:
    cohort_source_id: str
    accession: AccessionNumber
    source_cik: Cik
    form: str
    filing_date: date
    report_date: date | None

@dataclass(frozen=True, slots=True)
class AccessionInventory:
    accession: AccessionNumber
    filing_cik: Cik
    source_ciks: tuple[Cik, ...]
    form: str
    filing_date: date
    report_date: date | None
    cohort_sources: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AccessionSource:
    accession: AccessionNumber
    source_cik: Cik
    first_seen_by: str

@dataclass(frozen=True, slots=True)
class IndexWorkItem:
    accession: AccessionNumber
    index_url: str

@dataclass(frozen=True, slots=True)
class InventoryCohort:
    observations: tuple[CohortObservation, ...]
    accessions: tuple[AccessionInventory, ...]
    sources: tuple[AccessionSource, ...]
    work_items: tuple[IndexWorkItem, ...]

```

These immutable records and `inventory_entry_id` live in
`edgar_sec.domain.document_inventory.models`; the versioned durable entry schema lives
in its `schemas.py`. `CohortInputError`, the source readers, and the projection remain
in `pipelines.document_inventory.cohort` because they validate and consume artifacts.

`InventoryEntry` is the S3 parser output after page context is applied:

```python
@dataclass(frozen=True, slots=True)
class InventoryEntry:
    entry_id: str
    accession: AccessionNumber
    table_kind: Literal["document_format", "data_file"]
    row_ordinal: int
    sequence: int | None
    document_type: str | None
    document_label: str | None
    description: str | None
    filename: str | None
    href: str | None
    archive_url: str | None
    byte_size: int | None
```

`filing_date` and `report_date` are `date` values in these models and ISO-8601
strings in Parquet. `InventoryCohort.observations` retains every source contribution
for fixture provenance; `accessions` has one row per accession; `sources` has one
row per unique `(accession, source_cik)`; and `work_items` has one row per accession.
`filing_cik` is derived from the accession's first ten digits and is distinct from
the cohort `source_ciks`. All tuples are sorted by their identity keys. Entry identity
is SHA-256 of canonical JSON for
`[str(accession), table_kind, row_ordinal, index_sha256]`; `row_ordinal` is
zero-based among body rows in its table.

`filename` preserves each readable row value, even when another row repeats it;
it is never a uniqueness key. Target planning must retain ambiguity across rows.

Deduplicate physical work by accession; `(accession, source_cik)` is a relation,
not a fetch key. Form and filing date must agree across all observations. All
present report dates must agree; missing report dates do not conflict with a
present date. Union and sort CIKs. Ignore `document_path` and `primary_document`.
Identical repeated observations for `(cohort_source_id, accession, source_cik)`
collapse; conflicting duplicates are refused. Observation order is
`(accession, source_cik, cohort_source_id)`.

## Operation shapes

```python
read_catalog_observations(
    source_dir: Path,
    cohort_source_id: str,
    source_kind: Literal["catalog_snapshot", "catalog_plan"],
) -> Iterator[CohortObservation]

project_cohort(
    observations: Iterable[CohortObservation],
    *,
    archive_base_url: str,
) -> InventoryCohort

index_url_for(
    accession: AccessionNumber,
    *,
    archive_base_url: str,
) -> str

inventory_entry_id(
    accession: AccessionNumber,
    table_kind: Literal["document_format", "data_file"],
    row_ordinal: int,
    index_sha256: str,
) -> str
```

The index page filename is `{hyphenated_accession}-index.html` inside the compact
accession directory, e.g. `.../320193/000032019323000106/0000320193-23-000106-index.html`.
Use the supplied archive base and an unpadded archive CIK; do not request a file named
`-index.html`.

The reader validates the source-specific manifest and all declared target parts and
yields validated rows; it does not read document locators or perform network work.
Use `catalog_snapshot` for S0 sampling and `catalog_plan` for a selected inventory
cohort. `project_cohort` refuses malformed
rows and conflicting filing facts before returning any work item. The URL builder
uses the accession's first ten digits as archive CIK and its unhyphenated value
as the directory; the archive CIK segment is the integer value of those digits
without leading zeroes. `archive_base_url` supplies only the archive origin/prefix.
For repeated `(accession, source_cik)` observations in one projection,
`first_seen_by` is the lexicographically first `cohort_source_id`; a later snapshot
merge preserves the already-published value.

## Cohort reader

The reader serves only published `filing_catalog` snapshots/plans plus dedicated fixture cases:

1. Validate the source kind's manifest (`snapshot.manifest.json` or `plan.json`) and
   its declared target parts.
2. Project rows to `CohortObservation`, converting identities and ISO dates.
3. Group by accession; validate filing facts and union source CIKs.
4. Construct one `IndexWorkItem` per accession from its canonical identity.
5. Emit all model tuples in stable identity order.

`project_cohort` is an in-memory convenience contract for bounded offline fixtures
and unit tests; it is not the production-scale build boundary. S5 must implement a
streaming/relational projection with the same refusal, accession, and source-CIK
semantics and must not construct `InventoryCohort` for a complete production plan.
The catalog plan is the production input; S5 derives a run-scoped transient work
order after comparing its accession relation with the selected base snapshot. No
separately published inventory-plan artifact is introduced.

Reject unknown or malformed manifests, missing parts, and conflicting form or filing
dates. Transport failures are run results, not successful response rows.

## Tests

- Identity validation: stable `entry_id` from canonical inputs.
- Same accession from many CIKs: one physical work item, multiple relation rows.
- CIK union across plan shards: sorted, de-duplicated, no duplicates.
- Conflicting form/date refusal: cohort rejected before any network request.
- Nullable source fields: null report dates and missing optional fields parse.
- Stable ordering: reproducible ordering independent of input shard order.
- No dependency on `document_storage`: the model imports only foundation, domain, and
  engine layer APIs.

## Acceptance criteria

The cohort reader projects a catalog bundle to accession-level work by accession,
retains CIK associations as unique relation rows, requires form/filing-date agreement,
constructs the index URL from accession identity alone, and ignores document-path
locators. The model is independent of fetched payloads and target intent.
