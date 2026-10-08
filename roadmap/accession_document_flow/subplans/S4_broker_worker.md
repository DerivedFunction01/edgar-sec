# S4 — Broker-Backed Inventory Worker and Bounded Process Pool

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S4**.
- Status: bounded worker coordination, chunk checkpoints, per-accession transactional
  progress/resume, retry, run locking, and cooperative cancellation are implemented.
  S5's production builder creates the work order, invokes S4, and consumes its committed
  attempts. An offline progress/RSS scale simulation has passed; no durable run report is
  tracked, and live SEC workload behavior remains unverified.
- Depends on: S1 cohort contract, S2 index fixture store, and S3 typed contract.
- S7b review artifacts support S3 parser iteration; S0 runs alongside it and supplies
  final parser/resource evidence.
- Non-blocking for S4 implementation: S5 snapshot writer can be developed against
  synthetic typed outcomes and later consumes S4's stream.

## Objective

Execute one accession per process-pool task: fetch its `-index.html` through the
shared SEC broker, parse it, and return a typed outcome. The coordinator persists
validated, resumable Parquet chunks under the transient inventory run; S5 reads those
chunks to build and publish the canonical snapshot.

## Discovery boundary

S4 is strictly an index discovery and parsing engine:

- S4 fetches and parses `-index.html` pages for unindexed accessions.
- S4 **never** synthesizes `InventoryEntry` rows from catalog hints or filing
  summaries. Entries are strictly factual rows observed in `Document Format Files`
  or `Data Files`.
- S4 does not infer form capability rules or bypass decisions. If an explicit
  catalog-direct target path is used in S6, it operates as an independent planning
  source adapter outside of S4.

## Contract: `SecBrokerClient`

The only HTTP seam visible to workers. Injected by the coordinator; workers never
instantiate their own `SecHttpClient`.

```python
class SecBrokerClient:
    def fetch_index(
        self, accession: AccessionNumber, index_url: str
    ) -> IndexPageEnvelope | IndexFetchFailure: ...

@dataclass(frozen=True, slots=True)
class IndexFetchFailure:
    accession: AccessionNumber
    code: Literal["fetch_failed"]
    detail: str
```

`IndexPageEnvelope` carries `accession`, `index_url`, `response_size`, and
`html_bytes`; S3 computes the digest from those exact bytes. The broker owns the
settings-backed `SecHttpClient`, its cache, rate limiter, retries, and failure
ledger. Its existing cache peek occurs before network I/O and rate-slot acquisition.
The broker's rate limiter is authoritative for SEC requests; the process pool only
scales CPU work and shares that limiter. Broker retry policy is infra-owned; a final
broker failure is terminal for that page attempt; explicit `--retry-failures` starts a
new chunk attempt for the failed accession rather than adding a second HTTP retry loop.

## Worker lifecycle and IPC memory

1. S5 validates the cohort and base snapshot, anti-joins known accessions, then writes
   the sorted, unique missing work order to transient Parquet. S4 validates its schema,
   sorted uniqueness, row count, and streaming digest before the first request and
   starts one `SecBroker`/`managed_broker` for the run. The complete work order is never
   converted to an in-memory sequence.
2. Read the work-order Parquet incrementally and form deterministic chunks bounded by
   the resolved runtime chunk size. A chunk ID depends on the work-order version,
   ordinal, and that chunk's membership digest, not task completion order. Submit one
   accession per process-pool task; only a worker-budget-sized in-flight window is
   retained.
3. Each worker fetches through `SecBrokerClient`, then parses
   `parse_html_index(IndexPageInput(accession, index_url, html_bytes))`. It returns one
typed parse outcome or typed fetch/worker failure. Raw HTML stays in the process and
    never crosses production IPC. A task exception is typed `worker_error`, never an empty
    result.
4. The coordinator processes one deterministic chunk at a time, transactionally
   persists each complete parse result to the temporary progress journal, and
   immediately refills each freed worker slot. After every chunk member has a terminal
   result, it exports the journal to the paired transient Parquet attempt.
   There is one outcome row per accession, including recognized-empty and failed
   outcomes; entry rows preserve every parsed source row. The handoff retains paths and
   bounded batches, not the cohort or all parsed rows in Python memory.
5. S4 yields a committed chunk reference to S5. S5 streams its rows into separate
   publication staging, externally sorts them, validates the complete cohort, and is
   the only owner of immutable snapshot publication. A fetch/worker/parse refusal never
   becomes an empty inventory.

```python
def process_accession(item, broker) -> IndexParseOutcome | IndexFetchFailure | IndexWorkerFailure:
    page = broker.fetch_index(item.accession, item.index_url)
    if isinstance(page, IndexFetchFailure):
        return page
    return parse_html_index(
        IndexPageInput(item.accession, item.index_url, page.html_bytes)
    )

def run_missing_accessions(work_order_path, run_identity, paths) -> Iterator[ChunkRef]:
    validate_or_create_run_manifest(run_identity, work_order_path, paths)
    for chunk in deterministic_chunks_from_parquet(work_order_path):
        if checkpoint_is_valid(chunk, paths):
            yield current_chunk_ref(chunk, paths)
            continue
        progress = open_or_validate_progress(chunk, paths)
        results = process_bounded_accession_tasks(
            missing_members(chunk, progress), stop_requested
        )
        for result in results:
            record_complete_result_transactionally(progress, result)
            if stop_requested():
                return cancelled_summary()
        attempt = export_progress_to_parquet(progress)
        yield commit_parquet_attempt(chunk, attempt, paths)
```

The coordinator catches process-task exceptions and converts them to a typed worker
failure for the assigned accession so one future cannot erase sibling results. The
pseudocode omits the per-run lock, resume-validation predicates, and typed manifest
contents described below.

## Transient paths and run identity

Add `edgar_sec/pipelines/document_inventory/paths.py`, owned by this pipeline. It wraps
`ProjectPaths.artifacts_root` and shared `current_pointer_path()` /
`transient_dir()` helpers; it does not add inventory-specific properties to the
foundation path object or reuse frozen `DocumentStoragePaths`. S2 fixture paths use
the shared foundation fixture resolver.

```text
{artifacts_root}/document_inventory/snapshots/...
{artifacts_root}/transient/document_inventory/{run_id}/
  run_manifest.json
  work_order.parquet
  chunks/chunk-000000/current.json
  chunks/chunk-000000/progress/current.json
  chunks/chunk-000000/progress/progress-<attempt_id>.duckdb
  chunks/chunk-000000/attempt-<attempt_id>/
    outcomes.parquet
    entries.parquet
    manifest.json
  publication/                         # S5-owned staging
```

The path object exposes validated path methods for the run lock, run manifest, run/chunk
directories, attempt outputs/manifests, the committed-attempt pointer, the progress
pointer/database, and S5's publication staging directory. Run, chunk, and attempt IDs
are single safe path components; no method accepts an arbitrary relative path.
Published snapshot paths remain separate from transient run state.

Only one coordinator may own a run directory at a time; its lock is acquired before
manifest/checkpoint reads and writes. Different run IDs remain concurrent. Stale-lock
recovery is explicit, never inferred from an age-based timeout.

S5 supplies a stable run intent ID binding the parent snapshot, canonical cohort/source
identity, parser and schema versions, refresh mode, and exact missing-accession
worklist; that intent ID is the `run_id` path component. S4's atomic run manifest pins
the work-order Parquet digest and row count, work-order version, resolved chunk size,
outcome/entry/progress-store schema versions, fetch mode, and fixture identity when applicable. It does not
duplicate the accession list or store a list of every chunk identity; per-chunk manifests
pin bounded chunk membership. Worker count, cache location, and other machine-local
resource choices are excluded: they may change across resume without changing logical
work. An existing run ID with a missing, malformed, or mismatched manifest is refused
before any request.

## Parquet checkpoint and resume contract

- Each attempt contains `outcomes.parquet` (exactly one terminal result per input
  accession) and `entries.parquet` (zero or more rows per successfully parsed page).
  The former distinguishes parsed-empty, unrecognized, parse-failure, fetch-failure,
  and worker-failure outcomes; the latter preserves all `InventoryEntry` rows. Parser
  diagnostics remain in the outcome data for run inspection and are not a fourth
  canonical snapshot relation.
- Write with the repository's zstd/128,000-row-group Parquet defaults. Validate both
  schemas, row counts, unique outcome accessions, exact chunk membership, entry-parent
  membership, and file digests before committing.
- An attempt's manifest is written atomically after both Parquet files validate. The
  chunk's `current.json` pointer is then atomically advanced to that attempt. The
  pointer is the commit marker; temporary/orphan attempts without a valid manifest
  and pointer are never reusable.
- Resume first requires an exact run-manifest match. For each deterministic chunk,
  validate the pointed attempt's manifest, schema versions, parser fingerprint,
  membership digest, row counts, and Parquet digests. Reuse only an exact valid match;
  recompute a missing or invalid committed attempt as a whole. A crash before pointer
  advancement leaves the prior committed attempt intact, if one exists.
- A separate temporary progress journal supports recovery inside an incomplete chunk.
  The coordinator writes one complete worker parse result as one transaction: its one
  outcome, all its entry rows, and its completion marker commit together. It must not
  mark an accession complete while entry rows from that parse are still being written.
  Parquet remains the immutable chunk output; do not create one Parquet file per
  accession. The progress store is coordinator-owned, configured DuckDB staging, and
  is compacted to the paired attempt Parquet files after every work-order member has a
  terminal result.
- The journal contains run/chunk/attempt metadata, a terminal-outcome relation, an
  entry relation, and a completed-accession relation. One parent-owned DuckDB
  transaction inserts all rows from a single worker result into the outcome and entry
  relations and then its completion key. Only committed completion keys participate in
  resume. Export to Parquet reads these relations after the chunk is complete; it does
  not expose uncommitted entry batches.
- A progress journal is reusable only when its run ID, attempt ID, work-order version,
  chunk ID, exact membership digest/count, parser version, and outcome/entry schema
  and progress-store version match. An atomic per-chunk progress pointer names the
  active progress database; committed-attempt `current.json` remains a separate pointer.
  Resume anti-joins the expected chunk membership against completed progress rows in
  DuckDB and fetches only the missing accessions. An unreadable,
  mismatched, or structurally inconsistent journal is discarded and the incomplete
  chunk is recomputed; partial row groups are never treated as completed parses.
- Fetch and worker failures are persisted as typed outcomes, so a resumed run does not
  repeatedly hit the same failed page by default. `--retry-failures` makes a new
  immutable attempt only for chunks containing retryable fetch/worker failures; it
  reuses successful accession outcomes and retries only those failed accessions. The
  same per-parse transaction boundary applies to the retry progress journal. The new
  pointer advances only after complete validation. Unrecognized pages and parser
  failures are not transport retries; they require parser/code correction and a new
  run intent. Any remaining refusal prevents S5 publication.
- SIGINT and SIGTERM request cooperative stop: stop submitting new accessions, drain
  the bounded in-flight window, transactionally retain each complete result returned,
  and stop before starting another chunk. No pointer advances for an incomplete
  attempt; any prior committed chunk pointer remains unchanged. A restart resumes from
  a valid progress journal. The run summary distinguishes `completed` from `cancelled`.
  SIGKILL relies on database transaction rollback and the same journal validation.
- If S5 staging or publication fails after S4 chunks commit, retry rebuilds S5 staging
  from those validated chunks without refetching pages. S5 does not maintain a second
  checkpoint ledger.
- The coordinator returns aggregate run counters and retains only a bounded prefix of
  per-chunk details; result memory does not grow with the number of work-order chunks.

These are new inventory-owned checkpoint semantics. `document_storage` and the
historical phase inform bounded scheduling, attempt isolation, manifest validation,
and atomic commit ordering only; their database layouts, schemas, keys, or resume
protocols are not imported or copied.

## Current implementation blockers

- `tests/pipelines/document_inventory/test_progress.py` exercises atomic per-parse
  recovery; `test_coordinator.py` covers bounded scheduling, resume/retry, run behavior,
  signal drain, and worker ceilings; `test_run_lock.py` covers exclusive ownership.
- `tests/pipelines/document_inventory/test_progress_scale_check.py` runs only a small
  synthetic offline recovery case. A prior explicitly opted-in simulation also passed
  at the documented production-like work-order size, including recovery/resume without
  network or snapshot publication. Its result is not tracked as a durable report; live
  SEC workload behavior remains unverified.
- Production paths use the Parquet-backed work-order iterators. The in-memory chunk
  helper remains available for unit use and is not evidence of production behavior.
- S0 historical-page evidence still gates final parser acceptance and live rollout, not
  the implemented S4 recovery contract.

## Module map and reuse

S4 reuses lower-layer and shared-storage modules; it does not reimplement any of
them. The inventory-owned modules are new, and each one imports only the lower
layers and shared-storage helpers named here.

| Inventory module | Reuses (do not reimplement) | Owns |
|---|---|---|
| `domain/document_inventory/models.py` | `domain.identity`, `foundation.serialization` | Shared S1 cohort and S3 parser records; entry identity |
| `domain/document_inventory/schemas.py` | PyArrow schema primitives | Versioned durable entry schema |
| `engine/index_pages/parser.py` | Domain inventory records, `engine.document.html.tree`, `domain.sec_urls`, `foundation.hashing` | Pure index-page transformation and parser fingerprint |
| `paths.py` | `foundation.runtime.paths.ProjectPaths`, shared current-pointer/transient helpers, `foundation.runtime.fixtures` | Inventory run/chunk/attempt paths and binding the index fixture to its shared location; never `DocumentStoragePaths` |
| `run_manifest.py` | `infra.storage.atomic.atomic_write_json`, `foundation.serialization.canonical_json`, `foundation.hashing.file_sha256` | Run identity, work-order/chunk-size/schema pins, manifest validation |
| `checkpoint.py` | Domain entry schema, broker/worker failure records, `infra.storage.parquet`, atomic IO, DuckDB validation helpers | Transient outcome schema/status, attempt validation, chunk pointer advance; progress transaction contract |
| `broker.py` | `infra.broker.sec_broker.SecBrokerClient` | Picklable broker adapter, response envelope, fetch-failure record |
| `worker.py` | Broker adapter, engine parser, `foundation.runtime.memory.reclaim` | Module-level per-accession process task and worker-failure record |
| `coordinator.py` | Broker daemon, worker task, checkpoint/run manifest, `derive_resources`, process pool | Bounded scheduling, cooperative cancellation, chunk orchestration, resume, retry |
| `cohort.py` | `domain.filing_catalog.schemas`, domain inventory records, `domain.identity`, `domain.sec_urls` | S1 cohort reading and projection |

S4 does not import `pipelines.document_storage` or any frozen module. It does not
add inventory-specific properties to the foundation path object, and it never reaches
into a worker's HTTP client. The checkpoint module composes SQL through
`infra.storage.duckdb.connect` and `sql_path_list`; if it later needs to assemble a
statement at a sink, it must declare itself in
`foundation.scanners.sql_interpolation._SQL_COMPILER_PATHS` with the reason.

## Tests

- Fake broker success, 429 rate limit backoff, and transport failure.
- Picklable worker arguments and typed results.
- All worker requests aggregate through one shared broker instance.
- Bounded in-flight tasks/results under the resolved worker budget, with immediate
  worker-slot refill and completion-order streaming.
- Stable chunk membership is independent of task completion order and input arrival.
- Matching run/chunk manifests skip valid committed Parquet chunks without broker
  calls; mismatched run identity refuses before the first call.
- A valid partial progress journal resumes only accessions without an atomic completed
  parse transaction; every completed accession's outcome and full entry set are visible
  together or not at all.
- Missing, corrupted, stale-schema, wrong-membership, or digest-mismatched chunk
  attempts are never accepted as complete.
- Process interruption before an attempt pointer advances leaves the previous commit
  valid; valid progress rows in the incomplete chunk resume, while partial/mismatched
  progress transactions are never reused.
- A parse with multiple entry rows is transactionally all-or-nothing across its outcome,
  complete entry set, and completion marker.
- SIGINT/SIGTERM stops future submission, drains at most the in-flight worker window,
  and returns a cancelled status without advancing an incomplete attempt pointer.
- A valid progress journal resumes only accessions not already committed in the exact
  run/chunk/attempt identity; an invalid journal triggers a whole-chunk recompute.
- Concurrent coordinators for the same run ID are refused; different run IDs may run
  concurrently, subject to the shared publication lock at S5.
- A valid partially completed journal is resumed only when its progress pointer,
  journal metadata, run/work-order identity, and per-accession transaction records
  validate; a completed chunk pointer takes precedence over stale progress state.
- S5's disk-backed sort restores deterministic publication order independent of task
  completion order or transient chunk order.
- Explicit retry replaces only chunks with retryable typed fetch/worker failures and
  reuses their successful accession outcomes; parser failures remain explicit.
- A failed S5 publication can rebuild from complete S4 chunks with no refetch.
- One failed accession does not become empty or emit partial rows.
- Response bytes pass intact to the parser boundary; no response-size rejection or
  truncation path exists.
- Production IPC contains typed results, not raw HTML or fixture bytes.
- Worker exception cleanup: pool processes terminate cleanly on unexpected crash.
- Worker processes do not write progress stores, SQLite, or Parquet; the coordinator
  owns per-result transactions and chunk Parquet export.
- SIGINT/SIGTERM stops refill, drains at most the in-flight window, and leaves the
  current progress journal reusable without advancing the incomplete attempt pointer.
- A DuckDB crash/reopen test proves transactions that committed before interruption
  remain complete and the interrupted accession transaction leaves no completion key.
- Run lock contention refuses a second owner; explicit stale-lock recovery requires
  operator-confirmed owner state.
- All accessions validated before the first request.
- Pool derives its size from resources without hardcoded worker limits.
- Explicit worker overrides cannot exceed the safe resource-derived ceiling.
- `reclaim()` called at bounded intervals.
- S7b parser-review artifacts are separate from this production worker and preserve
  parser diagnostics for fixture-backed inspection.
- One parser exception does not erase sibling results.
- No `document_storage` imports; layer-boundary scan permits only downward imports.

## Worker budget and scaling

- Worker pool and broker connection sizing derive from `derive_resources().workers`; its default worker
  factory calls `auto_worker_count` with cgroup-aware available memory, worker-memory
  estimate, and a safety fraction.
- The resolved `runtime.chunk_size` is recorded in the run manifest and participates
  in deterministic chunk membership. Worker count and chunk size bound submitted work;
  no cohort-sized future list or result collection is built.
- Each process handles one response at a time; the pool count bounds simultaneous
  response buffers and parser working sets. S0 measures response sizes and exploratory
  parser expansion to tune the per-worker memory estimate.
- No per-response cap or truncation is applied. A single unusually large page can
  exceed the worker memory estimate; the design records this residual risk rather than
  converting a valid response into a fetch failure.
- Hardcoded worker counts or static memory ceilings are prohibited.

## Coordinator invariants

- No child worker opens SQLite or writes a published artifact.
- The run manifest binds resume identity before network work; each chunk pointer names
  only a schema-, membership-, and digest-validated Parquet attempt.
- S4 writes transient Parquet only. S5 consumes these checkpoints into separate
  publication staging and owns the canonical snapshot and `current` pointer.
- One failed accession does not silently become empty; typed errors propagate.
- Every recognized source-table row is retained. No S2 fixture-store writes are part
  of production worker orchestration; S0 uses the fixture store as a separate research
  and replay path.

## Acceptance criteria

The coordinator owns the broker lifecycle, deterministic run/chunk identity, and
validated transient Parquet checkpoints. Workers fetch and parse one accession each,
with memory-derived concurrency and no raw-page IPC. Committed chunks resume without
refetch; S5 reads them into bounded staging, restores deterministic physical order,
and alone publishes the canonical snapshot. Retryable fetch/worker failures have an
explicit retry path; parser refusals remain visible and prevent publication. Every
recognized source row is retained, no page is truncated, and workers neither create
their own HTTP client nor write artifacts.
