# `edgar_sec/engine/forms/common/tables` — tabular grid structure

Grid partitioning and column-anchor alignment for tabular form content.

## Purpose

Owns table structure recognition: partitioning a tabular grid into header,
data, and instructions (`tables`), and the form-schema column anchor
alignment state machine (`alignment`).

## Contracts

- **Structure only**: This package partitions and aligns grids; cell value
  parsing belongs to `values/` and row extraction to `fields/`.

## Deliberate gaps

- **No grid rendering**: ASCII/HTML grid conversion lives in
  `engine/tables/`; this package consumes its models, never re-renders them.
