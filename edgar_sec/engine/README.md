# `edgar_sec/engine` — Layer 3: pure transformation of SEC payloads

Layer 3 turns raw filing text into structured, canonical form. It is the layer where filing
algorithms live — and it is **partially built**. Unpacking SGML bundles, `selectolax` tree
access, form-alias resolution, and candidate selection are here. Page-furniture removal,
cover-boundary detection, checkmark solving, ASCII reflow, and table reconstruction are
**not**: those packages were removed in commit `079010e` and are being re-landed by
roadmap sub-plans 03 and 04. §"Deliberate gaps" says exactly what is missing.

The layer owns no I/O of consequence: no network, no filesystem writes, no ambient state.
The one place that composes its algorithms into an ordered chain is
`edgar_sec/engine/forms/normalize.py` — which today composes a single decode stage.

## Purpose

Engine is where filing-shaped text becomes filing-shaped *meaning*: which lines are cover
metadata, where the body begins, which statutory checkboxes were ticked, how a hard-wrapped
80-column ASCII page is un-wrapped without scrambling a table. Every module in this layer
is a pure function of its inputs.

This layer does not fetch anything (that is `edgar_sec/infra/sec_http`), does not write
artifacts (that is `edgar_sec/infra/storage` and `edgar_sec/pipelines`), and does not own
the domain vocabulary or schemas it consumes (that is `edgar_sec/domain`).

## Layer map

| Sub-package | Files | Loc | Responsibility |
| :--- | ---: | ---: | :--- |
| `selection/` | 6 | 2,316 | Stratified candidate selection for the filing-catalog pipeline: declarative policy, feature snapshot, deficit fill. |
| `submissions/` | 5 | 832 | SEC submissions JSON to canonical row dicts. |
| `company_family/` | 3 | 710 | Deterministic company-family name normalization and clustering. |
| `document/` | 24 | 3,966 | Input preparation, SGML unpacking, HTML cleaning/projection, page markers, signatures, whitespace. See `document/README.md`. |
| `tables/` | 42 | 7,180 | Table masking, HTML→ASCII rendering and geometry, false-table rejection, boundary resolution, financial-cell vocabulary. See `tables/README.md`. |
| `forms/` | 3 | 216 | The normalization composition seam — stage order and the result record. See `forms/README.md`. |
| `forms/plugins/` | 3 | 191 | The `FormPlugin` SPI, the family registry, and the per-family evaluators. |

File and loc counts are `wc -l` totals over the `*.py` directly in each directory,
measured on disk; they exclude `__pycache__/`. `document/`, `tables/`, `forms/`, and
`forms/plugins/` are low because the algorithms those packages used to contain were deleted in
commit `079010e` and are being re-landed by roadmap
`roadmap/refactor_v2/phase_2_5/03_engine_document_and_reflow.md` (03) and
`04_engine_tables_and_forms.md` (04). See each package's "Deliberate gaps" section for
exactly which capabilities are absent; do not read the low counts as a small design.

## Contracts

- **Layer 3 may import only from `infra`, `domain`, and `foundation`.** It must never import
  from `pipelines`. This is enforced by the `layer-boundary` scanner
  (`edgar_sec/foundation/scanners/layers.py`) and run by `check.py --scan`; it is a hard
  gate failure, not a lint warning. Within the layer, sibling sub-packages may import each
  freely — `forms/` imports from `document/`.
- **Purity.** The engine is documented as "pure, side-effect-free transformation"
  (`edgar_sec/engine/__init__.py`). Functions do not fetch, do not write artifacts, and do
  not read ambient configuration.
- **Explicit configuration travels as arguments, never as reads.** Effective settings come
  in as parameters or typed policy objects; the engine does not resolve the environment.
  This is what lets `AGENTS.md` §3 confine `os.environ` access to
  `edgar_sec/foundation/runtime/env.py` (the `environment-access` scanner).
- **No backward-compatibility shims.** `AGENTS.md` §1.1 forbids alias modules and
  forwarding functions. Every relocation in this layer updated its call sites in the same
  change.
- **The layer root is not the entry point.** There is no `normalize_document` here; the
  single functional entry point is `edgar_sec/engine/forms/normalize.py:93`, called by
  `pipelines/document_storage/processor.py:153` and `review_artifacts.py:291`.

## Public surface

- `normalize_document` — decode a raw payload and return a `NormalizationResult`.
  `edgar_sec/engine/forms/normalize.py:93`.
- `NormalizationResult` — text plus the structural facts discovered while producing it.
  `edgar_sec/engine/forms/normalize.py:77`. Fields: `text`, `family`, `representation`,
  `cover_boundary`, `cover_boundary_detected_line`, `cover_start_detected_line`,
  `body_start`, `closing_span`, `page_analysis`, `reflow`, `stage_trace`.
- `CoverBoundary` / `BodyStart` / `ClosingSpan` / `ReflowDecision` / `ReflowSummary` /
  `BoundaryMethod` — the structural fact records. `normalize.py:28`, `:39`, `:52`, `:62`,
  `:70`, `:16`.
- `get_plugin` — resolve a raw form string to its `FormPlugin`, falling back to the generic
  one. `edgar_sec/engine/forms/plugins/registry.py:19`.
- `unpack_sgml_submission` / `resolve_target_sub_document` /
  `extract_target_sub_document` / `find_sub_document` / `has_sgml_documents` /
  `strip_pem_envelope` / `SgmlSubDocument` — the SGML envelope surface.
  `edgar_sec/engine/document/unpacker.py:100`, `:182`, `:232`, `:158`, `:93`, `:64`, `:39`.
- `parse_html` / `FastHtmlNode` / `FastHtmlTree` / `BLOCK_TAGS` — the HTML tree surface.
  `edgar_sec/engine/document/html.py:142`, `:33`, `:88`, `:13`.
- `PageMarkerAction` / `PageMarkerDecision` / `PageMarkerAnalysis` — the page-marker type
  vocabulary. `edgar_sec/engine/document/page_markers/models.py`.
- `analyze_page_markers` / `find_page_markers` / `is_page_marker_line` —
  `edgar_sec/engine/document/page_markers/detector.py`.
- `apply_page_markers` / `apply_text_policy` / `apply_fast_html_page_policy` /
  `apply_html_policy` — `edgar_sec/engine/document/page_markers/policy.py`.
- `analyze_repeating_headers` / `build_page_artifact_metadata` —
  `edgar_sec/engine/document/page_markers/{templates,artifacts}.py`.
- `find_table_spans` / `mask_tagged_tables` / `restore_tagged_tables` /
  `strip_table_wrapper_tags` / `ensure_table_tag_boundaries` / `TableSpan` / `ProtectedText` —
  the byte-exact table protection contract.
  `edgar_sec/engine/tables/protection/tags.py`.
- `SENTINEL_PREFIX` / `SENTINEL_SUFFIX` / `TAGGED_TABLE_OPEN_RE` / `TAGGED_TABLE_CLOSE_RE` — the
  masking sentinel and table-tag vocabulary.
- `convert_html_table` / `convert_html_tables_to_ascii_with_metadata` / `TableGeometry` /
  `is_false_grid` / `cleanup_false_tables_with_metadata` / `normalize_hybrid_pre_text` — the
  HTML→ASCII table pipeline. `edgar_sec/engine/tables/ascii_html/converter.py`,
  `ascii_html/model.py`, `false_tables/{detector,unwrapper}.py`, `hybrid/masker.py`.

There is no barrel re-export anywhere in this layer. `edgar_sec/engine/__init__.py` is a
one-line docstring and every sub-package `__init__.py` likewise, per `AGENTS.md` §1.2.
Consumers import from the leaf module.

## Tests

The test tree mirrors the source tree, package for package (`AGENTS.md` §6):

- `tests/engine/selection/`
- `tests/engine/submissions/`
- `tests/engine/company_family/`
- `tests/engine/document/`
- `tests/engine/document/page_markers/`
- `tests/engine/reflow/`
- `tests/engine/tables/`

**`document/` and `forms/` have no test directories at all.** Commit `079010e` deleted
`tests/engine/document/` (its `__init__.py` and eight test files) and
`tests/engine/forms/` (its `__init__.py` and 15 test files). Both packages still have
production callers in `pipelines/document_storage/`, so this is a live `AGENTS.md` §6
violation, not an absence of requirement. Re-landing is in scope for sub-plans 03 and 04
respectively.

## Deliberate gaps

- **The layer does not yet do most of what its own summary claims.** It does not strip
  page furniture, detect cover and body boundaries, solve cover checkboxes, reflow ASCII
  prose, or reconstruct tables. `engine/reflow/`, `engine/forms/cover/`,
  `engine/forms/checkmarks/`, and `engine/forms/evaluators/` do not exist, and
  `engine/tables/` holds only `protection/`. Per-package detail is in each package's README.
- **`engine/tables/` renders tables but cannot yet find one.** The masking protocol, HTML→ASCII
  renderer, geometry model, and false-table detector are landed, tested, and parity-verified.
  Deciding where an *untagged* table begins and stops — `resolver.py`, `structural.py`,
  `policy/` — is slice 6, whose only caller is the reflow classifier. Until then the package
  converts tables that are already marked up and cannot find one in aligned prose.
- **`normalize_document` is a decode, not a normalization.** It runs a three-tier decode
  (`utf-8` → `cp1252` → `latin-1`), resolves the form alias, sniffs `html` vs `ascii` by
  substring, and returns a `CoverBoundary(method=NONE, confidence=0.0)` plus
  `stage_trace=["decode"]` (`normalize.py:103-135`). `body_start`, `closing_span`,
  `page_analysis`, and `reflow` are always `None`, and no stage ever produces a line
  coordinate other than 0. Sub-plans 03 and 04 replace it.
- **`ReflowDecision` and `ReflowSummary` are never constructed.** They are declared at
  `normalize.py:62` and `:70` and nothing in `edgar_sec/` builds one. `ReflowSummary.decisions`
  is typed `list[...]` inside a `slots=True` frozen dataclass, so it is also mutable-shared
  state — safe only because nothing populates it.
- **`BoundaryMethod` has six members and produces one.** `normalize.py:16-24` declares
  `TOC_TRANSITION`, `INCORPORATED_REFERENCE`, `PART_FALLBACK`, `ITEM_FALLBACK`, and
  `PAGE_MARKERS` alongside `NONE`; only `NONE` is ever emitted. The five others describe
  the v1 cover-boundary signal set that sub-plan 04 restores.
- **`engine/forms/plugins/registry.py` is 27 lines and resolves to a single no-op plugin.**
  `get_plugin` returns `_default_plugin()` for every form; there is no per-form plugin
  registry, and `domain/forms/families/{annual,quarterly,current}/` — which do carry
  the evidence packs — have no engine-side consumer. Sub-plan 04 §1.4 is scoped to close
  this.
- **No HTTP client, no cache, no rate limiter here.** Those live in
  `edgar_sec/infra/sec_http`. A reader looking for "how do we talk to EDGAR" in this
  layer is looking in the wrong place.
- **No artifact writing.** No engine module writes Parquet, JSON, or a DuckDB file. The
  engine produces values; `edgar_sec/pipelines` decides where they land.
- **No `run.py` or CLI entry point.** `check.py --test` runs the suite; there is no
  `python -m edgar_sec.engine` invocation. Package-level entry points belong to
  `edgar_sec/pipelines`.
- **No hierarchical document tree.** This layer works on flat line-offset text frames.
  Roadmap `v2_refactor_roadmap.md` §3 defers recursive sectioning to Phase 03 (TOC
  Spine); v2 deliberately kept the 1D representation to avoid coordinate drift.
- **No per-form pipeline subclasses.** v1 had a `ProfileDrivenPipeline` class per family.
  The intent is one chain in `normalize.py` reading per-form data from a plugin, so the
  stage order lives in exactly one place. That is a substitution, not a missing feature —
  though the chain it substitutes for does not exist yet.
