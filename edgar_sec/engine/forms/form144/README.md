# form144

Form 144 table classification, HTML-to-XML grid normalization, and semantic review analysis.

## Purpose

Extracts structured Form 144 data from legacy HTML multi-tier tables and synthesizes canonical `<edgarSubmission>` XML matching SEC electronic filing specifications.

Provides automated semantic diagnostics for review runs, auditing field completeness, detecting statutory boilerplate leaks, and flagging unparsed sections.

## Contracts

- **XML synthesis conformity**: Output XML conforms to `<edgarSubmission>` with `<formData>` containing issuer, proposed sale, Table I, Table II, and signature blocks.
- **Source fidelity**: Values absent from source filings remain unpopulated without fabricated defaults.
- **Downward layering**: Imports only domain and infra modules; never tools, apps, or pipelines.

## Deliberate gaps

- **Paper filing OCR**: Focuses on electronic XML and HTML filings; direct image OCR is deferred.
