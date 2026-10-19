# `edgar_sec/engine/forms/ownership` — ownership document transformation

Parses supported Form 3/4/5 ownership filings into SEC `<ownershipDocument>` XML.

## Purpose

Extracts supported reporting-owner details, transaction rows, dates, and signatures from
filer-authored tables. Recognized values are normalized to ownership XML types and date format.

## Contracts

- **Pure transformation only**: Transformation is total and offline with zero network or filesystem I/O.
- **Unparsed content**: Review runs persist unparsed sections in a sibling JSON sidecar, outside schema XML.
- **Incomplete forms**: Unrecognized required values are omitted from XML and reported by analysis.
- **Token-based cell disambiguation**: Table cells are mapped by lexical type invariants rather than rigid column coordinates.
- **No barrel re-exports**: Consumers import leaf modules directly.
- **Layer discipline**: Sits in Layer 3 (`engine/`), importing only downwards.

## Deliberate gaps

- **Paper and PDF routes deferred**: Only markup (`.htm`) routes are parsed into XML.
- **Late-filing Box 1(b) flags**: Preserved in diagnostic envelopes but not emitted as distinct statutory flags.
- **Form 3 tables**: Initial-ownership tables remain unparsed until their row model is implemented.
- **Non-standard co-owner schedules**: Joint filers sharing non-grid narrative blocks remain in the sidecar.
