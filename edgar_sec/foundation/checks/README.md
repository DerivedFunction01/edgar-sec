# Foundation Checks & Test Lineage (`edgar_sec.foundation.checks`)

Gate runners, git-aware change detection, and AST lineage resolution for targeted
test execution.

---

## Contracts

- **Deterministic & dependency-free**: standard library only (`ast`, `pathlib`, `json`, `subprocess`).
- **Layer 0**: imports only from `foundation.scanners` and `foundation.runtime.paths`, enforced by the `layer-boundary` scanner.
- **Transient cache isolation**: the dep graph lives in `.artifacts/transient/cache/dep_graph.json`, written by atomic rename from a `.tmp` sibling, so it never dirties the git tree.
- **Test selection is derived purely from the working tree**: direct test edits, 0-hop mirrors, conftest scope, and the reverse import closure. A source change to `check.py` selects all of `tests/foundation/checks/`.
- **Cache staleness is bounded**: entries are keyed on `mtime_ns`, evicted when their file disappears from a full-tree scan, and discarded wholesale on a version mismatch or unreadable payload.
- **Prose edits never select tests**: A `.py` file whose change survives docstring-stripped AST comparison against `HEAD` unchanged — which is what a comment, docstring, or blank-line edit leaves — is dropped from the snapshot before any classifier runs, so it selects no mirror, no dependent, and no conftest subtree. Because `ruff format --check` and `ruff lint` always run over the whole target set, a prose edit is still verified for formatting and lint; only pytest selection is skipped.

The comparison is deliberately fail-safe: an untracked file, a path with no `HEAD` blob, undecodable text, or text that does not parse is reported as a logic change. `HEAD` rather than the index is the baseline, so a staged edit whose working tree was reverted is also recognised as a no-op.

---

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate Gaps

- **Module-level lineage only**: Dependency tracking is per `.py` file, not per function or symbol. Module granularity is conservative and avoids brittle dynamic attribute resolution.
- **A docstring is prose even when code reads it**: Stripping docstrings assumes no runtime consumer of `__doc__` — a doctest runner, a doc build, or a fixture that asserts on a docstring would not be re-run. The gate never collects doctests; if one is introduced, this filter must be revisited.
- **Non-code changes bypass pytest**: `GitStatusSnapshot.is_docs_or_assets_only` lets `check.py` skip the test stage entirely when no executable Python or shell file changed. It is evaluated *after* the prose filter, so prose-only edits are covered by the same skip.
- **`NON_CODE_EXTENSIONS` is not consulted by any classifier**: The constant is exported and documented here, but `is_docs_or_assets_only` decides from `.py` and `.sh` suffixes instead. Treat the extension set as dead weight rather than as the rule.
- **No per-function granularity**: Selection is still per file: rewriting one function in a large module selects that module's mirror test and every dependent. The prose filter removes a whole file's worth of false positives, not a subset.
- **Reordering top-level definitions counts as a logic change**: AST comparison is order-sensitive, so a pure code move still selects dependents.
