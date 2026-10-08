# Cohort Ingestion, Sources & Relational Operations Specification

This specification defines the ingestion workflows, official SEC source management, relational set algebra, sampling, and comparison capabilities in `edgar_sec.pipelines.cohort` (Layer 4), delegating catalog and dataset persistence to `edgar_sec.infra.storage.cohort` (Layer 2).

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

Dedicated module `edgar_sec.pipelines.cohort.sources` manages official SEC reference registries.

### 2.1 Managed Official Sources
1. **Universe (`cik_lookup`)**:
   - Source: SEC `cik_lookup.txt` (full historical universe of ~980,000+ filers).
   - Stored with `origin_kind = 'official_source'`, `pinned = 1`.
   - Publishes canonical `ciks.parquet` under `c-<cohort_id>/`.
2. **Active Tickers (`company_tickers`)**:
   - Source: SEC `company_tickers.json` (~10,000+ active operating companies).
   - Stored with `origin_kind = 'official_source'`, `pinned = 1`.
   - Publishes canonical `ciks.parquet` (1 row per distinct CIK). Zero companion listing files are needed.

### 2.2 Canonical Name Priority Policy
For CIKs with multiple listings in `company_tickers.json`, the single canonical name for `ciks.parquet` is selected via deterministic source order:
```sql
first(nullif(trim(raw_name), '') ORDER BY source_order)
    FILTER (WHERE nullif(trim(raw_name), '') IS NOT NULL)
```

### 2.3 Active Version Management (SQLite WAL)
Active version pointers are stored in `source_active_pointers` in `cohorts.sqlite`:
- **Read Active Version**:
  `SELECT active_snapshot_id FROM source_active_pointers WHERE source_name = ?`
- **Atomic Pointer Swap**:
  `CohortCatalog.set_active_source_pointer(source_name, active_snapshot_id)`
  Enforces that `active_snapshot_id` exists in `cohorts`, has `origin_kind == 'official_source'`, and is pinned (`pinned == 1`).

### 2.4 Byte-Preserving Deduplication
Deduplication evaluates raw payload bytes directly via `hashlib.sha256(payload_bytes).hexdigest()`. If `(source_name, raw_source_sha256, parser_version, schema_version)` matches an existing cohort whose datasets are intact on disk, refresh exits immediately with zero re-work, preserving existing timestamps.

### 2.5 Python Signatures
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
```

---

## 3. Relational Set Algebra & Generic Diffing Engine (`operations.py`)

### 3.1 Relational Set Algebra
- **Operations Supported**: Union (`+`), Intersection (`&`), Difference (`-`).
- **AST Generation**: Compiles nested algebraic expressions (e.g. `(A + B) - C`) into a single DuckDB SQL query.
- **Relational Merge Execution**: Executes compiled AST against underlying `ciks.parquet` tables, publishing the evaluated result as a new canonical cohort.

### 3.2 Generic Cohort Diffing Engine
Diffing is generalized across all cohorts rather than coupled to raw SEC files or ticker listings. An operator imports any input (e.g., `cohort import --input curated.csv --name curated`) and diffs it against official sources (`tickers`, `universe`) or other custom cohorts.

```python
@dataclass(frozen=True, slots=True)
class SetDiffReport:
    left_count: int
    right_count: int
    left_only_count: int
    right_only_count: int
    union_count: int
    intersection_count: int
    sample_left_only: tuple[tuple[str, str], ...]
    sample_right_only: tuple[tuple[str, str], ...]
    delta_cohort_record: CohortRecord | None = None


def diff_cohorts(
    left_dataset: Path,
    right_dataset: Path,
    *,
    left_name: str = "A",
    right_name: str = "B",
    sample_limit: int = 5,
    save_delta_name: str | None = None,
    catalog: CohortCatalog | None = None,
    paths: CohortPaths | None = None,
) -> SetDiffReport: ...
```

- **Set Difference Metrics**: Computes cardinalities via DuckDB: `left_count`, `right_count`, `left_only_count` (`LEFT ANTI JOIN`), `right_only_count` (`RIGHT ANTI JOIN`), `union_count` (`UNION`), and `intersection_count` (`INNER JOIN`).
- **Sample Roster Preview**: Extracts preview samples `(cik_padded, name)` for inspection.
- **Optional Delta Publication**: When `save_delta_name` is provided, stages and publishes the difference cohort (`left - right`) atomically under `PublicationLock`.

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
  - `family_index_dataset: Path` **must be explicitly provided**. If `None` or missing, the operation **strictly fails closed** with `FamilyIndexNotFoundError`.
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
  - Guarantees deterministic pagination when scanning multiple cohorts (`LIMIT ? OFFSET ((page - 1) * limit)`).
