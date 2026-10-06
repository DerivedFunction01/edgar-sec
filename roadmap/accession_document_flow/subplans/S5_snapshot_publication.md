# S5 — Immutable Inventory Snapshot Publication

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S5**; the detailed
  contract for S5 is also in
  [inventory_snapshot.md](../inventory_snapshot.md).
- Status: cumulative, queryable snapshot contract; schema, query, and writer work can
  start from synthetic typed outcomes before production parsing is complete.
- Depends for operational publication on: S1 cohort contract, S3 parser body, and S4
  integrated broker+worker. S2 remains research/replay input, not a production writer.
- Non-blocking: S6–S10 design (consumers, not implementers).

## Objective

Publish the first cumulative, queryable snapshot: anti-join by accession before any
HTTP, merge new cohort source-CIK edges without refetching known accessions, publish
dense annual data parts plus accession/filing-CIK/source-CIK seek indexes, and atomically advance `current`
only after the complete snapshot is validated. No target profile or payload field
enters the snapshot.

## Contract

`build_inventory(cohort, base_snapshot, explicit_refresh=False, chunk_size=None, retry_failures=False) -> SnapshotPublication`

The build consumes S4's validated transient Parquet chunk references. S4 owns only its
identity-bound worker checkpoints; S5 reads them in bounded batches into separate
publication staging and owns every canonical Parquet relation. S4 workers never write
files. Typed outcomes may be supplied directly in isolated writer tests, but those
tests do not stand in for the S3 parser or full pipeline integration.

- `cohort`: the S1 `InventoryCohort` with validated, de-duplicated accessions.
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
   form/filing/report dates and sort/deduplicate source CIKs.
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
3. Read `current/pointer.json` and the accession lookup; anti-join candidates by
   **accession only**, not by `(source_cik, accession)`, locator, or plan ID.
4. For an accession already indexed, compare filing metadata, append any previously
   unseen `(accession, source_cik)` relationships, and reuse its index page/entries
   without HTTP.
5. Fetch and parse only accessions absent from the current snapshot through S4. Consume
   its committed chunk references and write bounded temporary batches; collect failures
   without dropping sibling results. If any outcome failed or is unrecognized, discard
   publication staging and leave `current` unchanged, while retaining valid S4 chunks.
6. Externally sort staged rows by the physical keys below using DuckDB configured from
   `derive_resources()` (`threads`, `memory_limit`, `temp_directory`, and
   `preserve_insertion_order=false`). Emit annual parts and lookup shards, validate the
   complete child snapshot, then atomically write `current` last.

An accession whose form/date metadata conflicts is refused before fetch; it is not
silently re-indexed. Snapshot updates are serialized per inventory root; readers
remain lock-free against immutable snapshots. A writer whose expected parent no
longer matches `current` refuses before pointer publication; a retry re-anti-joins
  against the new parent and may reuse compatible SEC-cache or fixture-page responses.

## Physical layout: dense annual partitions

The v1 layout uses **dense annual partitions**, avoiding sparse Hive form-directory
explosion while providing backend-neutral query selection:

```text
{artifacts_root}/document_inventory/
  snapshots/{snapshot_id}/manifest.json
  snapshots/{snapshot_id}/accessions/year=<YYYY>/part-*.parquet
  snapshots/{snapshot_id}/entries/year=<YYYY>/part-*.parquet
  snapshots/{snapshot_id}/accession_sources/year=<YYYY>/part-*.parquet
  snapshots/{snapshot_id}/lookups/accession/shard=<key>/part.parquet
  snapshots/{snapshot_id}/lookups/filing_cik/shard=<key>/part.parquet
  snapshots/{snapshot_id}/lookups/source_cik/shard=<key>/part.parquet
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
  chunks, and rebuilds only S5 publication staging. Incomplete or invalid S4 chunks
  are recomputed by S4; `--retry-failures` is required to reattempt committed
  retryable fetch/worker failures. S5 does not maintain a second checkpoint ledger.
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
- Point accession query resolves via a single lookup shard.
- Form+CIK combined filter intersects CIK postings with annual form row groups.
- Completion-order worker results produce the same deterministic sorted rows and
  logical fingerprint as accession-order synthetic inputs.
- Filing-CIK and source-CIK queries return distinct expected results; combined
  filters intersect each requested CIK posting with annual row groups.

## Acceptance criteria

The cumulative queryable snapshot is published in the first build: accessions are
anti-joined against `current` before HTTP, new source CIKs are merged into
`accession_sources` without refetching known accessions, annual parts and seek indexes
are published with zero-copy manifest inheritance, page refreshes supersede older
active entries cleanly, and `current` advances atomically after full validation. No
target profile or payload field enters the snapshot; filing-CIK and source-CIK queries
use distinct indexes; a failed fetch or parse publishes nothing.
