# `defs/` — Shared Infrastructure

Domain-neutral, phase-independent contracts. Phases consume the public
surfaces exported here and never reimplement or bypass them.

```text
defs/
  sec_http.py           # SEC HTTP client: pacing, retries, caching, metrics, headers
  filing_identity.py    # canonical filing identity: accessions, archive URLs,
                        # occurrence IDs, document locator keys, date-derived years
  table_definitions.py  # shared table-conversion helpers for later content phases
  storage/              # logical datasets, chunk backends, manifests, atomic publication
  sql/                  # SQL AST/compiler/executor boundary
  runtime/              # paths, settings registry, env resolution, artifacts/bundles,
                        # partitions, progress, CLI
  viewer/               # read-only local dataset/artifact viewer (see viewer/README.md)
  tests/                # contract tests for the shared contracts (run: pytest defs/tests)
```

## Settings registry and environment resolution

All application settings are declared once as typed specs under
`defs/runtime/settings/` (`runtime.py`, `paths.py`, `sec.py`);
phases add their own `settings.py` module registered in the
`phases/settings.py` barrel. Setting identity is a logical dotted path
(`runtime.threads`, `sec.user_agent`, `filing_extraction.source_batch_size`);
environment names are generated from it (`RUNTIME_THREADS`,
`FILING_EXTRACTION_SOURCE_BATCH_SIZE`) — modules never hardcode env names.

- `defs/runtime/env.py` is the only direct-environment boundary: dotenv
  parsing, direct-process-environment precedence, and `DOTENV_PATH`
  selection. It contains no application-specific names.
- Resolution precedence per spec: explicit CLI override → direct
  environment/dotenv (when `env=True`) → persisted config (when
  `config=True`) → default/factory. Empty environment values count as unset;
  explicit `0`/`false` are preserved. An explicit `env` mapping bypasses
  process/dotenv resolution entirely (deterministic tests, path resolution).
- Machine-derived defaults (engine threads, memory budget, spill directory)
  are factories over `psutil`/`os` probes and are never persisted
  automatically. Secret settings (SEC contact identity) resolve normally but
  are excluded from flattened reports and generated dotenv output.
- `python run.py settings generate-dotenv [--path .env] [--force] [--phase ID]`
  atomically renders a documented `.env` template from the same specs used at
  runtime: static defaults as values, machine-derived defaults as commented
  suggestions, secrets omitted.
- The validation gate runs registered policy scanners (see
  `defs/runtime/checks.py`) between linting and tests:
  - `environment-access`: flags direct `os.environ`/`os.getenv` outside `defs.runtime.env`
  - `artifact-paths`: flags hardcoded `".artifacts/"` path literals outside `defs.runtime.paths`
  - `sql-boundary`: flags raw SQL string literals and execution in phase code outside `defs.sql`
  - `storage-boundary`: flags direct `pyarrow`, database driver (`duckdb`/`sqlite3`), or `pandas` imports outside `defs/storage`
  - `secrets-leakage`: flags committed API keys, tokens, and credentials in source code
  - `clean-exit`: flags `sys.exit()` calls in library and core phase code outside CLI runners
  - `legacy-shims`: flags dead legacy behavior, backward-compatibility aliases, and transitional shims
  - `file-length`: advises when modified Python source files exceed 500 lines to encourage modular decomposition
  Register future policy scanners in their respective semantic boundaries or `defs/runtime/scanners/` — `check.py` stays generic.

## Rules

- New shared behavior lands here only with a reusable contract plus contract
  tests in `defs/tests/`; phase code consumes public contracts, never
  backend-private helpers.
- Finalized cross-phase artifacts publish immutable manifests under
  `.artifacts/artifact-manifests/`. Manifest paths are relative to the artifact
  root and content IDs exclude filesystem paths, so artifacts can move between
  persistent and ephemeral workspaces. The bundle command transports finalized
  artifacts without including chunks, checkpoints, caches, or absolute paths.
- `filing_identity` is the single owner of accession normalization (one
  canonical 18-digit value; the hyphenated form is derived on display),
  archive URL parsing/construction, occurrence identity
  `(source_cik, accession, document_path)`, and the pre-fetch document locator
  key `(accession, document_path)`. Phases must not rebuild these keys locally.
- `sec_http.default_headers` intentionally sets no `Host` header: the client
  serves both `data.sec.gov` and `www.sec.gov`, and the HTTP library derives
  Host from each URL.

## Tests

```bash
.venv/bin/pytest defs/tests
```

Run separately from phase suites; the `conftest.py` modules collide when
collected together.
