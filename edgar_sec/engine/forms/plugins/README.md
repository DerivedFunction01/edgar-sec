# `edgar_sec/engine/forms/plugins` — exhibit header probes

## Purpose

This package contains an isolated probe for an exhibit designation near a
document's opening. The active normalization chain owns form-family behavior in
`engine/forms/cover`; this package does not register runtime form plugins.

## Contracts

- **Bounded probe**: `probe_exhibit_header()` examines only the configured opening
  line window and ignores spans shielded by a table of contents.
- **Evidence only**: A designation match identifies a candidate; it does not fetch,
  route, or select an exhibit document.

## Deliberate gaps

- **No registry or dispatch**: Form-specific normalization remains owned by the
  cover-profile system.
