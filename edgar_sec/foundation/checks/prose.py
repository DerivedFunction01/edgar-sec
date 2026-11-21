"""Comment- and docstring-only detection for changed Python files."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from edgar_sec.foundation.checks.git_diff import GitStatusSnapshot


class _DocstringStripper(ast.NodeTransformer):
    def _strip(self, node: ast.AST) -> ast.AST:
        body = node.body  # type: ignore[attr-defined]
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:]  # type: ignore[attr-defined]
        return self.generic_visit(node)

    visit_Module = _strip
    visit_FunctionDef = _strip
    visit_AsyncFunctionDef = _strip
    visit_ClassDef = _strip


def normalized_dump(source: str) -> str | None:
    """Dump an AST with docstrings removed, or None when the text does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    return ast.dump(_DocstringStripper().visit(tree))


def is_prose_only(baseline: str, current: str) -> bool:
    """True when the two sources differ only in comments, docstrings, or layout."""
    before = normalized_dump(baseline)
    after = normalized_dump(current)
    return before is not None and before == after


def _head_source(repo_root: Path, rel_path: str) -> str | None:
    """Read a path's committed baseline, or None when it has none to compare."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        return proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def prose_only_python_files(
    snapshot: GitStatusSnapshot, repo_root: Path
) -> frozenset[str]:
    """Changed Python files that are equivalent to their baseline once prose is removed.

    HEAD is the baseline, not the index, so a staged-but-reverted edit is also
    recognised as a no-op. Untracked files have no baseline and are never returned.
    """
    untracked = frozenset(snapshot.untracked_files)
    candidates = (
        *snapshot.python_sources,
        *snapshot.python_tests,
        *snapshot.changed_conftests,
    )
    prose: set[str] = set()
    for rel_path in candidates:
        if rel_path in untracked:
            continue
        baseline = _head_source(repo_root, rel_path)
        if baseline is None:
            continue
        try:
            current = (repo_root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if is_prose_only(baseline, current):
            prose.add(rel_path)
    return frozenset(prose)
