# `edgar_sec/foundation/scanners` — the policy scanner registry

A rule stated in prose erodes, because the cost of ignoring it is invisible until
the damage is. This package turns the repository's structural rules into AST and
text scanners that run on every `check.py` invocation, so a violation fails the
build instead of being noticed later. It is not a linter and not a formatter: ruff
handles style, and this package handles architecture.

`AGENTS.md` §5 lists the registered rules and what each one enforces. Each scanner
carries its own exemptions inline, so the rule a scanner enforces and the files it
cannot apply to stay one edit in one place. There is no configuration file here: a
line that trips a scanner can only be silenced by changing the scanner.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `base.py` | `Scanner` and `ScannerFinding`. |
| `files.py` | `discover_python_files()`. |
| `lines.py` | The shared line-oriented rule driver and its helpers. |
| `__init__.py` | Binds `ALL_SCANNERS`. |
| `environment.py`, `artifact_paths.py`, `secrets.py`, `clean_exit.py`, `length.py`, `layers.py`, `resources.py`, `whole_file_read.py`, `regex_alternations.py`, `legacy_shims.py`, `json_io.py`, `date_patterns.py` | One scanner per module. |

`ALL_SCANNERS` is a true dynamic registry, which `AGENTS.md` §1.2 permits where a
barrel re-export is banned. Its order is the order
`edgar_sec.foundation.checks.runner.run_all()` executes the scanners in.

## Contracts

**Guarantees this package makes to its callers**

- `discover_python_files()` returns a **sorted** list of relative paths under
  `edgar_sec/` and `tests/`, plus `check.py` and `run.py` when present, skipping
  any dot-prefixed path component. Sorting is the contract: a gate whose output
  reshuffles between runs cannot be diffed against itself.
- Discovery is anchored on `Path.cwd()`, so the gate only sees the current tree.
- A file that cannot be read or decoded is skipped rather than failing the gate: a
  scanner that cannot decode a file has no opinion about its contents.
- The scanners and `tests/` are exempt from every text rule, so a test can assert
  on a violation without tripping the gate itself.
- Every finding is blocking: `run_all()` returns `1` if any scanner reported any,
  with no severity distinction between them.

Four behaviours are worth naming because they are not what the name implies.
`environment-access` matches raw line text, so `os.environ` inside a string or a
comment still trips it. `clean-exit` passes a file whose exits all sit inside its
main guard. `file-length` emits an advisory-sounding finding that blocks exactly
like a hard violation. `legacy-shims` reads comment lines on purpose, because a
shim is usually announced in prose rather than in code.

**Obligations callers place on this package**

- Run the gate from the repository root, because discovery is cwd-anchored.
- A new scanner means: a module in this package, an entry in `ALL_SCANNERS`, a
  mirrored `tests/foundation/scanners/test_<name>.py`, and a line in the
  `AGENTS.md` §5 list.
- Do not raise a finding from a comment when the rule is about code. Turn off
  comment skipping only when the prose is the point.
- Do not add an exemption broad enough to neuter a rule. A rule that is only
  stated in prose exempts the module that owns the vocabulary, plus tests and the
  scanners themselves.
- A finding cannot be waived. There is no inline suppression and no configuration
  file; the only fix is to change the code or change the scanner, in the diff.

## Command surface

This package has no command of its own. The scanner step runs from the repository
root, where `check.py` imports `run_all`, prints each scanner's name, description,
and findings, and exits non-zero when any scanner reported:

```bash
.venv/bin/python check.py           # ruff format check, ruff lint check, scanners, pytest
.venv/bin/python check.py --fast    # ruff format check, ruff lint check, scanners; skips pytest
.venv/bin/python check.py --scan    # registered scanners only
```

`check.py --fix` does not run the scanners at all.

## Public surface

- `ALL_SCANNERS` — the registry tuple, in gate order. `__init__.py`.
- `Scanner`, `ScannerFinding`. `base.py`.
- `discover_python_files`. `files.py`.
- `scan_text_rule` and its helpers. `lines.py`.
- `registered()`, `run_all()`. `edgar_sec/foundation/checks/runner.py`.

## Mirrored tests

[`tests/foundation/scanners/`](../../../tests/foundation/scanners/), plus
`tests/foundation/checks/test_runner.py` for the runner's return contract.

## Deliberate gaps

- **No auto-fix.** Every scanner reports and stops; `check.py --fix` runs ruff only.
- **No severity model.** `file-length` reads as advice in `AGENTS.md` §5 and its
  hint says "consider refactoring", but in practice it blocks the gate exactly as a
  hard violation does. Either the rule or the wording should change.
- **No suppression mechanism.** No `noqa` equivalent, no allowlist file, no
  per-line pragma. A false positive has to be fixed by editing the scanner.
- **`layer-boundary` is the only AST scanner.** Third-party and standard-library
  imports are out of scope, as is any dynamic import via `importlib` or
  `__import__`; relative upward imports *are* resolved, so both spellings are
  reported alike. A file that fails to parse is skipped silently. The line- and
  regex-oriented scanners can be evaded by constructing a violation across lines.
- **Discovery covers two trees and two root files.** Nothing in `roadmap/`,
  `ruff.toml`, CI configuration, dependency manifests, or documentation is
  scanned, so a secret or a hardcoded limit committed outside those paths is
  invisible. There is also no file-content, git-history, or runtime scanning: a
  committed `.env` or a secret in a commit is not detected.
- **`secrets-leakage` has a narrow signature set.** A credential in a JSON
  fixture, a URL query parameter, or a base64 blob is not detected, and any
  finding naming an email address is reported regardless of whether it is a real
  credential.
