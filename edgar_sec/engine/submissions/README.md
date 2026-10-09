# `edgar_sec/engine/submissions` — SEC submissions JSON to canonical `submission_metadata` rows

## Purpose

`https://data.sec.gov/submissions/CIK##########.json` is loosely typed and varies across eras. The
same logical field arrives under two spellings (`investorWebsite` / `investorwebsite`), the filing
history arrives as parallel columnar arrays that are sometimes ragged, historical filings arrive
in separate files listed in `filings.files`, and the whole record must survive all of it.

This package is the only place that decision is made, and the contract it makes is narrow and
strong: **one requested CIK in, one row out, always conforming to `SUBMISSION_METADATA_SCHEMA`**,
with every deviation surfaced in the row's `anomalies` list rather than in an exception. It is
pure computation: no disk I/O, no network, no ambient state.

## Contracts

- **One row per requested CIK, including failures.** `_failed_row` carries every field of the
  schema with `status="failed"`, so completion is determinable from the data rather than from
  queue state. `status` is `ok` (no historical errors), `partial` (historical errors but some
  records survived), or `failed`.
- **Every coercion is total.** `accession_normalized` returns `None` rather than raising on a
  malformed accession — malformed accessions are data to be recorded and flagged, not an exception
  that would discard the surrounding filing record. `to_bool` preserves `None`; `to_int` returns
  `None` for anything non-integral; `normalize_items` accepts a list, a comma-joined string, or a
  scalar.
- **Alias conflicts are reported, not resolved.** `resolve_alias` picks the canonical key, then
  checks every other case-variant for disagreement and records an `alias_conflict` anomaly rather
  than silently taking whichever key sorted first.
- **Unrecognised payload keys are preserved, not dropped.** `normalize_submissions` computes
  `extra_fields` as everything outside `PROFILE_KEYS` (case-insensitively) and stores it as
  canonical JSON.
- **Ragged columns pad to the longest and are never truncated.** Short columns are filled with
  `None` and `filing_array_length_mismatch` is recorded, so a short column cannot silently drop
  trailing filings.
- **Source order is preserved; no chronological sort is applied.** `recent` records in array order,
  then each historical file in manifest order.
- **Deduplication is first-occurrence-wins, and a disagreement is a conflict, not an overwrite.**
  `dedupe_filings` records `accession_conflict` with the differing field pairs. Records with an
  unusable accession are all retained, since they are already flagged upstream.
- **Schema conformance is checked before it is assumed.** `validate_row_shapes` probes every
  non-`None` field against the declared Arrow type and re-raises as `ValueError` naming the
  offending field. It runs once inside `normalize_submissions` and again for every row in
  `build_submission_table`.
- **"Not supplied" stays distinguishable from "supplied but empty".** `normalize_address` returns
  `None` for a missing key and an all-`None` struct for `{}`; `normalize_former_names` retains
  unrecognised entry shapes and flags them rather than dropping them.
- **List-length mismatches never truncate.** `zip_listings` keeps the longer side and nulls the
  missing entries, recording `listings_length_mismatch`.
- **Archive URLs carry their own fallback reason.** `build_archive_url` returns
  `(url, fallback_reason)`; a null document produces `("primary_document_missing")` rather than a
  fabricated path, and a `.txt` or `0001.htm` primary document yields a reason prefixed
  `primary_document_stub:`.
- **Historical file records carry a derived `url` that is not a schema field.**
  `normalize_submission_files` returns it; `normalize_submissions` projects only the four
  schema-declared file fields when building the row.
- **Layer discipline.** Imports are `domain.sec_urls`, `domain.submissions.schemas` and
  `foundation.serialization`, plus sibling relative imports. No `pipelines`, no `infra`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **This package does not fetch.** It takes a payload dict it was handed. Retrieval, the SEC
  `User-Agent` header, rate limiting, and failure ledgers are
  [`edgar_sec/infra/sec_http`](../../infra/sec_http/README.md). The only production caller is
  [`pipelines/metadata_sync/worker.py`](../../pipelines/metadata_sync/worker.py), which
  supplies `historical_payloads` and `historical_errors` from a thread pool.
- **No historical-file fetching and no retry.** `historical_payloads` and `historical_errors` are
  *required inputs*, not best-effort extras. A failed historical file is reported through
  `status` / `error`; recovering it is the caller's job. There is no re-request, no backoff, and no
  per-file timeout here.
- **No validated identity values.** `accession_normalized` is deliberately *more permissive* than
  `edgar_sec.domain.identity.AccessionNumber`: it returns a string or `None` rather than
  constructing a validated value or raising. This package produces data for the identity layer; it
  does not own identity.
- **The schema itself is not here.** `SUBMISSION_METADATA_SCHEMA` and `SCHEMA_VERSION` come from
  `edgar_sec/domain/submissions/schemas.py` (Layer 1). Changing the output shape means changing that
  module, and a `ValueError` from `validate_row_shapes` is how the mismatch surfaces.
- **No anomaly taxonomy is enforced.** `add_anomaly` accepts any `code` string, and the codes in use
  today are conventional, not registered. A caller parsing `anomalies` must tolerate an unknown code.
- **The anomaly list is unbounded.** Nothing caps it and nothing deduplicates it: a ragged filing
  history with a bad accession produces one `accession_unusable` per row. The row is still
  schema-conforming, but it is large.
- **No company-family resolution here.** `company_name` is passed through as a raw payload string.
  Clustering happens in [`edgar_sec/engine/company_family/`](../company_family/README.md), and only
  for the selection pipeline.
