# form144

Form 144 table classification, HTML-to-XML grid normalization, and semantic review analysis.

## Purpose

Extracts supported Form 144 fields from legacy HTML tables and serializes them using the supplied XML field types and formats.

Provides automated semantic diagnostics for review runs, auditing field completeness, detecting statutory boilerplate leaks, and flagging unparsed sections.

## Contracts

- **Schema-shaped output**: Recognized values use Form 144 XML field types; the analyzer reports missing conditional and required values.
- **Source fidelity**: Values absent from source filings remain unpopulated without fabricated defaults.
- **Unparsed tables**: Review runs persist residual table HTML in `operations/unparsed_sections.json`, outside XML payloads.
- **Downward layering**: Imports only domain and infra modules; never tools, apps, or pipelines.

## Deliberate gaps

- **Paper filing OCR**: Focuses on electronic XML and HTML filings; direct image OCR is deferred.
