# `edgar_sec/engine/forms/common` — shared form transformation helpers

Reusable engine parsers and extraction utilities shared across multi-form pipelines.

## Purpose

Provides reusable token-based extractors for conformed signatures, delegation structures,
and legal notice boundary detection across diverse SEC form families. Owns the shared
field contract every form family normalizes through: value types, date anchoring,
jurisdiction resolution, tabular row extraction, and unresolved-content evidence.

## Contracts

- **Layer discipline**: Sits in Layer 3 (`engine/`), importing only from `domain` and `foundation`.
- **Pure transformation**: Offline text and node parsing with zero network or filesystem I/O.
- **Total functions**: Parsers never throw on malformed or partial input.
- **One field contract**: Families declare fields and table columns as specs; this module owns normalization, constraint checking, and XML emission.
- **One evidence record**: Unresolved scalar values and unparsed regions share a single sidecar record shape.

## Deliberate gaps

- **Raster OCR**: Only conformed typed or markup signatures are resolved; handwritten scans remain deferred.
