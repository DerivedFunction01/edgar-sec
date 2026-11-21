# evidence

## Purpose

Per-family evidence builders: each module gathers its family's evidence over a
table context — vocabulary, shape, and arithmetic signals — and scores it for
the classification cascade.

## Contracts

- **Builders read their family's spec data from `specs/`** and the shared
  primitives from `core/`; no builder carries a private copy of a spec table.
- **Derivatives claims are gated on U/A evidence**: a `derivatives_hedging`
  claim issues only when the geometry itself carries underlying/notional or
  accounting-effects evidence under the gate algebra declared in
  `core.profiles`.
- **Evidence scores, it does not refuse**: refusal lives in `seats/` and
  `vetoes/`; a failed signal records a zero-point signal, never a gate.

## Deliberate gaps

- **Pension evidence lives in `pension/`** and separator evidence in
  `separators/` / `note_separators/`: the family complexes with their own
  internal seams are not flattened into this folder.
