# `edgar_sec/infra/storage` — every byte that outlives the process, and every DuckDB connection

This package is the persistence layer: atomic publication to disk, the Parquet
and SQLite formats, the DuckDB connection factory that keeps a large merge
inside the machine's memory budget, the filing-catalog SQL, and the Phase 2.5
document-snapshot machinery.

## Purpose

Two concerns, one package. First, **safe publication**: a reader must never
observe a half-written artifact, so every write here stages to a temp file and
renames. Second, **bounded resources**: a merge that exceeds memory is an
OOM kill, so every DuckDB connection is configured from a machine probe rather
than from a default.

It is not a processing database and not an ORM. There is no schema migration
system, no table registry, and no query builder beyond the handful of functions
in `duckdb_catalog.py` that exist because a specific pipeline needs them.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `atomic.py` | `atomic_write_bytes` / `_text` / `_json` plus `_fsync_dir`, the tmp-then-rename discipline the rest of the layer copies (69 loc). |
| `parquet.py` | `StagedParquetWriter` (incremental chunk staging and resumption), format constants, and `pyarrow` read/write wrappers. |
| `duckdb.py` | `connect()` — the only `duckdb.connect()` call in the package — plus out-of-core merge and merge-validation queries (184 loc). |
| `duckdb_catalog.py` | Filing-catalog SQL builders and the atomic query-to-Parquet COPY (315 loc). |
| `document_parquet.py` | Phase 2.5 chunk snapshot write / validate / assemble (211 loc). |
| `document_parts.py` | Byte-budgeted part planning and the index/payload column contracts (252 loc). |
| `manifests.py` | Snapshot identity, immutable manifest publication, and the `current` pointer (321 loc). |
| `payload_store.py` | Generic content-addressed `document_payloads` runtime store and fail-open reader (347 loc); not the fixture format. |
| `fixture_store.py` | Append-only `fixture_payloads(doc_id, raw_payload)` SQLite store used by offline replay and fixture fill. |
| `fixture_lineage.py` | Pure comparison of a fixture manifest against a plan (96 loc). |
| `__init__.py` | Docstring only (1 loc). No re-exports. |

## Contracts

**Guarantees this package makes to its callers**

- **Every DuckDB connection is bounded by the machine, and there is exactly one
  place a connection is made.** `duckdb.connect()` appears once in the entire
  `edgar_sec` package: `duckdb.py:55`, inside `connect()`
  (`grep -rn "duckdb.connect" edgar_sec/` returns that single line). `connect()`
  unconditionally sets all four values AGENTS.md §2.3 requires —
  `threads` (clamped to `max(1, int(...))`), `memory_limit`,
  `temp_directory`, and `preserve_insertion_order = false`
  (`duckdb.py:56-59`). With no `profile` argument it calls
  `foundation.runtime.resources.derive_resources()` itself, at call time rather
  than import time (`duckdb.py:39-42`), so the cgroup probe happens when a
  connection is opened and not when the module is loaded. `derive_resources`
  resolves `threads`, `workers`, `memory_limit`, `temp_directory`,
  `worker_memory_mib`, and `worker_memory_safety` through the settings registry,
  and `available_memory_bytes()` behind them walks cgroups v2, cgroups v1,
  psutil `.available`, then `/proc/meminfo` `MemAvailable` — never `MemTotal`,
  never a raw CPU count as a memory signal
  (`foundation/runtime/resources.py:55-116`). Worker counts come from
  `auto_worker_count(available, worker_memory_mib=512, safety_fraction=0.9)`
  (`resources.py:158-176`).
  The `resource-allocation` scanner
  (`foundation/scanners/resources.py:16-19`) fails the build on any
  `threads=` / `max_workers=` / `memory_limit=` literal outside
  `runtime/resources.py`, `runtime/settings/`, `foundation/scanners/`, and
  tests, which is why `connect()`'s parameters are all `None`-defaulted rather
  than literal-valued.
- **Every write is atomic, and the tmp-file name is pid-scoped.**
  `atomic_write_bytes` writes `<path>.tmp.<pid>`, `fsync`s the file, `os.replace`s
  onto the target, `fsync`s the parent directory, and removes the temp file in a
  `finally` (`atomic.py:25-44`). The same pattern is repeated in
  `parquet.write_parquet_table` (`parquet.py:24-43`), `duckdb.concat_to_parquet`
  (`duckdb.py:83-107`), `document_parquet.write_chunk_snapshot`
  (`document_parquet.py:122-138`), `document_parts._write_part`
  (`document_parts.py:162-183`), and, with a dot-prefixed temp name,
  `duckdb_catalog.copy_query_to_parquet` (`duckdb_catalog.py:251-263`).
  `duckdb_catalog.copy_query_to_parquet` is the one writer that does not fsync
  the parent directory; it does `os.replace`, which is atomic, but does not force
  the rename to disk.
- **Parquet format constants live in one place.** `DEFAULT_ROW_GROUP_SIZE =
  128_000` and `DEFAULT_COMPRESSION = "zstd"` (`parquet.py:12-13`) are the
  values AGENTS.md §2.5 names. `duckdb.concat_to_parquet` and
  `duckdb_catalog.copy_query_to_parquet` both import them as defaults rather
  than re-declaring literals, and `document_parquet` and `document_parts` pass
  them straight to `pq.write_table`.
- **JSON goes out through `atomic_write_json`, canonically by default.**
  `atomic_write_json(path, obj, canonical=True, indent=None)` serializes with
  `foundation.serialization.canonical_json` — sorted keys, compact separators,
  `ensure_ascii=True` — and only falls back to `json.dumps` when a caller passes
  `canonical=False`, which exists for human-readable files such as `plan.json`
  (`pipelines/metadata_sync/planner.py:114`). The `json-io` scanner
  (`foundation/scanners/json_io.py`) enforces both halves: it flags any
  redefinition of `canonical_json` / `_canonical_json` / `json_canonical` /
  `_load_json`, and it flags `json.dump(x, fh)` or
  `path.write_text(json.dumps(...))` — the shapes that leave a truncated file
  when a process dies. Its only exemptions are the two modules that own the
  primitives, `foundation/serialization.py` and `infra/storage/atomic.py`
  (`json_io.py:28-31`).
- **Merges stay out of core.** `concat_to_parquet` runs
  `COPY (SELECT * FROM read_parquet([...]) ORDER BY ...) TO ...` inside DuckDB
  (`duckdb.py:88-93`), so the result is sorted and written by the engine rather
  than materialized in the Python heap, and it returns the resulting row count
  by re-reading the footer. `copy_query_to_parquet` is the same idea for an
  arbitrary query and returns `count_parquet_rows(path)`.
- **Merge validation is expressed as three narrow queries**, not a general
  validator: `find_duplicate_keys` (primary-key duplicates across chunks,
  `duckdb.py:110-128`), `find_null_keys` (null count, `duckdb.py:131-148`), and
  `find_duplicate_nested_values` (duplicates inside a struct-list column such as
  `filings.accession_number`, via `unnest`, `duckdb.py:151-175`). The first two
  return `LIMIT 100`; the third does the same.
- **SQL is built with escaping at every interpolation point.**
  `duckdb_catalog` has two primitives: `sql_literal` doubles embedded single
  quotes (`duckdb_catalog.py:44-52`), and `_qualified_identifier` rejects any
  dotted name whose segments do not all match `^[A-Za-z_][A-Za-z0-9_]*$`
  (`duckdb_catalog.py:55-68`). `suffix_sql` and `build_profile_query` route
  every caller-supplied name through the second; `build_part_unnest_query` takes
  a single path parameter and emits it as a literal
  (`duckdb_catalog.py:71-77`). `document_parts.relation_for_parts` does the same
  for a part list, and `validate_part_paths` is the boundary check that runs
  first: it rejects an empty path, a `..` segment or an absolute path, a path
  containing `'`, `"`, or `;`, and a recorded file that does not exist
  (`document_parts.py:211-227`). The reasoning is stated in the docstring: a
  recorded path is interpolated into SQL, and a manifest is a file on disk that
  anyone can edit, so the check belongs at the boundary.
- **Document identity is one function, reused.** `duckdb_catalog.build_part_unnest_query`
  mints `document_locator_key` as `sha256(accession || ':' || document_path)` and
  `occurrence_id` as `sha256(source_cik || ':' || accession || ':' || document_path)`
  in SQL (`duckdb_catalog.py:153-155`), and
  `document_parquet.write_chunk_snapshot` derives the same key in Python via
  `domain.document.models.derive_document_locator_key`
  (`document_parquet.py:77`). The two forms agree, and a document is identified
  the same way whether it was fanned out from a Phase 1 part or written by a
  Phase 2.5 worker. Consumers: `pipelines/document_storage/worker.py`,
  `delegation.py`, `merger.py`; `pipelines/filing_catalog/catalog_job.py`.
- **A snapshot is immutable once published.** `write_manifest` refuses to write
  under a `snapshot_id` whose `manifest.json` already exists
  (`manifests.py:136-142`), because a published id is referenced from other
  records and overwriting it would retroactively change what those references
  mean.
- **The pointer is written after the manifest, never before.**
  `write_manifest` writes the manifest and only then calls `publish_pointer`
  (`manifests.py:144-146`); a crash between the two leaves a stale pointer to a
  snapshot that does exist, which is strictly better than a pointer to one that
  does not. `publish_pointer` writes `<root>/current/pointer.json` with
  `atomic_write_text(..., canonical_json(payload))`
  (`manifests.py:180-193`), and the path comes from the shared
  `foundation.runtime.paths.current_pointer_path` (`manifests.py:33`), so every
  dataset resolves "current" identically.
- **Snapshot ids are deterministic.**
  `snapshot_identity(operation, source_snapshot_ids, artifact_hashes, schema_version)`
  is `f"{operation}-{sha256_text(canonical_json(payload))[:16]}"` over
  *sorted* inputs (`manifests.py:90-109`), so consolidating the same sources
  twice yields the same id and a repeated consolidation is recognizably a no-op
  rather than a second near-identical snapshot.
- **A snapshot is a set of parts, planned by byte size, with snapshot-relative
  paths.** `plan_parts` fills a part until the next document would exceed
  `target_bytes`, and requires `doc_ids` to be sorted because the plan is
  derived from a contiguous document range a reader streams one part at a time
  (`document_parts.py:92-123`). The rationale is in the module docstring:
  normalized document text is wildly uneven, so counting rows would produce
  parts differing by three orders of magnitude in bytes. A part's recorded path
  is `parts/<kind>/<year>-<quarter>.parquet`, relative to its *own snapshot
  directory* (`quarter_path`, `document_parts.py:81-89`) — deliberately not to
  the snapshots root, so a manifest cannot name a part belonging to a different
  snapshot.
- **Index and payload are separate projections of one logical record.**
  `INDEX_COLUMNS` is 11 string columns —
  `occurrence_id`, `source_cik`, `accession`, `form`, `filing_date`,
  `report_date`, `document_path`, `doc_id`, `mime_type`, `byte_size`,
  `payload_file` (`document_parts.py:44-56`) — so a consumer can read metadata
  without the text. `PAYLOAD_COLUMNS` is `("doc_id", "clean_text")`
  (`document_parts.py:61`). `filing_year` and `filing_quarter` are deliberately
  *not* stored: they are derived at consolidation time, so an older snapshot
  consolidates alongside a newer one with no migration
  (`document_parts.py:57-60`). `write_index_part` returns a `SnapshotPart` whose
  `row_count` and `byte_size` are read back off the finished file
  (`document_parts.py:177-183`).
- **Parts are Parquet with the `zstd` codec, not zstandard BLOBs.**
  `_write_part` calls `pq.write_table(table, tmp, compression=DEFAULT_COMPRESSION,
  row_group_size=DEFAULT_ROW_GROUP_SIZE)` (`document_parts.py:167-172`). The
  `zstandard` *library* appears in exactly two modules in this layer:
  `payload_store.py` and, in the sibling `sec_http/cache.py`, both compressing
  BLOBs inside SQLite.
- **The raw-payload store is content-addressed and append-only in practice.**
  The `document_payloads` table is keyed `(document_locator_key, blob_hash)`
  (`payload_store.py:35-47`), so `put` uses `INSERT OR IGNORE` and returns
  `False` when identical bytes already exist (`payload_store.py:119-154`). Rows
  are identified twice over — by what was fetched and by what it contained — so
  a caller can assert it got the bytes it expected and two runs that fetched the
  same document agree without a round trip. Payloads are zstd-compressed on
  write and decompressed on read via thread-local codec objects
  (`payload_store.py:29,59-82`), and the SQLite connection runs WAL with
  `busy_timeout=5000` and `synchronous=NORMAL` (`payload_store.py:109-111`).
  `PayloadStoreReader` is the deliberately fail-open twin: `available` reports
  whether a store was found, and every read returns `None` rather than raising,
  so a missing or corrupt fixture degrades a status command instead of failing a
  run (`payload_store.py:260-325`).
- **Fixture lineage validation is pure and asymmetric.**
  `check_fixture_lineage` compares three identity axes —
  `catalog_id`, `policy_corpus`, `seed_fingerprint` — plus a case-insensitive
  form set, and raises `FixtureLineageError` only when *both* sides declare a
  value and they differ (`fixture_lineage.py:44-66`). The asymmetry is the point
  and is stated in the docstring: a missing field means "unknown", not
  "mismatched", so fixtures recorded before lineage was tracked are not stranded.
  `fixture_lineage_status` returns `"unknown"`, `"partial"`, or `"recorded"`
  (`fixture_lineage.py:78-88`).
- **A chunk snapshot is validated against a fixed schema.**
  `validate_chunk_snapshot` compares the file's schema names to
  `DOCUMENT_SNAPSHOT_SCHEMA.names` for exact order and equality, raising
  `ValueError` on any mismatch, and returns `path`, `num_rows`,
  `num_row_groups`, and `serialized_size_bytes` from the footer
  (`document_parquet.py:142-163`). `DOCUMENT_SNAPSHOT_SCHEMA` is 13 columns:
  `occurrence_id`, `source_cik`, `accession`, `document_path`,
  `document_locator_key`, `blob_hash`, `form`, `filing_date`, `raw_payload`
  (binary), `byte_size` (int64), `normalized_text`, `status`, `error_message`
  (`document_parquet.py:23-43`). `form` and `filing_date` are carried from the
  occurrence rather than derived, because a stored document without them cannot
  be repartitioned into fiscal quarters later
  (`document_parquet.py:32-35`).
- **Assembly is out-of-core, sorted, and counted.**
  `assemble_document_snapshots` opens a bounded connection, runs
  `COPY (SELECT * FROM read_parquet([...]) ORDER BY source_cik, accession) TO ...`
  with the standard row-group size and compression, renames into place, fsyncs
  the directory, and returns the row count read back from the output
  (`document_parquet.py:166-203`). It ignores chunk paths that are not files and
  raises `ValueError` when nothing valid remains.
- **A purge is gated on part sharing.** `dependents_of` maps each source snapshot
  to the snapshots whose recorded part paths intersect its own
  (`manifests.py:217-241`), and `expand_dependency_closure` grows a selection
  until nothing retained still shares a part with anything in it
  (`manifests.py:244-260`). Two snapshots sharing a part are physically
  entangled, so the dependent must be consolidated first.
- **Environment access is nil.** No module in this package reads
  `os.environ` or calls `os.getenv`; path roots are passed in as arguments. This
  is what `environment-access` enforces, and manifests and plans are persisted
  artifacts that must not carry machine-specific overrides
  (`manifests.py:19-20`).

**Obligations callers place on this package**

- Obtain DuckDB connections from `connect()` and pass a shared
  `RuntimeResourceProfile` (or `None`) rather than per-call numbers, so one
  profile governs a whole run.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes; a
  per-call literal reintroduces the inconsistency they exist to remove.
- Pass a **sorted** `doc_sizes` sequence to `plan_parts`, and treat the returned
  `PlannedPart.doc_ids` ranges as contiguous.
- Run `validate_part_paths` before `relation_for_parts` on any part list read
  from a manifest. The two docstrings say so explicitly
  (`document_parts.py:196-200`).
- Supply a writable parent for every write; each function `mkdir(parents=True,
  exist_ok=True)` before staging, so the caller does not have to — but the caller
  chooses where.
- Close `SqlCache` / `PayloadStore` connections; nothing here registers an
  `atexit` hook.
- For `write_chunk_snapshot`, supply `normalized_texts` and `statuses` keyed by
  `occurrence_id`; a missing status defaults to `"ok"` and a missing text to
  `""` (`document_parquet.py:98-102`), and a `raw_blobs` miss writes an empty
  payload and `byte_size = 0` rather than failing
  (`document_parquet.py:82-91`).

## Public surface

- `atomic_write_bytes`, `atomic_write_text`, `atomic_write_json` — the three
  atomic writers; each returns the number of bytes written. `atomic.py`.
  `atomic_write_json` takes `canonical: bool = True` and `indent: int | None = None`.
- `_fsync_dir` — the shared parent-directory fsync, private by naming but
  imported by `parquet.py`, `duckdb.py`, `document_parquet.py`, and
  `document_parts.py`. `atomic.py:12`.
- `DEFAULT_ROW_GROUP_SIZE`, `DEFAULT_COMPRESSION` — the Parquet format
  vocabulary. `parquet.py`.
- `write_parquet_table`, `read_parquet_table`, `read_parquet_schema`,
  `count_parquet_rows` — PyArrow wrappers; the last two read the footer rather
  than the data. `parquet.py`.
- `connect` — the single DuckDB connection factory. `duckdb.py`.
- `concat_to_parquet`, `find_duplicate_keys`, `find_null_keys`,
  `find_duplicate_nested_values` — out-of-core merge and the three
  merge-validation queries. `duckdb.py`.
- `sql_literal`, `_qualified_identifier`, `build_part_unnest_query`,
  `build_profile_query`, `build_merged_targets_query`, `copy_query_to_parquet`,
  `suffix_sql`, `amendment_sql` — the catalog SQL vocabulary.
  `duckdb_catalog.py`. `amendment_sql` validates against
  `domain.filing_catalog.filters.AMENDMENT_POLICIES` and reads the catalog's own
  `is_amendment` column rather than recomputing the suffix rule, so the two can
  never drift (`duckdb_catalog.py:288-304`).
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
  `DATASET` is `"document_storage"` and `PHASE` is `"025_webpage_storage"`
  (`manifests.py:39-40`) — both fixed constants used to stamp the pointer.
- `PayloadStore`, `PayloadStoreReader`, `PayloadRecord`, `PayloadStoreError`,
  `make_payload_store`, `make_payload_store_reader`, `compress_payload`,
  `decompress_payload`. `payload_store.py`.
- `FixtureStore`, `FixtureStoreError`. `fixture_store.py`; stores compressed bytes
  using the established `fixture.sqlite` / `fixture_payloads` fixture contract.
- `check_fixture_lineage`, `is_fixture_compatible`, `fixture_lineage_status`,
  `FixtureLineageError`. `fixture_lineage.py`.

## Tests

- `tests/infra/storage/test_atomic.py` (34 loc)
- `tests/infra/storage/test_document_parquet.py` (104 loc)
- `tests/infra/storage/test_duckdb.py` (106 loc) — `concat_to_parquet` sorting
  and row count, duplicate/null key detection both ways, and nested
  `filings.accession_number` fan-out detection.
- `tests/infra/storage/test_duckdb_catalog.py` (116 loc)
- `tests/infra/storage/test_fixture_lineage.py` (91 loc)
- `tests/infra/storage/test_fixture_store.py` — raw-table contract, immutable
  writes, read-only access, and the existing 10,000-row fixture when present.
- `tests/infra/storage/test_parquet.py` (65 loc)
- `tests/infra/storage/test_payload_store.py` (223 loc)

Two modules have **no mirrored test file**, which AGENTS.md §6 requires:
`document_parts.py` and `manifests.py`. They are exercised only through
`tests/pipelines/document_storage/test_vacuum.py` and `test_review.py`, so the
snapshot-identity and part-planning contracts are pinned indirectly.
`copy_query_to_parquet` has no behavioural test either; `test_parquet.py:62-64`
imports it only to read `inspect.signature`.

## Deliberate gaps

- **No `DuckDBStaging` equivalent.** v1's `.v1/defs/storage/staging.py` (196
  loc) defined `DuckDBStaging`: a *file-backed* `duckdb.connect(path)` append
  area with `register_function` UDFs, `create_table_as`, `insert_query`,
  `count`, `copy_table` (refusing to publish over an immutable artifact),
  `copy_query`, and a `close()` that unlinked the `.db`/`.wal` and optionally
  rmtree'd a cleanup root, with failures wrapped in a `StorageError`. **v2
  carries no equivalent, and the one behaviour the two share is elsewhere.**
  `connect()` here is *in-memory* (`duckdb.connect()` with no path), and the
  shared behaviour — publishing a query result to Parquet — lives at
  `duckdb_catalog.copy_query_to_parquet:236`, not in a staging class. So
  staging, append, UDF registration, artifact-immutability refusal, and cleanup
  all have no v2 home: `create_function` and `StorageError` are zero-hit in
  `edgar_sec/`, and callers that need bulk insert use `con.executemany()` on a
  raw connection.
- **No `defs/sql/` AST or compiler layer, and no `sql-boundary` scanner.** v1
  shipped 19 modules under `.v1/defs/sql/` — a typed statement, predicate,
  relation, expression, schema, and dialect model plus a string `compiler/`.
  v2 emits SQL text directly (`duckdb_catalog.py` is the replacement) and
  deliberately has no AST layer. The guard went with it: v1 registered a
  `sql-boundary` scanner (defined at `.v1/defs/sql/checks.py:65`, registered at
  `.v1/defs/runtime/checks.py:122`), and
  `roadmap/refactor_v2/v2_refactor_roadmap.md` §9.6 records that it was **not**
  restored, because a new guard would need a new rule — "no concatenated string
  SQL" — rather than the old one. `ALL_SCANNERS`
  (`foundation/scanners/__init__.py:18-30`) has eleven entries and no
  `sql-boundary`. The practical consequence for this package: `duckdb.py` and
  `document_parquet.py` build SQL with f-strings, and what keeps them safe is
  the escaping discipline documented above, not a gate. A future operator
  console that read user-supplied SQL would have no scanner standing in the way.
- **No JSONL backend.** v1's `.v1/defs/storage/jsonl/` (chunk, codec, kv, wal —
  564 loc) has no counterpart. `concat_to_parquet`'s docstring says "Parquet or
  JSONL chunks", but the body reads only `read_parquet([...])`
  (`duckdb.py:78`). The claim is stale.
- **No SQLite chunk backend, no `ATTACH`-batched merge, no partition DBs.** Those
  are Phase 2.5 scope, not present work; `v2_refactor_roadmap.md` §9.2 is where
  the boundary is drawn. The raw fixture store is a separate, narrow
  `fixture_store.py` contract and does not hold processing/chunk state.
- **No schema migration, versioning, or table registry.** The only versioning
  mechanism is the `schema_version` string inside a manifest
  (`manifests.py`, read back by `SnapshotReader.schema_version`) and
  `PROFILE_SCHEMA_VERSION` in `domain.filing_catalog.schemas`. Nothing migrates
  an old artifact.
- **No deletion or vacuum of Parquet parts here.** `manifests.py` computes
  `dependents_of` and `expand_dependency_closure` so a caller can decide what is
  safe to purge, but no function in this package deletes anything. The policy and
  the file removal both live in
  `pipelines/document_storage/vacuum.py`.
- **`list_snapshots` skips a damaged snapshot rather than failing.** A manifest
  that raises `OSError` or `json.JSONDecodeError` is logged at warning and left
  out of the listing (`manifests.py:158-177`). Consolidation can therefore proceed
  on a partial view; the alternative would be that one bad directory stops
  everything.
- **`SnapshotReader.logical_fingerprint` falls back to the snapshot id** when
  `logical_fingerprint` is absent from the manifest (`manifests.py:289-293`). A
  reader that trusted it would compare an id against a fingerprint.
- **`read_pointer` returns `None` for a missing or corrupt pointer**, logging at
  warning (`manifests.py:196-205`); it never raises.
- **`copy_query_to_parquet` does not fsync the parent directory**, unlike every
  other writer in the package. The rename is atomic; the durability of the
  directory entry is not forced.
- **`fixture_lineage` has no consumer.** `check_fixture_lineage`,
  `is_fixture_compatible`, and `fixture_lineage_status` are called from nothing
  outside `tests/infra/storage/test_fixture_lineage.py`. The guard that stops a
  plan being replayed against a fixture built from a different plan is not yet
  wired into the offline fetch path.
- **`PayloadStore` is not the fixture schema.** It remains a generic
  content-addressed store with `document_payloads`; Phase 2.5 fixture replay and
  fill use `FixtureStore` and its `fixture_payloads` table. The generic payload
  store is not opened by `FixtureArchiveFetcher`.
- **`document_parts.__all__` re-exports two constants it does not define.**
  `PART_KIND_INDEX` and `PART_KIND_PAYLOAD` are imported from `manifests.py`
  (`document_parts.py:32-36`) and then listed in `__all__`
  (`document_parts.py:242-243`). AGENTS.md §1.2 names `__init__.py`
  specifically, so this does not break the letter of the rule, but it is the
  only re-export in the layer and those constants are owned by `manifests.py`.
- **The `document_parts` module docstring overstates its own compression story.**
  It claims "PyArrow and zstandard are confined here, next with
  `document_parquet.py`", but the module imports only `pyarrow` and
  `pyarrow.parquet`. Parts are Parquet files using the `zstd` *codec*; the
  `zstandard` *library* is used only in `payload_store.py` in this package.
- **Parts are planned per quarter, not per snapshot.**
  `quarter_path` builds `parts/<kind>/<year>-<quarter>.parquet` from exactly one
  year and quarter, so a snapshot spanning several fiscal quarters would need one
  `plan_parts` call per quarter. Nothing in this module validates that a caller
  passes a coherent `(year, quarter)` pair.
- **The `resource-allocation` scanner does not see through indirection.** It is a
  line-level regex (`foundation/scanners/resources.py:16-19`) that skips comment
  and docstring lines, so a limit hidden behind a variable or a settings lookup
  is not flagged. The `connect()` contract holds by having exactly one
  `duckdb.connect()` call site, not because the scanner proves it.
