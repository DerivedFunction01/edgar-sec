# AGENTS.md — Repository Engineering Contract

Normative guidance for humans and coding agents working in this repository.
`roadmap/master_roadmap.md` is the long-term product direction; this file is
the engineering contract for how code must be built here.

## Mission And Current Boundaries

- The repository transforms SEC filing inputs into versioned, queryable
  research data (Parquet / JSONL / SQL) with provenance and resumable runs.
- The roadmap describes future phases and schemas. It is not permission to
  implement unplanned features or to assume future schemas already exist.
- Current ingestion boundary: the shared SEC HTTP client (`defs/sec_http.py`)
  plus phase-owned normalization, planning, checkpoint validation, and merge
  validation (`phases/01_metadata_extraction/core/`).
- `old-webpage.py` is historical reference material only (rate-limit and
  progress behavior). It is not a production dependency and its Item 1/1A
  keyword filtering must not leak into generic phases.

## Canonical Layout

```text
defs/                              # domain-neutral reusable infrastructure
  sec_http.py                      # SEC pacing, retries, caching, metrics
  storage/                         # logical datasets and immutable file chunks
  sql/                             # SQL AST/compiler/executor boundary
  llm/                             # future provider-neutral model boundary
  runtime/                         # shared paths and future lifecycle helpers
    interactive.py                 # shared partition-oriented operator UI
    partitions.py                  # partition selection and distribution
    progress.py                    # shared progress presentation adapter
    cli.py                         # shared CLI arguments/config bootstrap
    registry.py                    # static launcher entries for the root run.py
phases/<number>_<name>/
  core/                            # phase schemas, domain logic, validation
  extractors/                      # future regex/LLM phase adapters
  tests/                           # fixtures live in tests/fixtures/
  cli.py                           # canonical phase command surface
  smoke_test.py
roadmap/                           # product and extraction specifications
uploads/                           # input manifests
.artifacts/                        # generated config, plans, runs, checkpoints (ignored)
```

- A phase may add files for a real domain concern, but must not fork shared
  HTTP, storage, CLI lifecycle, progress, or worker-commit behavior.
- `run.py`-style interactive shims are transitional front-ends. The target
  command surface is `python -m phases.<phase>.cli {plan,preview,run,status,merge}`.
- Root `run.py` is a thin launcher over the static registry in
  `defs/runtime/registry.py` (`python run.py` menu, `python run.py <id>
  [args...]` direct dispatch, `--list` JSON). It owns no phase behavior and
  never subprocesses: entries name existing modules, which keep their own
  argparse, config handling, and exit codes. New phases register by adding one
  `LauncherEntry`.
- Shared interactive behavior belongs in `defs.runtime.interactive`; phase
  runners provide callbacks for preview, plan, status, partition execution,
  and phase-specific command rendering.
- Shared CLI argument registration, config bootstrap, override precedence,
  JSON output, and standard error handling belong in `defs.runtime.cli`.
- New shared behavior goes under `defs/` only after defining a reusable
  contract plus contract tests. Phase modules consume public contracts
  (`defs.storage.make_chunk_backend`, protocols), never backend-private helpers.
- Use `defs.runtime.paths.resolve_paths()` and its typed layout objects for
  artifact, config, cache, run, worker, test, and acceptance paths. Do not
  concatenate `.artifacts` paths or create directories at module import time.

## Configuration And Plans

- Reusable settings persist at `.artifacts/metadata/config.json` (phase
  default: `PROJECT_CONFIG_DEFAULT_PATH`), written atomically with versioning.
- `--configure` is the only writer; normal commands load the config and treat
  explicit CLI flags as temporary overrides that are never persisted.
- A missing config creates a validated template and stops before any network
  or model work, so credentials can be added first.
- `plan.json` is an immutable snapshot of effective run settings
  (`run_options`) plus fingerprint/hash. Plan-defining fields
  (`input_path`, `artifacts_dir`, `chunk_size`, `limit`, `storage_format`)
  are checked against effective options; stale plans are rejected with a
  regeneration message, never silently rewritten.

## Standard Phase Lifecycle

- `plan` is deterministic and performs no network or model calls.
- `preview` is bounded and explicitly non-production.
- `run` processes resumable work units (chunks) with shared progress, retry,
  and checkpoint behavior; completed chunks are skipped, never re-fetched.
- `status` reads manifests/checkpoints without re-fetching source data.
- `merge` validates phase invariants (ranges, row counts, duplicates,
  fingerprints, terminal statuses), then delegates physical assembly and
  atomic publication to shared storage.
- Partitions are the user-facing distribution unit; fixed-size chunks are the
  internal resumability unit. Partition assignment and manifests must be
  deterministic and shared across phases.

## Storage Rules

- Use shared storage protocols/factories (`defs/storage/`) for Parquet, JSONL,
  SQLite, and future backends. No phase-local serializers or filename schemes.
- Phase owns schema/semantic validation; storage owns physical reads/writes,
  manifest publication, atomicity, and read-back validation.
- Workers never write the canonical dataset concurrently. They emit immutable,
  schema-versioned fragments; a coordinator validates identity, provenance,
  schema, and duplicates before publishing.
- Standard temporary layout: `.artifacts/<phase>/runs/<run-id>/workers/<worker-id>/`
  with attempt IDs and a manifest. Partial files are never "complete".
- Use partition-scoped paths such as
  `.artifacts/<phase>/runs/<run-id>/partitions/partition-00001/chunks/` when a
  run is distributed. The same layout must work for one or many machines.
- Define idempotency keys and conflict policy before adding an append path.
  No last-writer-wins for conflicting extraction facts; quarantine or fail.
- Do not use pandas to define nested schemas or persistence behavior. PyArrow,
  DuckDB conversion, and backend details stay behind `defs/storage`.
- Phase code must not issue literal SQL or import backend-private persistence
  helpers; use compiled SQL objects and shared executors (`defs/sql/`).

## Regex And LLM Extraction Boundary

- Prefer deterministic regex where the signal is structurally reliable; use
  LLM extraction for semantic ambiguity, not to replace ingestion or schema
  validation.
- Provider-neutral contracts, request/response models, retries, rate limits,
  caching, usage/cost metrics, and provider adapters belong in `defs/llm/`.
- Prompts, extraction schemas, field mappings, source-span requirements,
  validators, and phase orchestration belong to the owning phase, preferably
  `extractors/regex/` and `extractors/llm/`.
- Every model-derived fact retains: source filing identity, location/provenance,
  provider, model, prompt/template version, extraction schema version, and
  validation outcome. Raw model text is not canonical data.
- Provider credentials live in environment/secret management, never in tracked
  configuration, plans, or worker artifacts.

## Parallel Worker Contract

- Workers read immutable inputs and emit independent fragments/deltas plus a
  manifest containing run, phase, worker, attempt, source identity, schema,
  code, and model/prompt metadata where applicable.
- The coordinator is the only component that commits to canonical storage.
- Coordinator commits are idempotent, deterministic, schema-checked, and
  atomic; retries create new attempts instead of mutating published fragments.
- Failed or ambiguous extractions are represented explicitly with
  status/error/provenance and never silently dropped.

## Engineering Rules And Validation

- Prefer the smallest compatible change; no compatibility layers without a
  concrete persisted or external contract.
- Never commit credentials, generated artifacts, caches, database files, or
  raw model responses. `.gitignore` already excludes `.artifacts/` patterns.
- Add contract tests when extending shared infrastructure; add phase tests for
  domain invariants. Default tests never touch live SEC or model services.
- Use the project virtual environment: `.venv/bin/python`, `.venv/bin/pytest`.
- Run suites separately — `defs/tests` and phase tests have `conftest.py`
  modules that collide when collected together:

  ```bash
  .venv/bin/pytest defs/tests
  .venv/bin/pytest phases/01_metadata_extraction/tests
  ```

- Preserve atomic publication, immutable checkpoints, schema versioning,
  provenance, and resumability in every phase.

## Environment And Paths

- `EDGAR_ARTIFACTS_ROOT` selects the shared generated-artifact workspace and
  defaults to `.artifacts`.
- `EDGAR_CONFIG_PATH` and `EDGAR_CACHE_ROOT` may override derived config and
  cache locations. Credentials and SEC contact identity come from the
  environment or the git-ignored root `.env` file (direct environment wins;
  `EDGAR_DOTENV_PATH` may relocate the file) resolved through
  `defs.runtime.env.get_env`; do not store provider API keys in config.
- Secrets and `.env` values are never written to plans, manifests, logs, or
  generated artifacts.
- Persist dataset identity and layout (input manifest, run ID, partition
  count, chunk size, and storage format) in project config and immutable plans.
  Keep worker count, rate, timeout, and cache overrides machine-local unless a
  phase explicitly makes them part of its reproducibility contract.
- Resolve paths through `defs.runtime.paths`; phase code supplies logical
  phase/run/worker/partition IDs and never invents directory names.

## Test Artifacts And Fixtures

- Default unit/contract tests are deterministic, offline, and credential-free.
  A test that exercises an LLM call uses a fake provider or a recorded,
  sanitized response — never a real model call.
- Committed fixtures live under the owning package's `tests/fixtures/`: minimal,
  synthetic or sanitized, versioned, one behavior each (malformed SEC payloads,
  era-specific filing shapes, regex edge cases, LLM structured responses,
  schema/provenance validation).
- Generated test/acceptance output goes under ignored `.artifacts/test-runs/`
  or `.artifacts/acceptance/`, never beside committed fixtures or canonical
  outputs. Every generated run recreates its own plan/manifest/storage.
- Test tiers:
  - unit/contract: fake SEC client, fake LLM provider, deterministic storage;
  - fixture replay: recorded responses, no network or provider calls;
  - live acceptance: explicit opt-in, credential-gated, rate-limited,
    cost-bounded, excluded from default test commands.
- Structural acceptance runs use a fixed sample manifest (e.g. 100 CIKs) stored
  as a tracked fixture `phases/<phase>/tests/fixtures/samples/<name>.json`
  recording the sample CIK list and source-manifest fingerprint. Do not rely
  on `limit`, which only takes a prefix of the input CSV.
- A sample acceptance run must use the same production plan/run/storage path
  as the full dataset, with only the sample manifest limiting work. Validate
  schema read-back, required fields, nested cardinality, statuses, provenance,
  duplicate/conflict behavior, and artifact completeness before authorizing a
  full run.
- Sample acceptance artifacts record code/schema/config versions, input and
  sample fingerprints, storage format, provider/model/prompt versions when
  applicable, request counts, retry/error counts, and validation results. The
  resulting raw data and generated Parquet/JSONL/SQL files are not committed.
- Live LLM acceptance is a separate command or marker (e.g. `-m live_llm`)
  with explicit model/provider selection and a hard budget/request limit.
  It produces evidence artifacts for review and is not a required CI gate
  unless credentials and budget are deliberately provided.
- Prefer a fake-provider contract asserting request schema, structured-output
  handling, retries, timeout behavior, usage accounting, and provenance
  propagation; reserve real-provider checks for adapter smoke tests.
