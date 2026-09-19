# SEC Storage, Parquet Lakehouse & Live Ingestion Architecture: Strategic Roadmap

---

> [NOTE]: This is only draft, not a literal implementation plan. It is subject to change at any time as the codebase evolves. It should not be used to implement changes, but rather as an inspiration for what should be implemented.

## 1. Executive Summary & Strategic Scope

This document serves as the normative reference and architectural specification for two interconnected evolutions of the EDGAR data pipeline:

1. **Storage Evolution (SQLite Scratchpad $\to$ Partitioned Parquet Lakehouse)**:
   Transitioning from transient local SQLite partition databases to published, columnar, Hive-partitioned Parquet datasets optimized for zero-copy DuckDB analytics and Hugging Face Hub distribution.
2. **Operational Evolution (Horizontal Batch Backfill $\to$ Vertical Live Streaming)**:
   Bridging the gap between the current historical backfill paradigm (stage-by-stage across millions of filings) and the future live operational mode (filing-by-filing end-to-end extraction upon SEC release).

---

## 2. The 3-Tier Storage Hierarchy

To eliminate the tension between high-speed concurrent worker writes and distributed, immutable cloud distribution, storage is divided into three distinct lifecycle tiers:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ TIER 1: TRANSIENT WORKER SCRATCHPAD (Local NVMe SQLite)                      │
│ - Ephemeral, isolated chunk databases (chunk-00001.db).                       │
│ - SQLite WAL mode, PRAGMA synchronous=OFF, streaming inserts.                │
│ - Contains dev/coordination tables (_committed_chunks, raw failure ledgers). │
│ - Destroyed or archived after verified partition merge.                      │
├──────────────────────────────────────────────────────────────────────────────┤
│ TIER 2: CANONICAL PUBLISHED LAKEHOUSE (Hive Parquet on S3 / Hugging Face)    │
│ - Clean, immutable, columnar Parquet files with Zstandard compression.       │
│ - Zero dev tables: only filing_occurrences and normalized_documents.        │
│ - Normalized document payloads stored as clean UTF-8 strings.                │
│ - Partitioned by filing_year and filing_quarter. Target size: 50MB–250MB.    │
├──────────────────────────────────────────────────────────────────────────────┤
│ TIER 3: SATELLITE FACT & EXTRACTION LAYERS (Downstream Phases 03+)           │
│ - Pure downstream projections referencing Tier 2 via doc_id & occurrence_id. │
│ - Document Sections (Item 1, 1A, 7, 8, Notes to Financials).                 │
│ - Extracted Facts (Labor union coverage, derivatives notional, covenants).   │
│ - Versioned by model/prompt (model_version=gemini_flash_v2/year=2024/).     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Partitioning Strategy & Lakehouse Directory Taxonomy

Because cloud and Git-LFS storage backends (Hugging Face Hub, AWS S3) cannot update large database files in place, all physical datasets are **append-only, Hive-partitioned Parquet files**.

### 3.1 Directory Topology

```text
sec-lakehouse-root/
│
├── 01_occurrences/
│   ├── form=10-K/
│   │   ├── filing_year=2024/filing_quarter=Q1/part-00001.parquet
│   │   └── filing_year=2024/filing_quarter=Q2/part-00001.parquet
│   ├── form=10-Q/
│   │   └── filing_year=2024/filing_quarter=Q1/part-00001.parquet
│   └── form=8-K/
│       └── filing_year=2024/part-00001.parquet
│
├── 02_normalized_documents/
│   ├── filing_year=2024/
│   │   ├── filing_quarter=Q1/
│   │   │   ├── part-00001.parquet  (doc_ids: 0000... to 3fff...)
│   │   │   └── part-00002.parquet  (doc_ids: 4000... to 7fff...)
│   │   └── filing_quarter=Q2/
│   │       └── part-00001.parquet
│
├── 03_sections/  (Phase 03 Output)
│   ├── form=10-K/
│   │   ├── item=item_1/filing_year=2024/part-00001.parquet
│   │   ├── item=item_1a/filing_year=2024/part-00001.parquet
│   │   └── item=item_7/filing_year=2024/part-00001.parquet
│
└── 04_extractions/  (Phase 04+ Domain Facts)
    ├── labor_union_coverage/
    │   └── model_version=regex_v1/filing_year=2024/part-00001.parquet
    └── derivatives_and_hedging/
        └── model_version=gemini_flash_v2/filing_year=2024/part-00001.parquet
```

### 3.2 The Temporal Invariant: `filing_date` vs. `report_date`

A critical failure mode in financial lakehouses is partitioning directories by fiscal period (`report_date`). When a company amends a filing two years later (e.g. Form 10-K/A filed in 2024 for fiscal year 2022), partitioning by `report_date` forces historical 2022 directories to be modified or rewritten, violating immutability.

* **Governing Specification**:
  1. **Physical Directory Partitioning**: Always keyed by **`filing_year`** and **`filing_quarter`** (derived from the SEC acceptance timestamp). `filing_date` is strictly monotonic and historical directory trees are sealed permanently upon quarter close.
  2. **Logical Query Filter**: **`report_date`** (period of report) is retained as a typed date column inside the Parquet schema. DuckDB and PyArrow push down predicates (`WHERE report_date BETWEEN '2023-01-01' AND '2023-12-31'`) using Parquet column metadata and page-level min/max zone maps without physical directory rewrites.

---

## 4. Multi-Registrant De-Duplication (1 Blob : N Filings)

Many SEC documents are shared across multiple registrants (e.g., parent/subsidiary co-filings on Form 8-K) or reused across filings as exhibits.

### 4.1 Lakehouse Normalization Contract

To prevent duplicating 10MB–50MB normalized document texts across registrants:
- **`filing_occurrences`** is the relational bridge:
  - Schema: `occurrence_id` (PK), `source_cik`, `accession`, `form`, `filing_date`, `report_date`, `document_path`, `doc_id` (FK), `document_status`.
  - Partitioned by `form` and `filing_date`.
- **`normalized_documents`** is the content-addressed blob store:
  - Schema: `doc_id` (PK), `accession` (representative), `document_path`, `clean_text`, `byte_size`, `character_count`, `table_count`, `processor_fingerprint`, `normalized_schema_version`.
  - Partitioned strictly by `filing_year` and `filing_quarter` based on the **first observed filing** of that content.
  - Exactly one physical record exists per unique `doc_id = sha256(accession/document_path)`.

---

## 5. Storage Encoding, Null Bytes & Text Sanitization

### 5.1 Native UTF-8 Strings vs. Pre-Compressed Binaries

In current Phase 2.5 SQLite chunk databases, normalized documents are stored as Zstandard-compressed byte arrays (`BLOB`). 

* **Published Lakehouse Specification**:
  - The canonical Parquet column for published documents must be **uncompressed UTF-8 `STRING`**, leaving compression to **Parquet's native columnar Zstandard compressor** (`compression="zstd"`, `compression_level=3`).
  - *Rationale*: Storing pre-compressed zstd bytes prevents DuckDB, Hugging Face Dataset Viewer, and PyArrow from querying or previewing text directly. When stored as native UTF-8 strings with Parquet zstd compression, DuckDB transparently decompresses column chunks in vectorized C++ at memory-bandwidth speeds, allowing full-text SQL search (`ILIKE '%collective bargaining%'`) across remote URLs.

### 5.2 The Null Byte (`\x00`) and Control Character Trap

Historical SEC filings (1993–2010) contain corrupted ASCII/HTML characters, non-breaking space anomalies, and embedded null bytes (`\x00`).
- While SQLite permits embedded `\x00` in `TEXT`/`BLOB`, **PyArrow, Parquet C++ writers, and DuckDB string engines will either crash or truncate text** at the first null byte.

* **Mandatory Sanitization Specification**:
  Prior to Parquet publication, all text content must pass through a strict sanitization pass:
  1. Strip all null bytes: `text = text.replace("\x00", "")`.
  2. Strip non-printable ASCII control characters (`\x01` through `\x08`, `\x0B`, `\x0C`, `\x0E` through `\x1F`), while preserving `\t`, `\n`, and `\r`.
  3. Validate valid UTF-8 encoding; replace unassigned surrogate code points with the Unicode replacement character `\uFFFD`.

---

## 6. Artifact Cleanliness & Production Ledger Contract

Published production artifacts must never leak development scaffolding or transient execution tables.

### 6.1 Table Separation Matrix

| Internal / Dev Table (SQLite Scratchpad Only) | Canonical Published Table (Parquet Lakehouse) |
| :--- | :--- |
| `_committed_chunks` (Worker audit logs) | `filing_occurrences` |
| `acquisition_failures` (HTTP/SGML network errors) | `normalized_documents` |
| `normalization_failures` (Parser tracebacks) | `document_sections` *(Phase 03)* |
| Transient worker thread IDs / attempt IDs | `extracted_facts` *(Phase 04)* |

### 6.2 The Zero-Loss Accounting Principle

If a document fails acquisition or normalization, omitting its row entirely from published datasets creates an audit gap (the consumer cannot tell if the filing was missed by the scraper or failed processing).
- **Specification**:
  - Every valid submission listed in the SEC index retains an immutable record in `filing_occurrences`.
  - If a document is unavailable or un-normalizable, `filing_occurrences.doc_id` is set to `NULL`, and `document_status` is explicitly set to an enumeration:
    - `"available"`: Document successfully normalized; present in `normalized_documents`.
    - `"sec_missing"`: 404/Missing on SEC EDGAR.
    - `"unsupported_binary"`: File is an image, PDF stub, or unsupported container.
    - `"normalization_failed"`: Raw file retained in raw archive; substantive text extraction failed validation.

---

## 7. Downstream Extraction Architecture (Phases 03+)

Downstream phases (Phase 03 Item Sectioning, Phase 04 Domain Fact Extraction) read Tier 2 text and emit Tier 3 satellite fact tables.

### 7.1 Separation of Algorithm Core from Storage Engine

To enable code reuse across both historical backfills and live streaming:
- **Rule**: Domain modules in `phases/*/core/` must operate on **in-memory domain models or plain strings**, never on SQLite or DuckDB connection objects.
  ```python
  # CORRECT: Pure functional engine, storage-agnostic
  class ItemSectioner:
      def partition_document(self, text: str, form: str) -> list[DocumentSection]: ...


  # INCORRECT: Tying sectioning logic to database persistence
  class ItemSectioner:
      def partition_document(self, db_conn: sqlite3.Connection, doc_id: str): ...
  ```

### 7.2 Satellite Fact Table Schema (Phase 04+)

Numerical data (union coverage, derivatives/hedging notional amounts, executive compensation) are stored as typed columnar records with strict provenance:

```text
struct ExtractedFact {
    fact_id:             VARCHAR (sha256 of doc_id + metric + span)
    doc_id:              VARCHAR (FK -> normalized_documents)
    occurrence_id:       VARCHAR (FK -> filing_occurrences)
    section_name:        VARCHAR ("Item 1A" | "Item 8 Note 12")
    source_cik:          VARCHAR
    filing_date:         DATE
    filing_year:         INT     (Partition key)

    // Domain Payload
    metric_category:     VARCHAR ("labor_relations" | "derivatives_hedging")
    metric_name:         VARCHAR ("cba_covered_percentage" | "fx_notional_usd")
    value_numeric:       DOUBLE  (e.g., 0.185 or 450000000.0)
    value_text:          VARCHAR (raw string, if categorical)
    unit:                VARCHAR ("ratio" | "USD" | "count")

    // Audit & Lineage
    extractor_type:      VARCHAR ("regex" | "llm")
    extractor_version:   VARCHAR ("regex_v1.4" | "gemini-2.5-flash@2026-09")
    source_line_start:   INT     (1-indexed start line in normalized .txt)
    source_evidence:     VARCHAR ("Approximately 18.5% of our active workforce...")
    confidence:          DOUBLE
}
```

---

## 8. Horizontal Batch vs. Vertical Live Streaming

### 8.1 The Dual-Paradigm Model

```text
===================================================================================
HORIZONTAL BATCH (Historical Backfill):
Optimized for high-throughput, bulk SEC rate limits, and global deduplication.
-----------------------------------------------------------------------------------
All Filings ──> [ Phase 01: Metadata ] ───────────> All Metadata (Done)
All Metadata ──> [ Phase 02: Target Planning ] ────> All Plans (Done)
All Plans ────> [ Phase 025: Fetch & Normalize ] ─> All Documents (Done)
All Documents ─> [ Phase 03: Item Sectioning ] ───> All Sections (Done)
All Sections ──> [ Phase 04: LLM Extraction ] ────> All Facts (Done)

===================================================================================
VERTICAL STREAMING (Live Production Daemon):
Optimized for low-latency (<30s per filing) as new 8-K/10-Q/10-K filings hit EDGAR.
-----------------------------------------------------------------------------------
SEC EDGAR RSS / Daily Feed (Single Filing Trigger)
       │
       ▼
[ Live Pipeline Orchestrator ] (services/live/pipeline.py)
  1. Parse metadata & accession              (reuses phases.01.core)
  2. Fetch document & clean DOM / reflow     (reuses phases.025.core)
  3. Detect Item boundaries & section spans  (reuses phases.03.core)
  4. Run targeted LLM / regex fact extract   (reuses phases.04.core)
       │
       ▼
Append row to Daily Intraday Buffer (DuckDB / Parquet delta)
```

### 8.2 Repository Topology

The "Live" system must not duplicate parsing or normalization code. It sits above the phases as an orchestrator:

```text
defs/                              # Shared foundation (sec_http, storage, sql, llm)
phases/                            # Domain modules & batch backfill CLIs
  01_metadata_extraction/core/     # Metadata extraction logic
  025_webpage_storage/core/        # Normalizer & ASCII reflow engines
  03_sectioning/core/              # Section & Item boundary detection
  04_domain_extraction/core/       # Regex & LLM structured fact extractors
services/                          # Live operational daemons
  live/
    poller.py                      # Polls SEC EDGAR RSS & daily index
    orchestrator.py                # Chains phase cores end-to-end for 1 filing
    compactor.py                   # Nightly compaction of daily deltas into lake
```

### 8.3 Intraday Staging and Nightly Compaction

To avoid creating thousands of tiny 1-row Parquet files on Hugging Face / S3 during live operation:
1. **Intraday Buffer**: During trading hours, live extractions append to a local daily staging SQLite/DuckDB buffer (`.artifacts/staging/YYYY-MM-DD.db`).
2. **Nightly Compaction**: At 8:00 PM EST (EDGAR filing close), a compaction worker reads the day's buffer and writes one consolidated `part-YYYYMMDD.parquet` file directly into the canonical lakehouse directory partition.
3. **Atomic Sync**: The consolidated file is committed to Hugging Face Hub / S3 via a single commit/PUT.

---

## 9. DuckDB Query Verification & Consumption

Because Tier 2 and Tier 3 use standardized Parquet schemas with consistent `doc_id` foreign keys, DuckDB can join full-text documents, section boundaries, and numerical facts directly from local disk or remote Hugging Face URLs without loading datasets into memory:

```sql
-- Analytical Query: Join company metadata with 10-K Item 1A Risk Factors and extracted labor facts
INSTALL httpfs; LOAD httpfs;

SELECT 
    o.source_cik,
    o.filing_date,
    o.form,
    f.metric_name,
    f.value_numeric AS union_coverage_pct,
    f.source_evidence,
    s.clean_text AS item_1a_text
FROM read_parquet('hf://datasets/org/sec-lake/01_occurrences/form=10-K/filing_year=2024/**/*.parquet') o
JOIN read_parquet('hf://datasets/org/sec-lake/04_extractions/labor_union_coverage/filing_year=2024/**/*.parquet') f
  ON o.occurrence_id = f.occurrence_id
JOIN read_parquet('hf://datasets/org/sec-lake/03_sections/form=10-K/item=item_1a/filing_year=2024/**/*.parquet') s
  ON o.doc_id = s.doc_id
WHERE f.value_numeric > 0.25
ORDER BY f.value_numeric DESC;
```

---

## 10. Summary Roadmap Checklist

```text
[x] 1. Phase 025 Lakehouse Exporter: `merge-to-snapshot` projects finalized SQLite partition databases into temporal Parquet snapshots.
[x] 2. Text Sanitization Gate: Remove null bytes and decode normalized payloads as native UTF-8 during Parquet serialization.
[x] 3. Two-Table Lakehouse Split: Maintain strict separation between occurrence indexes (1:N) and normalized document payloads (1:1).
[x] 4. Monotonic Partitioning: Ensure directory paths reflect filing_year and filing_quarter, not fiscal period dates.
[ ] 5. Pure Functional Cores: Validate that Phase 03 and Phase 04 engines accept pure domain objects, independent of storage backends.
[ ] 6. Live Orchestrator Service: Construct services/live/ to chain phase core libraries for single-filing streaming workflows.
[x] 7. Snapshot vacuum: Parallelize temporal-quarter compaction with immutable publication and dependency-aware purge.
```
