# Phase 2.5 — Sub-Plan 05: Pipeline & Batch Orchestration

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 4 (`pipelines/document_storage/`)  
> **Source Grounding:** `.v1/phases/025_webpage_storage/core/`, `.v1/phases/025_webpage_storage/run.py`, `cli.py`

---

## 1. Objectives & Architectural Role

`pipelines/document_storage` is the orchestration layer that executes large-scale batch acquisition and normalization:
1. **Target Plan Ingestion**: Consumes the Phase 2 `target_plan.parquet` without network access, calculating deterministic chunk assignments.
2. **Process Pool Concurrency**: Drives a pool of isolated worker processes budgeted via `derive_resources()`.
3. **Resumable Chunk Execution**: Workers write to isolated SQLite chunk databases (`chunk-00001.db`) with atomic checkpoint manifests. Stalled chunks resume cleanly without re-fetching SEC data.
4. **Interactive Operator Menu**: Preserves the zero-copy-paste interactive terminal workflow (target plan discovery, mode selection, vacuuming).
5. **Snapshot Publication**: Assembles final versioned Parquet datasets via DuckDB out-of-core COPY.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `phases/025/.../core/pipeline.py` | 460 | `pipelines/document_storage/pipeline.py` | Orchestrates end-to-end target plan execution and worker coordination. |
| `phases/025/.../core/chunk_worker.py` | 490 | `pipelines/document_storage/worker.py` | Worker process loop: broker lease &rarr; CAS blob write &rarr; engine normalizer &rarr; CAS occurrence. |
| `phases/025/.../core/fetcher.py` | 420 | `pipelines/document_storage/fetcher.py` | Acquisition adapter (live broker fetch vs. offline fixture CAS extraction). |
| `phases/025/.../core/exhibit_second_pass.py` | 260 | `pipelines/document_storage/exhibit_delegator.py` | Evaluator dispatch for secondary exhibit refetching (EX-13, EX-21). |
| `phases/025/.../core/snapshot_merge.py` | 410 | `pipelines/document_storage/merger.py` | Validates chunk invariants and publishes canonical Parquet dataset. |
| `phases/025/.../core/vacuum.py` | 380 | `pipelines/document_storage/vacuum.py` | CLI defragmentation and orphan blob pruning engine. |
| `phases/025_webpage_storage/run.py` | 312 | `pipelines/document_storage/operator.py` | Interactive terminal UI menu for operators. |
| `phases/025_webpage_storage/cli.py` | 580 | `pipelines/document_storage/cli.py` | Canonical CLI subcommands (`preview`, `run`, `status`, `merge`, `vacuum`). |

---

## 3. Detailed Component Specifications

### 3.1. Scoped Directory Layout (`edgar_sec/pipelines/document_storage/paths.py`)
```text
.artifacts/document_storage/
├── runs/<run_id>/
│   ├── target_plan/                 # Symlink or copy of Phase 2 plan
│   ├── checkpoints/                 # Atomic chunk manifests (chunk-00001.json)
│   ├── transient/                   # Isolated SQLite chunk DBs (chunk-00001.db)
│   └── failure_ledger.json          # Unretryable errors (e.g. permanent 404s)
└── snapshots/<snapshot_id>/
    ├── documents.parquet            # Final canonical normalized document dataset
    └── snapshot_manifest.json       # Invariant audit report and SHA-256 digests
```

### 3.2. Worker Execution Loop (`edgar_sec/pipelines/document_storage/worker.py`)
```python
def process_chunk(chunk: ChunkSpec, config: PipelineConfig) -> ChunkResult:
    # 1. Open isolated chunk SQLite database
    store = ChunkStore(chunk.db_path)
    
    for locator in chunk.locators:
        # 2. Acquire raw payload (via SecBroker or offline CAS fixture)
        raw_bytes, was_cached = fetcher.acquire(locator)
        blob_hash = store.put_blob(raw_bytes)
        
        # 3. Pure Engine Normalization (Layer 3)
        doc_rep = unpacker.unpack(raw_bytes, locator)
        normalized = form_plugin.normalize(doc_rep)
        
        # 4. Check for exhibit delegation
        decision = form_plugin.evaluate(doc_rep)
        if decision.action == DecisionAction.REFETCH_EXHIBIT:
            exhibit_bytes = fetcher.acquire(decision.target_locator)
            normalized.append_exhibit(exhibit_bytes)
            
        # 5. Persist occurrence record
        store.put_occurrence(locator, blob_hash, normalized.text, status="ok")
        
    # 6. Reclaim memory at batch interval
    foundation.runtime.memory.reclaim()
    return ChunkResult(chunk_id=chunk.id, status="completed")
```

### 3.3. Interactive Operator Menu (`edgar_sec/pipelines/document_storage/operator.py`)
Preserves the interactive workflow:
```text
Phase 2.5: Document Storage & Normalization
  Discovered Target Plans:
    1. plan-20260928-10k (10,000 locators) -> .artifacts/filing_extraction/...

Options:
  1. Preview (bounded 3 locators)
  2. Run Fixture Mode (offline CAS)
  3. Run Production Mode (live SEC broker)
  4. Fill Fixture (record live payloads into test fixture)
  5. Show Status & Resumability
  6. Merge Chunks to Canonical Snapshot
  7. Vacuum SQLite Chunk Databases
  0. Exit
```

---

## 4. Milestone Checklist & Verification

- [ ] **M5.1**: Implement `edgar_sec/pipelines/document_storage/paths.py` and `manifest.py`.
- [ ] **M5.2**: Implement `pipelines/document_storage/fetcher.py` (broker vs fixture CAS).
- [ ] **M5.3**: Implement `pipelines/document_storage/worker.py` with multi-process pool.
- [ ] **M5.4**: Implement `pipelines/document_storage/exhibit_delegator.py`.
- [ ] **M5.5**: Implement `pipelines/document_storage/merger.py` with DuckDB Parquet COPY.
- [ ] **M5.6**: Implement `operator.py` and canonical `cli.py`.
- [ ] **M5.7**: Register launcher entry in root `python run.py`.
