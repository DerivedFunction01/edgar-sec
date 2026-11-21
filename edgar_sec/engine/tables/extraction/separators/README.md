# separators

## Purpose

Separator evidence and specs for the five core statements — balance sheet,
cash flow, combined operations, comprehensive income, and equity — plus the
summary separator: the evidence that decides where one statement's tables end
and another's begin inside a filing.

## Contracts

- **Separator pairs stay together**: each separator's evidence module reads
  its own specs module in this folder; pairs are never split across folders.
- **Separator evidence composes shared forms**: over `evidence/`'s core-form
  evidence and, where measured, the pension routed forms in `pension/`.
- **The summary separator reads form-signal parameters from `form_specs/`**,
  like every other scored signal — no private parameter copy.

## Deliberate gaps

- **Note-table separators live in `note_separators/`**: the split is
  statement separators here, note separators there, not a size split.
