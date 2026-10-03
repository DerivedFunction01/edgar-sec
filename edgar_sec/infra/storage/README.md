# `edgar_sec/infra/storage` — every byte that outlives the process, and every DuckDB connection

This package is the persistence layer: atomic publication to disk, the Parquet
and SQLite formats, the DuckDB connection factory that keeps a large merge
inside the machine's memory budget, the filing-catalog SQL, and the
document-snapshot machinery.

## Purpose

Two concerns, one package. First, **safe publication**: a reader must never
observe a half-written artifact, so every write stages to a temp file and
renames. Second, **bounded resources**: a merge that exceeds memory is an OOM
kill, so every DuckDB connection is configured from a machine probe rather than
from a default.

It is not a processing database and not an ORM. There is no schema migration
system, no table registry, and no query builder beyond the SQL vocabulary
`duckdb_catalog.py` exposes for a specific caller.

## Module map

| Module | Responsibility |
| :--- | :--- |
| `atomic.py` | The three atomic writers and the shared parent-directory fsync — the tmp-then-rename discipline the rest of the layer copies. |
| `parquet.py` | The Parquet format constants, the PyArrow read/write wrappers, and `StagedParquetWriter` for incremental chunk staging and resumption. |
| `duckdb.py` | `connect()`, the only `duckdb.connect()` call site in `edgar_sec`, plus the out-of-core merge and the merge-validation queries. |
| `duckdb_catalog.py` | Filing-catalog SQL builders, document identity hashing, and the atomic query-to-Parquet COPY. |
| `document_parquet.py` | Document chunk-snapshot write, schema validation, and out-of-core assembly. |
| `document_parts.py` | Byte-budgeted part planning and the index/payload column contracts. |
| `manifests.py` | Snapshot identity, immutable manifest publication, the `current` pointer, and the part-sharing analysis a safe purge needs. |
| `fixture_store.py` | The append-only raw-payload SQLite store behind fixture fill and offline replay. |
| `fixture_lineage.py` | Pure comparison of a fixture manifest against a plan. |
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
- **Merges stay out of core.** Both publication paths run a `COPY (SELECT ...
  FROM read_parquet([...]) ORDER BY ...) TO ...` inside DuckDB and read the row
  count back off the output, so a sorted result is produced by the engine rather
  than materialized in the Python heap. The validation beside it is three narrow
  queries — duplicate keys, null keys, duplicate values inside a nested column —
  not a general validator.
- **SQL is escaped and validated at every interpolation point.**
  `duckdb_catalog` doubles embedded quotes in literals and rejects dotted names
  whose segments are not plain identifiers, and every caller-supplied name and
  path goes through those two. `document_parts` is the same story from the
  other side: `relation_for_parts` escapes paths itself, and
  `validate_part_paths` is the boundary check that runs first, because a
  recorded path is interpolated into SQL and a manifest is a file on disk that
  anyone can edit.
- **A document has one identity.** The catalog builder mints
  `document_locator_key` and `occurrence_id` as digests of accession, document
  path, and source CIK, and `write_chunk_snapshot` derives the same locator key
  in Python through `domain.document.models`. The two spellings must agree, so a
  document means the same thing whether it was fanned out from a published part
  or written by a chunk worker.
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
  `validate_chunk_snapshot` compares a file's schema to
  `DOCUMENT_SNAPSHOT_SCHEMA` for exact name order and equality, and reports row,
  row-group, and byte statistics; `form` and `filing_date` are carried from the
  occurrence rather than derived, because a stored document without them cannot
  be repartitioned into fiscal quarters later. Assembly is out-of-core, sorted,
  and counted.
- **Fixture payloads are append-only evidence.** A writable store inserts with
  ignore semantics so a recorded payload is never replaced by a later response,
  and a reader opens the database read-only. BLOB compression is the shared
  codec in `foundation/compression.py`.
- **Fixture lineage validation is pure and asymmetric.** A missing field means
  "unknown", not "mismatched", so a fixture recorded before lineage was tracked
  is not stranded; `fixture_lineage_status` reports `unknown`, `partial`, or
  `recorded`.

**Obligations callers place on this package**

- Obtain DuckDB connections from `connect()` and pass a shared
  `RuntimeResourceProfile` (or `None`) rather than per-call numbers, so one
  profile governs a whole run.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes; a
  per-call literal reintroduces the inconsistency they exist to remove, and the
  gate rejects one.
- Pass a **sorted** document-size sequence to `plan_parts`, and treat the
  returned document-id ranges as contiguous.
- Run `validate_part_paths` before `relation_for_parts` on any part list read
  from a manifest.
- Supply a writable parent for every write. Each function creates it before
  staging, so the caller does not have to — but the caller chooses where.
- Close what you open: the DuckDB connection, and any `SqlCache` or
  `FixtureStore`. Nothing here registers an `atexit` hook.
- For `write_chunk_snapshot`, supply texts and statuses keyed by
  `occurrence_id`. A missing status defaults to `ok`, a missing text to the empty
  string, and a missing raw blob to an empty payload with a zero byte size rather
  than a failure.

## Public surface

Entry points by owning module; each module's docstring is authoritative for its
members.

- `atomic.py` — the three atomic writers, each returning the bytes written, plus
  the shared parent-directory fsync.
- `parquet.py` — the two format constants, the PyArrow read/write wrappers, and
  `StagedParquetWriter` for incremental chunk staging and resumption.
- `duckdb.py` — `connect()`, the out-of-core merge, and the merge-validation
  queries.
- `duckdb_catalog.py` — the catalog SQL vocabulary: literal and identifier
  safety, the part, profile, and target query builders, the date projections,
  and `copy_query_to_parquet`.
- `document_parquet.py` — `DOCUMENT_SNAPSHOT_SCHEMA` and the
  write/validate/assemble trio.
- `document_parts.py` — the part column contracts, `plan_parts`, the index and
  payload writers, and the part-path boundary checks.
- `manifests.py` — snapshot identity and publication, the pointer, part
  resolution, and the dependency closure. `DATASET` (`document_storage`) and
  `PHASE` (`025_webpage_storage`) are fixed constants stamped into the pointer.
- `fixture_store.py` — `FixtureStore` over the `fixture_payloads` table in
  `fixture.sqlite`, plus its optional metadata tables.
- `fixture_lineage.py` — the lineage comparison and its status vocabulary.

**Command surface:** none. The consumer commands (`documents fill`, `documents
run`, `documents review-artifacts`, …) live in
`pipelines/document_storage/cli.py`, in Layer 4, not here.

## Mirrored tests

`tests/infra/storage/`, one file per source module. One module,
`document_parts.py`, has no mirrored file, so the part-planning contract is
exercised only through `tests/pipelines/document_storage/`.

## Deliberate gaps

- **No file-backed DuckDB staging API.** `connect()` opens an in-memory
  connection and query output is published with `copy_query_to_parquet`.
  Callers needing bulk inserts use `con.executemany()`; the package has no
  staging lifecycle, UDF-registration helper, or storage-error wrapper.
- **SQL is built directly, and no scanner inspects it.** The catalog and Parquet
  helpers construct SQL text, so safety is the escaping and identifier
  validation described above, reviewed by hand whenever a query input is added;
  there is no AST or compiler layer. The repository's one SQL guard covers a
  different case — a query a human typed, not SQL the pipeline builds; see
  [`../../foundation/sql/README.md`](../../foundation/sql/README.md).
- **Parquet is the only chunk interchange format.** There is no JSONL or SQLite
  checkpoint backend, and `concat_to_parquet`'s docstring still claims to
  concatenate JSONL chunks while the body reads Parquet only. The fixture store
  is separate and holds payload evidence, not processing or chunk state.
- **No schema migration or table registry.** The only versioning is the
  `schema_version` string inside a manifest; nothing migrates an artifact written
  under a different one, and a reader must treat a mismatch as its own problem.
- **No content-addressed payload store.** `fixture_payloads` is keyed by
  `doc_id` alone and treats a recorded payload as evidence, so a re-fetched
  document's earlier revision is not retained and there is no "newest revision
  wins" read path to keep correct.
- **No deletion or vacuum of Parquet parts here, and the purge guard is
  advisory.** The dependency analysis computes what is safe to remove, but
  nothing in this package deletes anything and nothing enforces the closure. The
  removal itself, and the only place the closure is checked before it, live in
  [`../../pipelines/document_storage/README.md`](../../pipelines/document_storage/README.md)
  — which is itself currently unwired.
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
- **Parts are planned per quarter, not per snapshot.** `quarter_path` builds a
  path from exactly one year and quarter, so a snapshot spanning several fiscal
  quarters needs one planning call per quarter, and nothing validates that a
  caller passes a coherent pair.
- **The `document_parts` module docstring overstates its compression story.** It
  claims `zstandard` is confined alongside PyArrow, but the module imports only
  `pyarrow`: parts are Parquet files using the `zstd` codec, and the
  `zstandard` library is not on that path at all.
- **`fixture_lineage` has no consumer.** The check is called from nothing outside
  its own test, so the guard that stops a plan being replayed against a fixture
  built from a different plan is not wired into the offline fetch path.
- **The `resource-allocation` scanner does not see through indirection.** It is a
  line-level rule, so a limit hidden behind a variable or a settings lookup is
  not flagged. The `connect()` contract holds by having exactly one
  `duckdb.connect()` call site, not because the scanner proves it.
