# Phase 2.5 — Sub-Plan 02: Infrastructure Broker & Direct Parquet Snapshots

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 2 (`infra/broker/`, `infra/storage/document_parquet.py`)  
> **Source Grounding:** `.v1/defs/sec_http/broker.py`, `.v1/phases/025_webpage_storage/core/chunk_persistence.py`, `snapshot_merge.py`

---

## 1. Objectives & Architectural Simplification

Phase 2.5 must manage high-throughput network I/O and large document payload storage under strict operational bounds.

In `.v1`, workers wrote intermediate rows into per-chunk SQLite databases (`chunk-00001.db`), requiring a custom SQL AST compiler (`defs/sql/`, 380 lines), SQLite WAL checkpointers, and an offline pass over those databases before finally reading them into Parquet.

### Empirical Validation: Direct Parquet vs SQLite Intermediate Chunks
A scratch benchmark on synthetic SEC filings (~50MB raw payload, 500 documents across 10 chunks) measured:

| Metric | Option A (Legacy SQLite Chunks) | Option B (Direct Parquet Chunks) | Improvement |
| :--- | :--- | :--- | :--- |
| **Intermediate Disk Footprint** | 77.45 MB | **13.16 MB** | **5.9x smaller** (instant zstd) |
| **Worker Chunk Write Time** | 2.561s | **0.843s** | **3.0x faster** |
| **DuckDB Merge / Assembly Time** | 1.061s (`sqlite_scan`) | **0.591s** (`read_parquet`) | **1.8x faster** |
| **End-to-End Pipeline Latency** | 3.622s | **1.434s** | **2.5x faster** |
| **Code Footprint** | ~690 lines (`defs/sql/`, `vacuum.py`) | **0 lines** | **~690 lines eliminated** |

### Target Architecture
1. **Multi-Process SEC Rate Pacing**: Enforce configured aggregate SEC rate limits (via `sec.rate_limit_rps` settings) across arbitrary multi-process worker pools using a single Unix-socket token bucket daemon (`SecBroker`).
2. **Direct Parquet Chunk Snapshots**: Workers stream and write atomic, typed Parquet chunk files (`chunk_XXXXX.parquet`) matching the final snapshot schema with Zstd compression. Content-addressed digests (`blob_hash`, `occurrence_id`, `document_locator_key`) are computed upfront and stored in typed columns.
3. **Zero SQLite Overhead**: Eliminate intermediate `.db` files, WAL lock contention, database defragmentation, and SQL string compilers.
4. **Out-of-Core DuckDB Assembly**: The coordinator merges completed chunk Parquet files into a sorted, partitioned, and verified final artifact in a single zero-copy DuckDB query.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Action |
| :--- | ---: | :--- | :--- |
| `defs/sec_http/broker.py` | 485 | `infra/broker/sec_broker.py` | **Unix-Socket Broker Client**: Central token bucket client managing rate leases per configured settings, warm-cache probe, and connection pooling. |
| `defs/sec_http/broker.py` (daemon) | 180 | `infra/broker/daemon.py` | **Broker Daemon**: Managed background daemon process hosting the Unix-socket listener and token replenishment loop. |
| `phases/025/.../snapshot_merge.py` | 350 | `infra/storage/document_parquet.py` | **Unified Parquet I/O**: PyArrow chunk snapshot writer, chunk schema validator, and DuckDB out-of-core final snapshot assembler. |
| `phases/025/.../chunk_persistence.py` | 420 | *Dropped* | Replaced by direct PyArrow Parquet writer in `document_parquet.py`. |
| `defs/sql/` (compiler/AST) | 380 | *Dropped* | Obsolete. Parquet serialization requires no SQL string compilation. v2 builds direct SQL strings; there is no AST and no SQL-boundary rule. |
| `phases/025/.../vacuum.py` | 449 | `pipelines/document_storage/vacuum.py` | **NOT defragmentation — see the correction below.** |

---

## 3. Detailed Component Specifications

### 3.1. Central Unix-Socket Token Bucket (`edgar_sec/infra/broker/sec_broker.py` & `daemon.py`)
- **Invariant**: No uncoordinated client-side sleeps. Rate limits are maintained centrally via token bucket on a dedicated Unix domain socket (`.artifacts/runtime/sec_broker.sock`).
- **Protocol**:
  - Message format: Canonical length-prefixed JSON frames.
  - Commands: `ACQUIRE_LEASE`, `RELEASE_LEASE`, `PROBE_CACHE`, `RECORD_FAILURE`.
  - Cache short-circuit: If the requested document URL already exists in local disk cache (`infra.sec_http.cache`), the broker returns immediately with `CACHE_HIT` (0 tokens consumed).

```python
class SecBrokerClient:
    def __init__(self, socket_path: Path): ...
    def acquire_token(self, timeout_seconds: float = 30.0) -> bool: ...
    def probe_cache(self, url: str) -> bool: ...
```

### 3.2. Direct Parquet Snapshot Engine (`edgar_sec/infra/storage/document_parquet.py`)
- **Schema Contract**:
  - `occurrence_id`: String (sha256 of `source_cik:locator_key`)
  - `source_cik`: String (10-digit zero-padded)
  - `accession`: String (canonical 20-character accession number)
  - `document_path`: String (relative filename, e.g. `form10k.htm`)
  - `document_locator_key`: String (sha256 of `accession:document_path`)
  - `blob_hash`: String (sha256 of uncompressed `raw_payload`)
  - `raw_payload`: Binary (compressed raw bytes)
  - `byte_size`: Int64 (uncompressed byte size)
  - `normalized_text`: String (clean normalized ASCII text)
  - `status`: String (`ok`, `stub`, `error`)
  - `error_message`: String (nullable)

- **Worker Chunk Writer**:
```python
def write_chunk_snapshot(
    output_path: Path,
    occurrences: Sequence[FilingOccurrence],
    normalized_docs: Mapping[str, NormalizedDocument],
    raw_blobs: Mapping[str, RawDocumentBlob],
) -> Path:
    """Serialize worker chunk directly to an atomic Parquet snapshot file."""
```

- **Coordinator Out-of-Core Assembler**:
```python
def assemble_document_snapshots(
    chunk_paths: Sequence[Path],
    destination_parquet: Path,
    resources: ExecutionResources,
) -> int:
    """DuckDB zero-copy union and sorted out-of-core COPY to final artifact."""
```

---

## 4. Milestone Checklist & Verification

- [x] **M2.1**: Implement `edgar_sec/infra/broker/sec_broker.py` and `daemon.py`.
- [x] **M2.2**: Write multi-worker concurrent soak test proving token bucket caps throughput at configured rate settings.
- [x] **M2.3**: Implement `edgar_sec/infra/storage/document_parquet.py` chunk snapshot writer and validator with PyArrow.
- [x] **M2.4**: Implement DuckDB out-of-core final snapshot assembler in `document_parquet.py`.
- [x] **M2.5**: Write unit tests for chunk serialization and merge in `tests/infra/storage/test_document_parquet.py` and `tests/infra/broker/test_broker.py`.
- [x] **Verification**: Run `python check.py --scan` to guarantee zero upward dependencies from Layer 2.


---

## Correction: `vacuum.py` is cross-run consolidation, not defragmentation

This sub-plan originally recorded `phases/025/.../core/vacuum.py` as a *dropped*
SQLite defragmenter. That is wrong, and dropping it on that reasoning would have
removed a load-bearing subsystem.

What v1's `vacuum.py` (449 lines) actually does: it **merges multiple
partial-run snapshots into one canonical snapshot**. It is the only mechanism by
which a corpus built from many independent runs becomes a single dataset a
consumer can read without unioning and de-duplicating itself. Concretely it
provides:

- **Source precedence** — when two runs describe the same document, the
  later-listed source wins. Precedence is the order the caller passed, so the
  outcome does not depend on filesystem ordering.
- **Quarter repartitioning** — `filing_year` and `filing_quarter` are derived at
  consolidation time from `filing_date`, never stored. A snapshot written by an
  older code version therefore consolidates alongside a newer one with no
  migration.
- **Conflict rejection** — if two sources carry *different* normalized text for
  the same document, consolidation raises rather than silently discarding one.
  Precedence would happily drop the losing row; choosing which text of a filing
  is authoritative is not a decision a consolidation may make for the caller.
- **Byte-budgeted part planning** — parts are planned by document *byte size*,
  not row count, because normalized filing text varies by orders of magnitude.
- **Dependency-aware purge** — a source may only be deleted once nothing
  retained still references its parts. `expand_dependency_closure` determines
  the safe set before anything is removed.
- **Source immutability** — consolidation never writes to a source, and refuses
  a re-derived snapshot id rather than overwriting a published one.

**Status: implemented.** `pipelines/document_storage/vacuum.py`, with
`queries.py` (direct SQL), `infra/storage/document_parts.py` (part tree), and
`infra/storage/manifests.py` (identity, pointer, dependency closure). Covered by
`tests/pipelines/document_storage/test_vacuum.py`, which ports v1's
`test_temporal_snapshot.py` consolidation and purge contracts as the oracle.

The genuinely dropped part of the original claim is narrower and still true:
Parquet chunk files are immutable and need no defragmentation, so there is no
SQLite-style space reclamation anywhere in v2.
