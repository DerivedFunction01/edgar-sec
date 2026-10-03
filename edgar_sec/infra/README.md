# `edgar_sec/infra` — Layer 2: external systems, protocols, and persistence

This layer owns everything that touches the world outside the process: the SEC
HTTP protocol, the same-host acquisition broker, and every byte of durable
state on disk or in SQLite. It is not a place for business rules, and it holds
no knowledge of which phase is running or why an artifact is being written.

## Purpose

Three subpackages, each a complete vertical over one external system:

- `sec_http/` — the shared client for `data.sec.gov` and `www.sec.gov`: pacing,
  retry classification, a compressed on-disk response cache, metrics, and a
  failure ledger that remembers a URL that already failed.
- `broker/` — a Unix-domain-socket server so an arbitrary number of worker
  *processes* share exactly one `SecHttpClient`, and therefore one aggregate
  request pace, instead of each process pacing itself.
- `storage/` — atomic filesystem publication, Parquet and DuckDB I/O, the
  filing-catalog SQL builders, and the Phase 2.5 document-snapshot machinery
  (parts, manifests, the raw-payload fixture store, chunk checkpoints).

The unifying rule is that a resource budget, a serialization format, or a
protocol detail is decided **once, here**, from a machine probe or a settings
lookup, and every layer above consumes the decision rather than re-making it.

## Layer map

Layer 2 sits between `domain` (Layer 1) and `engine` (Layer 3).

```text
Layer 4  pipelines/            CLI, Operator, Planner, Worker, Merger
             |  may import infra, engine, domain, foundation
Layer 3  engine/               Unroller, Profile, Normalizer, Arrow Builder
             |  may import infra, domain, foundation
Layer 2  infra/                <-- this package
             |  may import domain, foundation ONLY
Layer 1  domain/               Cik, AccessionNumber, filing-catalog schemas
             |  may import foundation
Layer 0  foundation/           hashing, serialization, runtime, scanners
```

**Layer 2 may import only from `edgar_sec.domain` and `edgar_sec.foundation` —
never from `engine` or `pipelines`.** This is not a convention; it is checked on
every `check.py` run by the `layer-boundary` scanner
(`foundation/scanners/layers.py`), which parses each module's AST and reports
any import whose callee layer ranks strictly above the caller's. Infra's rank is
2 in `_LAYER_RANK` (`layers.py:11-17`), so an `infra` → `engine` or
`infra` → `pipelines` import fails the gate.

Same-layer imports are unrestricted, which is why `storage/document_parquet.py`
may call `storage.duckdb.connect()` and `broker/sec_broker.py` may own a
`SecHttpClient`. Intra-package cycles are not detected: the scanner compares
layer ranks only, so two `infra` modules importing each other would pass.

Verified compliance as the tree stands. Every `edgar_sec.*` import in the
package crosses downward only to `foundation` or `domain`, or stays inside
`infra` itself:

| Imported package | Modules that import it |
| :--- | :--- |
| `edgar_sec.foundation` | `sec_http/cache.py`, `sec_http/client.py`, `sec_http/rate_limit.py`, `sec_http/retry.py`, `broker/sec_broker.py`, `storage/atomic.py`, `storage/manifests.py`, `storage/document_parquet.py`, `storage/fixture_store.py`, `storage/duckdb.py` |
| `edgar_sec.domain` | `storage/document_parquet.py` (`domain.document.models`), `storage/duckdb_catalog.py` (`domain.filing_catalog.filters`, `domain.filing_catalog.schemas`) |
| same-layer `edgar_sec.infra` | `broker/daemon.py`, `broker/sec_broker.py`, `sec_http/client.py`, `storage/document_parquet.py`, `storage/document_parts.py`, `storage/duckdb_catalog.py` |

`sec_http/errors.py`, `sec_http/metrics.py`, `storage/parquet.py`, and
`storage/fixture_lineage.py` import nothing from
`edgar_sec` at all.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (1 loc). No re-exports, per AGENTS.md §1.2. |
| `broker/__init__.py` | Docstring only (1 loc). |
| `broker/sec_broker.py` | The socket server and its worker-side client; owns one `SecHttpClient` for the whole host (361 loc). |
| `broker/daemon.py` | `managed_broker()`: start a live broker, health-check it, tear it down (61 loc). |
| `sec_http/__init__.py` | Docstring only (1 loc). |
| `sec_http/client.py` | `SecHttpClient`, the one place an HTTP request to SEC is issued (382 loc). |
| `sec_http/rate_limit.py` | `RateLimiter`: request-slot reservation, throttle backoff, quiet-period recovery (103 loc). |
| `sec_http/retry.py` | `RetryPolicy`: status classification and jittered exponential backoff (56 loc). |
| `sec_http/cache.py` | `SqlCache`: zstd-compressed response cache in SQLite plus the failure ledger (237 loc). |
| `sec_http/metrics.py` | `HttpMetrics`: lock-guarded request/response counters (74 loc). |
| `sec_http/errors.py` | The three transport exceptions callers branch on (36 loc). |
| `storage/__init__.py` | Docstring only (1 loc). |
| `storage/atomic.py` | `atomic_write_bytes` / `_text` / `_json` and the shared `_fsync_dir` (69 loc). |
| `storage/parquet.py` | The Parquet format constants and thin `pyarrow` read/write wrappers (72 loc). |
| `storage/duckdb.py` | `connect()` — the single DuckDB connection factory — plus out-of-core merge and merge-validation queries (184 loc). |
| `storage/duckdb_catalog.py` | Filing-catalog SQL builders and the atomic query-to-Parquet COPY (315 loc). |
| `storage/document_parquet.py` | Phase 2.5 chunk snapshot write / validate / assemble (211 loc). |
| `storage/document_parts.py` | Byte-budgeted part planning and the index/payload column contracts (252 loc). |
| `storage/manifests.py` | Snapshot identity, manifest publication, and the `current` pointer (321 loc). |
| `storage/fixture_store.py` | Append-only `fixture_payloads(doc_id, raw_payload)` SQLite store behind fixture fill and offline replay. |
| `storage/fixture_lineage.py` | Pure lineage comparison between a fixture manifest and a plan (96 loc). |

Total 3,373 lines across 21 files: 17 modules plus four one-line `__init__.py`
docstrings.

## Contracts

**Guarantees this layer makes to its callers**

- **Every DuckDB connection is resource-bounded, without exception.**
  `duckdb.connect()` appears exactly once in the entire package —
  `storage/duckdb.py:55`, inside `connect()`. Every caller in the repository
  obtains its connection from that function: `pipelines/filing_catalog/catalog_job.py:216,244`,
  `pipelines/filing_catalog/planner.py:208,448`, `engine/selection/features.py:646`,
  `pipelines/metadata_sync/merger.py:187`, and
  `storage/document_parquet.py:179`. `connect()` sets all four mandated values
  from `foundation.runtime.resources.derive_resources()` (called lazily at
  `duckdb.py:39-42` so importing the module does not probe the machine):
  `threads` (clamped to at least 1), `memory_limit`, `temp_directory` (created
  with `mkdir(parents=True, exist_ok=True)`), and `preserve_insertion_order = false`
  (`duckdb.py:56-59`). This is AGENTS.md §2.3, and it holds by construction
  rather than by review.
- **No hardcoded resource limits.** The `resource-allocation` scanner
  (`foundation/scanners/resources.py`) flags any `threads=`/`max_workers=`/
  `memory_limit=` literal outside `runtime/resources.py`, `runtime/settings/`,
  `foundation/scanners/`, and tests. `connect()` takes `threads: int | None = None`
  and `memory_limit: str | None = None` for that reason: the parameters exist, but
  the default is "ask the machine", and an override must be a variable.
- **Worker counts are cgroup-aware, never CPU-count-only.** Infra does not size
  workers itself; it takes the budget from
  `foundation.runtime.resources.RuntimeResourceProfile`, whose `workers` field is
  resolved by `derive_resources()` through the settings registry. The underlying
  probe ladder in `resources.py` is cgroups v2 (`read_cgroup_v2_available_bytes`),
  cgroups v1 (`read_cgroup_v1_available_bytes`), psutil `.available`, then
  `/proc/meminfo` `MemAvailable` (`available_memory_bytes`), with
  `auto_worker_count(available, worker_memory_mib=512, safety_fraction=0.9)` as the
  budget function and `default_cpu_cores()` as an upper bound, never a floor.
- **Every published file lands atomically.** All three atomic writers
  (`storage/atomic.py`) write to `<path>.tmp.<pid>`, `fsync` the file, `os.replace`
  onto the target, then `fsync` the parent directory, and unlink the temp file in
  a `finally`. The same tmp-then-replace discipline is repeated by every Parquet
  writer in the layer — `parquet.write_parquet_table`, `duckdb.concat_to_parquet`,
  `duckdb_catalog.copy_query_to_parquet`, `document_parquet.write_chunk_snapshot`,
  and `document_parts._write_part` — so a crashed run never leaves a
  half-written artifact in a published directory.
- **Parquet format is decided once.** `storage/parquet.py:12-13` defines
  `DEFAULT_ROW_GROUP_SIZE = 128_000` and `DEFAULT_COMPRESSION = "zstd"`. Every
  Parquet write in the layer uses those two constants rather than a literal;
  they are the values AGENTS.md §2.5 names.
- **JSON is written through the shared primitives.** `atomic_write_json`
  (`storage/atomic.py:54`) serializes with `foundation.serialization.canonical_json`
  by default — sorted keys, compact separators, `ensure_ascii=True` — and falls
  back to `json.dumps` only when a caller explicitly passes `canonical=False`
  for a human-readable file. The `json-io` scanner
  (`foundation/scanners/json_io.py`) enforces both halves: it flags a
  redefinition of `canonical_json`/`_canonical_json`/`json_canonical`/`_load_json`,
  and it flags `json.dump(x, fh)` or `path.write_text(json.dumps(...))`. The only
  two exempt files are the two that own the primitives,
  `foundation/serialization.py` and `infra/storage/atomic.py`
  (`json_io.py:28-31`).
- **Settings are read through the registry, never `os.environ`.** Every constant
  `sec_http` imports comes from `foundation.runtime.settings.sec` or
  `...settings.paths`. No module in this layer touches the environment directly,
  which is what keeps `environment-access` clean.
- **No barrel re-exports.** Every `__init__.py` in the layer is a single
  docstring line. Consumers import from the leaf module —
  `from edgar_sec.infra.storage.duckdb import connect`, not
  `from edgar_sec.infra.storage import duckdb`-style aggregation. Importing
  `edgar_sec.infra.storage.manifests` therefore does not drag in DuckDB or PyArrow.

**Obligations callers place on this layer**

- Take a DuckDB connection from `storage/duckdb.connect()` and do not construct
  one directly. The resource contract is enforced by the single call site, not
  by a runtime check, so a bypass loses it silently.
- Reuse `DEFAULT_ROW_GROUP_SIZE` / `DEFAULT_COMPRESSION` for Parquet writes. A
  per-call literal reintroduces the inconsistency those constants exist to remove.
- Treat `SnapshotsRoot` arguments to `storage/manifests.py` as
  `ProjectPaths.documents_root` (`foundation/runtime/paths.py:86`). The layout is
  `<documents_root>/<snapshot_id>/manifest.json` with the pointer at
  `<documents_root>/current/pointer.json`; `manifests.py` does not create or
  resolve that root for you.
- Pass a `RuntimeResourceProfile` (or `None`) rather than a string when a
  function takes a DuckDB resource budget, so a single profile governs a whole run.
- Inject network fakes at the transport seam. `SecHttpClient(session_factory=...)`
  is the supported seam (`sec_http/client.py:62,83`): the factory replaces the
  `requests.Session` and nothing else, so pacing, retry classification, caching,
  and the failure ledger all still run for real. `tests/support.py:130` and
  `tests/infra/sec_http/test_client.py:83` both use it. Reaching into `_send` or
  monkeypatching module internals is not the supported route.
- Close connections and cache stores. Nothing here registers an `atexit` hook;
  `SqlCache.close()`, `FixtureStore.close()`, and the DuckDB `close()` are the
  caller's responsibility.

## Public surface

This package exports no symbols of its own — `edgar_sec/infra/__init__.py` is a
docstring. The surface is the union of its three subpackages:

- `sec_http`: `SecHttpClient`, `default_headers` (`client.py`);
  `RateLimiter`, `DEFAULT_MIN_INTERVAL_S`, `MAX_INTERVAL_S`, `THROTTLE_MULTIPLIER`,
  `RECOVERY_QUIET_S`, `RECOVERY_DECAY`, `RETRY_AFTER_CAP_S` (`rate_limit.py`);
  `RetryPolicy`, `BACKOFF_BASE_S`, `BACKOFF_CAP_S` (`retry.py`);
  `SqlCache`, `make_cache_store` (`cache.py`); `HttpMetrics` (`metrics.py`);
  `PermanentHttpError`, `RetryExhausted`, `ResponseTooLargeError` (`errors.py`).
- `broker`: `SecBroker`, `SecBrokerClient`, `BrokerError`, `BrokerRequestError`,
  `PROTOCOL_VERSION`, `HEALTHCHECK_URL` (`sec_broker.py`); `managed_broker`
  (`daemon.py`).
- `storage`: `atomic_write_bytes`, `atomic_write_text`, `atomic_write_json`
  (`atomic.py`); `write_parquet_table`, `read_parquet_table`,
  `read_parquet_schema`, `count_parquet_rows`, `DEFAULT_COMPRESSION`,
  `DEFAULT_ROW_GROUP_SIZE` (`parquet.py`); `connect`, `concat_to_parquet`,
  `find_duplicate_keys`, `find_null_keys`, `find_duplicate_nested_values`
  (`duckdb.py`); `sql_literal`, `build_part_unnest_query`, `build_profile_query`,
  `build_merged_targets_query`, `copy_query_to_parquet`, `suffix_sql`
  (`duckdb_catalog.py`); `DOCUMENT_SNAPSHOT_SCHEMA`,
  `write_chunk_snapshot`, `validate_chunk_snapshot`, `assemble_document_snapshots`
  (`document_parquet.py`); `INDEX_COLUMNS`, `PAYLOAD_COLUMNS`, `INDEX_SCHEMA`,
  `PAYLOAD_SCHEMA`, `PlannedPart`, `PartError`, `plan_parts`, `quarter_path`,
  `write_index_part`, `write_payload_part`, `read_part`, `relation_for_parts`,
  `validate_part_paths`, `payload_doc_ids` (`document_parts.py`);
  `SnapshotPart`, `SnapshotReader`, `ManifestError`, `snapshot_identity`,
  `snapshot_dir`, `snapshots_dir`, `write_manifest`, `read_manifest`,
  `list_snapshots`, `publish_pointer`, `read_pointer`, `resolved_parts`,
  `dependents_of`, `expand_dependency_closure`, `now_iso`, `DATASET`, `PHASE`,
  `MANIFEST_NAME`, `PART_KIND_INDEX`, `PART_KIND_PAYLOAD` (`manifests.py`);
  `FixtureStore`, `FixtureStoreError` (`fixture_store.py`);
  `check_fixture_lineage`,
  `is_fixture_compatible`, `fixture_lineage_status`, `FixtureLineageError`
  (`fixture_lineage.py`).

## Tests

The test tree mirrors this one package-for-package
(`tests/infra/<sub>/test_<module>.py`, AGENTS.md §6):

- `tests/infra/broker/test_broker.py` (101 loc)
- `tests/infra/sec_http/test_cache.py` (62 loc)
- `tests/infra/sec_http/test_client.py` (104 loc)
- `tests/infra/sec_http/test_rate_limit.py` (26 loc)
- `tests/infra/sec_http/test_retry.py` (33 loc)
- `tests/infra/storage/test_atomic.py` (34 loc)
- `tests/infra/storage/test_document_parquet.py` (104 loc)
- `tests/infra/storage/test_duckdb.py` (106 loc)
- `tests/infra/storage/test_duckdb_catalog.py` (116 loc)
- `tests/infra/storage/test_fixture_lineage.py` (91 loc)
- `tests/infra/storage/test_fixture_store.py` — raw-table contract, immutable
  writes, read-only access, and the existing 10,000-row fixture when present.
- `tests/infra/storage/test_parquet.py` (65 loc)

Two gaps a reader should know about, since AGENTS.md §6 requires one test file
per source module:

- `storage/manifests.py` and `storage/document_parts.py` have **no mirrored test
  file**. They are exercised only through the pipeline that consumes them,
  `tests/pipelines/document_storage/test_vacuum.py` and `test_review.py`.
- `sec_http/metrics.py` and `sec_http/errors.py` have no test module of their
  own; they are covered through `test_client.py` and `test_broker.py`.

## Deliberate gaps

- **No `defs/sql/` AST or compiler layer.** v1 carried a typed SQL AST
  (`statements.py`, `predicates.py`, `relations.py`, `expressions.py`,
  `schema.py`, `dialects.py`) and a string compiler
  (`compiler/`) — 19 modules under `.v1/defs/sql/`. None of it exists in v2.
  v2 builds SQL strings directly, and `storage/duckdb_catalog.py` is the
  replacement: `build_part_unnest_query` and friends return SQL text, which the
  caller hands to a DuckDB connection. This is deliberate, and the roadmap
  records the consequence: `v2_refactor_roadmap.md` §9.6 states that v1's
  `sql-boundary` scanner "policed a `defs/sql/` AST layer that v2 removed. v2
  executes direct SQL deliberately" and that it was **not** restored, because
  a new guard would need a new rule — "no concatenated string SQL" — rather than
  the old one. `ALL_SCANNERS` in `foundation/scanners/__init__.py:18-30`
  confirms eleven scanners and no `sql-boundary`.
- **No `DuckDBStaging`.** v1's `.v1/defs/storage/staging.py` (196 loc) defined
  `DuckDBStaging`, a *file-backed* append-staging class with `register_function`
  UDFs, `create_table_as`, `insert_query`, `count`, `copy_table` (which refused
  to publish over an immutable artifact), `copy_query`, and a `close()` that
  unlinked the `.db`/`.wal` and optionally rmtree'd a cleanup root. **v2 carries
  no equivalent.** `storage/duckdb.connect()` returns an in-memory connection
  (`duckdb.connect()` with no path), and the one behaviour the two share —
  publishing a query result to Parquet — lives at
  `storage/duckdb_catalog.copy_query_to_parquet:236`, not in a staging class.
  Callers that need bulk insert use `con.executemany()` on a raw connection.
  There is no UDF-registration helper, no staging lifecycle, and no
  `StorageError` wrapper anywhere in the layer.
- **No persisted project configuration.** v1's `core/config.py` wrote
  `.artifacts/metadata/config.json`; v2 has no equivalent in this layer. Run
  options are per-invocation in `pipelines/`, not a stored artifact. Nothing in
  `storage/` reads a stored config.
- **No JSONL backend.** v1's `.v1/defs/storage/jsonl/` (chunk, codec, kv, wal —
  564 loc) has no v2 counterpart. `duckdb.concat_to_parquet`'s docstring mentions
  "Parquet or JSONL chunks", but the implementation reads only
  `read_parquet([...])` (`duckdb.py:78`), and `order_by` defaults to `("cik",)`.
  JSONL checkpoint persistence was dropped in the v2 refactor; the Parquet
  checkpoint path in AGENTS.md §4 is the only route.
- **No in-flight concurrency cap in `sec_http`.** v1 had a
  semaphore-bounded transport with an explicit concurrency policy. v2's
  `SecHttpClient` contains no `Semaphore` — it paces by reserving request slots
  in `RateLimiter` but never caps how many threads may be inside a request at
  once. The only concurrency bound in the layer is
  `broker/sec_broker.py:97`, `threading.Semaphore(max_connections)`, default 32,
  which bounds the broker's connections and therefore bounds aggregate
  in-flight requests *when workers go through the broker*. A caller that
  constructs its own `SecHttpClient` per worker gets pacing but no ceiling.
  The roadmap treats broker-mediated pacing as the answer
  (`v2_refactor_roadmap.md` §3.3 on why client-side `time.sleep` fails at
  multi-process scale), so this is a routing requirement rather than an
  oversight — but nothing enforces that a worker uses the broker.
- **No read-only query cache reader.** `sec_http/cache.py` offers `SqlCache` and
  `make_cache_store` only. A consumer that wants to inspect the cache without
  risking a write has no dedicated read-only class; the closest thing is
  `SqlCache.get`, which does not mutate but is reached through the same
  writable object.
- **No CLI, no `__main__`, no packaging entry point** anywhere in the layer.
  The v1 broker shipped a `broker_cli.py` (340 loc under
  `.v1/defs/sec_http/`); v2's broker is library-only, started in-process by
  `managed_broker()` or by the pipeline. `SecBroker.serve()` is a blocking loop
  with no signal handling — `stop()` sets an `Event` and closes the listening
  socket, and only a caller that holds the `SecBroker` object can do that.
- **No document-snapshot tests at the mirrored path**, as noted above. The
  manifest identity contract — writing a manifest under an existing `snapshot_id`
  is refused, and the pointer is written only after the manifest is on disk
  (`manifests.py:136-147`) — is therefore pinned only indirectly, by
  `tests/pipelines/document_storage/`.
- **`fixture_lineage` has no consumer in the tree.** `check_fixture_lineage`,
  `is_fixture_compatible`, and `fixture_lineage_status` are called from nothing
  outside `tests/infra/storage/test_fixture_lineage.py`. The guard they implement
  is not yet wired into the offline replay path; roadmap §9.2 (Phase 2.5 scope
  boundary) is where the fixture path is specified.
- **The broker is not a token bucket, despite what the roadmap says.** The
  roadmap describes the broker as a "Unix-socket token bucket" and a "4 RPS
  central token bucket" in several places
  (`v2_refactor_roadmap.md` §1.2, §3.3, §8; `phase_2_5.md`). Nothing in
  `broker/` or `sec_http/rate_limit.py` implements a token bucket.
  `RateLimiter` is a *slot-spacing* limiter: `acquire()` reserves the next slot
  under a lock and returns a delay, and the caller sleeps outside the lock
  (`rate_limit.py:45-60`). The broker's own concurrency bound is a
  `Semaphore`, and v1's `defs/sec_http/broker.py` had the same shape. The
  wording is a long-standing misnomer, not a missing feature. Relatedly,
  `DEFAULT_RATE_LIMIT_RPS` is `8.0`
  (`foundation/runtime/settings/sec.py:17`), not the 4 the roadmap quotes.
- **`document_parts.py` re-exports two constants.** `PART_KIND_INDEX` and
  `PART_KIND_PAYLOAD` are imported from `manifests.py` and then listed in
  `document_parts.__all__` (`document_parts.py:242-243`) without being
  redefined. AGENTS.md §1.2 names `__init__.py` specifically, so this does not
  violate the letter of the rule, but it is the only re-export in the layer and
  the constants are owned by `manifests.py`.
- **The `document_parts` module docstring overstates its compression story.** It
  says "PyArrow and zstandard are confined here, next to `document_parquet.py`",
  but the module imports only `pyarrow` and `pyarrow.parquet` — no
  `zstandard`. Parts are Parquet files using the `zstd` *codec*
  (`DEFAULT_COMPRESSION`); no module in the layer constructs a `zstandard` codec.
  The two BLOB-compressing consumers, `sec_http/cache.py` and
  `storage/fixture_store.py`, both call `foundation.compression`, which owns the
  one codec implementation in the tree. (`fixture_store.py` still imports
  `zstandard` for the `ZstdError` type it catches, and for nothing else.)
