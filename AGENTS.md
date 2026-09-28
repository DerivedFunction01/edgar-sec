# AGENTS.md — Repository Engineering Contract (v2)

Normative engineering contract for humans and coding agents working in this repository.
`roadmap/` describes the long-term product direction; this file is the binding contract
for how code must be structured, bounded, and verified.

---

## 1. Architectural Layers & Boundaries

The codebase follows a strict **acyclic downward-only layered architecture**:

```text
Layer 4: pipelines/       edgar_sec.pipelines.metadata_sync
                           ├── CLI, Operator, Planner, Worker, Merger, Augmentation
                            │
Layer 3: engine/          edgar_sec.engine.submissions
                           ├── Unroller, Profile, Normalizer, Arrow Builder
                            │
Layer 2: infra/           edgar_sec.infra
                           ├── sec_http (Client, RateLimiter, FailureLedger)
                           └── storage (Atomic IO, DuckDB engine, Parquet IO)
                            │
Layer 1: domain/          edgar_sec.domain
                           ├── Cik, AccessionNumber (identity primitives)
                           └── Submission schemas and data models
                            │
Layer 0: foundation/      edgar_sec.foundation
                           ├── Hashing & Serialization (file_sha256, canonical_json)
                           ├── Scanners (modular policy scanner registry)
                           └── Runtime (env, paths, resources, memory, settings/)


```

### Layer Dependency Rules (Enforced by AST Scanner)
- **Pipelines (Layer 4)** may import from: `engine`, `infra`, `domain`, `foundation`.
- **Engine (Layer 3)** may import from: `infra`, `domain`, `foundation`. Never `pipelines`.
- **Infra (Layer 2)** may import from: `domain`, `foundation`. Never `engine` or `pipelines`.
- **Domain (Layer 1)** may import from: `foundation`. Never `infra`, `engine`, or `pipelines`.
- **Foundation (Layer 0)** has **zero** internal dependencies on upper layers.
- The `layer-boundary` scanner automatically validates this graph in `check.py`.

### Package Import & Export Contract (No Shims, No Barrel Re-exports)
1. **Zero Backward-Compatibility Shims**:
   - Never create alias modules, forwarding functions, or legacy shims when refactoring or moving code.
   - When a component is relocated or renamed, update all call sites immediately.
2. **No Barrel Re-exports in `__init__.py`**:
   - `__init__.py` files must not re-export symbols from child submodules.
   - Consumers must import directly from the leaf module (e.g. `from edgar_sec.domain.identity import Cik`, `from edgar_sec.infra.storage.duckdb import connect`).
   - This prevents eager initialization of heavy dependencies (DuckDB, PyArrow), eliminates circular import cycles, and makes symbol ownership explicit.
   - Allowed in `__init__.py`: package docstrings, `__version__`, or true dynamic registries (e.g. `ALL_SCANNERS`).


---

## 2. Memory & Performance Non-Regression Guarantees

To prevent OOM kills, glibc fragmentation, and thread thrashing in containerized or shared environments:

1. **Cgroup-Aware Resource Budgeting**:
   - Never size workers from raw CPU count or DuckDB's 80% physical memory default.
   - Use `edgar_sec.foundation.runtime.resources.derive_resources()` which checks cgroups v2 (`memory.max` - `memory.current`), cgroups v1, `/proc/meminfo` `MemAvailable`, and psutil.
   - Workers are budgeted via `auto_worker_count(available_bytes, worker_memory_mib=512, safety_fraction=0.9)`.
2. **glibc Arena Heap Reclamation**:
   - Call `edgar_sec.foundation.runtime.memory.reclaim()` (`gc.collect()` + `malloc_trim(0)`) at bounded batch intervals to return freed pages to the OS.
3. **DuckDB Engine Hardening**:
   - Every DuckDB connection MUST set:
     - `threads = resources.threads`
     - `memory_limit = resources.memory_limit`
     - `temp_directory = resources.temp_directory`
     - `preserve_insertion_order = false`
4. **Hardcoded Limits Prohibited**:
   - Hardcoding `threads=`, `max_workers=`, or `memory_limit=` in library/pipeline code is blocked by the `resource-allocation` policy scanner.
5. **Streaming & Bounded IO**:
   - `sha256_text()` streams memory views in 1MB chunks to eliminate memory spikes on large SEC files.
   - Parquet files use `row_group_size = 128_000` and `compression = "zstd"`.

---

## 3. Settings & Configuration Management

1. **Modular Settings Registry**:
   - Settings are defined in `edgar_sec/foundation/runtime/settings/` (`sec.py`, `paths.py`, `runtime.py`).
   - Do NOT create monolithic configuration classes that accumulate parameters across phases.
   - New phases register their own domain/phase spec dictionaries.
2. **Deterministic Environment Resolution**:
   - Logical dotted paths map deterministically to env vars via `environment_name(path)` (e.g. `sec.rate_limit_rps` -> `SEC_RATE_LIMIT_RPS`).
   - Direct `os.environ` or `os.getenv` access outside `edgar_sec.foundation.runtime.env` is prohibited and caught by `environment-access` scanner.
3. **Secret Isolation**:
   - Settings marked `secret=True` are stripped by `flatten_settings()` before persisting manifests, provenance, or logs.
4. **Precedence Hierarchy**:
   `CLI overrides > Environment / .env > Stored Config > Defaults / Machine Factories`.

---

## 4. Phase 1 Pipeline & Resumability Contract

1. **Deterministic Planning**:
   - `plan` divides work into fixed-size chunks (default 1000 CIKs, or 100 for mini tests) and operational partitions without network access.
   - `plan.json` records input fingerprint, chunk boundaries, and schema version.
2. **Resumable Workers**:
   - Workers execute individual chunks, outputting validated atomic Parquet checkpoints (`.artifacts/transient/...`).
   - Completed chunks are verified and skipped on subsequent runs.
3. **Coordinator Merge**:
   - The coordinator validates all chunk checkpoints (schema conformance, row count, uniqueness of CIKs, null checks, fan-out accession records).
   - Assembles final sorted Parquet artifact via DuckDB out-of-core COPY (`ORDER BY cik`).

---

## 5. Verification & Quality Gate

Before submitting any turn or completing work, run the unified quality gate:

```bash
.venv/bin/python check.py          # full gate: ruff format check, ruff lint check, policy scanners, pytest
.venv/bin/python check.py --fix    # format & safe lint fixes only (< 0.5s; does NOT run tests)
.venv/bin/python check.py --fast   # fast static check: format check, lint check, scanners (skips tests)
.venv/bin/python check.py --scan   # runs only the registered policy scanners
.venv/bin/python check.py --test   # runs only the pytest suite
```

> [!NOTE]
> Do NOT run `check.py --fix` and then immediately `check.py` unless you actually need to auto-format.
> Use `check.py --fast` during iteration for instant (~1s) AST/layer/cgroup feedback, and run `check.py` when concluding a turn.


### Registered Policy Scanners
Scanners are defined modularly in `edgar_sec/foundation/scanners/` and collected via `ALL_SCANNERS`:
- `environment-access`: Bans direct `os.environ` / `os.getenv` outside `edgar_sec.foundation.runtime.env`.
- `artifact-paths`: Bans hardcoded `".artifacts"` path literals outside path resolvers.
- `secrets-leakage`: Bans committed API keys, tokens, or credentials.
- `clean-exit`: Bans `sys.exit()` in library modules (only allowed in `run.py`, `check.py`, and CLI entrypoints).
- `file-length`: Advises on files exceeding a set line limit to prevent monolithic growth.
- `layer-boundary`: Enforces strict downward-only import hierarchy.
- `resource-allocation`: Bans hardcoded thread counts or memory limits in pipeline/engine code.


---

## 6. Testing & Fixtures

- Default unit tests must be offline, deterministic, and fast (< 1s total).
- Committed fixtures live under `tests/fixtures/`: sanitized, minimal golden reference JSON and CSVs.
- Generated test outputs must use pytest's `tmp_path` fixture or transient paths, never dirtying the repository tree.

### Test Tree Mirrors the Source Tree

`tests/` mirrors `edgar_sec/` package-for-package, so a test file sits at the same relative path as the module it covers:

```text
edgar_sec/pipelines/metadata_sync/worker.py  ->  tests/pipelines/metadata_sync/test_worker.py
edgar_sec/infra/sec_http/cache.py             ->  tests/infra/sec_http/test_cache.py
edgar_sec/foundation/runtime/settings/        ->  tests/foundation/runtime/test_settings.py
```

This is a hard requirement, not a preference: as modules and pipelines accumulate, a flat test list makes it impossible to tell which tests a given pipeline requires.

1. **Every test directory is a package.** Each owns `__init__.py`, so pytest module names stay unambiguous and cannot collide across the tree.
2. **Add tests at the mirrored path.** Adding `foo/bar.py` means adding `tests/foo/test_bar.py`, not appending to an existing flat module.
3. **Do not merge unrelated modules into one test file.** One test file per source module. Shared setup lives in `conftest.py` at the narrowest directory that needs it.
4. **Fixture access goes through `tests.support`.** Never compute fixture paths with `parents[N]` depth arithmetic; it silently breaks when the tree is reorganized. Use `tests.support.load_fixture` / `fixture_path`.
5. **Offline test doubles live in `tests.support`.** Network fakes are injected at the transport seam (`SecHttpClient(session_factory=...)`), never by reaching into module internals.

> [!IMPORTANT]
> Committed fixtures and `ruff.toml` are un-ignored at the end of `.gitignore`. The blanket `.*` / `*.csv` / `*.parquet` rules would otherwise swallow them, and a fresh clone missing `tests/fixtures/` fails the gate.

### Lint Configuration

Lint suppression belongs in `ruff.toml`, not scattered `# noqa` comments. When a rule is noisy for a deliberate pattern, add a per-file ignore with a rationale comment rather than bypassing the gate.
