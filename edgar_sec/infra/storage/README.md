# `edgar_sec/infra/storage` — every byte that outlives the process, and every DuckDB connection

This package is the persistence layer: atomic publication to disk, the Parquet
and SQLite formats, the DuckDB connection factory that keeps a large merge
inside the machine's memory budget, and the immutable-publication machinery a
snapshot is made of.

It holds no knowledge of which phase is running. Statements that encode a
phase's schema, filters, or derivation rules are compiled by the pipeline or
engine that owns them; what arrives here is the vocabulary those statements are
built from.

## Purpose

Two concerns, one package. First, **safe publication**: a reader must never
observe a half-written artifact, so every write stages to a temp file and
renames. Second, **bounded resources**: a merge that exceeds memory is an OOM
kill, so every DuckDB connection is configured from a machine probe rather than
from a default.

It is not a processing database and not an ORM. There is no schema migration
system and no table registry.

## Module map

| Module | Responsibility |
| :--- | :--- |
| `atomic.py` | The three atomic writers and the shared parent-directory fsync — the tmp-then-rename discipline the rest of the layer copies. |
| `parquet.py` | The Parquet format constants, the PyArrow read/write wrappers, and `StagedParquetWriter` for incremental chunk staging and resumption. |
| `duckdb.py` | `connect()`, the only `duckdb.connect()` call site in `edgar_sec`; the SQL dialect primitives (`sql_literal`, `sql_identifier`, `sql_path_list`); the atomic out-of-core COPY; and the generic duplicate/null-key checks. |
| `manifests.py` | Snapshot identity, immutable manifest publication, the `current` pointer, and the part-sharing analysis a safe purge needs. |
| `__init__.py` | Docstring only. No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **One connection factory, and every connection is bounded by the machine.**
  `connect()` is the only `duckdb.connect()` call site in `edgar_sec` and sets
  the four values AGENTS.md §2.3 requires, from
  `foundation.runtime.resources.derive_resources()` when the connection is
  opened rather than when the module is imported. The probe ladder and the
  worker budget are owned by
  [`../../foundation/runtime/README.md`](../../foundation/runtime/README.md).
- **Publication is atomic, and the temp name is pid-scoped.** A writer stages to
  `<name>.tmp.<pid>`, fsyncs, `os.replace`s onto the target, and fsyncs the
  parent directory, so a reader never observes a partial artifact. The one
  writer that does not force the directory entry is named under
  *Deliberate gaps*.
- **Parquet format lives in one place.** `DEFAULT_ROW_GROUP_SIZE = 128_000` and
  `DEFAULT_COMPRESSION = "zstd"` are the values AGENTS.md §2.5 names, and every
  write path takes them rather than re-declaring a literal.
- **JSON leaves through `atomic_write_json`, canonically by default.** It
  serializes with `foundation.serialization.canonical_json` and falls back to
  `json.dumps` only for a caller that explicitly asks for human-readable output.
- **Merges stay out of core.** `copy_query_to_parquet` runs
  `COPY (SELECT ... FROM ... ) TO ...` inside DuckDB and reads the row count off
  the written Parquet metadata, so a sorted result is produced by the engine
  rather than materialized in the Python heap.
- **SQL is escaped and validated at every interpolation point.**
  `sql_literal` doubles embedded quotes in literals, and `sql_identifier`
  rejects dotted names whose segments are not plain identifiers; every
  caller-supplied name and path goes through those two or through
  `sql_path_list`. The `sql-interpolation` scanner reports any value that reaches
  a query sink without passing one of them, so the guarantee is checked rather
  than reviewed. Where a part set is read from a manifest, the pipeline's
  `validate_part_paths` is the boundary check that runs first, because a
  recorded path is interpolated into SQL and a manifest is a file on disk that
  anyone can edit.
- **A document has one identity.** The catalog materialization SQL mints
  `document_locator_key` and `occurrence_id` as digests of accession, document
  path, and source CIK, and the document-storage chunk writer derives the same
  locator key in Python through `domain.document.models`. The two spellings must
  agree, so a document means the same thing whether it was fanned out from a
  published part or written by a chunk worker.
- **A published snapshot is immutable, and the pointer comes second.**
  `write_manifest` refuses a `snapshot_id` that already has a manifest, then
  writes the manifest, and only then publishes the pointer: a crash between the
  two leaves a stale pointer to a snapshot that does exist, which is strictly
  better than a pointer to one that does not. The pointer goes through
  `atomic_write_text` and the shared `current_pointer_path`, so every dataset
  resolves `current` identically. `snapshot_identity` digests sorted inputs, so
  consolidating the same sources twice yields the same id and a repeat is
  recognizably a no-op.
- **Part paths are snapshot-relative, and a purge is gated on part sharing.** A
  recorded part path resolves against its *own* snapshot directory, so a
  manifest cannot name a part belonging to another snapshot. `dependents_of` maps
  each snapshot to those whose recorded part paths intersect its own, and
  `expand_dependency_closure` grows a selection until nothing retained still
  shares a part with it — two snapshots sharing a part are physically entangled,
  so the dependent must be consolidated first.
- **Parts are byte-budgeted, and index and payload are separate projections of
  one logical record**, so a consumer can read metadata without the text. Fiscal
  year and quarter are deliberately *not* stored: they are derived at
  consolidation time, so an older snapshot consolidates alongside a newer one
  with no migration.
- **A chunk snapshot is validated against a fixed schema.**
  `write_chunk_snapshot` in the document-storage pipeline writes and validates
  chunk checkpoints against `DOCUMENT_SNAPSHOT_SCHEMA`, comparing a file's
  schema for exact name order and equality.
- **Fixture payloads are append-only evidence.** This belongs to the
  document-storage pipeline's fixture store, not here.

**Obligations callers place on this package**

- Obtain DuckDB connections from `connect()` and pass a shared
  `RuntimeResourceProfile` (or `None`) rather than per-call numbers, so one
  profile governs a whole run.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes; a
  per-call literal reintroduces the inconsistency they exist to remove, and the
  gate rejects one.
- Route every value that reaches a SQL statement through `sql_literal`,
  `sql_identifier`, or `sql_path_list`, or bind it as a parameter. The
  `sql-interpolation` scanner enforces this for modules not declared as SQL
  composers.
- Name the key column when calling `find_duplicate_keys` / `find_null_keys`;
  there is no default, because the primary key of a published dataset belongs to
  the dataset.
- Supply a writable parent for every write. Each function creates it before
  staging, so the caller does not have to — but the caller chooses where.
- Close what you open: the DuckDB connection, and any `SqlCache`. Nothing here
  registers an `atexit` hook.

## Public surface

Entry points by owning module; each module's docstring is authoritative for its
members.

- `atomic.py` — the three atomic writers, each returning the bytes written, plus
  the shared parent-directory fsync.
- `parquet.py` — the two format constants, the PyArrow read/write wrappers, and
  `StagedParquetWriter` for incremental chunk staging and resumption.
- `duckdb.py` — `connect()`, the SQL dialect primitives (`sql_literal`,
  `sql_identifier`, `sql_path_list`), `copy_query_to_parquet`, and the generic
  duplicate/null-key checks.
- `manifests.py` — snapshot identity and publication, the pointer, part
  resolution, and the dependency closure. The publishing dataset and phase are
  supplied by the caller, because several phases publish through this one
  function and a constant here would mislabel all but one of them.

**Command surface:** none. The consumer commands (`documents fill`, `documents
run`, `documents review-artifacts`, …) live in
`pipelines/document_storage/cli.py`, in Layer 4, not here.

## Mirrored tests

`tests/infra/storage/`, one file per source module.

## Deliberate gaps

- **No file-backed DuckDB staging API.** `connect()` opens an in-memory
  connection and query output is published with `copy_query_to_parquet`.
  Callers needing bulk inserts use `con.executemany()`; the package has no
  staging lifecycle, UDF-registration helper, or storage-error wrapper.
- **SQL construction lives with its owner.** This package provides the dialect
  primitives but no statement builders: a phase's schema and filters are
  compiled by the pipeline or engine that owns them. The repository's one SQL
  guard covers a different case — a query a human typed, not SQL the pipeline
  builds; see [`../../foundation/sql/README.md`](../../foundation/sql/README.md).
- **Parquet is the only chunk interchange format.** There is no JSONL or SQLite
  checkpoint backend. The fixture store is separate and holds payload evidence,
  not processing or chunk state.
- **No schema migration or table registry.** The only versioning is the
  `schema_version` string inside a manifest; nothing migrates an artifact written
  under a different one, and a reader must treat a mismatch as its own problem.
- **No deletion or vacuum of Parquet parts here, and the purge guard is
  advisory.** The dependency analysis computes what is safe to remove, but
  nothing in this package deletes anything and nothing enforces the closure. The
  removal itself lives in
  [`../../pipelines/document_storage/README.md`](../../pipelines/document_storage/README.md).
- **A damaged snapshot is skipped, not fatal.** `list_snapshots` logs a warning
  and omits a manifest it cannot read or parse, so consolidation proceeds on a
  partial view rather than letting one bad directory stop everything.
  `read_pointer` likewise returns `None` for a missing or corrupt pointer
  instead of raising.
- **`SnapshotReader.logical_fingerprint` falls back to the snapshot id** when the
  manifest records no fingerprint, so a reader that compares the result against a
  real fingerprint is comparing two different things.
- **`copy_query_to_parquet` does not fsync the parent directory**, unlike every
  other writer in the package. The rename is atomic; the durability of the
  directory entry is not forced.
- **The `resource-allocation` scanner does not see through indirection.** It is a
  line-level rule, so a limit hidden behind a variable or a settings lookup is
  not flagged. The `connect()` contract holds by having exactly one
  `duckdb.connect()` call site, not because the scanner proves it.
