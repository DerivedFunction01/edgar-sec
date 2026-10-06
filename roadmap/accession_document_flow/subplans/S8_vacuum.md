# S8 — Snapshot Vacuum and Lookup-Index Compaction

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S8**; the detailed
  contract for S8 is in
  [inventory_snapshot.md](../inventory_snapshot.md) §7.
- Status: metadata-only compaction and lookup-shard rebuild; it does not re-fetch or
  alter logical inventory facts.
- Depends on: S5 cumulative snapshot.

## Objective

Compact form/year parts and accession/source-CIK lookup shards offline, rebuild the
seek indexes, enforce uniqueness and digest validation, verify query parity, manage
dependency-aware retention, and atomically publish a new `current` pointer. Cumulative
snapshots, co-filer merging, point/form queries, and the anti-join are already part of
S5, not deferred to vacuum.

## Contract

```text
vacuum(snapshot_id, retention_policy) -> SnapshotPublication | NoOp
```

- `snapshot_id`: the base snapshot to compact.
- `retention_policy`: the set of referenced target plans and child snapshots to
  retain.
- Returns a compacted snapshot, or `NoOp` when compaction would change nothing.

## Compaction steps

1. Merge accession, entry, and source-CIK deltas; enforce unique accession and
   `(accession, source_cik)` keys.
2. Compact form/year parts, sort by their query keys, and rebuild accession and CIK
   lookup shards and manifest key ranges.
3. Validate row counts, hashes, referential integrity, co-filer equality, and query
   parity for accession, filing form, and source CIK.
4. Keep source snapshots while retained target plans or child snapshots reference
   them; purge only in a dependency-aware pass that never mutates a source snapshot.
5. Make no HTTP requests. A changed query layout creates a new immutable snapshot with
   the same logical inventory fingerprint when row facts are unchanged.
6. Publish the compaction atomically: new parts and shards are written to staging,
   validated, then `current/pointer.json` is advanced.

## Retention

Retention is driven by references, not age:

- Target plans referencing a snapshot prevent its purge.
- Child snapshots referencing a parent snapshot prevent its purge.
- Reference resolution reads published manifests; an unresolved reference is treated
  as a live retention obligation.
- Purge is a separate, auditable operation from compaction.

## Query-parity verification

Before `current` moves, vacuum re-runs the three canonical queries against the
uncompacted base and the compacted staging:

- `get_accession(accession)` for a sample of accessions.
- `query_filings(form=..., source_cik=...)` for the selected form/year partitions.
- `query_entries(accession=..., document_type=...)` for selected entry filters.

Results must be byte-identical in logical content; only part/row-group locators and
manifest digests differ. Query parity is a publish precondition, not a post-check.

## Tests

- Compaction preserves accession, form, document-type, and CIK query results.
- Source/page counts and identities remain stable after compaction.
- No HTTP request occurs during vacuum or retention purge.
- Pointer atomicity: readers of the old `current` see the old snapshot while the new
  pointer is published, and never see a partially written new snapshot.
- Retained-plan dependencies: a plan still referencing an old snapshot prevents its
  purge.
- Lock-free readers of old snapshots: a reader can enumerate the old snapshot while
  vacuum compacts it.
- An interrupted or conflicting vacuum cannot move `current`.
- A vacuum that would change nothing returns `NoOp` without writing parts.
- Lookup shards remain single-shard-selectable after rebuild.
- Manifest key ranges are consistent with part contents.
- Purge mutates only unreferenced snapshots.
- A changed query layout without row changes produces a new snapshot with the same
  logical fingerprint.
- Uniqueness keys are enforced: duplicate accessions or `(accession, source_cik)`
  pairs are rejected.

## Acceptance criteria

Vacuum compacts form/year parts and accession/source-CIK lookup shards offline,
enforces uniqueness and digest validation, verifies query parity before publication,
respects dependency-aware retention, and publishes the new `current` pointer
atomically. Cumulative snapshots, co-filer merging, point/form queries, and the
anti-join remain S5 work. No page response is fetched; an interrupted or conflicting
vacuum cannot move `current`.
