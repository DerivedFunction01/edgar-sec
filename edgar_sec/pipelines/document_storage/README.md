# `edgar_sec/pipelines/document_storage` — Phase 2.5: acquire, normalize, snapshot, consolidate

This package fetches primary filing documents, unrolls their SGML envelopes,
normalizes them, resolves exhibits that a stub primary delegates to, and
publishes immutable snapshots that can be consolidated across runs. It is the
only pipeline in the layer that normalizes a full document body, and the only
one that needs a process pool.

## Purpose

Phase 2.5 is where the corpus itself is built. Phase 1 produced submissions
metadata; Phase 2 turned it into a catalog and a target plan; this package
consumes those locators and produces text.

Four things happen, in this order, and the order is load-bearing:

1. **Acquire.** A fetcher returns raw bytes for one document locator and decides
   nothing about storage (`fetching.py:19-22`).
2. **Normalize and triage.** A processor turns raw bytes into normalized text
   plus a stub/delegation verdict (`processor.py`).
3. **Resolve delegations.** A stub primary that incorporates its substance from
   an exhibit gets that exhibit fetched and recorded alongside it
   (`delegation.py`).
4. **Publish, then consolidate.** Per-run snapshots merge into one canonical
   snapshot (`merger.py`, `vacuum.py`).

What this package is not:

- Not the phase that decides *which* documents to fetch. That is
  `filing_catalog/planner.py`; this package consumes the plan.
- Not an HTTP client. It uses `infra/sec_http` or the `infra/broker` socket, and
its document-run CLI replays fixtures; a separate `fill` command acquires raw
bytes into those fixtures through the shared SEC HTTP client.
- Not a normalizer owner. `engine/forms/normalize.py` and
  `engine/document/unpacker.py` own text conventions and SGML structure; this
  package sequences them and records what they decided.

**Why this package sits in Layer 4 rather than Layer 2.** Its fetchers call
`engine.document.unpacker` to select a sub-document out of an SGML envelope, and
a fetcher that has to call the engine cannot live below it. The raw fixture store
it reads *is* infrastructure and stays in `infra/storage/fixture_store.py`
(`__init__.py:3-6`).

Status: **IMPLEMENTED, with fixture fill/replay available and M6.3/M6.4 deferred** (`roadmap/refactor_v2/
phase_2_5.md:4`). See "Deliberate gaps" — real-filing parity is unverified.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (7 loc); states the Layer 4 placement rationale. No re-exports, per AGENTS.md §1.2. |
| `cli.py` | `run` / `status` / `review` and plan-file ingestion (231 loc). |
| `operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish (updated loc). |
| `fixture_operator.py` | Fixture discovery, live raw fill, append/resume, and v2 manifest publication. |
| `worker.py` | Chunk processing, the process pool, and the checkpoint-reuse rule (498 loc). |
| `fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends (442 loc). |
| `processor.py` | `FilingProcessor`, `PassThroughProcessor`, and the processor fingerprint (231 loc). |
| `delegation.py` | The exhibit second pass for stub primaries (282 loc). |
| `merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer (403 loc). |
| `vacuum.py` | `vacuum_snapshots()`: cross-run consolidation into one canonical snapshot (564 loc). |
| `queries.py` | The direct SQL for consolidation; the only module that holds it (263 loc). |
| `review.py` | `compare_review_runs()`: base-vs-new review-run comparison (322 loc). |
| `review_artifacts.py` | Fixture-backed review artifact generation: selection, per-case files, manifest (545 loc). |

Total 4,100+ lines across 12 files: 11 modules plus a 7-line `__init__.py`
docstring.

## Contracts

**Guarantees this package makes to its callers**

- **A fetcher reports; it never decides.** It reports what happened and never
  writes a checkpoint, never opens a transaction, and never decides a payload is
  good enough. "Keeping that boundary sharp is what lets the same fetcher serve a
  worker, a fixture builder, and the review tool" (`fetching.py:19-22`).
- **A chunk checkpoint is complete only when it validates *and* was written by the
  processor being asked to run now.** `is_chunk_complete` requires
  `validate_chunk_snapshot` to succeed *and* the stamped fingerprint to match.
  "Reusing a chunk normalized by a different processor would silently mix two
  text conventions in one snapshot, which is worse than recomputing"
  (`worker.py:109-130`).
- **The Parquet file is the whole resumability record.** "There is no separate
  'committed' ledger to keep in sync, because the Parquet file *is* the record"
  (`worker.py:5-7`).
- **The processor fingerprint lives in a sidecar, not in the snapshot schema.**
  It is written to `chunk-<id>.fingerprint` so the snapshot's own schema stays
  exactly the contract the merger validates
  (`worker.py:337-345`).
- **Workers never write the published dataset.** They write
  `transient/document_storage/runs/<run_id>/chunks/chunk-<id>.parquet`.
  `publish_snapshot` is the only writer of a published snapshot, and it is the
  only writer of the pointer.
- **A run is refused when every chunk failed.** `run_document_storage` raises
  `OperatorError` when every chunk failed *and* nothing was normalized, measured
  on `normalized_count` rather than row count: "a chunk that recorded one failed
  acquisition still wrote a row, so counting rows would report a wholly failed
  run as a successful one and let it overwrite a good snapshot with a snapshot
  of nothing but failures" (`operator.py:252-260`).
- **A published snapshot is immutable.** `publish_snapshot` raises `MergeError`
  when the snapshot directory already exists, because "republishing under the
  same id would rewrite an identity other records already reference"
  (`merger.py:306-311`). Consolidation likewise refuses a re-derived id *before*
  writing anything, "because writing parts first would overwrite an immutable
  snapshot's bytes before the refusal could fire" (`vacuum.py:472-480`).
- **The pointer is written after the artifact, never before.** "A pointer naming
  a snapshot that does not exist is worse than a stale pointer, because a reader
  following it finds a missing dataset instead of an older one"
  (`merger.py:1-12, 250-262`).
- **Snapshot identity is derived from content, not from the merged file.**
  `content_fingerprint` hashes the chunk checkpoints' own digests, because
  "a Parquet file is not byte-stable across writes — the writer embeds metadata
  that varies" (`merger.py:188-206`). Consolidation's digest is likewise
  computed over the text being written, not over the part files
  (`vacuum.py:338-380`).
- **Every published snapshot is immediately consolidatable.** `_write_parts`
  projects the assembled artifact into an index part and a payload part, so
  "every published snapshot is immediately consolidatable, rather than only the
  ones a previous consolidation happened to produce" (`merger.py:101-107`).
- **Source precedence in consolidation is caller order, not filesystem order.**
  Each relation is tagged with its position in the input and every dedup ranks
  on that tag descending, so "the result of a consolidation depends only on the
  order the caller listed its sources" (`queries.py:59-73`).
- **Fiscal quarters are re-derived at consolidation time,** not stored, so
  snapshots written months apart by different code versions land in the same
  partitioning (`queries.py:76-99`).
- **No document is dropped by an undated filing.** A missing or malformed
  `filing_date`, or a month outside 1-12, buckets as year `0` / quarter `QTR0`
  rather than aborting the `CAST` or deriving a quarter outside `QTR1`-`QTR4`.
  "Both are reportable states, so neither drops a document" and `QTR0` sorts
  before real quarters, "so it is where a reviewer looks first"
  (`queries.py:86-99`).
- **Text conflicts are refused, not resolved.** If two sources carry *different*
  normalized text for the same document, `vacuum_snapshots` raises.
  "Precedence would happily discard one; silently accepting that a document's
  text changed is not a decision a consolidation may make on the caller's
  behalf" (`vacuum.py:19-21`, `163-179`).
- **Sources are immutable and purge is dependency-aware.** Consolidation never
  writes to a source. A source may only be deleted when nothing retained still
  references its parts, which `expand_dependency_closure` determines before
  anything is removed (`vacuum.py:23-26, 420-438`).
- **Workers are sized from cgroup-aware memory, never raw CPU count.**
  `resolved_worker_count` calls
  `auto_worker_count(resolved.available_memory_bytes, worker_memory_mib=512,
  safety_fraction=0.9)` (`worker.py:360-373`), because "a worker holds a full
  filing document in memory".
- **Concurrency is a process pool, not a thread pool, and children are
  recycled.** `ProcessPoolExecutor(max_workers=resolved,
  max_tasks_per_child=RECLAIM_INTERVAL)` — because "the allocation churn of doing
  that in threads fragments the heap past what the container's cgroup allows"
  (`worker.py:9-13, 457-459`).
- **Heap is reclaimed at bounded intervals.** `reclaim()` runs every
  `RECLAIM_INTERVAL = 64` documents (`worker.py:241-242`) and after every
  completed future (`worker.py:462`); consolidation calls it after every batch
  and every part write (`vacuum.py:250, 292, 379`).
- **The fetcher ships by value.** `FixtureArchiveFetcher`, `BrokerArchiveFetcher`,
  and `LiveArchiveFetcher` each define `__getstate__`/`__setstate__`, so the pool
  boundary is the only place picklability is enforced and it is tested there
  (`fetching.py:9-17, 150-157, 230-245, 327-339`).
- **The exhibit second pass is bounded.** One attempt against an already-held
  bundle, and at most one bundle fetch when none is held. "An unbounded retry
  loop here would turn one bad document into a network stall"
  (`delegation.py:8-11, 122-198`).
- **An exhibit is addressed by the bundle's own `<FILENAME>`** when the bundle
  declares one, "because that is the name the document is actually stored under;
  a synthetic name is only a fallback for a bundle that omits it"
  (`delegation.py:12-15, 112-119`).
- **This CLI is fixture-mode by construction.** `mode="fixture"` is hardcoded and
  `--fixture` is required for `run`; missing or malformed fixture stores fail
  before processing. The distinct `fill` action is the only CLI path that makes
  live requests, and it stores only raw response bytes. `--fixture` may be
  repeated for replay; lookups honor the supplied order, so the first store with
  a matching locator key wins.
- **Review selection is stratified by outcome, not sampled.** Strata are filled
  in the order `failed`, `missing`, `empty_text`, `ok`, and within a stratum
  documents are taken in `document_locator_key` order, "so two runs over the same
  snapshot render the same set, which is what makes a review diffable"
  (`review.py:187-221`). A uniform sample of a 99.9%-clean corpus shows only
  clean documents (`review.py:9-13`).
- **No SQL string is interpolated from data.** Every statement in `queries.py` is
  assembled from a literal in that file, a relation expression that
  `relation_for_parts` builds with its own quoting, and bound parameters. "No
  value read from a manifest or a row is ever interpolated into a statement,
  which is what keeps a hand-edited manifest from becoming SQL"
  (`queries.py:8-13`). Part paths from manifests are validated before
  interpolation for the same reason (`vacuum.py:128-131`).

**Obligations callers place on this package**

- Supply chunks. A run is a list of chunk ids with locators and occurrences per
  chunk; a chunk id that carries neither still produces a synthetic provenance
  row rather than being dropped (`worker.py:290-329`).
- Do not publish from a worker process, and do not hand-assemble a snapshot from
  chunk files. `validate_chunks` drops an invalid chunk with a *warning* rather
  than failing the merge, so a hand-assembled snapshot would silently lose data
  (`merger.py:79-98`).
- Do not treat "no artifact" as "nothing published." Only a *run* snapshot has an
  assembled `documents.parquet`; a consolidated snapshot is a repartitioned part
  tree, so `current_snapshot_artifact` returns `None` for it. Use
  `current_snapshot_dir` to tell them apart (`merger.py:376-388`).
- Do not interpret a document's `status` from a consolidated part tree. A part
  tree records no per-document status, "because a document only reaches
  consolidation if it was acquired" — the review reader reports `"ok"`
  unconditionally for that shape (`review.py:160-165`).
- Do not expect a `form` column in a run snapshot's review bundles. A document's
  form lives on its catalog occurrence, not on the stored artifact, so review
  "cannot stratify by form and does not pretend to" (`review.py:100-104`).
- Run from the repository root. The CLI resolves paths once through
  `resolve_paths()`.

## Public surface

- `main` — the `python run.py documents` entry point. `cli.py`.
- `run_document_storage` — the full run: chunks, delegation, publish; returns a
  `RunReport`. `operator.py`.
- `make_fetcher` — resolve a run's fetcher from its mode, with repository paths
  resolved. `operator.py`.
- `new_run_id` — a sortable, unique run identity: microsecond stamp plus a short
  random suffix, because "a collision would make the second run look like a
  republication of the first". `operator.py`.
- `RunReport` — `run_id`, `chunks`, `merge`, `exhibits`, `started_at`,
  `finished_at`, with `snapshot_id`, `artifact_path`, `ok`, `total_documents`,
  `failed_documents`, and `to_dict()`. `operator.py`.
- `OperatorError`. `operator.py`.
- `fill_fixture`, `list_fixtures`, `FixtureFillReport`, `FixtureInfo`,
  `FixtureOperatorError`. `fixture_operator.py`.
- `process_chunk` — fetch and normalize one chunk, publishing it as a Parquet
  checkpoint; `payload_sink` is the fixture-builder hook. `worker.py`.
- `process_chunks` — process every chunk not already published, returning all
  results in order, with skipped chunks reconstructed from their checkpoints.
  `worker.py`.
- `is_chunk_complete` — the validate-and-fingerprint reuse rule. `worker.py`.
- `chunk_checkpoint_path`, `chunk_fingerprint` — checkpoint path and stamped
  processor identity. `worker.py`.
- `resolved_worker_count` — cgroup-aware worker sizing. `worker.py`.
- `ChunkResult` — frozen slotted dataclass: `chunk_id`, `worker_id`,
  `output_path`, `document_count`, `normalized_count`, `failed_count`,
  `missing_count`, `occurrences`, `processor_fingerprint`, `payload_sha256`,
  `delegations`, and the `ok` property. `worker.py`.
- `DelegationTarget` — a stub decision a worker observed, for the delegation pass
  to resolve; only the *identity* of the target travels. `worker.py`.
- `ChunkError`, `RECLAIM_INTERVAL` (64), `WORKER_SCHEMA_VERSION` (1).
  `worker.py`.
- `ArchiveFetcher` — the runtime-checkable protocol every backend satisfies.
  `fetching.py`.
- `FixtureArchiveFetcher` — offline; reads content-addressed payloads from one or
  more fixture stores, opening connections per process. `fetching.py`.
- `BrokerArchiveFetcher` — routes through the broker socket with an optional
  read-only warm-cache probe in front; only cache misses traverse the socket.
  `fetching.py`.
- `LiveArchiveFetcher` — direct HTTP through a caller-supplied client; the
  in-process path. `fetching.py`.
- `make_archive_fetcher` — construct the configured backend; accepts `fixture`,
  `live`, `production`, or `broker`. `fetching.py`.
- `build_broker_fetcher` — the broker backend with an optional cache probe.
  `fetching.py`.
- `extract_from_sgml_envelope` — select the target sub-document from an SGML
  envelope, returning `(payload, source_bundle)`; the bundle is carried so a
  second pass can resolve in-bundle exhibits without a refetch. `fetching.py`.
- `DocumentProcessor` — the protocol: `process(raw_bytes, locator) ->
  ProcessedDocument`. `processor.py`.
- `FilingProcessor` — normalize, then ask the form's evaluator whether the
  result is self-contained or a stub delegating to an exhibit.
  `processor.py`.
- `PassThroughProcessor` — store the payload unprocessed. `processor.py`.
- `ProcessedDocument` — `document_locator_key`, `payload`, `byte_size`,
  `mime_type`, `representation`, `processor_fingerprint`, `metadata`, `decision`,
  with `text`, `word_count`, and `normalized_payload_sha256` properties.
  `processor.py`.
- `count_words`, `PROCESSOR_SCHEMA_VERSION` (1), `PROCESSOR_FINGERPRINT`
  (`document-storage-normalizer:v1`), `PASS_THROUGH_FINGERPRINT`
  (`raw-pass-through`), `REPRESENTATION_RAW`. `processor.py`.
- `resolve_delegated_exhibit` — resolve and process the exhibit a stub decision
  delegated to; returns `None` when the decision is not a refetch, names no
  exhibit, or the exhibit is unresolvable inside the one-fetch budget.
  `delegation.py`.
- `write_exhibit_snapshot` — publish resolved exhibits as a Parquet file with
  the chunk schema, so a later merge needs no separate reader. `delegation.py`.
- `exhibits_for` — the exhibits delegated to by one primary. `delegation.py`.
- `DelegatedExhibit` — carries the primary's accession, CIK, and form "because
  publishing the exhibit needs them to build a provenance row and re-deriving
  them from free-form metadata would make the snapshot's correctness depend on
  dict key spelling". `delegation.py`.
- `REFETCH_ACTION` (`"refetch_sub_doc"`). `delegation.py`.
- `publish_snapshot` — merge a run's chunks into an immutable snapshot and
  publish it. `merger.py`.
- `validate_chunks` — split chunk paths into usable and warned-about.
  `merger.py`.
- `content_fingerprint` — a stable content identity for a snapshot built from
  these chunks. `merger.py`.
- `read_pointer`, `current_snapshot_dir`, `current_snapshot_artifact` — the
  pointer readers. `merger.py`.
- `MergeResult`, `SnapshotRef`, `MergeError`, `SNAPSHOT_ARTIFACT_NAME`
  (`"documents.parquet"`), `SNAPSHOT_MANIFEST_NAME` (`"manifest.json"`),
  `SNAPSHOT_SCHEMA_VERSION` (`"1"`), `PHASE` (`"025_webpage_storage"`).
  `merger.py`.
- `vacuum_snapshots` — consolidate snapshots into one canonical snapshot;
  returns the published manifest. `vacuum.py`.
- `effective_relations` — the deduplicated index and payload relations for a
  consolidation. `vacuum.py`.
- `quarter_keys` — every fiscal quarter present in the effective index.
  `vacuum.py`.
- `validate_payload_conflicts` — raise when two sources disagree about a
  document's normalized text. `vacuum.py`.
- `index_part_for` — the single index part covering one quarter. `vacuum.py`.
- `QuarterResult`, `VacuumError`, `DEFAULT_TARGET_BYTES` (96 MiB).
  `vacuum.py`.
- `query_sql_batches` — the DuckDB adapter, using `fetchmany` "rather than
  materializing the result, because the payload queries here carry full document
  text". `queries.py`.
- `ranked_union_relations`, `effective_snapshot_relations` — precedence-tagged
  union and the deduplicated relations. `queries.py`.
- `relation_key_rows`, `relation_payload_conflicts`, `relation_group_keys`,
  `effective_quarter_batches`, `effective_quarter_index_rows` — the batched
  readers. `queries.py`.
- `DEFAULT_BATCH_SIZE` (4096) — "bounded so a consolidation never materializes a
  whole quarter's text in memory at once". `queries.py`.
- `select_review_cases` — load the documents one run will process, in document-id
  order, verifying every payload against its recorded hash.
  `review_artifacts.py`.
- `run_review_case` — normalize one document exactly as a pipeline worker does.
  `review_artifacts.py`.
- `write_review_artifacts` — write one case directory: `.txt`, `.source.txt`,
  `.analysis.json`, and `.html` for HTML inputs. `review_artifacts.py`.
- `render_review_run` — process the selection and write the run manifest.
  `review_artifacts.py`.
- `sanitized_source_html`, `bounded_analysis` — the two renderers.
  `review_artifacts.py`.
- `compare_review_runs` — diff two review runs into per-document patches.
  `review.py`.
- `load_run_manifest` — read a run's manifest, keyed by document id. `review.py`.
- `render_summary` — the human-readable comparison report. `review.py`.
- `ReviewArtifactError`, `ReviewDiffError`, `ReviewSelection`, `ReviewCase`,
  `ReviewCaseResult`, `ReviewRunResult`, `DocumentDiff`, `ReviewDiffResult`,
  `REVIEW_MANIFEST_NAME`, `CASES_DIR`, `SUMMARY_NAME`. Across both modules.

## Commands

Entry point: `python run.py documents <command>`, dispatched through `runpy`
directly to `edgar_sec/pipelines/document_storage/cli.py`. Invoking the document
entry without a subcommand opens its phase-local fixture menu.

```bash
python run.py documents status
python run.py documents run --plan corpus.json --fixture fix-001
python run.py documents run --plan corpus.json --fixture fix-a --fixture fix-b
python run.py documents fill --plan corpus.json --fixture fix-001 --workers 4
python run.py documents fixtures
python run.py documents review-artifacts --fixture fix-001 --limit 100
python run.py documents review --base <run-a> --new <run-b>
```

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `run` | `--plan` (**required**, chunk plan JSON path), `--fixture` (**required**, fixture id), `--run-id`, `--workers` (int), `--limit` (int), `--json` | 0 when `report.ok`, else **1**. Returns 1 with `plan contains no chunks` on stderr when the plan yields no chunks. |
| `status` | `--json` | 0 when a snapshot is published, else **1** (`cli.py:176`). |
| `review-artifacts` | `--fixture` (**required**), `--limit` (int), `--id` (repeatable), `--ids-file` (path), `--extension`/`--ext` (repeatable), `--run-id`, `--output` (path), `--workers` (int), `--json` | Renders one review run from a fixture. **0** when every selected document rendered, else **1**. Refuses a non-empty `--output`. Prints one note when documents were reviewed under a manifest-declared form. |
| `review` | `--base` (**required**), `--new` (**required**), `--output` (path), `--json` | Compares two review runs. **0** when nothing changed, **1** when differences exist (a result, not a failure) or when the runs could not be compared. |
| `fill` | `--plan` (**required**, target plan JSON), `--fixture` (**required**), `--workers`, `--limit` (locator count), `--json` | Fetch missing locators; stores successful raw bytes and exits 1 when any fetch failed. |
| `fixtures` | `--json` | Lists fixture IDs, readable payload counts, and manifest status. |

`main` resolves paths once through `resolve_paths()`, dispatches through
`_COMMANDS`, and catches `FileNotFoundError`, `ValueError`, and `RuntimeError`,
printing `error: <msg>` to stderr and returning 1 (`cli.py:211-228`).

`--plan` is required by `run` and `fill`, and the interactive menu still asks for
that path. This is an explicit artifact handoff, not a missing discovery surface:
the plan is a Phase 2 target plan, `filing_catalog` owns it, and Phase 2.5 consumes
it without owning or enumerating it. A sibling-pipeline import or a shared
plan-discovery contract would couple the two stages that are separate pipelines by
design, so the path stays. The fixture side of the same prompt *is* discovered —
the menu lists fixture stores with their payload counts — because fixtures are
this package's own artifact.

Details worth knowing before running:

- `--limit` on `run` truncates the chunk list for a smoke run, not the plan file
  (`cli.py:84-86`).
- `--limit` on `fill` caps unique target locators. Existing rows are skipped;
  failed/missing rows have no fixture payload and are eligible for another fill.
- A fill shares one settings-backed SEC HTTP client across fetch threads and uses
  one coordinator-owned SQLite writer. The fetch result's full SGML source bundle
  is stored when present, preserving replay extraction behavior.
- Fixture paths are `{artifacts_root}/fixtures/{fixture_id}/fixture.sqlite` and
  the sibling `fixture.manifest.json`. New stores contain only
  `fixture_payloads(doc_id, raw_payload)`; existing legacy processing tables are
  left untouched and are never read by v2.
- The v2 manifest records fixture/schema identity, relative database path,
  timestamps, payload count, and the latest fill summary. It is atomically
  replaced after the SQLite writes have committed; plan history and legacy
  catalog/policy compatibility fields are not required for replay.
- `--run-id` defaults to `new_run_id()`; omitting it is safe, because the id is
  microsecond-stamped and randomly suffixed.
- `--workers` is passed to `resolved_worker_count`, where a non-positive value
  falls through to cgroup-aware derivation.
- `--json` on any subcommand switches from the human summary to a JSON object;
  `run --json` emits `RunReport.to_dict()`.
- `run` remains offline by design. `fill` is a separate explicit live-acquisition
  operation and shares the SEC client's configured limiter/cache.
- `_plan_to_inputs` builds `DocumentLocator` and `FilingOccurrence` objects from
  the plan's `chunks` array, defaulting a missing `chunk_id` to
  `f"c{index:05d}"` (`cli.py:73-110`).

`documents status` reports `shape` as `"run"` when an assembled
`documents.parquet` exists and `"consolidated"` otherwise, because `current` can
name either (`cli.py:157-162`).

## Resumability and publication

### Artifact layout

```text
{artifacts_root}/document_storage/
├── snapshots/{snapshot_id}/          published, immutable
│   ├── documents.parquet             run snapshots only (assembled artifact)
│   ├── manifest.json                 required
│   └── parts/
│       ├── index/run.parquet         (part-kind tree: metadata)
│       └── payload/run.parquet       (part-kind tree: text)
├── snapshots/current/pointer.json
└── fixtures/{fixture_id}/                   offline raw-payload store
    ├── fixture.sqlite                      fixture_payloads(doc_id, raw_payload)
    └── fixture.manifest.json

{artifacts_root}/transient/document_storage/runs/{run_id}/
├── chunks/chunk-{chunk_id}.parquet          resumable checkpoints
├── chunks/chunk-{chunk_id}.fingerprint      processor identity sidecar
├── chunks/chunk-delegated.parquet           exhibit second-pass output
└── review/                                  review bundles
```

`ProjectPaths` owns every one of these paths (`foundation/runtime/paths.py:78-130`);
no module in this package contains an `.artifacts` literal.

### Per-run lifecycle

1. **Chunk check.** For each chunk, `is_chunk_complete` validates the Parquet
   and compares the fingerprint sidecar. A reusable chunk contributes a
   reconstructed `ChunkResult` with `worker_id="skipped"`
   (`worker.py:415-423, 467-483`).
2. **Fetch, process, write.** `process_chunk` deduplicates locators by
   content-addressed key while preserving order (`_unique_locators`,
   `worker.py:133-149`), fetches each, and processes it. A fetch that does not
   return `ok` becomes a `missing` count; a processing exception becomes a
   `failed` count and is caught, because "one bad document is not a bad chunk"
   (`worker.py:216-225`). Locators are deduplicated so "fetching it twice would
   double the cost and produce two rows for one document".
3. **Expand occurrences.** Every locator produces at least one provenance row: a
   locator with no recorded occurrence gets a synthetic one, and a document that
   failed to process still gets a row, because "the snapshot records *what
   happened*, not only what succeeded" (`worker.py:290-308`).
4. **Write and stamp.** `write_chunk_snapshot` writes the Parquet;
   `_stamp_fingerprint` writes the sidecar.
5. **Dispatch.** With a `payload_sink` (the fixture builder) or a resolved worker
   count of 1, chunks run inline in the parent; otherwise they go to a
   `ProcessPoolExecutor` with `max_tasks_per_child=64` (`worker.py:437-464`).

### Delegation sits between the chunks and the merge

The operator runs the exhibit second pass *after* the workers and *before*
publication, because its output is itself a chunk: "an exhibit resolved from a
stub must be merged into the same snapshot as its primary, or the snapshot would
claim a filing is complete when its substance sits in an unpublished file"
(`operator.py:12-16`).

The pass is driven by the workers' own `DelegationTarget` reports rather than by
re-triage, "so a primary is fetched and normalized exactly once per run"
(`operator.py:271-274`). The operator wraps each report in a `_StubDecision` —
a minimal stand-in carrying only `decision_action` and `target_exhibit` — so the
delegation pass does not re-run the evaluator and a full processed document never
enters the inter-stage contract (`operator.py:305-319`). Resolved exhibits are
written to `chunk-delegated.parquet` with the chunk schema, and the next
`publish_snapshot` picks it up because the glob is `chunk-*.parquet`
(`merger.py:294`).

### Publication

`publish_snapshot` globs `chunk-*.parquet`, splits them into usable and warned
via `validate_chunks`, and raises `MergeError` only when *nothing* is usable —
"losing one chunk is recoverable and visible; refusing to publish because of it
would also block the chunks that are fine" (`merger.py:79-98, 298-302`).

It then assembles the usable chunks into `documents.parquet` through
`infra/storage/document_parquet.assemble_document_snapshots`, an out-of-core
DuckDB `COPY (SELECT * FROM read_parquet([...]) ORDER BY source_cik, accession)`
into a PID-suffixed temporary file that is `os.replace`d into place
(`merger.py:317`; `infra/storage/document_parquet.py:166-196`). It counts
`failed` and `missing` statuses, digests the artifact for
`artifact_file_sha256`, computes `content_fingerprint` over the *chunks*, writes
the index and payload parts, writes the manifest into a `.staging-` directory
under the snapshots root, and `os.replace`s staging into the snapshot directory.
On any exception the staging directory is removed. Only after all of that does
`_publish_pointer` move `current` (`merger.py:313-340`).

The manifest records `snapshot_id`, `dataset`, `phase` (`025_webpage_storage`),
`run_id`, `published_at`, `artifact_name`, `artifact_file_sha256`,
`row_count`, `chunks`, `failed_documents`, `missing_documents`, `warnings`,
`resolved_parts`, `schema_version`, `source_snapshot_ids`, and
`logical_fingerprint`.

Snapshot id is `f"snap-{sha256_text(run_id)[:12]}"` unless an explicit id is
passed (`merger.py:304`).

### Consolidation across runs

A corpus is built by many partial runs, each publishing its own snapshot. Reading
them as N independent datasets means "every consumer has to union, dedupe, and
re-derive fiscal quarters itself — and get the same answers" (`vacuum.py:3-6`).
Consolidation does that once, into one canonical snapshot.

`vacuum_snapshots` in order:

1. resolves source manifests (explicit ids, or every published snapshot);
2. optionally expands the dependency closure, or refuses the purge while any
   retained snapshot references a source part;
3. builds per-source ranked union relations, validating part paths before
   interpolation;
4. opens a validation connection, refuses conflicting normalized text, and lists
   the fiscal quarters — **all before anything is written**;
5. derives the deterministic physical id from the operation name, the source ids,
   the sources' logical fingerprints, and the schema versions, and refuses if
   that id already has a manifest;
6. materializes each quarter in its own thread with its own connection — pass 1
   reads index metadata and releases each batch before planning, so "the planner
   never holds text"; pass 2 plans payload parts by document byte size and
   streams one doc range per part;
7. sorts parts by path, hashes the per-quarter digests into
   `logical_fingerprint`, writes the manifest with `set_current=True`, and
   removes the target directory if any step raised;
8. purges sources when asked, skipping the physical id itself.

Quarters run on a `ThreadPoolExecutor` over shared relations with a per-quarter
connection: "DuckDB releases the GIL during execution, so this overlaps real
work, and each quarter's memory is bounded by the batch size rather than by the
corpus size" (`vacuum.py:28-31`).

Index rows are one part per quarter, not byte-budgeted: "index rows are metadata:
roughly an order of magnitude smaller than the text they point at, so
byte-budgeting them would split a quarter's index across parts for no read
benefit" (`vacuum.py:198-213`).

## Tests

- `tests/pipelines/document_storage/test_fetching.py` (427 loc, 36 tests) — the
  three backends, SGML extraction, and the pickle boundary.
- `tests/pipelines/document_storage/test_worker.py` (550 loc, 31) — chunk
  processing, occurrence expansion, the reuse rule, worker sizing.
- `tests/pipelines/document_storage/test_delegation.py` (307 loc, 16) — the
  exhibit second pass and its one-fetch budget.
- `tests/pipelines/document_storage/test_merger.py` (292 loc, 15) — publication,
  immutability, pointer ordering.
- `tests/pipelines/document_storage/test_vacuum.py` (730 loc, 37) — consolidation,
  precedence, conflict refusal, purge.
- `tests/pipelines/document_storage/test_review.py` (314 loc, 18) — both snapshot
  shapes, stratification, determinism.
- `tests/pipelines/document_storage/test_operator_and_cli.py` (466 loc, 27) —
  run orchestration and every CLI subcommand and exit code.

3,086 lines total, offline and deterministic. The CLI tests inject a fetcher at
the transport seam through `tests.support` rather than reaching into module
internals (AGENTS.md §6.5).

Committed goldens live at `tests/fixtures/document_storage/`:
`annual_10k_html.json` and `annual_10k_normalization.json`. The HTML one
exercises the `<TABLE>` byte-preservation invariant. Both are **synthetic** —
see "Deliberate gaps".

## Deliberate gaps

- **M6.3, M6.4, and M6.5 are deferred: real-filing parity is unverified.** The
  only committed goldens are two synthetic ones,
  `tests/fixtures/document_storage/annual_10k_html.json` and
  `annual_10k_normalization.json`. There is no test in this package that compares
  its output against a real SEC filing, and no committed corpus of real
  historical filings exists. M6.3 (real fixtures in
  `tests/fixtures/archetypes/`) is deferred "until a sanitization and licensing
  decision is made"; M6.4 (golden comparison against promoted real-filing
  outputs) depends on it; M6.5 (golden coverage for real filings) waits on it
  too (`roadmap/refactor_v2/phase_2_5.md:263-265`). What the synthetic goldens
  *do* pin is this pipeline's own behaviour: the cover region, body anchor,
  closing span, evaluator verdict, and stage order. They catch a refactor
  silently moving a boundary, dropping a stage, or changing an evaluator's
  conclusion — offline, deterministically. They do not establish that the
  normalizer agrees with EDGAR's own output. Do not read the passing suite as
  evidence of real-filing parity.
- **v1's `core/vacuum.py` (449 loc) was split across three v2 modules, not ported
  1:1.** The responsibility landed in `document_storage/vacuum.py` (564 loc,
  orchestration and the manifest),
  `document_storage/queries.py` (263 loc, all the SQL), and
  `infra/storage/manifests.py` (321 loc, snapshot identity, manifest
  publication, the `current` pointer, and the dependency graph). The division is
  by layer: SQL is a consolidation concern, manifest identity and dependency
  tracking are infrastructure that `filing_catalog` and any future dataset can
  share. There is no v1-shaped `vacuum.py` in v2, and looking for one is a
  mistake.
- **v1's `core/chunk_worker.py` (483 loc) and `core/chunk_persistence.py`
  (481 loc) both map onto the single v2 `worker.py` (498 loc).** Two v1 files,
  one v2 module, and the v2 module is smaller than the pair. v1 persisted chunk
  state in SQLite through the `defs.sql` AST; v2 writes Parquet checkpoints and
  keeps the processor fingerprint in a sidecar. The two v1 files are not
  reachable by any v2 import path.
- **v1's `core/exhibit_second_pass.py` (280 loc) became
  `document_storage/delegation.py` (282 loc) under renamed symbols.** The
  function `resolve_delegated_exhibit` and the dataclass `DelegatedExhibit`
  replace v1's naming, and the v1 names are not re-exported as aliases — AGENTS.md
  §1.1 forbids compatibility shims, and the `legacy-shims` scanner enforces it.
- **v1's SQLite partition architecture was not ported.** v1 had
  `snapshot.py` (664 loc), `snapshot_merge.py` (485), `partition_merger.py`
  (341), `partition_reader.py` (226), `partition_handoff.py` (143),
  `chunk_cache.py` (135), `records.py` (187), `run_status.py` (115), and
  `targets.py` (203). v2 has none of these modules. The equivalent storage is
  Parquet chunk checkpoints plus a part tree (`infra/storage/document_parts.py`)
  plus manifests (`infra/storage/manifests.py`). Consequently there is **no
  bounded partition reader** in this package and no run-status module: `status`
  is a CLI over a pointer. Review no longer reads a published snapshot at all:
  `review-artifacts` reads a fixture directly and `review` compares two review
  runs, so neither depends on a snapshot existing.
- **Legacy fixture processing semantics are mostly not ported.** Raw
  fill/replay is implemented by `fixture_operator.py` and
  `infra/storage/fixture_store.py`. V2 does not depend on `_committed_chunks`,
  acquisition or normalization failure tables, normalized rows, or v1
  `plan_history`; these tables may remain untouched in old fixture databases.
  The one v1 table v2 *does* depend on is **`document_blobs`** — a payload key is
  a one-way digest, so accession, path, MIME and source hash cannot be recovered
  without it, and the normalizer needs a `DocumentLocator` (including its filing
  form) to run at all. v2 writes that table with v1's exact six-column shape, so
  a fixture recorded by v1 opens with no migration. `fill_fixture` also writes
  per-document forms to `fixture_document_forms`, a v2-only table that keeps
  `document_blobs` shape-compatible; when it is absent, review falls back to the
  manifest. The pure `fixture_lineage.py` helper still describes legacy plan
  lineage and is not a gate for fixture replay.
- **A payload-only fixture is repaired by re-running the same fill.**
  `fill_fixture` backfills metadata for documents that have a payload but no
  metadata row, reading the stored bytes rather than re-fetching, so the repair
  is offline and self-limiting. There is no separate migration tool.
- **v1's `defs/sql/` AST layer was deliberately removed, so the `sql-boundary`
  scanner was retired rather than ported.** v2 executes direct SQL. The AGENTS.md
  scanner list registers eleven scanners and `sql-boundary` is not among them.
  The compensating invariant is a convention: **all consolidation SQL lives in
  `document_storage/queries.py` and executes only on connections from
  `infra/storage/duckdb.py`** (`queries.py:1-16`). Do not scatter SQL into
  `vacuum.py`, and do not read the missing scanner as permission to.
- **No legacy plan/history compatibility gate.** Fill consumes the current v2
  target-plan JSON shape accepted by the document CLI. It records a portable
  target fingerprint/reference but does not require a v1 plan directory or its
  catalog, policy, seed, forms, or parent-plan lineage fields.
- **No read-only cache reader in v2.** `BrokerArchiveFetcher` accepts a
  `cache_reader` and probes it before every socket call, but the fetcher does not
  fabricate one from a directory: "v2 has no read-only cache reader yet, so this
  does not fabricate one from a directory — a probe that silently opened a
  *writable* cache would move pacing and ledger ownership out of the broker"
  (`fetching.py:388-403`). The seam is there and tested with an injected double;
  the production reader is not built.
- **`LiveArchiveFetcher` is not the supported path under a process pool.** Its own
  docstring says so: the client "owns a rate limiter that must stay
  single-owner", so the broker is the supported path there
  (`fetching.py:14-17, 313-320`).
- **No test modules for `processor.py` or `queries.py`.** Both are exercised
  through `test_worker.py`, `test_delegation.py`, and `test_vacuum.py`, but
  neither has a mirrored `tests/pipelines/document_storage/test_processor.py` or
  `test_queries.py`, which falls short of AGENTS.md §6.3.
- **A consolidated snapshot records no per-document status.** Documents only
  reach consolidation if they were acquired, so the part tree has nowhere to
  record `failed` or `missing` and the review reader reports `"ok"`
  unconditionally for that shape (`review.py:160-165`). A reviewer auditing
  failure rates must read the per-run snapshots, not the consolidated one.
- **Review artifacts are not excerpts.** Each case directory holds the *full*
  normalized text, the source bytes verbatim, the structural analysis, and a
  sanitized browser view. The old snapshot-bundle command truncated to 4,000
  characters so fifty bundles stayed readable in an editor; a review run is
  compared mechanically, so truncation would have thrown away exactly the
  evidence a diff needs.
- **Page-artifact analysis is not reproduced.** v1's `.analysis.json` carried
  `page_artifacts`, `artifacts`, `header_footer_templates`, `regions`,
  `page_boundaries`, `occupied_lines`, `page_number_runs`, `inferred_boundaries`,
  `rejection_diagnostics`, `source_identity`, and `coordinate_frame`. v2's
  `PageMarkerAnalysis` has six fields and renames `unresolved` to
  `unresolved_candidates`, so the v2 analysis file is a strict subset. The
  missing fields belonged to `PageArtifactPolicy.ANNOTATE`, which the engine
  README already records as having no distinct behaviour; re-adding an engine
  field to serialize evidence of a mode that does nothing is not a gap worth
  closing. v1's `table_count` and `stage_trace_count` are also gone — they
  duplicated the analysis, and `table_count` was a substring count of `<table`
  in the source, which was a proxy for quality only while the normalizer was
  incomplete.
- **The per-case `.metadata.json` is gone.** Every field in it also appeared in
  the run manifest, so it was a second copy of the same facts in a second file
  that had to be diffed alongside the manifest. The manifest now carries the
  provenance the comparison needs: `document_id`, `accession`, `document_path`,
  `form`, `fixture_id`, `processor_fingerprint`, `representation`,
  `source_sha256`, `current_output_sha256`.
- **A fixture with no per-document form reviews under a manifest-declared one,
  and says so.** The form selects the processing plugin, so this is a caveat the
  reviewer must see. `documents review-artifacts` prints one run-level note
  rather than repeating the caveat per document. The recorded
  `fix-99fdcf53` fixture has no per-document forms, so its documents are
  reviewed as `10-K` (the first entry of a 14-form manifest) — v1's fallback,
  reproduced so v2 output stays comparable with the v1 reference artifacts.
- **A corrupt or missing payload skips one document, not the run.** It is named
  in `ReviewSelection.failures` and sets a non-zero exit status, so it is
  reported rather than hidden. Refusing to review 9,999 sound documents because
  one is corrupt is the wrong trade for a 10,000-document fixture.
- **The `documents review` exit status is 1 when differences exist.** That is a
  result, not a failure, and it is what makes the comparison usable from a
  script. It must not be wired into `check.py`.
- **The phase-local menu is intentionally narrow.** It offers fixture fill,
  fixture replay, fixture listing, review-artifact generation, and review-run
  comparison. V1 preview, production-mode run, partition merge, and vacuum are
  not restored by this fixture correction.
- **No settings registry, and no phase-local specs.** The pipeline takes worker
  count, batch size, and part byte budget as function arguments defaulting to
  literals in this package (`DEFAULT_TARGET_BYTES`, `queries.DEFAULT_BATCH_SIZE`),
  and reads nothing from `edgar_sec/foundation/runtime/settings/`. This is the
  one place in Layer 4 where AGENTS.md §3.1's "new phases register their own spec
  dictionaries" is not honoured: `DEFAULT_TARGET_BYTES` and `DEFAULT_BATCH_SIZE`
  are module constants, not `SettingSpec`s, so neither is env-overridable. They
  are also not resource *allocations* in the `resource-allocation` scanner's
  sense, which is why the scanner is silent about them.
