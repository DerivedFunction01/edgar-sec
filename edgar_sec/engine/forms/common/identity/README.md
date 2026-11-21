# `edgar_sec/engine/forms/common/identity` — registrant and reporting-person identity

Entity parsers, the registrant head-line scan, and the facing/cover heads.

## Purpose

Owns who a filing is about: compiled regexes and parsers for reporting
persons, issuers, and addresses (`entities`), the canonical head-line scan
for the registrant name (`registrant_scan`), and the shared facing-sheet and
ICA cover-head extractors (`facing_sheet`, `ica_head`) built on them.

## Contracts

- **One identity seam**: Families resolve registrant and reporting-person
  identity through these parsers, never through local name regexes.

## Deliberate gaps

- **No cover layout policy**: Checkbox and layout analysis of the cover live
  in `engine/forms/cover/`; this package extracts the identity the head
  carries.
