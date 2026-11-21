# model

## Purpose

The cell and block model the ascii_html renderer stages share: the
resolved grid and table geometry types, cell text wrapping and style
parsing, render blocks, paren reunification, and span-width balancing.

## Contracts

- **One rendered line equals one logical row**: `TableGeometry.rows`
  is the resolved grid, never re-parsed from the emitted text.
- **Split parens are reunited in the geometry**: a value cell printed
  as `(digits` takes back its closing paren from the narrow column
  that carries it, so consumers read balanced accounting negatives.

## Deliberate gaps

- **A bare `hidden` attribute never hides a cell**: the parser reports
  a valueless `hidden` attribute with a `None` value and the attribute
  map drops `None` values, so the `attrs.get("hidden") is not None`
  probe in `cell.parse_style_and_attributes` cannot fire. Hiding
  requires `display:none` or `visibility:hidden` in the style
  attribute.
