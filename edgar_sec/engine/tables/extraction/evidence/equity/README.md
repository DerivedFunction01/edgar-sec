# equity

## Purpose

Evidence builders for the equity families — EPS and stock compensation: the
per-share detector seat and the stock-comp activity pair / price-form
reader, each gathering its family's evidence over a table context and
scoring it for the classification cascade.

## Contracts

- **Evidence scores, it does not refuse**: a failed signal records a
  zero-point signal, never a gate; refusal lives in `seats/` and `vetoes/`.
- **Builders read their family's spec data from `specs/`** and the shared
  primitives from `core/`; no builder carries a private copy of a spec table.

## Deliberate gaps

- **Separator evidence for these families is not here**: the stock-comp
  separator evidence lives in `note_separators/`.
