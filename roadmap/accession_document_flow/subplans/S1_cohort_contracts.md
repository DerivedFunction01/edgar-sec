# S1 — Cohort Projection and Inventory-Domain Contracts

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S1**.
- Status: schema and contract design before the parser and worker stages.
- Depends on: S0 evidence for URL construction rules; the S1 catalog adapter uses the
  existing `filing_catalog` bundle interface.
- Non-blocking: S2 index fixture store, S3 parser, S5 snapshot, S6 target planning.

## Objective

Specify the inventory-domain model and a narrow cohort reader that projects a filing
cohort to physical work by accession. Deduplicate physical work at the accession grain,
retain CIK associations as unique relation rows, require agreement on form/filing date
and any present report dates, construct the `-index.html` URL from accession identity,
and ignore document-path locators.

## Inputs

- Published `filing_catalog` bundle: `manifest.json`, `catalog.parquet`, and any
  required companion parts.
- Dedicated inventory fixture cases for testing.
- The S1 cohort model below; exact row grains and refusal rules are fixed here.

## Output contracts

### `InventoryCohort`

A cohort is a collection of accession-level observations contributed by one source.

| Field | Contract |
|---|---|
| `cohort_id` | Stable identity of the contributing catalog plan or fixture. |
| `accession` | Canonical `AccessionNumber`. |
| `source_cik` | Canonical `Cik` contributing this observation. |
| `form` | Filing form; agreement required across sources for the same accession. |
| `filing_date` | Validated ISO date; agreement required across sources. |
| `report_date` | Validated ISO date, nullable. |

Deduplicate to physical work by `(accession)`; the `(accession, source_cik)` pair is a
relation, not a fetch key. Require agreement on `form` and `filing_date`; a conflict
refuses the cohort before any network work. Union and sort `source_cik` values. Ignore
`document_path` and `primary_document`; they select no document and enter no observed
row.

### `AccessionInventory`

One row per canonical accession contributed to the run.

| Field | Contract |
|---|---|
| `accession` | Canonical `AccessionNumber`. |
| `source_ciks` | Sorted, de-duplicated source CIK list for the run. |
| `form` | The agreed filing form. |
| `filing_date` | The agreed filing date. |
| `report_date` | Nullable agreed report date, or null. |
| `cohort_sources` | Contributing `cohort_id` values, sorted. |

### `InventoryEntry`

One row per source table row; identity is stable and derived.

| Field | Contract |
|---|---|---|
| `entry_id` | Deterministic SHA-256 over `[accession, table_kind, row_ordinal, index_sha256]`. |
| `accession` | Parent accession. |
| `table_kind` | `document_format` or `data_file`. |
| `row_ordinal` | Source order within its table. |
| `sequence` | Nullable source sequence. |
| `document_type` | Nullable source statutory type. |
| `document_label` | Nullable visible Document-cell text. |
| `description` | Nullable source description. |
| `filename` | Nullable unambiguous source filename. |
| `href` | Nullable original href. |
| `archive_url` | Nullable resolved, same-accession SEC archive URL. |
| `byte_size` | Nullable advertised child size. |

### `AccessionSource`

One row per unique `(accession, source_cik)` relationship contributed by the run,
including the `cohort_id` that first contributed it.

## Cohort reader

The reader serves only published `filing_catalog` bundles plus dedicated fixture cases:

1. Read the bundle manifest and validate its schema version and required parts.
2. Project catalog rows to `(cohort_id, accession, source_cik, form, filing_date,
   report_date)`.
3. Group by accession; validate and union `source_cik`, and check `form`/`filing_date`
   agreement.
4. Construct the `-index.html` URL from the canonical accession identity: the decimal
   value of the accession's first ten digits for the archive CIK segment and the
   accession with punctuation removed for its directory segment.
5. Emit `InventoryCohort`/`AccessionInventory`/`AccessionSource` rows in stable order.

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
