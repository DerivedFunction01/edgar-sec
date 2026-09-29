# `edgar_sec/engine/forms/checkmarks` — statutory cover-page checkbox inference and rewrite

Resolves the SEC cover-page checkboxes (WKSI, Shell Company, Filer Status, 404(b), error
correction, recovery analysis) when the glyphs are ambiguous, then rewrites the text so the
answer is unambiguous. Three modules, one direction of flow: extract candidates, solve a
small constrained-assignment problem, apply the decision.

It is not a parser of checkbox *meaning*. The statutory relationships live as data in
`edgar_sec/domain/forms/schemas.py`; this package executes them.

## Purpose

A single 10-K cover can carry 20+ statutory checkboxes, and the marks are frequently
contradictory: both `Yes` and `No` marked, two mutually exclusive filer categories marked,
or a Wingdings glyph whose font context is lost. The solver enumerates every assignment of
the ambiguous glyphs, scores each against the statutory constraints, and applies only the
unique lowest-penalty one.

This package does not decide where the cover is. It receives a `CoverBoundary` and stays
strictly inside `boundary.end_line` — the scoping is what stops a body-prose mark from being
"resolved" as a statutory checkbox.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `extractor.py` | `CheckboxCandidate` plus geometry- and line-level candidate extraction over the bounded cover: label/mark association in tables (left, right, above, below, same cell) and explicit Yes/No pairs in ASCII lines. |
| `solver.py` | The quadratic-penalty constraint solver. `PenaltyScorer` holds the weights; `infer_cover_checkmarks` is the entry point the chain calls, with three narrower `solve_*` entry points. |
| `rewrite.py` | Applies resolved decisions to cover prose, to masked tagged tables, and to retained table metadata. Also owns the geometry carry-forward. |
| `_yesno.py` | Private shared helpers: Yes/No word and line patterns, `normalize_yes_no_pair_line`, and the masked-offset to original-offset translator. |

`_yesno.py` is private by the leading underscore because it is a helper shared by
`extractor.py` and `rewrite.py` and is not part of the package's contract. `normalize_yes_no_pair_line`
is nonetheless imported by `edgar_sec/engine/forms/normalize.py:52` and called there directly
to collapse bare Yes/No glyph pairs inside the cover region.

## The solver

`PenaltyScorer` (`solver.py:95-106`) is a frozen dataclass of five weights, and its defaults
are the design:

| Weight | Default | Applied to |
| :--- | ---: | :--- |
| `binary_xor` | 1000 | Yes and No do not have opposite states. |
| `primary_exactly_one` | 1000 | The primary filer triplet is not exactly one. |
| `filer_laf_overlay` | 300 | Large accelerated filer used with a smaller-reporting or EGC overlay. |
| `report_period` | 700 | Annual/quarterly versus transition-period disagreement. |
| `direct_state` | 5000 | A directly-read glyph contradicts the solved target. |

`direct_state` is the heaviest weight on purpose: it means the constraint wanted a glyph to
say one thing and the glyph plainly says another, which no soft recovery should paper over.
`_result_for_scores` (`solver.py:431-438`) therefore returns `UNRESOLVED` with the diagnostic
`direct_state_conflict` rather than a decision whenever any winning hypothesis carries one.

The search space is bounded by construction. `_ambiguous_glyphs` (`solver.py:185`) collects
only glyphs whose state is unknown *and* which carry a semantic key; `_hypotheses`
(`solver.py:349`) enumerates the assignments — one glyph gives two hypotheses, two give two,
and **three or more ambiguous glyphs yields no hypotheses at all** (`solver.py:352-353`),
producing `UNRESOLVED` with the diagnostic `more_than_two_glyph_classes`. That is a
deliberate refusal to guess, not a truncation.

Constraint sources are three, all evaluated per hypothesis and merged into one penalty
(`_score_candidates`, `solver.py:362-402`):

- `binary_xor` per Yes/No question key, from `_logical_values` (`solver.py:205`).
- The filer rules, from `_evaluate_filer` (`solver.py:276`) — exactly one primary category, and the large-accelerated overlay exclusions.
- The declarative schema constraints, from `_evaluate_constraint` (`solver.py:243`), which supports the `not_both` and `implies` relations. **An unrecognised relation is a violation, not a pass** (`solver.py:256-263`): the solver reports `Unknown constraint relation` rather than silently ignoring a rule it cannot evaluate.
- The report-period rule, from `_evaluate_report_period` (`solver.py:314`), which prefers the transition report only when the transition row's `date_valid` flag is set.

Resolution is inspectable, not just decisive. `CoverCheckmarkResult` (`solver.py:82`)
carries the full `hypotheses` tuple with each `HypothesisScore`'s penalty, violations, and
satisfied constraints, plus a `diagnostics` tuple. Ties are never broken arbitrarily: a tie
returns `UNRESOLVED` with `hypotheses_tied` and every hypothesis's penalty
(`solver.py:419-429`).

A non-zero penalty is not a failure. A resolved-but-penalised result is marked with the
diagnostic `soft_penalty_recovery=<n>`, and each emitted `CheckmarkDecision` gets
`confidence=0.75` with `reason="soft_penalty_recovery"` rather than `confidence=1.0` with
`reason="constraint_solution"` (`solver.py:441-456`).

## Contracts

- **Scoping is a guarantee, not a hope.** `infer_cover_checkmarks` requires a real
  `CoverBoundary` and returns `NOT_APPLICABLE` when `boundary.end_line is None`
  (`solver.py:611-612`). `extract_cover_candidates` then masks tagged tables and walks only
  lines whose *unmasked* index is below the boundary end, translating offsets with
  `build_masked_offset_translator` so a masked line's coordinates are still measured against
  the original text (`extractor.py:573-577`). `tests/engine/forms/test_normalize.py:146`
  pins this as `test_checkmark_is_scoped_to_cover_not_whole_document`.
- **Unresolved is a first-class outcome.** Four statuses — `NOT_APPLICABLE`, `ABSENT`,
  `UNRESOLVED`, `RESOLVED` (`solver.py:52-58`). `NOT_APPLICABLE` means the family has no
  schema or lacks the group; `ABSENT` means applicable but the cover does not carry the rows;
  `UNRESOLVED` means the evidence was ambiguous or contradictory. A caller that treats
  anything other than `RESOLVED` as "do nothing" is correct.
- **The caller owns the frame; the solver does not renumber.** The solver reads line numbers
  from the boundary it is handed. Because it runs before reflow
  (`edgar_sec/engine/forms/normalize.py:275`), those are pre-reflow coordinates — which is
  the only frame in which they are stable, since reflow can renumber lines it collapses.
- **The boundary argument is validated at runtime, not by the type system.**
  `infer_cover_checkmarks` types `boundary` as `object` specifically to avoid importing the
  cover model at module level, and asserts `isinstance(boundary, CoverBoundary)` inside the
  function (`solver.py:600-609`). The assert is a real precondition, not decoration.
- **Rewrite must not double-expand marks.** `_replace_mark_in_text` (`rewrite.py:75`) skips a
  token already enclosed in brackets or parentheses, and absorbs the surrounding pair so
  `[X]` becomes `[X]` rather than `[[X]]` (`rewrite.py:96-107`).
- **Rewrite must not reclassify generated tokens.** `apply_cover_checkmark_decisions`
  applies only decisions keyed by `(source_region, source_token)` — decisions derived from
  the source text — and never treats a token it just wrote as a new input
  (`rewrite.py:201-205`).
- **Conflicting spans are skipped, not resolved by preference.** `span_states`
  (`rewrite.py:253-260`) collects every state claimed for each mark span; a span claimed
  with more than one state is in `conflicted_spans` and is left untouched
  (`rewrite.py:269-270`).
- **Unwrapping a table is a caller obligation.** `apply_cover_checkmark_decisions` returns
  `(new_text, changed, unwrapped_table_indices)`. The docstring is explicit: callers must
  evict those geometry indices before any subsequent positional pass (`rewrite.py:204-211`).
  `normalize.py:286-288` discharges this by calling `update_table_geometries` with the
  returned set, which drops the unwrapped geometries entirely (`rewrite.py:335-395`).
- **Filer marks are only normalized next to a filer label.** `_normalize_filer_line`
  (`rewrite.py:44`) returns the line unchanged unless a `FILER_STATUS_TERMS` label is
  present, and further restricts edits to spans within 48 characters of a label
  (`rewrite.py:59-63`). This is what stops a bare underscore run elsewhere in the cover from
  being rewritten into a checkbox.

## Public surface

- `infer_cover_checkmarks` — extract and solve every active cover group; the entry point `normalize.py` calls. `edgar_sec/engine/forms/checkmarks/solver.py:593`.
- `solve_cover_constraints` — run all applicable groups with soft penalties. `edgar_sec/engine/forms/checkmarks/solver.py:559`.
- `solve_filer_constraints` — resolve the primary filer triplet and overlay pair alone; duplicate semantic rows return `UNRESOLVED`. `edgar_sec/engine/forms/checkmarks/solver.py:481`.
- `solve_statutory_constraints` — resolve the Yes/No and statutory Boolean relationships; returns `NOT_APPLICABLE` when the schema lacks `STATUTORY_BINARY_GROUP`. `edgar_sec/engine/forms/checkmarks/solver.py:507`.
- `solve_report_period` — resolve annual/quarterly versus transition source marks. `edgar_sec/engine/forms/checkmarks/solver.py:528`.
- `PenaltyScorer` / `DEFAULT_PENALTY_SCORER` — the weight table and its defaults. `edgar_sec/engine/forms/checkmarks/solver.py:95` and `:109`.
- `CoverCheckmarkResult`, `HypothesisScore`, `ConstraintViolation`, `InferenceStatus` — the inspectable result model. `edgar_sec/engine/forms/checkmarks/solver.py:82`, `:72`, `:61`, `:52`.
- `canonical_semantic_key` — canonicalise a source label without changing unknown ones. `edgar_sec/engine/forms/checkmarks/solver.py:153`.
- `extract_cover_candidates` — extract candidates from the bounded cover and retained table grids. `edgar_sec/engine/forms/checkmarks/extractor.py:514`.
- `extract_table_candidates` — extract from logical table rows and cell geometry. `edgar_sec/engine/forms/checkmarks/extractor.py:323`.
- `CheckboxCandidate` — one source checkbox; `glyph` and `known_state` are the properties the solver reads. `edgar_sec/engine/forms/checkmarks/extractor.py:62`.
- `apply_cover_checkmark_decisions` — apply resolved decisions to text. `edgar_sec/engine/forms/checkmarks/rewrite.py:201`.
- `update_table_geometries` — carry resolved states into retained table metadata. `edgar_sec/engine/forms/checkmarks/rewrite.py:335`.

The decision vocabulary it emits is not defined here: `CheckmarkDecision`, `CheckmarkScope`,
`CANONICAL_CHECKED` (`"[X]"`), `CANONICAL_UNCHECKED` (`"[ ]"`), and `CHECKMARK_MARK_RE` all
come from `edgar_sec/domain/forms/checkmarks.py`. The constraint data — `CoverCheckboxSchema`,
`CheckboxConstraint`, `ANNUAL_CHECKBOX_SCHEMA`, `QUARTERLY_CHECKBOX_SCHEMA`, and every
`STAT_*` / `FILER_*` / `REPORT_*` key — comes from `edgar_sec/domain/forms/schemas.py`.

## Tests

**There is no `tests/engine/forms/checkmarks/` directory.** No test file anywhere in
`tests/` imports `edgar_sec.engine.forms.checkmarks` or any of
`infer_cover_checkmarks`, `apply_cover_checkmark_decisions`, `extract_cover_candidates`,
`solve_cover_constraints`, or `normalize_yes_no_pair_line` (verified by repo-wide symbol grep
on 2026-09-28).

`tests/domain/forms/test_checkmarks.py` exists and covers only
`edgar_sec/domain/forms/checkmarks.py` — the domain module of constants, `CHECKMARK_MARK_RE`,
and the Wingdings glyph tables. It exercises none of this package. That is a deviation from
the one-test-file-per-source-module rule in `AGENTS.md` §6, and it is recorded here rather
than left for a reader to discover.

Indirect coverage does exist: `tests/engine/forms/test_normalize.py` drives the checkmark
stage through `normalize_document(DOC_10K, form="10-K")`, including
`test_checkmark_is_scoped_to_cover_not_whole_document` (line 146) and a case asserting
`result.checkmark_inference is None` for an unmodelled form (line 203), and
`tests/engine/forms/test_normalization_goldens.py` pins the chain's outcome. That is
integration coverage of the seam, not unit coverage of this package.

## Deliberate gaps

- **This package has no direct unit tests.** The mirrored paths
  `tests/engine/forms/checkmarks/test_extractor.py`,
  `tests/engine/forms/checkmarks/test_solver.py`,
  `tests/engine/forms/checkmarks/test_rewrite.py`, and
  `tests/engine/forms/checkmarks/test__yesno.py` do not exist. The solver's unresolved,
  tied, and over-two-glyph-class paths are therefore only reachable through the
  normalization goldens, not asserted directly. Roadmap milestone **M4.6** — replaying v1's
  `test_cover_checkmark_inference.py` for 100% solver parity — is **still unchecked** and
  blocked on the real-filing fixtures deferred in roadmap M6.3. Until M6.3 lands, the
  direct-test gap stays open; the roadmap tracks the parity half, not the unit-test half.
- **No image/font-glyph decoding.** v1's
  `defs/sec_forms/page_markers/fast_html/` resolved Wingdings and Wingdings 2 checkbox
  glyphs from the HTML DOM. That is gone: v2 has no HTML-frame path at all, and glyph state is
  decided by `CheckboxCandidate.known_state` from the text token alone
  (`extractor.py:85-98`). The font tables survive in
  `edgar_sec/domain/forms/checkmarks.py::font_glyph_state` / `font_bullet_glyph_state`, but
  nothing in this package calls them.
- **No v2 sub-package layout to speak of.** v1 had
  `defs/sec_forms/cover/checkmark/` with five modules plus a `models.py`. v2 consolidated
  `candidates.py`, `yes_no_pairs.py`, and `frames.py` into `extractor.py`, and
  `inference.py` and `solver.py` into `solver.py` (`extractor.py:1-6`, `solver.py:1-5`).
  `models.py` did not survive as a module: `CheckboxCandidate` lives in `extractor.py` and
  `CoverCheckmarkResult` / `PenaltyScorer` in `solver.py`. There is **no v2
  `engine/forms/cover/checkmark/`** — the package sits beside `cover/`, not inside it, which
  is a relocation rather than a re-export (AGENTS.md §1.1 forbids the alias module that would
  have preserved the old path).
- **No fingerprint or importance heuristic here.** The roadmap's M4.2 description mentions a
  "fingerprint/importance heuristic" being faithful to v1; no such symbol exists in these four
  modules. Do not go looking for it.
- **No more than two ambiguous glyph classes.** Three or more yields `UNRESOLVED` by design
  (`solver.py:352-353`). A cover with three genuinely ambiguous marks is not resolved today,
  and widening this is a solver change, not a configuration knob.
- **Filer-group rules live in code, not in the schema.** The "exactly one primary filer" and
  large-accelerated overlay exclusions are hardcoded in `_evaluate_filer`
  (`solver.py:276-311`) rather than declared as `CheckboxConstraint` entries in
  `edgar_sec/domain/forms/schemas.py`. `ANNUAL_CHECKBOX_SCHEMA` and
  `QUARTERLY_CHECKBOX_SCHEMA` currently declare the same seven
  `STATUTORY_CHECKBOX_CONSTRAINTS` and the same three groups, so this is invisible today — but
  a form needing a different filer rule cannot express it declaratively yet.
- **8-K, 6-K, and generic families have no cover handling at all.** `_schema_for_family`
  (`solver.py:160-168`) returns a schema only for `10-K`, `20-F`, and `10-Q`. The `8-K`
  plugin in `edgar_sec/engine/forms/plugins/registry.py:90-99` sets `cover_schema=None`, so
  the entire checkmark stage is skipped for current reports. That is a modelling decision
  (an 8-K has no statutory filer-status cover), not a gap in the solver.
- **The roadmap's target module names are not what shipped.** `phase_2_5/04_engine_tables_and_forms.md`
  §2 planned `engine/forms/cover/candidates.py`, `engine/forms/cover/solver.py`,
  `engine/forms/cover/models.py`, and `engine/forms/cover/rewrite.py`. The implementation
  placed them under `engine/forms/checkmarks/` as `extractor.py`, `solver.py`, `rewrite.py`,
  and (merged into `solver.py`) the models. The M4.2 checklist entry records this
  ("Shipped in sub-plan 02 under different names"), so it is reconciled rather than
  divergent — but the inventory table in that roadmap is stale relative to the tree.
- **`engine/tables/` reach-in.** `rewrite.py` and `extractor.py` import
  `mask_tagged_tables`, `restore_tagged_tables`, `strip_table_wrapper_tags`, `TableSpan`,
  and `TAGGED_TABLE_OPEN_RE` / `TAGGED_TABLE_CLOSE_RE` from `edgar_sec/engine/tables/protection.py`.
  That is a legal same-layer sibling import, but it means the checkmark rewriter is coupled
  to the table-masking protocol rather than to a forms-level interface.
