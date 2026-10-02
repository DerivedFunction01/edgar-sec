# `edgar_sec/engine/forms/cover/boundary` — cover boundary detection

Three modules turn a document and a profile policy into one decision: where the
cover page ends.

## Purpose

The boundary is the fence every cover-specific rewrite runs inside, so this
package is deliberately conservative. It would rather report no boundary than a
wrong one: a missed boundary leaves body text alone, while a wrong boundary lets
a rewrite touch filing prose.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `detector.py` | The evidence ladder and its two public entry points. |
| `corridor.py` | The forward cover-start scan, the backward body confirmation, the body-prose scan, and the finalizer. |
| `transition.py` | The proven-root transition out of an incorporated-reference block. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`detector.py` imports from `corridor.py` and `transition.py`; neither imports
back. `corridor.py` reaches upward only for `rules.py`, `models.py`, and
`structure.py`.

## Contracts

- `find_cover_boundary(input, None)` returns `BoundaryMethod.DISABLED`. Absence of
  a policy is an explicit opt-out.
- Every signal in the ladder is corroborated: a phrase match alone is not enough.
  This is the rule that keeps an 8-K from acquiring a cover boundary.
- Backward confirmation moves the boundary only backwards, and only to a root
  that scores 2 or 3 on the lexical body pack. Score-1 evidence is ambiguous and
  is never accepted as a root.
- The backward search never starts before `cover_start.start_line`, so a
  cover-shaped block cannot become its own body anchor.
- A heading followed by another heading of the same role, by continuation prose,
  or by a proxy reference disclosure is a child, not a root. Only the first
  proven root ends the cover.
- `find_cover_boundary_for_profile` reads `profile.boundary`,
  `profile.cover_evidence`, and `profile.body_evidence`. A profile without a
  `boundary` attribute yields `DISABLED`.

## Public surface

- `find_cover_boundary(boundary_input, policy, *, cover_evidence=None, body_evidence=None) -> CoverBoundary` — `detector.py`.
- `find_cover_boundary_for_profile(boundary_input, profile) -> CoverBoundary` — `detector.py`.
- `find_cover_start(boundary_input, policy, *, cover_evidence=None, body_evidence=None) -> CoverStart` — `corridor.py`.
- `confirm_backward_body(lines, provisional_end, cover_start_line, evidence, rules=None) -> tuple[int, list[BoundaryEvidence]]` — `corridor.py`.
- `is_toc_like_line`, `is_proxy_reference_disclosure`, `line_offset`, `line_at_offset`, `next_nonblank_line`, `prev_nonblank_line`, `enabled` — `corridor.py`.

Everything else stays private: `_finalize_boundary`, `_unknown`, and
`_find_body_prose_line` in `corridor.py`, plus `_next_cover_transition` and
`_first_body_semantic_line`, which `transition.py` exports in its `__all__`
under underscore names because `detector.py` is their only caller.

## Command surface

None. Library package, no CLI.

## Tests

- `tests/engine/forms/cover/boundary/test_detector.py`
- `tests/engine/forms/cover/boundary/test_corridor.py`
- `tests/engine/forms/cover/boundary/test_transition.py`

## Deliberate gaps

- **The `marker` method is declared but never produced.** v1's
  `BoundaryMethod.MARKER` has no producer in v1 either; it remains in the enum
  because the value is part of the recorded decision vocabulary.
- **No HTML cover detection.** The detector reads the ASCII representation only.
  `BoundaryInput.representation` is recorded but does not branch behaviour.
- **The search window is `max(200, 25% of lines)`.** A cover that begins later
  than that in a very long document is not found. v1 uses the same window.
- **`find_cover_start` scans only the first 60 lines.** A filing whose cover
  begins after 60 lines of front matter gets no cover start, and the boundary
  falls back to `scan_start = 0`.
- **The cover-only-fragment branch requires `len(lines) <= search_limit`.** A
  cover-shaped filing with more than 200 lines and no body anchor reports
  `UNKNOWN` rather than a whole-document cover.
