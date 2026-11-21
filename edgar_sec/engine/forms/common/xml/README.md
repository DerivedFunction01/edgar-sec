# `edgar_sec/engine/forms/common/xml` — XML passthrough and construction

Native XML detection, canonical XML building, and the unparsed-sections sidecar.

## Purpose

Owns the XML edge of form processing: streaming detection and passthrough for
native SEC XML filings (`native_xml`), shared canonical XML construction for
form renderers (`xml_builder`), and the unparsed-sections evidence sidecar
(`unparsed`) both of them serialize through.

## Contracts

- **One evidence record**: Unresolved scalar values and unparsed regions
  share the single sidecar record shape owned by `unparsed`.
- **Filesystem exception**: Only the unparsed-sections sidecar loader reads
  the filesystem; the rest is pure transformation.

## Deliberate gaps

- **No schema knowledge**: Form-specific XML vocabularies stay in the family
  packages; this package builds and passes through, never interprets.
