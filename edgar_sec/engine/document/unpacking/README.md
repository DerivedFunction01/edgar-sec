# `edgar_sec/engine/document/unpacking` — SGML envelopes and representation

## Purpose

Unpacks EDGAR submission envelopes and classifies the extracted content as
HTML, plain ASCII, or ASCII wrapped in `<PRE>`.

## Contracts

- Target resolution is deterministic and falls back to a usable text or HTML
  document when metadata is incomplete.
- Decoding and representation classification return a usable value for empty or
  malformed input rather than raising.
- A `<PRE>` wrapper alone is not enough to classify content as plain ASCII.
- HTML entities are preserved on the HTML path.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No acquisition, caching, or rate limiting.** Those belong to the HTTP and
  pipeline layers.
- **No exhibit-delegation triage.** Exhibit selection belongs to the pipeline.
