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
│   ├── cohorts.sqlite                  # Shared SQLite database (WAL mode)
│   ├── cohorts.sqlite-wal
│   ├── cohorts.sqlite-shm
│   ├── universe-1dddc0e9b6076010/      # Published cohort directory
│   │   ├── ciks.parquet                # Canonical columnar dataset
│   │   └── cohort.json                 # Exported manifest metadata
│   ├── tickers-2e7351357647487b/
│   │   └── ciks.parquet
│   └── c-59508de79eafa64e/
│       ├── ciks.parquet
│       └── cohort.json
├── metadata/                           # Phase 01 pipeline root
└── filing_catalog/                     # Phase 02 pipeline root
```

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
MANIFEST_FILE_NAME = "cohort.json"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")


@dataclass(frozen=True, slots=True)
class CohortPaths:
    artifacts_root: Path

    @property
    def cohorts_root(self) -> Path:
        return self.artifacts_root / COHORTS_DIR_NAME

    @property
    def catalog_file(self) -> Path:
        return self.cohorts_root / CATALOG_DB_NAME

    def cohort_dir(self, cohort_id: str) -> Path:
        if not _SAFE_ID_RE.match(cohort_id) or ".." in cohort_id or "/" in cohort_id:
            raise ValueError(f"Invalid or unsafe cohort identifier: {cohort_id!r}")
        path = (self.cohorts_root / cohort_id).resolve()
        if path.parent != self.cohorts_root.resolve():
            raise ValueError(f"Cohort directory escapes root: {cohort_id!r}")
        return path

    def cohort_dataset_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / DATASET_FILE_NAME

    def cohort_manifest_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / MANIFEST_FILE_NAME


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
-- 1. Workspace Sessions & Active Context Pointer
CREATE TABLE IF NOT EXISTS workspace_sessions (
    session_id           TEXT PRIMARY KEY,
    description          TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_workspace_session (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    session_id           TEXT NOT NULL REFERENCES workspace_sessions(session_id) ON DELETE CASCADE,
    switched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Global Immutable Expression DAG Nodes (Content-Addressed)
CREATE TABLE IF NOT EXISTS objects (
    object_id            TEXT PRIMARY KEY,      -- SHA-256 of canonical JSON AST
    schema_name          TEXT NOT NULL,         -- e.g. 'cohort_expr_ast'
    parent_object_id     TEXT NULL REFERENCES objects(object_id) ON DELETE SET NULL,
    data                 TEXT NOT NULL,         -- Serialized JSON AST or SQL generator definition
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_objects_parent 
    ON objects (parent_object_id);

-- 3. Movable Session Aliases (Pointers: 'x' -> object_id or cohort_id)
CREATE TABLE IF NOT EXISTS object_session_aliases (
    session_id           TEXT NOT NULL REFERENCES workspace_sessions(session_id) ON DELETE CASCADE,
    alias_name           TEXT NOT NULL,         -- e.g. 'A', 'B', 'x'
    target_id            TEXT NOT NULL,         -- Points to objects.object_id OR published cohort_id
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, alias_name)
);

CREATE INDEX IF NOT EXISTS idx_session_aliases_target 
    ON object_session_aliases (target_id);
```

### 2.3 Global Expression Lifecycle & Alias Safety
1. **Decoupled Node Ownership**:
   - `objects` nodes do **not** carry a foreign key to `workspace_sessions`.
   - Expressions are content-addressed and immutable across the entire catalog.
   - If Session 1 creates expression `A + B` (hash `018f...`) and Session 2 later builds the identical expression, Session 2 safely references the existing node via `ON CONFLICT (object_id) DO NOTHING`.
   - When Session 1 expires or is cleared, only its alias rows in `object_session_aliases` are deleted; the immutable node in `objects` remains intact, preventing dangling pointer corruptions in Session 2.
2. **Alias Target Validation**:
   - Calling `upsert_alias(session_id, alias_name, target_id)` performs validation before committing:
     - Target must exist in `objects.object_id` OR in `cohorts.cohort_id`.
     - If neither exists, the operation raises `ValueError(f"Invalid alias target '{target_id}': entity not found")`.
3. **Active Session Resolution & Fallback**:
   - Active session is resolved in order:
     1. Explicit CLI argument: `--session <id>`.
     2. Context pointer: `SELECT session_id FROM active_workspace_session WHERE id = 1`.
     3. Fallback: `"default"`.
   - If the active session is deleted, expired, or cleared, subsequent operations automatically fall back to `"default"`, lazily inserting it into `workspace_sessions` if absent.
4. **Session TTL & Boot Cleanup**:
   - Every read/write operation in a session updates `workspace_sessions.updated_at = CURRENT_TIMESTAMP`.
   - At CLI startup (`edgar_sec.pipelines.cohort.cli`), `ObjectStore.clean_expired_sessions(max_age_seconds=86400)` runs automatically, pruning sessions inactive for $> 24$ hours.
   - Orphaned expression nodes (objects with no referencing aliases and no child references) are pruned during explicit `cohort workspace clean` sweeps.

---

## 3. Cohort Domain Catalog Schema (`cohorts.sqlite`)

Stored in the same SQLite database alongside the object store:

```sql
CREATE TABLE IF NOT EXISTS cohorts (
    cohort_id            TEXT PRIMARY KEY,      -- e.g. "c-59508de79eafa64e"
    name                 TEXT UNIQUE,           -- Unique human alias or NULL
    description          TEXT NOT NULL DEFAULT '',
    manifest_schema_ver  TEXT NOT NULL DEFAULT '2.0.0',
    origin_kind          TEXT NOT NULL,         -- 'official_source', 'file_import', 'set_operation', 'sample'
    origin_json          TEXT NOT NULL DEFAULT '{}',
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
```

---

## 4. Canonical Dataset Contract & Identity

Every cohort is stored as an immutable Parquet file at `.artifacts/cohorts/<cohort_id>/ciks.parquet`.

### 4.1 Canonical Schema & Deliberate Sorting Migration
All cohort Parquet files adhere to the schema:
```text
ordinal:     int64          (1-indexed monotonic sequence, 0 to N-1)
cik_padded:  string         (10-digit zero-padded string, regex: ^[0-9]{10}$)
name:        string         (Entity title, defaults to empty string "")
```
- **Deliberate Migration from Legacy Input Order**:
  - Legacy `compile_cik_cohort` in `metadata_sync` preserved file line occurrence order (`ORDER BY rn`), which made cohort identity fragile to line permutations.
  - In `CohortCatalog`, datasets are **strictly sorted ascending by numeric CIK** (`ORDER BY try_cast(cik_padded AS BIGINT) ASC`).
  - Permuting rows in an input file produces the identical canonical Parquet dataset and identical `cohort_id`.
  - When downstream `metadata_sync` requires a `Roster`, an adapter loads the canonical Parquet into a `Roster` object with ordinal addressing.

### 4.2 Deterministic Writer Settings
To guarantee byte reproducibility across runs, all Parquet writes enforce:
- `compression = "zstd"`
- `compression_level = 3`
- `row_group_size = 128_000`
- `dictionary_encode = False`

### 4.3 Identity Hash (`roster_id`) vs Integrity Digest (`dataset_sha256`)
- **`roster_id`**: SHA-256 digest of the canonical sorted text stream of unique CIKs (`\n`-separated `cik_padded` lines). Independent of compression settings or timestamps.
- **`dataset_sha256`**: SHA-256 digest of the physical `ciks.parquet` file on disk via `foundation.hashing.file_sha256`.
- **`cohort_id`**: `c-<roster_id[:16]>`.
- **Collision Refusal**: If a computed 16-hex prefix collides with an existing cohort with a different full `roster_id`, registration raises `CohortCollisionError`.

### 4.4 Atomic Staging, Publication & Recovery
A file and a SQLite database cannot be committed together in a single hardware transaction. The system enforces strict staged commits:
1. **Staging**: Assemble dataset in temporary staging directory `.artifacts/cohorts/.stage-<cohort_id>-<uuid>/`.
2. **Integrity Validation**: Write `ciks.parquet`, verify row counts and compute `dataset_sha256`. Write `cohort.json`.
3. **Atomic Rename**: `os.replace(stage_dir, final_dir)` atomically publishes the directory.
4. **Catalog Commit**: Insert metadata row into `cohorts.sqlite` in an atomic transaction.
5. **Recovery**:
   - If SQLite insert fails, remove `final_dir`.
   - Any stale `.stage-*` directories left by interrupted processes are cleaned up during boot sweeps.

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
