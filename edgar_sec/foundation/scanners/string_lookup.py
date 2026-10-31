"""Policy scanner banning semantic string searches over XBRL concept names.

Equivalence is computed from atom coordinates, never by searching a concept
name string; residuals are a vocabulary-gap report, never a decision input.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .base import Scanner, ScannerFinding
from .files import discover_python_files

#: Only the XBRL engine and its client surface decide concept meaning.
_SCOPE_PREFIXES = ("edgar_sec/engine/xbrl/", "edgar_sec/apps/client/")

#: String-search calls that decide meaning when aimed at a name expression.
_SEARCH_CALLS = frozenset({"startswith", "endswith", "find", "index"})

#: A receiver whose identifiers tokenize to one of these carries a concept
#: name or local name, so a string search over it is a semantic lookup.
#: Tokenized, not substring-matched: ``fname`` is a filename, not a name.
_NAME_TOKENS = frozenset(
    {
        "qname",
        "concept",
        "local",
        "member",
        "axis",
        "role",
        "label",
        "unit",
        "head",
        "mod",
        "name",
    }
)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def _is_nameish(receiver: str) -> bool:
    """True when any identifier in ``receiver`` tokenizes to a name token."""
    for identifier in _IDENTIFIER_RE.findall(receiver):
        for part in identifier.split("_"):
            for token in _CAMEL_RE.findall(part):
                if token.lower() in _NAME_TOKENS:
                    return True
    return False


#: Modules where a ``residuals`` read is the sanctioned flow, each an audited
#: claim: the tokenizer uses residuals only to order atom-equal equivalents,
#: and equivalence itself is atom equality, which no residual can change.
_RESIDUAL_HOMES = frozenset(
    {
        "edgar_sec/engine/xbrl/solve/concept_table.py",
        "edgar_sec/engine/xbrl/solve/tokenizer.py",
        "edgar_sec/apps/client/facts.py",
    }
)
_RESIDUAL_HOME_PREFIXES = (
    "edgar_sec/engine/xbrl/normalize/",
    "edgar_sec/engine/xbrl/discovery/",
)

#: The Atom constructor normalizes its own symbol-family prefix; atom symbols
#: are the coordinates themselves, not names being looked up.
_SYMBOL_PATHS = frozenset({"edgar_sec/engine/xbrl/schema/atoms.py"})


def _in_scope(normalized: str) -> bool:
    return normalized.startswith(_SCOPE_PREFIXES)


def _residual_home(normalized: str) -> bool:
    return normalized in _RESIDUAL_HOMES or normalized.startswith(
        _RESIDUAL_HOME_PREFIXES
    )


def _finding(path: str, line: int, message: str, hint: str) -> ScannerFinding:
    return ScannerFinding(
        scanner="string-lookup",
        source="static",
        path=path,
        line=line,
        message=message,
        hint=hint,
    )


def scan_string_lookup() -> list[ScannerFinding]:
    """Scan the XBRL engine and client for name-string searches and stray residuals."""
    findings: list[ScannerFinding] = []
    for path_str in discover_python_files():
        normalized = path_str.replace("\\", "/")
        if not _in_scope(normalized):
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path_str)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                call = node.func
                if call.attr not in _SEARCH_CALLS:
                    continue
                if normalized in _SYMBOL_PATHS:
                    continue
                receiver = ast.unparse(call.value)
                if _is_nameish(receiver):
                    findings.append(
                        _finding(
                            path_str,
                            node.lineno,
                            f"string search .{call.attr}() on name expression {receiver}",
                            "parse the qname (split_concept_qname) and decide on "
                            "atom coordinates or declared taxonomy data",
                        )
                    )
            elif isinstance(node, ast.Attribute) and node.attr == "residuals":
                if not _residual_home(normalized):
                    findings.append(
                        _finding(
                            path_str,
                            node.lineno,
                            "residuals consumed outside their sanctioned homes",
                            "residuals are a vocabulary-gap report: report them "
                            "(normalize, concept table, facts carriage, discovery "
                            "mining) but never decide a result from them",
                        )
                    )
    return findings


SCANNER = Scanner(
    name="string-lookup",
    description="flags string searches on XBRL name expressions and residuals consumed outside their sanctioned homes",
    run=scan_string_lookup,
)

__all__ = ["SCANNER", "scan_string_lookup"]
