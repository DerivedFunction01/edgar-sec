# `edgar_sec/engine/document/unpacking` — SGML envelopes and representation

## Purpose

Unpacks EDGAR submission envelopes and classifies the extracted content as
HTML, plain ASCII, or ASCII wrapped in `<PRE>`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `unpacker.py` | SGML unpacking, target resolution, selective extraction, PEM removal. |
| `representation.py` | Decoding, framing removal, representation classification, HTML-cleaning dispatch. |
| `ascii_pre.py` | ASCII `<PRE>` extraction. |

## Contracts

- Target resolution is deterministic and falls back to a usable text or HTML
  document when metadata is incomplete.
- Decoding and representation classification return a usable value for empty or
  malformed input rather than raising.
- A `<PRE>` wrapper alone is not enough to classify content as plain ASCII.
- HTML entities are preserved on the HTML path.

## Public surface

- `SgmlSubDocument`, `unpack_sgml_submission`, `find_sub_document`,
  `resolve_target_sub_document`, `extract_target_sub_document`,
  `has_sgml_documents`, `strip_pem_envelope` — `unpacker.py`.
- `Representation`, `decode_bytes`, `strip_envelope_text`,
  `strip_sgml_document_wrapper`, `prepare_input_text` — `representation.py`.
- `extract_ascii_pre` — `ascii_pre.py`.

## Command surface

None. Library package, no CLI.

## Mirrored tests

Mirrored coverage lives under `tests/engine/document/unpacking/`.

## Deliberate gaps

- **No acquisition, caching, or rate limiting.** Those belong to the HTTP and
  pipeline layers.
- **No exhibit-delegation triage.** Exhibit selection belongs to the pipeline.
