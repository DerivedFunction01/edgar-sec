# `edgar_sec/engine` — Layer 3: pure transformation of SEC payloads

Layer 3 turns raw filing text into structured, canonical form. It owns the algorithms —
unpacking SGML bundles, stripping page furniture, detecting cover and body boundaries,
solving cover checkboxes, reflowing ASCII prose, and reconstructing tables — and it owns
no I/O of consequence: no network, no filesystem writes, no ambient state. The one place
that composes those algorithms into an ordered chain is `edgar_sec/engine/forms/normalize.py`.

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
| `document/` | 7 | 1,981 | SGML unpacking, HTML tag normalization, page-marker analysis, signature and whitespace primitives. |
| `forms/` | 25 | 5,181 | The form-normalization composition seam, cover boundary detection, checkmark solving, evaluators, and the `FormPlugin` SPI. See `forms/README.md`. |
| `reflow/` | 7 | 2,339 | Conservative ASCII prose reflow, layout-gap relaxation, and the line-anchor mapper used after every renumbering. |
| `selection/` | 6 | 2,192 | Stratified candidate selection for the filing-catalog pipeline: declarative policy, feature snapshot, deficit fill. |
| `submissions/` | 5 | 839 | SEC submissions JSON to canonical row dicts. |
| `tables/` | 26 | 6,791 | Table detection, ASCII/HTML grid resolution, `<TABLE>` masking, and TOC-row primitives. |
| `company_family/` | 3 | 710 | Deterministic company-family name normalization and clustering. |

File and loc counts are `wc -l` totals over `edgar_sec/engine/<pkg>/*.py`, measured on
disk; they exclude `node_modules/`, `__pycache__/`, and `scratch/`.

## Contracts

- **Layer 3 may import only from `infra`, `domain`, and `foundation`.** It must never import
  from `pipelines`. This is enforced by the `layer-boundary` scanner
  (`edgar_sec/foundation/scanners/layers.py`) and run by `check.py --scan`; it is a hard
  gate failure, not a lint warning. Within the layer, sibling sub-packages may import each
  freely — `forms/` imports from `document/`, `reflow/`, and `tables/`.
- **Purity.** The engine is documented as "pure, side-effect-free transformation"
  (`edgar_sec/engine/__init__.py`). Functions do not fetch, do not write artifacts, and do
  not read ambient configuration.
- **Explicit configuration travels as arguments, never as reads.** Effective settings come
  in as parameters or typed policy objects; the engine does not resolve the environment.
  This is what lets `AGENTS.md` §3 confine `os.environ` access to
  `edgar_sec/foundation/runtime/env.py` (the `environment-access` scanner).
- **Coordinate honesty is a contract, not an internal detail.** Any stage that renumbers
  lines must publish a mapper. `edgar_sec/engine/reflow/types.py::build_line_mapper` is the
  mechanism, and `edgar_sec/engine/forms/normalize.py::_remap_line_anchors` is the only
  caller that translates structural anchors across a reflow.
- **No backward-compatibility shims.** `AGENTS.md` §1.1 forbids alias modules and
  forwarding functions. Every relocation in this layer (v1 `defs/sec_forms/*` →
  `engine/forms/*`, v1 `defs/sec_forms/page_markers/` → `engine/document/page_markers.py`)
  updated its call sites in the same change.

## Public surface

- `DocumentNormalizer` — the shared normalization chain for one form family. `edgar_sec/engine/forms/normalize.py:213`.
- `normalize_document` — the single entry point the storage pipeline and the review tool both call; there is no per-form pipeline class to choose between. `edgar_sec/engine/forms/normalize.py:381`.
- `NormalizationResult` — normalized text plus the structural facts discovered while producing it (cover boundary, body start, closing span, reflow trace, stage trace). `edgar_sec/engine/forms/normalize.py:79`.
- `get_plugin` — resolve a raw form string to its `FormPlugin`, falling back to the generic one. `edgar_sec/engine/forms/plugins/registry.py:111`.
- `find_cover_boundary` — conservative exclusive end of the cover page. `edgar_sec/engine/forms/cover/boundary.py:440`.
- `find_body_start` — first validated body region after cover material. `edgar_sec/engine/forms/cover/body_start.py:187`.
- `find_closing_span` — conservative start of the signature / exhibit-index tail. `edgar_sec/engine/forms/cover/closing.py:55`.
- `infer_cover_checkmarks` — extract and solve the active cover checkbox groups. `edgar_sec/engine/forms/checkmarks/solver.py:593`.
- `reflow_ascii` — the ASCII reflow entry point. `edgar_sec/engine/reflow/engine.py:342`.
- `apply_text_policy` — validated page-furniture removal, returning text plus `PageMarkerAnalysis`. `edgar_sec/engine/document/page_markers.py:442`.
- `build_line_mapper` — construct the post-reflow line translator. `edgar_sec/engine/reflow/types.py:61`.

There is no barrel re-export anywhere in this layer. `edgar_sec/engine/__init__.py` is a
one-line docstring and every sub-package `__init__.py` likewise, per `AGENTS.md` §1.2.
Consumers import from the leaf module.

## Tests

The test tree mirrors the source tree, package for package (`AGENTS.md` §6):

- `tests/engine/forms/`
- `tests/engine/forms/cover/`
- `tests/engine/forms/evaluators/`
- `tests/engine/forms/plugins/`
- `tests/engine/document/`
- `tests/engine/reflow/`
- `tests/engine/tables/`
- `tests/engine/selection/`
- `tests/engine/submissions/`
- `tests/engine/company_family/`

## Deliberate gaps

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
  v2 keeps one chain in `normalize.py` and reads per-form data from a plugin, so the stage
  order lives in exactly one place. That is a substitution, not a missing feature.
- **`edgar_sec/engine/forms/cover/extractors.py` has no production caller.** It is verified
  only by its own test. It is the surviving universal cover-field extractor surface (EIN,
  commission file number, fiscal period, company-name matching) and is kept as the landing
  point for callers that need it, but nothing in `edgar_sec/` calls it today.
