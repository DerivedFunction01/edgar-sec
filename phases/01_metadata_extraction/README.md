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

# 2. Bounded SEC-backed smoke test (writes to transient preview storage).
.venv/bin/python -m phases.01_metadata_extraction.cli preview --sample-size 3

# 3. Run one operational partition (one or many machines; skips done chunks).
.venv/bin/python -m phases.01_metadata_extraction.cli run \
    --config .artifacts/metadata/config.json --partition-id 1

# 4. Inspect progress and mergeability (no re-fetch).
.venv/bin/python -m phases.01_metadata_extraction.cli status \
    --artifacts .artifacts/transient/metadata/runs/<run-id>

# 5. Publish one partition's chunks into a complete, portable partition dataset.
.venv/bin/python -m phases.01_metadata_extraction.cli merge-partition \
    --artifacts .artifacts/transient/metadata/runs/<run-id> --partition-id 1

# 6. Combine every completed published partition into the final dataset.
#    The final merge reads only published partition datasets and receipts.
.venv/bin/python -m phases.01_metadata_extraction.cli merge \
    --artifacts .artifacts/transient/metadata/runs/<run-id>
```

`run.py` also works as an interactive wizard when `--chunk-id` is omitted:

```bash
.venv/bin/python -m phases.01_metadata_extraction.run \
    --config .artifacts/metadata/config.json
```

The wizard offers: preview (1), run partition (2), show per-machine partition
commands (3), status (4), merge a partition from its chunks (5), and merge all
partition artifacts into the final dataset (6).

### Distributed run layout

Chunks and plans are transient; each completed partition is published separately:

```text
transient/metadata/runs/<run-id>/
  plan.json
  partitions/partition-00001.json
  partitions/partition-00001/chunks/    # merge-partition input only
  merge/partitions/partition-00001.json # transient partition audit report
  merge/merge_report.json               # transient final audit report
```

On partition merge, the verified partition and immutable receipt are published:
- Partition dataset: `.artifacts/manifests/metadata/submission_metadata/partitions/partition-00001/`
- Final unified dataset: `.artifacts/manifests/metadata/submission_metadata/final/submission_metadata.parquet` and `<artifact_id>.json`

Partition artifacts and the final dataset are always Parquet (ZSTD), regardless
of the checkpoint format used to produce them. JSONL checkpoints are accepted
as merge inputs and converted during validation/publication. When a single
partition artifact covers the whole plan, the final `merge` publishes it as a
byte copy of the verified artifact (same sha256) rather than re-encoding it.

To merge across machines, copy the published partition directory and its receipt
into the shared manifests workspace, then run final `merge`. Later phases may
consume a published partition directly without the source run or its chunks.

Integrity is carried by a hash chain instead of re-reading rows: each chunk is
spec-validated at write time, `merge-partition` performs the one deep row-level
validation (column-pruned DuckDB scans) and records the artifact's `sha256`,
row count, plan hash, fingerprint, and schema version in its report. The final
`merge` verifies each artifact against that report — content sha256, plan
binding, schema, and row count — using metadata and streamed hashing only, then
combines artifacts with a single deterministic scan. Missing reports trigger a
one-time deep re-validation and report regeneration. Missing, truncated,
tampered, stale-plan, foreign, or schema-drifted artifacts fail the merge.

The chunk/checkpoint directories are transient worker outputs. Only
`merge-partition` reads them, and it is the only operation that ever does: the
final `merge`, the viewer, the materializer, and every later phase read only
finalized partition artifacts or the final dataset. Chunks may be deleted once
their partition artifact is verified.

Duplicate accession values are expected SEC fan-out (the same filing listed by
multiple registrants) and are reported in `duplicate_accessions` with a warning;
they are not merge failures. Duplicate CIK rows, stale or foreign artifacts,
range gaps or overlaps, schema drift, mismatched fingerprints, and non-terminal
statuses still fail the merge.

## Configuration

`--configure` is the only writer of `.artifacts/metadata/config.json`. A missing
config is created as a validated template and the run stops before any network
work so the SEC contact identity (`--user-agent`, `AppName/1.0
contact@example.com`) can be added first. CLI flags are temporary overrides and
are never persisted.

SEC identity and cache settings are declared in the shared settings registry
(`defs/runtime/settings/sec.py`) and resolved through it: `sec.user_agent`
(environment name `SEC_USER_AGENT`, also persisted in the config's
`credentials` section) and `sec.cache_dir` (`SEC_CACHE_DIR`). Precedence is
direct environment → `.env` → persisted config → default. The legacy
`user_agent_env` config field was removed: configurations containing it fail
validation as an unknown field instead of silently resolving. Phase-specific
options (e.g. `metadata.max_failure_attempts`) are declared in this phase's
`settings.py` and registered through the `phases/settings.py` barrel.

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
  schema-versioned fragments. `merge-partition` is the only chunk reader: it
  validates identity, provenance, schema, fingerprint, row counts, CIK
  coverage, and terminal statuses through the shared DuckDB-backed dataset
  operations in `defs.storage` (column-pruned scans, no Python row
  materialization), then publishes its partition artifact atomically as
  Parquet. The final `merge` combines finalized partition artifacts only —
  it has no chunk fallback, requires a partitioned plan, and re-reads every
  artifact as Parquet regardless of the checkpoint format.
- Checkpoints support `parquet` (default) and `jsonl` (useful for inspection);
  both are accepted merge inputs. Merge outputs are always Parquet
  (ZSTD-compressed, deterministically ordered by CIK).

## Testing

```bash
.venv/bin/pytest phases/01_metadata_extraction/tests
```

Default tests use a fake SEC client and deterministic storage — no live SEC or
model calls. Fixtures live under `tests/fixtures/` (synthetic/secsanitized SEC
shapes, malformed payloads, era-specific filings).
