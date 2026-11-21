# geometry

## Purpose

The geometry stages of the ascii_html renderer: border and divider
recognition, column resolution, span ownership, and column widths over
the resolved grid the model subpackage defines.

## Contracts

- **Span ownership is resolved once**: `spans.build_span_matrix` assigns
  rowspan/colspan ownership; every later stage reads positions, never
  re-derives them.
- **Rendered width respects the supplied budget**: `widths` balances
  span widths against the render budget the model supplies.

## Deliberate gaps

- **Inferred dimensions stay estimates**: geometry is inferred from the
  source table's shape and carries the renderer's confidence
  information, never a parsed guarantee.
