# Queryable Accession Inventory Snapshot

This subplan defines the persistent index and its query/update behavior. It is
the detailed contract for S5 and S8 in
[implementation.md](./implementation.md). Unlike document payload storage, this
snapshot is designed now and is queryable from the first published version.

## 1. Difference from the Existing Snapshot

The frozen `document_storage` snapshot is downstream of acquisition and
normalization. It indexes occurrences keyed by `occurrence_id` (source CIK,
accession, and document path), splits that index from normalized-text payload
parts, and consolidates run snapshots by document ID and filing quarter. Its
index rows can be searched with local DuckDB, but the physical parts are not
seek indexes for accession/form queries; the payload model is intentionally
part of that snapshot. The owned implementation is in
[`merger.py`](../../edgar_sec/pipelines/document_storage/merger.py),
[`parts.py`](../../edgar_sec/pipelines/document_storage/parts.py), and
[`vacuum.py`](../../edgar_sec/pipelines/document_storage/vacuum.py).

The first accession-inventory draft also had a base metadata snapshot, but
applied the targeting profile during inventory and let cohort-shaped runs drive
when index pages were fetched. This plan changes the grain: the new inventory is an
upstream, cumulative accession directory containing every observed index-page
row. It exists before any selected document is fetched, and a request for a
different target is a query against the same snapshot.

**Current roadmap correction:** a cohort-only snapshot followed later by a
cumulative index is insufficient. If a plan contributes one subset of source-CIK
associations and a later plan contributes another, delaying global accession deduplication causes
repeated page fetches. The initial `current` snapshot, accession/form lookup,
and cross-plan anti-join therefore belong in the first inventory publication;
vacuum and compaction can follow later.

## 2. Queries the Snapshot Must Serve

Every query below is read-only and makes no SEC request. A miss means “not
indexed”; it does not silently fetch a page.

1. **One accession:** return its filing metadata, all observed
   `Document Format Files` and `Data Files` rows (including every document type),
   and its source-CIK associations. This is the query used to inspect one
   accession before planning its primary, exhibits, or data files.
2. **One filing form:** enumerate accessions for a filing form, optionally
   filtered by filing/report date and filing/source CIK, then stream the matching
   inventory entries. It reads only selected annual partitions and row groups;
   the result itself may be large, but unrelated forms are not scanned.
3. **One source CIK:** enumerate associated accessions from an inverse CIK index,
   optionally filter by filing form/date, and return entries through the
   accession lookup. Multiple CIKs associated with one accession do not duplicate
   the physical accession or its observed document rows.

The word *form* is explicit in the query API: `filing_form` filters the filing
(for example, 10-K or Form 4); `document_type` filters an observed child row
(for example, EX-21 or EX-101.SCH). Queries can filter either or both.

The current sample's large form cohorts are the scale targets for query tests.
Tests verify partition/row-group selection and result parity, not fixed corpus
counts. Reading all matches for a form is output-proportional; reading all other
filing forms to find them is not.

## 3. Logical Schema

The logical schema has three tables. The rows remain independent of fetched
payloads and target-plan intent.

### `accessions`

One row per canonical accession:

| Field | Arrow type | Contract |
|---|---|---|
| `accession` | `string` | Canonical `AccessionNumber`; unique physical filing key. |
| `filing_cik` | `string` | Canonical ten-digit CIK in the accession prefix; the filing entity. |
| `form` | `string` | Filing form from the selected catalog cohort. |
| `filing_date` | `string` | Validated ISO date; determines filing-year partition. |
| `report_date` | `string`, nullable | Catalog report date when present. |
| `bundle_url` | `string`, nullable | Advertised full-submission URL, not a child entry. |
| `bundle_size` | `int64`, nullable | Advertised bundle size. |
| `index_url` | `string` | URL of the source `-index.html`. |
| `index_sha256` | `string` | Digest of the exact page parsed for this snapshot. |
| `first_indexed_by` | `string` | Catalog-plan or fixture identity that first indexed this accession. |

### `entries`

One row per child-file row in the two index tables. The `Complete submission text
file` envelope row is excluded here and stored as accession-level bundle metadata.

There is no asset-count cap, target-based filtering, or per-response byte cap: every
body row observed in both tables is stored, including rows with no href and repeated
filenames or sequences. The process count is derived from available memory and CPU;
one unusually large response can exceed the per-worker estimate, and S0 page-size and
parser-memory evidence tunes that estimate. Responses are not truncated or rejected
by S4.

| Field | Arrow type | Contract |
|---|---|---|
| `entry_id` | `string` | SHA-256 of canonical `[str(accession), table_kind, row_ordinal, index_sha256]`. |
| `accession` | `string` | Parent accession. |
| `table_kind` | `string` | `document_format` or `data_file`. |
| `row_ordinal` | `int32` | Zero-based source body-row order within its table; the excluded bundle row still occupies its source position. |
| `sequence` | `int32`, nullable | Source sequence; may be absent or duplicated. |
| `document_type` | `string`, nullable | Source statutory type. |
| `document_label` | `string`, nullable | Visible text in the source Document cell. |
| `description` | `string`, nullable | Source description. |
| `filename` | `string`, nullable | Observed row filename; duplicates across rows are preserved, and null means unavailable on that row. |
| `href` | `string`, nullable | Original href; null is meaningful. |
| `archive_url` | `string`, nullable | Resolved, same-accession SEC archive URL. |
| `byte_size` | `int64`, nullable | Advertised child size. |

Sequence and filename are not keys. The source response digest in `entry_id`
keeps a refreshed page's rows distinct across immutable snapshots. A refresh
replaces the accession's active observed rows in the new snapshot; older
snapshots preserve the prior observation.

### `accession_sources`

One row per unique `(accession, source_cik)` relationship from filing-cohort
plans:

| Field | Arrow type | Contract |
|---|---|---|
| `accession` | `string` | Canonical `AccessionNumber`. |
| `source_cik` | `string` | Canonical `Cik` that brought the accession into a cohort. |
| `first_seen_by` | `string` | Plan/fixture identity that first contributed this relationship. |

The relation is not a fetch key. An accession referenced by 26 CIKs is still one
index-page request and one set of observed entries. The relationship table
supports CIK queries without repeatedly scanning a CIK list embedded in every
entry. Repeated `(accession, source_cik)` pairs from later plans are no-ops.

## 4. Physical Layout: Append-Only DAG Nodes

The snapshot is an append-only DAG of immutable Parquet parts anchored by
periodic checkpoint cuts, not one monolithic Parquet file or one zip that must
be downloaded to query. Each node is a directory containing a manifest and
partitioned Parquet relations defined via declarative `RelationSpec`s:

```text
{artifacts_root}/document_inventory/
  snapshots/{snapshot_id}/manifest.json
  snapshots/{snapshot_id}/accessions/part-*.parquet
  snapshots/{snapshot_id}/entries/part-*.parquet
  snapshots/{snapshot_id}/accession_sources/part-*.parquet
  snapshots/current/pointer.json
```

Within each relation, parts are sorted by the `RelationSpec` sort order so
Parquet min/max statistics prune row groups during form and date queries without
fragmenting into hundreds of sparse form folders. The `accession_sources`
relation is sorted by `(source_cik, accession)`.

**PartDescriptor and key bounds:**
Each part in the manifest is described by a `PartDescriptor` recording
`(path, sha256, row_count, byte_size, key_min, key_max)`. The `key_min`/`key_max`
bounds are extracted from Parquet footer metadata via `read_parquet_key_bounds()`
at publication time, enabling predicate pushdown without physical seek indexes.

**RelationSpecs** define the three canonical relations:
- `accessions`: `upsert` on `accession`, sorted by `(form, filing_date, accession)`
- `entries`: `scoped_mask` on `accession`, sorted by `(accession, table_kind, row_ordinal)`
- `accession_sources`: `append` on `(accession, source_cik)`, sorted by `(source_cik, accession)`

**Manifest inheritance & supersession:**
- Unchanged annual partitions are inherited directly from parent snapshots via
  `manifest.json`, writing new Parquet parts only for affected filing years.
- When an explicit refresh yields changed bytes, active manifest mappings mark
  prior entries for that accession as superseded, while older snapshots preserve
  historical observations intact.

The manifest lists every logical partition and part with its key range, row
count, byte size, digest, and DAG node kind (`checkpoint` or `delta`).

For local artifacts, DuckDB can query the selected files with partition and
row-group pruning. The read interface is also range-oriented: a future remote
object-store or repository adapter reads the manifest, prunes parts via
`(key_min, key_max)` metadata, and only selected Parquet parts/ranges. It must
not download the complete snapshot or fall back to fetching `-index.html` for a
query hit. The first implementation can use local paths; the query planner and
manifest must preserve the same selected-file contract for a later remote backend.

## 5. Cross-Plan Accession Anti-Join

Every inventory project pins the selected branch's tip as its base by default
(`--branch`, default `main`). An explicit base must equal that branch's tip at
projection time. Publish selects the target branch and refuses unless its current
tip still equals the run's pinned base:

1. Validate the catalog plan and aggregate its rows by accession. Validate
   consistent form/filing/report dates; sort and deduplicate source CIKs.
2. Resolve the branch pointer (default `main`) and the accession lookup. Anti-join
    candidates by **accession only**, not by `(source_cik, accession)`, locator, or plan
    ID.
3. For an accession already indexed, compare filing metadata, append any
   previously unseen `(accession, source_cik)` relationships, and reuse its
   index page/entries without HTTP.
4. `inventory run` fetches and parses only accessions absent from the pinned base.
   `inventory publish` publishes validated work as one immutable child snapshot under
   a CAS lock on the selected branch; the pointer moves last.

This is the critical case where one physical accession appears in plans for
different source-CIK contexts. The first plan fetches its `-index.html`
once. A later plan adds a new CIK edge and reuses the current index page. A known
accession whose form/date metadata conflicts is refused before fetch; it is not
silently re-indexed under a second identity.

Before fetch, `run_intent_id` hashes the current snapshot ID, canonical cohort
fingerprint, parser/schema/lookup versions, S4 work-order version and chunk size, and
optional explicit-refresh salt. An exact successfully published intent is validated
and reused without HTTP; if only the worker stage completed, retry reuses its valid
chunks. S4 pins the same identity and exact missing-accession worklist in its run
manifest; machine-local worker count and spill/cache paths are excluded. The immutable
`snapshot_id` hashes the parent snapshot ID, changed accession page digests, new
CIK/accession edges, and schema/lookup versions. A no-op cohort returns the
parent ID; explicit refresh creates a new page observation only if the source
digest changes. Failed fetch, parse, or index validation publishes no snapshot.

S4's attempt-scoped outcome and entry Parquet chunks live under
`{artifacts_root}/transient/document_inventory/{run_intent_id}/`; each is reusable only
after run identity, exact accession membership, schemas, counts, and digests validate.
S5 reads these checkpoints into separate publication staging and never treats them as
snapshot parts. See the [S4 worker contract](subplans/S4_broker_worker.md).

Snapshot updates are serialized per inventory root. Readers remain lock-free
against immutable snapshots. A writer whose expected parent no longer matches the
selected branch's tip refuses before pointer publication; retry re-anti-joins against
the new parent and reuses cached/captured pages. An explicit page refresh is separate
from a source-CIK addition and creates a new page observation only when its digest
changes.

## 6. Query API and Planning Handoff

The implemented reader is a pure snapshot reader with named-snapshot pinning:

```text
get_active_accession(..., snapshot_id=None)
get_active_entries(..., snapshot_id=None)
get_accessions_by_cik(..., snapshot_id=None)
get_accessions_by_source_cik(..., snapshot_id=None)
query_accessions(..., snapshot_id=None)
get_accession_bundle(..., snapshot_id=None)
```

Each function accepts a pinned snapshot ID or resolves the active branch when the ID is
omitted. The point/lookups return a record or materialized list; the API does not expose
a bounded iterator. None of these readers has a broker or fetcher dependency. S6 cannot
import this sibling-pipeline reader under the layer contract and needs bounded source
scans, so its inventory adapter streams through lower-layer DAG APIs using the S5 schema
contract. It writes a separate target-plan artifact; catalog-direct planning is a
separate S6 source adapter.

The S6 adapter resolves the selected branch's tip once before scanning and never
re-reads a moving pointer between batches. It streams the source accessions and applies
profile form rules using S5 Parquet range metadata; it does not add a separate
CIK/cohort filter in v1. A full inventory scan is explicit S6 planning work, not an
accidental query default.

CLI query shapes target the active branch (`current`) or a named snapshot/branch:

```text
inventory query --snapshot current --accession <accession>
inventory query --snapshot <branch> --accession <accession>
inventory query --snapshot current --form <filing-form> [--filing-cik <cik>] [--source-cik <cik>]
inventory query --snapshot current --filing-cik <cik>
inventory query --snapshot current --source-cik <cik>
inventory query --snapshot current --accession <accession> --document-type <type>
```

An accession absent from the selected snapshot is reported as not indexed. Only
`inventory run --run-id ...` fetches missing index pages; `inventory project`,
`inventory status`, and `inventory publish` perform no network work.

`filing_cik` and `source_cik` are separate query predicates: the former is the CIK
encoded in the accession and the latter records catalog/cohort provenance. Both may
be supplied with a form or date filter; if both CIK filters are supplied, results
must satisfy their intersection.

## 7. Vacuum and Snapshot Lifecycle

The first publication installs a complete base snapshot and branch pointer. Every
later project/run/publish cycle publishes an immutable delta snapshot over that base; readers resolve
the manifest's parent/part references. `vacuum` is a metadata-only compaction:

- Merge accession, entry, and source-CIK deltas; enforce unique accession and
  `(accession, source_cik)` keys.
- Compact DAG delta lineages into consolidated checkpoint parts, sort by their
  query keys, and calculate consolidated `key_min`/`key_max` bounds via
  `read_parquet_key_bounds()`.
- Validate row counts, hashes, referential integrity, source-CIK relation equality,
  and query parity for accession, filing form, filing CIK, and source CIK before
  moving `current`.
- Keep source snapshots while retained target plans or child snapshots reference
  them. Purging is dependency-aware; it never mutates a source snapshot.
- Make no HTTP requests. A changed query layout creates a new immutable snapshot
  with the same logical inventory fingerprint when row facts are unchanged.

Borrow immutable snapshot, pointer-last publication, dependency-aware purge,
manifest validation, and compaction concepts from `document_storage`. Do not
borrow its payload parts, occurrence-ID dedup key, quarter-only query layout, or
payload vacuum logic.

## 8. Implementation Subplan and Acceptance

This is an upfront S5/S8 subplan, not a follow-up to be written after the parser
or target planner is implemented. Its interfaces are fixed alongside the cohort,
index fixture, and parser subplans.

### S5a — Queryable cumulative snapshot

Implement the logical tables, declarative `RelationSpec`s, append-only delta and
checkpoint DAG publications, global accession anti-join, new source-CIK edge merge,
immutable parent-linked snapshots, and atomic `current` pointer in the first
snapshot publisher.

**Acceptance:** an accession with source-CIK associations split across independent plan
fixtures causes one index-page request total; later builds update only unseen
CIK relationships. The accession query returns all source rows without SEC
requests. Form queries read only selected row groups and return exact rows;
filing-CIK and source-CIK queries return their distinct expected accessions. A query
against a remote-range test adapter reads the manifest, prunes parts via
`(key_min, key_max)` metadata, and selected row groups, not all snapshot files.

### S8 — DAG compaction, lineage retention, and pruning

Implement DAG lineage compaction into consolidated checkpoint nodes, query-parity
verification, dependency-aware retention, and offline part pruning. Verify query
equivalence before/after compaction and retention of all referenced snapshots.

**Acceptance:** accessions, forms, entries, filing-CIK, and source-CIK queries return the same
logical results after vacuum; no page response is fetched; an interrupted or
conflicting vacuum cannot move `current`.

Normal tests use small synthetic partitions and instrumented I/O. A separate
offline scale exercise uses the larger 10-K/Form 4 sample cohorts to verify that
result cardinality—not the full inventory size—drives the selected data reads.
