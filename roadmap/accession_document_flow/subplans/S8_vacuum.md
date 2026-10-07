# S8 — Snapshot DAG Compaction, Lineage Retention, and Pruning

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S8**; the detailed
  contract for S8 is in
  [inventory_snapshot.md](../inventory_snapshot.md) §7.
- Status: metadata-only DAG compaction and lineage retention; it does not re-fetch or
  alter logical inventory facts.
- Depends on: S5 cumulative snapshot.
- Non-blocking: downstream processing.

## Objective

Compact DAG delta lineages into consolidated checkpoint nodes, verify logical query
parity, manage dependency-aware retention, and prune unreachable part files offline.
Enforce uniqueness and digest validation, and atomically publish a new `current`
pointer. Cumulative snapshots, source-CIK edge merging, point/form queries, and the
anti-join are already part of S5, not deferred to vacuum.

## Contract

```python
def vacuum(
    snapshot_id: str,
    retention_policy: RetentionPolicy,
) -> SnapshotPublication | NoOp: ...
```

- `snapshot_id`: the base snapshot to compact.
- `retention_policy`: the set of referenced target plans, live manifests, and
  retention rules.
- Returns a compacted snapshot publication, or `NoOp` when compaction would change nothing.

## Compaction mechanics

1. Merge annual accession, entry, and `accession_sources` deltas per `year=YYYY/`.
2. Enforce primary key uniqueness: unique canonical accession in `accessions`, unique
   `(accession, table_kind, row_ordinal)` in active `entries`, and unique
   `(accession, source_cik)` in `accession_sources`.
3. Sort annual parts by `(form, filing_date, accession)`. Write consolidated Parquet
   parts adhering strictly to the repository contract:
   - `row_group_size = 128_000`
   - `compression = "zstd"`
4. Calculate consolidated `key_min`/`key_max` bounds from Parquet footer metadata
   via `read_parquet_key_bounds()` for each consolidated part.
5. Zero HTTP requests. Logical inventory facts are unchanged.

## Logical parity verification gate

Before `current/pointer.json` can move to the compacted snapshot, vacuum executes a
mandatory verification gate:

1. **Logical Fingerprint Parity**: Compute an order-invariant hash of all active
    accessions (including derived filing CIKs), entries, and source-CIK relations in the uncompacted base vs. the
   compacted staging. Row counts, fields, and logical contents must be identical.
2. **Canonical Query Sampling**: Re-run the canonical query suite against both base
   and compacted staging:
   - `get_accession(accession)` for sampled accessions.
   - `query_filings(form=..., filing_date_range=...)` across all years.
   - `query_entries(accession=..., document_type=...)` for active entries.
     - `query_filings(source_cik=...)` via DuckDB lineage view with pushdown filter.
     - `query_filings(filing_cik=...)` via DuckDB lineage view with pushdown filter.
3. Query parity is a strict publish precondition. Any divergence halts compaction and
   leaves `current` unchanged.

## Dependency-aware retention

Retention is driven by actual part references and active plan pointers, not age alone:

- **Plan Reference Protection**: Any snapshot pinned by an active target plan
  (`document_planning/plans/*/manifest.json`) is protected from deletion.
- **Live Part Dependencies**: Distinguish parent lineage from actual part dependencies.
  A compacted snapshot references only its consolidated parts; an older snapshot is
  pruned only when **no** live manifest references any of its physical parts.
- Purge is an explicit, auditable operation separate from compaction.

## Staging cleanup safeguards

- Cleanup of `transient/{run_id}/` is strictly separated from snapshot vacuum.
- A TTL alone must **never** delete a still-active run.
- Staging cleanup requires:
  1. Age exceeding the configured TTL (e.g. 24 hours).
  2. An explicit inactive/lease check confirming no running process holds a lock or
     active task heartbeat on that run ID.
  3. Verification that no manifest has unresolved references to that staging path.

## Tests

- Compaction preserves accession, form, document-type, filing-CIK, and source-CIK query results.
- Consolidated Parquet parts adhere to 128k row group size and zstd compression.
- Source/page counts and identities remain stable after compaction.
- Logical fingerprint parity holds between uncompacted and compacted representations.
- Zero HTTP requests occur during vacuum, parity verification, or purge.
- Pointer atomicity: readers of the old `current` see the old snapshot while the new
  pointer is published, and never see a partially written new snapshot.
- Retained-plan dependencies: a plan still referencing an old snapshot prevents its purge.
- Part dependency tracking: uncompacted parts are deleted only when unreferenced by any live snapshot.
- Staging cleanup safeguards: active run directories under lock are preserved even if older than TTL.
- A vacuum that would change nothing returns `NoOp` without writing parts.
- Uniqueness keys are strictly enforced; duplicate accessions or relationships fail compaction.

## Acceptance criteria

Vacuum compacts annual parts and accession/filing-CIK/source-CIK lookup shards offline adhering to
128k-row zstd Parquet standards, enforces uniqueness and digest validation, verifies
logical parity before publication, respects dependency-aware retention for active plans
and live parts, safeguards staging cleanup with lease checks, and publishes the new
`current` pointer atomically. No page response is fetched.
