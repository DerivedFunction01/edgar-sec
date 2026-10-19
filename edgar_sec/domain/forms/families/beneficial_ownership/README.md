# beneficial_ownership

Layer 1 (domain) models, processing profiles, and section taxonomies for SEC beneficial ownership reports (Schedule 13D and Schedule 13G).

## Purpose

Provides immutable data structures representing cover page reporting person matrices, issuer identification, and narrative item disclosures for beneficial ownership filings under Sections 13(d) and 13(g) of the Securities Exchange Act of 1934.

## Contracts

- **Unified matrix representation**: Reporting person cover evidence carries both statutory line numbers and canonical semantic tags, allowing uniform extraction across Schedule 13D (14 slots) and Schedule 13G (12 slots).
- **Statutory item sequence**: Narrative taxonomies map statutory item headings for 13D (Items 1–7) and 13G (Items 1–10).
- **Leaf imports only**: Submodules must be imported directly without package re-exports.

## Deliberate gaps

- **Group joint filing agreements**: Joint filing exhibit parsing is handled in Layer 3 normalizers.
