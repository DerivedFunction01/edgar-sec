# `edgar_sec/engine/submissions` — SEC submissions JSON to canonical `submission_metadata` rows

Normalizes one SEC submissions payload — plus its historical companion files — into exactly one
schema-conforming row dict, and assembles those rows into an Arrow table. Every coercion is
total: a malformed field is recorded as an anomaly, never raised, so one bad field can never
discard an otherwise valid filing record.

## Purpose

`https://data.sec.gov/submissions/CIK##########.json` is loosely typed and varies across eras.
The same logical field arrives under two spellings (`investorWebsite` / `investorwebsite`), the
filing history arrives as parallel columnar arrays that are sometimes ragged, historical
filings arrive in separate files listed in `filings.files`, and the whole record must survive
all of it.

This package is the only place that decision is made, and the contract it makes is narrow and
strong: **one requested CIK in, one row out, always conforming to
`SUBMISSION_METADATA_SCHEMA`**, with every deviation surfaced in the row's `anomalies` list
rather than in an exception.

It is pure computation. No disk I/O, no network, no ambient state
(`edgar_sec/engine/submissions/__init__.py:1-4`).

## Layout

| Module | Responsibility |
| :--- | :--- |
| `builder.py` | The assembly. `normalize_submissions` builds one canonical row; `validate_row_shapes` fail-fasts on any value that will not fit the declared Arrow field type; `build_submission_table` assembles rows into a `pa.Table`; `_failed_row` emits a terminal row carrying every schema field. |
| `filings.py` | The columnar unroller. `zip_filing_arrays` turns one `filings.recent`-shaped section into one record dict per index; `dedupe_filings` is first-occurrence-wins on the normalized accession; `normalize_submission_files` normalizes the historical file descriptors. `FILING_ARRAY_KEYS` names the 16 columns. |
| `profile.py` | Entity identity. `PROFILE_KEYS` (the 24 recognised payload keys), `ADDRESS_KEYS` (the 10 address fields), `address_field` (camelCase → snake_case), `zip_listings`, `normalize_address`, `normalize_former_names`. |
| `helpers.py` | The coercion primitives. `add_anomaly`, `resolve_alias`, `normalize_cik_padded`, `accession_normalized`, `build_archive_url`, `normalize_items`, `to_bool`, `to_int`, plus `ACCESSION_RE` and a re-export of `canonical_json`. |

## Contracts

- **One row per requested CIK, including failures.** `_failed_row` (`builder.py:42-97`) carries
  every field of the schema with `status="failed"`, so completion is determinable from the data
  rather than from queue state (`builder.py:53-56`). `status` is one of `ok` (no historical
  errors), `partial` (historical errors but some records survived), or `failed` (`builder.py:211-217`).
- **Every coercion is total.** `accession_normalized` returns `None` rather than raising on a
  malformed accession — "malformed accessions are data to be recorded and flagged here, not an
  exception that would discard the surrounding filing record" (`helpers.py:80-82`).
  `to_bool` preserves `None`; `to_int` returns `None` for anything non-integral; `normalize_items`
  accepts a list, a comma-joined string, or a scalar.
- **Alias conflicts are reported, not resolved.** `resolve_alias` picks the canonical key, then
  checks every other case-variant for disagreement and records an `alias_conflict` anomaly rather
  than silently taking whichever key sorted first (`helpers.py:42-68`).
- **Unrecognised payload keys are preserved, not dropped.** `normalize_submissions` computes
  `extra_fields` as everything outside `PROFILE_KEYS` and stores it as canonical JSON
  (`builder.py:134-138`, `:230`).
- **Ragged columns pad to the longest and are never truncated.** `zip_filing_arrays` computes
  `row_count = max(lengths.values())` and fills short columns with `None`, recording
  `filing_array_length_mismatch` first (`filings.py:66-96`). A short column cannot silently drop
  trailing filings.
- **Source order is preserved; no chronological sort is applied.** `recent` records in array
  order, then each historical file in manifest order (`filings.py:8-10`).
- **Deduplication is first-occurrence-wins, and a disagreement is a conflict, not an overwrite.**
  `dedupe_filings` compares `form`, `filing_date`, `report_date`, and `primary_document` on a
  duplicate accession and records `accession_conflict` with the differing pairs
  (`filings.py:168-180`). Records with an unusable accession are all retained, since they are
  already flagged upstream (`filings.py:158-161`).
- **Schema conformance is checked before it is assumed.** `validate_row_shapes` probes every
  non-`None` field with `pa.array([value], type=field.type)` and re-raises as `ValueError` naming
  the offending field (`builder.py:28-39`). It runs once inside `normalize_submissions` and again
  for every row in `build_submission_table` (`builder.py:287`, `:296`).
- **"Not supplied" stays distinguishable from "supplied but empty".** `normalize_address` returns
  `None` for a missing key and an all-`None` struct for `{}` (`profile.py:98-101`);
  `normalize_former_names` retains unrecognised entry shapes and flags them rather than dropping
  them (`profile.py:152-159`).
- **List-length mismatches never truncate.** `zip_listings` keeps the longer side and nulls the
  missing entries, recording `listings_length_mismatch` (`profile.py:75-82`).
- **Archive URLs carry their own fallback reason.** `build_archive_url` returns
  `(url, fallback_reason)` and a null document produces `("primary_document_missing")` rather
  than a fabricated path; a `.txt` or `0001.htm` primary document yields a reason prefixed
  `primary_document_stub:` (`helpers.py:92-110`).
- **Historical file records carry a derived `url` that is not a schema field.**
  `normalize_submission_files` adds it, and `normalize_submissions` projects only
  `("name", "filing_count", "filing_from", "filing_to")` when building the row
  (`filings.py:184-188`; `builder.py:23`, `:276-279`).
- **Layer discipline.** Imports are `domain.sec_urls`, `domain.submissions.schemas`, and
  `foundation.serialization`, plus sibling relative imports. No `pipelines`, no `infra`.

## Public surface

- `normalize_submissions` — build one canonical `submission_metadata` row.
  `edgar_sec/engine/submissions/builder.py:100`.
- `build_submission_table` — assemble normalized rows into a schema-conforming `pa.Table`.
  `edgar_sec/engine/submissions/builder.py:291`.
- `validate_row_shapes` — fail fast on any value that will not fit the Arrow schema.
  `edgar_sec/engine/submissions/builder.py:28`.
- `zip_filing_arrays` — one filing-history column set into one record dict per index.
  `edgar_sec/engine/submissions/filings.py:58`.
- `dedupe_filings` — drop duplicate accessions, keeping the first occurrence; returns
  `(records, duplicates)`. `edgar_sec/engine/submissions/filings.py:144`.
- `normalize_submission_files` — normalize historical file descriptors, accepting SEC key case
  variants. `edgar_sec/engine/submissions/filings.py:184`.
- `FILING_ARRAY_KEYS` — the 16 unrolled filing columns.
  `edgar_sec/engine/submissions/filings.py:31`.
- `PROFILE_KEYS` / `ADDRESS_KEYS` — the recognised payload and address key sets.
  `edgar_sec/engine/submissions/profile.py:10` and `:37`.
- `address_field` — SEC camelCase address key to canonical snake_case field name.
  `edgar_sec/engine/submissions/profile.py:62`.
- `zip_listings` — zip tickers and exchanges by index, preserving order and duplicates.
  `edgar_sec/engine/submissions/profile.py:67`.
- `normalize_address` — one address object into the canonical snake_case struct.
  `edgar_sec/engine/submissions/profile.py:96`.
- `normalize_former_names` — `formerNames` entries of `[name, from, to]` or object form.
  `edgar_sec/engine/submissions/profile.py:127`.
- `add_anomaly` — append one `{code, detail, source}` record.
  `edgar_sec/engine/submissions/helpers.py:35`.
- `resolve_alias` — resolve a case-insensitive known alias, flagging disagreeing duplicates.
  `edgar_sec/engine/submissions/helpers.py:42`.
- `normalize_cik_padded` — ten-digit zero-padded CIK from an int or string.
  `edgar_sec/engine/submissions/helpers.py:71`.
- `accession_normalized` — hyphen-free 18-digit accession, or `None`.
  `edgar_sec/engine/submissions/helpers.py:77`.
- `ACCESSION_RE` — `^\d{10}-\d{2}-\d{6}$`, the hyphenated form.
  `edgar_sec/engine/submissions/helpers.py:19`.
- `build_archive_url` — `(url, fallback_reason)` for the archive document URL.
  `edgar_sec/engine/submissions/helpers.py:92`.
- `normalize_items` — filing items as a list, whether supplied as a list or a comma-joined
  string. `edgar_sec/engine/submissions/helpers.py:113`.
- `to_bool` / `to_int` — the numeric and boolean coercions.
  `edgar_sec/engine/submissions/helpers.py:125` and `:140`.
- `canonical_json` — re-exported from `edgar_sec.foundation.serialization` for the three modules
  that record structured anomaly details. `edgar_sec/engine/submissions/helpers.py:17`.

## Tests

- `tests/engine/submissions/test_normalizer.py` (356 lines) — parity tests. The expectations are
  golden values captured from the legacy `.v1` normalizer run against the same committed
  fixtures; the module docstring states that a deviation is a parity regression, not a
  preference change.

Note the filename: the test is `test_normalizer.py`, but there is no `normalizer.py` in
`edgar_sec/engine/submissions/`. The name is inherited from v1's `phases/01/.../normalize/`
and is the one place in this package where the test tree does not mirror the source tree
(`AGENTS.md` §6.2). It does cover all four source modules.

## Deliberate gaps

- **This package does not fetch.** It takes a payload dict it was handed. Retrieval, the
  SEC `User-Agent` header, rate limiting, and failure ledgers are
  `edgar_sec/infra/sec_http`. The only production caller is
  `edgar_sec/pipelines/metadata_sync/worker.py`, which supplies
  `historical_payloads` and `historical_errors` from a thread pool
  (roadmap `v2_refactor_roadmap.md` sec. 3: "`worker.py`: Thread pool fetching submissions and
  calling `engine.submissions`").
- **No historical-file fetching and no retry.** `historical_payloads` and `historical_errors`
  are *required inputs*, not best-effort extras (`builder.py:118-120`). A failed historical file
  is reported through `status`/`error`; recovering it is the caller's job. There is no
  re-request, no backoff, and no per-file timeout here.
- **No identity primitives.** `accession_normalized` is deliberately *more permissive* than
  `edgar_sec.domain.identity.AccessionNumber` (`helpers.py:80-82`): it returns a string or
  `None` rather than constructing a validated value or raising. This package produces data for
  the identity layer; it does not own identity.
- **The schema itself is not here.** `SUBMISSION_METADATA_SCHEMA` and `SCHEMA_VERSION` come from
  `edgar_sec/domain/submissions/schemas.py` (Layer 1). Changing the output shape means changing
  that module, and a `ValueError` from `validate_row_shapes` is how the mismatch surfaces.
- **No anomaly taxonomy is enforced.** `add_anomaly` accepts any `code` string. The codes in use
  today (`alias_conflict`, `listings_length_mismatch`, `unknown_address_keys`,
  `address_not_object`, `former_names_not_list`, `former_names_entry`,
  `unknown_filing_array_keys`, `filing_array_length_mismatch`, `accession_unusable`,
  `accession_conflict`, `files_not_list`, `file_descriptor_not_object`, `recent_missing`,
  `recent_not_object`, `historical_payload_not_object`, `filings_not_object`,
  `addresses_not_object`, `primary_document_missing`, `primary_document_stub:*`) are
  conventional, not registered. A caller parsing `anomalies` must tolerate an unknown code.
- **The anomaly list is unbounded.** Nothing caps it, and nothing deduplicates it: a 10,000-row
  ragged filing history with a bad accession produces one `accession_unusable` per row. The row
  is still schema-conforming, but it is large.
- **No entry point.** No CLI, no `python -m edgar_sec.engine.submissions`. `run.py metadata-sync`
  drives it from Layer 4.
- **No company-family resolution here.** `company_name` is passed through as a raw payload
  string. Clustering happens in `edgar_sec/engine/company_family/`, and only for the selection
  pipeline.
- **One test file, not four.** See the Tests section. `test_normalizer.py` exercises `builder`,
  `filings`, `profile`, and `helpers` together, so a failure does not localise to a module.
