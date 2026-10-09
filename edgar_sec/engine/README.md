# `edgar_sec/engine` — Layer 3: transformation of SEC payloads

Layer 3 turns raw filing text into structured, canonical form: SGML unpacking, HTML
projection, page-furniture removal, form-alias resolution, cover-boundary detection,
checkmark solving, ASCII reflow, table protection and reconstruction, and candidate
selection.

## Purpose

Engine is where filing-shaped text becomes filing-shaped *meaning*: which lines are cover
metadata, where the body begins, which statutory checkboxes were ticked, how a hard-wrapped
80-column ASCII page is un-wrapped without scrambling a table.

This layer does not fetch anything (that is `edgar_sec/infra/sec_http`), does not own
artifact layout (that is `edgar_sec/infra/storage` and `edgar_sec/pipelines`), and does not
own the domain vocabulary or schemas it consumes (that is `edgar_sec/domain`).

## Layer map

| Sub-package | Responsibility |
| :--- | :--- |
| `selection/` | Quota-driven candidate selection for the filing-catalog pipeline. |
| `submissions/` | SEC submissions JSON to canonical row dicts. |
| `index_pages/` | SEC filing index-page HTML to typed inventory outcomes. See `index_pages/README.md`. |
| `company_family/` | Deterministic company-family name normalization and clustering. |
| `document/` | Input preparation, SGML unpacking, HTML cleaning/projection, page markers, signatures, whitespace. See `document/README.md`. |
| `tables/` | Table masking, HTML→ASCII rendering and geometry, false-table rejection, boundary resolution, financial-cell vocabulary. See `tables/README.md`. |
| `reflow/` | Conservative ASCII reflow, untagged-table tagging, line-coordinate mapping. See `reflow/README.md`. |
| `forms/` | Document normalization and its result record. See `forms/README.md`. |
| `forms/plugins/` | The `FormPlugin` SPI, the family registry, and the per-family evaluators. |

Each package's README carries its module→responsibility layout and its own deliberate gaps.

## Contracts

- **Layer 3 may import only from `infra`, `domain`, and `foundation`.** It must never import
  from `pipelines`. This is enforced by the `layer-boundary` scanner
  (`edgar_sec/foundation/scanners/layers.py`) and run by `check.py --scan`; it is a hard
  gate failure, not a lint warning. Within the layer, sibling sub-packages may import each
  freely — `forms/` imports from `document/`, `reflow/`, and `tables/`.
- **Purity, with named exceptions.** The transformation packages (`document/`, `tables/`,
  `reflow/`, `forms/`, `submissions/`, `index_pages/`) do not fetch, do not write artifacts, and do
  not read ambient configuration. Two sub-packages are deliberate exceptions, and both
  go through `infra/storage` rather than owning a write path of their own —
  `selection/features.py` materialises a feature snapshot and `selection/policy.py`
  serializes a policy document, while `company_family/clustering.py` reads a
  company-profiles Parquet in `from_existing_profiles`.
- **Explicit configuration travels as arguments, never as reads.** Effective settings come
  in as parameters or typed policy objects; the engine does not resolve the environment.
  This is what lets `AGENTS.md` §3 confine `os.environ` access to
  `edgar_sec/foundation/runtime/env.py` (the `environment-access` scanner).
- **Form-specific behaviour arrives as data, never as a subclass.** `engine/forms/cover/profiles.py`
  compiles one `CoverProfile` per family and `engine/forms/normalize.py` reads it, so the
  per-family variance lives in data and the stage order lives in exactly one place.
- **No backward-compatibility shims.** `AGENTS.md` §1.1 forbids alias modules and
  forwarding functions. Every relocation in this layer updated its call sites in the same
  change.
- **The layer root is not the entry point.** There is no `normalize_document` here; the
  single functional entry point is `normalize_document` in `edgar_sec/engine/forms/normalize.py`,
  called by the document-storage pipeline.

## Deliberate gaps

- **No hierarchical document tree.** This layer works on flat line-offset text frames;
  section structure is recovered as a cover boundary, a TOC span, and a body start rather
  than as a recursive section tree.
- **No HTTP client, cache, or rate limiter.** Those live in `edgar_sec/infra/sec_http`.
- **No artifact layout ownership.** The transformation packages produce values, and
  `edgar_sec/pipelines` decides where they land. `selection/` materializes its feature
  snapshot through `infra/storage`, under the pipeline's chosen layout.
- **No CLI entry point.** Package-level entry points belong to `edgar_sec/pipelines`.

Per-package omissions are documented in each package's own README.
