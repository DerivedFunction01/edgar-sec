"""Scanner enforcing docstring and comment length caps."""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

_MODULE_CAP = 4
_DEF_CAP = 3
_COMMENT_CAP = 3

_TEST_MODULE_CAP = 3
_TEST_DEF_CAP = 2
_TEST_COMMENT_CAP = 2

_EXEMPT: dict[str, tuple[int, ...]] = {
    # Module docstring is argparse `description=__doc__`, i.e. the --help text.
    "check.py": (1,),
}


def _is_test(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/")
    return normalized.startswith("tests/") or "/tests/" in normalized


def _is_opener(text: str) -> bool:
    return text.strip() in {'"""', "'''"}


def content_lines(source_lines: list[str], start: int, end: int) -> int:
    """Count non-blank prose lines in a docstring span, excluding delimiters."""
    span = source_lines[start - 1 : end]
    if len(span) == 1:
        return 1 if span[0].strip().strip('"').strip("'").strip() else 0
    total = 0
    for offset, text in enumerate(span):
        stripped = text.strip()
        if not stripped:
            continue
        if _is_opener(stripped) or (
            stripped.startswith(('"""', "'''")) and stripped.endswith(('"""', "'''"))
        ):
            continue
        total += 1
    return total


def _docstring_findings(path_str: str, source: str) -> list[ScannerFinding]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    source_lines = source.splitlines()
    test = _is_test(path_str)
    module_cap = _TEST_MODULE_CAP if test else _MODULE_CAP
    def_cap = _TEST_DEF_CAP if test else _DEF_CAP
    exempt_lines = _EXEMPT.get(path_str.replace("\\", "/"), ())

    findings: list[ScannerFinding] = []
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        start = first.lineno
        end = first.end_lineno or first.lineno
        count = content_lines(source_lines, start, end)
        if count <= (module_cap if isinstance(node, ast.Module) else def_cap):
            continue
        if start in exempt_lines:
            continue
        kind = "module" if isinstance(node, ast.Module) else type(node).__name__.lower()
        name = "<module>" if isinstance(node, ast.Module) else node.name
        cap = module_cap if isinstance(node, ast.Module) else def_cap
        findings.append(
            ScannerFinding(
                scanner="prose-length",
                source="static",
                path=path_str,
                line=start,
                message=f"{kind} docstring for {name} is {count} prose lines (cap {cap})",
                hint="Keep the conclusion; drop the derivation, or link the owning docstring.",
            )
        )
    return findings


def _comment_runs(source: str) -> list[tuple[int, int]]:
    """Return (first_line, count) for each run of adjacent standalone comments.

    A trailing comment labels the line it sits on, so it counts alone: a column of
    dict entries each naming an invisible character is not one prose block.
    """
    standalone: list[int] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if token.start[1] > 0:
            continue
        standalone.append(token.start[0])
    runs: list[tuple[int, int]] = []
    for line in standalone:
        if runs and line == runs[-1][0] + runs[-1][1]:
            first, count = runs[-1]
            runs[-1] = (first, count + 1)
        else:
            runs.append((line, 1))
    return runs


def _comment_findings(path_str: str, source: str) -> list[ScannerFinding]:
    cap = _TEST_COMMENT_CAP if _is_test(path_str) else _COMMENT_CAP
    findings: list[ScannerFinding] = []
    for line, count in _comment_runs(source):
        if count > cap:
            findings.append(
                ScannerFinding(
                    scanner="prose-length",
                    source="static",
                    path=path_str,
                    line=line,
                    message=f"comment run is {count} lines (cap {cap})",
                    hint="Keep the constraint; delete the narration around it.",
                )
            )
    return findings


def scan_prose_length() -> list[ScannerFinding]:
    """Report docstrings and comment runs exceeding their prose caps."""
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(_docstring_findings(path_str, source))
        findings.extend(_comment_findings(path_str, source))
    return findings


SCANNER = Scanner(
    name="prose-length",
    description="check docstring and comment length caps",
    run=scan_prose_length,
)
