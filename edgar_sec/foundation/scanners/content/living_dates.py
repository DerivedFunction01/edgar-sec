"""Scanner banning dates in living documents and code comments.

Flags date forms in doc lines, Python and script comments and docstrings,
and config-file comments; dates as data pass (literals, fixtures, specimen
corpora, masked doc code). Exemptions: the date home, sanctioned sites.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from edgar_sec.foundation.text.dates import MONTH_PATTERN

from ..base import Scanner, ScannerFinding
from ..files import tracked_paths
from ..lines import finding

DOC_SUFFIXES = (".md",)
PYTHON_SUFFIXES = (".py",)
SCRIPT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
SCAN_SUFFIXES = DOC_SUFFIXES + PYTHON_SUFFIXES + SCRIPT_SUFFIXES
CONFIG_SUFFIXES = (".toml", ".yaml", ".yml", ".cfg", ".ini")
CONFIG_NAMES = frozenset({".gitignore"})
ALL_SUFFIXES = SCAN_SUFFIXES + CONFIG_SUFFIXES

# Markdown under these prefixes is a specimen or fixture corpus —
# source material quoted as data, not a living document.
DOC_EXCLUDED_PREFIXES = ("uploads/", "tests/fixtures/")

# The module that owns the date vocabulary states date shapes as
# its content; it is exempt by the one-home rule.
VOCABULARY_HOME = "edgar_sec/foundation/text/dates.py"

# Sanctioned sites: content-bearing specimens and record pointers
# whose date is the content documented, excused by file and fragment.
_SANCTIONED_SITES: tuple[tuple[str, str], ...] = (
    ("edgar_sec/engine/document/page_markers/eligibility.py", "April 27, 2015"),
    ("edgar_sec/engine/document/page_markers/eligibility.py", "DECEMBER 31, 2025"),
    ("edgar_sec/engine/forms/earnings/README.md", "2026-11-08-table-taxonomy-measurement.md"),
    ("edgar_sec/domain/forms/families/current/taxonomy.py", "2026-11-08-sixk-census.md"),
    ("edgar_sec/tools/measurement/measurement.py", "2026-11-14-greenfield-step2a/taxonomy.json"),
    ("edgar_sec/tools/fixtures/fixture_planning.py", "2026-11-01-xbrl-package-presence.md"),
    ("edgar_sec/pipelines/datasets/README.md", "2026-11-08-bdc-ic-dataset-probe.md"),
    (
        "edgar_sec/tools/table_extraction_corpus/README.md",
        "2026-11-08-table-extraction-successor.md",
    ),
    ("edgar_sec/engine/tables/extraction/vetoes/term_vetoes.py", "2026-11-16-greenfield-step6-v2-"),
    ("edgar_sec/engine/xbrl/review/census_expectations.py", "2026-11-01-derivation-direction-fix.md"),
    ("edgar_sec/engine/xbrl/review/census_expectations.py", "2026-11-09-rp-partner-coverage-impl.md"),
    ("tests/engine/selection/test_predicates.py", "2008-03-31 is Q1"),
    ("tests/engine/selection/test_source.py", "December 2023 row"),
    ("tests/apps/client/financials/test_ttm_comparison.py", "closing TTM 620 at 2024-09-30"),
)

# Archive directory conventions: a path under a finished-plan
# directory, a run-log or dated-log directory, or a date-named
# directory is a record, not a living document.
ARCHIVE_DIR_NAMES = frozenset(
    {"run-log", "run-logs", "run_log", "run_logs", "dated-logs", "dated_logs"}
)
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_MONTH = rf"(?:{MONTH_PATTERN})"
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
SLASH_DATE_RE = re.compile(r"\b\d{4}/\d{2}/\d{2}\b")
MONTH_DAY_YEAR_RE = re.compile(
    rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE
)
DAY_MONTH_YEAR_RE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}\b", re.IGNORECASE
)
MONTH_YEAR_RE = re.compile(rf"\b{_MONTH}\s+\d{{4}}\b", re.IGNORECASE)
PAREN_YEAR_RE = re.compile(r"\(\s*(?:19|20)\d{2}\s*\)")

DATE_LEGS = (
    ("iso-date", ISO_DATE_RE),
    ("iso-date", SLASH_DATE_RE),
    ("month-date", MONTH_DAY_YEAR_RE),
    ("month-date", DAY_MONTH_YEAR_RE),
    ("month-date", MONTH_YEAR_RE),
    ("date-parenthetical", PAREN_YEAR_RE),
)


def _is_archive(relpath: str) -> bool:
    parts = Path(relpath).parts
    dirs = parts[:-1]
    for index, part in enumerate(dirs):
        if part in ARCHIVE_DIR_NAMES or DATE_DIR_RE.match(part):
            return True
        if part == ".plans" and index + 1 < len(dirs):
            if dirs[index + 1] == "finished":
                return True
    return False


def _in_population(path: Path) -> bool:
    return path.suffix in ALL_SUFFIXES or path.name in CONFIG_NAMES


def _walk(root: Path) -> list[Path]:
    """Walk-mode candidates when no tracked listing is available."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _in_population(path):
            continue
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts[:-1]):
            continue
        found.append(path)
    return found


def population(root: Path) -> list[Path]:
    """Tracked living docs and code files, archives excluded."""
    tracked = tracked_paths(root)
    if tracked is not None:
        candidates = [root / name for name in tracked]
    else:
        candidates = _walk(root)
    files: list[Path] = []
    for path in candidates:
        if not _in_population(path) or not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        if relpath == VOCABULARY_HOME or _is_archive(relpath):
            continue
        if path.suffix in DOC_SUFFIXES and relpath.startswith(DOC_EXCLUDED_PREFIXES):
            continue
        files.append(path)
    return files


def _is_sanctioned(relpath: str, text: str) -> bool:
    return any(
        path == relpath and fragment in text for path, fragment in _SANCTIONED_SITES
    )


def _date_findings(relpath: str, lineno: int, text: str) -> list[ScannerFinding]:
    if _is_sanctioned(relpath, text):
        return []
    findings: list[ScannerFinding] = []
    for leg, pattern in DATE_LEGS:
        if pattern.search(text):
            findings.append(
                finding(
                    "living-dates",
                    relpath,
                    lineno,
                    f"date form ({leg}) in a living document or comment"
                    " (content withheld)",
                    "State the present truth without the date; dates as data"
                    " belong in literals and records.",
                )
            )
    return findings


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _find_span_close(line: str, start: int, run: int) -> int | None:
    """End index of the backtick run of exactly ``run`` closing a span."""
    index = start
    length = len(line)
    while index < length:
        if line[index] != "`":
            index += 1
            continue
        run_end = index
        while run_end < length and line[run_end] == "`":
            run_end += 1
        if run_end - index == run:
            return run_end
        index = run_end
    return None


def _mask_code_spans(line: str) -> str:
    """The line with inline code spans blanked to spaces.

    An unmatched backtick run is literal text and stays;
    length is preserved, so columns and line numbers hold.
    """
    chars = list(line)
    index = 0
    length = len(line)
    while index < length:
        if line[index] != "`":
            index += 1
            continue
        run_end = index
        while run_end < length and line[run_end] == "`":
            run_end += 1
        close = _find_span_close(line, run_end, run_end - index)
        if close is None:
            index = run_end
            continue
        for position in range(index, close):
            chars[position] = " "
        index = close
    return "".join(chars)


def _mask_doc_lines(text: str) -> list[str]:
    """Doc lines with fenced blocks and code spans blanked.

    Code inside a document is data, so it is blanked in
    place; prose still scans, and line numbers hold.
    """
    masked: list[str] = []
    fence_char = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence_char:
            masked.append("")
            if stripped.startswith(fence_char * 3):
                fence_char = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_char = stripped[0]
            masked.append("")
            continue
        masked.append(_mask_code_spans(line))
    return masked


def _scan_doc(root: Path, path: Path, text: str) -> list[ScannerFinding]:
    relpath = path.relative_to(root).as_posix()
    findings: list[ScannerFinding] = []
    for lineno, line in enumerate(_mask_doc_lines(text), start=1):
        findings.extend(_date_findings(relpath, lineno, line))
    return findings


def _python_surfaces(text: str) -> list[tuple[int, str]]:
    """(line, text) pairs for comments and docstring lines.

    Docstring lines pass through code-span masking: a date inside
    a docstring's code span is a literal, the doc form of data.
    """
    surfaces: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                surfaces.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return surfaces
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if not node.body or not isinstance(node.body[0], ast.Expr):
            continue
        value = node.body[0].value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        first = value.lineno
        last = value.end_lineno or first
        lines = text.splitlines()
        for lineno in range(first, last + 1):
            surfaces.append((lineno, _mask_code_spans(lines[lineno - 1])))
    return surfaces


def _script_surfaces(text: str) -> list[tuple[int, str]]:
    """(line, text) pairs for TS/JS comments, lexed by hand.

    Strings and template literals are skipped so dates held as
    data never read as comments; a date in a regex does.
    """
    surfaces: list[tuple[int, str]] = []
    index = 0
    lineno = 1
    length = len(text)
    while index < length:
        char = text[index]
        nxt = text[index + 1] if index + 1 < length else ""
        if char == "\n":
            lineno += 1
            index += 1
        elif char == "/" and nxt == "/":
            end = text.find("\n", index)
            if end == -1:
                end = length
            surfaces.append((lineno, text[index:end]))
            index = end
        elif char == "/" and nxt == "*":
            end = text.find("*/", index + 2)
            if end == -1:
                end = length - 2
            segment = text[index : end + 2]
            for offset, line in enumerate(segment.splitlines()):
                surfaces.append((lineno + offset, line))
            lineno += segment.count("\n")
            index = end + 2
        elif char in "'\"`":
            quote = char
            index += 1
            while index < length:
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == "\n":
                    lineno += 1
                if text[index] == quote:
                    index += 1
                    break
                index += 1
        else:
            index += 1
    return surfaces


def _scan_code(root: Path, path: Path, text: str) -> list[ScannerFinding]:
    relpath = path.relative_to(root).as_posix()
    if path.suffix in PYTHON_SUFFIXES:
        surfaces = _python_surfaces(text)
    else:
        surfaces = _script_surfaces(text)
    findings: list[ScannerFinding] = []
    for lineno, surface in surfaces:
        findings.extend(_date_findings(relpath, lineno, surface))
    return findings


def _hash_comment_surfaces(text: str) -> list[tuple[int, str]]:
    """(line, comment) pairs for hash-comment config files.

    A comment runs from an unquoted ``#`` to end of line;
    quoted strings are data and start no comment.
    """
    surfaces: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        quote = ""
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\" and quote == '"':
                    index += 2
                    continue
                if char == quote:
                    if quote == "'" and line[index + 1 : index + 2] == "'":
                        index += 2
                        continue
                    quote = ""
                index += 1
                continue
            if char in "'\"":
                quote = char
                index += 1
                continue
            if char == "#":
                surfaces.append((lineno, line[index:]))
                break
            index += 1
    return surfaces


def _scan_config(root: Path, path: Path, text: str) -> list[ScannerFinding]:
    relpath = path.relative_to(root).as_posix()
    if path.name in CONFIG_NAMES:
        # Gitignore syntax: a comment is a line whose first
        # character is a hash; a hash later in a line is
        # pattern content, not a comment.
        surfaces = [
            (lineno, line)
            for lineno, line in enumerate(text.splitlines(), start=1)
            if line.startswith("#")
        ]
    else:
        surfaces = _hash_comment_surfaces(text)
    findings: list[ScannerFinding] = []
    for lineno, surface in surfaces:
        findings.extend(_date_findings(relpath, lineno, surface))
    return findings


def scan_tree(root: Path) -> list[ScannerFinding]:
    """Scan one tree root and return the living-dates findings."""
    findings: list[ScannerFinding] = []
    for path in population(root):
        text = _read_text(path)
        if text is None:
            continue
        if path.suffix in DOC_SUFFIXES:
            findings.extend(_scan_doc(root, path, text))
        elif path.name in CONFIG_NAMES or path.suffix in CONFIG_SUFFIXES:
            findings.extend(_scan_config(root, path, text))
        else:
            findings.extend(_scan_code(root, path, text))
    return findings


def scan_living_dates() -> list[ScannerFinding]:
    """Report date forms in the current tree's living surfaces."""
    return scan_tree(Path.cwd())


SCANNER = Scanner(
    name="living-dates",
    description="living documents and code comments carry no dates",
    run=scan_living_dates,
)
