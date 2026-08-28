# edgar-sec

Transforms SEC filing inputs into versioned, queryable research data
(Parquet / JSONL / SQL) with provenance and resumable runs.

Engineering contract and long-term direction live in [`AGENTS.md`](AGENTS.md)
and [`roadmap/master_roadmap.md`](roadmap/master_roadmap.md).

## Repository layout

```text
defs/              # domain-neutral infrastructure (SEC HTTP, storage, runtime, sql, llm, viewer)
phases/            # phase-owned schemas, normalization, planning, validation, merge
 01_metadata_extraction/   # Pipeline A, Part 1 — submissions metadata
 02_filing_extraction/     # Pipeline A, Part 2 — filing catalog and targets (no network)
 #   (future) Phase 2.5 — filing document acquisition from Phase 02 target plans
roadmap/           # product and extraction specifications
uploads/           # input manifests
.artifacts/        # generated config, plans, runs, checkpoints (git-ignored)
```

## Quick start

```bash
# Run the repository launcher and pick an entry, or dispatch directly:
python run.py                 # interactive menu
python run.py metadata        # Phase 01 interactive wizard
python run.py filing-catalog  # Phase 02 interactive materialize/plan menu
python run.py viewer          # local read-only dataset viewer

# Or use a component's canonical command surface directly:
.venv/bin/python -m phases.01_metadata_extraction.cli plan \
    --config .artifacts/metadata/config.json
.venv/bin/python -m defs.viewer --artifacts-root .artifacts
# Portable finalized-artifact transport:
.venv/bin/python -m defs.runtime.bundle create --artifact-id <id> \
    --output artifacts.bundle.zip
# Or choose Artifact Bundle from `python run.py` for the interactive workflow.
```

## Phases

### [Phase 01 — Submissions Metadata Extraction](phases/01_metadata_extraction/README.md)

Fetches the SEC `data.sec.gov/submissions` feed per CIK, follows historical
submissions files, and produces one `submission_metadata` row per CIK (recent +
 historical filings combined into a nested `filings` list) with strict
 normalization, provenance, and resumable chunk/partition execution.

### [Phase 02 — Filing Catalog](phases/02_filing_extraction/README.md)

Materializes form-partitioned filing occurrences from the finalized Phase 01
artifact without network access or Phase 01 chunk reads, then plans deterministic
target selections for later archive resolution. Phase 02 is no-network metadata
preparation only; it does not fetch filing documents.

The interactive launcher (`python run.py filing-catalog`) and the canonical CLI
(`python -m phases.02_filing_extraction.cli {materialize,plan,status}`) share one
contract. Filing document acquisition is a separate Phase 2.5 boundary that
consumes these target plans; see the Phase 02 README for the scope split.

## Tools

### [Shared Infrastructure (`defs/`)](defs/README.md)

Domain-neutral contracts: SEC HTTP client (pacing/retries/caching), canonical
filing identity (accessions, archive URLs, occurrence IDs, document locator
keys), storage backends, SQL boundary, and the shared phase runtime.

### [Dataset Viewer](defs/viewer/README.md)

A local, read-only FastAPI + DuckDB web viewer over the `.artifacts` workspace.
Discovers Parquet/JSONL datasets and JSON documents (plans, manifests, merge
reports), serves schema/stats/paged rows with filter+sort+search, and a guarded
read-only SQL console — with a built TypeScript UI.

## Conventions

- Every change is gated by the root validation runner: `python check.py` runs
  the ruff format check, the ruff lint (configuration in `ruff.toml`), then
  each test suite in isolation; `--fix` applies formatting and safe lint fixes
  first.
- Shared HTTP, storage, CLI lifecycle, progress, and worker-commit behavior live
  under `defs/`; phases consume those public contracts and own their schemas and
  domain logic.
- Plans and configs are immutable snapshots validated against effective options;
  completed chunks are skipped and never re-fetched.
- Credentials (SEC User-Agent) come from the environment or the git-ignored
  `.env`; they are never written to plans, manifests, or artifacts.
- Finalized cross-phase artifacts are discovered through immutable manifests in
  `.artifacts/artifact-manifests/`; bundle transport rebases relative paths and
  never stores absolute filesystem paths.
