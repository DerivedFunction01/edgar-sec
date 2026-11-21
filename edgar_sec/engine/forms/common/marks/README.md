# `edgar_sec/engine/forms/common/marks` — mark recognition

Mark canonicalization, mark/label association, and columnar signature extraction.

## Purpose

Owns how recognized marks are read and written back: parser-facing mark
canonicalization (`marks`), geometry-only positions and association for mark
and label spans (`mark_association`), and columnar (fixed-width) signature
and notice-date extraction (`columnar_signatures`).

## Contracts

- **One mark writer**: `marks` owns how a recognized mark is written back
  into parser input; the token vocabulary stays in the domain layer.
- **Geometry only**: Association works on span positions, never on mark
  semantics.

## Deliberate gaps

- **No signature blocks**: Conformed signature block parsing lives in the
  sibling `signatures/` package; this package handles marks and columnar
  signature lines.
