# S8 — Snapshot DAG Compaction, Lineage Retention, and Pruning

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S8**; the detailed
  contract for S8 is in
  [inventory_snapshot.md](../inventory_snapshot.md) §7.
- Status: shared DAG compaction and retention primitives are implemented. The generic
  and inventory-relation tests now verify scoped-mask removal from compacted Parquet
  output and pass the runtime logical-fingerprint gate. They do not verify public query
  parity, byte-identical files, or deletion of the immutable source node. Staging cleanup
  and source-retention policy remain open.
- Depends on: S5 cumulative snapshot.
- Non-blocking: downstream processing.

## Current implementation evidence and blockers

- `edgar_sec/infra/storage/dag/compaction.py` implements schema-driven checkpoint
  compaction and logical-fingerprint parity; `retention.py` implements graph reachability
  analysis and locked removal of unreferenced snapshot directories.
- `edgar_sec/infra/storage/dag/cli.py` resolves the inventory relation specs for
  compaction and exposes generic `compact` and `gc` operations. Inventory relation
  definitions live in `edgar_sec/pipelines/document_inventory/snapshot/specs.py`.
- `tests/infra/storage/dag/test_compaction.py::test_compact_lineage_scoped_mask_purging`
  and `tests/pipelines/document_inventory/snapshot/test_specs.py::test_inventory_relations_compaction_parity`
  pass. They establish the runtime logical-fingerprint check and that compacted output
  excludes replaced rows. Logical equality is not byte-for-byte Parquet equality, and
  source snapshot files remain immutable until separate GC removes their node.
- The tests do not compare canonical inventory query results, row-group/compression
  settings, duplicate rejection, or digest validation. GC discovers catalog branch/tag
  roots and accepts optional caller-supplied pins; it does not inspect planning bundles.
  Campaign retention should use an explicit DAG tag rather than a plan-directory scan.
- GC prunes whole snapshot directories and has no independent cross-manifest physical
  part-reference check. Confirm node-local part ownership before treating this as a
  general part-purge guarantee. `analyze_retention` accepts `min_age_seconds` but does
  not apply it. Transient staging TTL/lease cleanup is not implemented.
- Next: add inventory public-query parity and validate node-local part ownership; define
  safe staging cleanup separately from snapshot GC. Do not make target-plan artifacts
  implicit DAG roots.

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
- `retention_policy`: catalog root tags and explicit retention rules. The DAG layer does
  not discover pipeline-owned target-plan directories.
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

Retention is driven by catalog roots and lineage, not pipeline plan directories:

- **Explicit campaign retention**: A plan records its source snapshot ID and digest but
  does not mutate the DAG. If an operator needs that snapshot retained beyond reachable
  branch lineage, create a DAG tag. The tag is an in-catalog root; the plan writer does
  not create it automatically.
- **Part ownership**: The current collector removes unreachable node directories. Safe
  purge relies on part files being node-local and parent references retaining required
  ancestors; verify this storage invariant before adding more aggressive part cleanup.
- Purge is an explicit, auditable operation separate from compaction.

## Staging cleanup safeguards

- Cleanup of `transient/{run_id}/` is strictly separated from snapshot vacuum.
- A TTL alone must **never** delete a still-active run.
- Staging cleanup requires:
  1. Age exceeding the configured TTL (e.g. 24 hours).
  2. An explicit inactive/lease check confirming no running process holds a lock or
     active task heartbeat on that run ID.
   3. Verification that no manifest has unresolved references to that staging path.

Target-plan retention tags do not substitute for active-worker lease checks on transient
run directories. The generic DAG collector does not own or inspect those directories.

## Tests

- Compaction preserves accession, form, document-type, filing-CIK, and source-CIK query results.
- Consolidated Parquet parts adhere to 128k row group size and zstd compression.
- Source/page counts and identities remain stable after compaction.
- Logical fingerprint parity holds between uncompacted and compacted representations.
- Zero HTTP requests occur during vacuum, parity verification, or purge.
- Pointer atomicity: readers of the old `current` see the old snapshot while the new
  pointer is published, and never see a partially written new snapshot.
- Tagged-source retention: a snapshot explicitly tagged for a campaign remains reachable
  regardless of whether its original branch advances. Target-plan directories are not
  scanned or treated as implicit DAG roots.
- Part ownership: compaction and GC must preserve every part reachable through retained
  node lineage; verify node-local part ownership before claiming independent part-level
  pruning safety.
- Staging cleanup safeguards: active run directories under lock are preserved even if older than TTL.
- A vacuum that would change nothing returns `NoOp` without writing parts.
- Uniqueness keys are strictly enforced; duplicate accessions or relationships fail compaction.

## Acceptance criteria

Vacuum compacts annual parts and accession/filing-CIK/source-CIK lookup shards offline adhering to
128k-row zstd Parquet standards, enforces uniqueness and digest validation, verifies
logical and public-query parity before publication, respects catalog branch/tag roots
and verified part ownership, safeguards staging cleanup with lease checks, and publishes
the new `current` pointer atomically. No page response is fetched.
