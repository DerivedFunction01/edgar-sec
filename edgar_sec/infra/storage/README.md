# `edgar_sec/infra/storage` — every byte that outlives the process, and every DuckDB connection

This package is the persistence layer: atomic publication to disk, the Parquet
and SQLite formats, the DuckDB connection factory that keeps a large merge
inside the machine's memory budget, the filing-catalog SQL, and the Phase 2.5
document-snapshot machinery.

## Purpose

Two concerns, one package. First, **safe publication**: a reader must never
observe a half-written artifact, so every write here stages to a temp file and
renames. Second, **bounded resources**: a merge that exceeds memory is an OOM
kill, so every DuckDB connection is configured from a machine probe rather than
from a default.

It is not a processing database and not an ORM. There is no schema migration
system, no table registry, and no query builder beyond the handful of functions
in `duckdb_catalog.py` that exist because a specific pipeline needs them.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `atomic.py` | `atomic_write_bytes` / `_text` / `_json` plus `_fsync_dir`, the tmp-then-rename discipline the rest of the layer copies. |
| `parquet.py` | `StagedParquetWriter` (incremental chunk staging and resumption), the format constants, and the PyArrow read/write wrappers. |
| `duckdb.py` | `connect()` — the only `duckdb.connect()` call site in `edgar_sec` — plus the out-of-core merge and the merge-validation queries. |
| `duckdb_catalog.py` | Filing-catalog SQL builders and the atomic query-to-Parquet COPY. |
| `document_parquet.py` | Phase 2.5 chunk snapshot write / validate / assemble. |
| `document_parts.py` | Byte-budgeted part planning and the index/payload column contracts. |
| `manifests.py` | Snapshot identity, immutable manifest publication, and the `current` pointer. |
| `fixture_store.py` | Append-only `fixture_payloads(doc_id, raw_payload)` SQLite store used by offline replay and fixture fill. |
| `fixture_lineage.py` | Pure comparison of a fixture manifest against a plan. |
| `__init__.py` | Docstring only. No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **Every DuckDB connection is bounded by the machine, and there is exactly one
  place a connection is made.** `connect()` unconditionally sets all four values
  AGENTS.md §2.3 requires — `threads` (clamped to `max(1, int(...))`),
  `memory_limit`, `temp_directory`, and `preserve_insertion_order = false`. With
  no `profile` argument it calls `foundation.runtime.resources.derive_resources()`
  itself, at call time rather than import time, so the cgroup probe happens when a
  connection is opened and not when the module is loaded. Behind it,
  `available_memory_bytes()` walks cgroups v2, cgroups v1, psutil `.available`,
  then `/proc/meminfo` `MemAvailable`, falling back to physical memory only if
  none of those resolve; worker counts come from
  `auto_worker_count(available, worker_memory_mib=512, safety_fraction=0.9)`.
  Every one of `connect()`'s parameters is `None`-defaulted rather than
  literal-valued, because the `resource-allocation` scanner
  (`foundation/scanners/resources.py`) fails the build on any
  `threads=` / `max_workers=` / `memory_limit=` literal outside
  `foundation/runtime/resources.py`, `runtime/settings/`,
  `foundation/scanners/`, and tests.
- **Every write is atomic, and the tmp-file name is pid-scoped.**
  `atomic_write_bytes` writes `<path>.tmp.<pid>`, `fsync`s the file,
  `os.replace`s onto the target, `fsync`s the parent directory, and removes the
  temp file in a `finally`. The same pattern is repeated in
  `parquet.write_parquet_table`, `duckdb.concat_to_parquet`,
  `document_parts._write_part`, and — with a dot-prefixed temp name —
  `duckdb_catalog.copy_query_to_parquet`.
  `document_parquet.write_chunk_snapshot` gets it by delegating to
  `StagedParquetWriter`, which stages to a sibling `.tmp` and promotes on
  `commit()`.
  `duckdb_catalog.copy_query_to_parquet` is the one writer that does not fsync
  the parent directory; its `os.replace` is still atomic, but it does not force
  the rename to disk.
- **Parquet format constants live in one place.** `DEFAULT_ROW_GROUP_SIZE =
  128_000` and `DEFAULT_COMPRESSION = "zstd"` are the values AGENTS.md §2.5
  names. `duckdb.concat_to_parquet` and `duckdb_catalog.copy_query_to_parquet`
  both take them as defaults rather than re-declaring literals, and
  `document_parquet` and `document_parts` pass them straight to
  `pq.write_table`.
- **JSON goes out through `atomic_write_json`, canonically by default.** It
  serializes with `foundation.serialization.canonical_json` — sorted keys,
  compact separators, `ensure_ascii=True` — and falls back to `json.dumps` only
  when a caller passes `canonical=False`, which exists for human-readable files
  such as `plan.json` (`pipelines/metadata_sync/planner.py`). The `json-io`
  scanner (`foundation/scanners/json_io.py`) enforces both halves: it flags any
  redefinition of the canonical-JSON and load helpers, and it flags
  non-atomic write shapes. Its only exemptions are the two modules that own the
  primitives, `foundation/serialization.py` and `infra/storage/atomic.py`.
- **Merges stay out of core.** `concat_to_parquet` runs
  `COPY (SELECT * FROM read_parquet([...]) ORDER BY ...) TO ...` inside DuckDB,
  so the result is sorted and written by the engine rather than materialized in
  the Python heap, and it returns the row count by re-counting the output file.
  `copy_query_to_parquet` is the same idea for an arbitrary query and returns
  `count_parquet_rows(path)`.
- **Merge validation is three narrow queries, not a general validator.**
  `find_duplicate_keys` finds primary-key duplicates across chunks,
  `find_null_keys` returns a null count, and `find_duplicate_nested_values`
  finds duplicates inside a struct-list column such as
  `filings.accession_number` via `unnest`. Both duplicate-finding queries cap
  their output at `LIMIT 100`.
- **SQL is built with escaping at every interpolation point.** `duckdb_catalog`
  has two primitives: `sql_literal` doubles embedded single quotes, and
  `_qualified_identifier` rejects any dotted name whose segments do not all match
  `^[A-Za-z_][A-Za-z0-9_]*$`. `suffix_sql`, `build_profile_query`, and
  `build_merged_targets_query` route every caller-supplied name through the
  second; `build_part_unnest_query` takes a part list (a bare string is treated
  as a one-element list) and emits it through `sql_path_list`, which wraps each
  element in `sql_literal` rather than joining a string. `document_parts`
  `relation_for_parts` escapes embedded quotes itself, and `validate_part_paths`
  is the boundary check that runs first: it rejects an empty path, a `..` segment
  or an absolute path, a path containing `'`, `"`, or `;`, and a recorded file
  that does not exist. The reasoning is stated in the docstring: a recorded path
  is interpolated into SQL, and a manifest is a file on disk that anyone can
  edit, so the check belongs at the boundary.
- **Document identity is one function, reused.**
  `duckdb_catalog.build_part_unnest_query` mints `document_locator_key` as
  `sha256(accession || ':' || document_path)` and `occurrence_id` as
  `sha256(source_cik || ':' || accession || ':' || document_path)` in SQL, and
  `document_parquet.write_chunk_snapshot` derives the same key in Python via
  `domain.document.models.derive_document_locator_key`. A document is identified
  the same way whether it was fanned out from a Phase 1 part or written by a
  Phase 2.5 worker.
- **A snapshot is immutable once published.** `write_manifest` refuses to write
  under a `snapshot_id` whose `manifest.json` already exists, because a published
  id is referenced from other records and overwriting it would retroactively
  change what those references mean.
- **The pointer is written after the manifest, never before.** `write_manifest`
  writes the manifest and only then calls `publish_pointer`; a crash between the
  two leaves a stale pointer to a snapshot that does exist, which is strictly
  better than a pointer to one that does not. `publish_pointer` writes
  `<root>/current/pointer.json` through `atomic_write_text` and
  `canonical_json`, using the shared `foundation.runtime.paths.current_pointer_path`
  so every dataset resolves "current" identically.
- **Snapshot ids are deterministic.** `snapshot_identity` is
  `f"{operation}-{sha256_text(canonical_json(payload))[:16]}"` over *sorted*
  inputs, so consolidating the same sources twice yields the same id and a
  repeated consolidation is recognizably a no-op rather than a second
  near-identical snapshot.
- **A snapshot is a set of parts, planned by byte size, with snapshot-relative
  paths.** `plan_parts` fills a part until the next document would exceed
  `target_bytes`, and requires `doc_ids` to be sorted because the plan is derived
  from a contiguous document range a reader streams one part at a time. The
  rationale is in the module docstring: normalized document text is wildly
  uneven, so counting rows would produce parts differing by three orders of
  magnitude in bytes. A part's recorded path is
  `parts/<kind>/<year>-<quarter>.parquet`, relative to its *own snapshot
  directory* (`quarter_path`) — deliberately not to the snapshots root, so a
  manifest cannot name a part belonging to a different snapshot.
- **Index and payload are separate projections of one logical record.**
  `INDEX_COLUMNS` is 11 string columns — `occurrence_id`, `source_cik`,
  `accession`, `form`, `filing_date`, `report_date`, `document_path`, `doc_id`,
  `mime_type`, `byte_size`, `payload_file` — so a consumer can read metadata
  without the text. `PAYLOAD_COLUMNS` is `("doc_id", "clean_text")`.
  `filing_year` and `filing_quarter` are deliberately *not* stored: they are
  derived at consolidation time, so an older snapshot consolidates alongside a
  newer one with no migration. `write_index_part` returns a `SnapshotPart` whose
  `row_count` and `byte_size` are read back off the finished file.
- **Parts are Parquet with the `zstd` codec, not zstandard BLOBs.**
  `_write_part` calls `pq.write_table` with `DEFAULT_COMPRESSION` and
  `DEFAULT_ROW_GROUP_SIZE`, so the format already compressed the file and the
  `zstandard` library is never on that path. The one place in this package that
  compresses a BLOB column is `fixture_store.py`, and it does so through
  `foundation.compression.compress_payload` — the codec shared with the `sec_http`
  response cache. `fixture_store.py` does import `zstandard`, but only for the
  `zstd.ZstdError` type it catches on a failed read or write.
- **Fixture lineage validation is pure and asymmetric.**
  `check_fixture_lineage` compares three identity axes — `catalog_id`,
  `policy_corpus`, `seed_fingerprint` — plus a case-insensitive form set, and
  raises `FixtureLineageError` only when *both* sides declare a value and they
  differ. The asymmetry is the point and is stated in the docstring: a missing
  field means "unknown", not "mismatched", so fixtures recorded before lineage
  was tracked are not stranded. `fixture_lineage_status` returns `"unknown"`,
  `"partial"`, or `"recorded"`.
- **A chunk snapshot is validated against a fixed schema.**
  `validate_chunk_snapshot` compares the file's schema names to
  `DOCUMENT_SNAPSHOT_SCHEMA.names` for exact order and equality, raising
  `ValueError` on any mismatch, and returns `path`, `num_rows`, `num_row_groups`,
  and `serialized_size_bytes`. `DOCUMENT_SNAPSHOT_SCHEMA` is 13 columns:
  `occurrence_id`, `source_cik`, `accession`, `document_path`,
  `document_locator_key`, `blob_hash`, `form`, `filing_date`, `raw_payload`
  (binary), `byte_size` (int64), `normalized_text`, `status`, `error_message`.
  `form` and `filing_date` are carried from the occurrence rather than derived,
  because a stored document without them cannot be repartitioned into fiscal
  quarters later.
- **Assembly is out-of-core, sorted, and counted.**
  `assemble_document_snapshots` opens a bounded connection, runs
  `COPY (SELECT * FROM read_parquet([...]) ORDER BY source_cik, accession) TO ...`
  with the standard row-group size and compression, renames into place, fsyncs
  the directory, and returns the row count read back from the output. It ignores
  chunk paths that are not files and raises `ValueError` when nothing valid
  remains.
- **A purge is gated on part sharing.** `dependents_of` maps each source snapshot
  to the snapshots whose recorded part paths intersect its own, and
  `expand_dependency_closure` grows a selection until nothing retained still
  shares a part with anything in it. Two snapshots sharing a part are physically
  entangled, so the dependent must be consolidated first.
- **Environment access is nil.** No module in this package reads `os.environ` or
  calls `os.getenv`; path roots are passed in as arguments. This is what
  `environment-access` enforces, and manifests and plans are persisted artifacts
  that must not carry machine-specific overrides.

**Obligations callers place on this package**

- Obtain DuckDB connections from `connect()` and pass a shared
  `RuntimeResourceProfile` (or `None`) rather than per-call numbers, so one
  profile governs a whole run.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes; a
  per-call literal reintroduces the inconsistency they exist to remove.
- Pass a **sorted** `doc_sizes` sequence to `plan_parts`, and treat the returned
  `PlannedPart.doc_ids` ranges as contiguous.
- Run `validate_part_paths` before `relation_for_parts` on any part list read
  from a manifest. The two docstrings say so explicitly.
- Supply a writable parent for every write; each function does
  `mkdir(parents=True, exist_ok=True)` before staging, so the caller does not
  have to — but the caller chooses where.
- Close `SqlCache` / `FixtureStore` connections; nothing here registers an
  `atexit` hook.
- For `write_chunk_snapshot`, supply `normalized_texts` and `statuses` keyed by
  `occurrence_id`; a missing status defaults to `"ok"` and a missing text to
  `""`, and a `raw_blobs` miss writes an empty payload with `byte_size = 0`
  rather than failing.

## Public surface

- `atomic_write_bytes`, `atomic_write_text`, `atomic_write_json` — the three
  atomic writers; each returns the number of bytes written. `atomic_write_json`
  takes `canonical: bool = True` and `indent: int | None = None`.
- `_fsync_dir` — the shared parent-directory fsync, private by naming but
  imported by `parquet.py`, `duckdb.py`, `document_parquet.py`, and
  `document_parts.py`.
- `DEFAULT_ROW_GROUP_SIZE`, `DEFAULT_COMPRESSION` — the Parquet format
  vocabulary. `parquet.py`.
- `write_parquet_table`, `read_parquet_table`, `read_parquet_schema`,
  `count_parquet_rows` — PyArrow wrappers; the last two read the footer rather
  than the data. `parquet.py`.
- `StagedParquetWriter` — incremental chunk staging: `write_batch`,
  `get_existing_ids` for intra-chunk resumption, `reset`, `commit`, and context
  management. `parquet.py`.
- `connect` — the single DuckDB connection factory. `duckdb.py`.
- `concat_to_parquet`, `find_duplicate_keys`, `find_null_keys`,
  `find_duplicate_nested_values` — out-of-core merge and the three
  merge-validation queries. `duckdb.py`.
- `sql_literal`, `sql_path_list`, `_qualified_identifier`,
  `build_part_unnest_query`, `build_profile_query`, `build_merged_targets_query`,
  `copy_query_to_parquet`, `suffix_sql` — the catalog SQL
  vocabulary. `duckdb_catalog.py`.
- `DOCUMENT_SNAPSHOT_SCHEMA`, `write_chunk_snapshot`,
  `validate_chunk_snapshot`, `assemble_document_snapshots`.
  `document_parquet.py`.
- `INDEX_COLUMNS`, `INDEX_SCHEMA`, `PAYLOAD_COLUMNS`, `PAYLOAD_SCHEMA`,
  `PlannedPart`, `PartError`, `plan_parts`, `quarter_path`, `write_index_part`,
  `write_payload_part`, `read_part`, `relation_for_parts`, `validate_part_paths`,
  `payload_doc_ids`. `document_parts.py`.
- `SnapshotPart`, `SnapshotReader`, `ManifestError`, `snapshot_identity`,
  `snapshot_dir`, `snapshots_dir`, `write_manifest`, `read_manifest`,
  `list_snapshots`, `publish_pointer`, `read_pointer`, `resolved_parts`,
  `dependents_of`, `expand_dependency_closure`, `now_iso`, `DATASET`, `PHASE`,
  `MANIFEST_NAME`, `PART_KIND_INDEX`, `PART_KIND_PAYLOAD`. `manifests.py`.
  `DATASET` is `"document_storage"` and `PHASE` is `"025_webpage_storage"` — both
  fixed constants used to stamp the pointer.
- `FixtureStore`, `FixtureStoreError`. `fixture_store.py`; stores compressed
  bytes using the established `fixture.sqlite` / `fixture_payloads` fixture
  contract (the file name is `foundation.runtime.paths.PAYLOAD_DB_NAME`),
  compressing through `foundation.compression`.
- `check_fixture_lineage`, `is_fixture_compatible`, `fixture_lineage_status`,
  `FixtureLineageError`. `fixture_lineage.py`.

**Command surface:** none. The consumer commands (`documents fill`, `documents
run`, `documents review-artifacts`, …) live in
`pipelines/document_storage/cli.py`, in Layer 4, not here.

## Tests

- `tests/infra/storage/test_atomic.py`
- `tests/infra/storage/test_document_parquet.py`
- `tests/infra/storage/test_duckdb.py` — `concat_to_parquet` sorting and row
  count, duplicate/null key detection both ways, and nested
  `filings.accession_number` fan-out detection.
- `tests/infra/storage/test_duckdb_catalog.py`
- `tests/infra/storage/test_fixture_lineage.py`
- `tests/infra/storage/test_fixture_store.py` — raw-table contract, immutable
  writes, read-only access, and the existing 10,000-row fixture when present.
- `tests/infra/storage/test_manifests.py` — snapshot immutability, pointer
  round-trip, part-path resolution, deterministic identity, and the dependency
  closure.
- `tests/infra/storage/test_parquet.py` — the format constants, the staging
  writer's atomicity, and a signature check that the DuckDB COPY path inherits the
  same row-group default.

`document_parts.py` is the one module with **no mirrored test file**, which
AGENTS.md §6 requires; it is exercised only indirectly through
`tests/pipelines/document_storage/test_vacuum.py` and `test_review.py`, so the
part-planning contract is pinned indirectly. `copy_query_to_parquet` has no
behavioural test either — `test_parquet.py` imports it only to read
`inspect.signature`.

## Deliberate gaps

- **No `DuckDBStaging` equivalent.** v1's `.v1/defs/storage/staging.py` defined
  `DuckDBStaging`: a *file-backed* `duckdb.connect(path)` append area with
  `register_function` UDFs, `create_table_as`, `insert_query`, `count`,
  `copy_table` (refusing to publish over an immutable artifact), `copy_query`, and
  a `close()` that unlinked the `.db`/`.wal`. **v2 carries no equivalent, and the
  one behaviour the two share is elsewhere.** `connect()` here is *in-memory*,
  and the shared behaviour — publishing a query result to Parquet — lives at
  `duckdb_catalog.copy_query_to_parquet`, not in a staging class. Staging, append,
  UDF registration, artifact-immutability refusal, and cleanup all have no v2
  home: `create_function` and `StorageError` are zero-hit in `edgar_sec/`, and
  callers needing bulk insert use `con.executemany()` on a raw connection.
- **No `defs/sql/` AST or compiler layer, and no `sql-boundary` scanner.** v1
  shipped 19 modules under `.v1/defs/sql/`. v2 emits SQL text directly and
  deliberately has no AST layer. The guard went with it, and
  `v2_refactor_roadmap.md` §9.6 records `sql-boundary` as **not** restored,
  because a new guard would need a new rule — "no concatenated string SQL" —
  rather than the old one. `ALL_SCANNERS` has twelve entries and no
  `sql-boundary`. The practical consequence for this package: `duckdb.py` and
  `document_parquet.py` build SQL with f-strings, and what keeps them safe is the
  escaping discipline documented above, not a gate. A future operator console
  reading user-supplied SQL would have no scanner standing in the way.
- **No JSONL backend.** v1's `.v1/defs/storage/jsonl/` (chunk, codec, kv, wal)
  has no counterpart. `concat_to_parquet`'s docstring says "Parquet or JSONL
  chunks", but the body reads only `read_parquet([...])`. The claim is stale.
- **No SQLite chunk backend, no `ATTACH`-batched merge, no partition DBs.** Those
  are Phase 2.5 scope; `v2_refactor_roadmap.md` §9.2 is where the boundary is
  drawn. The raw fixture store is a separate, narrow `fixture_store.py` contract
  and does not hold processing/chunk state.
- **No schema migration, versioning, or table registry.** The only versioning
  mechanism is the `schema_version` string inside a manifest (read back by
  `SnapshotReader.schema_version`) and `PROFILE_SCHEMA_VERSION` in
  `domain.filing_catalog.schemas`. Nothing migrates an old artifact.
- **No deletion or vacuum of Parquet parts here.** `manifests.py` computes
  `dependents_of` and `expand_dependency_closure` so a caller can decide what is
  safe to purge, but no function in this package deletes anything. The policy and
  the file removal both live in `pipelines/document_storage/vacuum.py`.
- **`list_snapshots` skips a damaged snapshot rather than failing.** A manifest
  that raises `OSError` or `json.JSONDecodeError` is logged at warning and left
  out of the listing, so consolidation can proceed on a partial view. The
  alternative would be that one bad directory stops everything.
- **`SnapshotReader.logical_fingerprint` falls back to the snapshot id** when
  `logical_fingerprint` is absent from the manifest. A reader that trusted it
  would compare an id against a fingerprint.
- **`read_pointer` returns `None` for a missing or corrupt pointer**, logging at
  warning; it never raises.
- **`copy_query_to_parquet` does not fsync the parent directory**, unlike every
  other writer in the package. The rename is atomic; the durability of the
  directory entry is not forced.
- **`fixture_lineage` has no consumer.** `check_fixture_lineage`,
  `is_fixture_compatible`, and `fixture_lineage_status` are called from nothing
  outside `tests/infra/storage/test_fixture_lineage.py`. The guard that stops a
  plan being replayed against a fixture built from a different plan is not yet
  wired into the offline fetch path.
- **There is no generic content-addressed payload store.** The former
  `payload_store.py` (`PayloadStore`, `PayloadStoreReader`, `PayloadRecord`, and
  the two `make_*` factories) was removed. It keyed `document_payloads` on
  `(document_locator_key, blob_hash)`, which kept every revision of a re-fetched
  document and needed a separate "newest revision wins" read path; `FixtureStore`
  keys `fixture_payloads` on `doc_id` alone and treats a recorded payload as
  evidence. Nothing ever opened the generic store — its only live exports were
  the two zstd helpers, which now live in `foundation/compression.py`, shared with
  the `sec_http` response cache and the dataset viewer. Phase 2.5 fixture fill and
  offline replay are the supported route.
- **`document_parts.__all__` re-exports two constants it does not define.**
  `PART_KIND_INDEX` and `PART_KIND_PAYLOAD` are imported from `manifests.py` and
  then listed in `__all__`. AGENTS.md §1.2 names `__init__.py` specifically, so
  this does not break the letter of the rule, but it is the only re-export in the
  layer and those constants are owned by `manifests.py`.
- **The `document_parts` module docstring overstates its own compression story.**
  It claims "PyArrow and zstandard are confined here, next with
  `document_parquet.py`", but the module imports only `pyarrow` and
  `pyarrow.parquet`. Parts are Parquet files using the `zstd` *codec*; the
  `zstandard` *library* is not used for a codec anywhere in this package.
- **Parts are planned per quarter, not per snapshot.** `quarter_path` builds
  `parts/<kind>/<year>-<quarter>.parquet` from exactly one year and quarter, so a
  snapshot spanning several fiscal quarters needs one `plan_parts` call per
  quarter. Nothing validates that a caller passes a coherent `(year, quarter)`
  pair.
- **The `resource-allocation` scanner does not see through indirection.** It is a
  line-level regex that skips comment and docstring lines, so a limit hidden
  behind a variable or a settings lookup is not flagged. The `connect()` contract
  holds by having exactly one `duckdb.connect()` call site, not because the
  scanner proves it.