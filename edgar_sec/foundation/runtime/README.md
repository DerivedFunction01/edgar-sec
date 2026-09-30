# `edgar_sec/foundation/runtime` — environment, path layout, resource budgeting, and process-facing wiring

`runtime/` is Layer 0's answer to "what machine am I on, where do I write, and
how much work may I start?". It resolves environment variables, derives the
project directory layout, computes memory- and CPU-aware concurrency budgets
from cgroup limits, reclaims glibc heap pages, partitions work across workers,
and adapts progress and terminal interaction for pipeline entry points. It is
not a process supervisor: it starts no workers, opens no sockets, and owns no
lifecycle.

## Purpose

Four concerns, all of them about the *host* rather than about data:

1. **Configuration sources.** `env.py` and `settings/` decide what a
   configurable value is. `env.py` is the only module in the repository
   permitted to touch `os.environ`.
2. **Where things live.** `paths.py` is the single place the `.artifacts`
   literal and the artifact-layout vocabulary are written down.
3. **How much may run at once.** `resources.py` derives threads, workers, and a
   memory limit from cgroup and `/proc` facts rather than from raw CPU count or
   a hardcoded number.
4. **How a run presents itself.** `progress.py`, `interactive.py`, and
   `partitions.py` hold the presentation and work-splitting wiring that every
   pipeline would otherwise re-implement.

What this package is not: it does not run a pipeline, does not create workers,
and does not know what a CIK or an accession number is.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `env.py` | `.env` parsing and typed environment reads; the sole `os.environ` owner (108 loc). |
| `interactive.py` | Terminal prompts, choice menus, and the operator entrypoint policy (111 loc). |
| `memory.py` | glibc heap reclamation and chunked text hashing (67 loc). |
| `partitions.py` | Partition-spec parsing and balanced work distribution (49 loc). |
| `paths.py` | Project directory layout, artifact vocabulary, and root validation (221 loc). |
| `progress.py` | tqdm adapters and the optional-callback contract (100 loc). |
| `resources.py` | cgroup-aware resource derivation and `RuntimeResourceProfile` (279 loc). |
| `settings/` | The typed settings registry. See `settings/README.md`. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`env.py` is imported by `paths.py` and by `settings/__init__.py`.
`resources.py` and `settings/` import each other through function-local imports
to keep the cycle open only at call time.

## Contracts

**Guarantees this package makes to its callers**

- `get_env(name, default="", dotenv_path=None)` resolves the process environment
  first, then a `.env` file, then the default. The `.env` location is, in order,
  the explicit `dotenv_path` argument, the `DOTENV_PATH` environment variable,
  then `.env` in the working directory (`env.py:49-60`).
- `load_dotenv()` returns a plain `dict` and does **not** mutate `os.environ`
  (`env.py:17`). It skips blank lines and `#` comments, strips a leading
  `export `, and unwraps matching single or double quotes. A missing or
  unreadable file yields `{}` rather than raising (`env.py:21-22`).
- `get_env_int`, `get_env_float`, and `get_env_bool` fall back to the supplied
  default on an unparseable value rather than raising.
  `get_env_bool` treats `{"1", "true", "yes", "on"}` as true, case-insensitively,
  and *any other non-empty value* as false.
- `available_memory_bytes()` never prefers `MemTotal` over a real limit. It
  tries cgroup v2 (`memory.max` minus `memory.current`, returning `None` when
  `memory.max` is the literal `max`), then cgroup v1, then psutil, then
  `/proc/meminfo` `MemAvailable`, and only then `_physical_memory_bytes()`.
- `auto_worker_count(available, worker_memory_mib=512, safety_fraction=0.9)`
  returns `max(1, min(cores, mem_workers))`, so both the memory budget and the
  CPU count are upper bounds and the answer is never zero
  (`resources.py:158-176`).
- `usable_memory_bytes()` and `auto_worker_count()` reject a
  `safety_fraction` outside `(0, 1]` with `ValueError`; `default_memory_limit()`
  rejects a `fraction` outside `(0, 1]`.
- `derive_resources()` returns a frozen, slotted `RuntimeResourceProfile` and
  creates its `temp_directory` as a side effect, with
  `mkdir(parents=True, exist_ok=True)` (`resources.py:247-248`).
- `resolve_paths()` with no `repo_root` treats the working directory as the
  project root, and raises `ProjectRootError` when that directory is the
  `edgar_sec` package directory or anywhere beneath it
  (`paths.py:141-162`). Passing an explicit `repo_root` bypasses that check,
  because a caller that names the root has already answered the question.
- The artifacts root is the registered setting `artifacts.root` (env
  `ARTIFACTS_ROOT`, default `.artifacts`), read by `resolve_paths()` through the
  registry. A relative value is anchored to the project root; an absolute value
  is taken as given. The uploads root is always `repo_root / "uploads"` and has
  no override.
- **`EDGAR_ARTIFACTS_DIR` is retired.** `resolve_paths()` used to read it
  directly, which meant the resolver and the registry each answered "where is
  the artifacts root?" and ignored the other: setting `ARTIFACTS_ROOT` changed
  what the registry reported while the paths actually used stayed at the
  default. The variable is now inert. `ARTIFACTS_ROOT` is the one global
  artifacts-root setting, as
  `roadmap/refactor_v2/unified-runtime-phase-ownership-plan.md` already
  required.
- **There is no cache root here.** The cache root is the registered setting
  `cache.root` (env `CACHE_ROOT`, defaulting to `<artifacts>/caches`) and is
  read through `resolve_runtime_settings().cache_root`. `ProjectPaths` used to
  carry a second answer under `EDGAR_CACHE_DIR` defaulting to
  `<artifacts>/cache`; the two disagreed on both the variable and the directory,
  and nothing read the `ProjectPaths` one. It was removed rather than pointed at
  the registry, so there is now exactly one answer to "where is the cache?".
  The same split has been closed for the artifacts root: the resolver now reads
  `artifacts.root` from the registry, so both roots have exactly one
  authority.
- `current_pointer_path()`, `plan_dir()`, and `transient_dir()` are the shared
  artifact-layout helpers, so every dataset resolves "current" and "staging"
  identically (`paths.py:35-51`).
- `emit_progress(progress, event)` is a no-op when `progress` is `None`, so
  every stage-oriented function can accept an optional callback without
  re-checking at each call site.
- `divide_ids_among_workers(ids, worker_count)` raises `ValueError` for
  `worker_count <= 0` and round-robins by index into `min(worker_count,
  len(ids))` buckets, dropping empty buckets.
- `reclaim()` is safe on any thread and any platform: `_malloc_trim()` loads
  `libc.so.6` once, and on `OSError` or any subsequent exception it sets
  `_TRIM_DISABLED` and returns `False` without propagating
  (`memory.py:21-46`).

**Obligations callers place on this package**

- Never read `os.environ` or `os.getenv` outside `env.py`. The
  `environment-access` scanner reports a finding for any other module.
- Never hardcode a `".artifacts"` literal. The `artifact-paths` scanner exempts
  only `runtime/paths.py`, `runtime/settings/paths.py`, and `check.py`.
- Never hardcode `threads=`, `max_workers=`, or `memory_limit=`. The
  `resource-allocation` scanner exempts `runtime/resources.py`,
  `runtime/settings/`, `foundation/scanners/`, and `scratch/`. Derive with
  `derive_resources()` or accept `None` and let the caller supply the value.
- Run the CLI from the repository root. `resolve_paths()` treats the working
  directory as the project root, so running from anywhere else publishes into a
  parallel tree; the package-directory case is the one it refuses outright.
- Do not call `ensure_directories()` at module import time. It is
  `ProjectPaths.ensure_directories()` and creating directories as an import side
  effect is what the path contract exists to prevent.
- DuckDB connections, per AGENTS.md §2.3, must take
  `threads = resources.threads`, `memory_limit = resources.memory_limit`,
  `temp_directory = resources.temp_directory`, and
  `preserve_insertion_order = false` from the profile this package returns.
  `RuntimeResourceProfile` also exposes `worker_threads`, `memory_limit_str`,
  `memory_limit_mb`, and `temp_dir` as convenience aliases for the same values.
- Any exception raised by a `MenuAction.callback` other than `KeyboardInterrupt`,
  `RuntimeError`, `ValueError`, or `OSError` propagates out of
  `run_interactive_menu()` (`interactive.py:79`). Catch inside the callback.

**How the operators reach the terminal**

`runtime/` has no command of its own. `operator_entrypoint(title, menu,
cli_main, argv=None)` in `interactive.py` is the policy every pipeline operator
follows: with no arguments it shows the interactive menu and returns `0` when
the user exits; with arguments it calls `cli_main(args)`. `run.py` at the
repository root is the separate launcher over a static `ENTRIES` tuple, and
`check.py` is the separate verification gate. Neither of those is in this
package.

## Public surface

- `get_env` / `get_env_int` / `get_env_float` / `get_env_bool` / `load_dotenv` / `DEFAULT_DOTENV_PATH` — environment resolution. `env.py`.
- `derive_resources` — build a `RuntimeResourceProfile` from the settings registry plus system probes, creating the temp directory. `resources.py`.
- `RuntimeResourceProfile` — frozen slotted dataclass: `cpu_cores`, `workers`, `threads`, `memory_limit`, `temp_directory`, `available_memory_bytes`, `worker_memory_mib`, `worker_memory_safety`. `resources.py`.
- `SystemResources` — a name alias of `RuntimeResourceProfile`, exported but referenced nowhere in `edgar_sec/` or `tests/`. `resources.py`.
- `available_memory_bytes` / `read_cgroup_v2_available_bytes` / `read_cgroup_v1_available_bytes` / `read_proc_mem_available_bytes` — individual probes. `resources.py`.
- `auto_worker_count` / `usable_memory_bytes` / `default_cpu_cores` / `default_threads` / `default_memory_limit` — budget arithmetic. `resources.py`.
- `DEFAULT_MEMORY_FRACTION` (0.6), `MIN_MEMORY_MIB` (256), `DEFAULT_WORKER_MEMORY_MIB` (512), `DEFAULT_WORKER_MEMORY_SAFETY` (0.9). `resources.py`.
- `resolve_paths` / `ProjectPaths` / `ProjectRootError` / `PACKAGE_ROOT` — project layout. `paths.py`.
- `current_pointer_path` / `plan_dir` / `transient_dir` and the layout constants `TRANSIENT_DIR`, `CURRENT_DIR`, `POINTER_FILE_NAME`, `PLAN_FILE_NAME`, `SNAPSHOTS_DIR`, `PLANS_DIR`, `DOCUMENTS_DATASET`, `RUNS_DIR`, `CHECKPOINTS_DIR`, `FIXTURES_DIR`, `PAYLOAD_DB_NAME`, `FIXTURE_MANIFEST_NAME`. `paths.py`.
- `reclaim` — `gc.collect()` plus a best-effort `malloc_trim(0)`. `memory.py`.
- `sha256_text` — 1 MiB-chunked text hashing, distinct from `hashing.sha256_text`. `memory.py`.
- `parse_id_selection` — `'1-3,5'` to `(1, 2, 3, 5)`; raises `ValueError` for a descending range. `partitions.py`.
- `divide_ids_among_workers` — balanced round-robin buckets. `partitions.py`.
- `ProgressCallback` / `emit_progress` / `make_tqdm_callback` / `make_merge_progress_callback` — progress wiring; `ProgressCallback` is `Callable[[dict[str, Any]], None] | None`. `progress.py`.
- `MenuAction` / `prompt_text` / `prompt_choice` / `run_interactive_menu` / `operator_entrypoint` — terminal presentation. `interactive.py`.

## Tests

- `tests/foundation/runtime/test_env.py`
- `tests/foundation/runtime/test_memory.py`
- `tests/foundation/runtime/test_partitions.py`
- `tests/foundation/runtime/test_paths.py`
- `tests/foundation/runtime/test_resources.py`
- `tests/foundation/runtime/test_settings.py` (shared with the `settings/` subpackage)

`interactive.py` and `progress.py` have no mirrored test modules. The settings
specs for this package's resources live in `settings/runtime.py` and are
exercised through `tests/foundation/runtime/test_settings.py`.

## Deliberate gaps

- **No config file reader or writer.** `resolve_settings(config=...)` accepts a
  `Mapping` that the caller must already have loaded; nothing in `edgar_sec/`
  reads or writes a persisted settings file. v1's
  `.v1/defs/runtime/config_io.py` and `.v1/defs/runtime/settings_cli.py` were
  not ported. A phase that wants persistence must supply the mapping itself.
- **`memory.sha256_text` is a duplicate with no callers.** It is the
  memory-safe implementation — it streams the encoded bytes through a
  `memoryview` in 1 MiB slices instead of materialising a second full-size copy
  — and it is what AGENTS.md §2.5 describes. Every call site in the repository
  imports the non-streaming `hashing.sha256_text` instead. Long-document callers
  should switch to this one, and the two definitions should collapse into one.
- **`file_sha256` streams 64 KiB, not 1 MiB.** AGENTS.md §2.5 attributes the
  1 MiB chunked streaming to `sha256_text()`; the 64 KiB block streaming in
  `hashing.py:13` belongs to `file_sha256()`, and `sha256_text()` there does a
  single `text.encode("utf-8")`. There is no single function that matches the
  rule as written.
- **`SystemResources` is a bare alias and a rule violation.** The
  `legacy-shims` scanner's rule matches `_legacy*`/`_compat*` function names,
  `Legacy`/`Compat`/`Shim` class names, `legacy_`/`compat_`/`shim_` assignments,
  and compatibility *comments* — not a plain `Alias = ClassName` assignment, so
  the gate stays clean. It is exactly the shim AGENTS.md §1.1 forbids, is
  referenced nowhere, and should be deleted rather than kept.
- **No worker supervision.** `auto_worker_count` and `derive_resources` compute
  budgets; nothing here spawns, monitors, restarts, or reaps processes. No
  `multiprocessing` or `subprocess` import exists in this package.
- **No async, no event loop, no thread pool.** `progress.py` imports `tqdm` at
  module scope, so importing this module requires the third-party dependency.
  `tqdm` is otherwise the only third-party import in `runtime/`; `resources.py`
  makes `psutil` optional and degrades to `/proc` when it is absent.
- **No logging setup.** There is no `logging` import in this package. Log
  configuration is not a Layer 0 concern as the code currently stands.
- **Dropped from v1, by design.** `.v1/defs/runtime/` carried `artifacts.py`,
  `bundle.py`, `cli.py`, `config_io.py`, `registry.py`, and `settings_cli.py`
  alongside the modules that were ported. None were carried over: shared CLI
  argument registration, config persistence, and the launcher registry are
  per-layer or per-pipeline concerns in v2.
- **`partitions.py` is integer-only.** `parse_id_selection` parses integers and
  integer ranges. There is no string- or list-valued selection, no negative or
  wildcard syntax, and no interactive picker; the menu in `interactive.py` is
  the only selection UI.
