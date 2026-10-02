# `edgar_sec/pipelines/document_storage` — Phase 2.5: acquire, normalize, snapshot, consolidate

Fetches primary filing documents, unrolls their SGML envelopes, normalizes them,
resolves exhibits a stub primary delegates to, and publishes immutable snapshots
that can be consolidated across runs. It is the only pipeline in the layer that
normalizes a full document body, and the only one that needs a process pool.

`AGENTS.md` is normative; where this file disagrees with it, this file is wrong.

## Purpose

Phase 1 produced submissions metadata; Phase 2 turned it into a catalog and a
target plan; this package consumes those locators and produces text.

1. **Acquire.** A fetcher returns raw bytes for one document locator and decides
   nothing about storage.
2. **Normalize and triage.** A processor returns normalized text plus a
   stub/delegation verdict.
3. **Resolve delegations.** A stub primary that incorporates its substance from
   an exhibit gets that exhibit fetched and recorded alongside it.
4. **Publish, then consolidate.** Per-run snapshots merge into one canonical
   snapshot.

What it is not:

- Not the phase that decides *which* documents to fetch — that is
  `filing_catalog/planner.py`; this package consumes the plan.
- Not an HTTP client owner. It uses `infra/sec_http`, the `infra/broker` socket,
  or a fixture; only `documents fill` makes live requests.
- Not a normalizer owner. `engine/forms/normalize.py` and
  `engine/document/unpacking/unpacker.py` own text conventions and SGML
  structure; this package sequences them and records what they decided.

**Why it sits in Layer 4 rather than Layer 2.** Its fetchers call
`engine.document.unpacking.unpacker` to select a sub-document out of an SGML
envelope, and a fetcher that has to call the engine cannot live below it. The raw
fixture store it reads *is* infrastructure and stays in
`infra/storage/fixture_store.py`.

Real-filing parity is unverified — see "Deliberate gaps".

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (7 loc); states the Layer 4 placement rationale. No re-exports, per AGENTS.md §1.2. |
| `cli.py` | Six subcommands, plan-file ingestion, and the phase-local menu. |
| `operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish. |
| `fixture_operator.py` | Fixture discovery, live raw fill, append/resume, manifest publication. |
| `paths.py` | `DocumentStoragePaths`, `chunk_checkpoint_path`, artifact constants (`SNAPSHOT_ARTIFACT_NAME`, `CASES_DIR`, `REVIEW_MANIFEST_NAME`, etc.). |
| `worker.py` | Chunk processing, the process pool, the checkpoint-reuse rule. |
| `fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends. |
| `processor.py` | `FilingProcessor`, `PassThroughProcessor`, the processor fingerprint. |
| `delegation.py` | The exhibit second pass for stub primaries. |
| `merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer. |
| `vacuum.py` | `vacuum_snapshots()`: cross-run consolidation. **Unwired** — no CLI route, no production caller. |
| `queries.py` | The consolidation SQL; the only module in this package that holds any. |
| `review.py` | `compare_review_runs()`: base-vs-new review-run comparison. |
| `review_artifacts.py` | Fixture-backed review artifact generation: selection, per-case files, manifest. |

## Contracts

**Guarantees to callers**

- **A fetcher reports; it never decides.** It never writes a checkpoint, never
  opens a transaction, and never judges a payload good enough. That boundary is
  what lets one fetcher serve a worker, a fixture builder, and the review tool.
- **A chunk checkpoint is reusable only when it validates *and* was written by
  the processor being asked to run now** — `is_chunk_complete` requires
  `validate_chunk_snapshot` to succeed *and* the stamped fingerprint to match.
  Mixing two text conventions in one snapshot is worse than recomputing.
- **The Parquet checkpoint is the whole resumability record.** There is no
  separate "committed" ledger to keep in sync.
- **The processor fingerprint lives in a sidecar** (`chunk-<id>.fingerprint`), not
  in the snapshot schema, so the schema stays exactly what the merger validates.
- **Workers never write the published dataset.** They write
  `{artifacts_root}/transient/document_storage/runs/<run_id>/chunks/`.
  `publish_snapshot` is the only writer of a published snapshot and of the
  pointer.
- **A run is refused when every chunk failed**, measured on `normalized_count`
  rather than row count: a chunk that recorded one failed acquisition still wrote
  a row, so counting rows would let a wholly failed run overwrite a good snapshot
  with a snapshot of failures.
- **A published snapshot is immutable.** `publish_snapshot` raises `MergeError`
  if the snapshot directory exists. Consolidation refuses a re-derived id *before*
  writing anything, because writing first would overwrite an immutable snapshot's
  bytes before the refusal could fire.
- **The pointer is written after the artifact, never before.** A pointer naming a
  snapshot that does not exist is worse than a stale pointer.
- **Snapshot identity is derived from content, not from the merged file.**
  `content_fingerprint` hashes the chunk checkpoints' own digests, because a
  Parquet file is not byte-stable across writes. Consolidation's digest is
  likewise computed over the text being written, not over the part files.
- **Every published snapshot is immediately consolidatable.** `_write_parts`
  projects the assembled artifact into an index part and a payload part, so a
  snapshot does not have to be produced by a previous consolidation to be
  consolidatable.
- **Every locator produces at least one provenance row.** A locator with no
  recorded occurrence gets a synthetic one, and a document that failed to process
  still gets a row — the snapshot records *what happened*, not only what
  succeeded.
- **Source precedence in consolidation is caller order, not filesystem order.**
  Each relation is tagged with its position in the input and dedup ranks on that
  tag descending, so the result depends only on the order the caller listed its
  sources.
- **Fiscal quarters are re-derived at consolidation time,** not stored, so
  snapshots written months apart land in the same partitioning.
- **No document is dropped by an undated filing.** A missing or malformed
  `filing_date`, or a month outside 1–12, buckets as year `0` / `QTR0` rather than
  aborting the `CAST` or deriving a quarter outside `QTR1`–`QTR4`. `QTR0` sorts
  before real quarters, so it is where a reviewer looks first.
- **Text conflicts are refused, not resolved.** If two sources carry *different*
  normalized text for one document, `vacuum_snapshots` raises. Precedence would
  discard one silently, and that is not a decision a consolidation may make on the
  caller's behalf.
- **Sources are immutable and purge is dependency-aware.** Consolidation never
  writes to a source; a source is deleted only when nothing retained still
  references its parts.
- **The exhibit second pass is bounded.** One attempt against an already-held
  bundle and at most one bundle fetch when none is held. An exhibit is addressed
  by the bundle's own `<FILENAME>` when declared, with a synthetic name only as a
  fallback.
- **Workers are sized from cgroup-aware memory, never raw CPU count.**
  `resolved_worker_count` calls
  `auto_worker_count(available_memory_bytes, worker_memory_mib=settings.worker_memory_mib, safety_fraction=settings.worker_memory_safety)`,
  because a worker holds a full filing document in memory. Both budgets come from
  the settings registry (`runtime.worker_memory_mib` = 512,
  `runtime.worker_memory_safety` = 0.9), not from literals here, so an operator who
  sets them is not silently ignored.
- **Concurrency is a process pool, not a thread pool, and children are recycled.**
  `ProcessPoolExecutor(max_workers=resolved, max_tasks_per_child=RECLAIM_INTERVAL)`,
  because the allocation churn of normalizing documents in threads fragments the
  heap past what the container's cgroup allows. `reclaim()` runs every
  `RECLAIM_INTERVAL = 64` documents, after every completed future, and — during
  consolidation — after every batch and every part write.
- **This CLI is fixture-mode by construction.** `mode="fixture"` is hardcoded for
  `run` and `--fixture` is required; a missing or malformed fixture store fails
  before any processing. `documents fill` is the only CLI path that makes live
  requests, and it stores only raw response bytes.
- **No SQL string is interpolated from data.** Every statement in `queries.py` is
  built from a literal in that file, a relation expression that
  `relation_for_parts` quotes itself, and bound parameters. Part paths read from
  manifests are validated before interpolation, so a hand-edited manifest cannot
  become SQL. All consolidation SQL lives in `queries.py` and executes only on
  connections from `infra/storage/duckdb.py`.
- **Batch and byte budgets are registered settings.** `documents.read_batch_size`
  (4096) and `documents.payload_target_bytes` (96 MiB) are the `documents.*`
  group in `foundation/runtime/settings/catalog.py`; the pipeline's
  `queries.DEFAULT_BATCH_SIZE` and `vacuum.DEFAULT_TARGET_BYTES` are the authority
  values for them, pinned by `tests/pipelines/document_storage/test_settings_contract.py`.

**Obligations on callers**

- Supply chunks: a list of chunk ids with locators and occurrences per chunk.
- Do not publish from a worker process, and do not hand-assemble a snapshot from
  chunk files. `validate_chunks` drops an invalid chunk with a *warning* rather
  than failing the merge, so a hand-assembled snapshot would silently lose data.
- Do not treat "no artifact" as "nothing published." Only a *run* snapshot has an
  assembled `documents.parquet`; a consolidated snapshot is a repartitioned part
  tree, so `current_snapshot_artifact` returns `None` for it. Use
  `current_snapshot_dir` to tell them apart.
- Do not read per-document `status` from a consolidated part tree. A document only
  reaches consolidation if it was acquired, so a part tree has nowhere to record
  `failed` or `missing`. Audit failure rates from the per-run snapshots.
- Run from the repository root; `resolve_paths()` treats the working directory as
  the project root and derives a parallel artifacts tree anywhere else.

### Where this package meets AGENTS.md §4

`document_storage` is a pipeline, so §4 binds it. The mapping: the plan is a
caller-supplied chunk-plan JSON (there is no `plan.json` written here — see gaps);
checkpoints are the Parquet chunk files plus a fingerprint sidecar; the coordinator
merge is `publish_snapshot`, which validates every checkpoint, refuses only when
*nothing* is usable, assembles out of core via DuckDB `COPY (... ORDER BY ...)`,
and rejects null or duplicate CIKs. Duplicate *accession* numbers are reportable
fan-out, surfaced as manifest warnings, never a merge failure.

## Public surface

Import from the leaf module; there are no re-exports and no shims.

| Module | Public |
| :--- | :--- |
| `cli.py` | `main` |
| `operator.py` | `run_document_storage`, `make_fetcher`, `new_run_id`, `RunReport`, `OperatorError` |
| `fixture_operator.py` | `fill_fixture`, `list_fixtures`, `validate_fixture_id`, `mime_type_for`, `FixtureFillReport`, `FixtureInfo`, `FixtureOperatorError` |
| `paths.py` | `DocumentStoragePaths`, `chunk_checkpoint_path`, `SNAPSHOT_ARTIFACT_NAME`, `CASES_DIR`, `REVIEW_MANIFEST_NAME`, `EXHIBITS_DATASET`, `EXHIBIT_SNAPSHOT_NAME` |
| `worker.py` | `process_chunk`, `process_chunks`, `is_chunk_complete`, `chunk_fingerprint`, `resolved_worker_count`, `ChunkResult`, `DelegationTarget`, `ChunkError`, `RECLAIM_INTERVAL`, `WORKER_SCHEMA_VERSION` |
| `fetching.py` | `ArchiveFetcher`, `FixtureArchiveFetcher`, `BrokerArchiveFetcher`, `LiveArchiveFetcher`, `make_archive_fetcher` (`fixture`, `live`, `production`, `broker`), `build_broker_fetcher`, `extract_from_sgml_envelope` |
| `processor.py` | `DocumentProcessor`, `FilingProcessor`, `PassThroughProcessor`, `ProcessedDocument`, `count_words`, `PROCESSOR_SCHEMA_VERSION`, `PROCESSOR_FINGERPRINT` (`document-storage-normalizer:v1`), `PASS_THROUGH_FINGERPRINT` (`raw-pass-through`), `REPRESENTATION_RAW` |
| `delegation.py` | `resolve_delegated_exhibit`, `write_exhibit_snapshot`, `exhibits_for`, `DelegatedExhibit`, `REFETCH_ACTION` (`refetch_sub_doc`) |
| `merger.py` | `publish_snapshot`, `validate_chunks`, `content_fingerprint`, `read_pointer`, `current_snapshot_dir`, `current_snapshot_artifact`, `MergeResult`, `SnapshotRef`, `MergeError`, `SNAPSHOT_ARTIFACT_NAME`, `SNAPSHOT_MANIFEST_NAME`, `SNAPSHOT_SCHEMA_VERSION`, `PHASE` (`025_webpage_storage`) |
| `vacuum.py` | `vacuum_snapshots`, `effective_relations`, `quarter_keys`, `validate_payload_conflicts`, `index_part_for`, `QuarterResult`, `VacuumError`, `DEFAULT_TARGET_BYTES` (96 MiB) |
| `queries.py` | `query_sql_batches`, `ranked_union_relations`, `effective_snapshot_relations`, `relation_key_rows`, `relation_payload_conflicts`, `relation_group_keys`, `effective_quarter_batches`, `effective_quarter_index_rows`, `DEFAULT_BATCH_SIZE` (4096) |
| `review.py` | `compare_review_runs`, `load_run_manifest`, `render_summary`, `DocumentDiff`, `ReviewDiffResult`, `ReviewDiffError`, `SUMMARY_NAME` |
| `review_artifacts.py` | `select_review_cases`, `run_review_case`, `write_review_artifacts`, `render_review_run`, `new_review_run_id`, `sanitized_source_html`, `bounded_analysis`, `ReviewSelection`, `ReviewCase`, `ReviewCaseResult`, `ReviewRunResult`, `ReviewArtifactError`, `REVIEW_MANIFEST_NAME`, `CASES_DIR` |

`WORKER_SCHEMA_VERSION` (1) is currently dead: exported and documented, written
nowhere and read nowhere. See "Deliberate gaps".

## Command surface

Entry point: `python run.py documents <command>`, dispatched through `runpy`
straight to `cli.py`. Invoking it with no subcommand opens the phase-local menu
(fill, replay, list fixtures, build review artifacts, compare review runs).
`--help` on the entry point is the authoritative flag list; `USAGE_EPILOG` in
`cli.py` carries worked examples.

| Subcommand | Flags | Exit status |
| :--- | :--- | :--- |
| `run` | `--plan` (**required**), `--fixture` (**required**, repeatable), `--run-id`, `--workers`, `--limit`, `--json` | 0 when `report.ok`, else 1. Prints `plan contains no chunks` on stderr and returns 1 when the plan yields no chunks. |
| `status` | `--json` | 0 when a snapshot is published, else 1. |
| `fill` | `--plan` (**required**), `--fixture` (**required**), `--workers`, `--limit`, `--json` | 0 when no fetch failed, else 1. |
| `fixtures` | `--json` | Always 0. |
| `review-artifacts` | `--fixture` (**required**), `--limit`, `--id` (repeatable), `--ids-file`, `--extension`/`--ext` (repeatable), `--run-id`, `--output`, `--workers`, `--json` | 0 when every selected document rendered, else 1. Non-positive `--limit`/`--workers` returns 2. Refuses a non-empty `--output`. |
| `review` | `--base` (**required**), `--new` (**required**), `--output`, `--json` | 0 when nothing changed, 1 when differences exist (a result, not a failure) or the runs could not be compared. |

`main` resolves paths once through `resolve_paths()`, dispatches through
`_COMMANDS`, and catches `FileNotFoundError`, `ValueError`, and `RuntimeError`,
printing `error: <msg>` to stderr and returning 1.

**Why `--plan` is a path and not a discovery surface.** The plan is a Phase 2
target plan, `filing_catalog` owns it, and Phase 2.5 consumes it without owning
or enumerating it. A sibling-pipeline import or a shared plan-discovery contract
would couple two stages that are separate pipelines by design, so the handoff
stays an explicit artifact path. The fixture side of the same handoff *is*
discovered — the menu lists fixture stores with payload counts — because fixtures
are this package's own artifact.

**Details worth knowing before running**

- `--limit` on `run` truncates the in-memory chunk list, not the plan file. On
  `fill` it caps unique target locators after deduplication.
- `fill` shares one settings-backed SEC HTTP client across fetch threads and one
  coordinator-owned SQLite writer. A locator already in the store is skipped; a
  locator whose fetch failed has no payload row and is eligible for a later fill.
- The fetch result's full SGML source bundle is stored when present, so replay can
  repeat sub-document extraction offline.
- `--run-id` defaults to `new_run_id()` (microsecond stamp plus a random suffix);
  omitting it is safe. `--workers` reaches `resolved_worker_count`, where a
  non-positive value falls through to cgroup-aware derivation.
- `--json` switches from the human summary to a JSON object on every subcommand;
  `run --json` emits `RunReport.to_dict()`.
- When a snapshot is published, `status` reports `shape` as `"run"` if an
  assembled `documents.parquet` exists and `"consolidated"` otherwise, because
  `current` can name either.
- `run` remains offline by design; `fill` is a separate explicit live-acquisition
  operation that shares the SEC client's configured limiter and cache.

## Artifacts

Top-level roots are listed in the root
[README](../../../README.md); every path below is resolved by
[`ProjectPaths`](../../../edgar_sec/foundation/runtime/paths.py), and no module in
this package hardcodes an artifacts directory.

```text
{artifacts_root}/document_storage/
├── snapshots/{snapshot_id}/              published, immutable
│   ├── manifest.json                     required, both shapes
│   ├── documents.parquet                 run snapshots only (assembled artifact)
│   └── parts/index/run.parquet           run snapshots: one metadata part
│       parts/payload/run.parquet         run snapshots: one text part
│   └── parts/index/{year}-{quarter}.parquet      consolidated: one index part per quarter
│       parts/payload/{year}-{quarter}.parquet     consolidated: text parts, byte-budgeted
├── snapshots/current/pointer.json
└── review-runs/{review_run_id}/          durable; a run is compared against a sibling
    ├── review_manifest.jsonl
    └── cases/{document_id}/

{artifacts_root}/transient/document_storage/runs/{run_id}/
└── chunks/
    ├── chunk-{chunk_id}.parquet          resumable checkpoints
    ├── chunk-{chunk_id}.fingerprint      processor identity sidecar
    ├── chunk-{chunk_id}.parquet.tmp      in-progress staging (intra-chunk resume)
    ├── chunk-{chunk_id}.parquet.tmp.delegations.json
    └── chunk-delegated.parquet           exhibit second-pass output
```

A run snapshot's manifest records `snapshot_id`, `dataset`, `phase`
(`025_webpage_storage`), `run_id`, `published_at`, `artifact_name`,
`artifact_file_sha256`, `row_count`, `chunks`, `failed_documents`,
`missing_documents`, `warnings`, `resolved_parts`, `schema_version`,
`source_snapshot_ids`, and `logical_fingerprint`. The snapshot id is
`f"snap-{sha256_text(run_id)[:12]}"` unless an explicit id is passed.

The v2 fixture manifest is `{artifacts_root}/fixtures/<fixture_id>/fixture.manifest.json`,
written atomically after the SQLite writes have committed, and records fixture and
schema identity, a relative database path, timestamps, the payload count, and the
latest fill summary. A writable store creates `fixture_payloads(doc_id, raw_payload)`
for payloads plus `document_blobs` and `fixture_document_forms`; legacy v1
processing tables in an existing database are left untouched and never read.

## Tests

Mirrored tests live under `tests/pipelines/document_storage/`: `test_fetching.py`,
`test_worker.py`, `test_delegation.py`, `test_merger.py`, `test_vacuum.py`,
`test_review.py`, `test_review_artifacts.py`, `test_fixture_operator.py`,
`test_operator_and_cli.py`, and `test_settings_contract.py`. All offline and
deterministic; CLI tests inject a fetcher at the transport seam through
`tests.support` rather than reaching into module internals (AGENTS.md §6.5).

Committed goldens live at `tests/fixtures/document_storage/`:
`annual_10k_html.json` and `annual_10k_normalization.json`. The HTML one exercises
the `<TABLE>` byte-preservation invariant. Both are **synthetic** — see
"Deliberate gaps".

## Deliberate gaps

- **Real-filing parity is unverified.** The only committed goldens are the two
  synthetic ones above. No test here compares output against a real SEC filing, and
  no real historical corpus is committed — `tests/fixtures/archetypes/` does not
  exist. The synthetic goldens pin this pipeline's own behaviour (cover region,
  body anchor, closing span, evaluator verdict, stage order), which catches a
  refactor silently moving a boundary or dropping a stage. They do not establish
  that the normalizer agrees with EDGAR's own output. Do not read the passing suite
  as evidence of real-filing parity.
- **`vacuum_snapshots` has no production caller and no CLI route.** It is
  implemented and tested (`test_vacuum.py`), but `cli.py` registers no `vacuum`
  subcommand and nothing outside the test file calls it, so cross-run
  consolidation is unreachable by an operator. `queries.relation_key_rows` is
  worse: no caller and no test. Both are green in the gate precisely because the
  gate does not check reachability. `vacuum.py:491` also defaults quarter
  concurrency to a hardcoded `1` rather than deriving it from
  `derive_resources()`, even though the function accepts a
  `RuntimeResourceProfile` and ignores it.
- **Checkpoint validation checks column names, not the schema.**
  `validate_chunk_snapshot` compares `schema.names` against
  `DOCUMENT_SNAPSHOT_SCHEMA.names` and nothing else. Arrow **types** are never
  compared, and a checkpoint carries no schema or version marker, so a Parquet
  file with the right column names and wrong types is accepted and reused.
  `WORKER_SCHEMA_VERSION` exists and is exported but is written nowhere. The suite
  has a corrupt-bytes rejection test and a writer-output schema assertion, but no
  test that a wrong-Arrow-type checkpoint is rejected — which is what makes the
  gap invisible.
- **Resume is whole-chunk, then sub-chunk — but only by primary key.**
  `StagedParquetWriter` stages each chunk to a sibling `.tmp` and promotes it with
  an atomic `os.replace` plus directory fsync, so a `.tmp` is never discovered as
  a complete checkpoint. On restart `get_existing_ids()` reads the committed
  `occurrence_id`s and the worker skips those locators, so an interrupt mid-chunk
  no longer discards payloads already staged. Still absent: there is **no
  `retry_failures` path**, so a locator recorded `missing`/`failed` in a
  *completed* checkpoint is never re-attempted — `is_chunk_complete` returns
  `True` and the chunk is skipped wholesale. There is no cross-attempt search
  either: `worker_id` is recorded in `ChunkResult` but never used in a path. A
  `.tmp.delegations.json` sidecar does carry delegation targets across an
  interrupt.
- **Skipped chunks still fabricate their counts.** `is_chunk_complete` returns a
  bare `bool`; `_skipped_result` hardcodes `failed_count=0, missing_count=0`. A
  chunk that was entirely missing or failed is reported to the caller as fully
  normalized.
- **`documents run` has no producer for its `--plan` input.** `_load_plan` /
  `_plan_to_inputs` expect a `{"chunks": [{"locators": [...], "occurrences":
  [...]}]}` JSON document. `filing_catalog` publishes Parquet
  (`targets/form=*/data.parquet`) and no v2 module writes that shape. Until the
  bundle adapter lands, the runnable Phase 2.5 paths are `fill`, `fixtures`,
  `status`, `review-artifacts`, and `review` — and `review-artifacts` is the only
  one that exercises the normalizer end to end from a fixture alone.
- **No test modules for `processor.py` or `queries.py`.** Both are exercised
  through `test_worker.py`, `test_delegation.py`, and `test_vacuum.py`, but
  neither has a mirrored `test_processor.py` or `test_queries.py`, which falls
  short of AGENTS.md §6.3.
- **Review shares nothing with the storage pipeline.** There is no plan, chunk,
  checkpoint, Parquet, or published snapshot on the review path:
  `review-artifacts` reads a fixture directly and `review` compares two review
  runs, so neither depends on a snapshot existing. A review run that could not be
  reproduced from a fixture alone would show what the snapshot did, not what the
  code change did.
- **Review artifacts are not excerpts.** Each case directory holds the *full*
  normalized text, the source bytes verbatim, the structural analysis, and a
  sanitized browser view — no 4,000-character truncation — because a review run is
  compared mechanically and truncation would discard the evidence a diff needs.
- **The per-case `.metadata.json` is gone.** Every field in it also appeared in
  the run manifest, which now carries the provenance the comparison needs:
  `document_id`, `accession`, `document_path`, `form`, `fixture_id`,
  `processor_fingerprint`, `representation`, `source_sha256`,
  `current_output_sha256`. The analysis file is not a second copy of the manifest,
  and v1's `table_count` / `stage_trace_count` substring proxies are gone.
- **A fixture with no per-document form reviews under a manifest-declared one, and
  says so.** Form selects the processing plugin, so a document reviewed under the
  wrong form normalizes differently from the same document in a run. v1's
  fallback (the first entry of the manifest's form list) is reproduced and
  labelled so v2 output stays comparable with the v1 artifacts; `review-artifacts`
  prints one run-level note via `forms_inferred` rather than repeating the caveat
  per document. The committed `fix-99fdcf53` fixture has no
  `fixture_document_forms` table and a 14-entry form list, so its documents review
  as `10-K`.
- **A corrupt or missing payload skips one document, not the run.** It is named in
  `ReviewSelection.failures` and sets a non-zero exit status. Refusing to review
  9,999 sound documents because one is corrupt is the wrong trade.
- **The `documents review` exit status is 1 when differences exist.** That is a
  result, not a failure, and it is what makes the comparison usable from a script.
  It must not be wired into `check.py`.
- **The phase-local menu is intentionally narrow** — fill, replay, list fixtures,
  build review artifacts, compare review runs. Preview, production-mode run,
  partition merge, and vacuum are not reachable from it.
- **v1's SQLite partition architecture was not ported.** The equivalent storage is
  Parquet chunk checkpoints plus a part tree
  (`infra/storage/document_parts.py`) plus manifests and a dependency graph
  (`infra/storage/manifests.py`). Consequently there is **no bounded partition
  reader** here, and no run-status module: `status` is a CLI over a pointer. v1's
  `vacuum.py` responsibility was split three ways rather than ported 1:1 —
  orchestration here, SQL in `queries.py`, identity and dependency tracking in
  `infra/storage/manifests.py` — by layer. Looking for a v1-shaped `vacuum.py` in
  v2 is a mistake, and no v1 symbol is re-exported as an alias; AGENTS.md §1.1
  forbids shims and the `legacy-shims` scanner enforces it.
- **Legacy fixture processing semantics are mostly not ported.** V2 does not
  depend on `_committed_chunks`, acquisition or normalization failure tables,
  normalized rows, or v1 `plan_history`; those tables may remain untouched in old
  fixture databases. The one v1 table v2 *does* depend on is **`document_blobs`** —
  a payload key is a one-way digest, so accession, path, MIME and source hash
  cannot be recovered without it, and the normalizer needs a `DocumentLocator`
  (including its filing form) to run at all. V2 writes it with v1's exact
  six-column shape, so a v1 fixture opens with no migration, and keeps
  per-document forms in the v2-only `fixture_document_forms` so `document_blobs`
  stays shape-compatible. A payload-only fixture is repaired by re-running the same
  fill: `fill_fixture` backfills metadata rows by reading the stored bytes rather
  than re-fetching, so the repair is offline and self-limiting. There is no
  separate migration tool, and `infra/storage/fixture_lineage.py` — which still
  describes legacy plan lineage — is not a gate for fixture replay.
- **No legacy plan/history compatibility gate, and no read-only cache reader.**
  Fill consumes the current v2 target-plan JSON shape and records a portable
  target fingerprint and basename reference; it does not require a v1 plan
  directory or its catalog, policy, seed, forms, or parent-plan lineage fields.
  Separately, `BrokerArchiveFetcher` accepts a `cache_reader` and probes it before
  every socket call, but nothing fabricates one from a directory — a probe that
  silently opened a *writable* cache would move pacing and ledger ownership out of
  the broker. The seam is there and tested with an injected double; the production
  reader is not built.
- **A consolidated quarter's payload parts share one file name.**
  `infra/storage/document_parts.quarter_path` returns
  `parts/payload/{year}-{quarter}.parquet` for *every* planned part in a quarter,
  and `write_payload_part` writes to `part.path` verbatim. A quarter exceeding
  `DEFAULT_TARGET_BYTES` is split by `plan_parts` into several parts that therefore
  resolve to the same path, so each write replaces the previous one and the
  surviving part holds only the last document range — silently, with the manifest
  recording the same path more than once. `plan_parts` splitting is unit-tested,
  but every `vacuum_snapshots` test uses `target_bytes=1024` with tiny documents, so
  no test writes a second payload part for a quarter — which is why the gate is
  green. The defect is in `infra/storage/document_parts.py`; index parts are
  unaffected because `index_part_for` deliberately emits exactly one per quarter.
- **`LiveArchiveFetcher` is not the supported path under a process pool.** Its
  client owns a rate limiter that must stay single-owner, so the broker is the
  supported path there.
- **v1's `defs/sql/` AST layer was deliberately removed, so the `sql-boundary`
  scanner was retired rather than ported.** V2 executes direct SQL and the registry
  holds twelve scanners, none of them `sql-boundary`. `foundation/sql/guard.py`
  does **not** replace it: that module validates operator-typed SQL inside the
  viewer console and returns a string, not a policy. Nothing in the gate inspects
  SQL. The compensating invariant is the convention stated under "Contracts": all
  consolidation SQL lives in `queries.py`, executes only on connections from
  `infra/storage/duckdb.py`, and interpolates no value read from a manifest or a
  row. Do not scatter SQL into `vacuum.py`, and do not read the missing scanner as
  permission to.
