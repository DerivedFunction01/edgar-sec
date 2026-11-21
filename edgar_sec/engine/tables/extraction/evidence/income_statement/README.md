# income_statement

## Purpose

Evidence builders for the income-statement families — the set-level stage of
the routed income-statement cascade, restructuring, and the
tax-reconciliation seat: each module gathers its family's evidence over a
table context — vocabulary, shape, and arithmetic signals — and scores it
for the classification cascade.

## Contracts

- **Evidence scores, it does not refuse**: a failed signal records a
  zero-point signal, never a gate; refusal lives in `seats/` and `vetoes/`.
- **Builders read their family's spec data from `specs/`** and the shared
  primitives from `core/`; no builder carries a private copy of a spec table.

## Deliberate gaps

- **Routing and seating are not here**: the set-level module carries the
  stage's evidence only; the cascade's routing and seating acts live in
  `cascade/`.
