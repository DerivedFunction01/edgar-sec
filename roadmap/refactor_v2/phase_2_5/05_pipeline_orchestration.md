# Phase 2.5 — Sub-Plan 05: Pipeline & Batch Orchestration

> [!NOTE]
> **Parent Plan:** [Phase 2.5 Master Plan (`phase_2_5.md`)](file:///home/denny/edgar-sec/roadmap/refactor_v2/phase_2_5.md)  
> **Layer Focus:** Layer 4 (`pipelines/document_storage/`)  
> **Source Grounding:** `.v1/phases/025_webpage_storage/core/`, `.v1/phases/025_webpage_storage/run.py`, `cli.py`

---

## 1. Objectives & Architectural Role

`pipelines/document_storage` is the orchestration layer that executes large-scale batch acquisition and normalization:
1. **Target Plan Ingestion**: Reads a chunk-plan JSON file with no network access. This is **not** the published Phase 2 bundle — see "What `--plan` actually is" below.
2. **Process Pool Concurrency**: Drives a pool of isolated worker processes budgeted via `derive_resources()`.
3. **Resumable Chunk Execution**: Workers write atomic, typed **Parquet** chunk checkpoints (`chunk-{chunk_id}.parquet`) with a processor-fingerprint sidecar. Stalled chunks resume cleanly without re-fetching SEC data. v1's isolated SQLite chunk databases were measured and dropped — see sub-plan 02.
4. **Launcher Entry**: `run.py` registers `documents` alongside `metadata` and
   `filing-catalog`, so the whole pipeline is reached from the existing root
   launcher rather than a bespoke front end.

### Implemented surface

| Module | Responsibility |
| :--- | :--- |
| `pipelines/document_storage/processor.py` | `FilingProcessor` (normalize + triage) and `PassThroughProcessor`; stamps a processor fingerprint. |
| `pipelines/document_storage/worker.py` | `process_chunk` / `process_chunks`; process pool with `max_tasks_per_child`; chunk checkpoints verified and skipped on resume. |
| `pipelines/document_storage/delegation.py` | Bounded exhibit second pass: one held-bundle attempt plus at most one bundle fetch. |
| `pipelines/document_storage/merger.py` | Out-of-core merge into an immutable snapshot, part projection, and the `current` pointer. |
| `pipelines/document_storage/operator.py` | `run_document_storage`: acquire → delegate → merge → publish. |
| `pipelines/document_storage/queries.py` | Direct SQL for consolidation. |
| `pipelines/document_storage/vacuum.py` | `vacuum_snapshots`: cross-run consolidation. **Not reachable from the CLI or any operator surface.** |
| `pipelines/document_storage/review.py` | `compare_review_runs`: base-vs-new review-run comparison. |
| `pipelines/document_storage/review_artifacts.py` | Fixture-backed review artifact generation. **The only Phase 2.5 path runnable end-to-end today**, because it needs no plan. |
| `pipelines/document_storage/fixture_operator.py` | `fill_fixture` / `list_fixtures`: live raw fill, discovery, and manifest publication. |
| `pipelines/document_storage/cli.py` | `run.py documents {run,status,review,review-artifacts,fill,fixtures}`. |

The worker reports each stub decision as a `DelegationTarget` rather than the
operator re-deriving it, so a primary document is fetched and normalized exactly
once per run.
5. **Snapshot Publication**: Assembles final versioned Parquet datasets via DuckDB out-of-core COPY.

### What `--plan` actually is

`run` and `fill` both take `--plan <path-to-json>`. `_load_plan` (`cli.py:124-127`)
reads that file and `_plan_to_inputs` (`cli.py:132-169`) expects exactly one shape:

```json
{"chunks": [{"chunk_id": "c00000",
             "locators":    [{"accession": "...", "document_path": "...",
                              "archive_url": "...", "form": "10-K", "source_cik": "..."}],
             "occurrences": [{"source_cik": "...", "accession": "...",
                              "document_path": "...", "form": "...", "filing_date": "..."}]}]}
```

This is **not** the published Phase 2 bundle described in master §3, which is a
directory of Parquet (`locator_groups.parquet` plus `targets/form=*/data.parquet`)
carrying a `plan_fingerprint`. No v2 module writes the JSON above:
`filing_catalog` publishes Parquet, and no other writer emits a
`chunks`/`locators`/`occurrences` document. A missing `chunk_id` defaults to
`f"c{index:05d}"`, and a chunk with no locators is an empty chunk rather than an
error, so a plan may declare more chunks than a smoke run wants
(`cli.py:145-147`).

> [!IMPORTANT]
> This is the single largest handoff gap in Phase 2.5. `documents run` is the
> headline command and it has **no producer for its input**. `--plan` is an
> explicit artifact handoff by design rather than a discovery problem, but
> nothing yet performs the handoff. The bridge from a published Phase 2 bundle to
> this chunk-plan JSON is unimplemented.

---

## 2. Inventory & Migration Mapping

| `.v1` Source File | Lines | Target v2 Location | Responsibility & Invariants |
| :--- | ---: | :--- | :--- |
| `phases/025/.../core/pipeline.py` | 460 | `pipelines/document_storage/operator.py` | Orchestrates end-to-end target plan execution and worker coordination. The filename in this table is v1's, not v2's — v2 has no `pipeline.py`. |
| `phases/025/.../core/chunk_worker.py` | 490 | `pipelines/document_storage/worker.py` | Worker process loop: fetch &rarr; engine normalizer &rarr; Parquet chunk checkpoint. |
| `phases/025/.../core/fetcher.py` | 420 | `pipelines/document_storage/fetching.py` | Acquisition adapter (live broker fetch vs. offline fixture replay). v2 has no `fetcher.py`. |
| `phases/025/.../core/exhibit_second_pass.py` | 260 | `pipelines/document_storage/delegation.py` | Evaluator dispatch for secondary exhibit refetching (EX-13, EX-21). v2 has no `exhibit_delegator.py`. |
| `phases/025/.../core/snapshot_merge.py` | 410 | `pipelines/document_storage/merger.py` | Validates chunk invariants and publishes canonical Parquet dataset. |
| `phases/025/.../core/vacuum.py` | 449 | `pipelines/document_storage/vacuum.py` | **Cross-run snapshot consolidation**, not defragmentation. See the correction in sub-plan 02. Implemented and tested but **unwired**. |
| `phases/025/.../core/fixture_builder.py` | 293 | `pipelines/document_storage/fixture_operator.py` | Fill, discovery, and manifest publication. Reachable via `documents fill` and `documents fixtures`. |
| `phases/025_webpage_storage/run.py` | 312 | `pipelines/document_storage/cli.py::_interactive` | Phase-local menu, reached when `documents` is invoked with no subcommand. **Not** a full operator wizard — see §3.3. |
| `phases/025_webpage_storage/cli.py` | 580 | `pipelines/document_storage/cli.py` | Canonical CLI, reached as `python run.py documents {run,status,review,review-artifacts,fill,fixtures}`. |

---

## 3. Detailed Component Specifications

### 3.1 Scoped Directory Layout

There is no `pipelines/document_storage/paths.py`. Every path is resolved by
`ProjectPaths` in `edgar_sec/foundation/runtime/paths.py:78-140`, and the layout it
produces is:

```text
{artifacts_root}/document_storage/
├── snapshots/{snapshot_id}/          published, immutable
│   ├── documents.parquet             run snapshots only (assembled artifact)
│   ├── manifest.json                 required
│   └── parts/
│       ├── index/run.parquet         part-kind tree: metadata
│       └── payload/run.parquet       part-kind tree: text
└── snapshots/current/pointer.json

{artifacts_root}/fixtures/{fixture_id}/
├── fixture.sqlite                    fixture_payloads(doc_id, raw_payload)
└── fixture.manifest.json

{artifacts_root}/transient/document_storage/runs/{run_id}/
├── chunks/chunk-{chunk_id}.parquet   resumable checkpoints
├── chunks/chunk-{chunk_id}.fingerprint   processor identity sidecar
├── chunks/chunk-delegated.parquet    exhibit second-pass output
└── review/                           review bundles

{artifacts_root}/document_storage/review-runs/{run_id}/   durable review output
```

No `.db` files, no `target_plan/` copy, and no `failure_ledger.json` exist in v2.
Unretryable-fetch tracking is owned by the shared SEC HTTP failure ledger rather
than a per-run file. A review run lives beside the snapshots and fixtures rather
than under the run-scoped transient tree, because a review run is a deliverable
you intend to diff against a sibling, not staging (`paths.py:126-140`).

### 3.2 Worker Execution Loop (`edgar_sec/pipelines/document_storage/worker.py`)
```python
def process_chunk(chunk, processor, fetcher, ...):
    # 1. Reuse check: is_chunk_complete validates the Parquet and compares the
    #    fingerprint sidecar. A reusable chunk is skipped outright.
    if is_chunk_complete(...):
        return ChunkResult(..., worker_id="skipped")

    for locator in _unique_locators(chunk.locators):   # dedup by key, order preserved
        # 2. Acquire the raw payload (broker, live, or fixture replay)
        fetched = fetcher.acquire(locator)
        if not fetched.ok:
            missing += 1; continue          # no callback, no row

        # 3. Pure engine normalization (Layer 3)
        normalized = processor.process(fetched.payload, locator=locator)

        # 4. Expand occurrences: every locator yields >= 1 provenance row,
        #    including failures, because the snapshot records what happened.

    # 5. Write the Parquet chunk snapshot, then the fingerprint sidecar.
    #    A processing exception becomes a `failed` count and is caught:
    #    one bad document is not a bad chunk.
    return ChunkResult(chunk_id=chunk.id, status="completed")
```

Exhibit delegation does **not** run inside the worker. The workers report
`DelegationTarget` records, and `operator._run_delegation` performs the second
pass after the pool drains and before publication, because an exhibit resolved
from a stub must land in the same snapshot as its primary
(`operator.py:12-16`).

### 3.3 Phase-Local Menu (`cli.py::_interactive`)

Reached by invoking the `documents` launcher entry with no subcommand. It is a
five-item fixture-lifecycle menu, not the eight-item v1 wizard:

```text
Document Storage (Phase 2.5)
  1. Fill or extend a fixture
  2. Run a plan from a fixture
  3. List fixtures
  4. Build review artifacts from a fixture
  5. Compare two review runs
  0. Exit
```

Fixtures are discovered by the menu (they are this package's own artifact);
target plans are not, because `filing_catalog` owns them and a sibling-pipeline
import would couple two pipelines that are separate by design. **Preview,
Production Mode, Status & Resumability, Merge, and Vacuum are not menu items.**
Status is a subcommand (`documents status`); the other four have no reachable
route at all. v2 has no `build_operator_menu` in this package — that pattern
exists only in `metadata_sync/operator.py:555` and `filing_catalog/operator.py:209`.

---

## 4. Milestone Checklist & Verification

- [x] **M5.1**-**M5.7**: the orchestration surface in "Implemented surface" exists
  and is covered by `tests/pipelines/document_storage/`; `documents` is registered
  in `run.py:36-41`.
- [ ] **M5.8 (open)**: a bundle reader converting a published Phase 2 plan bundle
  into the chunk-plan JSON described above, with rejection tests for an invalid
  schema version, a malformed payload, and a foreign-chunk assignment. This is
  the "restore the published Phase 2 handoff" step in the
  [implementation roadmap](../../../.kilo/plans/phase-025-implementation-roadmap.md)
  and Plan 08 of the sequential track.
- [ ] **M5.9 (open)**: `vacuum_snapshots` is implemented and tested
  (`test_vacuum.py`, 28 call sites) but has **zero** production callers and no
  `documents vacuum` subcommand, so cross-run consolidation is unreachable by an
  operator. Before wiring it, `vacuum.py:491` should derive quarter concurrency
  from `derive_resources()` rather than defaulting to a hardcoded `1`; the
  function already accepts a `RuntimeResourceProfile` and never uses it.
