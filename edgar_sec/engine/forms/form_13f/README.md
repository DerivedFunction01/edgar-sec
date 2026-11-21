# form_13f

SEC Form 13F institutional holdings processing and semantic review analysis (Layer 3: Engine).

## Purpose

Provides native XML pass-through, streaming XML parsing of the `edgarSubmission` cover/summary and the `informationTable` holdings documents into typed domain models, a fixed-column ASCII parser for pre-2013-05-20 text filings, canonical XML rendering through the shared builder, and semantic review analysis with holdings completeness checks.

## Contracts

- **Byte-Identical Native Pass-Through**: Submissions conforming to the official 13F XML technical specification (v1.9) pass through with byte identity via `passthrough_sec_xml` against `FORM13F_XML_SPEC`.
- **Dollars Invariant**: The domain model carries holding values in dollars; documents from the thousands era (text era, and XML periods before 2023-01-03 per spec v1.7) are normalized at parse time when the document carries its report period.
- **Completeness Checks**: When a parsed document carries both holdings rows and the summary totals, the analyzer compares row count against `tableEntryTotal` and the value sum against `tableValueTotal`, recording discrepancies as review signals.

## Deliberate gaps

- **Companion Documents**: In the XML era the cover/summary and the information table are separate documents of one filing; a submission-only document reports its totals and signals that holdings live in the companion document rather than manufacturing rows.
- **Standalone Information Tables**: A bare information-table document carries no report period, so its stated values cannot be era-normalized and are carried as stated.
