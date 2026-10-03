# `edgar_sec/foundation/runtime/settings` — the typed settings registry

Every configurable value in the repository is declared once here, as a
`SettingSpec` under a logical dotted path. This package is a registry and a
resolver; it is not a config file reader, a `.env` writer, or a place for
phase-specific parameters.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | The spec model, name derivation, collection, resolution, and dotenv rendering. |
| `runtime.py` | Concurrency, memory, and chunk specs. |
| `sec.py` | SEC identity, rate limit, timeout, retry, and failure-history specs; `SecSettings`. |
| `paths.py` | Artifacts, cache root, and cache TTL specs. |
| `catalog.py` | Filing-catalog and document-storage batch and row-group specs. |
| `validators.py` | The shared numeric bounds checks. |

## The registry

Every setting under a dotted path, with its derived `env` name and per-spec source
flags. A default marked `secret` is contact identity that must never be published.

| Logical path | Env name | Type | Default | env | config | cli | secret | machine_local |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `runtime.worker_memory_mib` | `RUNTIME_WORKER_MEMORY_MIB` | int | `512` | yes | no | no | no | yes |
| `runtime.worker_memory_safety` | `RUNTIME_WORKER_MEMORY_SAFETY` | float | `0.9` | yes | no | no | no | yes |
| `runtime.workers` | `RUNTIME_WORKERS` | int | `auto_worker_count(...)` | yes | no | yes | no | yes |
| `runtime.chunk_size` | `RUNTIME_CHUNK_SIZE` | int | `1000` | yes | no | yes | no | no |
| `runtime.threads` | `RUNTIME_THREADS` | int | `default_threads()` | yes | no | yes | no | yes |
| `runtime.memory_fraction` | `RUNTIME_MEMORY_FRACTION` | float | `0.6` | yes | no | no | no | yes |
| `runtime.memory_limit` | `RUNTIME_MEMORY_LIMIT` | str | `default_memory_limit(fraction)` | yes | no | yes | no | yes |
| `runtime.temp_directory` | `RUNTIME_TEMP_DIRECTORY` | str | `<tempdir>/edgar-sec-spill` | yes | no | no | no | yes |
| `artifacts.root` | `ARTIFACTS_ROOT` | Path | `.artifacts` | yes | no | no | no | yes |
| `cache.root` | `CACHE_ROOT` | Path | `<artifacts.root>/caches` | yes | no | no | no | yes |
| `cache.ttl_s` | `CACHE_TTL_S` | int | `7776000` (90 days) | yes | no | no | no | yes |
| `sec.user_agent` | `SEC_USER_AGENT` | str | `"Sample Company Name AdminContact@sample.com"` | yes | no | yes | **yes** | no |
| `sec.rate_limit_rps` | `SEC_RATE_LIMIT_RPS` | float | `8.0` | yes | no | yes | no | yes |
| `sec.timeout_s` | `SEC_TIMEOUT_S` | float | `15.0` | yes | no | yes | no | yes |
| `sec.max_retries` | `SEC_MAX_RETRIES` | int | `3` | yes | no | yes | no | yes |
| `sec.max_failure_attempts` | `SEC_MAX_FAILURE_ATTEMPTS` | int | `3` | yes | no | yes | no | yes |
| `catalog.row_group_size` | `CATALOG_ROW_GROUP_SIZE` | int | `128000` | no | no | no | no | no |
| `documents.read_batch_size` | `DOCUMENTS_READ_BATCH_SIZE` | int | `4096` | yes | no | no | no | yes |
| `documents.payload_target_bytes` | `DOCUMENTS_PAYLOAD_TARGET_BYTES` | int | `100663296` (96 MiB) | yes | no | no | no | yes |

`sec.user_agent` is the only `secret=True` spec, and no spec declares
`config=True`. The `catalog.row_group_size` and `documents.*` defaults duplicate
authorities owned by `infra.storage.parquet` and `pipelines.document_storage`; the
layer graph forbids Layer 0 from importing them, so each pair is pinned by a
mirrored test instead.

## Contracts

**Guarantees this package makes to its callers**

- `resolve_settings()` applies one fixed precedence per spec: a non-`None` CLI
  override, then the environment or `.env` when `spec.env` is set, then `config`
  when `spec.config` is set, then the default or default factory. A callable
  default receives the already-resolved mapping, so one setting's default can
  depend on an earlier one. A spec with no value afterwards raises `ValueError`.
- Values are typed at every stage, not only from strings, and a string that does
  not fit its declared type raises an error naming the expected type. Booleans
  accept only `1/true/yes/on` and `0/false/no/off`; a `Path` is `expanduser()`-ed.
- `include` filters by path prefix, matching a whole path or a dotted prefix.
- `flatten_settings(resolved)` drops every path whose spec is `secret=True`, so
  `sec.user_agent` cannot reach a manifest, provenance record, or log.
  `resolve_settings()` itself still returns the secret.
- `render_dotenv()` returns a documented template string with machine-derived
  defaults and secrets commented out. Nothing in this package writes it to disk.

**Obligations callers place on this package**

- Add a setting by declaring a `SettingSpec` in the provider for its concern and
  registering that provider with `collect_specs()`. Do not hand-write the
  environment variable name, and do not read `os.environ` to find it.
- Do not put a credential in a spec that is not `secret=True`, and do not assume
  `secret=True` protects a value you resolve yourself.
- Do not declare `config=True` without a backing store; a spec that advertises
  persistence nothing implements is a capability that does not exist.
- Treat a change to the `validate_fraction` bound as settings-breaking: `1.0` is
  currently accepted, and narrowing the range would reject a value that resolves
  today.

## Public surface

- `SettingSpec`, `MISSING`, `environment_name`, `collect_specs`,
  `resolve_settings`, `resolve_runtime_settings`, `flatten_settings`,
  `render_dotenv`, `RuntimeSettings`. `__init__.py`.
- `SecSettings`. `sec.py`.
- The `get_*_specs()` provider and `DEFAULT_*` value constants that each concern
  module exports. `validators.py` owns the shared bounds checks.

## Mirrored tests

[`tests/foundation/runtime/`](../../../../tests/foundation/runtime/). The catalog
and document defaults are additionally pinned against their owning layers in
`tests/infra/storage/test_parquet.py` and
`tests/pipelines/document_storage/test_settings_contract.py`.

## Deliberate gaps

- **No persistence.** `resolve_settings(config=...)` takes a mapping the caller
  has already loaded. Nothing in `edgar_sec/foundation/` opens, reads, or writes a
  settings file, and no call site in the repository passes a `config` argument. A
  phase needing persistence must supply the mapping.
- **`runtime.partition_count` is retired, not reserved.** Work is distributed
  through static per-worker chunk assignments, so a spec that resolved and were
  addressable by environment variable would let an operator set `RUNTIME_PARTITION_COUNT`
  and see nothing change. A distribution design that needs a count registers a
  phase-owned setting with its own provider.
- **`render_dotenv` returns a template; it does not write one.** An operator
  generates a `.env` by printing it, and `runtime/env.py` reads it back.
- **`machine_local` is declared but not enforced.** No code branches on it, so the
  "do not persist or share across machines" guarantee rests on convention. Anything
  that starts persisting settings has to honour it.
- **No validation of cross-setting consistency.** Each spec is validated in
  isolation; nothing checks that one resolved value is compatible with another.
- **No `catalog.source_batch_size`.** `materialize` never batched on it, so a knob
  that appears to bound work and does not would be worse than no knob.
- **No command surface.** There is no `__main__.py` and no console-script entry
  point; `check.py --scan` is the only way the repository surfaces the registry's
  own rules.
