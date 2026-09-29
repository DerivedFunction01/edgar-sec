# `edgar_sec/engine/forms/evaluators` — per-form stub and delegation triage

Four modules: one shared input contract, three form-specific decisions. An evaluator answers
a single question — is this fetched primary document a self-contained filing, or a stub that
delegates substantive disclosure to an exhibit? — and returns an `EvaluatorDecision` that
tells the pipeline whether to fetch a second time.

It does not normalize. It runs *after* `edgar_sec/engine/forms/normalize.py` has produced
clean text, because deciding a document is a stub requires having normalized it.

## Purpose

Emit one reproducible, cheap verdict per document. The decision is a pure function of
normalized text plus a few scalars, and it drives a targeted second fetch, so it must be
affordable to run on every document in a corpus.

This package does not perform the refetch. It returns `DecisionAction.REFETCH_SUB_DOC` with
a `target_exhibit`; `edgar_sec/pipelines/document_storage/processor.py:157-158` reads the
decision off the plugin and the pipeline owns the fetch.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `base.py` | The shared input contract and the two decision constructors. Owns the XBRL mandate year and the size ceilings. |
| `annual.py` | 10-K / 20-F: Exhibit 13 incorporation delegation. The only evaluator that can emit `REFETCH_SUB_DOC`. |
| `quarterly.py` | 10-Q: cheap early exits; a 10-Q has no incorporation-stub structure. |
| `current_report.py` | 8-K: a pass-through. |

`__init__.py` is a six-line docstring and nothing else — no re-exports, per `AGENTS.md` §1.2.
`edgar_sec/engine/forms/plugins/registry.py` binds these three functions through
`_lazy_evaluator` (`registry.py:48-55`), so importing the registry does not import this
package and the engine's import graph stays acyclic.

## Contracts

- **The input contract is closed.** `EvaluatorInput` (`base.py:25`) is a frozen dataclass with
  exactly four fields: `text`, `raw_text`, `has_html_tags`, `filing_year`. The docstring
  states the obligation plainly: "What an evaluator is allowed to look at." An evaluator that
  reaches outside those four fields has broken the contract.
- **Accept both a bare string and a record.** `EvaluatorInput.coerce` (`base.py:34-39`) lets
  a caller pass raw text and get a record back, treating the payload as both the cleaned and
  the raw text. Every `evaluate_*` entry point calls it first, so both call styles work.
- **Provenance comes from the caller, not from parsing.** `filing_year` is an input. An
  evaluator never infers the filing year from the text; `is_post_xbrl` (`base.py:46-49`)
  compares the supplied year against `XBRL_MANDATE_YEAR = 2012` and returns `False` when no
  year was given, so an unknown year falls through to the content tier rather than assuming
  modern.
- **Size ceilings are format-aware.** `above_size_ceiling` (`base.py:52-56`) uses
  `HTML_SIZE_CEILING = 750_000` when `has_html_tags` is set and `ASCII_SIZE_CEILING = 300_000`
  otherwise, measured on `raw_text or text`. The asymmetry is deliberate and stated at
  `base.py:19-20`: HTML filings run several times larger than ASCII ones for the same content.
- **Every decision carries a reason and a category.** Both constructors in `base.py` require
  a `reason` and a `category`; `refetch_exhibit` additionally pins `confidence=1.0` and
  `is_stub=True` (`base.py:71-86`). A verdict without a reproducible reason would make the
  second fetch unauditable, which the module docstring names as the reason evaluators must be
  cheap *and* explainable.
- **The XBRL bypass is Tier 1 everywhere, and it is a bypass, not a heuristic.** Post-2011
  periodic filings carry their financial statements inline and cannot be incorporation stubs.
  `annual.py:57-63` and `quarterly.py:23-28` both return `PROCEED` with category
  `post_2011_xbrl_full` before touching the text. `annual.py:58-59` states the arithmetic
  consequence: zero text operations for roughly 65% of filings.
- **A bare Exhibit 13 mention is not a stub.** The annual evaluator requires an Exhibit 13
  anchor *and* a delegation verb within `_DELEGATION_WINDOW = 300` characters
  (`annual.py:79-106`). Exhibit 13 in isolation is almost always the Item 15 exhibit index,
  which is reported as `exhibit_index_only` with a `PROCEED` (`annual.py:108-113`). This
  is the load-bearing rule of the whole module and its docstring says why (`annual.py:5-9`).
- **The 10-Q evaluator cannot emit a refetch.** `quarterly.py:37-42` documents the
  reasoning: a 10-Q has no incorporation-stub structure in the corpus, so there is no
  exhibit to refetch, and every path terminates in `PROCEED`.
- **The 8-K evaluator is a pass-through by design.** `current_report.py:1-8` states it: an
  8-K body is a short item list, its exhibits are referenced rather than incorporated, and
  the exhibits that matter (Item 9.01 lists) are indexed inside the same document. It
  still coerces its input (`current_report.py:20`) so a malformed payload fails the same way
  as it would in the other evaluators.

## Public surface

- `EvaluatorInput` — the closed input record, with `coerce`, `body_text`, `is_post_xbrl`, and `above_size_ceiling`. `edgar_sec/engine/forms/evaluators/base.py:25`.
- `proceed` — construct a `PROCEED` decision with a reason and category. `edgar_sec/engine/forms/evaluators/base.py:59`.
- `refetch_exhibit` — construct a `REFETCH_SUB_DOC` decision targeting a named exhibit, with arbitrary `**metadata`. `edgar_sec/engine/forms/evaluators/base.py:71`.
- `XBRL_MANDATE_YEAR`, `HTML_SIZE_CEILING`, `ASCII_SIZE_CEILING` — the three tuning constants, exported from their defining module. `edgar_sec/engine/forms/evaluators/base.py:17`, `:21`, `:22`.
- `evaluate_annual` — 10-K / 20-F Exhibit 13 delegation. `edgar_sec/engine/forms/evaluators/annual.py:53`.
- `RE_EX13` / `RE_DELEGATION_VERB` — the two compiled patterns, both built through `build_alternation`. `edgar_sec/engine/forms/evaluators/annual.py:29` and `:45`.
- `evaluate_quarterly` — 10-Q, early exits only. `edgar_sec/engine/forms/evaluators/quarterly.py:19`.
- `evaluate_current_report` — 8-K, always proceeds. `edgar_sec/engine/forms/evaluators/current_report.py:18`.

`DecisionAction` and `EvaluatorDecision` are **not** defined here. Both live in Layer 1 at
`edgar_sec/domain/forms/decisions.py` (`DecisionAction` at line 10, `EvaluatorDecision` at
line 19), and every module in this package imports them from there. This is deliberate and
follows AGENTS.md §1.2: the decision vocabulary is domain data, so consumers import it from
the domain leaf module rather than through a package re-export. Do not look for a local
re-export; there is none.

The three entry-point names are the plugin contract, not an implementation detail:
`registry.py:68-98` binds them by string module path and attribute name, so renaming one
breaks the registry silently at call time rather than at import time.

## Tests

- `tests/engine/forms/evaluators/test_base.py` — 7 tests over the input contract and the two constructors.
- `tests/engine/forms/evaluators/test_annual.py` — 10 tests, including the Exhibit-13-without-delegation case.
- `tests/engine/forms/evaluators/test_quarterly.py` — 5 tests.
- `tests/engine/forms/evaluators/test_current_report.py` — 3 tests.

## Deliberate gaps

- **Only Exhibit 13 delegation is modelled.** v1 had per-family evaluators under
  `defs/sec_forms/forms/*/evaluator.py`; v2's entire triage surface is the 10-K Exhibit 13
  rule. A pre-2012 10-K that delegates to any *other* exhibit is not detected, and
  `refetch_exhibit` is the only constructor in the package that can produce
  `REFETCH_SUB_DOC`. This is a real narrowing, not an oversight — the roadmap records the
  v1 source as 347 loc, not the ~600 originally estimated
  (`phase_2_5/04_engine_tables_and_forms.md` M4.4).
- **`DecisionAction.SKIP_HARD_STUB` is never emitted.** The enum member exists at
  `edgar_sec/domain/forms/decisions.py:15`, but no module in this package constructs a
  decision with it. A caller must not write a branch that expects it; today the reachable
  actions are `PROCEED` and `REFETCH_SUB_DOC`.
- **No image, font, or layout analysis.** An evaluator sees text. It never sees the HTML
  source, the DOM, or a page image — `has_html_tags` is a single boolean, not a rendered
  representation. A delegation stated only in a graphic is invisible.
- **No cross-document or cross-chunk state.** Each decision is a pure function of one
  document's normalized text and its `filing_year`. There is no accumulation across a filing,
  no cross-check against the exhibit index, and no use of a previously cached decision. The
  module docstring names the reason: a decision must be reproducible, which is incompatible
  with hidden state.
- **The roadmap's target API is not what shipped.** `phase_2_5/04_engine_tables_and_forms.md`
  §3.3 sketched an abstract `FormPlugin` with `evaluate()` and `normalize()` methods taking a
  `DocumentRepresentation`. What shipped is a frozen dataclass carrying data and callables
  (`edgar_sec/engine/forms/plugins/models.py`) and a single linear chain. The spirit —
  replacing hardcoded conditionals with a pluggable seam — was kept; the class-based
  inheritance sketch was not. Likewise, the same roadmap's §1 objective promises plugins for
  `6-K`, Form 3/4/5, and Form 13F; only 10-K, 20-F, 10-Q, and 8-K are registered.
- **No `form_family` narrowing in the quarterly or current-report evaluators.** Both accept
  any payload. Whether they are reached at all is decided by which plugin the registry
  returned, not by a check inside the evaluator — so a
  `register_plugin("10-Q", <plugin with evaluate_quarterly>)` override would run the 10-Q
  evaluator for a non-10-Q form without complaint.
- **The 65% XBRL bypass figure is an estimate, not an instrumented metric.** It is stated in
  the `annual.py:58-59` comment; no counter records it. Do not read it as a measured
  corpus statistic.
