# `edgar_sec/pipelines/metadata_sync` — Phase 1: SEC submissions metadata to a published snapshot

This package turns a CSV of CIKs into a published, sorted, versioned
`metadata.parquet` dataset. It owns the plan, the resumable workers, the
validation that decides a run is publishable, and the merge that publishes — and
nothing else. Row normalization lives in `engine/submissions/`, the HTTP client
in `infra/sec_http/`, and the Parquet and DuckDB primitives in `infra/storage/`.

## Purpose

Phase 1 is the pipeline that *fetches*. It is the only pipeline in the layer
that performs network I/O as its main job, and the only one whose unit of
resumability is a network fetch.

Its design premise is that **completion is a property of the data, not of queue
state**: every requested CIK produces exactly one row, including failures, so a
chunk's completeness is decidable by reading the chunk
(`worker.py:8-9`). That is what makes `run` idempotent and a resume cheap.

What this package is not:

- Not a document pipeline. It does not fetch filing documents, unroll SGML, or
  resolve exhibits. That is `document_storage/`, which consumes the catalog this
  pipeline's output feeds through `filing_catalog/`.
- Not the schema owner. `SUBMISSION_METADATA_SCHEMA`, `SCHEMA_VERSION`, and
  `TERMINAL_STATUSES` are declared in `edgar_sec/domain/submissions/schemas.py`.
  This package asserts conformance to them and never redefines them.
- Not a source of identity. `Cik` comes from `domain/identity`; the manifest
  normalizes *to* 10-digit CIK strings and never invents one.

Status: **Phase 1, complete.** `roadmap/refactor_v2/phase_1.md` records
"Milestones 0, 1, 2, 3, 4, 5, 6, and 6.1 implemented, tested, and passing all
quality gates."

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (1 loc). No re-exports, per AGENTS.md §1.2. |
| `cli.py` | The five pipeline commands plus the nested `sources` group and the argparse surface; each `cmd_*` is a plain callable the operator also calls (372 loc). |
| `operator.py` | Interactive wizard; a presentation shim over the same `cmd_*` functions (146 loc). |
| `manifest.py` | CIK CSV ingestion, header detection, normalization, deduplication, skipped-row reporting, curated names, and the input fingerprint (110 loc). |
| `planner.py` | Deterministic chunk/partition planning, `plan_id` derivation, partition-coverage invariant, atomic `plan.json` write, and stale-plan/schema-version rejection (195 loc). |
| `paths.py` | `MetadataPaths` / `RunPaths`; the published-vs-transient split plus source and registry locations (148 loc). |
| `sec_client.py` | One CIK to its submissions document plus every historical file listed under `filings.files` (120 loc). |
| `worker.py` | Resumable chunk and partition execution over a thread pool; the never-refetch guarantee (268 loc). |
| `checkpoints.py` | What counts as a *complete* chunk on disk (133 loc). |
| `merger.py` | Coordinator validation, out-of-core sorted merge, progress events, snapshot manifest, pointer advance (278 loc). |
| `augmentation.py` | Delta merge onto a published snapshot without refetching the base (234 loc). |
| `source_registry.py` | Write-once, content-addressed `company_tickers.json` snapshots, reached by `sources refresh` (215 loc). |
| `registry.py` | Curated-versus-source comparison and the effective-input projection, reached by `sources compare` (348 loc). |
| `smoke_test.py` | Credential-gated live check that never publishes, and the documented replacement for v1's `preview` command (141 loc). |

Total 2,807 lines across 14 files: 13 modules plus a one-line `__init__.py`.

## Contracts

**Guarantees this package makes to its callers**

- **`plan` performs no network and no model calls.** It reads a CSV, hashes it,
  and writes one JSON file. `cmd_plan` builds a `SubmissionsClient` only in
  `cmd_run` and `cmd_augment` (`cli.py:80-82`).
- **Planning is deterministic and idempotent.** `plan_id` is
  `sha256(f"{input_fingerprint}:{chunk_size}:{partition_count}")[:16]`
  (`planner.py:36-41`) — derived from the plan-defining inputs, never a
  timestamp. Replanning unchanged inputs reproduces the same id; changing the
  chunking produces a different one.
- **A stale plan is rejected, not reused.** `load_plan` recomputes the expected
  id from the plan's own recorded `input_fingerprint`, `chunk_size`, and
  `partition_count`, and raises when they disagree; it also verifies that the
  chunk boundaries reconstruct the CIK list and that `row_count` matches
  (`planner.py:117-156`). A stale plan can never produce a mislabeled snapshot.
- **Every requested CIK produces exactly one row.** Failures are rows, not
  absences (`worker.py:8-9`). A non-terminal status is rewritten to `failed`
  with an explanatory error (`worker.py:95-97`), and a terminal transport error
  with no filings becomes `failed` while one with filings becomes `partial`
  (`worker.py:91-94`).
- **A completed chunk is never refetched.** The guarantee lives in `run_chunk`,
  not in each caller, "because a refetch is exactly what makes a resume slow and
  a rerun non-idempotent" (`worker.py:164-170`). `inspect_chunk` short-circuits
  before any client is touched.
- **A worker never writes a published artifact.** Workers write only
  `transient/metadata/<plan_id>/chunk_NNNN.parquet`. `publish_snapshot` is the
  only writer of the snapshot manifest and the `current` pointer, and
  `merger.py:1-11` says so: "The coordinator is the only component that writes
  published artifacts."
- **Workers are sized from memory, not CPU count.** `resolve_workers` returns
  `derive_resources().workers` for a non-positive request
  (`worker.py:43-49`), and `_run_chunk_rows` applies it to the `ThreadPoolExecutor`
  (`worker.py:130`). Hardcoding `max_workers` is blocked by the
  `resource-allocation` scanner.
- **Heap is reclaimed at bounded intervals.** `reclaim()` runs every
  `RECLAIM_INTERVAL = 64` processed CIKs and once more at the end of every chunk
  (`worker.py:32, 146-149`).
- **The merge is out-of-core.** `concat_to_parquet(con, paths, output_path,
  order_by=("cik",))` issues a DuckDB `COPY (... ORDER BY cik)`, so a dataset
  larger than memory still merges (`merger.py:205`).
- **The manifest is the reproducibility root.** `input_fingerprint` is
  `file_sha256(input_csv)` and appears in `plan.json`, in every row, in every
  chunk, and in the published snapshot manifest.
- **Malformed input rows are reported, not dropped silently.** `read_cik_manifest`
  collects unparseable rows into `skipped` with line number, value, and reason,
  and counts duplicates separately (`manifest.py:55-98`).
- **The `current` pointer is written after the artifact, never before.** Both
  writes are atomic (`merger.py:225-247`).

**Obligations callers place on this package**

- Supply a CIK manifest whose file content is stable if you want plan identity
  to be stable. The fingerprint is the file digest, not a normalized digest, so
  reordering or reformatting the CSV produces a different plan.
- Treat `status` as read-only. It is the only command that neither fetches nor
  publishes, and it is the correct preflight for `merge`.
- Do not publish from a worker process, and do not hand-assemble the snapshot
  from chunk files. The coordinator's validation list is the contract; bypassing
  it skips duplicate-CIK, null-CIK, schema-drift, and fingerprint checks.
- Do not expect a per-CIK retry beyond what `infra/sec_http/retry.py` already
  does. A CIK that exhausts retries becomes a `failed` row, not an exception.
- Do not treat a `partial` row as `ok`. `partial` means the submissions document
  was retrieved but at least one historical file was not, and the errors are
  recorded on the result (`sec_client.py:94-105`).

## Public surface

- `RunOptions` — frozen slotted dataclass of effective invocation settings
  (`input_path`, `artifacts_root`, `chunk_size`, `partition_count`, `workers`,
  `snapshot_id`, `plan_id`, `input_fingerprint`, `limit`) with
  `effective_plan_id()` and `snapshot()`. `cli.py`.
- `build_parser` — the argparse surface for `python run.py metadata`.
  `cli.py`.
- `main` — CLI entrypoint; dispatches `args.func` and returns 1 on
  `FileNotFoundError`, `ValueError`, or `RuntimeError`. `cli.py`.
- `cmd_plan`, `cmd_status`, `cmd_run`, `cmd_merge`, `cmd_augment` — the five
  command implementations, importable and callable directly. `cli.py`.
- `build_operator_menu` — five `MenuAction` entries bound to the same `cmd_*`
  functions. `operator.py`.
- `InputManifest` — frozen slotted dataclass: `input_name`, `input_path`,
  `input_fingerprint`, `ciks`, `skipped`, `duplicate_count`, and the
  `row_count` property. `manifest.py`.
- `read_cik_manifest` — CSV to a normalized, deduplicated, fingerprinted
  manifest; raises `FileNotFoundError` for a missing file and `ValueError` for a
  manifest with no usable CIKs. `manifest.py`.
- `build_plan` — the immutable plan document; raises `ValueError` for
  `chunk_size < 1` or `partition_count < 1`. `planner.py`.
- `derive_plan_id` — the 16-character content-derived plan identifier.
  `planner.py`.
- `write_plan`, `load_plan` — atomic persist and validated reload. `planner.py`.
- `plan_chunk_ids` — planned chunk ids, optionally restricted to one partition.
  `planner.py`.
- `utc_now_iso` — second-resolution UTC stamp; the one time source in the
  package. `planner.py`.
- `PLAN_FORMAT_VERSION` (`"1.0.0"`). `planner.py`.
- `MetadataPaths`, `RunPaths` — the two path dataclasses; `RunPaths.chunk_file`
  returns `chunk_{chunk_id:04d}.parquet`. `paths.py`.
- `resolve_metadata_paths`, `resolve_run_paths` — resolve the layout from an
  explicit artifacts root, a `ProjectPaths`, or the project default.
  `paths.py`.
- `METADATA_DIR`, `SNAPSHOT_FILE_NAME`, `SNAPSHOT_MANIFEST_NAME` — the artifact
  names Phase 2 and other consumers bind to. `paths.py`.
- `SubmissionsClient` — fetches one CIK's submissions document and every
  historical file it lists. The `SecHttpClient` is injected, so a test supplies
  a scripted session while pacing, retry, cache, and failure-ledger behaviour
  stay under test. `sec_client.py`.
- `CikFetchResult` — per-CIK outcome with `terminal_error()`,
  `historical_payloads`, `historical_errors`, `historical_files_fetched`,
  `byte_count`, and `response_sha256`. `sec_client.py`.
- `run_chunk` — execute one chunk and atomically write its checkpoint; returns a
  `ChunkResult` with `skipped_existing=True` when a valid checkpoint exists.
  `worker.py`.
- `run_partition` — run every outstanding chunk in one partition, skipping
  completed ones. `worker.py`.
- `resolve_workers` — the cgroup-aware worker count. `worker.py`.
- `normalize_one_cik` — fetch and normalize one CIK into a canonical row dict.
  `worker.py`.
- `ChunkResult` — frozen slotted dataclass: `chunk_id`, `path`, `row_count`,
  `skipped_existing`, `statuses`, `historical_files`. `worker.py`.
- `RECLAIM_INTERVAL` (64). `worker.py`.
- `ChunkInfo` — a validated checkpoint: `chunk_id`, `path`, `row_count`, `ciks`,
  `file_sha256`, and an always-true `valid` property (instances are only
  constructed for valid checkpoints). `checkpoints.py`.
- `inspect_chunk` — validate one checkpoint, returning `None` when unusable.
  `checkpoints.py`.
- `discover_completed_chunks` — every valid checkpoint for a plan, keyed by
  chunk id. `checkpoints.py`.
- `schema_matches` — Parquet footer schema equals the canonical schema.
  `checkpoints.py`.
- `merge_chunks` — validate all chunks and publish a sorted snapshot dataset;
  raises `MergeError` on any failure. Accepts an optional `progress` callback
  that receives one event per merge stage. `merger.py`.
- `validate_chunks` — the full rejection list, returning ordered checkpoint
  paths. `merger.py`.
- `publish_snapshot` — write the snapshot manifest and advance the pointer.
  `merger.py`.
- `MergeReport` — frozen-ish report with `to_dict()`: `snapshot_id`,
  `output_path`, `row_count`, `chunk_count`, `filing_record_count`,
  `artifact_sha256`, `plan_id`, `input_fingerprint`, `schema_version`,
  `merged_at`, `duplicate_accessions`, `warnings`. `merger.py`.
- `MergeError` — merge rejected; the snapshot was not published. `merger.py`.
- `augment` — augment a published snapshot with newly requested CIKs.
  `augmentation.py`.
- `augment_from_manifest` — the same, reading the manifest from disk first.
  `augmentation.py`.
- `plan_delta`, `base_snapshot_ciks` — delta planning primitives.
  `augmentation.py`.
- `AugmentResult` — `base_snapshot_id`, `new_snapshot_id`, `base_row_count`,
  `delta_row_count`, `refetched_ciks`, `report`, and the `total_row_count`
  property. `augmentation.py`.
- `refresh_company_tickers` — fetch and publish one immutable source snapshot.
  Reached from the CLI by `sources refresh`. `source_registry.py`.
- `load_source_snapshot` — load a source manifest and verify the referenced
  payload digest. `source_registry.py`.
- `parse_company_tickers`, `source_snapshot_id` — listing normalization and
  content addressing. `source_registry.py`.
- `SourceSnapshot`, `SourceRegistryError`, `SOURCE_NAME`
  (`"company_tickers"`), `SOURCE_URL`, `SOURCE_SCHEMA_VERSION`, and
  `SOURCE_MANIFEST_KIND`. `source_registry.py`.
- `compare_sources` — project the curated CIK input against a published source
  snapshot into listing observations, the registrant registry, new CIKs, an
  augmentation worklist, and an effective CIK input CSV, each with a published
  manifest. Performs no network access. Reached from the CLI by
  `sources compare`. `registry.py`.
- `registry_id_for` — content-derived registry identity for one
  source/curated-input pair. `registry.py`.
- `load_registry_manifest` — load one effective-input manifest and verify its CSV
  digest. `registry.py`.
- `RegistryError`, `REGISTRY_SCHEMA_VERSION`, `REGISTRY_MANIFEST_KIND`,
  `EFFECTIVE_INPUT_MANIFEST_KIND`, `LISTING_SCHEMA`, `REGISTRY_SCHEMA`,
  `WORKLIST_SCHEMA`. `registry.py`.
- `build_parser`, `main` — the bounded live smoke test's command surface.
  `smoke_test.py`.

## Commands

Entry point: `python run.py metadata <command>`, which dispatches through
`runpy` to `edgar_sec/pipelines/metadata_sync/operator.py`. With no argument,
`operator_entrypoint` shows the wizard; with an argument it calls `cli.main`.

```bash
python run.py metadata plan   --input uploads/cik-sec.csv
python run.py metadata status --input uploads/cik-sec.csv
python run.py metadata run    --input uploads/cik-sec.csv
python run.py metadata merge  --input uploads/cik-sec.csv
python run.py metadata augment --input uploads/cik-sec-new.csv \
    --base-snapshot-id <id> --new-snapshot-id <id>
python run.py metadata sources refresh
python run.py metadata sources compare --input uploads/cik-sec.csv \
    --source-manifest <artifacts-root>/metadata/sources/company_tickers/<id>/manifest.json
```

Common flags, added to every subcommand by `add_common` (`cli.py:224-244`):

| Flag | Type | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `--input` | str | required | CIK manifest CSV. |
| `--artifacts` | str | `""` | Artifacts root override; empty means `resolve_paths().artifacts_root`. |
| `--chunk-size` | int | `runtime.chunk_size` (1000) | CIKs per resumable chunk. |
| `--partition-count` | int | `runtime.partition_count` (1) | Operational partitions; chunk *i* goes to partition `i % partition_count`. |
| `--workers` | int | `runtime.workers` (machine-derived) | Worker threads; unset means machine-derived. |

Each of these three flags defaults to *unset* in the parser and is resolved at
the options boundary in `cli.py`, so building a parser never reads the process
environment. Resolution order is **CLI flag → environment/`.env` → code
default**. `test_cli.py` pins each tier, including the regression that
`RUNTIME_CHUNK_SIZE=2 RUNTIME_PARTITION_COUNT=3` must produce a plan recording
`2` and `3`.

Per-subcommand flags:

- `plan`: `--limit` (int, default `None`) — truncate the manifest CIK list before
  planning, for a bounded plan.
- `status`: none beyond the common set.
- `run`: `--chunk` (int), `--partition` (int). `--chunk` takes precedence over
  `--partition`; with neither, every planned chunk is a target. The partition
  branch calls `worker.run_partition` and rejects an id absent from the plan.
- `merge`: none beyond the common set. Snapshot identity is **plan-derived**;
  see the deliberate gap below.
- `augment`: `--base-snapshot-id` and `--new-snapshot-id`, **both required**.
- `sources refresh`: `--artifacts` only.
- `sources compare`: `--input`, `--source-manifest`, and `--artifacts` — the
  first two required.

Exit behaviour. `main` wraps the dispatch in `try/except` for
`FileNotFoundError`, `ValueError`, and `RuntimeError`, printing
`error: <message>` to stderr and returning 1 (`cli.py:277-285`). Every
successful command returns 0. Two cases return 1 without raising:

- `run` with no chunks selected prints `no chunks selected` and returns 1
  (`cli.py:155-157`).
- `augment` when every requested CIK is already in the base snapshot raises
  `MergeError` from `augment()`, which `main` converts to `error: ...` and 1.

`MergeError` subclasses `RuntimeError`, so a rejected merge is reported through
the same path as a missing file.

Output: `plan` prints one summary line; `status` prints an indented JSON object;
`run` prints one line per chunk; `merge` prints the snapshot manifest JSON;
`augment` prints a JSON summary of the delta.

### The live smoke test

Not part of the CLI and not collected by pytest:

```bash
python -m edgar_sec.pipelines.metadata_sync.smoke_test \
    --input tests/fixtures/cik_sec_mini.csv --sample-size 3 --artifacts preview/metadata
```

`--artifacts` is required and must resolve under a `preview` directory; anything
else exits 2 with `error: --artifacts must point at a preview directory, never a
production snapshot root` (`smoke_test.py:76-84`). A manifest error exits 2; any
sampled CIK with `status == "failed"` exits 1; otherwise it prints
`smoke test passed (no snapshot published)` and exits 0. It never touches a
published snapshot or the production `current` pointer.

## Resumability and publication

### Artifact layout

```text
{artifacts_root}/metadata/
├── plans/{plan_id}/plan.json                  immutable plan
├── sources/{name}/{snapshot_id}/              immutable raw source snapshot
│   ├── raw.json
│   └── manifest.json
├── snapshots/{snapshot_id}/
│   ├── metadata.parquet                       published, sorted by cik
│   └── metadata.manifest.json
└── snapshots/current/pointer.json             currently published snapshot

{artifacts_root}/transient/metadata/{plan_id}/chunk_NNNN.parquet   resumable state
```

The split is stated in `paths.py:1-6`: "Plan-scoped transient checkpoints are
separated from published snapshots: chunks are resumability state, snapshots are
output." No module in this package contains a `.artifacts` literal;
`artifact-paths` blocks one outside the resolvers.

### The lifecycle

**1. `plan` — deterministic, offline.** `read_cik_manifest` validates the raw
text before integer conversion, because `Cik.from_raw("")` deliberately yields
CIK zero and would let an empty manifest row masquerade as a real registrant
(`manifest.py:39-52`). A header row is detected by the absence of a leading
digit in the first cell. Duplicates keep their first position and are counted.
Then `build_plan` slices the CIK list into `chunk_size` chunks, each carrying
`chunk_id`, `offset`, and `cik_padded`, and assigns partitions by
`chunk_index % partition_count`, skipping empty partitions
(`planner.py:44-91`). The plan records `plan_id`, `plan_format_version`,
`schema_version`, `created_at`, `input_name`, `input_fingerprint`, `chunk_size`,
`partition_count`, `row_count`, the full `cik_padded` list, `chunks`,
`partitions`, `skipped_rows`, and `duplicate_rows`. `write_plan` persists it with
`atomic_write_json(..., canonical=False, indent=2)`.

**2. `run` — resumable, network.** For each target chunk not already complete,
`_run_chunk_rows` submits one `normalize_one_cik` future per CIK to a
`ThreadPoolExecutor` and collects results **in plan order**, not completion
order (`worker.py:143-150`). A thread pool rather than a process pool, for three
reasons given at `worker.py:1-7`: the shared HTTP client and its SQLite cache are
thread-safe, the work is network-bound rather than CPU-bound, and DuckDB is
confined to the coordinator. Rows are written through
`build_submission_table` and `write_parquet_table`, so the checkpoint carries the
canonical Arrow schema rather than a private one.

**3. The checkpoint contract.** `inspect_chunk` returns a `ChunkInfo` only when
all of the following hold; anything else returns `None`, so the chunk is
refetched rather than merged (`checkpoints.py:1-6, 56-101`):

- the file exists;
- `read_parquet_schema(path).equals(SUBMISSION_METADATA_SCHEMA,
  check_metadata=False)`;
- its CIK column, as a set, equals the planned CIK set and the lengths agree;
- its `input_fingerprint` column contains no value other than the plan's
  fingerprint.

A `ChunkInfo` also carries `file_sha256` for the file on disk.

**4. `status` — offline progress.** Reports `planned_chunks`,
`completed_chunks`, `outstanding_chunks`, and `mergeable` (`not outstanding`).
It builds no HTTP client.

**5. `merge` — coordinator publication.** `validate_chunks` raises
`MergeError` on: chunk files outside the plan; missing checkpoints; schema drift
from the dataset contract; row count differing from the plan; CIK coverage
differing from the plan; a foreign input fingerprint; a status outside
`{ok, partial, failed}`; and a plan whose chunks do not cover its own
`row_count` (`merger.py:88-160`).

`merge_chunks` then opens **one** DuckDB connection, refuses null CIKs and
duplicate CIKs, records duplicate accessions as reportable fan-out rather than a
failure, and runs the out-of-core `ORDER BY cik` COPY. It re-checks the merged
row count against the plan and the published schema against the contract, and
records `artifact_sha256` and `filing_record_count`
(`merger.py:170-222`).

Two classes of finding are deliberately distinguished (`merger.py:4-11`):

- **Failures** — duplicate or null CIKs, schema drift, plan coverage gaps,
  mismatched row counts, foreign chunk files, non-terminal statuses.
- **Reportable fan-out** — duplicate accessions. "The same filing is
  legitimately listed by more than one registrant, so duplicates are surfaced as
  a warning and never reject a merge."

**6. `augment` — the delta path.** `plan_delta` builds a plan over only the CIKs
absent from the base snapshot; an empty delta raises rather than publishing a
no-op snapshot. The base Parquet is merged *alongside* the delta checkpoints, so
base CIKs are carried forward untouched and never refetched
(`augmentation.py:1-7, 104-119`). A base of N rows receiving K new rows must end
at exactly N+K, and the merged CIK set must equal the union of base and delta —
both checked, both `MergeError` otherwise (`augmentation.py:186-200`).

### On resume

Nothing is refetched and nothing is re-planned unnecessarily:

- `run` and `status` re-derive the plan id from the manifest fingerprint and the
  *effective* chunking settings, so an unchanged input resolves to the same plan
  directory and the same chunk checkpoints. There is no `--plan-id` override:
  the plan id is derived, never chosen.
- `load_plan` refuses a plan whose recorded inputs do not reproduce its id, and
  refuses a plan whose `schema_version` or `plan_format_version` differs from the
  running build, so a stale plan cannot silently produce a mislabeled snapshot.
  A plan written by an older build must be regenerated.
- Each chunk is revalidated before it is skipped, so a truncated or
  schema-drifted checkpoint is refetched rather than trusted.
- `merge` is idempotent in the sense that it re-validates everything and then
  publishes; it does not itself skip already-merged chunks, because the snapshot
  directory is content-addressed by `plan_id`.

Because the plan id follows the effective chunking, changing `RUNTIME_CHUNK_SIZE`
between `plan` and `run`/`merge` resolves a *different* plan and the command
fails with `error: missing plan: ...` rather than reusing the wrong checkpoints.
`test_cli.py::test_changed_effective_chunking_fails_loudly` pins that.

## Tests

- `tests/pipelines/metadata_sync/test_manifest.py` (71 loc, 6 tests) — CSV
  ingestion, header detection, malformed rows, duplicates, fingerprint.
- `tests/pipelines/metadata_sync/test_planner.py` (173 loc, 16) — plan identity,
  chunking, partition assignment, partition-coverage invariant,
  stale-plan/schema-version/format-version rejection.
- `tests/pipelines/metadata_sync/test_checkpoints.py` (110 loc, 7) — what counts
  as complete.
- `tests/pipelines/metadata_sync/test_worker.py` (188 loc, 10) — one-row-per-CIK,
  status coercion, never-refetch.
- `tests/pipelines/metadata_sync/test_merger.py` (378 loc, 18) — the rejection
  list, the merge itself, progress events, and plan-derived snapshot identity.
- `tests/pipelines/metadata_sync/test_augmentation.py` (251 loc, 8) — the delta
  path and its documented `augment_from_manifest` wrapper.
- `tests/pipelines/metadata_sync/test_end_to_end.py` (150 loc, 3) — the
  plan → run → merge replay.
- `tests/pipelines/metadata_sync/test_cli.py` (358 loc, 19) — the command
  surface, the settings-resolution tiers, `sources` routing, partition
  execution, launcher registration.
- `tests/pipelines/metadata_sync/test_operator.py` (264 loc, 17) — menu
  bindings, namespace shape, action-to-command delegation.
- `tests/pipelines/metadata_sync/test_paths.py` (110 loc, 7) — the
  published-vs-transient split, snapshot/plan/source/registry locations.
- `tests/pipelines/metadata_sync/test_sec_client.py` (126 loc, 9) — submissions
  fan-out, historical-file outcomes, permanent vs transient errors.
- `tests/pipelines/metadata_sync/test_source_registry.py` (180 loc, 10) — the
  immutable source snapshot lifecycle.
- `tests/pipelines/metadata_sync/test_registry.py` (318 loc, 14) — the
  curated-versus-source comparison, its published artifacts and manifests, and
  the effective-input CSV contract.
- `tests/pipelines/metadata_sync/test_smoke_test.py` (201 loc, 8) — the
  preview-root guard and exit codes. The live fetch itself is not exercised.
- `tests/pipelines/metadata_sync/conftest.py` (24 loc) — shared setup.

Mirrored tests in the dependency closure:

- `tests/domain/submissions/test_models.py` (125 loc, 8) — the deferred domain
  models' own invariants.
- `tests/engine/submissions/test_helpers.py` (165 loc, 14) — coercion and alias
  resolution.
- `tests/infra/storage/test_parquet.py` (120 loc, 8) — including Parquet write
  atomicity, which the chunk-checkpoint contract depends on.
- `tests/infra/sec_http/test_client.py` (187 loc, 12) — including the
  `max_response_bytes` permanent-failure classification.

Every source module in this package now has a mirrored test file. Offline and
deterministic; the network fakes are injected at the `SecHttpClient` transport
seam through `tests.support`, never by reaching into module internals
(AGENTS.md §6.5).

`smoke_test.py` is itself not collected by pytest as a live run, but its parser
and its preview-root guard are covered offline by `test_smoke_test.py`
(`smoke_test.py:12-14`).

`tests/test_network_isolation.py` deliberately includes
`pipelines.metadata_sync` in its final walk — the package that *does* import
`edgar_sec.infra.sec_http` — to prove the AST walk is sensitive enough to find a
dependency that exists.

## Deliberate gaps

- **No persisted project configuration.** v1 wrote `.artifacts/metadata/config.json`
  through a `--configure` command and validated plans against saved options. That
  is not carried forward. Effective settings are the CLI flag, then
  environment/`.env`, then the code default, and `plan.json` is the record of
  what a run actually used. There is no `--configure`, no stored operator
  defaults, and `--input` must be supplied on every command. The plan-defining
  stale-plan guard v1 paired with the config file is not lost with it:
  `load_plan` re-derives the plan id from the plan's own recorded fingerprint and
  chunking, and now also refuses a plan whose `schema_version` or
  `plan_format_version` differs from the running build. The cost is that an
  operator must keep effective chunking stable across `plan`/`run`/`merge`; when
  it changes, the derived plan id changes and the command fails loudly with
  `error: missing plan` instead of reusing mismatched checkpoints.
  `runtime.chunk_size` and `runtime.partition_count` are declared `env=True,
  cli=True` only; the `config=True` flags they previously carried described a
  capability that had no backing store and were removed.
- **Snapshot identity is plan-derived.** There is no `--snapshot-id` override.
  The chunk rows, the `MergeReport`, the published manifest, and the snapshot
  directory all use the plan id, so a row's `snapshot_id` can never disagree with
  the artifact containing it. A merge-only rename flag would have published an
  artifact whose rows still carried the plan id, so it was removed rather than
  wired.
- **The v1 two-stage merge protocol is retired.** v1 published one finalized
  artifact per partition (`merge-partition`) and then merged only those
  artifacts, binding each to the plan with `plan_hash` and `artifact_sha256`.
  This package validates every chunk directly against the canonical schema and
  publishes one sorted snapshot in a single stage, keeping all of AGENTS.md
  §4.3's validation requirements and additionally binding the published manifest
  to its plan id. What v2 does **not** have is partition-level intermediate
  artifacts, receipts, or report regeneration from a finalized artifact without
  chunk access. With `runtime.partition_count` defaulting to 1 the boundary would
  be inert anyway. Merge *progress* events were restored: `merge_chunks` takes an
  optional `progress` callback and the CLI renders stage events to stderr.
- **`preview` is replaced by `smoke_test.py`, not a subcommand.** v1's lifecycle
  listed `preview` as a bounded, explicitly non-production command. This package
  has no `preview` subcommand; `smoke_test.py` performs the same bounded live
  fetch under a mandatory preview-root guard and never publishes. It is a
  standalone module command rather than part of the CLI, and its parser and guard
  are covered offline by `test_smoke_test.py`.
- **The domain submission models are deferred, not produced.** `EntityProfile`,
  `SubmissionsAggregate`, `FilingRecord`, `Listing`, `FormerName`, and `Address`
  in `edgar_sec/domain/submissions/models.py` have **no producer in this
  pipeline**. The live row contract is `SUBMISSION_METADATA_SCHEMA` and the
  engine builder; `normalize_one_cik` returns a row dict, never a typed aggregate.
  They are retained as the domain vocabulary a future rendering/projection layer
  will read published Arrow rows into, and
  `tests/domain/submissions/test_models.py` pins their invariants *and* asserts
  that no current pipeline module constructs them, so the deferred status stays
  checkable. Building the adapter that consumes them is out of scope here.
- **`engine/submissions/helpers.normalize_cik_padded` was removed.** It was an
  unused orphan that zero-filled a raw value with no validation, weaker than the
  `edgar_sec.domain.identity.Cik` path that actually performs padding. `Cik` is
  the single padding authority.
- **No parallel settings registry, deliberately.** AGENTS.md §3.1 says a new
  phase registers its own spec dictionaries. This package registers none: it
  reads `resolve_runtime_settings()` for SEC identity, rate limits, and the
  chunk/partition/worker defaults (`cli.py`, `source_registry.py`,
  `smoke_test.py`) and overrides chunk size, partition count, and worker count
  from the command line. The specs it reads are declared once, in Layer 0.
  There is no `settings.py` in this package, and `os.environ` is unreachable here
  under the `environment-access` scanner.
- **`--workers` is threads, not processes.** A reader looking for a process pool
  in Phase 1 will not find one, and that is correct: the reason is written at
  `worker.py:1-7`. Process isolation enters at Phase 2.5, where a worker
  normalizes a full filing document and the allocation churn fragments the heap
  past what the container's cgroup allows.
- **No retry beyond the shared HTTP client.** `SubmissionsClient.fetch_cik`
  catches `PermanentHttpError` and `RetryExhausted` and records them on the
  result; it does not retry itself, and it does not retry an individual
  historical file that failed — the error is appended to `historical_errors` and
  the fetch moves on (`sec_client.py:94-105`). Historical files are "required
  inputs rather than best-effort extras" in the sense that a missing one changes
  the row to `partial`; it does not mean they are re-requested.
- **The source registry is one hardcoded source.** `SOURCE_NAME` and `SOURCE_URL`
  are module constants for `company_tickers.json`. `sources refresh` publishes an
  immutable, content-addressed snapshot and `sources compare` projects the
  curated input against it, but there is no other external source, and nothing
  in the fetch path consults a source snapshot: a CIK manifest still arrives as a
  CSV. `compare_sources` is a pure projection over its two inputs and performs no
  network access, so a comparison is reproducible from immutable evidence.
- **No date, era, or cohort reasoning.** Planning slices on CIK identity and
  nothing else. Everything downstream of identity — form filters, amendment
  policy, suffixes, quotas, stratification — belongs to
  `filing_catalog/planner.py`. The `SelectionPolicy` type is not referenced in
  this package.
- **No deletion or garbage collection.** There is no command that prunes
  snapshots, plans, chunk checkpoints, source snapshots, or registries. A
  published snapshot directory is never removed by this package, and nothing
  compacts the transient tree. Phase 2.5 has `vacuum_snapshots()`; Phase 1 has no
  equivalent, by design — a Phase 1 dataset is a direct function of its input
  manifest, so re-planning is cheaper than vacuuming.
- **`filing_record_count` is computed by a second full read.**
  `_filing_record_count` re-opens the published Parquet and sums the `filings`
  list lengths (`merger.py:76-85`) after the COPY has already run. It is
  metadata for the manifest, not part of the merge, and it is the one place in
  the merge that is not out-of-core.
- **`plan.json` embeds the full CIK list.** `cik_padded` is stored alongside the
  chunk boundaries, which is redundant by roughly a factor of the chunk count.
  The redundancy is what makes `load_plan` able to verify that the chunk
  boundaries reconstruct the CIK list (`planner.py`), so it is a deliberate
  integrity check rather than an oversight.
