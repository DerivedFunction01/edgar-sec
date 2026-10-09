# `edgar_sec/engine/forms/cover/healing` — cover text healing

Repairs the shapes an HTML cover render leaves behind that plain normalization
cannot see.

## Purpose

A binary Yes/No question arrives from an HTML cover as several stacked lines: the
question tail, a mark, an opposite-answer tail, and a box+dot spacer between them.
Left alone those lines defeat every downstream stage — a mark is no longer
adjacent to its answer, and a Yes and its No can end up on different lines.
`binary_blocks.py` recognises that shape and collapses it.

## Contracts

`heal_cover_text` works on the line slice before `boundary.end_line` and never
reaches the body:

- Tagged tables are masked for the whole line-level pass and restored
  afterwards. A pass that could account for every sentinel restores; one that
  cannot returns the original text and `False` rather than a cover that lost a
  table.
- Global-safe checkbox normalization runs last, over the healed slice *including*
  restored table content, because masked cells never reached the line-level
  pass.
- The returned boolean reports whether the text changed, so a caller can
  refresh line-coordinate analyses.

`binary_blocks.py` contracts:

- Only the specific Yes/No block shape is merged: a question tail, zero or more
  recognised mark lines or box+dot spacers, the opposite question tail, and a
  trailing mark. A single bare bullet is never evidence of a binary block.
- A separator line inside a block breaks the block rather than being stripped.
- Lines outside a detected block are returned unchanged except for
  `normalize_checkbox_tokens`, which canonicalises globally safe marks.
- `normalize_checkbox_tokens` leaves a lone underscore run alone. Two runs
  separated by whitespace, `[ ]`, `{ }`, `(_ )`, `/   /`, and a bare `x` are
  canonicalised; a bare `o` is not.
- Context glyphs such as `●` are canonicalised only under
  `CheckmarkScope.COVER_CONTEXT` or `ALL`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **The reflow branch is dormant.** `heal_cover_text` only reflows when
  `reflow_prose=True`, and its sole caller `normalize_document` passes
  `reflow_prose=False` until cover boundary/table interactions are resolved.
  The code path is live and tested; nothing exercises it in production.
- **Phrase healing and reflow are mutually exclusive here.** When
  `reflow_prose=True` the configured `healing_rules` are not applied, because
  the reflow has already merged the lines they would have joined.
- **The block window is ten lines.** A binary question rendered across more than
  ten intervening lines is not recognised, and the lines are left in place.
- **No mark-position inference beyond the three declared contexts.** A mark in any
  other position on a single-character line classifies as `unknown`.
