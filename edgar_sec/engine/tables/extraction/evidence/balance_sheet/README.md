# balance_sheet

## Purpose

Evidence builders for the balance-sheet families — ARO, credit losses,
derivatives, inventory, leases, PPE, and warranty: each module gathers its
family's evidence over a table context — vocabulary, shape, and arithmetic
signals — and scores it for the classification cascade.

## Contracts

- **Evidence scores, it does not refuse**: a failed signal records a
  zero-point signal, never a gate; refusal lives in `seats/` and `vetoes/`.
- **Builders read their family's spec data from `specs/`** and the shared
  primitives from `core/`; no builder carries a private copy of a spec table.
- **Derivatives claims are gated on U/A evidence**: a `derivatives_hedging`
  claim issues only when the geometry itself carries underlying/notional or
  accounting-effects evidence under the gate algebra declared in
  `core.profiles`.

## Deliberate gaps

- **The pension complex is not here**: pension evidence lives in `pension/`,
  and separator evidence in `separators/` / `note_separators/`.
