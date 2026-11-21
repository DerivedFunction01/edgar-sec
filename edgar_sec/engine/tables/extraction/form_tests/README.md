# form_tests

## Purpose

The form-test stage: `form_tests` evaluates the declared specs from
`form_specs/` once per table, between context assembly and the vocabulary
competition, dispatching on the spec's kind only. The kind evaluators
(separator, signal, walk) and the form runtimes they dispatch to (composition,
measure set, percentage form, year ladder) live here.

## Contracts

- **One stage, kind dispatch only**: `form_tests` dispatches on the spec's
  kind, never on its family; each kind's parameters live in `form_specs/`.
- **A passed test scores as evidence in both competitions** (the `form_test`
  channel and the evidence group); a failed evaluable test records a
  zero-point signal, never a veto or a standalone assignment.
- **Placement facts are computed from the filing's own first-pass reads** in
  `cascade.classify_filing` and applied by re-arbitration; unstamped,
  placement tests are unevaluable.

## Deliberate gaps

- **No spec data lives here**: declarations and parameters are data in
  `form_specs/` and `specs/`; this folder holds only evaluators and runtimes.
