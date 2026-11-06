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

## Contracts

**Guarantees this package makes to its callers**

- **One connection factory, and every connection is bounded by the machine.**
  `connect()` is the only `duckdb.connect()` call site in `edgar_sec` and sets
  the values AGENTS.md requires, from
  `foundation.runtime.resources.derive_resources()` when the connection is
  opened rather than when the module is imported. The probe ladder and the
  worker budget are owned by
  [`../../foundation/runtime/README.md`](../../foundation/runtime/README.md).
- **Publication is atomic, and the temp name is pid-scoped.** A writer stages to
  `<name>.tmp.<pid>`, fsyncs, `os.replace`s onto the target, and fsyncs the
  parent directory, so a reader never observes a partial artifact.
- **Parquet format lives in one place.** The compression default is declared in
  `parquet.py` and the row-group size is resolved through
  `foundation.runtime.settings.parquet`; every write path takes them rather
  than re-declaring a literal.
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
- **The corpus index stores coordinates, not semantics.** `corpus_index.py`
  owns the `concept_coordinates` DuckDB schema and its screening filters;
  rows arrive as caller-derived plain data (cik, accession, concept, head,
  modifiers, residual mass, item type), are replaced per filing on
  re-ingest, and gain no equivalence meaning in this package.
- **A document has one identity.** The catalog materialization SQL mints
  `document_locator_key` and `occurrence_id` as digests of accession, document
  path, and source CIK, so a document means the same thing wherever its
  occurrence was written from.
- **Snapshot mechanics live in [`dag/`](dag/README.md).** The DAG catalog owns
  manifests, branch pointers, and retention; this package supplies only the
  atomic writers and Parquet/DuckDB primitives those mechanics are built from.
- **Parts are byte-budgeted, and index and payload are separate projections of
  one logical record**, so a consumer can read metadata without the text. Fiscal
  year and quarter are deliberately *not* stored: they are derived at
  consolidation time, so an older snapshot consolidates alongside a newer one
  with no migration.
- **Expression nodes are global and immutable; aliases are session-scoped.**
  [`object_store/`](object_store/README.md) owns the SQLite schema and validates
  alias targets before moving a pointer.
- **Cohort identities refer to immutable datasets.** The shared
  [`cohort/`](cohort/README.md) package owns relative paths, catalog records,
  source pointers, and lifecycle guards.
- **CIK, not name, determines membership.** File intake selects the first
  non-empty label in input order; union/intersection select the left operand's
  non-empty name before the right. Callers must place the preferred label source
  on the left; conflicting payloads for an existing CIK-set identity are refused.
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
  nothing in this package deletes anything or enforces the closure. Artifact-owning
  pipelines must coordinate part removal explicitly.
- **The `resource-allocation` scanner does not see through indirection.** It is a
  line-level rule, so a limit hidden behind a variable or a settings lookup is
  not flagged. The `connect()` contract holds by having exactly one
  `duckdb.connect()` call site, not because the scanner proves it.
