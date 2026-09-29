# `edgar_sec/engine/forms` — the composition seam for SEC form normalization

This package owns the *order* in which form normalization happens. Every other module in
the subtree already existed as a pure function; nothing composed them. `normalize.py` is
the only place the stage order is written, and that ordering is the load-bearing invariant
of the whole engine: reflow must never run before table protection, and the cover boundary
must be detected on the same coordinate frame the checkmark rewriter edits.

It is not a form *taxonomy*. Item lists, cover label vocabulary, checkbox schemas, and form
aliases all live in `edgar_sec/domain/forms/`, one layer down. This package supplies the
data and the hooks; the shared chain does the work.

## Purpose

Turn one raw filing payload (bytes, text, or an SGML bundle) into normalized text plus the
structural facts discovered while producing it: where the cover ends, where the body
begins, what the checkmark solver concluded, and which lines the closing span occupies.

This package does not fetch payloads, does not write artifacts, and does not choose between
form families — a caller passes a form string and `get_plugin` resolves it.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalize.py` | The composition seam. `DocumentNormalizer` runs the ten ordered stages; `normalize_document` is the single functional entry point; `NormalizationResult` carries the discovered structure and the per-stage trace. |

The four sub-packages supply stages to that chain:

| Sub-package | Files | Loc | Role in the chain |
| :--- | ---: | ---: | :--- |
| `cover/` | 10 | 2,413 | Stages 4, 8, 10: cover region detection, forward body anchor, closing tail span. Plus the structural and lexical primitives those three need. |
| `checkmarks/` | 5 | 1,868 | Stages 5 and 6: statutory cover-page checkbox extraction, quadratic-penalty constraint solve, and canonical rewrite. |
| `evaluators/` | 5 | 290 | Per-form stub/delegation triage. Runs *after* normalization, not inside the chain. |
| `plugins/` | 3 | 196 | The `FormPlugin` SPI and its registry — the data and hooks the chain consults. |

## The stage order

From `normalize.py:9-20` and the `DocumentNormalizer.normalize` body
(`normalize.py:232-346`), in execution order:

1. `unpack` — SGML bundle / primary sub-document selection (`_unpack`, `normalize.py:151`).
2. `html_clean` — tag decomposition; tagged tables are masked and restored internally
   (`_html_clean`, `normalize.py:179`, delegating to
   `edgar_sec/engine/document/html.py::normalize_html_document`).
3. `page_policy` — validated page-furniture removal via `apply_text_policy`.
4. `boundary` — cover region detection, scoped by the plugin's `boundary_signals`.
5. `checkmark` — Yes/No pair normalization, constraint solve, rewrite. Skipped entirely when
   the plugin's `cover_schema` is `None`.
6. `content` — the per-form `transform_content` hook, when the plugin supplies one.
7. `whitespace` — final line/bullet/blank-run normalization.
8. `body_start` — structural body anchor after the cover, when `enable_body_start` is set.
9. `reflow` — ASCII block reflow, with all line anchors remapped. ASCII only; skipped for HTML.
10. `closing` — signature / closing tail span, searched from one line past the first body unit.

Two ordering facts are load-bearing and are not incidental:

- **The checkmark solver runs on the pre-reflow frame.** Reflow renumbers lines, and a line
  it collapsed into a longer one cannot be mapped back. `normalize.py` therefore records the
  boundary as detected in `cover_boundary_detected_line` and `cover_start_detected_line`,
  separate from `cover_boundary.end_line`, which is reported in the final text's coordinates
  (`NormalizationResult`, `normalize.py:101-108`).
- **The yes/no pair collapse is bounded to the cover region** (`_normalize_yes_no_pairs`,
  `normalize.py:184`). It only touches lines between `boundary.start_line` and
  `boundary.end_line`, so body prose is never rewritten by a cover-scoped rule.

## Contracts

- **One entry point, no per-form pipeline class.** `normalize_document(payload, form=...)`
  is what the storage pipeline and the review tool both call (`normalize.py:381`). A caller
  does not select a pipeline; it selects a form.
- **Every stage is a pure function of the previous text.** A stage returns new text; nothing
  observes the document out of band. This is what makes the golden fixtures meaningful.
- **An empty `boundary_signals` tuple disables cover parsing.** `find_cover_boundary` returns
  a `BoundaryMethod.DISABLED` unknown boundary when `signals` is empty
  (`edgar_sec/engine/forms/cover/boundary.py:454-455`). This is deliberate: the checkmark
  solver must never be handed a whole document as its "cover region".
- **Unknown forms degrade, they do not raise.** `get_plugin` returns the generic plugin for
  an unmodeled form, so a new SEC form type yields no cover handling rather than an exception
  (`plugins/registry.py:111-133`).
- **Obligations on callers.** Callers must supply a form string that
  `edgar_sec/domain/forms/families.py::resolve_alias` understands if they want form-specific
  behaviour, and must treat `cover_boundary.end_line` as approximate: every `CoverBoundary`
  is constructed with `approximate=True` (`cover/models.py:74`). The name of the result field
  is the contract, not a caveat to be ignored.
- **Stage trace is bounded and hashed once.** `_StageTracer` (`normalize.py:115`) recomputes
  a stage's `sha256_text` identity only when the text object actually changed, so an
  unchanged stage costs a comparison rather than a full digest. `stage_trace` records
  `stage`, `text_identity`, `line_count`, and `char_count` per stage, which is what localizes
  a regression to one stage.

## Public surface

- `DocumentNormalizer` — the shared normalization chain for one form family; takes a `FormPlugin`, or a `form` string to resolve one. `edgar_sec/engine/forms/normalize.py:213`.
- `normalize_document` — the single functional entry point. `edgar_sec/engine/forms/normalize.py:381`.
- `NormalizationResult` — frozen result record; `is_html` is the representation predicate. `edgar_sec/engine/forms/normalize.py:79`.
- `build_line_mapper` — the line translator every remap depends on, consumed here at `normalize.py:322`. `edgar_sec/engine/reflow/types.py:61`.
- `sha256_text` — the streaming digest backing the stage tracer. `edgar_sec/foundation/hashing.py`.

Per AGENTS.md §1.2 there are no barrel re-exports: `edgar_sec/engine/forms/__init__.py` is a
one-line docstring, and consumers import from the leaf module
(`from edgar_sec.engine.forms.normalize import normalize_document`).

## Tests

- `tests/engine/forms/test_normalize.py` — 22 tests over the chain: stage order, HTML vs ASCII representation, boundary/checkmark scoping, anchor remapping, SGML bundle unpacking.
- `tests/engine/forms/test_normalization_goldens.py` — 4 tests that parametrize over the committed goldens in `tests/fixtures/document_storage/` and pin the chain's *outcome*.
- `tests/engine/forms/cover/` — `test_boundary.py`, `test_body_start.py`, `test_body_evidence.py`, `test_closing.py`, `test_structure.py`, `test_extractors.py`.
- `tests/engine/forms/evaluators/` — `test_base.py`, `test_annual.py`, `test_quarterly.py`, `test_current_report.py`.
- `tests/engine/forms/plugins/` — `test_models.py`, `test_registry.py`.

## Deliberate gaps

- **No v1 TOC span finder exists, and none is planned here.** v1's `defs/sec_forms/cover/toc/`
  (938 loc measured by `wc -l` across its six modules) included `find_toc_span`. That
  refinement was **not ported** — this is a dropped capability, not a relocated one. The
  `TOC_TRANSITION` signal instead uses v1's heading-based path, reusing the TOC *primitives*
  that `edgar_sec/engine/tables/toc.py` already provides
  (`looks_like_toc_row`, `looks_like_toc_tabular`, `RE_ITEM_REFERENCE`). The signal still
  fires — one signal later than v1, and without the `find_toc_span` confidence refinement
  (`cover/boundary.py:21-28`, roadmap `phase_2_5/04_engine_tables_and_forms.md` §4.3).
  Consequently, body-start detection is anchored on cover end alone: `normalize.py:29-30`
  states this directly, and `DocumentTopology` — the v1 four-zone record that carried
  `toc_start`/`toc_end` — is declared in `cover/models.py:118` but has no producer anywhere
  in `edgar_sec/` or `tests/`.
- **The tiered bag-of-words lexical engine was substituted, not ported.** v1's
  `defs/text/bow/` (1,234 loc across five modules) was a four-tier weighted engine with
  per-form packs. v2's `edgar_sec/foundation/text/automaton.py` (421 loc) compiles **one tier
  per category**, so the tier structure cannot be reproduced as written. The replacement is
  a single-tier Aho-Corasick match over the generic body-prose vocabulary in
  `edgar_sec/domain/forms/body_evidence.py`, scored onto **v1's same 0-3 scale** by
  `cover/body_evidence.py::score_body_text`. This package does consume that vocabulary —
  `cover/body_evidence.py` imports `BODY_STRONG_PHRASES`, `BODY_SOFT_PHRASES`,
  `BODY_STRONG_TERMS`, `BODY_WEAK_TERMS`, `BODY_FORWARD_TERMS`, `COVER_EXCLUSION_TERMS`, and
  `BODY_SEMANTIC_HEADINGS` from it. Per-form evidence packs (v1's `forms/annual/`,
  `forms/quarterly/`, `forms/current_report/`) do not exist in v2; the annual pack was a
  superset for every tier the boundary consults, so splitting it per form reproduced data
  without reproducing a distinction (`domain/forms/body_evidence.py:8-12`).
- **The logical-unit classifier is gone, replaced by line-level gates.** v1's `find_body_start`
  called `classify_units` to know whether a candidate line sat in a table, list, signature, or
  TOC unit. v2 approximates unit context with line-level structural and lexical predicates
  (`cover/body_start.py:20-27`). The distinctions are preserved; the unit abstraction is not.
- **No per-form pipeline subclass and no HTML-frame page-marker path.** v1 resolved page
  markers on the HTML DOM via `apply_html_policy`; v2 resolves markers on the *rendered text*
  frame for both representations (`normalize.py:22-25`). Both departures are deliberate and
  documented in the module docstring rather than silently narrowed.
- **`edgar_sec/engine/forms/cover/extractors.py` has no production caller.** Its seven
  public functions are covered by `tests/engine/forms/cover/test_extractors.py` and by
  nothing else in `edgar_sec/`. It is a retained landing surface, not a dead-code oversight,
  but a reader should not assume the pipeline routes through it — it does not.
- **No filesystem, no network, no `run.py`.** This package has no entry point; it is a
  library. Its only production consumer is
  `edgar_sec/pipelines/document_storage/processor.py:30-31`, which calls `normalize_document`
  and `get_plugin`.
- **Real-filing fixtures are deferred.** Golden coverage for real historical filings
  (roadmap M6.3/M6.4/M6.5) waits on a sanitization and licensing decision that has not been
  made. What exists instead is two committed *synthetic* goldens
  (`tests/fixtures/document_storage/annual_10k_normalization.json` and `annual_10k_html.json`),
  which pin cover region, body anchor, closing span, and stage order offline in under a second
  (roadmap `phase_2_5.md` §7).
- **Solver parity against v1 is still open.** Roadmap milestone M4.6 — replaying v1's
  `test_cover_checkmark_inference.py` for 100% solver parity — is unchecked and blocked on
  the same missing real-filing fixtures.
