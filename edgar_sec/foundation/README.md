# `edgar_sec/foundation` — Layer 0: primitives with zero SEC domain knowledge

Layer 0 is the bottom of the acyclic layer graph: hashing, canonical
serialization, zstd frame compression, the policy-scanner registry and the gate
that runs it, the runtime environment, path layout, resource budgeting, and the
shared text and regex vocabulary every upper layer builds on. It is not the
place for SEC domain logic — a CIK, an accession number, or a filing-specific
vocabulary belongs in `domain/`, not here.

## Purpose

Two responsibilities, and nothing else:

1. **Primitives with no dependencies.** Hashing, canonical JSON, zstd frame
   compression, Unicode and text normalization, regex assembly, and resource
   derivation. Every function here is callable in isolation, with no repository
   state and no network.
2. **The enforcement mechanism.** The scanners in `scanners/` are what turn the
   rules in `AGENTS.md` into a failing build rather than a paragraph nobody
   reads.

It holds no data models, performs no I/O against SEC endpoints, and starts no
work. Its only side effects are directory creation in `runtime/paths.py` and
`runtime/resources.py`, and the transient dependency-graph cache written by
`checks/lineage.py`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `hashing.py` | Streaming SHA-256 digests of files, bytes, and text. |
| `serialization.py` | `canonical_json` / `canonical_hash` for identity-stable payloads; `json_safe` / `safe_dumps` for representability. |
| `compression.py` | The repository's only zstd frame codec. |
| `regex/` | The regex builder DSL and prefix-tree factorisation. See [`regex/README.md`](regex/README.md). |
| `runtime/` | Environment, project and fixture paths, resources, memory, progress, partitions, interactive dispatch. See [`runtime/README.md`](runtime/README.md). |
| `runtime/settings/` | The single typed settings registry. See [`runtime/settings/README.md`](runtime/settings/README.md). |
| `scanners/` | The registered policy scanners. See [`scanners/README.md`](scanners/README.md). |
| `checks/` | The gate: runs the scanners, reads git status, resolves AST test lineage. See [`checks/README.md`](checks/README.md). |
| `sql/` | Read-only validation for operator-supplied queries. See [`sql/README.md`](sql/README.md). |
| `text/` | Shared pattern vocabulary: dates, tokens, grammar, compounds, normalisation, the Aho-Corasick automaton. See [`text/README.md`](text/README.md). |

Consumers import from the leaf module, e.g.
`from edgar_sec.foundation.hashing import file_sha256`. Per `AGENTS.md` §1.2 no
`__init__.py` here re-exports a child module's symbols; the two deliberate
registries that clause permits are `scanners.ALL_SCANNERS` and the settings API
in `runtime/settings/__init__.py`.

## Contracts

**Boundaries this layer draws**

- Zero internal dependencies on upper layers (`AGENTS.md` §1), re-validated on
  every gate run by the `layer-boundary` scanner.
- Two function-local imports are important rather than stylistic, because a
  module-scope import in either direction would be a cycle:
  `runtime/resources.derive_resources()` reaching into `.settings`, and the
  default factories in `runtime/settings/runtime.py` reaching into `..resources`.
- The layer graph also forces *value* duplication. `runtime/settings/catalog.py`
  mirrors constants whose owners sit above it — the Parquet row-group size and
  the document batch and target sizes. Equality is pinned by tests in those
  owning packages, so one-sided drift fails the gate instead of silently moving a
  default. See [`runtime/settings/README.md`](runtime/settings/README.md).

**Guarantees this layer makes to its callers**

- `canonical_json` is byte-stable — sorted keys, compact separators, ASCII
  escaping — so two structurally equal payloads produce the same
  `canonical_hash()` digest, which is what makes manifest identity reproducible
  across runs and machines. `json_safe` / `safe_dumps` are lossy by design and
  carry no determinism guarantee.
- Hashing streams rather than materialising: `file_sha256` and `sha256_text` are
  digest-equivalent to their whole-input forms without a second full-size bytes
  copy. The block and slice sizes are module constants in `hashing.py`.
- `compression.py` is the only entry point to the `zstandard` library, so a frame
  written by one layer is read by another without either owning the parameters.
  A codec object carries window and history state, so each thread gets its own. A
  Parquet-`zstd` file never routes through here: the format already compressed
  it, and this is for values that are themselves a frame.
- `runtime/resources.py` reads cgroup limits before falling back to `psutil` and
  `/proc/meminfo`, and never sizes workers from raw CPU count; `auto_worker_count`
  is the smaller of the core count and the memory budget, floored at one.
- `runtime/settings/` is the single settings registry. `environment_name()` is
  the only place an environment variable name is derived, resolution precedence is
  fixed, a `validate` callback that raises `ValueError` fails resolution rather
  than yielding an out-of-range value, and `flatten_settings()` strips every
  `secret=True` spec before a mapping reaches a manifest, a provenance record, or
  a log.
- `regex/builder.py` orders alternation branches longest-first, so a longer
  phrase is never shadowed by a shorter one that is a prefix of it.
- Scanner output is order-stable, and **every finding fails the gate**:
  `checks.runner.run_all()` returns `1` if any scanner reported any. There is no
  severity model and no suppression mechanism.

**Obligations callers place on this layer**

- `runtime/env.py` is the only sanctioned environment access. A path literal
  belongs in a path resolver. A resource budget must be derived, never
  hardcoded. Vocabulary — regex alternations, month tables, canonical JSON —
  belongs to the module that owns it, not to the caller. Each scanner's rule and
  its exemptions are tabulated in [`scanners/README.md`](scanners/README.md).
- Lint suppression belongs in `ruff.toml`. The scanners do not read lint
  configuration, so a `# noqa` cannot silence a policy finding.

## Command surface

Layer 0 has no command of its own. `check.py` at the repository root imports
`edgar_sec.foundation.checks.runner.run_all` and exits on its return code, so the
gate must be run from the repository root — file discovery is `Path.cwd()`-anchored.

```bash
.venv/bin/python check.py           # ruff format check, ruff lint check, scanners, pytest
.venv/bin/python check.py --fast    # static checks and scanners; skips pytest
.venv/bin/python check.py --scan    # registered scanners only
```

Exit status is `0` when every scanner is clean and `1` when any scanner reported a
finding. See [`checks/README.md`](checks/README.md).

## Public surface

Grouped by owner; the owning module or subpackage README carries the signatures
and the per-symbol detail.

- Identity and encoding: `file_sha256`, `sha256_bytes`, `sha256_text`
  (`hashing.py`); `canonical_json`, `canonical_hash`, `json_safe`, `safe_dumps`
  (`serialization.py`); `compress_payload`, `decompress_payload`
  (`compression.py`).
- [`regex/`](regex/README.md): the builder DSL and prefix-tree factorisation.
- [`runtime/`](runtime/README.md): environment access, `ProjectPaths`, generic
  fixture location and manifest-envelope validation, the
  derived resource profile and its memory arithmetic, `reclaim`, progress,
  partitions, interactive dispatch. [`runtime/settings/`](runtime/settings/README.md):
  `SettingSpec` and the resolve, flatten, and render API.
- [`scanners/`](scanners/README.md): `ALL_SCANNERS`, `Scanner`, `ScannerFinding`.
- [`checks/`](checks/README.md): `registered()`, `run_all()`.
- [`sql/`](sql/README.md): `validate_read_only` and its verb allowlist.
- [`text/`](text/README.md): the date, token, grammar, compound, and
  normalization vocabulary, plus the multi-pattern automaton.

## Mirrored tests

`tests/foundation/` mirrors this package directory for directory, with one test
module per source module and `conftest.py` at the narrowest directory that needs
shared setup. Fixture paths come from `tests.support` (`load_fixture`,
`fixture_path`) rather than `parents[N]` depth arithmetic, and offline network
doubles are injected at the transport seam. Scanner tests build a synthetic
repository tree under `tmp_path` and `monkeypatch.chdir` into it, because
discovery is cwd-anchored.

## Deliberate gaps

- **No packaging metadata.** There is no `pyproject.toml` and no console script.
  Everything is invoked as `python check.py`, `python run.py`, or
  `python -m edgar_sec.pipelines.<name>.operator`.
- **The gate sees Python source in two trees.** Discovery covers `edgar_sec/`
  and `tests/` plus `check.py` and `run.py`, skipping dot-prefixed path
  components. Nothing in `roadmap/`, `ruff.toml`, CI configuration, dependency
  manifests, or documentation is scanned. See
  [`scanners/README.md`](scanners/README.md).
- **No SEC domain knowledge, by design.** Identity primitives, filing schemas,
  and form vocabulary live in `domain/`. Anything Layer 0 would need to know about
  a filing is a dependency running the wrong way.
- **Runtime-adjacent capabilities are delegated, not absent.** Logging setup,
  config persistence, worker supervision, and the argument registry are owned by
  the layers that need them. The specific omissions are recorded in
  [`runtime/README.md`](runtime/README.md),
  [`runtime/settings/README.md`](runtime/settings/README.md), and
  [`regex/README.md`](regex/README.md).
