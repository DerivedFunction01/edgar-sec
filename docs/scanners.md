# Registered Policy Scanners

The catalog of the repository's registered policy scanners. `AGENTS.md`
points here for the per-scanner rules; this file is their authority.

Scanners are defined modularly in `edgar_sec/foundation/scanners/`. The
roster itself is owned by `ALL_SCANNERS` in
`edgar_sec/foundation/scanners/__init__.py` — the entries below are this
catalog's per-scanner rules for that roster, and a registered scanner
with no entry here is a catalog defect, not an unregistered scanner.

Roster: `ALL_SCANNERS` in `edgar_sec/foundation/scanners/__init__.py`:

One-home rule (normative for every scanner below): shared regexes, methods,
and helpers have one homed module per intent — extend the home, never define
locally. Date/datetime helpers have one shared home
(`edgar_sec/foundation/text/dates.py`). Enforcement is shape-based at the
gate: the per-family scanners (`pattern-registry`, `page-patterns`,
`helper-duplicates`, `date-patterns`, and their kin) flag the shape of a
private copy wherever it appears, not only a duplicated name.


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
- `date-patterns`: Bans private month tables, hand-crafted date patterns, and
  narrowed-year alternations (`(19|20)` / `(?:19|20)` century groups and
  `19\d{2}|20\d{2}`-style year alternations, in any digit spelling or as
  alternation-builder list items) outside `foundation/text/dates.py`, whose
  year patterns span the full 1900-9999 range. Year literals as data are not
  flagged; the rule targets regex pattern source.
- `pattern-registry`: The intent registry: each recognizer family has one home and
  one sanctioned export surface, recorded as a data table the scanner consumes
  (word token in `foundation/text/words.py`, full date, year, and month in
  `foundation/text/dates.py`, scale patterns in `engine/tables/patterns.py`,
  extraction normalisers in `extraction/core/text/normalize.py`, the classifier registry in
  `extraction/core/subjects/profiles.py`, work-item ids in
  `pipelines/table_classification/planner.py`); a new family is a new
  table row, not new rule code. Bans definitions of a family's names outside its
  home, with no exceptions — assignment detection is statement-level (a keyword
  argument inside brackets is a use, not a definition), and function names may
  register def-only — and bans the recognizer shapes themselves outside
  `foundation/text/dates.py`: a bare year recognizer (`\d{4}` as a standalone
  recognizer), a hard-coded consecutive-year vocabulary, a hand-crafted
  month-name alternation, an any-word month slot in a date pattern, and a
  private recomposition of `MONTH_PATTERN`. Allowlisted
  format shapes: SEC archive URLs, OMB numbers, phone and ZIP+4 tails,
  ISO/compact archive, feed, and version date formats, filename numbering, and
  the signer-name termination slot; corpus tools are in scope.
- `money-patterns`: Bans private money-amount recognizers (loose amount cores,
  comma-grouped figures, and decimal figures spelled as pattern text) outside
  `engine/tables/numeric_cells.py`, private scale vocabularies (scale-word
  alternations and `in <scale>` labels) outside `engine/tables/patterns.py`,
  and private percent recognizers (digit cores with a `%` tail and
  percent-sign alternations) outside `engine/forms/common/values/numbers.py`.
- `page-patterns`: Bans private page-reference cores (plain, page-no., and letter-dash forms as spelled in pattern source) outside `foundation/text/patterns.py`, the page-reference vocabulary's one home; page-marker extraction shapes (page N of M, whole-line page labels, optional-prefix line classifiers, compositions over the home's fragments) are not flagged.
- `period-patterns`: Bans private period-phrase recognizers outside `foundation/text/dates.py`, private total-row recognizers outside `engine/tables/extraction/core/typed_rows.py`, private whitespace-collapse literals outside `foundation/text/patterns.py` and `foundation/text/normalize.py`, and private table-tag recognizers outside `foundation/text/patterns.py`.
- `helper-duplicates`: Bans function bodies duplicated across modules or against the scaffold and operator-kit homes, and private parameterized-get helpers (`return x.get("<key>", {})`) outside `engine/forms/common/scaffold/family_scaffold.py`.
- `identifier-patterns`: Bans private identifier recognizers (accession cores and digits, CIK member names, commission file caption/number, EIN, registration-number values, CUSIP value class) outside `domain/identity.py`, `engine/forms/common/identity/entities.py`, and `pipelines/metadata_sync/paths.py`; SQL regexp literals, SEC URL paths, and the sanctioned divergences are allowed.
- `refcell-patterns`: Bans private note/item/part reference cores (caption cores as spelled in pattern source) outside `engine/tables/toc/patterns.py`, the reference vocabulary's one home; slot prefixes, boundary terms, item ranges, and the full `[IVXLCDM]` PART composition are not flagged.
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
- `form-isolation`: Bans hardcoded SEC form-type literals — quoted form
  names and `form ==` comparisons — in generic code, so form-specific
  code stays confined to the form packages (`edgar_sec/domain/forms/`,
  the form-specific `engine/forms/` packages, and their tests).
- `form-vocabulary`: Bans private CUSIP regexes outside `engine/forms/common/identity/entities.py`,
  DOM table markup regexes outside legacy ASCII table unwrappers, and duplicate unit
  suffix literals outside `engine/forms/common/values/numbers.py`.
- `sec-surface`: Bans SEC URL shapes constructed anywhere in the codebase that the
  `domain/sec_urls.py` rule table cannot classify into a governed surface, and any
  classified or builder-named surface with no freshness-policy row in the SEC settings
  provider. The URL module owns the rule table (read statically, so the gate and the
  runtime classifier cannot drift); the exhibits coverage registry's provenance
  citations are exempt because they are never fetched.
- `tables-form-literals`: Bans quoted form-type literals under `engine/tables`, so the
  classifier layer stays form-agnostic by gate: form enters only as detected context
  data and per-form differences are family-profile data. Exhibit-type data and
  stratum codes are not form types and are allowed.

> [!NOTE]
> `regex-alternations`, `legacy-shims`, `json-io`, and `date-patterns` exist to
> keep a rule *enforced* rather than merely *stated*.
> Each points at infrastructure the repository already ships — the regex builder
> DSL, the "zero shims" rule, `foundation.serialization.canonical_json`,
> `infra.storage.atomic.atomic_write_json`, and `foundation.text.dates`. A rule
> with no scanner erodes, because the cost of ignoring it is invisible until the
> damage is. Each exempts only the module that owns the vocabulary, plus tests
> and the scanners themselves.
