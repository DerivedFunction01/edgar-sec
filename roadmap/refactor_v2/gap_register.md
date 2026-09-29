# v1 → v2 Gap Register

**Generated:** 2026-09-29 · **Method:** four independent read-only audits
(Phase 1, Phase 2, Phase 2.5 parsing/normalization, Phase 2.5 storage pipeline)
plus this session's own defect fixes. Every finding carries executed evidence —
a probe, a grep, or a named line number — not an inference from a similar name.

**Gate state at generation:** 1,388 passed, 11 scanners clean.

> **Read this first.** The audits found that several modules described as
> "complete" in the roadmap are *implemented, imported, tested, and unreachable
> from any command*. A green suite proves importability, not usefulness. The
> single most common finding is not missing code — it is code that cannot be
> invoked.

---

## Part 0 — Fixed during this session

| defect | severity | resolution |
| :--- | :--- | :--- |
| `processor.py:72` compared `decision.action == PageMarkerAction.STRIP`; the enum has `REMOVE`/`NORMALIZE`/`PRESERVE` | **production crash** | changed to `REMOVE`; added `test_filing_processor_survives_a_payload_carrying_page_markers`. Every acquired payload carrying page furniture raised `AttributeError` inside the worker. The suite stayed green because no committed golden and no prior test contained a page marker. |

That last sentence is the pattern this whole register is about: **1,387 tests
passed while the pipeline aborted on essentially all real input.**

---

## Part 1 — Unreachable capability (code exists, nothing can call it)

These are the highest-value findings because the roadmap records them as shipped.

| # | capability | evidence | impact |
| :--- | :--- | :--- | :--- |
| 1.1 | **`vacuum_snapshots` has no entry point** | 568 loc implemented, 37 named tests pass, but 21 of 22 call sites are in `test_vacuum.py`. `cli.py:211` registers only `run`/`status`/`review`; neither `cli.py` nor `operator.py` imports `vacuum` | N partial-run snapshots are **never consolidated**. Every `documents run` overwrites `current` with one run's snapshot. The entire quarter-derivation / conflict-rejection / dependency-purge story is unreachable |
| 1.2 | **`reflow` policy callbacks all `None`** | `normalize.py:204-210` builds `ReflowPolicy(unwrap_pre_body_prose=…, relax_prose_layout_gaps=…, unwrap_bullet_continuations=…)`. All five hooks (`is_structural_line`, `is_checkbox_answer_line`, `is_page_boundary_line`, `is_table_bridge_line`, `is_table_tail_line`) are `None`, verified by probe | v1 supplied all five. Table-bridging, tail-merging, page-break segmenting and the "unwrap prose that looks like a table" safety valve never activate |
| 1.3 | **`convert_html_tables_to_ascii_with_metadata` + `cleanup_false_tables_with_metadata` have zero callers** | `html.py:331-343` passes `cleanup_tables=None`; `normalize.py:181` calls it that way. `table_geometries` is permanently `()` (probe: `extract_table_candidates calls: 0`) | No HTML table is ever rendered to an ASCII grid, so the geometry-driven checkbox path (`extractor.py:534-551`) and `rewrite.py:update_table_geometries` are dead |
| 1.4 | **metadata_sync `source_registry` has no CLI** | 215 loc, `refresh_company_tickers`/`load_source_snapshot`, 0 production callers; the `sources` subparser is gone | The content-addressed source-snapshot guarantee is inert, plus three dead `MetadataPaths` methods |
| 1.5 | **`load_seed_cik_csv` unreachable; seeded plans cannot be expanded** | `policy.py:165` defined, 0 production callers. Probe: a plan published with seed filers then expanded by the real `cmd_expand` raises `ParentPlanError` | `DeficitSelector`'s phase 1 is dead; the "child contains 100% of parent's locators" chain cannot be built for anchor-tenant plans |
| 1.6 | **`run_partition` has no caller** | `worker.py:220`, exported, 0 production uses. `cli.py:159-171` reimplements it inline. `merger.py` never reads `plan["partitions"]` | Partitions exist in the plan and the CLI selector and nowhere else |
| 1.7 | **`cover/extractors.py` has no production caller** | All 7 public functions reachable only from `test_extractors.py` | 194 loc of tested, working field extraction reaching no snapshot |
| 1.8 | **`PayloadStore.put` never called; `fixture_lineage.py` is a pure island** | Only `.put(` in `edgar_sec/` is `sec_http/client.py:128` (a different class). Nothing writes `fixture_manifest.json`. All four lineage functions are test-only | No way to build or extend a fixture. See Part 3.3 |
| 1.9 | **broker `daemon.py` is a 61-line in-process thread, not a daemon** | `threading.Thread` context manager; 0 `multiprocessing`/`Process`; only caller is a test. `run.py` has 0 broker entries | v1's `broker_cli.py` (340 loc: start/stop/status/serve, PID registry) has no counterpart |
| 1.10 | **`foundation/text/compounds.py`** (154 loc) | 3 functions, tests only | parity-preserving dead code at Layer 0 |
| 1.11 | **`engine/selection/inventory.py`** (181 loc) | 0 production importers, 14 tests. Inherited from v1 (also an orphan there) | v2 strictly better; noted because the README calls it a pre-run tool nothing invokes |

---

## Part 2 — MISSING capability (v1 behaviour with no v2 equivalent)

### 2.1 The pre-region protector — `.v1/defs/tables/hybrid.py` (284 loc, 12 named tests)

v1's `classify_pre_block` discriminated `<pre>` payloads into
`SGML_TABLE | FIXED_WIDTH | HTML_TABLE | NARRATIVE`; fixed-width payloads were
returned **verbatim**. Exported by `tables/__init__.py`, consumed by
`text/html/pipeline.py` and `sec_documents/preprocessor.py`.

v2 masks only `<table` spans (`protection.py:177`); the `pre` token in
`TABLE_AND_PRE_TAGS` is a line-break mapping, not protection. Differential probe
on 8 v1 test cases — **5 of 8 diverge**:

```
fixed-width in pre
 v1: '\n  Year      2023     2022\n  ------    ----     ----\n  Net     1,234     1,111\n'
 v2: 'Year 2023 2022 ------ ---- ---- Net 1,234 1,111'      *** DIFFERENT ***
```

Impact: the canonical transition-section equity tables and EDGAR's `.txt`
ASCII-pre wrappers collapse to one run-on line.

### 2.2 The entire cover-healing stage (619 loc, undisclosed)

`.v1/defs/sec_forms/cover/healing.py` (106) composed by
`normalization/pipelines/common.py:285` *between* checkmark rewrite and content
transform. Its leaves: `text/healing/lines.py` (513) and `dates.py:419
heal_date_fragments`. Repo-wide grep for all ten function names: **0 hits outside
`.v1/`**. `normalize.py:29-36` documents three departures from v1 and does not
mention it.

### 2.3 The plan producer for `documents run` (v1 `core/targets.py` + `pipeline.py`, 647 loc)

`cli.py:67-110` reads `{"chunks":[{…locators…}]}` — a JSON shape **no v2 module
writes**. The only producer is a test that hand-writes it
(`test_operator_and_cli.py:333`). `load_targets`, `partition_locators`,
`calculate_optimal_chunk_size`, `run_partition`, `_ChunkTask`: 0 v2 hits.

Impact: `python run.py documents run --plan corpus.json` is not runnable
end-to-end. **The phase-2 → 2.5 handoff the architecture diagram asserts is not
implemented.**

### 2.4 Other MISSING, with the honest reason

| v1 module | loc | note |
| :--- | ---: | :--- |
| `01/core/config.py` (`ProjectConfig`) | 247 | both halves gone — see Part 4.1 |
| `01/core/registry.py` (`compare_sources`) | 272 | no path home in v2's `MetadataPaths` |
| `01/core/preview.py` | 90 | lifecycle is 4 commands, not 5 |
| `025/core/snapshot_merge.py` | 485 | `merge_partitions_to_snapshot` gone; orphan `relation_key_rows` left behind |
| `025/core/partition_merger.py` | 341 | `merge_partition`, `append_occurrences` gone |
| `025/core/partition_reader.py` | 226 | declared in README as dropped |
| `025/core/partition_handoff.py` | 143 | `write_handoff`, `validate_handoffs` gone |
| `025/core/chunk_cache.py` | 135 | `find_completed_chunk_db` gone |
| `025/core/fixture_builder.py` | 293 | Part 3.3 |
| `defs/sec_http/broker_cli.py` | 340 | Part 1.9 |
| `025/testing/{corpus,review,paths}.py` | 547 | `review.py` is a different responsibility |
| `025/tools/*.py` (7 scripts) | 968 | deliberately removed by sub-plan 06 §1.2 — but the replacement (M6.3) was then deferred, so **neither** exists |

---

## Part 3 — DIVERGED: silent regressions against v1

These are worse than MISSING because the code looks right and the gate is green.

### 3.1 Memory regression: the byte-budgeted prefetch pipeline is gone

v1's `chunk_persistence.py:60-104 _ByteBudget` + `:355-440
_run_pipelined_acquisitions` capped in-flight payload bytes at 96 MiB with a
8-item queue, releasing each reservation after persisting and calling `reclaim()`
per batch. v2's `worker.py:152-280 process_chunk` accumulates `raw_blobs`,
`processed_text` and `normalized_texts` for the **whole chunk**, then writes once
(probe: 1 `write_chunk_snapshot` call, 0 `ThreadPoolExecutor`).

**Peak RSS is now O(sum of all payloads in a chunk)** rather than O(96 MiB) —
directly against `AGENTS.md` §2.

Correction to this session's own work: my `implementation_ledger.tsv` row for
`worker.py` claims v2 "absorbed `chunk_persistence.py` `ChunkResult`/`_ByteBudget`".
`_ByteBudget` has **zero** v2 hits. `ChunkResult` was absorbed; the byte budget
was not. The ledger row is wrong.

### 3.2 Four chunk-resumability guarantees lost in the merge

`chunk_worker.py` (483) + `chunk_persistence.py` (481) → one 502-loc `worker.py`.
Lost, with 0 v2 hits for `allow_append`, `retry_failures`,
`NORMALIZATION_FAILURES`, `normalized_schema_version`:

1. **Sub-chunk resumption** — v1 queried the chunk DB and skipped already-persisted documents. v2 loops every locator unconditionally (`worker.py:204-244`).
2. **Per-attempt normalization-failure ledger** keyed by `(source_doc_id, processor_fingerprint)`.
3. **`retry_failures`** — re-attempting previously failed documents.
4. **Schema-version gate on reuse** — `WORKER_SCHEMA_VERSION` (`worker.py:60`) is written nowhere and checked nowhere.

Impact: resuming after a mid-chunk crash re-fetches and re-normalizes every
document; a failed document is permanently failed with no retry path.
`AGENTS.md` §4 is satisfied at chunk granularity only.

### 3.3 The fixture-extend capability: all four behaviours absent

v1's `fill_fixture` (293 loc) could append to an existing fixture database. The
four behaviours, each verified absent from v2:

| v1 behaviour | v2 |
| :--- | :--- |
| `allow_append=True` into `process_chunk` | 0 hits repo-wide |
| `unknown_lineage=fixture_db.is_file()` | `check_fixture_lineage` has no production caller |
| `before_blob_ids`/`cached_count`/`newly_fetched` | no equivalent |
| history entry with `added_locator_count` | nothing writes `fixture_manifest.json` |

The primitive underneath is correct and append-capable: `PayloadStore.put` is
`INSERT OR IGNORE` on PK `(document_locator_key, blob_hash)`, returning `False`
when identical bytes exist. **Nothing calls it.**

### 3.4 `latin-1` hardcoded, and a 2048-byte representation sniff

`normalize.py:169` hardcodes `text.decode("latin-1")` where v1's
`preprocessor.py:99-117` tried utf-8 → cp1252 → latin-1 and recorded the result;
`:171-176` sniffs only `text[:2048]` where v1 classified the whole document.

```
utf-8 payload  v1: '<p>Café naïve résumé ? 5</p>'
               v2: '<p>CafÃ© naÃ¯ve rÃ©sumÃ© â\x80\x94 5</p>'
late-table (SGML <TABLE> at byte 2500):  v2=ascii   v1_repr=html
```

Impact: every UTF-8-encoded non-ASCII filing is stored as mojibake; a filing
whose first 2 KB is a banner bypasses Stage-1 cleaning entirely.

### 3.5 `RE_SEPARATOR_LINE` restated with different semantics

The exact `vocabulary.py` → `jurisdictions.py` drift pattern fixed earlier this
session, reproduced. `foundation/text/patterns.py:20` is the owner; v1's
`candidates.py` **imported** it. v2's `checkmarks/_yesno.py:66` re-compiles a
different pattern under the same name, and `numeric_cells.py:79` holds a third
byte-identical copy of `RE_COLUMN_GAP`. `dash_only` now accepts
whitespace-only and single-dash lines v1 rejected.

### 3.6 Two-stage merge collapsed to single-stage (Phase 1)

v1's `merge.py` (780 loc) had a partition→final boundary with
`plan_hash`/`artifact_sha256` binding. v2's is 248 loc. Inert rather than broken
at `DEFAULT_PARTITION_COUNT=1` — **except** the progress channel: `merge_chunks`
takes no progress parameter, so a multi-million-row merge is silent, where v1
emitted `merge_stage`/`readback_done` events.

### 3.7 v1's plan-fingerprint verification on reuse was dropped

Probe: a published bundle's `locator_groups.parquet` was rewritten from 2 rows
to 1; `plan_bundle_complete()` still returned `True` and the re-plan claimed 2
locators. v1 re-derived and compared a fingerprint and rejected the mismatch.

---

## Part 4 — Contract violations

### 4.1 Phase 1 settings bypass — the only finding that produces silently wrong output

`runtime.chunk_size` and `runtime.partition_count` are declared
`SettingSpec(env=True, config=True, cli=True)`, resolve correctly, and are read
by **nothing**. `cli.py:227-238` wires argparse defaults to module constants.

```
$ RUNTIME_CHUNK_SIZE=2 RUNTIME_PARTITION_COUNT=3 … plan --input …
plan written: 4 CIKs, 1 chunks, 1 partitions
  chunk_size     : 1000   <-- env said 2
  partition_count: 1      <-- env said 3
```

An operator who sets the documented env vars gets a different plan than the
environment declares, with a success line printed. This is the v1
`validate_plan_against_options` guard, with both halves gone.

### 4.2 The policy-scope occurrence partition ships a duplicate column

`planner.py:476` uses `SELECT *` over a **two-way join**, projecting
`document_locator_key` twice. Probe: the published policy-scope occurrence file
has **45 columns including `document_locator_key_1`** where the deterministic
scope has 16. `test_phase25_contract.py:168` asserts column *containment*, never
schema equality, so the bundle that Phase 2.5 consumes as its sole input is
unpinned. One-word fix (`SELECT o.*`).

### 4.3 `validate_chunks` is far weaker than AGENTS.md §4.3

§4.3 requires the coordinator to validate "schema conformance, row count,
uniqueness of CIKs, null checks, fan-out accession records". `merger.py:79-98`
does two checks: `path.is_file()` and column names. Everything else is a warning.
v1's `snapshot_merge.py:199` raised on duplicate occurrences; v2 cannot.

### 4.4 Also open

- **Three workers, not a token bucket.** `daemon.py` has 0 occurrences of token/bucket; pacing is `RateLimiter` inside each `SecHttpClient`. `M2.2 [x]` claims a "soak test proving token bucket caps throughput" — the test injects a pacing-free double and asserts 10 requests return `"ok"`.
- **`catalog_job.py:189,253` hash the two largest files in the pipeline with `read_bytes()`.** Measured with `tracemalloc` on a 210 MB file: 209.7 MB peak vs 0.1 MB for the existing streaming `file_sha256` — **1542× amplification**, and `resource-allocation` cannot see it.
- **Delegation link direction reversed.** v1 rewrote the *primary*'s metadata to point at its exhibits; v2 annotates the *exhibit* to point at its primary, and `exhibits_for` (the only primary→exhibits lookup) has no production caller.
- **`plan["schema_version"]` is recorded, displayed and never enforced.** Probe: a forged `0.0.1-FORGED` was accepted by `load_plan`. Mitigated — chunk validation compares against the live schema, which is stronger — but `status` reports a version the code may not honour.

---

## Part 5 — UNTESTED

| area | gap |
| :--- | :--- |
| `checkmarks/rewrite.py` (398 loc) | **zero** named tests. Instrumented full-suite run: `apply_cover_checkmark_decisions` **0 calls**, `update_table_geometries` **0 calls**, `extract_table_candidates` **0 calls** — because no committed fixture yields a non-empty `decisions` tuple. The existing "checkmark scoped to cover" test asserts only `inference.status is not None`, which is always true |
| offset translator | `build_masked_offset_translator` is a **verified-correct** port (46-offset differential probe, 0 diffs) with **no** test of its own. The one test that appears to cover the line mapper is non-discriminating — it also passes if no remapping occurs |
| `engine/reflow/` (1,562 loc) | 5 modules, 7 tests. v1 had 49 reflow tests. 42 have no v2 counterpart. Combined with 1.2 (all callbacks `None`), reflow's table and structural behaviour is entirely unevidenced |
| Phase 1 CLI/operator | `cmd_run`/`cmd_merge`/`cmd_augment` have 0 named tests; the sibling `filing_catalog/test_cli.py` has the pattern to copy |
| atomic checkpoint contract | `write_parquet_table`'s tmp+`os.replace`+`_fsync_dir` is correct and tmp-safe against the merge glob, but **no test would catch a regression** |
| broker → `SqlCache` seam | all 3 broker tests inject a pacing-free double; the real warm-cache path is untested |
| `max_response_bytes` | guard is correct, off by default in both v1 and v2, but v1 had `test_response_too_large_is_permanent` and v2 has none |
| 16 public symbols | no named test, and 5 with no production caller either (`_fingerprint_matches`, `_send_frame`, `relation_key_rows`, `read_part`, `payload_doc_ids`) |

---

## Part 6 — Documentation and roadmap claims found FALSE

| claim | reality |
| :--- | :--- |
| `phase_1.md:4` "Progress: 100% — … implemented, tested, and passing all quality gates" | 3 v1 modules (609 loc) and 5 of 7 subcommands missing; 6 of 13 modules have no mirrored test. The Phase 1 drops are recorded **nowhere** — contrast `phase_2_5.md` §5's honest "M4.3 shipped with documented scope reductions" |
| `phase_2.md:4` "Status: COMPLETE" / §14.4 "Outstanding: None" | 4 undisclosed defects, one in the published artifact |
| `phase_2_5.md:6` "Phase 1: COMPLETE" | see above |
| `02_infra_broker_and_cas.md:144` consolidation "Status: implemented" | implemented and unreachable — no `vacuum` subcommand |
| `02_infra_broker_and_cas.md:40` `daemon.py` = "background daemon process … token replenishment loop" | a 61-line in-process thread context manager |
| `02_infra_broker_and_cas.md:104` `M2.2 [x]` token-bucket soak test | no token bucket; the test asserts concurrency only |
| `03_engine_document_and_reflow.md:69` specs "stored in `docs/reflow/` or `engine/reflow/`" | `RULE_ENGINE_SPEC.md` and `HYPOTHESES.md` exist **only** in `.v1/` |
| `04_engine_tables_and_forms.md:32` §1.4 "covers 10-K, 10-Q, 8-K, 6-K, 20-F, Form 3/4/5, 13F" | `registry.py` seeds **four**; the other six fall through to `_default_plugin()` with no evaluator |
| `filing_catalog/README.md:197-199` `plan_fingerprint` "binds identity to its selection" | `plan_id` is derived from the request alone, which contains no locator keys. Two runs with different selections **do** share a `plan_id` |
| `filing_catalog/paths.py:8-10` `snapshots/` and `plans/` subdirectories | both resolve to `catalog_root`; `snapshot_dir(X) == plan_dir(X)` |
| `phase_2_5.md` §3 Phase 2 input contract | names `target_plan.parquet`, `plan_manifest.json`, `partitions/`, a `selection_weight` column, and a 20-char dashed `accession_number` — **none exist**. The real bundle is `plan.json` + `locator_groups.parquet` with an 18-char stripped accession |
| `engine/forms/README.md:113-119` | discloses `DocumentTopology`; omits `BodyRoot`, `BoundaryInput`, `ItemDefinition` (all dead) |
| `implementation_ledger.tsv` `worker.py` row | claims `_ByteBudget` was absorbed; it was not (Part 3.1) |

---

## Part 7 — The deferral that undercut everything above

`phase_2_5.md` §7 defers M6.3/M6.4/M6.5: real historical SEC filing fixtures
and golden comparison. Sub-plan 06 §1.2 removed v1's 968-loc corpus tooling
*because* real archetypes were coming instead.

**Neither exists.** The committed goldens are two synthetic files, and they
assert **nothing** about the storage layer — no Parquet schema, no chunk
checkpoint, no processor fingerprint, no manifest shape, no part tree, no
`vacuum`, no delegation, no CLI. They exercise `engine.forms.normalize` and one
evaluator, and nothing else.

This matters beyond the deferral itself: the nine v1 files marked `DELETE_NOW`
in `v1_retirement.tsv` on the strength of "tested by N v2 test files" rest on
synthetic unit tests, never on a golden comparison against a real filing.

---

## Part 8 — Dead surface with neither producer nor consumer

| symbol | location | note |
| :--- | :--- | :--- |
| `DocumentTopology`, `BodyRoot`, `BoundaryInput`, `ItemDefinition` | `cover/models.py` | 0 consumers each. v1's `resolve_document_topology` was test-only in v1 too |
| `SubmissionsAggregate`, `EntityProfile`, `FilingRecord`, `Listing`, `FormerName`, `Address` | `domain/submissions/models.py` (105 loc) | 0 producers, 0 tests. A parallel, drifting description of data the PyArrow schema already owns |
| `run_partition` | `metadata_sync/worker.py:220` | Part 1.6 |
| `augment_from_manifest` | `metadata_sync/augmentation.py:220` | documented as public surface, 0 callers, 0 tests |
| `normalize_cik_padded` | `engine/submissions/helpers.py:71` | inherited v1 orphan |
| `relation_key_rows`, `read_part`, `payload_doc_ids`, `_fingerprint_matches`, `_send_frame` | 2.5 storage | no caller and no test |

---

## Part 9 — Coverage census at a glance

`roadmap/refactor_v2/test_coverage_census.tsv` — 170 source modules:
**96 mirrored · 34 imported · 40 untested (9,181 loc)**.

Largest untested blocks: 14 `ascii_html` sub-modules · 5 `reflow` modules
(1,562 loc) · `checkmarks/extractor.py` (672) · `checkmarks/solver.py` (637) ·
`checkmarks/rewrite.py` (398) · `processor.py` (271) · `queries.py` (267) ·
`sec_broker.py` (361).

---

## Suggested order of work

1. **Fix the shipped-artifact and wrong-output defects** — 4.2 (`SELECT o.*`,
   one word), 4.1 (settings bypass), Part 0 regression test.
2. **Make the built-but-unreachable reachable** — 1.1 `vacuum` subcommand first
   (it gates the corpus story), then 1.2 reflow callbacks, then 1.3 table
   rendering. Each converts a green test into a real capability.
3. **Restore the two silent regressions** — 3.1 byte budget, 3.2 sub-chunk resume.
4. **The two missing subsystems with the largest v1 surface** — 2.1 pre-region
   protector (284 + 12 tests to port), 2.2 cover healing (619 loc).
5. **Build the Phase 2 → 2.5 handoff** — 2.3, without which `documents run` is
   not runnable end to end.
6. **Resolve the deferral** — 7. Without real archetypes, the storage layer has
   no golden coverage and the `DELETE_NOW` verdicts rest on synthetic tests.
7. **Correct the documentation** — Part 6, now that the code is settled.
8. **Then** delete the dead surface (Part 8) and archive `.v1`.
