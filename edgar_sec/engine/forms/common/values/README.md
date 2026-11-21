# `edgar_sec/engine/forms/common/values` — scalar value parsing

Date, magnitude, and period parsing for form field values.

## Purpose

Owns the scalar lexemes the field contract normalizes through: schema dates
(`dates`), financial magnitudes and unit scales (`numbers`), and filing
periods, amendments, and box header dates (`periods`).

## Contracts

- **Total parsers**: Parsers never throw on malformed or partial input.
- **Guarded magnitudes**: Number parsing carries anti-coincidence guardrails;
  a token is a value only in its field context.

## Deliberate gaps

- **No field semantics**: Which scalar a field expects is declared by the
  field spec in `fields/`; this package only parses the lexemes.
