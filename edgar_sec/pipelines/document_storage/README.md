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
  [`filing_catalog`](../filing_catalog/README.md), whose published plan bundle
  this package consumes.
- Not an HTTP client owner. It uses `infra/sec_http`, the `infra/broker` socket,
  or a fixture; only `documents fill` makes live requests.
- Not a normalizer owner. `engine/forms/normalize.py` and
  `engine/document/unpacking/unpacker.py` own text conventions and SGML
  structure; this package sequences them and records what they decided.

Real-filing parity is unverified — see "Deliberate gaps".

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Package docstring and the layer-placement rationale. No re-exports, per AGENTS.md §1.2. |
| `cli.py` | Subcommand parsing, plan-file ingestion, and the phase-local menu. |
| `operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish. |
| `fixture_operator.py` | Fixture discovery, live raw fill, append/resume, manifest publication. |
| `paths.py` | `DocumentStoragePaths`, the published-vs-transient split, and the artifact-name constants. |
| `worker.py` | Chunk processing, the process pool, the checkpoint-reuse rule. |
| `fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends. |
| `processor.py` | `FilingProcessor`, `PassThroughProcessor`, the processor fingerprint. |
| `delegation.py` | The exhibit second pass for stub primaries. |
| `merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer. |
| `vacuum.py` | `vacuum_snapshots()`: cross-run consolidation. **Unwired** — no CLI route, no production caller. |
| `queries.py` | The consolidation SQL. |
| `review.py` | `compare_review_runs()`: base-vs-new review-run comparison. |
| `review_artifacts.py` | Fixture-backed review artifact generation: selection, per-case files, manifest. |

## Contracts

**Guarantees to callers**

- **A fetcher reports; it never decides.** It never writes a checkpoint, never
  opens a transaction, and never judges a payload good enough. That boundary is
  what lets one fetcher serve a worker, a fixture builder, and the review tool.
- **A chunk checkpoint is reusable only when it validates *and* was written by
  the processor being asked to run now** — reuse requires both the snapshot
  schema check and a match on the stamped processor fingerprint. Mixing two text
  conventions in one snapshot is worse than recomputing.
- **The Parquet checkpoint is the whole resumability record.** There is no
  separate "committed" ledger to keep in sync.
- **The processor fingerprint lives in a sidecar** (`chunk-<id>.fingerprint`),
  not in the snapshot schema, so the schema stays exactly what the merger
  validates.
- **Workers never write the published dataset.** They write
  `{artifacts_root}/transient/document_storage/runs/<run_id>/chunks/`.
  `publish_snapshot` is the only writer of a published snapshot and of the
  pointer.
- **A run is refused when every chunk failed**, measured on `normalized_count`
  rather than row count: a chunk that recorded one failed acquisition still wrote
  a row, so counting rows would let a wholly failed run overwrite a good snapshot
  with a snapshot of failures.
- **A published snapshot is immutable.** `publish_snapshot` raises `MergeError`
  if the snapshot directory exists, and consolidation refuses a re-derived id
  *before* writing anything, because writing first would overwrite an immutable
  snapshot's bytes before the refusal could fire.
- **The pointer is written after the artifact, never before.** A pointer naming a
  snapshot that does not exist is worse than a stale pointer.
- **Snapshot identity is derived from content, not from the merged file.**
  Consolidation digests the chunks' own text rather than the part files, because
  a Parquet file is not byte-stable across writes.
- **Every published snapshot is immediately consolidatable.** A *run* snapshot
  is published already projected into an index part and a payload part, so it
  does not have to come from an earlier consolidation to be consolidatable.
- **Every locator produces at least one provenance row.** A locator with no
  recorded occurrence gets a synthetic one, and a document that failed to process
  still gets a row — the snapshot records *what happened*, not only what
  succeeded.
- **Source precedence in consolidation is caller order, not filesystem order.**
  Each source is tagged with its position in the input and dedup ranks on that
  tag descending, so the result depends only on the order the caller listed its
  sources.
- **Fiscal quarters are re-derived at consolidation time,** not stored, so
  snapshots written months apart land in the same partitioning.
- **No document is dropped by an undated filing.** A missing or malformed
  `filing_date`, or a month outside 1–12, buckets as year `0` / `QTR0` rather than
  aborting the conversion or deriving a quarter outside `QTR1`–`QTR4`. `QTR0` is
  persisted in the part path and sorts before real quarters, so it is where a
  reviewer looks first.
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
- **Workers are sized from cgroup-aware memory, never raw CPU count**, because a
  worker holds a full filing document in memory. The per-worker budget and safety
  fraction are operator-settable (`runtime.worker_memory_mib`,
  `runtime.worker_memory_safety`), so an operator who changes them is honoured.
- **Concurrency is a process pool, not a thread pool, and children are recycled.**
  Normalizing documents in threads fragments the heap past what the container's
  cgroup allows, so each pool child is retired after a bounded number of tasks and
  `reclaim()` runs on that same interval — after every completed future during a
  run, and after every batch and part write during a consolidation.
- **This CLI is fixture-mode by construction.** `run` is hardcoded to fixture mode
  and requires `--fixture`; a missing or malformed fixture store fails before any
  processing. `documents fill` is the only CLI path that makes live requests, and
  it stores only raw response bytes.
- **No SQL string is interpolated from data.** Every consolidation statement is
  built from a literal, a self-quoting relation expression, and bound parameters;
  part paths read from manifests are validated before interpolation, so a
  hand-edited manifest cannot become SQL.

**Obligations on callers**

- Supply chunks: a list of chunk ids with locators and occurrences per chunk.
- Do not publish from a worker process, and do not hand-assemble a snapshot from
  chunk files. An invalid chunk is dropped with a *warning* rather than failing
  the merge, so a hand-assembled snapshot would silently lose data.
- Do not treat "no artifact" as "nothing published." Only a *run* snapshot has an
  assembled `documents.parquet`; a consolidated snapshot is a repartitioned part
  tree, so `current_snapshot_artifact` returns `None` for it. Use
  `current_snapshot_dir` to tell them apart.
- Do not read per-document `status` from a consolidated part tree. A document only
  reaches consolidation if it was acquired, so a part tree has nowhere to record
  `failed` or `missing`. Audit failure rates from the per-run snapshots.
- Run from the repository root; `resolve_paths()` treats the working directory as
  the project root and derives a parallel artifacts tree anywhere else.

## Public surface

There are no re-exports and no shims; import from the leaf module. The entry
points a caller is expected to use are:

- `run_document_storage` — the one-call publish path from a chunk list plus
  fetcher. `operator.py`.
- `publish_snapshot`, `validate_chunks`, `content_fingerprint`,
  `current_snapshot_dir`, `current_snapshot_artifact` — publication, validation,
  identity, and pointer reads. `merger.py`.
- `vacuum_snapshots` — cross-run consolidation. `vacuum.py`.
- `process_chunks`, `is_chunk_complete`, `resolved_worker_count` — chunk
  execution and checkpoint reuse. `worker.py`.
- `ArchiveFetcher`, `make_archive_fetcher` — the acquisition seam and its
  fixture / broker / live backends. `fetching.py`.
- `DocumentProcessor`, `FilingProcessor`, `PassThroughProcessor` — the
  normalization seam and the two implementations. `processor.py`.
- `resolve_delegated_exhibit`, `exhibits_for` — the exhibit second pass.
  `delegation.py`.
- `fill_fixture`, `list_fixtures` — fixture creation, extension, and discovery.
  `fixture_operator.py`.
- `compare_review_runs`, `write_review_artifacts`, `render_review_run` — the
  review path. `review.py`, `review_artifacts.py`.
- `DocumentStoragePaths` — artifact locations. `paths.py`.

Per-module exports beyond these, including the error classes and the artifact and
schema-version constants, are the owning module's own docstring.

## Command surface

Entry point: `python run.py documents <command>`, dispatched straight to
`cli.py`. Invoking it with no subcommand opens the phase-local menu. `--help` on
the entry point is the authoritative flag list; `USAGE_EPILOG` in `cli.py`
carries worked examples.

| Subcommand | Flags | Exit status |
| :--- | :--- | :--- |
| `run` | `--plan` (**required**), `--fixture` (**required**, repeatable — repeat to set lookup precedence), `--run-id`, `--workers`, `--limit`, `--json` | 0 when `report.ok`, else 1. Prints `plan contains no chunks` on stderr and returns 1 when the plan yields no chunks. |
| `status` | `--json` | 0 when a snapshot is published, else 1. |
| `fill` | `--plan` (**required**), `--fixture` (**required**), `--workers`, `--limit`, `--json` | 0 when no fetch failed, else 1. |
| `fixtures` | `--json` | Always 0. |
| `review-artifacts` | `--fixture` (**required**), `--limit`, `--id` (repeatable), `--ids-file`, `--extension`/`--ext` (repeatable), `--run-id`, `--output`, `--workers`, `--json` | 0 when every selected document rendered, else 1. Non-positive `--limit`/`--workers` returns 2. Refuses a non-empty `--output`. |
| `review` | `--base` (**required**), `--new` (**required**), `--output`, `--json` | 0 when nothing changed, 1 when differences exist (a result, not a failure) or the runs could not be compared. Refuses a non-empty `--output`. |

`main` resolves paths once through `resolve_paths()`, dispatches through
`_COMMANDS`, and catches `FileNotFoundError`, `ValueError`, and `RuntimeError`,
printing `error: <msg>` to stderr and returning 1. This is the only pipeline whose
CLI exposes no `--artifacts` flag; it is bound to the configured project root in
a way the other two are not.

**Details worth knowing before running**

- `--plan` is a path, not a discovery surface: it names a Phase 2 plan bundle
  directly. The fixture side of the same handoff *is* discovered — the menu lists
  fixture stores with payload counts — because fixtures are this package's own
  artifact.
- `--limit` on `run` truncates the in-memory chunk list, not the plan file. On
  `fill` it caps unique target locators after deduplication.
- `fill` shares one settings-backed SEC HTTP client across fetch threads and one
  coordinator-owned writer. A locator already in the store is skipped; a locator
  whose fetch failed has no payload row and is eligible for a later fill. The full
  SGML source bundle is stored when present, so replay can repeat sub-document
  extraction offline.
- `--run-id` defaults to a generated stamp, so omitting it is safe. `--workers`
  reaches `resolved_worker_count`, where a non-positive value falls through to
  cgroup-aware derivation.
- `--json` switches from the human summary to a JSON object on every subcommand.
- When a snapshot is published, `status` reports `shape` as `"run"` if an
  assembled `documents.parquet` exists and `"consolidated"` otherwise, because
  `current` can name either.
- The menu is intentionally narrow: fill, replay, list fixtures, build review
  artifacts, compare review runs. Preview, production-mode run, partition merge,
  and vacuum are not reachable from it.

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
`source_snapshot_ids`, and `logical_fingerprint`. Snapshot identity is derived
from the run id unless an explicit id is passed (`merger.publish_snapshot`).

A review run's manifest carries the provenance the comparison needs per document:
`document_id`, `accession`, `document_path`, `form`, `fixture_id`,
`processor_fingerprint`, `representation`, `source_sha256`, and
`current_output_sha256`.

The fixture manifest is `{artifacts_root}/fixtures/<fixture_id>/fixture.manifest.json`,
written atomically after the SQLite writes have committed, and records fixture and
schema identity, a relative database path, timestamps, the payload count, and the
latest fill summary. A writable store creates `fixture_payloads(doc_id, raw_payload)`
for payloads plus `document_blobs` and `fixture_document_forms`; superseded
processing tables in an existing database are left untouched and never read.

## Mirrored tests

Mirrored tests live under `tests/pipelines/document_storage/`, one per source
module per AGENTS.md §6. All offline and deterministic; CLI tests inject a fetcher
at the transport seam through `tests.support` rather than reaching into module
internals (AGENTS.md §6.5).

Committed goldens live at `tests/fixtures/document_storage/`:
`annual_10k_html.json` (which exercises the `<TABLE>` byte-preservation
invariant) and `annual_10k_normalization.json`. Both are **synthetic** — see
"Deliberate gaps".

## Deliberate gaps

- **Real-filing parity is unverified.** The only committed goldens are the two
  synthetic ones above. No test here compares output against a real SEC filing,
  and no real historical corpus is committed. The synthetic goldens pin this
  pipeline's own behaviour (cover region, body anchor, closing span, evaluator
  verdict, stage order), which catches a refactor silently moving a boundary or
  dropping a stage. They do not establish that the normalizer agrees with EDGAR's
  own output. Do not read the passing suite as evidence of real-filing parity.
- **`vacuum_snapshots` has no production caller and no CLI route.** It is
  implemented and tested, but `cli.py` registers no `vacuum` subcommand and nothing
  outside its test module calls it, so cross-run consolidation is unreachable by an
  operator. Its quarter concurrency is also a hardcoded `1` rather than a value
  derived from `derive_resources()`: the function accepts a
  `RuntimeResourceProfile` and threads it through to its DuckDB connections, but
  not to the concurrency decision.
- **`documents run` has no producer for its `--plan` input.** The CLI expects a
  `{"chunks": [{"locators": [...], "occurrences": [...]}]}` JSON document;
  `filing_catalog` publishes a Parquet plan bundle (`locator_groups.parquet` plus
  `targets/form=*/data.parquet`) and no module in this repository writes that
  shape. Until a bundle adapter lands, the runnable paths here are `fill`,
  `fixtures`, `status`, `review-artifacts`, and `review` — and `review-artifacts`
  is the only one that exercises the normalizer end to end from a fixture alone.
- **No incremental or partial publication.** `publish_snapshot` requires at least
  one usable chunk, drops an invalid chunk with a manifest *warning* rather than
  failing the merge, and refuses to overwrite an existing snapshot id. A snapshot
  published from a partly-failed run is therefore a complete artifact over the
  chunks that were usable — read its `warnings` and `failed_documents` fields
  before trusting its row count.
- **Checkpoint validation checks column names, not the schema.**
  `validate_chunk_snapshot` compares `schema.names` against the snapshot schema's
  names and nothing else. Arrow **types** are never compared and a checkpoint
  carries no version marker, so a Parquet file with the right column names and
  wrong types is accepted and reused. The suite has a corrupt-bytes rejection test
  and a writer-output schema assertion, but nothing that pins rejection of a
  wrong-typed checkpoint.
- **Resume is whole-chunk, then sub-chunk — but only by primary key.** Each chunk
  is staged to a sibling `.tmp` and promoted with an atomic `os.replace` plus
  directory fsync, so a `.tmp` is never discovered as a complete checkpoint. On
  restart the committed `occurrence_id`s are read and the worker skips those
  locators, so an interrupt mid-chunk no longer discards payloads already staged.
  Still absent: there is **no `retry_failures` path**, so a locator recorded
  `missing`/`failed` in a *completed* checkpoint is never re-attempted — the chunk
  is skipped wholesale. A locator recorded `failed` therefore stays failed for the
  life of that checkpoint.
- **Skipped chunks still fabricate their counts.** A reused chunk is reported with
  `failed_count=0, missing_count=0`, so a chunk that was entirely missing or failed
  is reported to the caller as fully normalized.
- **A consolidated quarter's payload parts share one file name.**
  `infra/storage/document_parts.quarter_path` returns
  `parts/payload/{year}-{quarter}.parquet` for *every* planned part in a quarter
  and `write_payload_part` writes to `part.path` verbatim. A quarter exceeding the
  payload byte budget is split into several parts that therefore resolve to the
  same path, so each write replaces the previous one and the surviving part holds
  only the last document range — silently, with the manifest recording the same
  path more than once. Index parts are unaffected because exactly one is emitted
  per quarter. The defect is in `infra/storage/document_parts.py`.
- **Review shares nothing with the storage pipeline.** There is no plan, chunk,
  checkpoint, Parquet, or published snapshot on the review path:
  `review-artifacts` reads a fixture directly and `review` compares two review
  runs, so neither depends on a snapshot existing. A review run that could not be
  reproduced from a fixture alone would show what the snapshot did, not what the
  code change did.
- **Review artifacts are not excerpts.** Each case directory holds the *full*
  normalized text, the source bytes verbatim, the structural analysis, and a
  sanitized browser view — no truncation — because a review run is compared
  mechanically and truncation would discard the evidence a diff needs.
- **Review artifacts carry no per-case `.metadata.json`.** The run manifest
  carries the provenance the comparison needs, and a second copy in a per-document
  file would only have to be diffed alongside it. For the same reason the analysis
  file is not a copy of the manifest, and no substring proxies are derived from the
  source.
- **A fixture with no per-document form reviews under a manifest-declared one, and
  says so.** Form selects the processing plugin, so a document reviewed under the
  wrong form normalizes differently from the same document in a run. The
  manifest-declared fallback (the first entry of the manifest's form list) is
  reproduced and labelled so review output stays comparable with the artifacts it
  replaces; `review-artifacts` prints one run-level note via `forms_inferred` rather
  than repeating the caveat per document.
- **A corrupt or missing payload skips one document, not the run.** It is named in
  the selection failures and sets a non-zero exit status. Refusing to review sound
  documents because one is corrupt is the wrong trade.
- **The `documents review` exit status must not be wired into `check.py`.** A
  non-zero status on a difference is a result a reviewer reads, and what makes the
  comparison usable from a script.
- **There is no SQLite partition architecture.** Storage is Parquet chunk
  checkpoints plus a part tree plus manifests and a dependency graph (all owned by
  `infra/storage/`). Consequently there is **no bounded partition reader** here and
  no run-status module: `status` is a CLI over a pointer.
- **Legacy fixture processing semantics are mostly not read.** This pipeline does
  not depend on `_committed_chunks`, acquisition or normalization failure tables,
  normalized rows, or legacy `plan_history`; those tables may remain untouched in
  older fixture databases. The one legacy table it *does* depend on is
  **`document_blobs`** — a payload key is a one-way digest, so accession, path,
  MIME and source hash cannot be recovered without it, and the normalizer needs a
  `DocumentLocator` (including its filing form) to run at all. A payload-only
  fixture is repaired by re-running the same fill: `fill_fixture` backfills
  metadata rows by reading the stored bytes rather than re-fetching, so the repair
  is offline and self-limiting. There is no separate migration tool, and
  `infra/storage/fixture_lineage.py` is not a gate for fixture replay.
- **There is no legacy plan/history compatibility gate, and no read-only cache
  reader.** Fill consumes the current target-plan JSON shape and records a portable
  target fingerprint and basename reference; it does not require a historical plan
  directory or its catalog, policy, seed, forms, or parent-plan lineage fields.
  Separately, `BrokerArchiveFetcher` accepts a `cache_reader` and probes it before
  every socket call, but nothing fabricates one from a directory — a probe that
  silently opened a *writable* cache would move pacing and ledger ownership out of
  the broker. The seam is there and tested with an injected double; the production
  reader is not built.
- **`LiveArchiveFetcher` is not the supported path under a process pool.** Its
  client owns a rate limiter that must stay single-owner, so the broker is the
  supported path there.