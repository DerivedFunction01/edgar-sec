# `edgar_sec/engine/forms/cover/boundary` — cover boundary detection

This package determines where a cover ends from document content and profile policy.

## Purpose

The boundary is the fence every cover-specific rewrite runs inside, so this
package is deliberately conservative. It would rather report no boundary than a
wrong one: a missed boundary leaves body text alone, while a wrong boundary lets
a rewrite touch filing prose.

## Contracts

- `find_cover_boundary(input, None)` returns `BoundaryMethod.DISABLED`. Absence of
  a policy is an explicit opt-out.
- Every signal in the ladder is corroborated: a phrase match alone is not enough.
  This is the rule that keeps an 8-K from acquiring a cover boundary.
- Backward confirmation accepts only corroborated body-root evidence; ambiguous
  evidence cannot move the boundary.
- The backward search never starts before `cover_start.start_line`, so a
  cover-shaped block cannot become its own body anchor.
- A heading followed by another heading of the same role, by continuation prose,
  or by a proxy reference disclosure is a child, not a root. Only the first
  proven root ends the cover.
- `find_cover_boundary_for_profile` reads `profile.boundary`,
  `profile.cover_evidence`, and `profile.body_evidence`. A profile without a
  `boundary` attribute yields `DISABLED`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No HTML-aware cover detection.** The detector reads a projected text frame
  rather than a DOM, so HTML-specific evidence is never evaluated.
- **Bounded scans can miss unusually late cover material.** Long leading content
  or cover-only documents may leave the boundary unknown.
