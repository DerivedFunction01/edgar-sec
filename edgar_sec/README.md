# `edgar_sec` — the v2 package

A layered rewrite of the SEC filing ingestion system. This file is the map: it
tells you which layer owns what, where the boundaries are, and which README to
read next. Every package below owns its own `README.md` with the detail.

## Layers

Imports flow **downward only**. A layer may import from the layers beneath it
and never from the layers above. This is not a convention — the
`layer-boundary` policy scanner parses every import in the package and fails the
gate on a violation.

```text
Layer 5  apps/          read-only, operator-facing consumers of published artifacts
           │            may read every layer below; nothing may import it
Layer 4  pipelines/    orchestration: CLI, operator, planner, worker, merger
           │            the only layer permitted to sequence the others
Layer 3  engine/       pure transformation: parsing, normalization, solving
           │
Layer 2  infra/        I/O adapters: SEC HTTP, broker, DuckDB, Parquet, CAS
           │
Layer 1  domain/       data contracts and vocabularies. No IO.
           │
Layer 0  foundation/   runtime, memory, hashing, compression, settings, scanners
                         zero internal dependencies on upper layers
```

| Layer | Package | Owns |
| :--- | :--- | :--- |
| 0 | [`foundation/`](foundation/README.md) | cgroup-aware resources, memory reclamation, hashing, canonical JSON, the zstd frame codec, the settings registry, the 11 policy scanners |
| 0 | [`foundation/runtime/`](foundation/runtime/README.md) | paths, env resolution, progress, partitions, interactive prompts, memory |
| 0 | [`foundation/runtime/settings/`](foundation/runtime/settings/README.md) | the single typed settings registry; env names derive from logical dotted paths |
| 0 | [`foundation/scanners/`](foundation/scanners/README.md) | policy scanners and `ALL_SCANNERS` |
| 0 | [`foundation/text/`](foundation/text/README.md) | shared pattern vocabulary: dates, tokens, grammar, unicode, compounds, the Aho-Corasick automaton |
| 0 | [`foundation/regex/`](foundation/regex/README.md) | the regex builder DSL that guarantees longest-first alternation ordering |
| 1 | [`domain/`](domain/README.md) | layer root; contracts only |
| 1 | [`domain/identity.py`](domain/README.md) | `Cik`, `AccessionNumber` |
| 1 | [`domain/document/`](domain/document/README.md) | document and occurrence record contracts, acquisition results |
| 1 | [`domain/forms/`](domain/forms/README.md) | cover/form vocabulary: checkmarks, family aliases, field schemas, body evidence |
| 1 | [`domain/taxonomy/`](domain/taxonomy/README.md) | jurisdictions, legal forms, family vocabulary |
| 1 | [`domain/submissions/`](domain/submissions/README.md) | submission schemas |
| 1 | [`domain/filing_catalog/`](domain/filing_catalog/README.md) | catalog schemas and filters |
| 2 | [`infra/`](infra/README.md) | layer root; I/O adapters |
| 2 | [`infra/sec_http/`](infra/sec_http/README.md) | the shared SEC client: pacing, retries, cache, metrics, failure ledger |
| 2 | [`infra/broker/`](infra/broker/README.md) | Unix-socket broker so an arbitrary worker pool shares one rate limit |
| 2 | [`infra/storage/`](infra/storage/README.md) | atomic IO, DuckDB engine, Parquet, snapshot manifests, the document part tree and payload store |
| 3 | [`engine/`](engine/README.md) | layer root; pure transformation. Partially built — read its gaps section |
| 3 | [`engine/document/`](engine/document/README.md) | input preparation, SGML unpacking, HTML cleaning/projection, page markers, signatures, whitespace |
| 3 | [`engine/tables/`](engine/tables/README.md) | table masking, HTML→ASCII rendering with geometry, false-table rejection |
| 3 | [`engine/forms/`](engine/forms/README.md) | stage order, result record, cover decision chain, family SPI and evaluators |
| 3 | [`engine/reflow/`](engine/reflow/README.md) | conservative ASCII reflow: features, calibrated thresholds, rule cascades |
| 3 | [`engine/forms/plugins/`](engine/forms/plugins/README.md) | the `FormPlugin` SPI and registry — the Phase 2.5 extension seam |
| 3 | [`engine/selection/`](engine/selection/README.md) | Phase 2 target-plan selection: features, policy, selector, source |
| 3 | [`engine/company_family/`](engine/company_family/README.md) | name normalization and family clustering |
| 3 | [`engine/submissions/`](engine/submissions/README.md) | submission unrolling, profiling, building |
| 5 | [`apps/`](apps/README.md) | layer root; read-only operator-facing consumers of published artifacts |
| 5 | [`apps/viewer/`](apps/viewer/README.md) | the dataset viewer: a lazy filesystem explorer, manifest-driven virtual datasets, paged DuckDB reads, a guarded read-only SQL console |
| 4 | [`pipelines/`](pipelines/README.md) | layer root; orchestration |
| 4 | [`pipelines/metadata_sync/`](pipelines/metadata_sync/README.md) | **Phase 1, complete.** Submissions metadata ingest, chunked and resumable |
| 4 | [`pipelines/filing_catalog/`](pipelines/filing_catalog/README.md) | **Phase 2, complete.** Zero-network catalog materialisation and target planning |
| 4 | [`pipelines/document_storage/`](pipelines/document_storage/README.md) | **Phase 2.5.** Fetch, normalize, delegate, checkpoint, merge, consolidate |

## Contracts that hold everywhere

- **No barrel re-exports.** `__init__.py` files must not re-export child symbols.
  Consumers import from the leaf module (`from edgar_sec.domain.identity import Cik`).
  This keeps heavy dependencies lazy and symbol ownership explicit.
- **No backward-compatibility shims.** When a component moves, call sites move with
  it. The `legacy-shims` scanner enforces this.
- **Apps are not batch pipelines.** An app has no chunks, no plan, no worker,
  and no resumability, so §4's pipeline contracts do not bind it. The
  `layer-boundary` scanner enforces exactly one clause for it: nothing below
  `apps/` may import it.
- **No direct `os.environ` access** outside `edgar_sec.foundation.runtime.env`.
  The `environment-access` scanner enforces this.
- **No hardcoded thread counts or memory limits** outside the resource helpers.
  The `resource-allocation` scanner enforces this.
- **Tests mirror the source tree.** `edgar_sec/foundation/text/dates.py` is covered
  by `tests/foundation/text/test_dates.py`. One test file per source module.

`AGENTS.md` is the binding contract and is normative where it conflicts with a
README.

## Known defects in this package

Recorded here because a reader should not have to discover them by importing:

- **`engine/forms/` has no test directory.** `tests/engine/forms/` does not exist;
  commit `079010e` deleted it along with 15 test files. The source package retains two
  production callers in `pipelines/document_storage/`. This is an `AGENTS.md` §6 violation
  that `check.py` cannot detect — pytest over an absent directory is indistinguishable from
  pytest over a package that required no tests. Re-landing is in scope for sub-plan 04.
  (`tests/engine/document/` was re-landed with sub-plan 03 slice 2.)
- **`engine/forms/normalize.py` composes one stage.** It resolves a form alias and returns a
  `CoverBoundary(method=NONE, confidence=0.0)`. Six of `NormalizationResult`'s ten fields are
  always `None`, and `stage_trace` is always `["decode"]`. Two production callers read those
  fields. Its `decode` stage is now the full V1 input chain — decode, envelope stripping,
  non-displaying-block purge, ASCII-PRE discrimination, representation classification, HTML
  Stage-1 cleaning. See `engine/forms/README.md`.
- **`engine/tables/` renders tables but cannot find one.** Masking, HTML→ASCII rendering, the
  geometry model, and false-table rejection are landed and wired: `normalize_document` runs
  `html_project` on the HTML branch and populates `NormalizationResult.table_geometries` from
  real conversion. The resolver that decides where an *untagged* table begins and stops is
  slice 6. See `engine/tables/README.md`.
- **`normalize_document` runs three of twelve stages.** `decode`, `html_project`, and
  `page_policy` are complete and production-wired. Cover boundary, checkmarks, healing,
  whitespace, TOC, body start, reflow, and closing are slices 5–7.
- **`get_plugin` ignores its argument.** `edgar_sec/engine/forms/plugins/registry.py:19-21`
  returns a fresh `FormPlugin(form=form or "UNKNOWN", evaluator=None)` for every input;
  there is no registry. `pipelines/document_storage/processor.py:155` calls it and reads
  neither field.
- **Historical, now closed.** `engine/tables/ascii_html/` did not import at all until
  2026-09-29 — v1's `defs/tables/tokens.py` facade was never ported, so five sub-modules
  imported four definitions that existed nowhere. Fixed by porting them into
  `engine/tables/numeric_cells.py`. `tests/test_package_imports.py` now fails the gate if
  any package stops importing. The package itself was removed in commit `079010e` and
  returns with sub-plan 04.
- Two further contract violations and several coverage gaps are catalogued in
  `roadmap/refactor_v2/v2_refactor_roadmap.md` §9.7 and the `Deliberate gaps`
  section of each package README.
