# `edgar_sec/engine/forms/common/fields` — the shared field contract

Field specs and tabular row specs every form family normalizes through.

## Purpose

Owns the field contract: `FieldSpec`/`FieldKind` and schema value extraction
(`extraction`), plus the row-spec home (`row_extraction`) — the column factory
and row-field lookup both form packages bind.

## Contracts

- **One field contract**: Families declare fields and table columns as specs;
  normalization and constraint checking live here, not per family.
- **Home stability**: Row-spec symbols live here alone; families bind the
  homes rather than copying them.

## Deliberate gaps

- **No XML emission**: Specs are rendered by the family renderers and the
  builders in `xml/`; this package stops at the normalized record.
