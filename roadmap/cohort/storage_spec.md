# Cohort Storage & Object Store Specification

This specification defines the storage layer (Layer 2) for cohorts and expressions:
- **`edgar_sec.infra.storage.object_store`**: Generic single-user hierarchical object store.
- **`edgar_sec.infra.storage.cohort`**: Domain-specific registrant dataset storage, catalog, and canonical dataset contracts.

Both subsystems share the embedded SQLite database at `.artifacts/cohorts/cohorts.sqlite` (WAL mode).

---

## 1. Directory Layout & Path Contract (`CohortPaths`)

The cohort subsystem lives as a sibling to pipeline artifacts under `.artifacts/cohorts/`:

```text
.artifacts/
├── cohorts/                            # Cohort storage root (CohortPaths.cohorts_root)
│   ├── cohorts.sqlite                  # Authoritative SQLite catalog (WAL mode)
│   ├── universe-1dddc0e9b6076010/      # Published universe cohort directory
│   │   └── ciks.parquet                # Canonical columnar dataset (1 row per CIK)
│   ├── tickers-2e7351357647487b/       # Published operating tickers cohort directory
│   │   └── ciks.parquet                # Canonical columnar dataset (1 row per CIK)
│   ├── c-59508de79eafa64e/             # Custom cohort directory
│   │   └── ciks.parquet
│   └── family_index/                   # Company family indices namespace
│       └── 7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d/
│           └── company_family.parquet
├── metadata/                           # Phase 01 pipeline root
└── filing_catalog/                     # Phase 02 pipeline root
```

*(Note: SQLite `-wal` and `-shm` files are transient engine files managed by SQLite WAL mode and are not guaranteed or tracked as repository artifacts.)*

### 1.1 Relative Path Portability
In `cohorts.sqlite`, `dataset_path` stores the relative path relative to `cohorts_root` (e.g. `c-59508de79eafa64e/ciks.parquet`). Path resolvers convert between relative stored strings and runtime `Path` instances:
- Guarantees portable execution across machines, containers, and WSL environments.
- Satisfies the repository rule forbidding hardcoded or absolute path references in persisted artifacts.

### 1.2 Path Resolution & Traversal Security
Located in `edgar_sec.infra.storage.cohort.paths`:
```python
COHORTS_DIR_NAME = "cohorts"
CATALOG_DB_NAME = "cohorts.sqlite"
DATASET_FILE_NAME = "ciks.parquet"
FAMILY_INDEX_DIR_NAME = "family_index"
FAMILY_INDEX_FILE_NAME = "company_family.parquet"

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")
_FAMILY_INDEX_ID_RE = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True, slots=True)
class CohortPaths:
    artifacts_root: Path

    @property
    def cohorts_root(self) -> Path:
        return self.artifacts_root / COHORTS_DIR_NAME

    @property
    def catalog_file(self) -> Path:
        return self.cohorts_root / CATALOG_DB_NAME

    @property
    def publication_lock_path(self) -> Path:
        return self.cohorts_root / ".publication.lock"

    @property
    def family_indices_root(self) -> Path:
        return self.cohorts_root / FAMILY_INDEX_DIR_NAME

    def cohort_dir(self, cohort_id: str) -> Path:
        if not _SAFE_ID_RE.match(cohort_id) or ".." in cohort_id or "/" in cohort_id:
            raise ValueError(f"Invalid or unsafe cohort identifier: {cohort_id!r}")
        path = (self.cohorts_root / cohort_id).resolve()
        if path.parent != self.cohorts_root.resolve():
            raise ValueError(f"Cohort directory escapes root: {cohort_id!r}")
        return path

    def cohort_dataset_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / DATASET_FILE_NAME

    def family_index_dir(self, family_index_id: str) -> Path:
        if not _FAMILY_INDEX_ID_RE.match(family_index_id):
            raise ValueError(f"Invalid family index identifier: {family_index_id!r}")
        target = (self.family_indices_root / family_index_id).resolve()
        if target.parent != self.family_indices_root.resolve():
            raise ValueError("Path traversal detected in family index id")
        return target

    def family_index_file(self, family_index_id: str) -> Path:
        return self.family_index_dir(family_index_id) / FAMILY_INDEX_FILE_NAME


def resolve_cohort_paths(
    artifacts_root: Path | str | None = None,
    *,
    project_paths: ProjectPaths | None = None,
) -> CohortPaths: ...
```

---

## 2. Generic Object Store (`infra.storage.object_store`)

`ObjectStore` provides domain-agnostic, single-user session tracking, movable alias pointers, and content-addressed immutable expression DAGs.

### 2.1 Connection Hardening & SQLite Settings
Per connection rules in `edgar_sec/infra/storage/dag/catalog.py`:
- SQLite connections are connection-local. Every connection opened by `ObjectStore` or `CohortCatalog` must execute:
  ```sql
  PRAGMA foreign_keys = ON;
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA page_size = 8192;
  ```
- `CohortWorkspace` accepts `CohortPaths` and verifies that `ObjectStore` and `CohortCatalog` are constructed on the exact same database file (`paths.catalog_file`).

### 2.2 Database Schema (`object_store/schema.py`)
```sql
CREATE TABLE IF NOT EXISTS workspace_sessions (
    session_id          TEXT PRIMARY KEY,
    description         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_accessed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS object_nodes (
    object_id           TEXT PRIMARY KEY,
    expression_kind     TEXT NOT NULL,
    expression_json     TEXT NOT NULL,
    result_hash         TEXT NOT NULL,
    row_count           INTEGER NOT NULL,
    distinct_cik_count  INTEGER NOT NULL,
    dataset_path        TEXT NOT NULL,
    dataset_sha256      TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS object_session_aliases (
    session_id          TEXT NOT NULL REFERENCES workspace_sessions(session_id) ON DELETE CASCADE,
    alias_name          TEXT NOT NULL,
    object_id           TEXT NOT NULL REFERENCES object_nodes(object_id),
    bound_at            TEXT NOT NULL,
    PRIMARY KEY (session_id, alias_name)
);

CREATE INDEX IF NOT EXISTS idx_object_aliases_object ON object_session_aliases(object_id);
```

---

## 3. Cohort Catalog Schema (`cohorts.sqlite`)

```sql
CREATE TABLE IF NOT EXISTS cohorts (
    cohort_id            TEXT PRIMARY KEY,      -- 'c-<16-hex>' or 'universe-<16-hex>'
    name                 TEXT UNIQUE,           -- Unique human alias, e.g. 'universe'
    description          TEXT NOT NULL DEFAULT '',
    manifest_schema_ver  INTEGER NOT NULL DEFAULT 1,
    origin_kind          TEXT NOT NULL,         -- 'file_import', 'official_source', 'expression'
    origin_json          TEXT NOT NULL,         -- Canonical JSON provenance details
    roster_id            TEXT NOT NULL,         -- SHA-256 of sorted CIK text stream
    row_count            INTEGER NOT NULL,
    distinct_cik_count   INTEGER NOT NULL,
    dataset_sha256       TEXT NOT NULL,         -- SHA-256 of physical ciks.parquet
    dataset_path         TEXT NOT NULL,         -- Relative path from cohorts_root
    pinned               INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cohorts_name ON cohorts(name);
CREATE INDEX IF NOT EXISTS idx_cohorts_pinned ON cohorts(pinned);
CREATE INDEX IF NOT EXISTS idx_cohorts_created ON cohorts(created_at);

CREATE TABLE IF NOT EXISTS cohort_tags (
    cohort_id            TEXT NOT NULL REFERENCES cohorts(cohort_id) ON DELETE CASCADE,
    tag                  TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    PRIMARY KEY (cohort_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_cohort_tags_tag ON cohort_tags(tag);

CREATE TABLE IF NOT EXISTS source_active_pointers (
    source_name          TEXT PRIMARY KEY,      -- 'cik_lookup' or 'company_tickers'
    active_snapshot_id   TEXT NOT NULL,
    pinned_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_family_indices (
    universe_cohort_id   TEXT NOT NULL REFERENCES cohorts(cohort_id),
    family_index_id      TEXT NOT NULL,         -- 32-hex identifier
    rules_fingerprint    TEXT NOT NULL,
    dataset_path         TEXT NOT NULL,
    dataset_sha256       TEXT NOT NULL,
    pinned_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (universe_cohort_id)
);

CREATE TABLE IF NOT EXISTS detached_cohort_datasets (
    cohort_id            TEXT PRIMARY KEY,
    dataset_path         TEXT NOT NULL,
    dataset_sha256       TEXT NOT NULL,
    detached_at          TEXT NOT NULL
);
```

---

## 4. Canonical Dataset Contract & Identity

Every cohort is stored as an immutable Parquet file at `.artifacts/cohorts/<cohort_id>/ciks.parquet`. All cohorts—including official operating tickers and SEC universe sources—compile directly to this canonical format.

### 4.1 Canonical Schema & Deliberate Sorting Migration
All cohort Parquet files adhere to the canonical schema:
```text
ordinal:     int64          (1-indexed monotonic sequence, 0 to N-1)
cik_padded:  string         (10-digit zero-padded string, regex: ^[0-9]{10}$)
name:        string         (Entity title, defaults to empty string "")
```
- **Sorting Invariant**: Datasets are **strictly sorted ascending by numeric CIK** (`ORDER BY try_cast(cik_padded AS BIGINT) ASC`).
- **1-Row-Per-CIK Invariant**: Canonical cohorts enforce `row_count == distinct_cik_count`.
- **Sole Canonical Format**: Downstream pipelines (`metadata_sync` plan and augment, `filing_catalog`) exclusively consume CIKs. No companion listing tables are generated or maintained. Operating filers with multiple listings in `company_tickers.json` resolve to a single canonical name via deterministic source order:
  ```sql
  first(nullif(trim(raw_name), '') ORDER BY source_order)
      FILTER (WHERE nullif(trim(raw_name), '') IS NOT NULL)
  ```

### 4.2 Deterministic Writer Settings
To guarantee byte reproducibility across runs, all Parquet writes enforce:
- `compression = "zstd"`
- `compression_level = 3`
- `row_group_size = 128_000`
- `dictionary_encode = False`

### 4.3 Identity Hash (`roster_id`) vs Integrity Digest (`dataset_sha256`)
- **`roster_id`**: SHA-256 digest of the canonical sorted text stream of unique CIKs (`\n`-separated `cik_padded` lines).
- **`dataset_sha256`**: SHA-256 digest of the physical `ciks.parquet` file on disk via `foundation.hashing.file_sha256`.
- **`cohort_id`**: `c-<roster_id[:16]>`.

### 4.4 Publication Locking, Leases & Scoped Pruning
1. **PublicationLock**: Moving staged directories to publication paths and committing SQLite records are serialized under `PublicationLock(paths.publication_lock_path)`. Maintenance sweeps also acquire this exclusive lock, preventing race conditions with in-flight publications.
2. **Multi-Attribute Lease**: Staging directories write `.stage.lease` recording `{host, pid, created_at, heartbeat}`. Long jobs update heartbeat every 30s. Explicit maintenance reclaims foreign leases older than 2 hours or dead local PIDs under `PublicationLock`; local live PIDs are never reclaimed.
3. **Integrity Validation**: Write `ciks.parquet`, verify row counts and compute `dataset_sha256`. Unlink `.stage.lease`.
4. **Atomic Rename & Catalog Commit**: `os.replace(stage_dir, final_dir)` and `INSERT INTO cohorts` execute under `PublicationLock`.
5. **Scoped Pruning & Retained Datasets**: Cleanup runs only through `cohort maintain`. Orphan sweeps target uncataloged `c-<16-hex>` directories and preserve detached datasets. `delete --keep-dataset` records the dataset path and digest in `detached_cohort_datasets` and writes a `.detached` sentinel. Historical raw snapshots are removed only by explicit `--clean-raw-snapshots`; family-index and workspace state are outside the cleanup scope.

### 4.5 Deletion Reference & Purge Guard
Calling `delete_cohort(cohort_id, purge_dataset=True)`:
1. **Reference Checks**:
   - Refuses if `pinned == 1` (`CohortPinnedError`).
   - Refuses if referenced by `source_active_pointers` (`CohortActiveSourceError`).
   - Refuses if referenced by any active alias in `object_session_aliases` (`CohortInUseError`), unless `--force` is specified.
2. **Purge Boundary Validation**:
   - Target directory is resolved and verified:
     `target_dir.resolve().parent == paths.cohorts_root.resolve()`
   - Deletion strictly purges only within `cohorts_root`. Never deletes external paths.
