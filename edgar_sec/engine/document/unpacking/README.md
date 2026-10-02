# `edgar_sec/engine/document/unpacking` — SGML envelopes and representation

## Purpose

Everything that happens before the engine knows what kind of document it holds:
unwrap the EDGAR submission envelope, strip framing a fetcher-bypass caller may
have skipped, decode the bytes, and answer the question the whole stage chain
branches on — real HTML, plain ASCII, or ASCII inside a `<PRE>` wrapper?

## Layout

| Module | Responsibility |
| :--- | :--- |
| `unpacker.py` | SGML `<DOCUMENT>` unpacking, four-tier target resolution, selective extraction, PEM removal. |
| `representation.py` | Decode ladder, transport-framing removal, representation classification, HTML Stage-1 cleaning dispatch. |
| `ascii_pre.py` | `extract_ascii_pre` — PRE-wrapper discrimination. |

## Contracts

- **Four ordered resolution tiers, first match wins**: target types → primary
  filename → `SEQUENCE 1` → first non-binary text/HTML document. The final tier
  is load-bearing: returning `None` for a `<TYPE>` the caller did not enumerate
  would abort acquisition of an otherwise valid filing.
- **`extract_target_sub_document` never decodes a losing document.** It builds a
  light record per block with `raw_payload=b""`, resolves over those, then slices
  the winner's bytes.
- **SGML decoding is latin-1 and lossless**; `decode_bytes` in `representation.py`
  is the separate UTF-8 → CP1252 → Latin-1 ladder.
- **`prepare_input_text` stage order is load-bearing**: decode → strip envelopes
  → purge non-displaying blocks → test for ASCII-PRE → classify → clean.
- **ASCII-PRE requires proof, not a `<PRE>` tag**: exactly one `<PRE>`, nothing
  but tags outside it, no layout markup inside it. Real HTML using `<PRE>` for
  layout must return `None`, or the whole filing is routed as ASCII.
- **`<TABLE>`/`<S>`/`<C>` are not HTML evidence** — that is ASCII statement markup,
  so a document made only of them classifies as `ASCII_PLAIN`.
- **HTML entities survive the HTML path.** Unescaping runs only on the ASCII
  branches, so an escaped `&lt;tag&gt;` cannot become a synthetic tag.
- **Nothing raises.** Empty input, unterminated `<PRE>`, and malformed bytes all
  return a usable value.

## Public surface

- `SgmlSubDocument`, `unpack_sgml_submission`, `find_sub_document`,
  `resolve_target_sub_document`, `extract_target_sub_document`,
  `has_sgml_documents`, `strip_pem_envelope` — `unpacker.py`.
- `Representation`, `decode_bytes`, `strip_envelope_text`,
  `strip_sgml_document_wrapper`, `prepare_input_text` — `representation.py`.
- `extract_ascii_pre` — `ascii_pre.py`.

## Command surface

None. Library package, no CLI.

## Production consumers

- `edgar_sec/engine/forms/normalize.py` — `prepare_input_text`, in the `unpacked`
  stage of `normalize_document`.
- `edgar_sec/pipelines/document_storage/fetching.py` — `unpack_sgml_submission`,
  `has_sgml_documents`, `strip_pem_envelope`, `extract_target_sub_document`.
- `edgar_sec/pipelines/document_storage/delegation.py` — `SgmlSubDocument`,
  `unpack_sgml_submission`, `find_sub_document`, `has_sgml_documents`.

## Mirrored tests

`tests/engine/document/unpacking/` — `test_unpacker.py`, `test_representation.py`,
`test_ascii_pre.py`. One per module; all three exist.

## Deliberate gaps

- **`html/cleaner.py` lives in a sibling package.** `representation.py` imports
  `clean_html_for_parsing` and `strip_non_displaying_blocks` from
  `edgar_sec/engine/document/html/`, because the purge must run before
  classification. A one-way sibling import, not a cycle.
- **No word counting.** The pipeline computes `word_count` in
  `pipelines/document_storage/processor.py`, where it is consumed; keeping it out
  of the engine is deliberate.
- **No acquisition, no caching, no rate limiting.** Those are
  `edgar_sec/infra/sec_http` and `pipelines/document_storage`.
- **No exhibit-delegation triage.** Which exhibit is the target document is a
  pipeline decision, informed by the per-form evaluators in
  `edgar_sec/engine/forms/plugins/evaluators/`.