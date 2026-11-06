# `edgar_sec/engine/forms/plugins` — exhibit header probes

## Purpose

This package contains a probe for an exhibit designation near a document's opening and the exhibit body evaluator that consumes the domain exhibit packs. The active normalization chain owns form-family behavior in `engine/forms/cover`; this package does not register runtime form plugins.

## Contracts

- **Bounded probe**: `probe_exhibit_header()` examines only the configured opening
  line window and ignores spans shielded by a table of contents.
- **Evidence only (probe)**: A designation match identifies a candidate; it does not fetch, route, or select an exhibit document. `evaluate_exhibit_body` goes one step further and returns a role assessment with a disposition, but it does not fetch or route either.

## Deliberate gaps

- **No registry or dispatch**: Form-specific normalization remains owned by the
  cover-profile system.
