# `edgar_sec/foundation/runtime/settings` — the typed settings registry

Every configurable value in the repository is declared here exactly once, as a
`SettingSpec` under a logical dotted path. The environment variable name is
derived from that path by `environment_name()` rather than written by hand, and
resolution flows through `runtime/env.py` in a fixed precedence order. This
package is a registry and a resolver; it is not a config file reader, a
`.env` writer, or a place for phase-specific parameters.

## Purpose

The registry exists so that a setting has one identity, one type, one default,
and one documented description, and so that the environment variable which
controls it is a pure function of its name. `sec.rate_limit_rps` becomes
`SEC_RATE_LIMIT_RPS` because `environment_name()` uppercases and replaces
separators — not because somebody wrote that constant somewhere.

Each spec module owns one concern and exports a `get_*_specs()` function, so a
new phase registers its own group rather than growing a monolithic configuration
class.

What this package is not: a persistence layer. `resolve_settings(config=...)`
takes a mapping the caller supplies; nothing here reads or writes a file.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | `SettingSpec`, `environment_name`, `collect_specs`, `resolve_settings`, `flatten_settings`, `render_dotenv`, `RuntimeSettings` (315 loc). |
| `runtime.py` | Concurrency, memory, chunk, and partition specs (143 loc). |
| `sec.py` | SEC identity, rate limit, timeout, retry, and failure-history specs; `SecSettings` (99 loc). |
| `paths.py` | Artifacts and cache root specs (64 loc). |
| `catalog.py` | Filing-catalog batch and row-group specs (63 loc). |
| `validators.py` | `validate_positive_int`, `validate_non_negative_int`, `validate_fraction` (38 loc). |

`collect_specs()` calls exactly four providers, in this order:
`get_runtime_specs`, `get_paths_specs`, `get_sec_specs`, `get_catalog_specs`
(`__init__.py:75-80`). Each spec module imports `SettingSpec` from `.` inside
its function body under a `TYPE_CHECKING` guard, so the cycle between the
package and its providers is closed only at call time.

## The registry

Nineteen settings are registered. `env` names below are derived, never
hand-written.

| Logical path | Env name | Type | Default | env | config | cli | secret | machine_local |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `runtime.worker_memory_mib` | `RUNTIME_WORKER_MEMORY_MIB` | int | `512` | yes | no | no | no | yes |
| `runtime.worker_memory_safety` | `RUNTIME_WORKER_MEMORY_SAFETY` | float | `0.9` | yes | no | no | no | yes |
| `runtime.workers` | `RUNTIME_WORKERS` | int | `auto_worker_count(...)` | yes | no | yes | no | yes |
| `runtime.chunk_size` | `RUNTIME_CHUNK_SIZE` | int | `1000` | yes | yes | yes | no | no |
| `runtime.partition_count` | `RUNTIME_PARTITION_COUNT` | int | `1` | yes | yes | yes | no | no |
| `runtime.threads` | `RUNTIME_THREADS` | int | `default_threads()` | yes | no | yes | no | yes |
| `runtime.memory_fraction` | `RUNTIME_MEMORY_FRACTION` | float | `0.6` | yes | no | no | no | yes |
| `runtime.memory_limit` | `RUNTIME_MEMORY_LIMIT` | str | `default_memory_limit(fraction)` | yes | no | yes | no | yes |
| `runtime.temp_directory` | `RUNTIME_TEMP_DIRECTORY` | str | `<tempdir>/edgar-sec-spill` | yes | no | no | no | yes |
| `artifacts.root` | `ARTIFACTS_ROOT` | Path | `.artifacts` | yes | no | no | no | yes |
| `cache.root` | `CACHE_ROOT` | Path | `<artifacts.root>/caches` | yes | no | no | no | yes |
| `cache.json_ttl_s` | `CACHE_JSON_TTL_S` | int | `7776000` (90 days) | yes | no | no | no | yes |
| `sec.user_agent` | `SEC_USER_AGENT` | str | `"Sample Company Name AdminContact@sample.com"` | yes | no | yes | **yes** | no |
| `sec.rate_limit_rps` | `SEC_RATE_LIMIT_RPS` | float | `8.0` | yes | no | yes | no | yes |
| `sec.timeout_s` | `SEC_TIMEOUT_S` | float | `15.0` | yes | no | yes | no | yes |
| `sec.max_retries` | `SEC_MAX_RETRIES` | int | `3` | yes | no | yes | no | yes |
| `sec.max_failure_attempts` | `SEC_MAX_FAILURE_ATTEMPTS` | int | `3` | yes | no | yes | no | yes |
| `catalog.source_batch_size` | `CATALOG_SOURCE_BATCH_SIZE` | int | `1000` | yes | no | no | no | yes |
| `catalog.row_group_size` | `CATALOG_ROW_GROUP_SIZE` | int | `128000` | no | no | no | no | no |

`sec.user_agent` is the only `secret=True` spec. It is also the only spec with
`env` and `cli` set and `machine_local` unset.

## Contracts

**Guarantees this package makes to its callers**

- `environment_name(path)` is the sole source of environment variable names for
  settings: hyphens and dots become underscores, and the result is uppercased
  (`__init__.py:45-52`). An empty or non-string path raises `ValueError`.
- `resolve_settings()` applies one fixed precedence per spec: a non-`None` CLI
  override, then the environment or `.env` when `spec.env` is set, then
  `config` when `spec.config` is set, then the default or default factory
  (`__init__.py:174-196`). A spec whose value is still missing afterwards raises
  `ValueError("setting {path!r} has no value")`.
- A default that is a callable is invoked. `_call_default` inspects the
  signature and passes the already-resolved mapping when the callable takes at
  least one parameter, which is how `cache.root` reads `artifacts.root` and
  `runtime.memory_limit` reads `runtime.memory_fraction` (`__init__.py:140-147`).
- Values are typed at every stage, not only from strings. CLI and config values
  go through `_check_typed_value`; string values go through `_parse_value`,
  which also raises a message naming the expected type. `Path` values are
  `expanduser()`-ed.
- Boolean strings are matched against `{"1", "true", "yes", "on"}` and
  `{"0", "false", "no", "off"}`; anything else in a `bool` spec raises
  `ValueError` (`__init__.py:87-93`).
- `include` filters by path prefix, matching either the whole path or a dotted
  prefix (`__init__.py:150-154`). `derive_resources()` uses
  `include=["runtime"]`.
- `flatten_settings(resolved)` drops every path whose spec is `secret=True`, so
  `sec.user_agent` cannot reach a manifest, provenance record, or log
  (`__init__.py:260-269`).
- `render_dotenv()` groups by the first dotted segment, emits the spec
  `description` as a comment above each entry, writes a secret as a commented
  `# NAME=<secret-value>` placeholder, and comments out any value whose default
  is a callable, because those are machine-derived.
- Setting names are validated on collection: a segment must match
  `^[a-z][a-z0-9_]*$`, and a duplicate flattened path raises `ValueError`
  (`__init__.py:59-66`).
- `validate_fraction` accepts `(0, 1]` inclusively at the top, matching the
  pre-existing `runtime` spec check. Narrowing it would silently reject a value
  that used to resolve, so it is documented rather than "fixed"
  (`validators.py:23-31`).
- `catalog.DEFAULT_ROW_GROUP_SIZE` is a deliberate duplication of
  `edgar_sec.infra.storage.parquet.DEFAULT_ROW_GROUP_SIZE`, forced by the layer
  graph: Layer 0 may not import Layer 2. The equality is pinned by
  `tests/infra/storage/test_parquet.py:55`, so a one-sided change fails the gate.

**Obligations callers place on this package**

- Add a setting by declaring a `SettingSpec` in the provider for its concern and
  adding that provider to the tuple in `collect_specs()`. Do not add a
  hand-written environment variable name, and do not read `os.environ` to find
  it: the `environment-access` scanner reports a finding for any `os.environ` or
  `os.getenv` outside `runtime/env.py`.
- Do not create a monolithic settings class. A new concern gets its own
  `get_*_specs()` provider, which is the mechanism AGENTS.md §3.1 requires.
- Do not widen `validate_fraction` to `(0, 1)` or narrow it to exclude `1.0`
  without treating it as a settings-breaking change.
- Do not put a credential in a spec that is not `secret=True`, and do not
  assume `secret=True` protects a value you resolve yourself: `resolve_settings`
  returns the secret; only `flatten_settings` strips it.
- If you read `.artifacts` from this package, use `artifacts.root` rather than
  writing the literal. The `artifact-paths` scanner exempts
  `settings/paths.py` as the owner of that default.

## Public surface

- `SettingSpec` — frozen slotted dataclass: `value_type`, `default`, `env`, `config`, `cli`, `secret`, `machine_local`, `description`, `validate`. `__init__.py`.
- `environment_name` — logical dotted path to derived environment name. `__init__.py`.
- `collect_specs` — flatten all four providers into `dict[str, SettingSpec]`. `__init__.py`.
- `resolve_settings` — the precedence resolver, returning `dict[str, object]`. `__init__.py`.
- `resolve_runtime_settings` — resolve everything and return a typed `RuntimeSettings`. `__init__.py`.
- `RuntimeSettings` — frozen slotted dataclass: `sec`, `worker_memory_mib`, `worker_memory_safety`, `memory_fraction`, `default_chunk_size`, `default_partition_count`, `artifacts_root`, `cache_root`, `temp_directory`, `log_level`. `__init__.py`.
- `flatten_settings` — strip `secret=True` paths from a resolved mapping. `__init__.py`.
- `render_dotenv` — produce a documented `.env` template string. `__init__.py`.
- `MISSING` — sentinel distinguishing "not supplied" from a value. `__init__.py`.
- `SecSettings` — frozen slotted dataclass of the five SEC values, plus `header_user_agent`. `sec.py`.
- `get_runtime_specs` / `get_paths_specs` / `get_sec_specs` / `get_catalog_specs` — the four providers. `runtime.py`, `paths.py`, `sec.py`, `catalog.py`.
- `validate_positive_int` / `validate_non_negative_int` / `validate_fraction` — shared bounds checks. `validators.py`.
- `DEFAULT_CHUNK_SIZE` (1000), `DEFAULT_PARTITION_COUNT` (1), `DEFAULT_WORKER_MEMORY_MIB` (512), `DEFAULT_WORKER_MEMORY_SAFETY` (0.9), `DEFAULT_MEMORY_FRACTION` (0.6). `runtime.py`.
- `DEFAULT_ARTIFACTS_ROOT` (`Path(".artifacts")`), `DEFAULT_CACHE_JSON_TTL_S` (7776000). `paths.py`.
- `DEFAULT_USER_AGENT`, `DEFAULT_RATE_LIMIT_RPS` (8.0), `DEFAULT_TIMEOUT_S` (15.0), `DEFAULT_MAX_RETRIES` (3), `DEFAULT_MAX_FAILURE_ATTEMPTS` (3). `sec.py`.
- `DEFAULT_SOURCE_BATCH_SIZE` (1000), `DEFAULT_ROW_GROUP_SIZE` (128000). `catalog.py`.

## Tests

- `tests/foundation/runtime/test_settings.py` — the single test module for this
  package. It covers `environment_name` mapping, typed resolution, and the
  `flatten_settings` / `render_dotenv` behaviour.
- `tests/foundation/runtime/test_resources.py` — exercises the `runtime` group
  through `derive_resources()`.
- `tests/foundation/runtime/test_runtime_settings.py` — the mirrored test for
  `runtime.py`: spec defaults against the exported constants, the `env`/`cli`/
  `config` flags, bounds validation, and the `machine_local` partition between
  plan-defining and machine-derived settings.
- `tests/infra/storage/test_parquet.py` — pins `catalog.row_group_size` to the
  Parquet writer's `DEFAULT_ROW_GROUP_SIZE`.

There are no separate test modules for `catalog.py`, `paths.py`, `sec.py`, or
`validators.py`; `validators.py` is covered through
`test_runtime_settings.py::test_validators_enforce_their_documented_bounds`.

## Deliberate gaps

- **No persistence.** `resolve_settings(config=...)` takes a `Mapping` the
  caller has already loaded. Nothing in `edgar_sec/foundation/` opens, reads, or
  writes a settings file, and no call site in the repository passes a `config`
  argument. v1's `.v1/defs/runtime/config_io.py` and `settings_cli.py` were not
  ported, and neither was v1's Phase 1 `ProjectConfig` / `--configure`; the
  retirement is recorded in `roadmap/refactor_v2/phase_1.md` §10. A phase needing
  persistence must supply the mapping. The `config=True` flags that
  `runtime.chunk_size` and `runtime.partition_count` previously carried have been
  **removed**: a spec declaring persistence with no backing store advertises a
  capability that does not exist, and
  `tests/foundation/runtime/test_runtime_settings.py` now fails if either
  reintroduces it.
- **`render_dotenv` has no callers.** It returns a template string; no writer
  in this package places it on disk, and nothing in `edgar_sec/` invokes it.
  Callers that want a `.env` must write the string themselves, and
  `load_dotenv` in `runtime/env.py` is what reads it back.
- **`machine_local` is declared and never read.** The flag is on the
  `SettingSpec` dataclass and set on 15 of the 19 specs, but no code branches on
  it. It documents intent — that a value should not be persisted or shared
  across machines — and AGENTS.md §3 treats that as a real requirement, so the
  guarantee currently rests on convention rather than on enforcement. Anything
  that persists settings would have to honour it.
- **No plugin or per-phase registration mechanism.** `collect_specs()` names its
  four providers in a hardcoded tuple. Registering a fifth concern means editing
  `__init__.py`; there is no entry-point discovery, decorator, or registry
  pattern for extension.
- **`log_level` is inert.** `RuntimeSettings.log_level` defaults to `"INFO"` but
  is not read from any spec, and no logger in this repository is configured by
  it.
- **No validation of cross-setting consistency.** Each spec is validated in
  isolation. Nothing checks that, for example, `runtime.partition_count` is
  reachable by the available `runtime.workers`, or that a `sec.timeout_s` is
  compatible with a configured rate limit.
- **No coercion of near-miss strings.** `_parse_value` is strict: `"8"` will not
  satisfy a `float` spec, and an unrecognised boolean word raises rather than
  defaulting. The looser behaviour lives in `runtime/env.py`'s
  `get_env_int` / `get_env_float` / `get_env_bool`, which is a deliberate
  difference: a typo in a setting name should be loud.
- **No command surface.** v1 shipped a `settings_cli.py`. There is no v2
  equivalent, and no `__main__.py` in this package; `python check.py --scan`
  is the only way the repository surfaces the registry's own rules.
