# Foundation Checks & Test Lineage (`edgar_sec.foundation.checks`)

Gate runners, git-aware change detection, and AST lineage resolution for targeted
test execution.

---

## Module Layout & Responsibilities

| Module | Responsibility |
| :--- | :--- |
| [`runner.py`](runner.py) | Scanner gate runner: runs every registered scanner, prints findings, returns `0` or `1`. |
| [`git_diff.py`](git_diff.py) | Working-tree change detection via `git status --porcelain=v1`, categorised into sources, tests, conftests, root configs, and docs/assets. |
| [`lineage.py`](lineage.py) | Static AST import analysis with `mtime_ns` caching, relative-import canonicalisation, reverse-BFS transitive closure, and conftest invalidation scoping. |

---

## Guaranteed Contracts

1. **Deterministic & dependency-free**: standard library only (`ast`, `pathlib`,
   `json`, `subprocess`).
2. **Layer 0**: imports only from `foundation.scanners` and
   `foundation.runtime.paths`, enforced by the `layer-boundary` scanner.
3. **Transient cache isolation**: the dep graph lives in
   `.artifacts/transient/cache/dep_graph.json`, written by atomic rename from a
   `.tmp` sibling, so it never dirties the git tree.
4. **Test selection is derived purely from the working tree**: direct test edits,
   0-hop mirrors, conftest scope, and the reverse import closure. A source change
   to `check.py` selects all of `tests/foundation/checks/`.
5. **Cache staleness is bounded**: entries are keyed on `mtime_ns`, evicted when
   their file disappears from a full-tree scan, and discarded wholesale on a
   version mismatch or unreadable payload.

---

## Public Surface

```python
from edgar_sec.foundation.checks.runner import registered, run_all
from edgar_sec.foundation.checks.git_diff import (
    GitStatusSnapshot,
    get_git_status,
    parse_porcelain_output,
)
from edgar_sec.foundation.checks.lineage import (
    LineageGraph,
    TestSelectionResult,
    find_mirror_test,
    path_to_module,
    resolve_relative_import,
)
```

---

## Command Surface

None. `check.py` at the repository root imports
`edgar_sec.foundation.checks.runner.run_all` and exits on its return code.

---

## Mirrored Tests

- [`tests/foundation/checks/test_runner.py`](../../../tests/foundation/checks/test_runner.py)
- [`tests/foundation/checks/test_git_diff.py`](../../../tests/foundation/checks/test_git_diff.py)
- [`tests/foundation/checks/test_lineage.py`](../../../tests/foundation/checks/test_lineage.py)

---

## Deliberate Gaps

- **Module-level lineage only.** Dependency tracking is per `.py` file, not per
  function or symbol. Module granularity is conservative and avoids brittle
  dynamic attribute resolution.
- **Non-code changes bypass pytest.** `GitStatusSnapshot.is_docs_or_assets_only`
  lets `check.py` skip the test stage entirely when no executable Python or
  shell file changed.
- **`NON_CODE_EXTENSIONS` is not consulted by any classifier.** The constant is
  exported and documented here, but `is_docs_or_assets_only` decides from `.py`
  and `.sh` suffixes instead. Treat the extension set as dead weight rather than
  as the rule.
- **No partial-file or diff-hunk granularity.** Selection is per file; editing
  one function in a large module still selects that module's mirror test and
  every dependent.
