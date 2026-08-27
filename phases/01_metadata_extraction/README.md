# Phase 01 — Submissions Metadata Extraction

Pipeline A, Part 1. Transforms the SEC `data.sec.gov/submissions` feed into a
versioned, queryable `submission_metadata` dataset (Parquet / JSONL) with
provenance and resumable runs.

One output row per CIK. For each filing CIK the phase fetches the current
submissions JSON, follows every historical submissions file, and combines all
filing records (recent + historical) into a single nested `filings` list on
that row. Entity profile fields (name, SIC, address, listings, former names,
identifiers, insider flags) are modeled as typed structs, and anything not yet
modeled is preserved verbatim in `extra_fields`.

## Layout

```text
phases/01_metadata_extraction/
  cli.py            # canonical command surface: plan / preview / run / status / merge
  run.py            # transitional interactive wizard + non-interactive single-chunk runner
  smoke_test.py     # bounded SEC-backed preview shim (never writes production output)
  core/             # schemas, normalization, planning, checkpoints, merge, SEC client
    schemas.py      # explicit PyArrow schema for submission_metadata (v1.0.0)
    normalize.py    # deterministic, network-free normalization of SEC JSON
    input_manifest.py  # CIK/name CSV validation + deterministic ordering + fingerprint
    application.py  # orchestration: build_plan / run_chunk / get_status / merge
    config.py       # RunOptions / ProjectConfig persistence (config.json, plan.json)
    chunks.py       # chunk + partition assignment (deterministic, shared across phases)
    storage.py      # checkpoint + phase stores (shared defs.storage backend)
    sec_client.py   # submissions fetch client (pacing, retries, caching, failure ledger)
    merge.py        # merge validation + atomic publication
    checkpoints.py  # immutable, schema-versioned chunk checkpoints
  tests/            # offline contract + fixture-replay tests (no live SEC calls)
```

## Canonical command surface

All production commands go through `cli.py`; the same `RunOptions` drive the
interactive `run.py` wizard. From the repository root:

```bash
# 1. Write a plan (no network): validate CSV, assign chunks/partitions, hash it.
.venv/bin/python -m phases.01_metadata_extraction.cli plan \
    --config .artifacts/metadata/config.json

# 2. Bounded SEC-backed smoke test (writes to .artifacts/metadata/preview only).
.venv/bin/python -m phases.01_metadata_extraction.cli preview --sample-size 3

# 3. Run one operational partition (one or many machines; skips done chunks).
.venv/bin/python -m phases.01_metadata_extraction.cli run \
    --config .artifacts/metadata/config.json --partition-id 1

# 4. Inspect progress and mergeability (no re-fetch).
.venv/bin/python -m phases.01_metadata_extraction.cli status \
    --artifacts .artifacts/metadata/runs/<run-id>

# 5. Validate and publish the unified dataset.
.venv/bin/python -m phases.01_metadata_extraction.cli merge \
    --artifacts .artifacts/metadata/runs/<run-id> \
    --output phases/01_metadata_extraction/output/merged/submission_metadata.parquet
```

`run.py` also works as an interactive wizard when `--chunk-id` is omitted:

```bash
.venv/bin/python -m phases.01_metadata_extraction.run \
    --config .artifacts/metadata/config.json
```

## Configuration

`--configure` is the only writer of `.artifacts/metadata/config.json`. A missing
config is created as a validated template and the run stops before any network
work so the SEC contact identity (`--user-agent` / `SEC_USER_AGENT`,
`AppName/1.0 contact@example.com`) can be added first. CLI flags are temporary
overrides and are never persisted.

`plan.json` is an immutable snapshot of the effective run options plus an input
fingerprint and plan hash. If the effective options or input CSV change, the plan
is rejected with a regeneration message rather than silently rewritten.

## Dataset contract

- **One row per CIK.** Failures are still emitted as terminal `failed` rows so
  completeness is determined from data, not queue state.
- **Status** is `ok | partial | failed`. `partial` means some historical files
  failed but recent filings were recovered.
- **Provenance** on every row: `snapshot_id`, `fetched_at`, `source_url`,
  `response_sha256`, `byte_count`, `schema_version`, `input_fingerprint`,
  `chunk_id`, and per-filing `source_section` / `source_file` / `source_array_index`.
- **Strict null vs empty.** `""`, `null`, `{}`, and `[]` are not coerced into one
  value; an empty `filings.recent` object is a successful zero-filing result, not
  a fetch failure.
- **Anomalies, not silent coercion.** Field-name aliases (`investorWebsite` vs
  `investorwebsite`), `ticker`/`exchange` length mismatches, and filing-history
  array length mismatches are recorded in `anomalies` and never silently truncated
  or chosen.
- **Accession integrity.** Every filing carries both the hyphenated
  `accession_number` and the validated de-hyphenated form, plus a derived archive
  URL. Conflicting duplicate accessions are flagged, not overwritten.

## Resumability and storage

- Fixed-size **chunks** are the internal resumability unit; **partitions** are the
  user-facing distribution unit. Both assignments are deterministic and shared
  across phases.
- Completed chunks are skipped and never re-fetched. Checkpoints are immutable,
  schema-versioned fragments; the coordinator-only `merge` validates identity,
  provenance, schema, fingerprint, row counts, duplicates, and terminal statuses
  before publishing atomically.
- Checkpoints support `parquet` (default) and `jsonl` (useful for inspection).
  The final output format follows the `--output` suffix unless overridden.

## Testing

```bash
.venv/bin/pytest phases/01_metadata_extraction/tests
```

Default tests use a fake SEC client and deterministic storage — no live SEC or
model calls. Fixtures live under `tests/fixtures/` (synthetic/secsanitized SEC
shapes, malformed payloads, era-specific filings).
