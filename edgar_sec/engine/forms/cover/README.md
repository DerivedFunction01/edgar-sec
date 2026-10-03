# `edgar_sec/engine/forms/cover` — cover-page region recognition

Decides where an SEC filing's cover page ends and what may be rewritten inside
it. Every downstream cover-specific stage — checkbox rewriting, cover table
cleaning, cover healing — runs strictly inside the boundary this package
establishes, so the boundary decision is the important one.

## Purpose

A bounded search for the end of the cover, bounded searches for the surrounding
regions (cover start, table of contents, closing signatures), and the rewrites
that are only safe because they are fenced by that boundary.

Not a form classifier, taxonomy engine, or normalizer. Vocabulary arrives as
typed evidence packs from `edgar_sec.domain.forms`; this package compiles and
applies it but never owns it.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | Immutable boundary, TOC, and body-anchor models plus their capability enums. |
| `profiles.py` | `CoverProfile`, the `build_*_profile` functions, `COVER_PROFILES`, `get_profile`, and the per-profile label and phrase-rule vocabularies. |
| `rules.py` | Compiles evidence packs into cover regexes and a lexical body pack, cached by evidence identity. |
| `structure.py` | Generic PART/ITEM heading mechanics shared by the boundary, TOC, and body stages. |
| `reflow.py` | The cover's two policies handed to the generic ASCII reflow engine. |
| `closing.py` | Signature-block and exhibit-index detection. |
| `body_context.py` | Logical-unit context and lexical pack glue for body-start detection. |
| `body_start.py` | Forward body-start detection after the cover/TOC boundaries. |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |

Subpackages, each with its own README:

| Package | Responsibility |
| :--- | :--- |
| `boundary/` | The evidence ladder that produces a `CoverBoundary`. See `boundary/README.md`. |
| `toc/` | Table-of-contents span detection. See `toc/README.md`. |
| `tables/` | Form-governed cover pseudo-table unwrapping. See `tables/README.md`. |
| `checkmarks/` | Cover checkbox candidate extraction, constraint solving, and rewrite. See `checkmarks/README.md`. |
| `healing/` | Bounded cover text healing and binary-block merging. See `healing/README.md`. |

## Contracts

**Guarantees to callers**

- `find_cover_boundary(input, None)` returns `BoundaryMethod.DISABLED` and no
  boundary. An absent policy is an explicit opt-out, never a default guess.
- No single signal is authoritative. Every rung requires corroboration: an
  incorporated-reference phrase match is ignored unless at least two cover
  identity signals matched *or* a page marker was seen, and the same identity
  gate guards the TOC, PART, and ITEM rungs. This is why a current report never
  acquires a cover boundary even when its text contains a form heading.
- The ladder returns the **first** rung that both fires and is corroborated:
  incorporated reference, TOC span, bare TOC heading, exact PART, exact ITEM,
  decisive body prose, then the cover-only fragment.
- Every returned boundary carries the evidence rows that produced it, and
  `approximate=True` always. A caller needing certainty should read `evidence`,
  not `confidence`.
- Backward confirmation may only move the boundary **earlier** (to a body root),
  never later. A gap wider than the confirm window pulls the boundary back; a
  narrow gap leaves it alone.
- `infer_cover_checkmarks` reports `UNRESOLVED` with the full hypothesis table
  whenever two assignments are equally cheap. It never breaks a tie.
- `clean_cover_tables` classifies a table against its **raw text**, never against
  geometry rows from a prior render pass, which may belong to a different table.

**Obligations callers place on this package**

- Pass a policy built from the form profile. Hand-assembled signal tuples will
  silently disable whatever the profile would have enabled.
- Treat `end_line` as an exclusive line fence, not an inclusive one.
- Re-derive page analysis when the text has been rewritten since the boundary was
  computed; `find_cover_boundary` accepts a `BoundaryInput` carrying a cached
  `PageMarkerAnalysis` and does not recompute it when one is supplied.

## Public surface

- `find_cover_boundary`, `find_cover_boundary_for_profile` — `boundary/detector.py`.
- `find_cover_start`, `confirm_backward_body`, `is_toc_like_line`,
  `is_proxy_reference_disclosure`, `line_offset`, `line_at_offset`,
  `next_nonblank_line`, `prev_nonblank_line`, `enabled` — `boundary/corridor.py`.
- `compile_cover_rules`, `CompiledCoverRules` — `rules.py`.
- `parse_section_heading`, `match_structural_line`, `is_exact_heading`,
  `is_continuation_prose`, `is_preceding_continuation`, `SectionKind`,
  `ParsedSection`, `StructuralRole`, `StructuralMatch`, `RE_PART`, `RE_ITEM_EXACT`
  — `structure.py`.
- `CoverProfile`, `COVER_PROFILES`, `get_profile`, `build_annual_profile`,
  `build_quarterly_profile`, `build_current_profile`,
  `build_generic_cover_profile`, `build_no_cover_profile` — `profiles.py`.
- `find_body_start` — `body_start.py`.
- `find_closing_span`, `ClosingSpan` — `closing.py`.
- `is_checkbox_answer_line`, `is_cover_layout_line` — `reflow.py`.
- `BoundarySignal`, `BoundaryMethod`, `BodyAnchorType`, `CoverBoundaryPolicy`,
  `BoundaryEvidence`, `CoverBoundary`, `BoundaryInput`, `CoverStart`, `BodyRoot`,
  `BodyStartEvidence`, `BodyStart`, `DocumentTopology` — `models.py`.

The `toc/`, `tables/`, `checkmarks/`, and `healing/` surfaces are listed in those
packages' READMEs.

## Command surface

None. Library package, no CLI.

## Tests

Mirrored coverage lives under `tests/engine/forms/cover/`.

## Deliberate gaps

- **`DocumentTopology` is declared, but no resolver produces it.**
- **Part-heading recognition does not cover all Roman-numeral forms.** Some
  part-like headings are treated as prose.
- **No closing-region merging.** Detection does not extend over following
  consent pages or identify exhibit indexes without a heading.
- **No parity harness against a reference implementation.**
