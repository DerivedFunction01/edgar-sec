# `edgar_sec/engine/forms/cover/checkmarks` — cover checkbox recognition

Extracts the checkbox glyphs on an SEC cover, decides what they mean from the
filing's own statutory constraints, and applies the decision to the text.

## Purpose

An ambiguous cover glyph — a Wingdings `x`, a bare underscore run, an empty box —
is not decidable from the mark alone. This package therefore does not classify
marks; it enumerates the assignments still consistent with the filing's own
constraints, scores each with soft penalties, and reports a decision only when
exactly one assignment is cheapest. A tie is reported as `UNRESOLVED` with the
full hypothesis table rather than resolved arbitrarily.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | Immutable candidate, violation, hypothesis, and result models plus penalty weights. |
| `yes_no_pairs.py` | Authoritative normalization for complete inline Yes/No pairs. |
| `frames.py` | Masked-frame to original-frame offset translation. |
| `candidates.py` | Geometry and text candidate extraction. |
| `solver.py` | Constraint enumeration, penalty scoring, and the public solver entry points. |
| `rewrite.py` | Applies resolved decisions to text and table metadata. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`solver.py` imports `candidates.py`; `rewrite.py` imports `yes_no_pairs.py` and
`models.py`. `candidates.py` imports `frames.py`. The only consumer of `rewrite.py`
outside this package is `edgar_sec/engine/forms/normalize.py`, which drives the
rewrite stage.

## Contracts

- Every reported decision carries the `source_region` and `mark_span` it came
  from, in the **original** (unmasked) frame. A caller may slice the source text
  with them directly.
- A span is rewritten at most once, however many semantic labels point at it. On
  real 10-K covers a single Wingdings `x` is associated with every filer-status
  label; re-applying one span would slice the expanded token into `[X]X]X]...`.
- A span whose text no longer matches the extracted `source_token` is dropped,
  not applied. A stale or foreign-frame span would otherwise corrupt unrelated
  text, including structural table tags.
- Two candidates that resolve the same physical span to different states mark it
  conflicted, and no decision is applied to it.
- A tie between hypotheses is reported, not broken. A `direct_state` violation
  (an observed mark contradicting the constraint solution) also reports
  `UNRESOLVED` rather than overwriting the observed state.
- `apply_cover_checkmark_decisions` returns the set of geometry table indices it
  physically unwrapped. The caller must evict exactly those from its
  `table_geometries` before any positional-pairing pass, or the first surviving
  `<TABLE>` block will be paired with the wrong geometry.
- Candidates carry offsets in the original frame even though extraction runs over
  a masked frame; `frames.py` translates every offset back before a candidate is
  emitted.

## Public surface

- `extract_cover_candidates(text, boundary, *, family, table_geometries=()) -> tuple[CheckboxCandidate, ...]` — `candidates.py`.
- `extract_table_candidates(geometry, *, table_index) -> tuple[CheckboxCandidate, ...]` — `candidates.py`.
- `infer_cover_checkmarks(text, boundary, *, family, table_geometries=(), schema=None) -> CoverCheckmarkResult` — `solver.py`.
- `solve_filer_constraints`, `solve_statutory_constraints`, `solve_report_period`, `solve_cover_constraints`, `canonical_semantic_key` — `solver.py`.
- `apply_cover_checkmark_decisions(text, result) -> tuple[str, bool, frozenset[int]]` — `rewrite.py`.
- `update_table_geometries(table_geometries, result, unwrapped_table_indices=frozenset()) -> tuple[object, ...]` — `rewrite.py`.
- `has_labeled_checkmark_candidates`, `has_resolvable_line_yes_no_candidates` — `rewrite.py`.
- `normalize_yes_no_pair_line`, `normalize_yes_no_pairs`, `YES_NO_WORD_RE`, `YES_NO_LINE_RE` — `yes_no_pairs.py`.
- `build_masked_offset_translator(masked, spans) -> Callable[[int], int]` — `frames.py`.
- `InferenceStatus`, `CheckboxCandidate`, `ConstraintViolation`, `HypothesisScore`, `CoverCheckmarkResult`, `PenaltyScorer`, `DEFAULT_PENALTY_SCORER` — `models.py`.

## Command surface

None. Library package, no CLI.

## Tests

- `tests/engine/forms/cover/checkmarks/test_models.py`
- `tests/engine/forms/cover/checkmarks/test_yes_no_pairs.py`
- `tests/engine/forms/cover/checkmarks/test_frames.py`
- `tests/engine/forms/cover/checkmarks/test_candidates.py`
- `tests/engine/forms/cover/checkmarks/test_solver.py`
- `tests/engine/forms/cover/checkmarks/test_rewrite.py`

## Deliberate gaps

- **`schemas.py` is not declared here.** `CheckboxConstraint`,
  `CoverCheckboxSchema`, `STATUTORY_CHECKBOX_CONSTRAINTS`, `ANNUAL_CHECKBOX_SCHEMA`,
  and `QUARTERLY_CHECKBOX_SCHEMA` live in
  `edgar_sec/domain/forms/common/schemas.py` and
  `edgar_sec/domain/forms/families/{annual,quarterly}/checkmarks.py`. `solver.py`
  imports them from there.
- **Only `10-K`, `20-F`, and `10-Q` are inferable.** Any other family yields
  `NOT_APPLICABLE`, because no schema is declared for it. A `10-Q` with a
  transition-report period has no declared schema in this slice.
- **More than two ambiguous glyph classes is `UNRESOLVED`.** The hypothesis
  enumeration is a full cross-product; past two glyphs it is refused rather than
  bounded, so a cover with three different Wingdings symbols is not solved.
- **`PenaltyScorer` weights are not tuned per form.** One default set applies to
  every family. The dataclass is frozen and constructible with overrides, but
  nothing in this package selects different weights per form.
- **`update_table_geometries` returns `tuple[object, ...]`**, not
  `tuple[TableGeometry, ...]`, because it passes through any geometry that
  carries a `render_result` attribute rather than requiring the concrete type.
- **A pure Yes/No table row is unwrapped, not re-wrapped.** Once its states are
  resolved the wrapper adds nothing, so `apply_cover_checkmark_decisions` strips
  the tags and the caller is told to drop the geometry.
- **`extract_cover_candidates` takes `family` and discards it.** The parameter is
  part of the call signature and is `del`-ed; per-family candidate vocabulary is
  not implemented here.
