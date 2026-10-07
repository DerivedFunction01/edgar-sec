# `edgar_sec/infra/storage/dag` — Schema-agnostic append-only snapshot DAG engine

This package provides generic DAG snapshot mechanics for content-addressed datasets.
It decouples graph traversal, CAS publication, candidate anti-joining, and Checkpoint compaction
from phase-specific schemas and table structures.

## Purpose

Replaces monolithic Copy-on-Write (CoW) partition rewrites with lightweight, append-only
deltas. Upper layers configure declarative `RelationSpec` contracts; this layer compiles
the relational resolution views in DuckDB, enforces cycle immunity and parent digest chains,
and provides two-tier retention analysis.

## Module map

| Module | Responsibility |
| :--- | :--- |
| `spec.py` | Declarative `RelationSpec` contracts and `MergeStrategy` options (`upsert`, `append`, `scoped_mask`). |
| `manifest.py` | `DAGNodeManifest`, `ParentRef`, `PartDescriptor`, and canonical JSON IO. |
| `traversal.py` | Anchor-to-tip topological DFS traversal, cycle verification, and digest checking. |
| `resolution.py` | Dynamic DuckDB view compiler (`active_{name}`) and streamed logical fingerprinting. |
| `anti_join.py` | Pre-publish candidate filtering and no-op delta detection. |
| `publication.py` | Atomic pointer updates, POSIX file locking (`PublicationLock`), and branch support. |
| `compaction.py` | Lineage compaction into standalone Checkpoints with the Logical Parity Gate. |
| `retention.py` | Multi-root reachability tracing and physical part reference counting. |
| `doctor.py` | Graph health audits: detects cycles, missing manifests, unreadable parts, and stale stages. |
| `query.py` | Point-lookup and range-pruned DuckDB view compiler using part min/max bounds. |
| `cli.py` | Standard maintenance CLI entrypoint dispatching commands (`doctor`, `compact`, `purge`, `show`). |
| `__init__.py` | Package docstring only. No re-exports. |

## Contracts

- **Append-only ingestion:** Deltas record only new or modified Parquet files ($O(\Delta)$).
- **Cycle immunity via content addressing:** Every parent link cryptographically pins `manifest_sha256`.
- **Topological linearization:** Multi-parent diamond merges are deduplicated; checkpoints are loaded once.
- **Atomic publication:** Installs staged directory before advancing the pointer file under an exclusive file lock.
- **Fail-closed missing parents:** Any broken parent link immediately halts resolution with `BrokenLineageError`.
- **Part range pruning & lineage caching:** Queries filter candidate Parquet parts by range bounds; lineage resolution is cached in-memory.

## Public surface

- `RelationSpec`, `MergeStrategy` in [`spec.py`](spec.py).
- `DAGNodeManifest`, `ParentRef`, `PartDescriptor`, `read_manifest`, `write_manifest` in [`manifest.py`](manifest.py).
- `walk_lineage`, `resolve_lineage`, `clear_lineage_cache`, `LineageChain` in [`traversal.py`](traversal.py).
- `compile_virtual_views`, `compute_logical_fingerprint` in [`resolution.py`](resolution.py).
- `compile_pruned_views`, `derive_accession_range`, `prune_parts_for_range`, `query_point` in [`query.py`](query.py).
- `filter_candidate_delta`, `FilteredDelta` in [`anti_join.py`](anti_join.py).
- `publish_node`, `PublicationLock`, `pointer_path_for` in [`publication.py`](publication.py).
- `compact_lineage` in [`compaction.py`](compaction.py).
- `analyze_retention`, `purge_unreferenced` in [`retention.py`](retention.py).
- `audit_graph` in [`doctor.py`](doctor.py).
- `main` in [`cli.py`](cli.py).

## Command surface

```bash
.venv/bin/python -m edgar_sec.infra.storage.dag.cli --help
```

## Mirrored tests

- Direct unit and integration tests live under [`tests/infra/storage/dag/`](../../../../tests/infra/storage/dag/).

## Deliberate gaps

- **Secondary inverted index management:** Generating multi-shard seek indexes (such as 48-shard lookups)
  is deferred to domain adapters and Checkpoint compaction.
