# `edgar_sec/engine/document/whitespace` — final whitespace normalization

## Purpose

Three problems visible only once every earlier stage has run: line-end padding
left by markup wrapping, list items the source concatenated onto one line, and
blank runs accumulated by block-tag substitution.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalizer.py` | `normalize_final_text_whitespace`, `split_concatenated_bullets`. |

## Contracts

- **Splitting is punctuation-gated.** A separator only splits when a bullet or
  footnote marker follows, and only when an alphanumeric follows that — so an
  inline column separator or a hyphenated phrase is not read as a list boundary.
- **Tagged tables are masked first.** Their internal spacing survives
  byte-for-byte, and a line carrying a table sentinel is never split.
- **Trailing newlines are preserved.** This stage normalizes; it does not
  truncate. The pipeline's final strip owns the outer edges.

## Public surface

`normalize_final_text_whitespace`, `split_concatenated_bullets` —
`normalizer.py`.

## Command surface

None. Library package, no CLI.

## Production consumers

`edgar_sec/engine/forms/normalize.py` — the `after_final_whitespace` stage of
`normalize_document`, after cover healing.

## Mirrored tests

`tests/engine/document/whitespace/test_normalizer.py`.

## Deliberate gaps

- **Representation-neutral by construction, not by assumption.** The pass keys on
  ASCII bullet markers and tagged-table sentinels, so a glyph-only non-ASCII
  bullet is not a split point. The production call site is the post-cover-healing
  text frame; cover-specific healing (line and date fragment repair, Yes/No
  merging) is `edgar_sec/engine/forms/cover/healing/`, not here.
- **No signature-region awareness.** A masked signature block would still be
  split on punctuation here. In `normalize_document` the reflow stage that owns
  signature masking runs after this pass, so no caller currently supplies a mask.