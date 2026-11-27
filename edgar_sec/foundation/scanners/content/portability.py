"""Scanner flagging tracked references a fresh clone cannot resolve.
Flags absolute or home-anchored paths, specific untracked plan files and
dated memory logs in tracked text outside the test tree (test specimens
seed such strings as inputs), and tracked code naming another repository
when a repo set is provisioned. Exemptions: exception directives in the
registry files named in ``EXCEPTION_FILES``."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..base import Scanner, ScannerFinding
from ..files import CODE_SUFFIXES
from ..lines import finding
from .denylist import population

REPO_SET_ENV_VAR = "STARTER_REPO_SET_FILE"
DEFAULT_REPO_SET_PATH = Path("var/config/repo-set.txt")

# Files that may declare portability-exception directives.
# Empty today: the tree needs none. Add a path here only
# together with the directive it relies on, in that file.
EXCEPTION_FILES: tuple[str, ...] = ()

_MARKER = "portability" + "-exception:"
EXCEPTION_DIRECTIVE_RE = re.compile(re.escape(_MARKER) + r"\s*(\S+)\s+—\s*(\S.*)$")

_BOUNDARY = r"(?<![\w/.-])"
_PATH_TAIL = r"[\w.-]+(?:/[\w.-]+)*"

ABS_HOME_RE = re.compile(_BOUNDARY + "/home/" + _PATH_TAIL)
ABS_USERS_RE = re.compile(_BOUNDARY + "/Users/" + _PATH_TAIL)
ABS_OPT_RE = re.compile(_BOUNDARY + "/opt/" + _PATH_TAIL)
ABS_TMP_RE = re.compile(_BOUNDARY + "/tmp/" + _PATH_TAIL)
DRIVE_RE = re.compile(
    r"(?<![\w])[A-Za-z]" + ":" + r"\\|(?<=[\s\"'(=])[A-Za-z]" + ":" + "/"
)
TILDE_RE = re.compile(_BOUNDARY + r"~/[\w.-][\w./-]*")

PLAN_FILE_RE = re.compile(
    r"\.plans/(?!finished/)[\w.-]+\.(?:md|json|ya?ml)"
    r"|\.plans/(?!finished/)[\w.-]+/"
    r"|\.plans/finished/[\w.-]+\.(?:md|json|ya?ml)"
)
DATED_MEMORY_RE = re.compile(_BOUNDARY + r"memory/\d{4}-\d{2}-\d{2}")

GENERIC_LEGS = (
    ("portability/abs-path", ABS_HOME_RE),
    ("portability/abs-path", ABS_USERS_RE),
    ("portability/abs-path", ABS_OPT_RE),
    ("portability/abs-path", ABS_TMP_RE),
    ("portability/abs-path", DRIVE_RE),
    ("portability/home-path", TILDE_RE),
    ("portability/untracked-ref", PLAN_FILE_RE),
    ("portability/untracked-ref", DATED_MEMORY_RE),
)


def _read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _declared_exceptions(relpath: str, lines: list[str]) -> set[str]:
    """Exact strings this file's directives exempt, if any."""
    if relpath not in EXCEPTION_FILES:
        return set()
    found = set()
    for line in lines:
        match = EXCEPTION_DIRECTIVE_RE.search(line)
        if match:
            found.add(match.group(1))
    return found


def _scan_file(root: Path, path: Path) -> list[ScannerFinding]:
    relpath = path.relative_to(root).as_posix()
    lines = _read_lines(path)
    if lines is None:
        return []
    exceptions = _declared_exceptions(relpath, lines)
    findings: list[ScannerFinding] = []
    for lineno, line in enumerate(lines, start=1):
        if relpath not in EXCEPTION_FILES and EXCEPTION_DIRECTIVE_RE.search(line):
            findings.append(
                finding(
                    "portability",
                    relpath,
                    lineno,
                    "portability/exception-misuse: exception directive"
                    " in a non-registry file",
                    "Directives live only in the files named in the"
                    " scanner's EXCEPTION_FILES registry.",
                )
            )
        for rule, pattern in GENERIC_LEGS:
            for match in pattern.finditer(line):
                if match.group(0) in exceptions:
                    continue
                findings.append(
                    finding(
                        "portability",
                        relpath,
                        lineno,
                        f"{rule}: non-portable reference (content withheld)",
                        "Reference only what a fresh clone of this"
                        " repository resolves.",
                    )
                )
    return findings


def _resolve_repo_set(root: Path) -> Path | None:
    """The provisioned repo-set file, if one resolves."""
    raw = os.environ.get(REPO_SET_ENV_VAR)
    if raw:
        return Path(raw)
    default = root / DEFAULT_REPO_SET_PATH
    if default.is_file():
        return default
    return None


def _load_repo_set(root: Path) -> list[str]:
    """The provisioned sibling-repo names; empty when none resolve."""
    repo_set_path = _resolve_repo_set(root)
    if repo_set_path is None:
        return []
    try:
        lines = repo_set_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def _code_population(root: Path) -> list[Path]:
    """Tracked code files, the scanner mirror tests excluded."""
    return [path for path in population(root) if path.suffix in CODE_SUFFIXES]


def _repo_ref_findings(root: Path) -> list[ScannerFinding]:
    """Tracked code naming another repository in the provisioned set."""
    names = [name for name in _load_repo_set(root) if name != root.name]
    if not names:
        return []
    alternation = "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)
    )
    pattern = re.compile(r"(?<![\w-])(" + alternation + r")(?![\w-])")
    findings: list[ScannerFinding] = []
    for path in _code_population(root):
        relpath = path.relative_to(root).as_posix()
        lines = _read_lines(path)
        if lines is None:
            continue
        exceptions = _declared_exceptions(relpath, lines)
        for lineno, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                if match.group(0) in exceptions:
                    continue
                findings.append(
                    finding(
                        "portability",
                        relpath,
                        lineno,
                        "portability/external-repo-ref: tracked code"
                        f" names external repository '{match.group(1)}'",
                        "Reference repositories through registry or"
                        " config data, never literals in code.",
                    )
                )
    return findings


def scan_tree(root: Path) -> list[ScannerFinding]:
    """Scan one tree root and return the portability findings."""
    findings: list[ScannerFinding] = []
    for path in population(root):
        relpath = path.relative_to(root).as_posix()
        if relpath.startswith("tests/"):
            continue
        findings.extend(_scan_file(root, path))
    findings.extend(_repo_ref_findings(root))
    return findings


def scan_portability() -> list[ScannerFinding]:
    """Report non-portable references in the current tree."""
    return scan_tree(Path.cwd())


SCANNER = Scanner(
    name="portability",
    description="tracked text references only what a fresh clone resolves",
    run=scan_portability,
)
