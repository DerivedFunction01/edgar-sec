# `edgar_sec/foundation` — Layer 0 utilities: pure primitives with zero SEC domain knowledge

Layer 0 is the bottom of the acyclic layer graph. It owns hashing, canonical
serialization, the policy-scanner registry, the runtime environment, resource
budgeting, path layout, and the shared text/regex vocabulary that every upper
layer builds on. It is not a place for SEC domain logic: a CIK, an accession
number, or a filing-specific vocabulary belongs in `domain/`, not here.

## Purpose

Two responsibilities, and nothing else:

1. **Primitives with no dependencies.** Hashing, canonical JSON, Unicode and
   text normalization, regex assembly, and resource derivation. Each function
   here is callable in isolation, with no repository state and no network.
2. **The enforcement mechanism.** The policy scanners in `scanners/` are what
   turn the rules in `AGENTS.md` into a failing build rather than a paragraph
   nobody reads.

What this package is *not*: it holds no data models, performs no I/O against
SEC endpoints, and starts no work. The only side effect any Layer 0 function
performs is directory creation in `runtime/resources.derive_resources()` and
`runtime/paths.ProjectPaths.ensure_directories()`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `checks.py` | Runs every registered scanner and returns a gate exit code (29 loc). |
| `hashing.py` | `file_sha256`, `sha256_bytes`, `sha256_text` hex digests (28 loc). |
| `serialization.py` | `canonical_json` / `canonical_hash` for identity-stable payloads, and `json_safe` / `safe_dumps` for representability (78 loc). |
| `regex/` | Regex builder DSL and prefix-tree factorisation. See `regex/README.md`. |
| `runtime/` | Environment, paths, resources, memory, progress, partitions, interactive dispatch, `settings/`. See `runtime/README.md`. |
| `runtime/settings/` | Typed settings specs and resolution. See `runtime/settings/README.md`. |
| `scanners/` | The 11 registered policy scanners. See `scanners/README.md`. |
| `sql/` | Read-only validation for operator-supplied queries. See `sql/README.md`. |
| `text/` | Shared pattern vocabulary: dates, tokens, grammar, compounds, normalisation, the Aho-Corasick automaton. See `text/README.md`. |

Every `__init__.py` in this layer is a one-line docstring. There are no barrel
re-exports, per `AGENTS.md` §1.2: consumers import from the leaf module, e.g.
`from edgar_sec.foundation.hashing import file_sha256`. The one registry
exception is `scanners.ALL_SCANNERS`, which `AGENTS.md` §1.2 explicitly allows.

## Layer map

Layer 0 has **zero internal dependencies on upper layers**. The complete
internal import graph of this layer is:

| Subpackage | Modules | May import from within Layer 0 |
| :--- | :--- | :--- |
| `checks.py` | 1 | `scanners` |
| `hashing.py` | 1 | nothing (stdlib only) |
| `serialization.py` | 1 | nothing (stdlib only) |
| `regex/` | `builder.py` (209 loc), `trie.py` (99 loc) | `regex.trie` |
| `runtime/` | `env.py`, `interactive.py`, `memory.py`, `partitions.py`, `paths.py`, `progress.py`, `resources.py`, `settings/` | `runtime.env`, `runtime.settings` (and back again, via function-local imports) |
| `runtime/settings/` | `__init__.py` (315), `runtime.py` (143), `sec.py` (99), `paths.py` (64), `catalog.py` (63), `validators.py` (38) | `settings.validators`, `settings.catalog`, `settings.paths`, `settings.runtime`, `settings.sec` |
| `scanners/` | 15 modules; 11 are registered scanners | `scanners.base`, `scanners.files`, `scanners.lines` |
| `text/` | `dates.py` (448), `automaton.py` (421), `grammar.py` (233), `compounds.py` (169), `tokens.py` (147), `normalize.py` (71), `patterns.py` (47) | `regex.builder`, `text.tokens` |

Two cross-edges are resolved with function-local imports rather than at module
scope, and both are load-bearing rather than stylistic:

- `runtime/resources.derive_resources()` imports `.settings` inside the
  function body (`resources.py:227`).
- `settings/runtime.py` imports `..resources` inside its default factories
  (`_default_threads`, `_default_workers`, `_default_memory_limit`).

Module-scope imports in both directions would be a cycle, since
`settings/catalog.py` documents the reason in the other direction too: Layer 0
may not import Layer 2, so `DEFAULT_ROW_GROUP_SIZE` is duplicated from
`edgar_sec.infra.storage.parquet` and the equality is pinned by
`tests/infra/storage/test_parquet.py:55`.

The `layer-boundary` scanner in `scanners/layers.py` validates this graph on
every gate run. It assigns ranks `{foundation: 0, domain: 1, infra: 2, engine: 3,
pipelines: 4}` and reports an `Illegal upward import` finding whenever a module
imports a strictly higher rank. Caveat worth knowing: the scanner only inspects
`ast.Import` and `ast.ImportFrom` nodes whose `node.module` begins with
`edgar_sec.`, so a *relative* upward import such as `from ..infra.storage import
duckdb` written inside `edgar_sec/foundation/` is not flagged. The rule holds by
convention and by review today, not by the scanner for that one spelling.

## Contracts

**Guarantees this layer makes to its callers**

- `canonical_json()` in `serialization.py` is byte-stable: `sort_keys=True`,
  `separators=(",", ":")`, `ensure_ascii=True`. Two structurally equal payloads
  therefore produce the same `canonical_hash()` digest, which is what makes
  manifest identity reproducible across runs and machines.
- `file_sha256()` in `hashing.py` never loads the whole file; it streams in
  64 KiB blocks (`hashing.py:13`).
- `derive_resources()` in `runtime/resources.py` never sizes workers from raw
  CPU count. `auto_worker_count()` returns `max(1, min(cores, mem_workers))`
  where `mem_workers` is the safety-fraction-scaled available memory divided by
  the per-worker budget, and `available_memory_bytes()` prefers cgroup v2, then
  cgroup v1, then psutil, then `/proc/meminfo` `MemAvailable`.
- `environment_name()` in `runtime/settings/__init__.py` is the only way an
  environment variable name is derived for a setting. There are no
  hand-written env-name constants anywhere in the repository.
- `resolve_settings()` applies a fixed precedence:
  CLI override > environment/`.env` > stored config > default or default factory.
  A spec whose `validate` callback raises `ValueError` fails resolution rather
  than yielding an out-of-range value.
- `flatten_settings()` removes every spec marked `secret=True` before a resolved
  mapping is written into a manifest, provenance record, or log.
- `build_alternation()` in `regex/builder.py` orders branches by
  `(-word_count, -char_length)` by default, so a longer phrase is never
  shadowed by a shorter one that is a prefix of it.
- Scanners are deterministic and order-stable: `discover_python_files()` sorts
  its result, and `ALL_SCANNERS` is a fixed tuple, so two gate runs over the
  same tree print findings in the same order.
- Any scanner finding fails the gate. `checks.run_all()` returns `1` if
  **any** scanner reported at least one finding, and `check.py` calls
  `sys.exit(code)` on a non-zero result.

**Obligations callers place on this layer**

- Never write `os.environ` or `os.getenv` outside
  `edgar_sec/foundation/runtime/env.py`. The `environment-access` scanner
  reports a finding for any such line, exempting only `env.py`, `check.py`,
  `tests/`, and `foundation/scanners/`.
- Never hardcode a `".artifacts"` path literal outside a path resolver. The
  `artifact-paths` scanner exempts `runtime/paths.py`,
  `runtime/settings/paths.py`, and `check.py`, so those three modules are the
  only sanctioned places for the literal.
- Never hardcode `threads=`, `max_workers=`, or `memory_limit=`. The
  `resource-allocation` scanner exempts `runtime/resources.py`,
  `runtime/settings/`, `foundation/scanners/`, and `scratch/`.
- Never write a raw three-or-more-branch alternation literal such as
  `(?:alpha|beta|gamma)` or the quoted chain `'a|b|c|d'`. The
  `regex-alternations` scanner exempts exactly two path prefixes,
  `edgar_sec/foundation/regex/` and `edgar_sec/foundation/text/`, which is what
  keeps the DSL load-bearing rather than decorative.
- Never define a private month table or hand-write a date pattern. The
  `date-patterns` scanner exempts exactly one module,
  `edgar_sec/foundation/text/dates.py`.
- Do not import Layer 0 symbols from a barrel. Import from the leaf module.
- Lint suppression belongs in `ruff.toml`. The gate's own scanners do not read
  lint configuration, so a `# noqa` comment will not silence a policy finding.

**How the scanners are invoked**

Layer 0 has no entry point of its own. The scanners are driven from the
repository root by `python check.py`, which imports
`edgar_sec.foundation.checks.run_all` and exits with its return code. The
scanner step alone runs with `python check.py --scan`; `--fast` runs ruff format
check, ruff lint check, and the scanners but skips pytest. Exit behaviour:
`0` when every scanner is clean, otherwise the first non-zero subprocess return
code, or `1` when a scanner reported findings.

## Public surface

- `file_sha256` — streaming SHA-256 hex digest of a file in 64 KiB blocks. `hashing.py`.
- `sha256_bytes` — SHA-256 hex digest of raw bytes. `hashing.py`.
- `sha256_text` — SHA-256 hex digest of UTF-8 text. `hashing.py`. A second, 1 MiB-chunked `sha256_text` lives in `runtime/memory.py`; see "Deliberate gaps".
- `canonical_json` — deterministic JSON with sorted keys and compact separators. `serialization.py`.
- `canonical_hash` — SHA-256 of the canonical JSON encoding of a payload. `serialization.py`.
- `json_safe` — coerce a value into something `json.dumps` can encode: `Decimal` to its exact string, `bytes` to base64, non-finite floats to `None`, dates to ISO-8601, nested containers recursively. Lossy by design and carries no determinism guarantee. `serialization.py`.
- `safe_dumps` — `json.dumps` after `json_safe`, preserving insertion order. `serialization.py`.
- `validate_read_only` — return a single read statement or raise `SqlGuardError`. `sql/guard.py`.
- `ALLOWED_LEADING_KEYWORDS` — the console's verb allowlist, exported so the rule and its error message cannot drift. `sql/guard.py`.
- `registered()` — the `ALL_SCANNERS` tuple. `checks.py`.
- `run_all()` — execute every registered scanner, print findings, return `0` or `1`. `checks.py`.
- `ALL_SCANNERS` — the 11-entry registry tuple, in gate order. `scanners/__init__.py`.
- `Scanner` / `ScannerFinding` — the frozen dataclasses every scanner returns. `scanners/base.py`.
- `get_env` / `get_env_int` / `get_env_float` / `get_env_bool` / `load_dotenv` — the only sanctioned environment access. `runtime/env.py`.
- `resolve_paths` — derive `ProjectPaths` from a repo root or the CWD. `runtime/paths.py`.
- `derive_resources` — cgroup-aware `RuntimeResourceProfile`. `runtime/resources.py`.
- `auto_worker_count` / `available_memory_bytes` / `usable_memory_bytes` — memory-budget arithmetic. `runtime/resources.py`.
- `reclaim` — `gc.collect()` plus `malloc_trim(0)`. `runtime/memory.py`.
- `SettingSpec` / `resolve_settings` / `collect_specs` / `environment_name` / `flatten_settings` / `render_dotenv` — the settings registry API. `runtime/settings/__init__.py`.
- `build_alternation` / `build_compound` / `add_restrictions` / `build_regex` — the regex DSL. `regex/builder.py`.
- `compact_alternation` / `trie_to_regex` / `build_prefix_trie` / `TrieNode` — prefix-tree factorisation. `regex/trie.py`.
- `parse_date` / `SEC_DATE_FORMATS` / `MONTH_PATTERN` / `MONTH_NAMES` / `expand_2digit_year` / `extract_years` — the date vocabulary. `text/dates.py`.
- `tokenize` / `compile_lexical_matcher` / `LexicalMatcher` / `MultiPatternAutomaton` / `tier_confidence` — token-level multi-pattern matching. `text/automaton.py`.
- `sanitize_unicode_whitespace` / `collapse_whitespace` / `collapse_excessive_blank_lines` — Unicode and whitespace normalisation. `text/normalize.py`.
- `expand_alternations` / `expand_variants` / `expand_compounds` — phrase generation. `text/compounds.py`.

## Tests

Mirrored test paths under `tests/`:

- `tests/foundation/test_hashing.py`
- `tests/foundation/test_serialization.py`
- `tests/foundation/sql/test_guard.py`
- `tests/foundation/regex/test_builder.py`, `tests/foundation/regex/test_trie.py`
- `tests/foundation/runtime/test_env.py`, `test_memory.py`, `test_partitions.py`, `test_paths.py`, `test_resources.py`, `test_settings.py`
- `tests/foundation/scanners/test_scanners.py`, `test_lines.py`, `test_regex_alternations.py`, `test_legacy_shims.py`, `test_json_io.py`, `test_date_patterns.py`
- `tests/foundation/text/test_automaton.py`, `test_compounds.py`, `test_dates.py`, `test_grammar.py`, `test_normalize.py`, `test_patterns.py`, `test_tokens.py`

`tests/support.py` provides `load_fixture` / `fixture_path` and the offline test
doubles. The scanner tests build a synthetic repository tree under `tmp_path`
and `monkeypatch.chdir` into it, because `discover_python_files()` anchors on
`Path.cwd()`.

## Deliberate gaps

- **`checks.py` has no test module.** `edgar_sec/foundation/checks.py` is
  covered only indirectly, by `check.py --scan` runs. There is no
  `tests/foundation/test_checks.py`. This is an omission, not a decision.
- **`runtime/memory.sha256_text` has no callers.** Two functions named
  `sha256_text` exist. The one in `hashing.py` encodes the whole string at once;
  the one in `runtime/memory.py:49` streams 1 MiB chunks. Every one of the
  roughly twenty call sites in the repository imports the `hashing.py` version.
  The chunked variant is the memory-safe one and is the one AGENTS.md §2.5
  describes, so the description currently points at dead code. Callers handling
  multi-megabyte document text should import the `runtime.memory` variant
  instead; the duplicate should collapse to one implementation.
- **`runtime/resources.SystemResources` is a bare alias.**
  `SystemResources = RuntimeResourceProfile` (`resources.py:214`) is exported
  but referenced nowhere in `edgar_sec/` or `tests/`, and the `legacy-shims`
  scanner does not flag it, because its rule matches `_legacy*`/`_compat*`
  function names, `Legacy`/`Compat`/`Shim` class names, `legacy_`/`compat_`/
  `shim_` assignments, and compatibility *comments* — not a plain
  `Alias = ClassName` assignment. It is exactly the kind of shim AGENTS.md §1.1
  forbids, so it is recorded here rather than left to look intentional.
- **No packaging metadata.** There is no `pyproject.toml` and no console-script
  entry point. Everything is invoked as `python check.py`, `python run.py`, or
  `python -m edgar_sec.pipelines.<name>.operator`.
- **No logging configuration.** `RuntimeSettings.log_level` exists as a field
  with a default of `"INFO"`, but nothing in Layer 0 configures a logger. There
  is no logging setup module in this layer.
- **No concurrency primitives.** Layer 0 provides resource *budgeting*
  (`auto_worker_count`, `derive_resources`) but no pool, queue, executor, or
  async runtime. Process and thread management belongs to the layer that
  spawns workers.
- **Dropped from v1, by design.** The v1 system at `.v1/` carried
  `defs/runtime/artifacts.py`, `bundle.py`, `cli.py`, `config_io.py`,
  `registry.py`, and `settings_cli.py`. None of those were ported: argument
  registration, config persistence, and the launcher registry are the owning
  layers' concerns now, and a v2 config file is not read or written anywhere in
  `edgar_sec/foundation/`. See `runtime/settings/README.md` for what that means
  for `resolve_settings(config=...)`.
- **Not ported from v1 regex.** `defs/regex/formatting.py` and its
  `to_verbose_pattern` helper, which wrapped deep alternations across indented
  lines for `re.VERBOSE`, have no v2 counterpart. `foundation/regex/` is
  `builder.py` and `trie.py` only. The alternative is plain single-line
  patterns; nothing in v2 relies on `re.VERBOSE` formatting.
- **Not ported from v1 text.** `defs/text/healing/`, `defs/text/html/`,
  `defs/text/reflow/`, `defs/text/structure/logical_units.py`, and the
  `defs/text/reflow/tools/` analysis and clustering suites are not in
  `foundation/text/`. Where they survived the migration they moved up a layer:
  `engine/reflow/`, `engine/document/html.py` and `html_cleaner.py`,
  `engine/forms/checkmarks/`, `engine/document/signatures.py`. `LogicalUnit`
  classification and the clustering tooling have no v2 home. See
  `text/README.md`.
- **Scanner scope is Python source in two trees.** `discover_python_files()`
  walks `edgar_sec/` and `tests/` plus `check.py` and `run.py`, skipping
  dot-prefixed path components. Nothing in `roadmap/`, `ruff.toml`, CI
  configuration, or dependency manifests is scanned.
