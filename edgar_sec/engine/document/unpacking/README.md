# `edgar_sec/engine/document/unpacking` — SGML envelopes and representation

## Purpose

Unpacks EDGAR submission envelopes and classifies the extracted content as
HTML, plain ASCII, or ASCII wrapped in `<PRE>`.

## Contracts

- **Target resolution is deterministic and falls back**: Uses usable text/HTML when metadata is incomplete.
- **Decoding and representation classification do not raise**: Return usable value for empty/malformed input.
- **A `<PRE>` wrapper alone does not classify plain ASCII**: Requires additional content evidence.
- **HTML entities are preserved on the HTML path**: Not escaped during projection.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No acquisition, caching, or rate limiting**: Belong to HTTP and pipeline layers.
- **No exhibit-delegation triage**: Exhibit selection belongs to pipeline.
