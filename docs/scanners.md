# Registered Policy Scanners

The catalog of the repository's registered policy scanners. `AGENTS.md`
points here for the per-scanner rules; this file is their authority.

Scanners are defined modularly in `edgar_sec/foundation/scanners/` and collected via `ALL_SCANNERS`:

- `environment-access`: Bans direct `os.environ` / `os.getenv` outside `edgar_sec.foundation.runtime.env`.
- `artifact-paths`: Bans hardcoded `".artifacts"` path literals outside path resolvers.
- `test-tree-paths`: Bans `tests` path components and `tests` imports in layers 0–5, exempting only the gate machinery that owns the test tree (`foundation/checks`, the scanners) and the tools layer. No file exemptions: production-consumed data lives in the package or the workspace, never under `tests/`.
- `secrets-leakage`: Bans committed API keys, tokens, or credentials.
- `clean-exit`: Bans `sys.exit()` in library modules (only allowed in `run.py`, `check.py`, and CLI entrypoints).
- `file-length`: **Fails the gate** on files exceeding the line limit (800) to prevent monolithic growth. Any finding from any scanner returns a nonzero exit code, so "advisory" is not how it behaves.
- `layer-boundary`: Enforces strict downward-only import hierarchy.
- `resource-allocation`: Bans hardcoded thread counts or memory limits in pipeline/engine code.
- `batch-defaults`: Enforces ownership of shared chunk, read, SQL-insert, Parquet, document payload, and I/O buffer defaults; it flags duplicate symbol definitions and governed literals at identified call sites while allowing equal numbers used for distinct policies.
- `whole-file-read`: Bans `read_bytes()` consumed by a digest constructor. Hashing a whole
  artifact to prove it intact materializes the file; use `file_sha256`. Narrow on purpose —
  a `read_bytes()` feeding `json.loads` on a small payload is a different trade and is not flagged.
- `uncompiled-regex`: Bans uncompiled `re.search`/`match`/`findall`/`finditer`/`split`/
  `sub`/`subn`/`fullmatch` calls. Compile the pattern once into a module-level constant
  and call its method instead.
- `prose-length`: **Fails the gate** on a docstring or comment block over its cap. Enforces the
  prose caps (see the comments-and-docstrings binding in `AGENTS.md`), with tighter caps for tests.
- `regex-alternations`: Bans hand-crafted 3+ branch alternation literals, so `foundation.regex.builder` is used.
- `sha256-validation`: Bans duplicate SHA-256 string validation (regex, length/all, or letters in a set) outside `foundation.hashing.is_sha256_hex_digest`; SQL validation is not scanned.
- `legacy-shims`: Bans backward-compatibility aliases and transitional shims (enforces the no-shims rule).
- `json-io`: Bans redundant JSON helper definitions and non-atomic JSON writes.
- `date-patterns`: Bans private month tables and hand-crafted date patterns.
- `sql-interpolation`: Bans SQL assembled from unescaped values at a query sink. It
  inspects the argument of `execute` / `executemany` / `executescript` and reports an
  f-string, `%`, or `+` that interpolates a value which did not reach the statement
  through `infra.storage.duckdb.sql_literal` / `sql_path_list` / `sql_identifier`, a
  constant, or a local derived from those. A bound parameter is never a finding, and a
  module that composes SQL at a sink must be declared in `_SQL_COMPILER_PATHS` — an
  audited list, each entry recording why its interpolated values are safe.
- `string-lookup`: Bans semantic string searches over XBRL concept names in
  `engine/xbrl` and `apps/client`: `startswith`/`endswith`/`find`/`index` on a
  qname or local-name expression, and any consumption of a `residuals` attribute
  outside its sanctioned homes (normalize, the concept table, the tokenizer's
  ordering, discovery mining, `facts.py` carriage). Equivalence is computed from
  atom coordinates; residuals are a vocabulary-gap report, never a decision
  input. The Atom constructor's own symbol-prefix normalization is exempt.
- `form-vocabulary`: Bans private CUSIP regexes outside `engine/forms/common/entities.py`,
  DOM table markup regexes outside legacy ASCII table unwrappers, and duplicate unit
  suffix literals outside `engine/forms/common/numbers.py`.
- `sec-surface`: Bans SEC URL shapes constructed anywhere in the codebase that the
  `domain/sec_urls.py` rule table cannot classify into a governed surface, and any
  classified or builder-named surface with no freshness-policy row in the SEC settings
  provider. The URL module owns the rule table (read statically, so the gate and the
  runtime classifier cannot drift); the exhibits coverage registry's provenance
  citations are exempt because they are never fetched.

> [!NOTE]
> `regex-alternations`, `legacy-shims`, `json-io`, and `date-patterns` exist to
> keep a rule *enforced* rather than merely *stated*.
> Each points at infrastructure the repository already ships — the regex builder
> DSL, the "zero shims" rule, `foundation.serialization.canonical_json`,
> `infra.storage.atomic.atomic_write_json`, and `foundation.text.dates`. A rule
> with no scanner erodes, because the cost of ignoring it is invisible until the
> damage is. Each exempts only the module that owns the vocabulary, plus tests
> and the scanners themselves.
