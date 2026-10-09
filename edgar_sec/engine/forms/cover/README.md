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

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **`DocumentTopology` is declared, but no resolver produces it.**
- **Part-heading recognition does not cover all Roman-numeral forms.** Some
  part-like headings are treated as prose.
- **No closing-region merging.** Detection does not extend over following
  consent pages or identify exhibit indexes without a heading.
- **No parity harness against a reference implementation.**
