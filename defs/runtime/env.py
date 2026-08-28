"""Environment and .env-based setting resolution.

Settings resolve in order: direct process environment, then the repository
``.env`` file (default ``.env``, overridable via ``DOTENV_PATH``).
Secrets never come from tracked configuration; ``.env`` is git-ignored.

This module is application-agnostic: it owns dotenv parsing, precedence,
dotenv-path selection, safe rendering, and the modified-file environment
access scanner. It contains no application-specific environment names; new
settings are declared in ``defs/runtime/settings/`` (or a phase settings
module) and resolved through :mod:`defs.runtime.settings`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_DOTENV_PATH = ".env"


def load_dotenv(path: str | os.PathLike[str] = DEFAULT_DOTENV_PATH) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping without mutating the environment.

    Supports blank lines, ``#`` comments, an optional ``export `` prefix,
    and matching single/double quotes around values. A missing or unreadable
    file yields an empty mapping.
    """
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def get_env(
    name: str, default: str = "", *, path: str | os.PathLike[str] | None = None
) -> str:
    """Resolve one setting: direct environment first, then the ``.env`` file.

    An empty direct-environment value is treated as unset so a ``.env``
    fallback still applies. ``path=None`` uses ``DOTENV_PATH`` when set,
    otherwise ``.env`` relative to the current working directory.
    """
    value = os.environ.get(name)
    if value:
        return value
    dotenv_path = (
        path if path is not None else os.environ.get("DOTENV_PATH", DEFAULT_DOTENV_PATH)
    )
    return load_dotenv(dotenv_path).get(name, default)


def render_dotenv_value(value: str) -> str:
    """Quote one value for safe inclusion in a ``.env`` file.

    Values containing whitespace, quotes, or comment characters are wrapped
    in double quotes with embedded double quotes escaped; other values pass
    through unchanged.
    """
    if value == "" or not re.search(r"[\s'\"#]", value):
        return value
    escaped = value.replace('"', '\\"')
    return '"' + escaped + '"'


# --- Modified-file environment access scanner --------------------------------
#
# Generic policy: new direct environment access and ad-hoc dotenv parsing is
# only permitted inside the documented environment/path boundary (this module
# and the settings registry); application-specific environment-name constants
# belong in settings-spec modules, nowhere else. Paths under a ``tests``
# directory are exempt because suites legitimately inject environment values.

_ENV_ACCESS_RE = re.compile(r"\bos\.environ\b|\benviron\.get\b|\bos\.getenv\b")
_DOTENV_PARSE_RE = re.compile(r"\bload_dotenv\s*\(")
# A variable assigned a string that itself looks like an environment name,
# e.g. ``LEGACY_INPUT = "SEC_USER_AGENT"`` — ordinary constants are ignored.
_ENV_NAME_CONSTANT_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]*\s*=\s*([\"'])([A-Z][A-Z0-9_]+)\1"
)
# Broad -G filter so git only surfaces candidate lines; the per-line patterns
# above make the final determination.
_CANDIDATE_RE = r"os\.environ|os\.getenv|environ\.get|load_dotenv|[A-Z][A-Z0-9_]+ *="

_ALLOWED_PREFIXES = (
    "defs/runtime/env.py",
    "defs/runtime/settings/",
    "defs/runtime/checks.py",
)


def _is_allowed(path: str) -> bool:
    if path.startswith(_ALLOWED_PREFIXES):
        return True
    return "/tests/" in f"/{path}"


def _match_line(path: str, line_number: int, text: str, source: str) -> list:
    if _is_allowed(path):
        return []
    from .checks import ScannerFinding

    findings: list[ScannerFinding] = []
    if _DOTENV_PARSE_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="environment-access",
                source=source,
                path=path,
                line=line_number,
                message="ad-hoc dotenv parsing outside defs.runtime.env",
                hint="resolve settings through defs.runtime.settings or get_env",
            )
        )
    if _ENV_ACCESS_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="environment-access",
                source=source,
                path=path,
                line=line_number,
                message="direct environment access outside the generic env layer",
                hint="declare the setting in a settings spec and resolve via defs.runtime.settings",
            )
        )
    if _ENV_NAME_CONSTANT_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="environment-access",
                source=source,
                path=path,
                line=line_number,
                message="application environment-name constant declared outside a settings module",
                hint="derive names with defs.runtime.settings.environment_name instead",
            )
        )
    return findings


def scan_modified_environment_access(
    repo_root: str | os.PathLike[str] | None = None,
) -> list:
    """Scan staged, unstaged, and untracked Python changes for env access.

    Tracked files are scanned from both staged and unstaged patch content so
    one version cannot hide behind the other; untracked files are read
    directly because ``git diff`` omits them. Deleted files need no
    working-tree scan. Returns structured findings; empty means clean.
    """
    from .scanners.engine import scan_patch_and_untracked

    return scan_patch_and_untracked(
        candidate_re=_CANDIDATE_RE,
        match_line_fn=_match_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = [
    "DEFAULT_DOTENV_PATH",
    "get_env",
    "load_dotenv",
    "render_dotenv_value",
    "scan_modified_environment_access",
]
