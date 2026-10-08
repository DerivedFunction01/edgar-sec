# Cohort Ingestion, Sources & Relational Operations Specification

This specification defines the ingestion engines, official SEC source management, relational set algebra, and sampling capabilities in `edgar_sec.infra.storage.cohort`.

---

## 1. Multi-Format File Intake Engine (`ingestion.py`)

The file intake engine ingests external files with streaming DuckDB execution, zero Python heap row buffering, and strict row quality tracking.

### 1.1 Ingestion Quality Invariant
Every ingestion pass produces an `IngestionQuality` summary satisfying the invariant:
```text
total_raw_rows = usable_rows + rejected_rows + duplicate_rows
```
- **`usable_rows`**: Count of distinct, valid CIKs saved to the cohort dataset.
- **`rejected_rows`**: Count of non-numeric, malformed, or out-of-range rows ($CIK < 1$ or $CIK > 9,999,999,999$).
- **`duplicate_rows`**: Count of subsequent rows containing a valid CIK that was already encountered earlier in the input.

### 1.2 Streaming Memory Contract
- **Streaming Guarantee**: Ingestion compiles DuckDB query pipelines directly into `copy_query_to_parquet`. No intermediate rows or Python string objects are materialized on the Python heap.
- **Benchmark Isolation**: High-throughput workloads (e.g. 100k or 1M line TXT benchmarks) are isolated in `scratch/bench_cohort_txt.py` and run separately from the fast, deterministic unit test gate.

### 1.3 Format Detection & Parsing Strategies
- **CSV / TSV**:
  - Automatically sniffs delimiter if unspecified (commas, tabs, pipes).
  - Matches headers case-insensitively (`cik`, `CIK`, `central_index_key`). If no header exists, maps column index 0.
- **Plain TXT (1-Column CIK List)**:
  - Uses DuckDB newline streaming: `read_csv(?, delim='\n', columns={'line':'VARCHAR'})`.
  - Entity name defaults to `""`.
- **Parquet**:
  - Direct columnar projection with schema validation.

### 1.4 Python Signatures
```python
@dataclass(frozen=True, slots=True)
class IngestionQuality:
    total_raw_rows: int
    usable_rows: int
    rejected_rows: int
    duplicate_rows: int


@dataclass(frozen=True, slots=True)
class IngestResult:
    cohort: CohortRecord
    quality: IngestionQuality


def ingest_file_to_cohort(
    input_path: Path | str,
    *,
    catalog: CohortCatalog,
    paths: CohortPaths,
    name: str | None = None,
    description: str = "",
    tags: Sequence[str] = (),
    limit: int | None = None,
    delimiter: str | None = None,
) -> IngestResult: ...
```

---

## 2. Official SEC Sources Subsystem (`sources.py`)

Dedicated module `edgar_sec.infra.storage.cohort.sources` manages official SEC reference registries.

### 2.1 Managed Official Sources
1. **Universe (`cik_lookup`)**:
   - Source: SEC `cik_lookup.txt` (full historical universe of ~980,000+ filers).
   - Stored with `origin_kind = 'official_source'`, `pinned = 1`.
2. **Active Tickers (`company_tickers`)**:
   - Source: SEC `company_tickers.json` (~10,000+ active operating companies).
   - Stored with `origin_kind = 'official_source'`, `pinned = 1`.

### 2.2 Active Version Management (SQLite WAL)
Active version pointers are stored in `source_active_pointers` in `cohorts.sqlite`:
- **Read Active Version**:
  `SELECT active_snapshot_id FROM source_active_pointers WHERE source_name = ?`
- **Atomic Pointer Swap**:
  `INSERT OR REPLACE INTO source_active_pointers (source_name, active_snapshot_id) VALUES (?, ?)`
- Completely replaces disk-based `active_pointer.json` files, preventing multi-process race conditions.

### 2.3 Python Signatures
```python
def refresh_official_source(
    source_name: str,  # 'cik_lookup' or 'company_tickers'
    *,
    client: SecHttpClient,
    paths: CohortPaths,
    catalog: CohortCatalog,
) -> CohortRecord: ...


def publish_universe_source(
    raw_path: Path,
    *,
    paths: CohortPaths,
    catalog: CohortCatalog,
) -> CohortRecord: ...


def publish_tickers_source(
    raw_path: Path,
    *,
    paths: CohortPaths,
    catalog: CohortCatalog,
) -> CohortRecord: ...


def swap_active_source_pointer(
    source_name: str,
    snapshot_id: str,
    *,
    catalog: CohortCatalog,
) -> None: ...


def resolve_active_source(
    source_name: str,
    *,
    catalog: CohortCatalog,
) -> CohortRecord | None: ...
```

---

## 3. Relational Set Algebra & AST Compiler (`operations.py`)

Relational set operations combine cohorts into derived cohorts, inspection reports, or augmentation delta rosters.

### 3.1 Set Operation Execution
Supports `union`, `intersect`, and `difference` producing a new registered cohort:
- **Set Logic**:
  - `union`: Distinct union of all CIKs across both operands.
  - `intersect`: Inner join of CIKs present in both operands.
  - `difference`: Left anti-join (`left` minus `right`).
- **Name Resolution**:
  `coalesce(nullif(left.name, ''), nullif(right.name, ''), '')`
  Prefers non-empty name from left operand, falls back to right, then defaults to `""`.
- **Monotonic Ordinal**:
  Output rows are strictly ordered by `try_cast(cik_padded AS BIGINT) ASC`, and `ordinal` is re-assigned via `row_number() OVER () - 1`.

### 3.2 Augmentation Delta Roster Materialization
For `metadata_sync` augmentation planning, a dedicated anti-join operator materializes the subtraction of a base snapshot CIK index from a requested cohort:
```python
def execute_delta_roster(
    requested_dataset: Path,
    base_cik_map_dataset: Path,
    output_dataset: Path,
) -> int:
    """Materialize rows in requested cohort absent from base CIK map.

    Renubers ordinals monotonically from 0 for chunk addressing.
    """
    ...
```

### 3.3 AST Compiler & Dry-Run Preview
The expression compiler parses tree expressions into structured AST nodes:
```python
SetOpKind = Literal["union", "intersect", "difference"]


@dataclass(frozen=True, slots=True)
class ExprNode:
    pass


@dataclass(frozen=True, slots=True)
class CohortRef(ExprNode):
    cohort_identifier: str  # name or cohort_id


@dataclass(frozen=True, slots=True)
class BinaryOp(ExprNode):
    left: ExprNode
    right: ExprNode
    op: SetOpKind


def compile_ast_to_sql(node: ExprNode, catalog: CohortCatalog) -> str: ...
```
- Compiles into a single nested DuckDB SQL query.
- Evaluated directly into destination Parquet via `copy_query_to_parquet` without disk intermediates.
- `--serialize` outputs canonical JSON AST without executing the query.

### 3.4 Set Difference Inspection (`diff_cohorts`)
Generates comparison metrics between two cohorts without creating a new cohort:
```python
@dataclass(frozen=True, slots=True)
class SetDiffReport:
    left_name: str
    right_name: str
    left_total: int
    right_total: int
    intersection_count: int
    left_only_count: int
    right_only_count: int
    union_count: int
    sample_left_only: tuple[tuple[str, str], ...]  # (cik_padded, name)
    sample_right_only: tuple[tuple[str, str], ...]


def diff_cohorts(
    left_dataset: Path,
    right_dataset: Path,
    *,
    left_name: str = "A",
    right_name: str = "B",
    sample_limit: int = 5,
) -> SetDiffReport: ...
```

---

## 4. Composable Sampling Engine (`operations.py`)

Sampling enables reproducible sub-cohort creation from large rosters.

### 4.1 Sampling Algorithms
1. **Deterministic Modulo Sampling (`method = "modulo"`)**:
   - Uses DuckDB MD5 on zero-padded CIK strings:
     ```sql
     WHERE try_cast('0x' || substr(md5(cik_padded), 1, 8) AS BIGINT) % 100 < ?
     ```
   - Stable across runs, architectures, and DuckDB versions without depending on PRNG state.
2. **Seeded Random Sampling (`method = "random"`)**:
   - Uses DuckDB `USING SAMPLE rate_percent % (BERNOULLI, SEED seed)` or `ORDER BY hash(cik_padded, seed) LIMIT sample_limit`.
   - Seed defaults to `42`.

### 4.2 Parameter Validation
- `rate_percent`: Must satisfy $0.0 < \text{rate\_percent} \le 100.0$.
- `sample_limit`: Must be $\ge 1$.
- If both are provided, the dataset is sampled by rate first, then capped by `sample_limit`.

### 4.3 Family Grouping & SPV Filtering
- When `--group-family` is requested:
  - If `family_index_dataset` is missing or unreadable, the operation **fails closed** with `FamilyIndexNotFoundError`.
  - For entities not found in the family index (NULL family), each unindexed CIK is treated as its own independent singleton family (retained, never dropped).
  - Deduplicates to 1 representative per family, preferring operating companies over special purpose vehicles (`exclude_spv = True`).

### 4.4 Python Signature
```python
def sample_cohort(
    source_dataset: Path,
    output_dataset: Path,
    *,
    method: Literal["modulo", "random"] = "modulo",
    rate_percent: float | None = None,
    sample_limit: int | None = None,
    seed: int = 42,
    family_index_dataset: Path | None = None,
    group_by_family: bool = False,
    exclude_spv: bool = False,
) -> int: ...  # returns output row count
```

---

## 5. Stable Pagination Ordering Contract (`query.py`)

Query operations enforce deterministic ordering to prevent row duplicates or omissions across adjacent pages:

- **Single Cohort (`query_cohort_members`)**:
  - Strictly ordered by **`ordinal ASC`**.
  - `SELECT ordinal, cik_padded, name FROM read_parquet(?) WHERE ... ORDER BY ordinal ASC LIMIT ? OFFSET ?`
- **Global Search (`find_across_cohorts`)**:
  - Strictly ordered by **`cohort_id ASC, ordinal ASC`**.
  - Guarantees deterministic pagination when scanning multiple cohorts.
