# `edgar_sec/engine/forms/common` — shared form transformation helpers

Reusable engine parsers and extraction utilities shared across multi-form pipelines.

## Purpose

Provides reusable token-based extractors for conformed signatures, delegation structures,
and legal notice boundary detection across diverse SEC form families.

## Contracts

- **Layer discipline**: Sits in Layer 3 (`engine/`), importing only from `domain` and `foundation`.
- **Pure transformation**: Offline text and node parsing with zero network or filesystem I/O.
- **Total functions**: Parsers never throw on malformed or partial input.

## Deliberate gaps

- **Raster OCR**: Only conformed typed or markup signatures are resolved; handwritten scans remain deferred.
