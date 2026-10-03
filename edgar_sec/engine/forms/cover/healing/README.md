# `edgar_sec/engine/forms/cover/healing` — cover text healing

Repairs the shapes an HTML cover render leaves behind that plain normalization
cannot see.

## Purpose

A binary Yes/No question arrives from an HTML cover as several stacked lines: the
question tail, a mark, an opposite-answer tail, and a box+dot spacer between them.
Left alone those lines defeat every downstream stage — a mark is no longer
adjacent to its answer, and a Yes and its No can end up on different lines.
`binary_blocks.py` recognises that shape and collapses it.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `binary_blocks.py` | Binary block detection, collapsing, and checkbox token normalization. |
| `text.py` | Bounded cover text healing: table masking, binary-block merging, phrase-sequence and date-fragment healing, then restoration. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

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

## Public surface

- `heal_cover_text(text, boundary, healing_rules, *, merge_binary_blocks=False, reflow_prose=True) -> tuple[str, bool]` — `text.py`.
- `merge_yes_no_binary_blocks(lines, *, scope=CheckmarkScope.GLOBAL_SAFE) -> list[str]` — `binary_blocks.py`.
- `normalize_checkbox_tokens(text, *, scope=CheckmarkScope.GLOBAL_SAFE) -> str` — `binary_blocks.py`.
- `classify_mark_line(line, *, context="gap", scope=CheckmarkScope.GLOBAL_SAFE) -> str` — `binary_blocks.py`.

## Command surface

None. Library package, no CLI.

## Tests

- `tests/engine/forms/cover/healing/test_binary_blocks.py`
- `tests/engine/forms/cover/healing/test_text.py`

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
