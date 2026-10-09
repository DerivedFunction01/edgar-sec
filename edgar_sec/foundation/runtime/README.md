# `edgar_sec/foundation/runtime` — environment, path layout, resource budgeting, and process-facing wiring

Layer 0's answer to "what machine am I on, where do I write, and how much work may
I start?". It resolves environment variables, derives the project directory
layout, computes memory- and CPU-aware concurrency budgets from cgroup limits,
reclaims glibc heap pages, and adapts progress and terminal interaction for
pipeline entry points. It starts no workers, opens no sockets, and owns no
lifecycle.

## Purpose

| Concern | Modules |
| :--- | :--- |
| Configuration sources. `env.py` is the only module permitted to touch `os.environ`. | `env.py`, `settings/` |
| Where project roots and shared artifact/fixture layout are resolved. | `paths.py`, `fixtures.py`, `settings/paths.py` |
| How much may run at once, from cgroup and `/proc` facts rather than raw CPU count. | `resources.py` |
| How a run presents itself and splits work. | `progress.py`, `interactive.py`, `partitions.py` |

Not a pipeline runner: this package does not run a pipeline, create workers, or
know what a CIK or an accession number is.

## Contracts

**Guarantees this package makes to its callers**

- `get_env(name, default="", *, dotenv_path=None)` resolves the process
  environment first, then a `.env` file, then the default. The `.env` location
  is, in order, the explicit `dotenv_path`, the `DOTENV_PATH` environment
  variable, then `.env` in the working directory.
- `load_dotenv(path=".env")` returns a plain `dict` and does **not** mutate
  `os.environ`. It skips blank lines and `#` comments, strips a leading
  `export `, and unwraps matching single or double quotes. A missing or
  unreadable file yields `{}` rather than raising.
- `get_env_int`, `get_env_float`, and `get_env_bool` fall back to the supplied
  default on an unparseable value rather than raising. `get_env_bool` treats
  `{"1", "true", "yes", "on"}` as true, case-insensitively, and *any other
  non-empty value* as false.
- `available_memory_bytes()` never prefers `MemTotal` over a real limit. It tries
  cgroup v2 (`memory.max` minus `memory.current`, returning `None` when
  `memory.max` is the literal `max`), then cgroup v1, then psutil, then
  `/proc/meminfo` `MemAvailable`, and only then `_physical_memory_bytes()`.
- `auto_worker_count(available, worker_memory_mib=512, safety_fraction=0.9)`
  returns `max(1, min(cores, mem_workers))`, so the memory budget and the CPU
  count are both upper bounds and the answer is never zero.
- `usable_memory_bytes()` and `auto_worker_count()` reject a `safety_fraction`
  outside `(0, 1]` with `ValueError`; `default_memory_limit()` rejects a
  `fraction` outside `(0, 1]`.
- `derive_resources()` returns a frozen, slotted `RuntimeResourceProfile` and
  creates its `temp_directory` as a side effect with
  `mkdir(parents=True, exist_ok=True)`.
- `resolve_paths()` with no `repo_root` treats the working directory as the
  project root, and raises `ProjectRootError` when that directory is the
  `edgar_sec` package directory or anywhere beneath it. Passing an explicit
  `repo_root` bypasses that check, because a caller that names the root has
  already answered the question.
- The artifacts root is the registered setting `artifacts.root` (env
  `ARTIFACTS_ROOT`, default `.artifacts`), read by `resolve_paths()` through the
  registry. A relative value is anchored to the project root; an absolute value
  is taken as given. The uploads root is always `repo_root / "uploads"` and has
  no override. **There is no cache root here**: the cache root is `cache.root`
  (env `CACHE_ROOT`, default `<artifacts>/caches`), read through
  `resolve_runtime_settings().cache_root`. Both roots have exactly one
  authority.
- `runtime_root()` and `transient_dir()` are shared
  artifact-layout primitives. Dataset run/checkpoint trees remain pipeline-owned.
- `fixture_paths()` resolves a fixture below
  `<artifacts_root>/<dataset>/fixtures/<fixture_id>` and validates every path
  component. `FixtureManifestEnvelope` validates the common identity, version,
  storage reference, timestamps, and details object. This module does no file or
  JSON IO; pipelines own fixture discovery and payload semantics, and storage
  infrastructure owns atomic persistence.
- `emit_progress(progress, event)` is a no-op when `progress` is `None`, so
  every stage-oriented function can accept an optional callback without
  re-checking at each call site.
- `divide_ids_among_workers(ids, worker_count)` raises `ValueError` for
  `worker_count <= 0` and round-robins by index into `min(worker_count,
  len(ids))` buckets, dropping empty buckets.
- `reclaim()` is safe on any thread and any platform: `_malloc_trim()` loads
  `libc.so.6` once, and on `OSError` or any subsequent exception it sets
  `_TRIM_DISABLED` and returns `False` without propagating.

**Obligations callers place on this package**

- Never read `os.environ` or `os.getenv` outside `env.py`; the
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
- Do not call `ensure_directories()` at module import time. Creating directories
  as an import side effect is what the path contract exists to prevent.
- DuckDB connections, per AGENTS.md §2.3, must take `threads`, `memory_limit`,
  `temp_directory`, and `preserve_insertion_order = false` from the profile this
  package returns. `RuntimeResourceProfile` also exposes `worker_threads`,
  `memory_limit_str`, `memory_limit_mb`, and `temp_dir` as convenience aliases.

**How the operators reach the terminal**

`runtime/` has no command of its own. `operator_entrypoint(title, menu,
cli_main, argv=None)` in `interactive.py` is the policy every pipeline operator
follows: with no arguments it shows the interactive menu and returns `0` when the
user exits; with arguments it calls `cli_main(args)`. `run.py` at the repository
root is the separate launcher over a static `ENTRIES` tuple, and `check.py` is
the separate verification gate. Neither is in this package.

## Deliberate gaps

- **No fixture file IO or payload schema.** The shared fixture module validates
  locations and the common manifest envelope only; pipelines own JSON/SQLite
  readers, writers, lineage, and domain-specific details.
- **No config file reader or writer.** `resolve_settings(config=...)` accepts a
  `Mapping` the caller must already have loaded; nothing in `edgar_sec/` reads
  or writes a persisted settings file, and no call site passes a `config`
  argument. A phase that wants persistence must supply the mapping itself.
- **No worker supervision.** `auto_worker_count` and `derive_resources` compute
  budgets; nothing here spawns, monitors, restarts, or reaps processes. No
  `multiprocessing` or `subprocess` import exists in this package.
- **No async, no event loop, no thread pool.** `progress.py` imports `tqdm` at
  module scope, so importing it requires the third-party dependency. `tqdm` is
  otherwise the only third-party import in `runtime/`; `resources.py` makes
  `psutil` optional and degrades to `/proc` when it is absent.
- **No logging setup.** There is no `logging` import in this package. Log
  configuration is not a Layer 0 concern as the code currently stands.
- **No argument registry or launcher.** CLI argument registration, config
  persistence, and the launcher registry are per-layer or per-pipeline concerns;
  the gate lives in `edgar_sec/foundation/checks/`.
- **`partitions.py` is integer-only.** `parse_id_selection` parses integers and
  integer ranges. There is no string- or list-valued selection, no negative or
  wildcard syntax, and no interactive picker; the menu in `interactive.py` is
  the only selection UI.
