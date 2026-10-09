# `edgar_sec/infra/storage/dag` — Schema-agnostic append-only snapshot DAG engine

This package provides generic DAG snapshot mechanics for content-addressed datasets.
It decouples graph traversal, CAS publication, candidate anti-joining, and Checkpoint compaction
from phase-specific schemas and table structures.

## Purpose

Replaces monolithic Copy-on-Write (CoW) partition rewrites with lightweight, append-only
deltas. Upper layers configure declarative `RelationSpec` contracts; this layer compiles
the relational resolution views in DuckDB, enforces cycle immunity and parent digest chains,
and provides two-tier retention analysis.

## Contracts

- **Append-only ingestion:** Deltas record only new or modified Parquet files ($O(\Delta)$).
- **Cycle immunity via content addressing:** Every parent link cryptographically pins `manifest_sha256`.
- **Topological linearization:** Multi-parent diamond merges are deduplicated; checkpoints are loaded once.
- **CAS publication:** the target branch tip is compare-and-swapped under one exclusive lock; a stale tip leaves the active pointer unchanged.
- **Read-only inspection:** `DAGCatalog(..., read_only=True)` requires an existing catalog and never initializes its schema; metadata lookup does not create a catalog.
- **Fail-closed missing parents:** Any broken parent link immediately halts resolution with `BrokenLineageError`.
- **Branch targeting:** durable publishers resolve a named branch (default `main`); explicit non-main branches must exist and be tip-matched before publishing.
- **Lineage vs. CAS:** a node's manifest `parents` are distinct from the branch-tip guard; `publish_node` validates the pointer, `walk_lineage` validates parent reachability.
- **Part range pruning & lineage caching:** Queries filter candidate Parquet parts by range bounds; lineage resolution is cached in-memory.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `branch` | List, create, or delete branches | `[--from]` |
| `checkout` | Switch current or branch pointer | `[--branch]`, `[--force]` |
| `compact` | Consolidate lineage into a checkpoint | `[--branch]`, `[--specs]`, `[--new-id]`, `[--no-publish]` |
| `doctor` | Run integrity checks | `[--skip-digests]` |
| `gc` | Collect unreferenced snapshots and parts | `[--dry-run]` |
| `log` | Display lineage history | `[-n]`, `[--branch]`, `[--graph]`, `[--all]` |
| `publish` | Publish a staged snapshot node | `[--expected-parent]`, `[--allow-null]`, `[--branch]` |
| `status` | Show current snapshot status | `[--branch]` |
| `tag` | List, create, or delete tags | `[-m]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
.venv/bin/python -m edgar_sec.infra.storage.dag.cli --help
```

## Deliberate gaps

- **Secondary inverted index management:** Generating multi-shard seek indexes (such as 48-shard lookups)
  is deferred to domain adapters and Checkpoint compaction.
