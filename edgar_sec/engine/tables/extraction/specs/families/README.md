# families

## Purpose

The per-family evidence spec modules: one module per supported table family,
holding that family's measured vocabulary, pattern, and bound tables for the
evidence builders. The set-level and measure-set specs stay at the parent
`specs/` root.

## Contracts

- **One module per family, named for its family**: the module set mirrors the
  family set in `core.profiles`; a family with no module here has no evidence
  specs.
- **Data only**: no evaluator logic lives here — the parent package's measured
  value and provenance contracts apply unchanged.

## Deliberate gaps

- **Set-level specs are not family specs**: form-separation, input-class,
  income-statement set-level, and measure-set specs remain at the `specs/`
  root, beside this subpackage rather than inside it.
