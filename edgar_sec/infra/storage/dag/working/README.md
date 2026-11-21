# `edgar_sec/infra/storage/dag/working` — the working engine

The DAG's working mechanics over the store core: lineage traversal,
relational resolution, CAS publication, candidate anti-joining, checkpoint
compaction, pruned queries, graph rendering, and retention.

## Purpose

Owns the operations that read and extend a snapshot graph: `traversal`
walks lineage with cycle detection, `resolution` compiles the virtual
views and logical fingerprints, `publication` publishes nodes and moves
branch tips, `anti_join` filters candidate deltas, `compaction` folds
lineage into checkpoints, `query` compiles part-range-pruned views,
`renderer` builds the swimlane graph, and `retention` analyzes and purges
unreferenced snapshots and parts.

## Contracts

- **CAS publication**: a branch tip moves only by compare-and-swap under
  the one exclusive lock; a stale tip leaves the active pointer unchanged.
- **Fail-closed lineage**: a broken parent link halts resolution with
  `BrokenLineageError`; no operation repairs or skips a missing parent.
- **Append-only**: operations record deltas and checkpoints; published
  snapshot content is never rewritten in place.

## Deliberate gaps

- **Secondary inverted index management**: multi-shard seek indexes are
  deferred to domain adapters and checkpoint compaction, per the parent
  package's gaps.
