# pension

## Purpose

The pension family's evidence complex, kept together as one subpackage: plain
evidence, routed evidence and specs, and combination evidence and specs. The
routed forms are consumed across the package — separator evidence in
`separators/` and `note_separators/` composes over `pension_routed_evidence`.

## Contracts

- **Routed evidence composes core-form evidence with the routed specs**;
  combination evidence builds on the routed forms, never on a private copy.
- **The family's spec tables live beside their builders** (the separator-pair
  rule applied to a family complex): `pension_routed_specs` and
  `pension_combination_specs` are read by this folder's evidence and by the
  form-test aggregator in `form_specs/`.

## Deliberate gaps

- **No other family is homed here**: pension is a subpackage because its
  routed/combination subgraph is internally dense and externally consumed as
  a unit, not as a precedent for per-family folders.
