# `edgar_sec/foundation/scanners` — the policy scanner registry that enforces `AGENTS.md`

A rule stated in prose erodes, because the cost of ignoring it is invisible until
the damage is. This package turns the repository's structural rules into twelve
AST and text scanners that run on every `check.py` invocation, so a violation
fails the build instead of being noticed later. It is not a linter and not a
formatter: ruff handles style, and this package handles architecture.

## Purpose

The twelve registered scanners cover the rules in `AGENTS.md` that ruff cannot
see: which modules may import which layers, where environment variables may be
read, where a path literal may appear, whether a resource budget is hardcoded,
and whether a stated rule is actually enforced.

Four of them — `regex-alternations`, `legacy-shims`, `json-io`, and
`date-patterns` — exist specifically to keep a *stated* rule enforced. Each
points at infrastructure the repository already ships: the regex builder DSL, the
zero-shims rule, `foundation.serialization.canonical_json` with
`infra.storage.atomic.atomic_write_json`, and `foundation.text.dates`. A rule
with no scanner erodes silently; these four were the ones that had drifted.

Not a linter with configuration: there is no `ruff.toml`-style file here. Each
scanner hardcodes its own thresholds and exemptions, and a line that trips a
scanner can only be silenced by changing the scanner.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `base.py` | `Scanner` and `ScannerFinding`, the two frozen dataclasses everything returns. |
| `files.py` | `discover_python_files()`: sorted, cwd-anchored file discovery. |
| `lines.py` | `scan_text_rule`, `is_noise`, `is_scanner_infrastructure`, `matches_allowed`, `iter_source_lines`, `finding`, `Rule`. |
| `__init__.py` | Imports the twelve `SCANNER` objects and binds `ALL_SCANNERS`. |
| `environment.py` | `environment-access`. |
| `paths.py` | `artifact-paths`. |
| `secrets.py` | `secrets-leakage`. |
| `clean_exit.py` | `clean-exit`. |
| `length.py` | `file-length`. |
| `layers.py` | `layer-boundary`. |
| `resources.py` | `resource-allocation`. |
| `whole_file_read.py` | `whole-file-read`. |
| `regex_alternations.py` | `regex-alternations`. |
| `legacy_shims.py` | `legacy-shims`. |
| `json_io.py` | `json-io`. |
| `date_patterns.py` | `date-patterns`. |

`__init__.py` is the one file in the repository that binds a tuple of imported
symbols. AGENTS.md §1.2 permits this explicitly, because `ALL_SCANNERS` is a
true dynamic registry rather than a barrel re-export.

## The twelve registered scanners

`ALL_SCANNERS` in `__init__.py` binds these in this order, and that order is the
order `checks.runner.run_all()` executes them in.

| # | Name | Rule | Pattern owner(s) exempted |
| :--- | :--- | :--- | :--- |
| 1 | `environment-access` | No line may contain `os.environ` or `os.getenv`. | `edgar_sec/foundation/runtime/env.py`, `check.py`, `tests/`, anything containing `scanners/` |
| 2 | `artifact-paths` | No line may contain a `".artifacts` or `'.artifacts` literal. | `edgar_sec/foundation/runtime/paths.py`, `edgar_sec/foundation/runtime/settings/paths.py`, `check.py`, `tests/`, anything containing `scanners/` |
| 3 | `secrets-leakage` | Three regexes: `api_key`/`secret`/`password`/`token` assigned a 16+ char literal, a `ghp_` token, or a `sec-contact: ...@host.tld` credential. | `tests/`, anything containing `scanners/` |
| 4 | `clean-exit` | No `sys.exit(` or bare `exit(` in library code. | `check.py`, `run.py`, `tests/`, anything containing `scanners/`, any path ending `cli.py` or `operator.py` |
| 5 | `file-length` | A file over 800 lines produces a finding. | `tests/` |
| 6 | `layer-boundary` | An AST walk forbids importing a strictly higher layer. | none |
| 7 | `resource-allocation` | No `threads=`, `max_workers=`, or `memory_limit=` with a literal value. | `runtime/resources.py`, `runtime/settings/`, `foundation/scanners/`, `scratch/`, and any test path |
| 8 | `whole-file-read` | No `read_bytes()` whose value reaches a digest constructor on the same line. | `edgar_sec/foundation/scanners/`, `edgar_sec/foundation/hashing.py`, and any test path |
| 9 | `regex-alternations` | No raw 3+ branch alternation group and no quoted 4+ token pipe chain. | `edgar_sec/foundation/regex/`, `edgar_sec/foundation/text/`, `tests/`, anything containing `scanners/` |
| 10 | `legacy-shims` | No compatibility-alias identifiers, compatibility comments, or bare `Alias = ClassName` binding. | `check.py`, `run.py`, `tests/`, anything containing `scanners/` |
| 11 | `json-io` | No redefinition of a shared JSON helper, and no non-atomic JSON write. | `edgar_sec/foundation/serialization.py`, `edgar_sec/infra/storage/atomic.py`, `tests/`, anything containing `scanners/` |
| 12 | `date-patterns` | No private month table, month sequence, month alternation, or hand-written date separator pattern. | `edgar_sec/foundation/text/dates.py`, `tests/`, anything containing `scanners/` |

Details worth stating, because they are not what the name implies:

- **`environment-access` is a substring match, not an AST match.** It flags any
  line whose text contains `os.environ` or `os.getenv`, including inside a string
  or a comment.
- **`clean-exit` accepts exits confined to a main guard.** If a file's every
  `sys.exit`/`exit(` call sits at or below its `if __name__ == "__main__":`
  line, the file passes. Any exit above the guard is still a finding.
- **`file-length` "advises" but fails the gate.** `length.py` emits a normal
  `ScannerFinding`, and `checks.runner.run_all()` treats any finding as an error
  and returns `1`. There is no warning severity, so the advice in AGENTS.md §5 is
  blocking, not advisory. No discovered file currently exceeds the 800-line
  threshold; the largest is `edgar_sec/engine/reflow/rules/cascades.py` at 791
  lines, so the margin is about nine lines.
- **`resource-allocation` skips comment and docstring lines** before matching,
  and exempts anything whose path looks like a test (`tests/`, `/tests/`,
  `/test_`, `_test.py`), not just `tests/`.
- **`whole-file-read` is deliberately narrow.** The pattern requires a digest
  constructor and `.read_bytes()` on the same line, so a hash three statements
  away cannot borrow the read, and a `read_bytes()` feeding `json.loads` is not
  flagged.
- **`regex-alternations` builds its own detectors with the DSL it protects.**
  `_GROUP_ALTERNATION`, `_QUOTED_PIPE_CHAIN`, `_RAW_ALTERNATION_RE`, and
  `_PIPE_CHAIN_CORE` are all assembled through `build_compound` and
  `build_alternation` from `foundation/regex/builder.py`. A line containing a
  call to `build_alternation`, `build_compound`, or `compact_alternation` is
  skipped outright before the pattern is tested.
- **`legacy-shims` reads comments, on purpose.** It passes `skip_noise=False`,
  because a shim is usually announced in a comment rather than in code. It
  matches six comment terms (`backward`/`backwards compatibility`,
  `compatibility`, `legacy`, `kept for compatibility`, `transitional shim`,
  `deprecated`), identifier shapes (`def _legacy*`/`_compat*`/`_shim*`,
  `class Legacy*`/`Compat*`/`Shim*`, and `legacy_*`/`compat_*`/`shim_*`
  assignments), and a module-level `Alias = ClassName` binding of two distinct
  single identifiers.
- **`json-io` distinguishes two failure modes.** Redefining `canonical_json`,
  `_canonical_json`, `json_canonical`, or `_load_json` is one finding; a
  `json.dump(x, fh)` or a `path.write_text(json.dumps(...))` is another, because
  a crash can leave a truncated artifact.
- **`date-patterns` derives its month vocabulary from the module it protects.**
  It imports `MONTH_PATTERN` from `edgar_sec/foundation/text/dates.py` and uses
  it to build the detector, then exempts that one file.

## Contracts

**Guarantees this package makes to its callers**

- `discover_python_files()` returns a **sorted** list of relative paths under
  `edgar_sec/` and `tests/`, plus `check.py` and `run.py` when present, skipping
  any path with a dot-prefixed component. Sorting exists so findings are reported
  in the same order on every machine; `Path.rglob` yields filesystem order, and a
  gate whose output reshuffles cannot be diffed against itself.
- Discovery is anchored on `Path.cwd()`, not on a discovered repository root.
  The gate therefore only sees the current tree.
- A file that cannot be read or decoded is skipped, not fatal. A scanner that
  cannot decode a file has no opinion about its contents.
- `scan_text_rule(rule, prefixes=(), skip=(), skip_noise=True)` is the shared
  driver. `prefixes` exempts the modules that own a vocabulary; `skip` exempts
  individual files; `skip_noise` drops comment and docstring-delimiter lines.
- `is_scanner_infrastructure(path)` exempts anything containing
  `foundation/scanners/` and anything starting with `tests/`, for every
  text-based rule. Scanners must spell out the patterns they detect, and tests
  must be able to assert on a violation without tripping the gate.
- `finding(...)` always tags `source="static"`.
- Every finding is blocking. `edgar_sec/foundation/checks/runner.py` prints each
  one and returns `1` if any scanner reported any.

**Obligations callers place on this package**

- Run the gate from the repository root, because discovery is cwd-anchored.
- A new scanner means four things: a module in `foundation/scanners/`, an entry
  in `ALL_SCANNERS`, a mirrored `tests/foundation/scanners/test_<name>.py`, and a
  line in the AGENTS.md §5 list.
- Do not raise a finding from a comment when the rule is about code; use
  `skip_noise=True` (the default). Turn it off only when the prose is the point.
- Do not add an exemption broad enough to neuter a rule. The four most recent
  scanners each exempt exactly the module that owns the vocabulary, plus tests
  and the scanners themselves.
- A finding cannot be waived. There is no `noqa`-equivalent, no inline
  suppression, and no configuration file; the only fix is to change the code or
  change the scanner, deliberately and in the diff.

**How the scanners are invoked**

This package has no command of its own. The scanner step runs from the
repository root:

```bash
.venv/bin/python check.py           # ruff format check, ruff lint check, scanners, pytest
.venv/bin/python check.py --fast    # ruff format check, ruff lint check, scanners; skips pytest
.venv/bin/python check.py --scan    # registered scanners only
```

`check.py` imports `edgar_sec.foundation.checks.runner.run_all`, prints each
scanner's name, description, and findings, and calls `sys.exit(code)`. Exit
behaviour: `0` when every scanner is clean, otherwise `1` when a scanner reported
findings. `check.py --fix` does not run the scanners at all.

## Public surface

- `ALL_SCANNERS` — the twelve-entry registry tuple, in gate order. `__init__.py`.
- The twelve per-scanner aliases `ENV_SCANNER`, `PATHS_SCANNER`, `SECRETS_SCANNER`, `CLEAN_EXIT_SCANNER`, `LENGTH_SCANNER`, `LAYERS_SCANNER`, `RESOURCES_SCANNER`, `WHOLE_FILE_READ_SCANNER`, `REGEX_ALTERNATIONS_SCANNER`, `LEGACY_SHIMS_SCANNER`, `JSON_IO_SCANNER`, `DATE_PATTERNS_SCANNER`. `__init__.py`.
- `Scanner` — frozen dataclass of `name`, `description`, `run`. `base.py`.
- `ScannerFinding` — frozen dataclass of `scanner`, `source`, `path`, `line`, `message`, `hint`. `base.py`.
- `registered()` — the `ALL_SCANNERS` tuple. `edgar_sec/foundation/checks/runner.py`.
- `run_all()` — run every scanner, print findings, return `0` or `1`. `edgar_sec/foundation/checks/runner.py`.
- `discover_python_files`. `files.py`.
- `scan_text_rule` / `finding` / `is_noise` / `is_scanner_infrastructure` / `matches_allowed` / `iter_source_lines` / `Rule` — the text-scanner driver and helpers. `lines.py`.
- Per-scanner `scan_*` functions: `scan_environment_access`, `scan_artifact_paths`, `scan_secrets_leakage`, `scan_clean_exit`, `scan_file_length`, `scan_layer_boundary`, `scan_resource_allocations`, `scan_whole_file_reads`, `scan_regex_alternations`, `scan_legacy_shims`, `scan_json_io`, `scan_date_patterns`.

## Tests

- `tests/foundation/scanners/test_scanners.py` — behavioural tests for `clean_exit`, `environment`, `layers`, `length`, `paths`, and `secrets`, built against a synthetic repository tree under `tmp_path` with `monkeypatch.chdir`.
- `tests/foundation/scanners/test_lines.py` — the shared text-rule driver.
- `tests/foundation/scanners/test_regex_alternations.py`
- `tests/foundation/scanners/test_legacy_shims.py`
- `tests/foundation/scanners/test_json_io.py`
- `tests/foundation/scanners/test_date_patterns.py`
- `tests/foundation/scanners/test_whole_file_read.py`
- `tests/foundation/checks/test_runner.py` — `registered()` and `run_all()`'s return contract.

There are no dedicated test modules for `base.py`, `files.py`, or
`resources.py`; those are covered only by the gate itself running over the real
tree.

## Deliberate gaps

- **No auto-fix.** Every scanner reports and stops. There is no
  `check.py --fix`-equivalent for a policy finding, and AGENTS.md says `--fix`
  runs ruff only.
- **No severity model.** `ScannerFinding` has no severity field and
  `run_all()` treats all findings identically. `file-length` is described in
  AGENTS.md §5 as advising, and its hint reads "Consider refactoring", but in
  practice it blocks the gate exactly as a hard violation does. Either the rule
  or the wording should change.
- **No suppression mechanism.** No `# noqa` equivalent, no allowlist file, no
  per-line pragma. A false positive has to be fixed by editing the scanner.
- **`layer-boundary` only checks internal imports.** Third-party and standard
  library imports are out of scope, as is any dynamic import via `importlib` or
  `__import__`. It also skips files that fail to parse, silently. Relative
  upward imports *are* resolved, via `_resolve_relative`, so the absolute and
  relative spellings are reported alike.
- **Discovery covers two trees and two root files.** `edgar_sec/`, `tests/`,
  `check.py`, and `run.py`. Nothing in `roadmap/`, `.v1/`, `ruff.toml`, CI
  configuration, dependency manifests, or documentation is scanned. Secrets and
  resource limits committed outside those paths are invisible. One consequence
  worth naming: the `scratch/` entry in `resource-allocation`'s `_ALLOWED_PATHS`
  is unreachable, because `discover_python_files()` never walks that directory
  and no such directory exists in the tree.
- **No file-content, git-history, or runtime scanning.** Everything is static
  source text. There is no check for a committed `.env`, an artifact in the
  tree, or a secret in a commit.
- **`layer-boundary` is the only AST scanner; the other eleven are line- or
  regex-oriented.** A violation constructed across lines by string concatenation
  or variable indirection evades the line-based ones.
- **`secrets-leakage` has a narrow signature set.** Three patterns cover
  assignment-style credentials, GitHub personal access tokens, and
  `sec-contact:` email identities. A credential in a JSON fixture, a URL query
  parameter, or a base64 blob is not detected, and any finding naming an email
  address is reported regardless of whether it is a real credential.
- **`length.py` and `resources.py` have no behavioural tests.** Both are
  exercised only by the gate running over the real tree, which is a weaker signal
  than a synthetic-tree assertion.