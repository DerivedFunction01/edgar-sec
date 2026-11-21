# form_d

SEC Form D Notice of Exempt Offering processing and semantic review analysis (Layer 3: Engine).

## Purpose

Provides native XML pass-through, streaming XML parsing into typed domain models, canonical XML envelope serialization, and single-pass semantic review analysis for Form D and Form D/A submissions under Regulation D and Section 4(a)(5).

## Contracts

- **Byte-Identical Native Pass-Through**: Submissions conforming to the SEC XML specification pass through with 100% SHA-256 byte identity via `passthrough_sec_xml`.
- **Single-Pass Observation Index**: Semantic analysis indexes document elements once in a dictionary by local tag name, eliminating repeated full-tree DOM walks.
- **Arithmetic Invariance**: Validates non-indefinite offering amounts against the offering balance equation and records discrepancies as review signals.

## Deliberate gaps

- **Paper Era OCR Reconstruction**: Historical pre-2009 filings submitted on paper are out of scope; the pipeline targets modern electronic EDGAR submissions.

