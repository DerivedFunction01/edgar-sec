# `edgar_sec/engine/document/whitespace` — final whitespace normalization

## Purpose

Three problems visible only once every earlier stage has run: line-end padding
left by markup wrapping, list items the source concatenated onto one line, and
blank runs accumulated by block-tag substitution.

## Contracts

- **Splitting is punctuation-gated.** A separator only splits when a bullet or
  footnote marker follows, and only when an alphanumeric follows that — so an
  inline column separator or a hyphenated phrase is not read as a list boundary.
- **Tagged tables are masked first.** Their internal spacing survives
  byte-for-byte, and a line carrying a table sentinel is never split.
- **Trailing newlines are preserved.** This stage normalizes; it does not
  truncate. The pipeline's final strip owns the outer edges.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Production consumers

`edgar_sec/engine/forms/normalize.py` — the `after_final_whitespace` stage of
`normalize_document`, after cover healing.

## Deliberate gaps

- **Representation-neutral by construction, not by assumption.** The pass keys on
  ASCII bullet markers and tagged-table sentinels, so a glyph-only non-ASCII
  bullet is never read as a list boundary.
- **No signature-region awareness.** This pass runs before the reflow stage that
  masks signature regions, so a signature block is still split on punctuation
  here.
