# `edgar_sec.engine.filing_summary`

## Purpose

Transform an SEC FilingSummary document or EDGAR-generated XBRL package into typed inventory outcomes without fetching or persisting data. This is the index-free enumeration vehicle for catalog-flagged XBRL filings: the summary names the filing's documents, and the enumerator synthesizes the same inventory entries the index parser produces from an index page.

## Contracts

- **Parsing consumes explicit bytes and domain records**: Uses only the standard XML and zip readers; no network or artifact access.
- **The primary entry is synthesized from catalog facts, never from a listing**: A listing that also names the primary dedupes to the synthesized row; the inline extracted instance is likewise synthesized from the primary document's stem.
- **A summary without an InputFiles section is a typed refusal**: It yields `UnrecognizedEnumeration`, never an empty success.
- **Entry fields a vehicle cannot supply stay null**: `sequence` is always null, and `byte_size` is null on the summary path (the package path supplies real sizes from the zip directory).
- **The bundle URL is constructed, not observed**: It is a candidate, never proof of existence.
- **Engine imports are restricted to `infra`, `domain`, `foundation`**: No pipeline imports.

## Deliberate gaps

- **Exhibit and graphic types are not synthesized**: The vehicles carry no declared types, so non-primary document-format entries are name-only; measured coverage deltas live in the Step 1 specimen record under `.artifacts/run-logs/`.
