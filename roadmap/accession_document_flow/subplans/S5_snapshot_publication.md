# S5 — Immutable Inventory Snapshot Publication

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S5**; the detailed
  contract for S5 is also in
  [inventory_snapshot.md](../inventory_snapshot.md).
- Status: production build flow (`build_inventory`), streamed pre-fetch projection and
  work-order generation, S4 execution, validated-attempt merge, snapshot validation,
  serialized installation, stale-parent refusal, pointer-last publication, and reader/
  query commands are implemented. Entry supersession uses DAG `scoped_mask` through
  `INVENTORY_ENTRIES_SPEC`, but the planned explicit prior-entry-ID mapping is not
  persisted. Offline test coverage exists; historical parser acceptance and live
  operational rollout remain gated by S0.
- Depends for operational publication on: S1 cohort contract, S3 parser body, and S4
  integrated broker+worker. S2 remains research/replay input, not a production writer.
- Non-blocking: S6 target planning and S9–S10 acquisition/processing (read-only
  consumers, not inventory writers).

## Objective

Publish the first cumulative, queryable snapshot: anti-join by accession before any
HTTP, merge new cohort source-CIK edges without refetching known accessions, publish
dense annual data parts plus accession/filing-CIK/source-CIK seek indexes, and atomically advance `current`
only after the complete snapshot is validated. No target profile or payload field
enters the snapshot.

## Contract

`build_inventory(catalog_plan_id, base_snapshot=None, explicit_refresh=False, chunk_size=None, retry_failures=False) -> SnapshotPublication`

The build consumes S4's validated transient Parquet chunk references. S4 owns only its
identity-bound worker checkpoints; S5 reads them in bounded batches into separate
publication staging and owns every canonical Parquet relation. S4 workers never write
files. Typed outcomes may be supplied directly in isolated writer tests, but those
tests do not stand in for the S3 parser or full pipeline integration.

Production input is a validated, published `filing_catalog` plan. S5 streams its
declared Parquet parts and performs accession aggregation, conflict checks, source-CIK
relation construction, and pre-fetch anti-join in resource-configured DuckDB. S5 does
not first build a tuple-wide `InventoryCohort`, collect DuckDB results with `fetchall()`,
or keep the current snapshot's keys in Python sets. The S1 `InventoryCohort` remains
useful for small offline unit tests, not the production-scale build boundary. A sorted,
unique accession/URL work order is written to the run's transient tree and passed to
S4. It is not a separately published inventory-plan artifact. Temporary cohort
relations and the work order live under the transient run root; the work order is
referenced by the run manifest, not by the published snapshot.

- `catalog_plan_id`: a discovered published catalog-plan ID whose manifest and declared
  parts validate and whose observations project to a consistent accession relation;
  callers do not provide arbitrary plan paths.
- `base_snapshot`: the current snapshot to anti-join against; `None` for the base run.
- `explicit_refresh`: force re-read of all cohort index pages.

Returns one of: `published(snapshot)`, `no_op(parent_snapshot)`, or `failed(reason)`.

## Run intent and immutable identity

Before fetch, `run_intent_id` hashes the current snapshot ID, the canonical cohort
fingerprint, parser/schema/lookup versions, S4 work-order version and chunk size, and
an optional explicit-refresh salt. An exact completed intent is validated and reused
without HTTP. S4 pins that identity and the exact missing-accession worklist in its
run manifest; worker count and other machine-local resources do not affect identity.
The `run_intent_id` is also the transient run-directory ID.
The immutable
`snapshot_id` hashes the parent snapshot ID, changed accession page digests, new
cohort CIK/accession edges, and schema/lookup versions. A no-op cohort returns the
parent ID; explicit refresh creates a new page observation only if the source
digest changes.

## Anti-join and distinct CIK semantics

1. Validate the catalog plan and aggregate its rows by accession; validate consistent
   form/filing/report dates and write normalized accession and source-CIK relations.
   Projection is streaming/relational; it does not call S1 `project_cohort` on the full
   production plan.
2. CIK meanings remain distinct:
   - `filing_cik` is the canonical first ten digits of the accession (the filing
     entity) and has a distinct lookup from source-CIK associations.
   - `source_cik` records catalog/cohort associations in the `accession_sources`
     relation table. It represents discovery provenance, not a verified legal
     co-filer roster.
   - **Do not duplicate relationships in a `co_filers` list on each accession row.**
     Adding a new source-CIK association appends a row to
     `accession_sources/year=YYYY/` with zero page refetches and no rewrite of
     the accession facts.
3. Read and validate `current/pointer.json` and its accession relation; anti-join
   candidates by **accession only**, not by `(source_cik, accession)`, locator, or plan
   ID. Write the sorted, unique missing-accession work order before any SEC request.
4. For an accession already indexed, compare filing metadata, append any previously
   unseen `(accession, source_cik)` relationships, and reuse its index page/entries
   without HTTP.
5. Fetch and parse only accessions absent from the current snapshot through S4. Consume
   its committed chunk references and write bounded temporary batches; collect failures
   without dropping sibling results. If any outcome failed or is unrecognized, discard
   publication staging and leave `current` unchanged, while retaining valid S4 chunks.
6. Externally sort staged rows by the physical keys below using DuckDB configured from
   `derive_resources()` (`threads`, `memory_limit`, `temp_directory`, and
   `preserve_insertion_order=false`). Emit annual parts and delta manifests, validate the
   complete child snapshot, then atomically write `current` last.

Candidate and current relations stay on disk or inside DuckDB-managed temporary storage.
Only bounded Arrow/fetch batches and per-chunk S4 work items may be materialized in
Python. S4 must accept the missing-accession work order as a stream or Parquet-backed
source; passing the complete anti-join result through an in-memory sequence is not a
production implementation of this contract.

## Prefetch work-order and recovery boundary

- The filing-catalog plan is the source cohort; S5 creates an identity-pinned transient
  inventory work order after the current-snapshot anti-join. There is no second
  published inventory-plan artifact.
- The current `snapshot.anti_join.anti_join` consumes already-staged worker outcomes,
  entries, and source edges as a post-fetch delta classifier. The separate
  `snapshot.projection` validates catalog plans and writes the pre-fetch work order.
- S4 owns per-accession progress inside a temporary chunk. One complete parse result's
  outcome, all entries, and completion marker commit atomically in its configured
  transactional progress store. S5 consumes only S4's fully validated chunk Parquet
  pointers; it does not read partial progress journals or introduce a second recovery
  ledger.
- Run locking protects one run's work order and S4 progress. A separate publication
  lock protects the current-parent check, immutable snapshot installation, and final
  pointer update. Snapshot staging may be rebuilt from committed S4 chunks after an
  S5 failure without fetching again.

An accession whose form/date metadata conflicts is refused before fetch; it is not
silently re-indexed. Snapshot updates are serialized per inventory root; readers
remain lock-free against immutable snapshots. A writer whose expected parent no
longer matches `current` refuses before pointer publication; a retry re-anti-joins
against the new parent and may reuse compatible SEC-cache or fixture-page responses.

All published and transient path construction is owned by
`document_inventory.paths`; the snapshot package does not define a second layout.

## Current implementation blockers

- The S0 SEC-page audit still gates final historical parser acceptance and any claim of
  historical/live source coverage. It does not block the implemented offline
  plan-to-snapshot build path.
- Refresh publication masks parent entries for a changed accession from active queries
  and preserves the parent snapshot, but does not persist the explicit prior-entry-ID
  supersession mapping required by the contract below. Current reader tests establish
  active-query behavior only. Decide whether that mapping is required; if retained,
  implement a bounded persisted representation and test its lineage behavior.
- The reader resolves a branch/current tip for queries but does not expose an immutable
  named-snapshot read boundary for downstream planning. Add a reader path that resolves
  one snapshot ID and validates its manifest/parts before S6 streams batches; never let a
  target plan re-read a moving branch pointer.

## Acceptance evidence and next step

- `edgar_sec/pipelines/document_inventory/snapshot/builder.py` connects validated plan
  projection, S4 coordination, and snapshot publication; `snapshot/reader.py` exposes
  active accession, entry, filing-CIK, and source-CIK queries.
- `tests/pipelines/document_inventory/snapshot/test_projection.py` covers bounded
  projection and a 236k-row projection case; `test_builder.py` covers offline build,
  no-op, source-edge addition without refetch, and failed-build refusal;
  `test_writer.py` covers delta publication, validation, stale parents, refresh
  supersession, and publication locking; `test_reader.py` covers active queries and
  scoped-mask supersession.
- The inventory CLI/operator routes build and query operations through the production
  builder/reader. These offline cases do not establish live SEC behavior or S0 historical
  parser coverage.
- No plan-projection, S4 integration, active-query, or pointer-last publisher wiring
  task remains outstanding in this subplan. Next: add named-snapshot reads for S6, resolve
  the explicit supersession-map contract and implement/test it if retained, then complete
  S0's authorized source audit.

## Physical layout: dense annual partitions

The v1 layout uses **dense annual partitions**, avoiding sparse Hive form-directory
explosion while providing backend-neutral query selection:

```text
{artifacts_root}/document_inventory/
  snapshots/{snapshot_id}/manifest.json
  snapshots/{snapshot_id}/accessions/part-*.parquet
  snapshots/{snapshot_id}/entries/part-*.parquet
  snapshots/{snapshot_id}/accession_sources/part-*.parquet
  snapshots/current/pointer.json
```

- Annual parts are sorted by `(form, filing_date, accession)` so Parquet min/max
  statistics prune row groups during form and date queries.
- Worker completion order never determines persisted row order. Staging and sorting
  spill to the configured temp directory rather than collecting all parsed entries in
  Python memory.
- Manifest maps partitions and lookup shards to exact parts, row groups, and key ranges.
- `filing_cik` postings use the accession-prefix CIK; `source_cik` postings use the
  separate catalog/cohort relation. Query APIs never treat them as interchangeable.

## Manifest inheritance and page supersession

1. **Partition Inheritance**: Unmodified annual partitions are inherited directly from
   the parent snapshot. The new `manifest.json` references unchanged part paths and
   digests; physical Parquet files are written only for affected filing years.
2. **Page Supersession & Tombstones**: When an explicit refresh yields a changed page
   digest for an accession, the new snapshot's delta marks the accession's prior
   entries as superseded. Older snapshots retain the previous observation intact,
   while queries against the new snapshot see only the active superseded entries.
   Accession-keyed append-only rows alone are insufficient without this active
   manifest mapping.

## Fetch and publish policy

- If any page fetch or parse fails, publish no snapshot.
- Parser diagnostics remain available to fixture/review artifacts and are not stored
  as a fourth canonical Parquet relation.
- A retry validates the same base/cohort intent, reuses valid completed S4 Parquet
  chunks and valid per-accession progress journals, then rebuilds only S5 publication
  staging. Invalid S4 progress is recomputed by S4; `--retry-failures` is required to
  reattempt committed retryable fetch/worker failures. S5 does not maintain a second
  checkpoint ledger.
- No target profile or payload field enters the snapshot.
- Atomic publication: write S5 staging under
  `transient/document_inventory/{run_id}/publication/`, validate completely, move to
  `document_inventory/snapshots/{snapshot_id}/`, and update
  `snapshots/current/pointer.json` last. S4 checkpoints remain beside, not inside,
  publication staging.

Validation before `current` advances: row counts, hashes, referential integrity,
and query parity for accession, filing form, filing CIK, and source CIK.

## Tests

- Same-accession/multi-plan CIK union causes exactly one index-page request.
- A source-CIK association differing from the accession-prefix filing CIK is queryable only through the correct distinct index.
- A queryable `current` snapshot exists after each successful build.
- An exact accession query returns all child rows and associated source CIKs.
- Form query selects only matching annual partitions and row groups; unrelated years
  and forms are pruned without directory explosion.
- No query makes HTTP requests.
- Explicit refresh re-reads sources and supersedes prior entries only when the
  digest changes; older snapshots remain unaffected.
- Unchanged years reuse parent parts via manifest inheritance (zero-copy deltas).
- No duplicate CIK arrays on accession rows; `accession_sources` records associations.
- Bad lookup/schema/digest inputs are refused.
- An interrupted S5 stage leaves `current` unchanged; retry reuses valid S4 chunks and
  rebuilds publication staging without refetch.
- S4 chunk pointer/manifest/schema/digest mismatches are never consumed as complete.
- Concurrent writers serialize; a writer with a stale parent refuses before publish.
- Manifest digests match all published parts.
- Point accession query resolves via DuckDB predicate pushdown over the
  snapshot's lineage view with `(key_min, key_max)` range pruning.
- Form+CIK combined filter intersects CIK postings with annual form row groups.
- Completion-order worker results produce the same deterministic sorted rows and
  logical fingerprint as accession-order synthetic inputs.
- Filing-CIK and source-CIK queries return distinct expected results; combined
  filters intersect each requested CIK posting with annual row groups.
- A large synthetic filing-catalog plan produces a sorted unique work order without a
  full-plan Python collection; duplicate accessions collapse while source-CIK edges
  remain distinct.
- No SEC request occurs before catalog-plan validation and the pre-fetch anti-join
  complete.
- The production builder derives a transient work order directly from the published
  filing-catalog plan; no second published inventory-plan artifact is created.

## Acceptance criteria

The cumulative queryable snapshot is published in the first build: accessions are
anti-joined against `current` before HTTP, new source CIKs are merged into
`accession_sources` without refetching known accessions, annual parts and seek indexes
are published with zero-copy manifest inheritance, page refreshes supersede older
active entries cleanly, and `current` advances atomically after full validation. No
target profile or payload field enters the snapshot; filing-CIK and source-CIK queries
use distinct indexes; a failed fetch or parse publishes nothing.

The run can be stopped during a chunk and resumed from valid per-parse progress. Every
progress transaction contains one terminal outcome, all entries from that accession's
parse, and its completion marker. A partial entry set is never marked complete. Run
and publication locks prevent same-run writes and stale-parent pointer movement.
