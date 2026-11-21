# `edgar_sec/engine/forms/common` — shared form transformation helpers

Reusable engine parsers and extraction utilities shared across multi-form pipelines.

## Purpose

Provides reusable token-based extractors for conformed signatures, delegation structures,
source-aware phrase annotations, and legal notice boundary detection across diverse SEC
form families. Owns the shared field contract every form family normalizes through: value
types, date anchoring, jurisdiction resolution, tabular row extraction, and
unresolved-content evidence.

## Contracts

- **Layer discipline**: Sits in Layer 3 (`engine/`), importing only from `domain`, `foundation`, and other `engine` modules.
- **Pure transformation**: Offline text and node parsing with zero network I/O; only the unparsed-sections sidecar loader reads the filesystem.
- **Total parsers**: Text parsers never throw on malformed or partial input; the sidecar loader and field-spec validation raise `ValueError` on invalid records.
- **One field contract**: Families declare fields and table columns as specs; this module owns normalization, constraint checking, and XML emission.
- **One evidence record**: Unresolved scalar values and unparsed regions share a single sidecar record shape.
- **One mark writer**: `marks.py` owns how a recognized mark is written back into parser input; the token vocabulary stays in the domain layer.
- **Source-aware phrase matches**: Phrase classification returns source offsets and neighboring lines; matching never mutates parser input.

## Deliberate gaps

- **Raster OCR**: Only conformed typed or markup signatures are resolved; handwritten scans remain deferred.
