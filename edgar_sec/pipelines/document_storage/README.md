# `edgar_sec/pipelines/document_storage` — Phase 2.5: acquire, normalize, snapshot, consolidate

Fetches primary filing documents, unrolls their SGML envelopes, normalizes them,
resolves exhibits a stub primary delegates to, and publishes immutable snapshots
that can be consolidated across runs. It is the only pipeline in the layer that
normalizes a full document body, and the only one that needs a process pool.

`AGENTS.md` is normative; where this file disagrees with it, this file is wrong.

## Purpose

Phase 1 produced submissions metadata; Phase 2 turned it into a catalog and a
target plan; this package consumes those locators and produces text.

1. **Acquire.** A fetcher returns an accession-scoped view of one response — every
   document it revealed, one of them loaded — plus which source served it, and decides
   nothing about storage. The requested link, the acquired source, and each document's
   content route stay separate: an SGML `<accession>.txt` bundle can deliver an XML
   primary, and a rendered link is served from the archive root under a different
   basename.
2. **Normalize and triage.** A processor takes that acquisition and returns normalized
   text plus a stub/delegation verdict for the one document it selected.
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
| `__init__.py` | Package docstring. No re-exports, per AGENTS.md §1.2. |
| `cli.py` | Subcommand parsing, plan-file ingestion, and the phase-local menu. |
| `operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish. |
| `fixture_operator.py` | Fixture discovery, live raw fill, append/resume, manifest publication. |
| `paths.py` | `DocumentStoragePaths`, the published-vs-transient split, and the artifact-name constants. |
| `worker.py` | Chunk processing, the process pool, the checkpoint-reuse rule. |
| `candidates.py` | The pre-2005 exhibit-candidate gate: filing-date agreement, statutory filename grammar, dynamic form-token rejection. |
| `catalog_plan.py` | Reader for a published `filing_catalog` plan bundle: validation, then replayable streaming chunks. |
| `work_order.py` | `ChunkInput` and the `WorkOrder` seam between an input plan and chunk execution. |
| `fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends. |
| `processor.py` | `FilingProcessor`, `PassThroughProcessor`, the processor fingerprint. |
| `delegation.py` | The exhibit second pass for stub primaries. |
| `merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer. |
| `vacuum.py` | `vacuum_snapshots()`: cross-run consolidation. **Unwired** — no CLI route, no production caller. |
| `queries.py` | The assembly and consolidation SQL. |
| `checkpoint.py` | The chunk-checkpoint schema and its write/validate pair. |
| `parts.py` | Byte-budgeted part planning, the index/payload column contracts, and the part-path boundary checks. |
| `fixture_store.py` | The append-only raw-payload SQLite store behind fixture fill and offline replay. |
| `fixture_lineage.py` | Pure comparison of a fixture manifest against a plan. |
| `review.py` | `compare_review_runs()`: base-vs-new review-run comparison. |
| `review_artifacts.py` | Fixture-backed review artifact generation: selection, per-case files, manifest. |

## Contracts

**Guarantees to callers**

- **A fetcher reports; it never decides.** It never writes a checkpoint, never
  opens a transaction, and never judges a payload good enough. That boundary is
  what lets one fetcher serve a worker, a fixture builder, and the review tool.
- **One response becomes one accession-scoped acquisition.** Direct content and an
  SGML envelope produce the same shape: an ordered `SubmissionDocument` per document the
  response revealed, and exactly one loaded body named by `selected_index`. Only that
  body reaches normalization, so a submission never has to be materialized. Sequence
  numbers and filenames can be absent or duplicated in real envelopes, so the index is
  the only link between a descriptor and its bytes. The descriptors make no
  primary/exhibit claim; see `domain/document/README.md`.
- **The complete envelope is released before normalization.** `FetchResult.source_payload`
  is the only place a whole submission is held, and it survives solely for fixture
  seeding and the delegated-exhibit second pass.
- **Acquisition provenance is in-memory.** Each backend records the URL or fixture key
  that served the bytes on the acquisition. It is not persisted: the snapshot schema
  carries no source column, so a stored row does not record which URL answered it.
- **`FilingProcessor` dispatches on the selected document's content route, not on the
  requested path.** A binary route never reaches the normalizer, which refuses it: the
  payload is stored byte for byte as `raw`, with the suffix's MIME type and an empty
  `normalized_text`. `raw` is the default representation on `ProcessedDocument` and
  means exactly that — no normalized text exists — so `PassThroughProcessor` reports
  empty text as well. The review tool takes the same dispatch, so a reviewer sees what
  the worker would produce.
- **The candidate gate is advisory and has no side effect.** `candidates.py` classifies a
  requested locator against a `2000-01-01 <= filing_date < 2005-01-01` window, the
  Item 601 filename grammar, and the target form's canonical tokens. A positive decision
  changes no fetch candidate, no selected index, no snapshot key, and no payload: it is a
  request worth inspecting, not a claim that the document is displaced. The date comes
  from the locator's occurrence rows, never from the locator or the accession's year; a
  co-filer locator whose occurrences disagree, or whose dates are missing or malformed,
  gets no decision at all.
- **`RunReport` reports candidate counts, and persists none of them.**
  `candidate_eligible_count` and `bundle_candidate_count` count locator work items over
  the whole requested plan — including chunks a resume skipped, whose summary is derived
  from plan inputs rather than from a checkpoint. Co-filer occurrences coalesce onto
  their shared locator, so a locator counts once however many rows reference it.
  `candidate_date_unresolved_count` counts requested locators with no agreed parseable
  filing date, so a fail-closed date reads as a measured condition instead of an
  unexplained zero. The counts reach `ChunkResult`, `RunReport.to_dict()`, and the `run`
  summary; no manifest, checkpoint, or snapshot artifact carries them.
- **A catalog plan bundle is an input mode, validated before anything is fetched.**
  `--catalog-plan` reads a published `filing_catalog` bundle through `catalog_plan.py`,
  which refuses an incomplete bundle, an unsupported `plan_schema_version`, a `plan_id`
  that disagrees with its directory, an unknown scope, a locator-group schema that does
  not match the scope, a missing declared partition, a count that disagrees with its
  partition, a target row with no locator group, a locator group with no target row, and a
  row whose derived locator key or occurrence id does not match its own fields. The
  catalog remains the sole selection authority: storage validates and executes its rows
  and never re-selects, filters, or rewrites a target. `reserve_targets.parquet` holds
  locators withheld from the active set and is never read. An occurrence's `doc_id` is its
  `document_locator_key`, because a catalog plan carries no pre-storage document identity
  and the worker groups occurrences by that key.
- **A catalog run streams and is never resumed.** `work_order.py` defines the seam;
  `CatalogPlan` is replayable and yields at most `runtime.chunk_size` locators per chunk,
  and `process_chunk_stream()` keeps only `resolved_worker_count` chunks in flight, so
  resident work is set by chunk size and concurrency rather than by plan size. Chunk ids
  derive from the plan id, the work-order contract version, the chunk size, and an
  ordinal, so membership and identity do not depend on row arrival or filesystem order;
  a policy bundle's wider locator and target schemas are projected by name and their
  feature columns are ignored. Such a run refuses a run directory that already exists and
  deletes nothing, so an interrupted run keeps its chunks and an operator chooses a new
  run id. The `--plan` JSON mode keeps its existing resume behavior unchanged.
- **A rendered path resolves to its original, with the rendering as fallback.** When
  the route from `domain/document/route.py` is `RENDERED`, all three backends prefer
  the archive-root basename over the XSL rendering, and keep the rendering so a root
  document that does not exist cannot lose a reachable filing. Only the fetched URL
  changes: `document_path` and `document_locator_key` still name the catalog's path,
  so a stored row's key may name the rendering while its bytes are the original. The
  content route follows the *requested* path here, so a root basename ending in `.xml`
  does not turn a rendering into an XML document.
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
  it stores only raw response bytes. Both accept either `--plan` (hand-authored
  JSON) or `--catalog-plan` (a published catalog bundle directory), exclusively.
- **No SQL string is interpolated from data.** Every consolidation statement is
  built from a literal, a self-quoting relation expression, and bound parameters;
  part paths read from manifests are validated before interpolation, so a
  hand-edited manifest cannot become SQL.

**Obligations on callers**

- Supply chunks either as a list of chunk ids with locators and occurrences per
  chunk, or as a replayable `WorkOrder`. The two are exclusive input modes; a work
  order is the fresh-run contract and refuses an existing run directory.
- Implement `DocumentProcessor.process` against an `AcquiredSubmission`, not a raw
  `(bytes, locator)` pair: read the body as `selected_payload` and its route from
  `selected_document`, because the acquired bytes' route is not always the requested
  path's. A processor that re-derives the route from the locator will normalize an SGML
  bundle's XML primary as a text file.
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
- `process_chunks`, `is_chunk_complete`, `resolved_worker_count`, `candidate_summary` —
  chunk execution, checkpoint reuse, and the plan-derived candidate summary that lets a
  resumed chunk report the same counts as a fresh one. `worker.py`.
- `candidate_for`, `occurrence_filing_date`, `primary_form_token_pattern` — the
  pre-2005 exhibit-candidate gate and its two inputs. `candidates.py`.
- `CatalogPlan` — validate a published catalog bundle and read it as replayable
  chunks. `catalog_plan.py`.
- `fill_fixture` — fill a fixture from either a locator sequence or a streamed
  locator source; `verify_fixture_lineage` — check a fixture against a
  selection. `fixture_operator.py`.
- `FilingWork` — one requested locator's pass from catalog row to normalized result.
  `worker.py`.
- `ArchiveFetcher`, `make_archive_fetcher`, `EnvelopeExtraction`,
  `extract_from_sgml_envelope` — the acquisition seam, its fixture / broker / live
  backends, and the envelope scan. `fetching.py`.
- `DocumentProcessor`, `FilingProcessor`, `PassThroughProcessor` — the
  normalization seam over an `AcquiredSubmission`, and the two implementations.
  `processor.py`.
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

The catalog-bundle tests build a real plan in a temporary artifacts root through
the catalog planner, from `tests.support.era_submission_metadata()`. That fixture
copies the committed catalog parquet and appends pre-2005 filings, because the
committed catalog fixture holds only 1999 and 2023-2026 dates and a plan built from
it alone yields no in-window locator — the candidate gate would be untestable
against a credible zero.

## Deliberate gaps

- **Real-filing parity is unverified.** The only committed goldens are the two
  synthetic ones above. No test here compares output against a real SEC filing,
  and no real historical corpus is committed. The synthetic goldens pin this
  pipeline's own behaviour (cover region, body anchor, closing span, evaluator
  verdict, stage order), which catches a refactor silently moving a boundary or
  dropping a stage. They do not establish that the normalizer agrees with EDGAR's
  own output. Do not read the passing suite as evidence of real-filing parity.
- **`fixture_lineage` has no consumer.** The check is called from nothing outside
  its own test, so the guard that stops a plan being replayed against a fixture
  built from a different plan is not wired into the offline fetch path.
- **A row's stored bytes may disagree with the path its key names.** Fetch-time
  resolution deliberately fetches the archive-root original for a rendered path while
  identity still derives from the catalog's `xsl*` path, so `document_locator_key`
  names the rendering. The acquiring fetcher now records which URL served the bytes in
  memory, but no persisted column does, and the document model has not settled how a
  document's authoritative source is represented.
- **Sibling sub-documents are described but never resolved.** An SGML response
  describes every sub-document it holds and loads one, then stops there. A sibling with
  a usable `<TYPE>` is *not* promoted in place of the selected one, and nothing consults
  those descriptors to recover a primary document that a 2000-2004 filer uploaded at
  sequence 1 as an exhibit. Only the existing stub-delegation path acquires a sibling,
  and it re-fetches rather than reading the descriptors already in hand.
- **A candidate count is not a verified inversion.** The gate measures how many requests
  are worth a bundle inspection and classifies them; it opens no bundle, reads no
  `<TYPE>`, and confirms nothing. Nothing persists the per-request decisions, so a count
  cannot be audited back to the documents behind it — re-deriving that population means
  re-running the plan. Any promotion or dual-write needs the resolution contract that
  represents a requested exhibit and a form-matched primary as two references, and that
  does not exist yet.
- **A catalog plan cannot be resumed, and no selection drift is detected.**
  `documents run --catalog-plan` refuses a run directory that already exists, so an
  interrupted catalog run must be retried under a new run id and its partial chunks are
  re-fetched. Nothing fingerprints the bundle's source files, recomputes its published
  selection fingerprint, or records a run manifest, so nothing refuses a resume against a
  changed selection or a changed chunk layout. Reusing checkpoints across runs, and
  publishing a reusable child acquisition plan, both wait on a work-order serialization
  contract that does not exist yet. `--limit` is therefore refused on the catalog mode,
  since a whole plan is the unit of work.
- **Fixture lineage covers only the most recent fill.** A catalog `run` accepts a fixture
  whose `last_fill` names this plan id and this `plan_fingerprint`, and refuses one whose
  last fill names something else. A fixture that was filled from two plans therefore
  cannot be replayed against the second, because only the last fill is recorded; deciding
  what a fixture may still hold after a selection changes needs a manifest-model change.
- **Co-filer fields are read as the catalog's published representative.** A locator
  group carries one `representative_cik` and `archive_url`, chosen deterministically by
  the catalog, and co-filer rows of one document may publish different values: two
  registrants filing the same accession carry their own archive URLs. Storage validates
  only what the locator key implies — document path, canonical accession, and
  `document_path_source` — and takes form and archive URL as published. A disagreement on
  those representative fields is not detected.
- **`document_path_source` is validated but not carried.** A catalog plan distinguishes a
  path taken from the primary document from one falling back to the submission bundle,
  which is the inversion-exception signal, and the reader checks the two agree with the
  locator group. Nothing stores it: `DocumentLocator`, `FilingOccurrence`, and the
  14-column snapshot have nowhere to put it, so its durable representation awaits the
  document-model contract.
- **No filing-scoped view exists.** `AcquiredSubmission` scopes one *response* to one
  accession; it never merges acquisitions, so a filing reached through several requests
  has no aggregate grouping it and a caller cannot ask "everything this filing contains"
  without re-deriving it from accessions and occurrences.
- **A `.paper` row is a pointer, not a document.** Its payload names an off-archive
  Document Control Number that the warehouse cannot resolve, and the bypass keeps only
  that pointer text. The filing's actual content is not retrievable from EDGAR.
- **A binary document is stored verbatim; only its text is missing.** A `.pdf`, `.gif`,
  or `.jpg` bypasses normalization entirely: the payload is stored byte for byte, the
  row reports `raw` with the suffix's MIME type, and `normalized_text` is empty because
  no text form of it exists. What is absent is any *extraction* — nothing reads a PDF's
  content, so a binary filing contributes a stored blob and no searchable text.
- **Parts are planned per quarter, not per snapshot.** `quarter_path` builds a
  path from exactly one year and quarter, so a snapshot spanning several fiscal
  quarters needs one planning call per quarter, and nothing validates that a
  caller passes a coherent pair.
- **`parts.py` overstates its compression story in nothing that matters.** Parts
  are Parquet files using the `zstd` codec through PyArrow; the `zstandard`
  library is not on that path.
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
  `parts.quarter_path` returns
  `parts/payload/{year}-{quarter}.parquet` for *every* planned part in a quarter
  and `write_payload_part` writes to `part.path` verbatim. A quarter exceeding the
  payload byte budget is split into several parts that therefore resolve to the
  same path, so each write replaces the previous one and the surviving part holds
  only the last document range — silently, with the manifest recording the same
  path more than once. Index parts are unaffected because exactly one is emitted
  per quarter. The defect is in `parts.py`.
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
  checkpoints plus a part tree plus manifests (owned by `infra/storage/`) and a
  dependency graph (owned by this package). Consequently there is **no bounded
  partition reader** here and no run-status module: `status` is a CLI over a pointer.
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
  `fixture_lineage.py` is not a gate for fixture replay.
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