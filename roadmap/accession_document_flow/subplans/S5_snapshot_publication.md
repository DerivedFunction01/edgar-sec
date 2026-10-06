# S5 — Immutable Inventory Snapshot Publication

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S5**; the detailed
  contract for S5 is also in
  [inventory_snapshot.md](../inventory_snapshot.md).
- Status: first implementation subplan; cumulative, queryable snapshot from the first
  publication.
- Depends on: S1 cohort contract, S2 index fixture store, S3 parser, S4 broker+worker.
- Non-blocking: S6–S10 design (consumers, not implementers).

## Objective

Publish the first cumulative, queryable snapshot: anti-join by accession before any
HTTP, merge new co-filer CIK edges without refetching known accessions, publish
form/year data parts plus accession/CIK seek indexes, and atomically advance `current`
only after the complete snapshot is validated. No target profile or payload field
enters the snapshot.

## Contract

`build_inventory(cohort, base_snapshot, explicit_refresh=False) -> SnapshotPublication`

- `cohort`: the S1 `InventoryCohort` with validated, de-duplicated accessions.
- `base_snapshot`: the current snapshot to anti-join against; `None` for the base run.
- `explicit_refresh`: force re-read of all cohort index pages.

Returns one of: `published(snapshot)`, `no_op(parent_snapshot)`, or `failed(reason)`.

## Run intent and immutable identity

Before fetch, `run_intent_id` hashes the current snapshot ID, the canonical cohort
fingerprint, parser/schema/lookup versions, and an optional explicit-refresh salt. An
exact completed intent is validated and reused without HTTP. The immutable
`snapshot_id` hashes the parent snapshot ID, changed accession page digests, new
CIK/accession edges, and schema/lookup versions. A no-op cohort returns the parent
ID; explicit refresh creates a new page observation only if the source digest
changes.

## Anti-join by accession

1. Validate the catalog plan and aggregate its rows by accession; validate consistent
   form/filing/report dates and sort/deduplicate source CIKs.
2. Read `current/pointer.json` and the accession lookup; anti-join candidates by
   **accession only**, not by `(source_cik, accession)`, locator, or plan ID.
3. For an accession already indexed, compare filing metadata, append any previously
   unseen `(accession, source_cik)` relationships, and reuse its index page/entries
   without HTTP.
4. Fetch and parse only accessions absent from the current snapshot. Publish new
   accession rows, entries, source relationships, and lookup deltas as one immutable
   child snapshot; write `current` last.

An accession whose form/date metadata conflicts is refused before fetch; it is not
silently re-indexed. Snapshot updates are serialized per inventory root; readers
remain lock-free against immutable snapshots. A writer whose expected parent no
longer matches `current` refuses before pointer publication; a retry re-anti-joins
against the new parent and reuses cached or fixture-page responses.

## Fetch and publish policy

- If any page fetch or parse fails, publish no snapshot.
- A retry validates the same base/cohort intent and rebuilds staging from verified
  SEC-cache or fixture-page responses; no per-accession checkpoint machinery is
  added.
- A changed page body is accepted only through explicit refresh and creates a new
  immutable observation version.
- No target profile or payload field enters the snapshot.

## Physical publication

Write to staging under `{snapshot_id}/`, then atomically publish:

- form/year Parquet partitions for `accessions`, `entries`, and `accession_sources`;
- the `accession` and `source_cik` lookup shards;
- `manifest.json` listing every part with key range, row count, byte size, digest,
  and lookup-layout version;
- `current/pointer.json` last.

Validation before `current` advances: row counts, hashes, referential integrity,
co-filer equality, and query parity for accession, filing form, and source CIK.

## Tests

- Same-accession/multi-plan CIK union causes exactly one index-page request.
- A queryable `current` snapshot exists after each successful build.
- An exact accession query returns all child rows and co-filer CIKs.
- A form query selects only matching form/year partitions and returns exact rows.
- No query makes HTTP requests.
- Explicit refresh re-reads sources and produces a new snapshot when the digest
  changes.
- Unchanged bytes reuse the parent's content (no-op cohort returns parent ID).
- Bad lookup/schema/digest inputs are refused.
- An interrupted stage is invisible to readers (old `current` unchanged).
- No partial publication after a page error.
- Concurrent writers serialize; a writer with a stale parent refuses before
  publishing.
- `snapshot_id` changes on changed accessions and is stable for unchanged cohorts.
- Manifest digests match the published parts.
- Lookup shards select a single shard for a point accession lookup.
- CIK query resolves via the CIK shard and accession index without scanning all
  accessions.
- A form+CIK combined filter intersects the form partition with CIK postings rather
  than scanning all accessions.

## Acceptance criteria

The cumulative queryable snapshot is published in the first build: accessions are
anti-joined against `current` by accession before HTTP, new co-filer CIK edges are
merged without refetching known accessions, form/year parts and accession/CIK seek
indexes are published, and `current` advances atomically after full validation. No
target profile or payload field enters the snapshot; a failed fetch or parse publishes
nothing.
