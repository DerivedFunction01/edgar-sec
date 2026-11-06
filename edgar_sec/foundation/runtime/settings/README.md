# `edgar_sec/foundation/runtime/settings` — the typed settings registry

Every configurable value in the repository is declared once here, as a
`SettingSpec` under a logical dotted path. This package is a registry and a
resolver; it is not a config file reader, a `.env` writer, or a place for
phase-specific parameters.

## The registry

Settings are declared as `SettingSpec`s by the modular providers under
`foundation/runtime/settings/` — one provider per concern, covering runtime
budgets, project paths, SEC access, Parquet and SQL batching, and the
concerns phases register for themselves. The registry declared there is the
single source of truth: `collect_specs()` introspects every declared spec —
its logical path, derived environment name, type, default, and per-spec
source flags — so this README does not copy the registry out as a table.

`sec.user_agent` is the only `secret=True` spec; a default marked `secret`
is contact identity that must never be published.

One default is deliberately duplicated: the `parquet.row_group_size`
default declared here is consumed above this layer by
`infra.storage.parquet`; the layer graph forbids Layer 0 from importing it,
so the pair is pinned by a mirrored test instead.

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
- Treat a change to the `validate_fraction` bound as settings-breaking:
  narrowing the accepted range would reject a value that resolves today.

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
