# `edgar_sec/engine/forms/ownership` — ownership document transformation

Parses historical pre-2003 Form 4 HTML filings into canonical SEC `<ownershipDocument>` XML.

## Purpose

Extracts reporting owner details, issuer identity, transaction matrices (Table I and Table II),
signatures, and footnotes from filer-authored HTML tables, replacing brittle presentation markup
with structured, validated XML.

## Contracts

- **Pure transformation only**: Transformation is total and offline with zero network or filesystem I/O.
- **Fail-safe fallback**: Malformed or unrecognized sections are enclosed in `<unparsedSections>` without throwing.
- **Token-based cell disambiguation**: Table cells are mapped by lexical type invariants rather than rigid column coordinates.
- **No barrel re-exports**: Consumers import leaf modules directly.
- **Layer discipline**: Sits in Layer 3 (`engine/`), importing only downwards.

## Deliberate gaps

- **Paper and PDF routes deferred**: Only markup (`.htm`) routes are parsed into XML.
- **Late-filing Box 1(b) flags**: Preserved in diagnostic envelopes but not emitted as distinct statutory flags.
- **Non-standard co-owner schedules**: Joint filers sharing non-grid narrative blocks are preserved in unparsed fallback tags.
