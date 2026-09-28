# Phase 2.5 — Sub-Plan 02: Infrastructure Broker & Content-Addressed Storage (CAS)

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 2 (`infra/broker/`, `infra/storage/cas/`, `infra/storage/document_parquet.py`)  
> **Source Grounding:** `.v1/defs/sec_http/broker.py`, `.v1/defs/sql/`, `.v1/phases/025_webpage_storage/core/chunk_persistence.py`, `vacuum.py`

---

## 1. Objectives & Architectural Role

Phase 2.5 must manage high-throughput I/O under strict operational bounds:
1. **Multi-Process SEC Rate Pacing**: Enforce configured aggregate SEC rate pacing (via `sec.rate_limit_rps` settings) across arbitrary multi-process worker pools (e.g. 16 workers) using a single Unix-socket token bucket daemon (`SecBroker`).
2. **Content-Addressed Storage (CAS)**: Store raw uncompressed/compressed document payloads keyed by SHA-256 digest (`document_blobs`) in isolated worker SQLite chunk databases.
3. **Zero Lock Contention**: Workers write exclusively to isolated chunk SQLite files (`chunk-00001.db`). DuckDB merges completed chunks directly to Parquet.
4. **Automated Maintenance**: Defragment chunk databases via SQLite `VACUUM INTO` and prune orphan binary blobs.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `defs/sec_http/broker.py` | 485 | `infra/broker/sec_broker.py` | **Unix-Socket Broker**: Central token bucket managing rate leases per configured settings, warm-cache probe, and connection pooling. |
| `defs/sec_http/broker.py` (daemon) | 180 | `infra/broker/daemon.py` | Managed background daemon process hosting the Unix socket listener. |
| `phases/025/.../chunk_persistence.py` | 420 | `infra/storage/cas/chunk_store.py` | Isolated SQLite chunk store: manages `document_blobs` and `filing_occurrences`. |
| `defs/sql/` (compiler/AST) | 380 | `infra/storage/cas/sql.py` | Parameterized SQL compilation ensuring zero string concatenation or SQL injection. |
| `phases/025/.../vacuum.py` | 310 | `infra/storage/cas/vacuum.py` | `VACUUM INTO`, space reclamation, and orphan blob pruning. |
| `phases/025/.../snapshot_merge.py` | 350 | `infra/storage/document_parquet.py` | DuckDB out-of-core COPY joining chunk SQLite databases into final Parquet. |

---

## 3. Detailed Component Specifications

### 3.1. Central Unix-Socket Token Bucket (`edgar_sec/infra/broker/sec_broker.py`)
- **Invariant**: No client-side `time.sleep()`. When 16 workers run in parallel, uncoordinated sleeps violate SEC IP-level 10 RPS thresholds.
- **Protocol**:
  - Workers connect to Unix domain socket at `.artifacts/runtime/sec_broker.sock`.
  - Message format: Canonical length-prefixed JSON.
  - Commands: `ACQUIRE_LEASE`, `RELEASE_LEASE`, `PROBE_CACHE`, `RECORD_FAILURE`.
  - Warm Cache Hit: If the requested URL exists in `infra.sec_http.cache`, the broker returns immediately with `CACHE_HIT` (0 token consumed).

```python
class SecBrokerClient:
    def __init__(self, socket_path: Path): ...
    def request_document(self, url: str) -> tuple[bytes, bool]:
        """Requests a document through the broker. Returns (payload, was_cached)."""
```

### 3.2. SQLite Content-Addressed Storage (`edgar_sec/infra/storage/cas/chunk_store.py`)
- **Schema Contract**:
```sql
CREATE TABLE IF NOT EXISTS document_blobs (
    blob_hash TEXT PRIMARY KEY,          -- sha256 of raw uncompressed payload
    compression TEXT NOT NULL,           -- 'zstd' or 'none'
    raw_payload BLOB NOT NULL,
    byte_size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filing_occurrences (
    occurrence_id TEXT PRIMARY KEY,      -- sha256(source_cik + ":" + locator_key)
    source_cik TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    document_path TEXT NOT NULL,
    document_locator_key TEXT NOT NULL,
    blob_hash TEXT NOT NULL,
    normalized_text TEXT,
    status TEXT NOT NULL,                -- 'ok', 'stub', 'error'
    error_message TEXT,
    FOREIGN KEY(blob_hash) REFERENCES document_blobs(blob_hash)
);
```

### 3.3. Out-of-Core DuckDB Parquet Assembler (`edgar_sec/infra/storage/document_parquet.py`)
- **Invariant**: The coordinator never reads multi-gigabyte document strings into Python memory.
- DuckDB executes an out-of-core scan over all chunk SQLite databases:
```sql
COPY (
    SELECT 
        occurrence_id, source_cik, accession_number, document_path,
        document_locator_key, blob_hash, normalized_text, status
    FROM sqlite_scan('chunk-*.db', 'filing_occurrences')
    ORDER BY source_cik, accession_number
) TO '.artifacts/document_snapshots/snapshot.parquet' (FORMAT PARQUET, COMPRESSION 'zstd');
```

---

## 4. Milestone Checklist & Verification

- [ ] **M2.1**: Implement `edgar_sec/infra/broker/sec_broker.py` and `daemon.py`.
- [ ] **M2.2**: Write multi-worker concurrent soak test proving token bucket caps throughput at configured rate settings.
- [ ] **M2.3**: Implement `edgar_sec/infra/storage/cas/chunk_store.py` with WAL mode and CAS deduplication.
- [ ] **M2.4**: Implement `edgar_sec/infra/storage/cas/vacuum.py` for SQLite defragmentation.
- [ ] **M2.5**: Implement `edgar_sec/infra/storage/document_parquet.py` via DuckDB out-of-core COPY.
- [ ] **Verification**: Run `python check.py --scan` to guarantee zero layer violations.
