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

## Contracts

- **Every reported decision carries `source_region` and `mark_span`**: in the original (unmasked) frame. A caller may slice the source text with them directly.
- **A span is rewritten at most once**: however many semantic labels point at it. On real 10-K covers a single Wingdings `x` is associated with every filer-status label; re-applying one span would slice the expanded token into `[X]X]X]...`.
- **A span whose text no longer matches the extracted `source_token` is dropped**: not applied. A stale or foreign-frame span would otherwise corrupt unrelated text, including structural table tags.
- **Two candidates that resolve the same physical span to different states mark it conflicted**: and no decision is applied to it.
- **A tie between hypotheses is reported, not broken**: A `direct_state` violation (an observed mark contradicting the constraint solution) also reports `UNRESOLVED` rather than overwriting the observed state.
- **`apply_cover_checkmark_decisions` returns geometry table indices physically unwrapped**: The caller must evict exactly those from its `table_geometries` before any positional-pairing pass, or the first surviving `<TABLE>` block will be paired with the wrong geometry.
- **Candidates carry offsets in the original frame**: even though extraction runs over a masked frame; `frames.py` translates every offset back before a candidate is emitted.
- **A mark's state comes from the shared vocabulary**: `known_state` reads `mark_token_state()`, so a filled slot is checked, a bare mark needs the contextual opt-in, and an underscore-only run is never a state.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **`schemas.py` is not declared here.** `CheckboxConstraint`,
  `CoverCheckboxSchema`, and `STATUTORY_CHECKBOX_CONSTRAINTS` live in
  `edgar_sec/domain/forms/common/schemas.py`; family schemas live in the
  `checkmarks.py` module of their family package under
  `edgar_sec/domain/forms/families/`. `solver.py` consumes them through
  `FAMILY_PROCESSING_PROFILES`.
- **Inference follows `FAMILY_PROCESSING_PROFILES` schema scope**:
  Registered families with a cover checkbox schema are inferred from it.
  Registered profiles with no schema return `NOT_APPLICABLE`; unknown families
  and unknown cover ends do too. A schema-backed family returns `ABSENT` when
  extraction finds no candidates. The profile registry in
  `domain/forms/families/processing_profiles.py` is authoritative for which
  families carry a schema.
- **More than two ambiguous glyph classes is `UNRESOLVED`.** The hypothesis
  enumeration is a full cross-product; past two glyphs it is refused rather than
  bounded, so a cover with three different Wingdings symbols is not solved.
- **`PenaltyScorer` weights are not tuned per form.** One default set applies to
  every family. The dataclass is frozen and constructible with overrides, but
  nothing in this package selects different weights per form.
- **`update_table_geometries` returns a loosely typed tuple**, not the concrete geometry type, because it passes through any geometry that carries a `render_result` attribute rather than requiring the concrete type.
- **A pure Yes/No table row is unwrapped, not re-wrapped.** Once its states are
  resolved the wrapper adds nothing, so `apply_cover_checkmark_decisions` strips
  the tags and the caller is told to drop the geometry.
- **Per-family candidate vocabulary is schema-only**:
  `extract_cover_candidates` uses `family` only to resolve the family's
  checkbox schema; no other per-family candidate vocabulary is implemented here.
