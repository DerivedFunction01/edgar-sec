# AGENTS.md — Repository Engineering Contract (v2)

Normative engineering contract for humans and coding agents working in this repository.
`roadmap/` describes the long-term product direction; this file is the binding contract
for how code must be structured, bounded, and verified.

---

## Architectural Layers & Boundaries

The codebase follows a strict **acyclic downward-only layered architecture**:

```text
Layer 6: tools/           edgar_sec.tools
                           ├── CLI reflection, path introspection, sentinel synchronization
                            │
Layer 5: apps/            edgar_sec.apps.viewer
                           ├── read-only consumers of published artifacts
                            │
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
- **Tools (Layer 6)** may import from: `apps`, `pipelines`, `engine`, `infra`, `domain`, `foundation`. Never imported by lower layers.
- **Apps (Layer 5)** may import from: `pipelines`, `engine`, `infra`, `domain`, `foundation`. Never `tools`.
- **Pipelines (Layer 4)** may import from: `engine`, `infra`, `domain`, `foundation`. Never `apps` or `tools`.
- Cross-pipeline path/schema contract imports are limited to matching `paths.py` or `schemas.py` modules. These direct imports must be unaliased and acyclic; re-exports are confined to those owner modules.
- **Engine (Layer 3)** may import from: `infra`, `domain`, `foundation`. Never `pipelines`, `apps`, or `tools`.
- **Infra (Layer 2)** may import from: `domain`, `foundation`. Never `engine`, `pipelines`, `apps`, or `tools`.
- **Domain (Layer 1)** may import from: `foundation`. Never `infra`, `engine`, `pipelines`, `apps`, or `tools`.
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

## Memory & Performance Non-Regression Guarantees

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
   - `file_sha256()` streams a file in 64KB blocks. `sha256_text()` also streams:
     `foundation/hashing.py` encodes the text in 1 MiB code-point slices and
     updates one hasher, so hashing a multi-megabyte filing never allocates a
     second full-size bytes copy. Its digest is byte-identical to
     `hashlib.sha256(text.encode("utf-8"))` — Python `str` indices are code points
     and UTF-8 encodes each independently, so bounded slices concatenate to the
     whole string's bytes. `tests/foundation/test_hashing.py` pins the equality.
     Prefer this over `read_bytes()` into a digest anywhere; the `whole-file-read`
     scanner enforces that for the obvious cases.
   - Parquet writers use the shared `parquet.row_group_size` setting and the storage layer's `DEFAULT_COMPRESSION`; Parquet readers use `parquet.read_batch_size`, and SQL readers use `runtime.read_batch_size`. Do not define pipeline-local copies of these defaults.

---

## Settings & Configuration Management

1. **Modular Settings Registry**:
   - Settings are defined in modular providers under `edgar_sec/foundation/runtime/settings/`, including `sec.py`, `paths.py`, `runtime.py`, `parquet.py`, and `sql.py`.
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

## Verification & Quality Gate

Before submitting any turn or completing work, run the unified quality gate:

```bash
.venv/bin/python check.py            # smart gate: ruff format, lint, scanners, targeted pytest
.venv/bin/python check.py --all      # full gate: runs full unconditional test suite across repository. Do not run unless explicitly told to do so.
.venv/bin/python check.py --fix      # format & safe lint fixes only; does NOT run tests
.venv/bin/python check.py --fast     # fast static check: format check, lint check, scanners (skips tests)
.venv/bin/python check.py --scan     # runs only the registered policy scanners
.venv/bin/python check.py --test     # runs targeted pytest (or full suite with --all)
.venv/bin/python check.py --explain  # prints detected git changes and reverse AST test lineage
.venv/bin/python check.py <path>     # passes explicit test paths directly to pytest
```

> [!NOTE]
> `check.py` automatically uses Git change detection and static AST reverse-dependency lineage tracking:
> - **Documentation / Assets**: If only markdown, documentation, or static non-code assets changed, pytest execution is bypassed completely. Do not run `check.py` when only comments, doc-strings, or markdown files are edited (run `--fast`).
> - **Prose-Only Edits**: A `.py` file is compared to its `HEAD` baseline through docstring-stripped AST dumps. A change that leaves those dumps identical — a comment, docstring, or blank-line edit — selects no tests. `ruff format` and `ruff lint` still cover the file, so only pytest selection is skipped. An untracked file, a missing baseline, or unparsable text counts as a logic change.
> - **Targeted Execution**: Modifying a module resolves and runs its direct mirrored test and downstream dependents, respecting pipeline boundaries.
> - **Full Gate Verification**: Use `check.py --all` only when requested by the user to do so. Never run `pytest` with the `test/` directory; it is equivalent to `--all`. 


### Registered Policy Scanners
Scanners are defined modularly in `edgar_sec/foundation/scanners/` and collected via `ALL_SCANNERS`:
- `environment-access`: Bans direct `os.environ` / `os.getenv` outside `edgar_sec.foundation.runtime.env`.
- `artifact-paths`: Bans hardcoded `".artifacts"` path literals outside path resolvers.
- `secrets-leakage`: Bans committed API keys, tokens, or credentials.
- `clean-exit`: Bans `sys.exit()` in library modules (only allowed in `run.py`, `check.py`, and CLI entrypoints).
- `file-length`: **Fails the gate** on files exceeding the line limit (800) to prevent monolithic growth. Any finding from any scanner returns a nonzero exit code, so "advisory" is not how it behaves.
- `layer-boundary`: Enforces strict downward-only import hierarchy.
- `resource-allocation`: Bans hardcoded thread counts or memory limits in pipeline/engine code.
- `batch-defaults`: Enforces ownership of shared chunk, read, SQL-insert, Parquet, document payload, and I/O buffer defaults; it flags duplicate symbol definitions and governed literals at identified call sites while allowing equal numbers used for distinct policies.
- `whole-file-read`: Bans `read_bytes()` consumed by a digest constructor. Hashing a whole
  artifact to prove it intact materializes the file; use `file_sha256`. Narrow on purpose —
  a `read_bytes()` feeding `json.loads` on a small payload is a different trade and is not flagged.
- `prose-length`: **Fails the gate** on a docstring or comment block over its cap. Enforces the
  "Code Comments and Docstrings" caps below, with tighter caps for tests.
- `regex-alternations`: Bans hand-crafted 3+ branch alternation literals, so `foundation.regex.builder` is used.
- `legacy-shims`: Bans backward-compatibility aliases and transitional shims (enforces §1.1).
- `json-io`: Bans redundant JSON helper definitions and non-atomic JSON writes.
- `date-patterns`: Bans private month tables and hand-crafted date patterns.
- `sql-interpolation`: Bans SQL assembled from unescaped values at a query sink. It
  inspects the argument of `execute` / `executemany` / `executescript` and reports an
  f-string, `%`, or `+` that interpolates a value which did not reach the statement
  through `infra.storage.duckdb.sql_literal` / `sql_path_list` / `sql_identifier`, a
  constant, or a local derived from those. A bound parameter is never a finding, and a
  module that composes SQL at a sink must be declared in `_SQL_COMPILER_PATHS` — an
  audited list, each entry recording why its interpolated values are safe.

> [!NOTE]
> `regex-alternations`, `legacy-shims`, `json-io`, and `date-patterns` exist to
> keep a rule *enforced* rather than merely *stated*.
> Each points at infrastructure the repository already ships — the regex builder
> DSL, the "zero shims" rule in §1.1, `foundation.serialization.canonical_json`,
> `infra.storage.atomic.atomic_write_json`, and `foundation.text.dates`. A rule
> with no scanner erodes, because the cost of ignoring it is invisible until the
> damage is. Each exempts only the module that owns the vocabulary, plus tests
> and the scanners themselves.

Adding a scanner means: a module in `edgar_sec/foundation/scanners/`, an entry in
`ALL_SCANNERS`, a mirrored `tests/foundation/scanners/test_<name>.py` (§6), and a
line in the list above. Because that list already specifies the rule, the scanner's
module docstring states only what it flags, what it deliberately allows, and its
exemption mechanism — never a restatement of the rule (see **Code Comments and
Docstrings**).

### Documentation Contract

Every package in the repository owns a concise `README.md` (`edgar_sec/<layer>/<pkg>/README.md`, layer roots, and `edgar_sec/` root) that preserves architectural boundaries without mechanical redundancy:

1. **The "If it can be autogenerated, drop it" rule**:
   - **Banned**: `Module layout` tables, `Public surface` symbol inventories, `Mirrored tests` pointers, and `Component Documentation` link farms. Code signatures, leaf imports (§1.2), docstrings, and directory structure own these.

2. **Standardized Section Formats**:
   - `# <package_name>`: Package title and layer location.
   - `## Purpose`: 1–2 paragraphs explaining the problem domain and architectural intent.
   - `## Contracts`: Strict unordered list of bolded invariants (`- **<Rule>**: <Constraint>`). Documents non-obvious refusals, ordering, determinism, memory bounds, and CAS guarantees. Prohibited as a table.
   - `## Deliberate gaps`: Strict unordered list of bolded omissions (`- **<Omission>**: <Impact and deferred alternative>`). Prohibited as a table.
   - `## Command surface` (Pipelines & Apps only): Autogenerated table bounded by `<!-- AUTOGEN:COMMANDS:START -->` and `<!-- AUTOGEN:COMMANDS:END -->`, followed immediately by `### Usage examples` (a single `bash` block with curated CLI invocations).
   - `## Artifact layout` (Artifact-persisting pipelines only): Autogenerated table bounded by `<!-- AUTOGEN:PATHS:START -->` and `<!-- AUTOGEN:PATHS:END -->`.

3. **Core Documentation Invariants**:
   - **Root `README.md` scope**: Onboarding and architecture gateway only. Pipeline execution belongs in pipeline READMEs; root maintains no multi-page CLI walkthrough or ASCII artifact tree.
   - **No volatile tuning**: Leave algorithm thresholds, window sizes, and counts with owning code; cite numbers in READMEs only when part of a persisted schema or wire contract.
   - **Tracked evidence only**: Cite only paths that exist in the repository; never reference untracked local scratch trees.
   - **Verified behavior, not intent**: Documented capabilities that fail or do not exist are defects; record planned work in `Deliberate gaps` rather than describing it as working.
   - **`AGENTS.md` is normative**: Where a README and this file disagree, this file wins.

Adding a package means: a `README.md` in it and an entry in the parent layer's README layout table.

### Code Comments and Docstrings

These rules are normative for code, not just Markdown. They exist because a
long-prose comment habit, once established, is reintroduced by every later change
that "documents while implementing". Apply them when you write code, not only
when reviewing it.

**Default to none.** A `#` or `"""` earns its place only by stating something the
code cannot state. The code already explains execution; a comment that describes
what the next lines do is deleted on sight.

**Hard caps.** A module docstring is at most four lines. A function or class
docstring is at most three. A standalone comment block is at most three lines. A
test module docstring is at most three lines, a test function at most two, a test
comment block at most two. A trailing comment (code precedes it on the line) is
counted alone: it labels its own line, so adjacency is irrelevant. Exceeding a cap
requires a precondition the type system cannot express, and is justified in review;
it is not a default to fall back on. The `prose-length` scanner enforces these.

**Document intent, not execution.** Keep the conclusion and drop the derivation.
"Rows must be sorted before merging, or the fingerprint is unstable" is worth
writing. "First we sort, then we hash each row, then we compare with the previous
fingerprint, and if any differ we reject the run" is not.

**Six things justify prose.** A non-obvious invariant the code does not enforce;
a refusal or rejection semantic and why it refuses; an ordering, determinism, or
atomicity constraint; a caller obligation ("do not bypass X", "Y must be sorted
first"); a safety or integrity rule (injection, path traversal, data loss, memory
bound); a precondition the type system cannot express.

**Do not duplicate.** If a type, function, or module already documents a rule,
reference it by name in a few words or say nothing. Do not restate a rule that
`AGENTS.md` already owns.

**Never add:** step-by-step narration; benchmarks, measured figures, or corpus
statistics; project vocabulary (phase numbers, stage names, milestones, roadmap
references); design essays on why a file was split or a symbol placed where it is;
what an earlier implementation did; comments that restate the following line.

**When you change code, do not grow the prose.** Editing a function does not
license expanding its docstring. New behaviour needs a sentence only when it
introduces an invariant, a refusal, or an obligation that did not exist before.
Net comment and docstring volume should not grow with a feature.

---

## Testing & Fixtures

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
